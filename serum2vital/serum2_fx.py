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
    vital_type, exact = fx.dist_mode_index(mode)
    conv.set("distortion_on", 1.0)
    conv.set("distortion_type", vital_type)
    conv.set("distortion_drive", 30.0 * clamp01(m.get("kParamDrive") / 100.0))
    conv.set("distortion_mix", clamp01(m.get("kParamWet") / 100.0))
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
        index = fx.rate_hz_to_tempo_index(rate)
        conv.set(f"{prefix}_sync", SYNC_TEMPO)
        conv.set(f"{prefix}_tempo", float(index))
        if index > 10:
            conv.note(f"approximation: {prefix} synced rate 1/32 clamped to Vital's 1/16")
        conv.note(f"approximation: {prefix} synced division inferred from the rate knob position")
    else:
        conv.set(f"{prefix}_sync", SYNC_FREE)
        conv.set(f"{prefix}_frequency", max(freq_lo, min(freq_hi, log2_hz(rate))))
        if rate < 2.0 ** freq_lo:
            conv.note(f"approximation: {prefix} rate {rate:.3f} Hz is below Vital's minimum, clamped")


def _flanger(conv, m: _Module, state: _RackState) -> None:
    if not state.claim("flanger", m):
        return
    conv.set("flanger_on", 1.0)
    conv.set("flanger_dry_wet", 0.5 * clamp01(m.get("kParamWet") / 100.0))
    conv.set("flanger_mod_depth", clamp01(m.get("kParamDepth") / 100.0))
    conv.set("flanger_feedback", clamp01(m.get("kParamFeedback") / 100.0))
    conv.set("flanger_phase_offset", clamp01(m.get("kParamWidth") / 360.0))
    _mod_rate(conv, "flanger", m, -5.0, 2.0)
    conv.note("approximation: flanger centre frequency left at Vital's default (Serum has no such control)")
    _level_out_note(conv, m)


def _phaser(conv, m: _Module, state: _RackState) -> None:
    if not state.claim("phaser", m):
        return
    conv.set("phaser_on", 1.0)
    conv.set("phaser_dry_wet", clamp01(m.get("kParamWet") / 100.0))
    conv.set("phaser_feedback", clamp01(m.get("kParamFeedback") / 100.0))
    conv.set("phaser_center", hz_to_note(m.get("kParamFreq")))
    conv.set("phaser_mod_depth", 48.0 * clamp01(m.get("kParamDepth") / 100.0))
    conv.set("phaser_phase_offset", clamp01(m.get("kParamWidth") / 360.0))
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
    conv.set("chorus_dry_wet", clamp01(m.get("kParamWet") / 100.0))
    for key, vital in (("kParamDelay", "chorus_delay_1"), ("kParamDelay2", "chorus_delay_2")):
        ms = max(m.get(key), 1.0)
        conv.set(vital, math.log2(ms / 1000.0))
        if m.get(key) < 1.0:
            conv.note(f"approximation: chorus {key[6:]} below 1 ms raised to Vital's 1 ms minimum")
    conv.set("chorus_mod_depth", clamp01(m.get("kParamDepth") / CHORUS_DEPTH_MAX_MS))
    conv.set("chorus_feedback", max(-0.95, min(0.95, m.get("kParamFeedback") / 100.0)))
    conv.set("chorus_cutoff", hz_to_note(m.get("kParamFilt")))
    if m.get("kParamFiltMode") > 0.5:
        conv.set("chorus_cutoff", 136.0)
        conv.note("unsupported: chorus HPF mode dropped (Vital's chorus filter is low-pass only)")
    _mod_rate(conv, "chorus", m, -6.0, 3.0)
    _level_out_note(conv, m)


def _delay(conv, m: _Module, state: _RackState) -> None:
    if not state.claim("delay", m):
        return
    conv.set("delay_on", 1.0)
    conv.set("delay_dry_wet", clamp01(m.get("kParamWet") / 100.0))
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

    if mode == DELAY_PING_PONG:
        conv.set("delay_style", STYLE_PING_PONG)
    elif mode == DELAY_TAP:
        conv.set("delay_style", STYLE_MONO)
        time_l, off_l = time_r, off_r
        conv.note("approximation: Tap->Delay mode mapped onto a mono delay using the right-channel time")
    else:
        conv.set("delay_style", STYLE_MONO if same else STYLE_STEREO)

    synced = m.get("kParamBeatSync") > 0.5
    for prefix, seconds, offset in (("delay", time_l, off_l), ("delay_aux", time_r, off_r)):
        if synced:
            sync = fx.offset_to_sync(offset)
            conv.set(f"{prefix}_sync", float(sync))
            conv.set(f"{prefix}_tempo", float(fx.delay_seconds_to_tempo_index(seconds)))
            if sync == SYNC_TEMPO and abs(offset - 1.0) > 0.02:
                conv.note(f"approximation: delay time scalar {offset:.3f} is neither dotted nor triplet; ignored")
        else:
            conv.set(f"{prefix}_sync", SYNC_FREE)
            conv.set(f"{prefix}_frequency", max(-2.0, min(9.0, math.log2(1.0 / max(seconds * offset, 1e-4)))))
    if synced:
        conv.note("approximation: synced delay division inferred from the stored time-knob value")
    if m.has("kParamHQ"):
        conv.note("unsupported: delay High Quality switch dropped")
    _level_out_note(conv, m)


def _compressor(conv, m: _Module, state: _RackState) -> None:
    if not state.claim("compressor", m):
        return
    conv.set("compressor_on", 1.0)
    conv.set("compressor_mix", clamp01(m.get("kParamWet") / 100.0))
    conv.set("compressor_attack", fx.comp_time_to_vital(m.get("kParamAttack")))
    conv.set("compressor_release", fx.comp_time_to_vital(m.get("kParamRelease")))
    conv.note("approximation: compressor attack/release mapped by knob position (Vital's times are not in ms)")

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
        if multiband:
            scale = m.get(f"kParamThreshUD{suffix}") / 100.0
            band_ratio = clamp01(m.get(f"kParamRatio{suffix}", ratio)) if m.has(f"kParamRatio{suffix}") else ratio
            band_below = clamp01(m.get(f"kParamRatioBelow{suffix}")) if m.has(f"kParamRatioBelow{suffix}") else below
            gain = makeup_db + m.get(f"kParamGain{suffix}")
        else:
            scale, band_ratio, band_below, gain = 1.0, ratio, below, makeup_db
        threshold = max(-80.0, min(0.0, thresh_db * scale))
        conv.set(f"compressor_{band}_upper_threshold", threshold)
        conv.set(f"compressor_{band}_lower_threshold", max(-80.0, threshold - 10.0))
        conv.set(f"compressor_{band}_upper_ratio", band_ratio)
        conv.set(f"compressor_{band}_lower_ratio", band_below)
        conv.set(f"compressor_{band}_gain", max(-30.0, min(30.0, gain)))
    if multiband:
        conv.note("approximation: multiband thresholds scaled per band from Serum's THRESH x band offsets")
        if m.has("kParamXoverLow") or m.has("kParamXoverHi"):
            conv.note("unsupported: compressor crossover frequencies dropped (Vital's bands are fixed)")
    if below > 0.0 or any(m.has(f"kParamRatioBelow{s}") for _, s in bands):
        conv.note("approximation: Serum's BELOW ratio mapped onto Vital's lower (upward) ratio")
    conv.note("approximation: Vital's lower threshold set 10 dB under the upper threshold (Serum has one threshold)")
    if m.has("kParamDeadband0"):
        conv.note("unsupported: compressor deadband settings dropped")
    _level_out_note(conv, m)


def _reverb(conv, m: _Module, state: _RackState) -> None:
    if not state.claim("reverb", m):
        return
    kind = m.text("kParamType") or "kPlate"
    size = clamp01(m.get("kParamSize") / 100.0)
    conv.set("reverb_on", 1.0)
    conv.set("reverb_dry_wet", clamp01(m.get("kParamWet") / 100.0))
    conv.set("reverb_size", size)
    # Serum's SIZE is "reverb time + dimension"; spread it over 0.3 s .. 13 s.
    conv.set("reverb_decay_time", -1.74 + 5.5 * size)
    conv.set("reverb_delay", max(0.0, min(0.3, m.get("kParamPreDelay"))))
    if m.get("kParamPreDelay") > 0.3:
        conv.note("approximation: reverb pre-delay clamped to Vital's 300 ms maximum")
    if m.get("kParamPreDelayBeatSync") > 0.5:
        conv.note("unsupported: reverb pre-delay tempo sync dropped")
    conv.set("reverb_pre_low_cutoff", 128.0 * clamp01(m.get("kParamFreq") / 100.0))
    high_cut = 128.0 * (1.0 - clamp01(m.get("kParamFreqB") / 100.0))
    conv.set("reverb_high_shelf_cutoff", high_cut)
    conv.set("reverb_pre_high_cutoff", high_cut)
    conv.set("reverb_high_shelf_gain", -6.0 * clamp01(m.get("kParamFreqC") / 100.0))
    conv.note("approximation: reverb decay time derived from SIZE; LO/HI CUT percentages mapped linearly onto Vital's cutoffs")
    if kind != "kPlate":
        conv.note(f"approximation: Serum reverb type {kind[1:]} rendered with Vital's single reverb algorithm")
    if m.has("kParamWidth") and m.get("kParamWidth") < 99.0:
        conv.note("unsupported: reverb WIDTH dropped (Vital's reverb has no width control)")
    if m.has("kParamDelay"):
        conv.note(f"unsupported: {kind[1:]} reverb DECAY/PRE-DLY control (kParamDelay) dropped")
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
    reso = clamp01(m.get(f"kParamReso{n}") / 100.0)
    label = f"EQ {side} band ({kind})"
    if kind == EQ_PEAK:
        if state.claim_band("band", label):
            conv.set("eq_band_mode", 0.0)
            conv.set("eq_band_cutoff", hz_to_note(hz))
            conv.set("eq_band_gain", max(-15.0, min(15.0, gain)))
            conv.set("eq_band_resonance", reso)
        elif state.claim_band(side, label):
            conv.set(f"eq_{side}_mode", 0.0)
            conv.set(f"eq_{side}_cutoff", hz_to_note(hz))
            conv.set(f"eq_{side}_gain", max(-15.0, min(15.0, gain)))
            conv.set(f"eq_{side}_resonance", reso)
            conv.note(f"approximation: EQ {side} peak band rendered as a shelf (Vital's peak band was taken)")
        else:
            return
    else:
        if not state.claim_band(side, label):
            return
        conv.set(f"eq_{side}_mode", 1.0 if kind == EQ_PASS else 0.0)
        conv.set(f"eq_{side}_cutoff", hz_to_note(hz))
        conv.set(f"eq_{side}_gain", 0.0 if kind == EQ_PASS else max(-15.0, min(15.0, gain)))
        conv.set(f"eq_{side}_resonance", reso)
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
