"""Serum 2 effect racks -> Vital effect settings.

Serum 2 stores three racks (`FXRack0` is the main chain, 1 and 2 are FX
buses) as ordered lists of modules::

    {"type": 5, "FXComp": {"plainParams": {...}}, "kUIParamMixOrGain": 0.0}

`plainParams` is either the string "default" or a map of the parameters that
differ from the module defaults, so the defaults below matter.  Units are the
ones Serum displays: Hz, ms, %, dB, seconds -- with a few knob-position
parameters (compressor threshold, filter cutoff, distortion cutoff) that use
the laws measured on Serum 1 (see fx_common).

Vital owns exactly one instance of each effect, so the first module of a kind
wins and later ones are reported as `resource-conflict`.  Every dropped or
approximated control produces a `conv.note(...)`; see docs/serum2_fx_survey.md
for the corpus survey behind each mapping.
"""

from __future__ import annotations

import math

from . import fx_common as fx
from .fx_common import SYNC_FREE, SYNC_TEMPO, clamp01, hz_to_note, log2_hz

# Serum 2 module keys (the dict key inside a rack entry) by rack `type`.
FX_TYPE_NAMES = {
    0: "FXDistortion",
    1: "FXFlanger",
    2: "FXPhaser",
    3: "FXChorus",
    4: "FXDelay",
    5: "FXComp",
    6: "FXReverb",
    7: "FXEQ",
    8: "FXFilter",
    9: "FXHyperD",
    10: "FXBode",
    11: "FXConv",
    12: "FXUtils",
    13: "FXSplit",
    14: "FXSplit3",
    15: "FXSplitMS",
}

# Serum's filter cutoff knob spans roughly MIDI note 0..135 (same as the
# voice filters); the distortion module's cutoff spans 0..128 (measured).
FILTER_CUTOFF_MAX_NOTE = 135.0
DIST_CUTOFF_MAX_NOTE = 128.0

# Serum 1's chorus depth tops out at 26 ms; Serum 2 keeps the same knob.
CHORUS_DEPTH_MAX_MS = 26.0

# Module defaults (only non-default values are stored).  Values marked
# "assumed" are inferred from the survey (most common stored value / the
# user guide); everything else is a plain unit default.
S2_FX_DEFAULTS: dict[str, dict[str, float | str]] = {
    "FXDistortion": {
        "kParamMode": "kTube", "kParamDrive": 0.0, "kParamWet": 100.0, "kParamPrePost": 0.0,
        "kParamLPHP": 0.0, "kParamFreq": 0.5, "kParamBW": 1.0, "kParamEnable": 1.0,
    },
    "FXFlanger": {
        "kParamRate": 0.5, "kParamBeatSync": 0.0, "kParamDepth": 50.0, "kParamFeedback": 50.0,
        "kParamWidth": 90.0, "kParamWet": 50.0, "kParamEnable": 1.0,
    },
    "FXPhaser": {
        "kParamRate": 0.5, "kParamBeatSync": 0.0, "kParamDepth": 50.0, "kParamDepth2": 0.5,
        "kParamFeedback": 50.0, "kParamFreq": 400.0, "kParamNumPoles": 6.0, "kParamWidth": 90.0,
        "kParamWet": 50.0, "kParamEnable": 1.0,
    },
    "FXChorus": {
        "kParamRate": 0.25, "kParamBeatSync": 0.0, "kParamDelay": 5.0, "kParamDelay2": 10.0,
        "kParamDepth": 4.0, "kParamFeedback": 0.0, "kParamFilt": 20000.0, "kParamFiltMode": 0.0,
        "kParamWet": 50.0, "kParamEnable": 1.0,
    },
    "FXDelay": {
        "kParamBeatSync": 1.0, "kParamMode": 0.0, "kParamTimeL": 0.08316586760018929,
        "kParamTimeR": 0.08316586760018929, "kParamOffsetL": 1.0, "kParamOffsetR": 1.0,
        "kParamLink": 0.0, "kParamFeedback": 50.0, "kParamFreq": 1000.0, "kParamBW": 3.0,
        "kParamWet": 30.0, "kParamEnable": 1.0,
    },
    "FXComp": {
        "kParamAttack": 10.0, "kParamRelease": 100.0, "kParamThresh": 0.25, "kParamRatio": 2.0,
        "kParamMakeup": 1.0, "kParamMultiband": 0.0, "kParamWet": 100.0, "kParamRatioBelow": 0.0,
        "kParamGain0": 0.0, "kParamGain1": 0.0, "kParamGain2": 0.0,
        "kParamThreshUD0": 100.0, "kParamThreshUD1": 100.0, "kParamThreshUD2": 100.0,
        "kParamEnable": 1.0,
    },
    "FXReverb": {
        "kParamType": "kPlate", "kParamSize": 50.0, "kParamWet": 30.0, "kParamWidth": 100.0,
        "kParamFreq": 0.0, "kParamFreqB": 0.0, "kParamFreqC": 0.0, "kParamPreDelay": 0.0,
        "kParamFeedback": 0.0, "kParamEnable": 1.0,
    },
    "FXEQ": {
        "kParamFreq1": 200.0, "kParamFreq2": 2000.0, "kParamGain1": 0.0, "kParamGain2": 0.0,
        "kParamReso1": 43.33, "kParamReso2": 43.33, "kParamType1": 0.0, "kParamType2": 0.0,
        "kParamEnable": 1.0,
    },
    "FXFilter": {
        "kParamType": "MgL6", "kParamFreq": 1.0, "kParamReso": 10.0, "kParamDrive": 0.0,
        "kParamVar": 50.0, "kParamWet": 100.0, "kParamEnable": 1.0,
    },
    "FXHyperD": {
        "kParamRate": 40.0, "kParamDetune": 25.0, "kParamUnison": 4.0, "kParamRetrig": 0.0,
        "kParamWet": 50.0, "kParamDimESize": 0.0, "kParamDimEWet": 0.0, "kParamEnable": 1.0,
    },
    "FXConv": {"kParamWet": 50.0, "kParamSize": 100.0, "kParamTone": 0.0, "kParamEnable": 1.0},
    "FXUtils": {"kParamHPF": 0.0, "kParamLPF": 20000.0, "kParamWidth": 100.0, "kParamBalance": 0.0, "kParamEnable": 1.0},
    "FXBode": {"kParamEnable": 1.0},
}

# Serum 2 EQ band types.
EQ_SHELF, EQ_PEAK, EQ_PASS = 0, 1, 2

# Serum 2 delay modes.
DELAY_NORMAL, DELAY_PING_PONG, DELAY_TAP = 0, 1, 2

# Vital delay styles.
STYLE_MONO, STYLE_STEREO, STYLE_PING_PONG, STYLE_MID_PING_PONG = 0, 1, 2, 3


class _Module:
    """One rack entry with default-filled parameter access."""

    def __init__(self, entry: dict, position: int):
        self.entry = entry
        self.position = position
        self.type = entry.get("type")
        keys = [k for k, v in entry.items() if isinstance(v, dict) and k.startswith("FX")]
        self.name = keys[0] if keys else FX_TYPE_NAMES.get(self.type, f"FXType{self.type}")
        body = entry.get(self.name) if keys else None
        self.body = body if isinstance(body, dict) else {}
        params = self.body.get("plainParams")
        self.params: dict = params if isinstance(params, dict) else {}
        self.defaults = S2_FX_DEFAULTS.get(self.name, {})

    @property
    def short(self) -> str:
        return self.name[2:] if self.name.startswith("FX") else self.name

    def get(self, key: str, fallback: float | None = None) -> float:
        value = self.params.get(key)
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            return float(value)
        default = self.defaults.get(key, fallback)
        return float(default) if isinstance(default, (int, float)) else 0.0

    def text(self, key: str) -> str:
        value = self.params.get(key)
        if isinstance(value, str):
            return value
        default = self.defaults.get(key, "")
        return default if isinstance(default, str) else ""

    def has(self, key: str) -> bool:
        return key in self.params

    @property
    def enabled(self) -> bool:
        return self.get("kParamEnable", 1.0) > 0.5


class _RackState:
    """Which Vital effects (and EQ bands) have been claimed so far."""

    def __init__(self, conv):
        self.conv = conv
        self.used: dict[str, str] = {}
        self.eq_bands: dict[str, str] = {}
        self.chain: list[str] = []

    def claim(self, vital: str, module: _Module) -> bool:
        owner = self.used.get(vital)
        if owner is not None:
            self.conv.note(
                f"resource-conflict: second {module.short} module (rack slot {module.position + 1}) "
                f"dropped, Vital's {vital} already holds {owner}"
            )
            return False
        self.used[vital] = module.short
        self.chain.append(vital)
        return True

    def claim_band(self, band: str, label: str) -> bool:
        if band in self.eq_bands:
            self.conv.note(f"resource-conflict: {label} dropped, Vital's EQ {band} band already holds {self.eq_bands[band]}")
            return False
        self.eq_bands[band] = label
        if "eq" not in self.used:
            self.used["eq"] = label
            self.chain.append("eq")
        return True


def _level_out_note(conv, module: _Module) -> None:
    if module.has("kParamLevelOut") and abs(module.get("kParamLevelOut") - 0.5) > 0.02:
        conv.note(f"unsupported: {module.short} output LEVEL dropped (Vital effects have no output trim)")


# --------------------------------------------------------------------------
# individual modules
# --------------------------------------------------------------------------


def _distortion(conv, m: _Module, state: _RackState) -> None:
    if not state.claim("distortion", m):
        return
    mode = m.text("kParamMode") or "kTube"
    # Same drive law as Serum 1 (the Serum 2 tube fixtures match within 0.4 dB).
    vital_type, drive_db, exact = fx.dist_settings(mode, clamp01(m.get("kParamDrive") / 100.0))
    conv.set("distortion_on", 1.0)
    conv.set("distortion_type", vital_type)
    conv.set("distortion_drive", drive_db)
    conv.set("distortion_mix", fx.serum_wet_gain(clamp01(m.get("kParamWet") / 100.0)))
    key = fx.normalise_dist_name(mode)
    if key in fx.DIST_MODES_WITHOUT_COUNTERPART:
        conv.note(f"unsupported: distortion mode {mode} has no Vital waveshaper; substituted soft clip")
    elif not exact:
        conv.note(f"approximation: distortion mode {mode} mapped onto Vital type {vital_type}")
    if key in ("xshaper", "xshaperasym") and m.entry.get("flex"):
        conv.note("unsupported: X-Shaper custom waveshape curves dropped")
    if m.has("kParamNumStages"):
        conv.note("unsupported: distortion STAGES (kParamNumStages) dropped")

    order = int(round(m.get("kParamPrePost")))
    conv.set("distortion_filter_order", float(max(0, min(2, order))))
    if order:
        conv.set("distortion_filter_cutoff", DIST_CUTOFF_MAX_NOTE * clamp01(m.get("kParamFreq")))
        conv.set("distortion_filter_blend", 2.0 * clamp01(m.get("kParamLPHP") / 100.0))
        bw = m.get("kParamBW")
        conv.set("distortion_filter_resonance", 1.0 - clamp01((bw - 0.075) / 7.5))
        conv.note("approximation: distortion filter Q derived from Serum's bandwidth knob")
    _level_out_note(conv, m)


def _mod_rate(conv, prefix: str, m: _Module, freq_lo: float, freq_hi: float) -> None:
    rate = m.get("kParamRate")
    if m.get("kParamBeatSync") > 0.5:
        # The stored Hz is the knob position (20 n^4); synced, Serum steps that
        # position through the same 31-entry ladder as Serum 1 (checked by rendering).
        sync, index = fx.fx_rate_sync(fx.fx_rate_step_from_hz(rate))
        conv.set(f"{prefix}_sync", float(sync))
        conv.set(f"{prefix}_tempo", float(max(0, min(10, index))))
        if index > 10:
            conv.note(f"approximation: {prefix} synced rate 1/32 clamped to Vital's 1/16")
    else:
        conv.set(f"{prefix}_sync", SYNC_FREE)
        conv.set(f"{prefix}_frequency", max(freq_lo, min(freq_hi, log2_hz(rate))))
        if rate < 2.0 ** freq_lo:
            conv.note(f"approximation: {prefix} rate {rate:.3f} Hz is below Vital's minimum, clamped")


def _flanger(conv, m: _Module, state: _RackState) -> None:
    if not state.claim("flanger", m):
        return
    conv.set("flanger_on", 1.0)
    conv.set("flanger_dry_wet", 0.5 * fx.serum_wet_gain(clamp01(m.get("kParamWet") / 100.0)))
    conv.set("flanger_mod_depth", clamp01(m.get("kParamDepth") / 100.0))
    conv.set("flanger_feedback", clamp01(m.get("kParamFeedback") / 100.0))
    conv.set("flanger_phase_offset", clamp01(fx.FLANGER_OFFSET_PER_180 * m.get("kParamWidth") / 180.0))
    conv.set("flanger_center", fx.FLANGER_CENTER_NOTE)   # Serum's flanger sits at ~16 ms (measured on Serum 1)
    _mod_rate(conv, "flanger", m, -5.0, 2.0)
    _level_out_note(conv, m)


def _phaser(conv, m: _Module, state: _RackState) -> None:
    if not state.claim("phaser", m):
        return
    conv.set("phaser_on", 1.0)
    conv.set("phaser_dry_wet", fx.serum_wet_gain(clamp01(m.get("kParamWet") / 100.0)))
    conv.set("phaser_feedback", clamp01(m.get("kParamFeedback") / 100.0))
    conv.set("phaser_center", hz_to_note(m.get("kParamFreq")))
    conv.set("phaser_mod_depth", 48.0 * clamp01(m.get("kParamDepth") / 100.0))
    conv.set("phaser_phase_offset", clamp01(fx.PHASER_OFFSET_PER_180 * m.get("kParamWidth") / 180.0))
    _mod_rate(conv, "phaser", m, -5.0, 2.0)
    if m.has("kParamNumPoles"):
        conv.note("unsupported: phaser POLES count dropped (Vital's phaser has a fixed stage count)")
    if m.has("kParamDepth2"):
        conv.note("unsupported: phaser DEPTH 2 (stage offset) dropped")
    _level_out_note(conv, m)


def _chorus(conv, m: _Module, state: _RackState) -> None:
    if not state.claim("chorus", m):
        return
    conv.set("chorus_on", 1.0)
    conv.set("chorus_voices", 2.0)  # Serum: two stereo pairs
    conv.set("chorus_dry_wet", fx.serum_wet_to_vital(clamp01(m.get("kParamWet") / 100.0)))
    for key, vital in (("kParamDelay", "chorus_delay_1"), ("kParamDelay2", "chorus_delay_2")):
        ms = max(m.get(key), 1.0)
        conv.set(vital, math.log2(ms / 1000.0))
        if m.get(key) < 1.0:
            conv.note(f"approximation: chorus {key[6:]} below 1 ms raised to Vital's 1 ms minimum")
    conv.set("chorus_mod_depth", clamp01(m.get("kParamDepth") / CHORUS_DEPTH_MAX_MS))
    conv.set("chorus_feedback", max(-0.95, min(0.95, m.get("kParamFeedback") / 100.0)))
    # Serum's chorus FILTER is a low-pass on the wet path (Vital: cutoff +/- spread, see fx_common.chorus_lowpass).
    cutoff, spread = fx.chorus_lowpass(m.get("kParamFilt"))
    conv.set("chorus_cutoff", cutoff)
    conv.set("chorus_spread", spread)
    if m.get("kParamFiltMode") > 0.5:
        # HPF mode: put Vital's high-pass at the knob frequency and open the low-pass.
        lp, hp = hz_to_note(20000.0), hz_to_note(max(20.0, m.get("kParamFilt")))
        conv.set("chorus_cutoff", (lp + hp) / 2.0)
        conv.set("chorus_spread", clamp01((lp - hp) / 2.0 / 96.0))
    _mod_rate(conv, "chorus", m, -6.0, 3.0)
    _level_out_note(conv, m)


def _delay(conv, m: _Module, state: _RackState) -> None:
    if not state.claim("delay", m):
        return
    conv.set("delay_on", 1.0)
    conv.set("delay_feedback", max(-1.0, min(1.0, m.get("kParamFeedback") / 100.0)))
    conv.set("delay_filter_cutoff", hz_to_note(m.get("kParamFreq")))
    conv.set("delay_filter_spread", clamp01((m.get("kParamBW") - 0.75) / 7.5))
    conv.note("approximation: delay filter width derived from Serum's Q (bandwidth) knob")

    mode = int(round(m.get("kParamMode")))
    linked = m.get("kParamLink") > 0.5
    time_l, time_r = m.get("kParamTimeL"), m.get("kParamTimeR")
    off_l, off_r = m.get("kParamOffsetL"), m.get("kParamOffsetR")
    if linked:
        time_r, off_r = time_l, off_l
    same = abs(time_l * off_l - time_r * off_r) <= 0.02 * max(time_l * off_l, 1e-6)

    wet_scale = 1.0
    if mode == DELAY_PING_PONG:
        conv.set("delay_style", STYLE_PING_PONG)
        wet_scale = 0.707   # Vital's ping-pong echoes sit 3 dB above its plain delay; Serum's do not
    elif mode == DELAY_TAP:
        conv.set("delay_style", STYLE_MONO)
        time_l, off_l = time_r, off_r
        conv.note("approximation: Tap->Delay mode mapped onto a mono delay using the right-channel time")
    else:
        conv.set("delay_style", STYLE_MONO if same else STYLE_STEREO)
    conv.set("delay_dry_wet", fx.serum_wet_to_vital(clamp01(m.get("kParamWet") / 100.0), wet_scale))

    synced = m.get("kParamBeatSync") > 0.5
    for prefix, seconds, offset in (("delay", time_l, off_l), ("delay_aux", time_r, off_r)):
        if synced:
            # The stored seconds are the knob position; Serum quantises it to a
            # division at render time (ladder measured with crafted fixtures).
            # The offset scalar multiplies that division: 1.5 dotted, 4/3 = the
            # triplet of the next longer division, anything else the nearest.
            sync, tempo = fx.synced_delay(fx.delay_seconds_to_tempo_index(seconds), offset)
            conv.set(f"{prefix}_sync", float(sync))
            conv.set(f"{prefix}_tempo", float(tempo))
        else:
            conv.set(f"{prefix}_sync", SYNC_FREE)
            conv.set(f"{prefix}_frequency", max(-2.0, min(9.0, math.log2(1.0 / max(seconds * offset, 1e-4)))))
    if m.has("kParamHQ"):
        conv.note("unsupported: delay High Quality switch dropped")
    _level_out_note(conv, m)


def _compressor(conv, m: _Module, state: _RackState) -> None:
    if not state.claim("compressor", m):
        return
    conv.set("compressor_on", 1.0)
    conv.set("compressor_mix", clamp01(m.get("kParamWet") / 100.0))
    conv.set("compressor_attack", fx.comp_time_to_vital(m.get("kParamAttack"), "attack"))
    conv.set("compressor_release", fx.comp_time_to_vital(m.get("kParamRelease"), "release"))

    thresh_db = fx.comp_threshold_db(m.get("kParamThresh"))
    ratio = fx.serum_ratio_to_vital(m.get("kParamRatio"))
    if m.get("kParamRatio") >= 1e5:
        conv.note("approximation: Serum's Limit mode mapped onto a 1:inf compressor ratio")
    makeup_db = 20.0 * math.log10(max(m.get("kParamMakeup"), 1e-3))
    below = clamp01(m.get("kParamRatioBelow"))

    multiband = m.get("kParamMultiband") > 0.5
    conv.set("compressor_enabled_bands", 0.0 if multiband else 3.0)
    bands = (("low", "0"), ("band", "1"), ("high", "2"))
    for band, suffix in bands:
        band_ratio = clamp01(m.get(f"kParamRatio{suffix}", ratio)) if m.has(f"kParamRatio{suffix}") else ratio
        band_below = clamp01(m.get(f"kParamRatioBelow{suffix}")) if m.has(f"kParamRatioBelow{suffix}") else below
        if multiband:
            # OTT-style: Vital's upward + downward compressor with the measured offsets;
            # the band L/M/H knobs (kParamThreshUD, 0..200 %) act as band level.
            values = fx.mb_band_settings(thresh_db, band_ratio, band)
            upper, lower = values["upper_threshold"], values["lower_threshold"]
            lower_ratio = max(values["lower_ratio"], band_below)
            gain = makeup_db + m.get(f"kParamGain{suffix}") + values["gain"] + fx.mb_band_gain_db(m.get(f"kParamThreshUD{suffix}"))
        else:
            upper = max(-80.0, min(0.0, thresh_db + fx.COMP_THRESHOLD_OFFSET_DB))
            lower = max(-80.0, upper - 10.0) if band_below > 0.0 else -80.0
            lower_ratio = band_below
            gain = makeup_db
        conv.set(f"compressor_{band}_upper_threshold", upper)
        conv.set(f"compressor_{band}_lower_threshold", lower)
        conv.set(f"compressor_{band}_upper_ratio", band_ratio)
        conv.set(f"compressor_{band}_lower_ratio", lower_ratio)
        conv.set(f"compressor_{band}_gain", max(-30.0, min(30.0, gain)))
    if multiband:
        if m.has("kParamXoverLow") or m.has("kParamXoverHi"):
            conv.note("unsupported: compressor crossover frequencies dropped (Vital's bands are fixed)")
    elif below > 0.0 or any(m.has(f"kParamRatioBelow{s}") for _, s in bands):
        conv.note("approximation: Serum's BELOW ratio mapped onto Vital's lower (upward) ratio, 10 dB under the threshold")
    if m.has("kParamDeadband0"):
        conv.note("unsupported: compressor deadband settings dropped")
    _level_out_note(conv, m)


def _reverb(conv, m: _Module, state: _RackState) -> None:
    if not state.claim("reverb", m):
        return
    kind = m.text("kParamType") or "kPlate"
    size = clamp01(m.get("kParamSize") / 100.0)
    conv.set("reverb_on", 1.0)
    wet_scale = fx.S2_PLATE_WET_SCALE if kind == "kPlate" else fx.REVERB_WET_SCALE   # the plate runs ~6 dB hot
    conv.set("reverb_dry_wet", fx.serum_wet_to_vital(clamp01(m.get("kParamWet") / 100.0), wet_scale))
    conv.set("reverb_size", size)
    # RT60 per type from crafted-fixture renders: plate and vintage follow SIZE
    # alone, hall/space a floor by SIZE overtaken by kParamDelay (its DECAY knob),
    # abyss both; Vital's decay_time is set to measure the same RT60.
    rt60 = fx.serum2_reverb_rt60(kind, m.get("kParamSize"), m.get("kParamDelay"))
    conv.set("reverb_decay_time", fx.vital_decay_for_rt60(rt60, size))
    conv.set("reverb_delay", max(0.0, min(0.3, m.get("kParamPreDelay"))))
    if m.get("kParamPreDelay") > 0.3:
        conv.note("approximation: reverb pre-delay clamped to Vital's 300 ms maximum")
    if m.get("kParamPreDelayBeatSync") > 0.5:
        conv.note("unsupported: reverb pre-delay tempo sync dropped")
    # LO CUT 50 % measures like Serum 1's 40 %, HI CUT 60 % like Serum 1's 45 %.
    pre_high, pre_low = fx.reverb_tone(0.75 * clamp01(m.get("kParamFreqB") / 100.0), 0.8 * clamp01(m.get("kParamFreq") / 100.0))
    conv.set("reverb_pre_high_cutoff", pre_high)
    conv.set("reverb_pre_low_cutoff", pre_low)
    conv.set("reverb_high_shelf_gain", 0.0)
    if kind not in ("kPlate", "kHall"):
        conv.note(f"approximation: Serum reverb type {kind[1:]} rendered with Vital's single reverb algorithm")
    if kind == "kSpace":
        conv.note("approximation: Space reverb could not be measured; Hall decay law used")
    if m.has("kParamWidth") and m.get("kParamWidth") < 99.0:
        conv.note("unsupported: reverb WIDTH dropped (Vital's reverb has no width control)")
    if m.has("kParamFeedback") and m.get("kParamFeedback") > 0.0:
        conv.note(f"unsupported: {kind[1:]} reverb FEEDBACK dropped")
    for key in ("kParamMode", "kParamVintageScale", "kParamVintageScaleB"):
        if m.has(key):
            conv.note(f"unsupported: reverb {kind[1:]} extra control {key[6:]} dropped")
    _level_out_note(conv, m)


def _eq_band(conv, state: _RackState, m: _Module, side: str) -> None:
    n = "1" if side == "low" else "2"
    kind = int(round(m.get(f"kParamType{n}")))
    hz, gain = m.get(f"kParamFreq{n}"), m.get(f"kParamGain{n}")
    # Q knob 0..100 %: Serum 1's law (peak / pass tables, shelves flat and shifted) is assumed to carry over.
    q = clamp01(m.get(f"kParamReso{n}") / 100.0)
    label = f"EQ {side} band ({kind})"
    if kind == EQ_PEAK:
        if state.claim_band("band", label):
            conv.set("eq_band_mode", 0.0)
            conv.set("eq_band_cutoff", hz_to_note(hz))
            conv.set("eq_band_gain", max(-15.0, min(15.0, gain)))
            conv.set("eq_band_resonance", fx.eq_resonance(q, "peak"))
        elif state.claim_band(side, label):
            conv.set(f"eq_{side}_mode", 0.0)
            conv.set(f"eq_{side}_cutoff", hz_to_note(hz) + fx.EQ_SHELF_SHIFT_SEMITONES)
            conv.set(f"eq_{side}_gain", max(-15.0, min(15.0, gain)))
            conv.set(f"eq_{side}_resonance", 0.0)
            conv.note(f"approximation: EQ {side} peak band rendered as a shelf (Vital's peak band was taken)")
        else:
            return
    else:
        if not state.claim_band(side, label):
            return
        conv.set(f"eq_{side}_mode", 1.0 if kind == EQ_PASS else 0.0)
        conv.set(f"eq_{side}_cutoff", hz_to_note(hz) if kind == EQ_PASS else hz_to_note(hz) + fx.EQ_SHELF_SHIFT_SEMITONES)
        conv.set(f"eq_{side}_gain", 0.0 if kind == EQ_PASS else max(-15.0, min(15.0, gain)))
        conv.set(f"eq_{side}_resonance", fx.eq_resonance(q, "pass" if kind == EQ_PASS else "shelf"))
    if abs(gain) > 15.0 and kind != EQ_PASS:
        conv.note(f"approximation: EQ gain {gain:+.1f} dB clamped to Vital's +/-15 dB")


def _eq(conv, m: _Module, state: _RackState) -> None:
    conv.set("eq_on", 1.0)
    _eq_band(conv, state, m, "low")
    _eq_band(conv, state, m, "high")
    _level_out_note(conv, m)


def _filter(conv, m: _Module, state: _RackState) -> None:
    if not state.claim("filter_fx", m):
        return
    name = m.text("kParamType") or "MgL6"
    mapping = fx.filter_type_to_vital(name)
    conv.set("filter_fx_on", 1.0)
    conv.set("filter_fx_model", float(mapping.model))
    conv.set("filter_fx_style", float(mapping.style))
    conv.set("filter_fx_cutoff", FILTER_CUTOFF_MAX_NOTE * clamp01(m.get("kParamFreq")))
    conv.set("filter_fx_resonance", clamp01(m.get("kParamReso") / 100.0))
    conv.set("filter_fx_drive", 20.0 * clamp01(m.get("kParamDrive") / 100.0))
    conv.set("filter_fx_mix", clamp01(m.get("kParamWet") / 100.0))
    if mapping.morph:
        conv.set("filter_fx_blend", 2.0 * clamp01(m.get("kParamVar") / 100.0))
        conv.note(f"approximation: FX filter {name} morph driven by Serum's VAR knob")
    else:
        conv.set("filter_fx_blend", float(mapping.blend))
        if m.has("kParamVar"):
            conv.note(f"unsupported: FX filter {name} VAR knob dropped")
    if not mapping.supported:
        conv.note(f"unsupported: FX filter type {name} has no Vital model; substituted an analog 12 dB low-pass")
    elif not mapping.exact:
        conv.note(f"approximation: FX filter type {name} mapped onto Vital {mapping.label}")
    if m.has("kParamStereo"):
        conv.note("unsupported: FX filter PAN (cutoff offset) dropped")
    _level_out_note(conv, m)


def _hyper(conv, m: _Module, state: _RackState) -> None:
    voices = int(round(m.get("kParamUnison")))
    chorus_busy = "chorus" in state.used
    if chorus_busy and "flanger" in state.used:
        conv.note("resource-conflict: Hyper/Dimension dropped, both chorus and flanger already used")
        return
    target = fx.hyper_to_chorus(
        conv,
        wet=clamp01(m.get("kParamWet") / 100.0),
        rate_hz=fx.hyper_rate_to_hz(m.get("kParamRate")),
        detune=clamp01(m.get("kParamDetune") / 100.0),
        voices=voices,
        retrig=m.get("kParamRetrig") > 0.5,
        dim_size=clamp01(m.get("kParamDimESize") / 100.0),
        dim_mix=clamp01(m.get("kParamDimEWet") / 100.0),
        chorus_busy=chorus_busy,
    )
    state.used[target] = m.short
    state.chain.append(target)
    for key in ("kParamLevelOut", "kParamDimELevelOut"):
        if m.has(key) and abs(m.get(key) - 0.5) > 0.02:
            conv.note("unsupported: Hyper/Dimension output LEVEL dropped")


def _convolution(conv, m: _Module, state: _RackState) -> None:
    ir = m.body.get("relativePathToIR") or m.body.get("pathToIR") or "embedded IR"
    if "reverb" in state.used:
        conv.note(f"resource-conflict: Convolve ({ir}) dropped, Vital's reverb already holds {state.used['reverb']}")
        return
    state.used["reverb"] = "Conv"
    state.chain.append("reverb")
    conv.set("reverb_on", 1.0)
    conv.set("reverb_dry_wet", clamp01(m.get("kParamWet") / 100.0))
    conv.set("reverb_size", clamp01(0.5 * m.get("kParamSize") / 100.0))
    if m.has("kParamDecay"):
        conv.set("reverb_decay_time", max(-6.0, min(6.0, math.log2(max(m.get("kParamDecay"), 0.02)))))
    if m.has("kParamPredelay"):
        conv.set("reverb_delay", max(0.0, min(0.3, m.get("kParamPredelay"))))
    tone = m.get("kParamTone")
    if tone < 0.0:
        conv.set("reverb_high_shelf_gain", -6.0 * clamp01(-tone / 100.0))
    if m.has("kParamDamping"):
        conv.set("reverb_high_shelf_cutoff", 128.0 * (1.0 - 0.5 * clamp01(m.get("kParamDamping") / 100.0)))
    conv.note(f"approximation: Convolve ({ir}) rendered with Vital's algorithmic reverb")
    for key, label in (("kParamIpTrim", "input trim"), ("kParamAttack", "attack"), ("kParamMinPhase", "min-phase")):
        if m.has(key):
            conv.note(f"unsupported: Convolve {label} dropped")
    _level_out_note(conv, m)


def _utility(conv, m: _Module, state: _RackState) -> None:
    mapped = False
    hpf, lpf = m.get("kParamHPF"), m.get("kParamLPF")
    if m.has("kParamHPF") and hpf > 1.0 and state.claim_band("low", "Utility HPF"):
        conv.set("eq_on", 1.0)
        conv.set("eq_low_mode", 1.0)
        conv.set("eq_low_cutoff", hz_to_note(hpf))
        conv.set("eq_low_gain", 0.0)
        mapped = True
    if m.has("kParamLPF") and lpf < 19999.0 and state.claim_band("high", "Utility LPF"):
        conv.set("eq_on", 1.0)
        conv.set("eq_high_mode", 1.0)
        conv.set("eq_high_cutoff", hz_to_note(lpf))
        conv.set("eq_high_gain", 0.0)
        mapped = True
    if mapped:
        conv.note("approximation: Utility HPF/LPF rendered with Vital's EQ pass bands")
    for key, label in (
        ("kParamWidth", "stereo WIDTH"),
        ("kParamBalance", "PAN"),
        ("kParamLFMono", "mono bass"),
        ("kParamPolarityL", "polarity invert"),
        ("kParamPolarityR", "polarity invert"),
    ):
        if m.has(key):
            conv.note(f"unsupported: Utility {label} dropped")
    _level_out_note(conv, m)


def _unsupported(conv, m: _Module, state: _RackState) -> None:
    labels = {
        "FXBode": "Bode frequency shifter",
        "FXSplit": "Splitter L/H (its branches are flattened into the chain)",
        "FXSplit3": "Splitter L/M/H (its branches are flattened into the chain)",
        "FXSplitMS": "Splitter M/S (its branches are flattened into the chain)",
    }
    conv.note(f"unsupported: {labels.get(m.name, m.short)} dropped")


_HANDLERS = {
    "FXDistortion": _distortion,
    "FXFlanger": _flanger,
    "FXPhaser": _phaser,
    "FXChorus": _chorus,
    "FXDelay": _delay,
    "FXComp": _compressor,
    "FXReverb": _reverb,
    "FXEQ": _eq,
    "FXFilter": _filter,
    "FXHyperD": _hyper,
    "FXConv": _convolution,
    "FXUtils": _utility,
    "FXBode": _unsupported,
    "FXSplit": _unsupported,
    "FXSplit3": _unsupported,
    "FXSplitMS": _unsupported,
}


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def rack_modules(patch, rack: int) -> list[_Module]:
    entries = patch.module(f"FXRack{rack}").get("FX")
    if not isinstance(entries, list):
        return []
    return [_Module(e, i) for i, e in enumerate(entries) if isinstance(e, dict)]


def convert_fx_racks(patch, conv) -> None:
    """Map Serum 2's main FX rack onto Vital's effects and set the chain order."""
    state = _RackState(conv)
    for module in rack_modules(patch, 0):
        if not module.enabled:
            conv.note(f"bypassed {module.short} module skipped")
            continue
        handler = _HANDLERS.get(module.name)
        if handler is None:
            conv.note(f"unsupported: unknown FX module {module.name} (type {module.type}) dropped")
            continue
        handler(conv, module, state)

    conv.set("effect_chain_order", fx.encode_effect_order(fx.vital_chain_from_rack(state.chain)))

    for bus in (1, 2):
        modules = rack_modules(patch, bus)
        if modules:
            types = ", ".join(m.short for m in modules)
            conv.note(f"unsupported: FX bus {bus} with {types}")
