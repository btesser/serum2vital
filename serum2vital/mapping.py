"""Serum -> Vital parameter mapping.

The two synths are close cousins -- wavetable oscillators, a modulation matrix,
point-based LFOs -- but not identical, so this module is explicit about which
mappings are exact and which are approximations.  Every unit curve and menu
order used here was measured from the Serum 1 plugin itself (see
serum_tables.py and docs/FINDINGS_AND_PLAN.md); nothing is guessed from knob
positions any more.

Fidelity notes are recorded in `Conversion.notes` with a prefix:

    exact:          same quantity, different encoding (not normally noted)
    approximation:  a Vital control that behaves similarly but not identically
    conflict:       two Serum features compete for one Vital resource
    unsupported:    dropped, nothing in Vital can stand in for it
    unknown:        the Serum state could not be read; a default was assumed
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from . import serum1
from . import serum_tables as st
from .serum_params import NAME_TO_INDEX
from .vital_defaults import DEFAULTS, clamp

try:  # optional companions; the converter degrades gracefully without them
    from . import filter_map
except ImportError:  # pragma: no cover
    filter_map = None
try:
    from . import fx_common
except ImportError:  # pragma: no cover
    fx_common = None
try:
    from . import serum2_fx
except ImportError:  # pragma: no cover
    serum2_fx = None

# Vital stores envelope times as seconds**(1/4); 2.37842**4 == 32.0 seconds,
# which is also where Serum's time knobs top out.  Serum's knob is quintic
# (t = 32 * n**5, measured), so the Vital value is 2.37842 * n**1.25.
ENV_TIME_SCALE = 2.37842
ENV_HOLD_MAX = 1.4142135624   # Vital hold tops out at 4 s

# Serum's A/D/R curve knobs are 0..100% with 50% == linear.  Vital's "power"
# controls were matched by rendering: for the amplitude envelope (which Vital
# squares) Serum 50/67/90% decays line up with Vital powers +2/-1/-5 and a 50%
# attack with +3; modulation envelopes are not squared, so they get no offset.
ENV_CURVE_SCALE = 17.5


def env_power(curve: float, stage: str, amplitude: bool) -> float:
    base = -ENV_CURVE_SCALE * (curve - 0.5)
    if amplitude:
        base += 3.0 if stage == "attack" else 2.0
    return max(-20.0, min(20.0, base))

# Vital tempo indices: 0 Freeze, 1 = 32/1, 2 = 16/1, ... 6 = 1/1, 8 = 1/4, 12 = 1/64.
VITAL_TEMPO = {
    "32 bar": 1, "16 bar": 2, "8 bar": 3, "4 bar": 4, "2 bar": 5, "bar": 6,
    "1/2": 7, "1/4": 8, "1/8": 9, "1/16": 10, "1/32": 11, "1/64": 12,
    "1/128": 12, "1/256": 12, "fast": 12,
}
VITAL_TEMPO_TOO_FAST = {"1/128", "1/256", "fast"}

# Vital lfo_N_sync values.
SYNC_SECONDS, SYNC_TEMPO, SYNC_DOTTED, SYNC_TRIPLET = 0, 1, 2, 3
# Vital lfo_N_sync_type values.
SYNC_TYPE = {"trig": 0, "off": 1, "env": 2}

# Serum warp menu (serum_tables.WARP_NAMES order) -> (Vital distortion type,
# amount transform, label, exact).  Vital types: 0 None, 1 Sync, 2 Formant,
# 3 Quantize, 4 Bend, 5 Squeeze, 6 Pulse, 7 FM<-osc A, 8 FM<-osc B,
# 9 FM<-sample, 10 RM<-osc A, 11 RM<-osc B, 12 RM<-sample.  "osc A/B" are the
# other two oscillators in order, so for Vital osc 1 type 7 is FM from osc 2
# and type 8 is FM from osc 3 (Serum's sub oscillator).
WARP_TO_VITAL = {
    "Off": (0, "zero", True),
    "Sync": (1, "sync", True),
    "Sync 1/2 Win.": (1, "sync", False),
    "Sync Window": (2, "sync", False),
    # Measured: Serum's Bend+ brightens and drops level the way Vital's Squeeze
    # does above its 0.5 neutral point, while Vital's Bend darkens both ways.
    "Bend +": (5, "half_up", False),
    "Bend -": (5, "half_down", False),
    "Bend +/-": (5, "same", False),
    "PWM": (6, "same", True),
    "Asym +": (4, "half_up", False),
    "Asym -": (4, "half_down", False),
    "Asym +/-": (4, "same", False),
    "Quantize": (3, "same", True),
    "FM (from B)": (7, "fm", True),
    "AM (from B)": (10, "same", False),
    "RM (from B)": (10, "same", True),
    "FM (Noise)": (9, "fm", True),
    "FM (Sub)": (8, "fm_sub", True),
}
WARP_UNSUPPORTED = {"Flip", "Mirror", "Remap 1", "Remap 2", "Remap 3", "Remap 4"}

# Serum unison stack menu (serum_tables.UNISON_STACK_NAMES) -> Vital stack style.
# Vital: 0 Unison, 1 Center Drop 12, 2 Center Drop 24, 3 Octave, 4 2x Octave,
# 5 Power Chord, 6 2x Power Chord, 7 Major, 8 Minor, 9 Harmonics, 10 Odd Harmonics.
STACK_TO_VITAL = {
    "off": (0, True), "12 (1x)": (3, True), "12 (2x)": (4, True), "12 (3x)": (4, False),
    "12+7(1x)": (5, True), "12+7(2x)": (6, True), "12+7(3x)": (6, False),
    "Center-12": (1, True), "Center-24": (2, True),
}

# Serum's built-in default wavetable (what an empty table name means); resolved
# against the Serum 2 library first, then synthesised as a saw.
DEFAULT_TABLE = "S2 Tables/Default Shapes.wav"

# Serum sub-oscillator shapes -> names understood by wavetables.builtin_wavetable.
SUB_SHAPE_FILES = {"Sine": "sin.wav", "RoundRect": "roundrect.wav", "Saw": "saw.wav",
                   "Square": "square.wav", "Pulse": "pulse.wav"}

# Serum mod sources -> Vital modulation source names (None: no counterpart).
SOURCE_TO_VITAL = {
    "env_1": "env_1", "env_2": "env_2", "env_3": "env_3", "env_4": "env_4",
    **{f"lfo_{i}": f"lfo_{i}" for i in range(1, 9)},
    **{f"macro_{i}": f"macro_control_{i}" for i in range(1, 5)},
    "mod_wheel": "mod_wheel",
    "velocity": "velocity",
    "note": "note",
    "aftertouch": "aftertouch",
    "poly_aftertouch": "aftertouch",
    "pitch_bend": "pitch_wheel",
    "chaos_1": "random_1",
    "chaos_2": "random_2",
    "note_random_1": "random",
    "note_random_2": "random",
    "release_velocity": "lift",
    "mpe_y": "slide",
    "mpe_z": "aftertouch",
    "note_alt_1": None, "note_alt_2": None, "noise_osc": None, "fixed": None, "mpe_x": None,
}
BIPOLAR_SOURCES = {"random_1", "random_2", "pitch_wheel"}


@dataclass
class Conversion:
    """Everything needed to write one .vital file."""

    name: str
    author: str = ""
    comments: str = ""
    style: str = ""
    macro_names: list[str] = field(default_factory=lambda: ["MACRO 1", "MACRO 2", "MACRO 3", "MACRO 4"])
    settings: dict = field(default_factory=dict)
    modulations: list[dict] = field(default_factory=list)
    wavetables: list[dict | None] = field(default_factory=lambda: [None, None, None])
    lfos: list[dict | None] = field(default_factory=lambda: [None] * 8)
    sample: dict | None = None
    notes: list[str] = field(default_factory=list)
    # (INSTRUMENT, TYPE, MODIFIER) folder names, filled in by categorize.py.
    category: tuple[str, str, str] | None = None
    # Asset references the preset points at, resolved later against the Serum
    # data folder: one wavetable name per Vital oscillator, plus a noise sample.
    wavetable_refs: list[str | None] = field(default_factory=lambda: [None, None, None])
    sample_ref: str | None = None
    # Bookkeeping used while mapping (not written out).
    lfo_hz_mode: list[bool] = field(default_factory=lambda: [False] * 8)
    chorus_busy: bool = False

    def set(self, key: str, value: float) -> None:
        if key not in DEFAULTS:
            self.notes.append(f"unknown Vital parameter {key!r} skipped")
            return
        self.settings[key] = float(clamp(key, value))

    def get(self, key: str) -> float:
        return self.settings.get(key, DEFAULTS[key])

    def note(self, message: str) -> None:
        if message not in self.notes:
            self.notes.append(message)

    def add_modulation(self, source: str, destination: str, amount: float, bipolar: bool = False) -> int | None:
        """Add a routing; returns its 1-based slot index, or None when full."""
        if destination not in DEFAULTS:
            self.note(f"unsupported: modulation destination {destination!r} is not a Vital parameter")
            return None
        if len(self.modulations) >= 64:
            self.note("conflict: more than 64 modulations; extra routings dropped")
            return None
        index = len(self.modulations) + 1
        self.modulations.append({"source": source, "destination": destination})
        self.set(f"modulation_{index}_amount", amount)
        self.set(f"modulation_{index}_bipolar", 1.0 if bipolar else 0.0)
        return index


# --------------------------------------------------------------------------
# unit helpers
# --------------------------------------------------------------------------


def db_to_volume(db: float) -> float:
    """Vital's master `volume` parameter from a dB value.

    Vital declares volume as 0..7399.4404 on a square-root scale; sqrt of the
    bounds gives 0..86.02 and sqrt of the default gives 73.98, i.e. a clean
    -80 dB .. +6.02 dB range with the default at -6.02 dB.
    """
    return max(0.0, (80.0 + db) ** 2)


def note_to_hz(note: float) -> float:
    return 440.0 * (2.0 ** ((note - 69.0) / 12.0))


def hz_to_note(hz: float) -> float:
    return 69.0 + 12.0 * math.log2(max(hz, 1e-6) / 440.0)


def serum_cutoff_to_note(normalised: float) -> float:
    """Serum's 0..1 cutoff knob (8 Hz .. 22.05 kHz, log) to a Vital MIDI-note cutoff."""
    return hz_to_note(st.cutoff_hz(normalised))


def log2_hz(hz: float, lo: float = 1e-4) -> float:
    return math.log2(max(hz, lo))


def env_time(normalised: float, maximum: float = ENV_TIME_SCALE) -> float:
    n = max(0.0, min(1.0, normalised))
    return min(maximum, ENV_TIME_SCALE * n ** 1.25)


def rate_step(normalised: float) -> int:
    return int(round(max(0.0, min(1.0, normalised)) * 228))


def division_to_tempo(division: str, conv: Conversion | None = None, what: str = "") -> int:
    index = VITAL_TEMPO.get(division, 8)
    if conv is not None and division in VITAL_TEMPO_TOO_FAST:
        conv.note(f"approximation: {what} rate {division} is faster than Vital's 1/64; clamped")
    return index


def serum_filter_index(value: float) -> int | None:
    """Recover Serum's filter menu index from the stored 0..1 value."""
    return st.indexed(value, (95, 89, 88))


def _interp(x: float, points: list[tuple[float, float]]) -> float:
    """Piecewise-linear interpolation through sorted (x, y) points, flat outside."""
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


def warp_amount(transform: str, amount: float) -> float:
    if transform == "zero":
        return 0.0
    if transform == "half_up":
        return 0.5 + 0.5 * amount
    if transform == "half_down":
        return 0.5 - 0.5 * amount
    if transform == "fm":       # Serum's FM index is stronger below the midpoint
        return amount ** 0.8
    if transform == "fm_sub":   # spectral-centroid match: Serum warp 0.4 = Vital 0.6, 0.6+ beyond Vital's range
        return min(1.0, 1.5 * amount)
    if transform == "fm_osc":   # from the other wavetable oscillator: Serum stays gentle below the midpoint
        return amount ** 1.5
    if transform == "sync":     # Serum's sync sweeps further at the same knob
        return min(1.0, 1.3 * amount)
    return amount


# --------------------------------------------------------------------------
# shared building blocks
# --------------------------------------------------------------------------


def apply_lfo_settings(conv: Conversion, slot: int, settings: serum1.LfoSettings, rate_norm: float,
                       what: str = "LFO", used: bool = True) -> None:
    """Set Vital's sync mode, tempo/frequency and trigger type for one LFO."""
    if not settings.known and used:
        conv.note(f"unknown: {what} {slot} sync/trigger switches are not stored in this preset; "
                  "loaded as Serum does (BPM synced, free-running, anchored)")
    conv.lfo_hz_mode[slot - 1] = settings.hz_mode
    if settings.hz_mode:
        conv.set(f"lfo_{slot}_sync", SYNC_SECONDS)
        conv.set(f"lfo_{slot}_frequency", log2_hz(st.lfo_hz(rate_norm), 2.0 ** -7))
    else:
        division = st.lfo_division(rate_step(rate_norm))
        conv.set(f"lfo_{slot}_tempo", division_to_tempo(division, conv if used else None, f"{what} {slot}"))
        if settings.dotted:
            conv.set(f"lfo_{slot}_sync", SYNC_DOTTED)
        elif settings.triplet:
            conv.set(f"lfo_{slot}_sync", SYNC_TRIPLET)
        else:
            conv.set(f"lfo_{slot}_sync", SYNC_TEMPO)
    conv.set(f"lfo_{slot}_sync_type", SYNC_TYPE.get(settings.mode, 0))


def route(conv: Conversion, source: str | None, destination: str, amount: float,
          aux: str | None = None, what: str = "", bipolar: bool | None = None) -> None:
    """Add one Serum routing (source x aux x amount -> destination) to Vital."""
    if source is None:
        conv.note(f"unsupported: modulation source {what or '?'} has no Vital counterpart; routing dropped")
        return
    vital_source = SOURCE_TO_VITAL.get(source)
    if vital_source is None:
        conv.note(f"unsupported: modulation source '{source}' has no Vital counterpart; routing dropped")
        return
    # Serum's matrix "type" column makes any source swing +-amount around the
    # knob (measured: an LFO -> Semi routing at +100% steps -12..+12 st, i.e.
    # 24*(0.5 - y)); Vital's bipolar flag has the same law (+-amount*range/2).
    bipolar = bool(bipolar) or vital_source in BIPOLAR_SOURCES
    if re.match(r"lfo_\d+_(tempo|frequency)$", destination):
        # Serum's rate knob spans about 8 octaves; Vital's tempo list is 12
        # steps of one octave with "freeze" at 0, so a full-range Serum amount
        # would park the LFO at freeze (holding its first value) half the time.
        amount *= CALIB["lfo_rate_mod_scale"]
    vital_aux = SOURCE_TO_VITAL.get(aux) if aux else None
    if aux and vital_aux is None:
        conv.note(f"approximation: aux source '{aux}' has no Vital counterpart; routing applied without it")
    if vital_aux:
        # Serum multiplies source by aux.  Vital can modulate a routing's own
        # amount, so the primary amount starts at zero and the aux drives it.
        index = conv.add_modulation(vital_source, destination, 0.0, bipolar)
        if index is not None:
            # A routing's amount parameter spans -1..1, so a modulation of it
            # by x moves the amount by 2x; halve so that the aux at full
            # value yields exactly `amount` (measured: 0.25 gave a 41 st
            # swing on transpose, the direct routing 23 st).
            conv.add_modulation(vital_aux, f"modulation_{index}_amount", amount / 2.0, False)
    else:
        conv.add_modulation(vital_source, destination, amount, bipolar)


def set_effect_order(conv: Conversion, rack: list[str]) -> None:
    if fx_common is None:
        return
    try:
        chain = fx_common.vital_chain_from_rack(rack)
        conv.set("effect_chain_order", fx_common.encode_effect_order(chain))
    except Exception as exc:  # never let ordering break a conversion
        conv.note(f"unknown: effect order not applied ({exc})")


def apply_filter_target(conv: Conversion, prefix: str, index_or_name, var: float, cutoff_note: float,
                        serum2: bool = False) -> None:
    """Set Vital filter model/style/blend for slot `prefix` from a Serum filter type."""
    if filter_map is None:
        conv.set(f"{prefix}_model", 0.0)
        conv.set(f"{prefix}_style", 0.0)
        conv.note("unknown: filter catalog unavailable; analog 12 dB low-pass substituted")
        return
    target = filter_map.target_for_serum2(index_or_name) if serum2 else filter_map.target_for_serum1(index_or_name)
    params = target.slot_params() if hasattr(target, "slot_params") else {
        "model": target.model, "style": target.style, "blend": target.blend}
    params.update(filter_map.apply_var(target, var, cutoff_note))
    for key, value in params.items():
        if key == "mix" and conv.get(f"{prefix}_mix") < value:
            continue  # a hint only lowers the mix, never raises what Serum set
        conv.set(f"{prefix}_{key}", value)
    if hasattr(filter_map, "map_resonance"):
        conv.set(f"{prefix}_resonance", filter_map.map_resonance(target, conv.get(f"{prefix}_resonance")))
    if target.fidelity != "exact" and target.note:
        conv.note(f"{target.fidelity}: filter '{target_name(index_or_name, serum2)}' -> {target.note}")
    if target.second is not None and prefix == "filter_1":
        # Dual SVF: the secondary response goes to Vital filter 2 in series.
        second = target.second
        conv.set("filter_2_on", 1.0)
        conv.set("filter_2_filter_input", 1.0)
        for key, value in (second.slot_params() if hasattr(second, "slot_params") else
                           {"model": second.model, "style": second.style, "blend": second.blend}).items():
            conv.set(f"filter_2_{key}", value)
        conv.set("filter_2_cutoff", serum_cutoff_to_note(var))
        conv.set("filter_2_resonance", conv.get("filter_1_resonance"))
        conv.set("filter_2_mix", conv.get("filter_1_mix"))


def target_name(index_or_name, serum2: bool) -> str:
    if serum2:
        return str(index_or_name)
    if isinstance(index_or_name, int) and 0 <= index_or_name < len(st.FILTER_NAMES):
        return st.FILTER_NAMES[index_or_name]
    return str(index_or_name)


# --------------------------------------------------------------------------
# Serum 1
# --------------------------------------------------------------------------


def _p(patch: serum1.Serum1Patch, name: str) -> float:
    """Normalised value of a Serum parameter, by name."""
    return patch.params[NAME_TO_INDEX[name]]


def _display(patch: serum1.Serum1Patch, name: str) -> float:
    """Serum parameter in the units Serum displays."""
    from .serum_params import denormalise

    index = NAME_TO_INDEX[name]
    return denormalise(index, patch.params[index])


# Serum's unison tuning menu -> Vital's detune power.  Measured on 7/8-voice
# stacks: Serum Linear spaces voices evenly (Vital power 0), Exp matches Vital's
# default 1.5 (-50 -25 -9 0 +9 +25 +50 cents), Inv pushes voices outwards
# (power -2: -50 -43 -28 0 +28 +43 +50).  Super's slightly uneven spacing and
# Random's per-note spacing have no counterpart and fall back to linear.
UNISON_TUNING_TO_POWER = {"Linear": 0.0, "Super": 0.0, "Exp": 1.5, "Inv": -2.0, "Random": 0.0}


# Serum's unison stack changes the oscillator's level with the voice count
# (Vital's stays flat).  Measured twice on the init saw at default detune and
# blend, relative to one voice; intermediate counts are interpolated.
# Serum 2 conversions were 3.0 dB louder than Serum 2's own render of the same preset.
S2_LEVEL_OFFSET_DB = 3.0

# Calibration switches, mainly so tools/evaluate.py can ablate one change at a time.
CALIB = {"drive_residual": False, "sub_linear": True, "unison_gain": False,
         "lfo_invert": False, "lfo_wrap": True, "lfo_power_flip": False, "comp_excess_scale": 0.5,
         "lfo_rate_mod_scale": 1.0}

UNISON_GAIN_DB = {1: 0.0, 2: -1.9, 3: -3.6, 4: -0.6, 5: -1.5, 6: 0.2, 7: -0.3, 8: 0.9, 10: 1.25, 12: 1.5, 16: 1.4}


def unison_gain_db(voices: int) -> float:
    voices = max(1, min(16, int(voices)))
    if voices in UNISON_GAIN_DB:
        return UNISON_GAIN_DB[voices]
    lower = max(v for v in UNISON_GAIN_DB if v < voices)
    upper = min(v for v in UNISON_GAIN_DB if v > voices)
    t = (voices - lower) / (upper - lower)
    return UNISON_GAIN_DB[lower] + t * (UNISON_GAIN_DB[upper] - UNISON_GAIN_DB[lower])


def serum_phase_to_vital(phase: float) -> float:
    """Serum oscillator phase (0..1 of a cycle) -> Vital's phase parameter.

    Both synths start a note at a fixed point of the frame when random phase
    is off, but Serum reads from index phase * N while Vital reads from
    (phase + 0.5) * N; Serum's default of 180 degrees is therefore Vital 0.0.
    Serum's sub oscillator has no phase knob and behaves like 180 degrees
    (a sine starting at zero and falling), i.e. Vital phase 0.0.
    """
    return (phase + 0.5) % 1.0


def _osc_from_serum1(conv: Conversion, patch: serum1.Serum1Patch, letter: str, slot: int) -> None:
    """Map Serum oscillator A/B onto Vital oscillator `slot` (1-based)."""
    prefix = f"osc_{slot}"
    on = _p(patch, f"Osc {letter} On") > 0.5
    conv.set(f"{prefix}_on", 1.0 if on else 0.0)
    if not on:
        return

    # Serum's Vol knob is quadratic in amplitude, and so is Vital's level; the
    # unison stack's measured level change is folded in as a gain (dB / 40
    # because the level is an amplitude squared).
    voices = max(1, round(_display(patch, f"{letter} Unison")))
    gain_db = unison_gain_db(voices) if CALIB["unison_gain"] else 0.0
    conv.set(f"{prefix}_level", min(1.0, _p(patch, f"{letter} Vol") * 10 ** (gain_db / 40.0)))
    conv.set(f"{prefix}_pan", _display(patch, f"{letter} Pan") / 50.0)

    octave = round(_display(patch, f"{letter} Octave"))
    semi = round(_display(patch, f"{letter} Semi"))
    # CoarsePit is a third pitch control, -64..+64 semitones (measured), that
    # arps and sequences modulate; its static value adds to the transpose.
    coarse = round((_p(patch, f"{letter} CoarsePit") - 0.5) * 128.0)
    transpose = octave * 12 + semi + coarse
    if abs(transpose) > 48:
        conv.note(f"approximation: osc {letter} pitch offset {transpose:+d} st exceeds Vital's +-48; clamped")
    conv.set(f"{prefix}_transpose", max(-48, min(48, transpose)))
    conv.set(f"{prefix}_tune", _display(patch, f"{letter} Fine") / 100.0)

    voices = max(1, round(_display(patch, f"{letter} Unison")))
    conv.set(f"{prefix}_unison_voices", voices)
    # Both detune knobs are quadratic over a 2-semitone default range.
    conv.set(f"{prefix}_unison_detune", 10.0 * _p(patch, f"{letter} UniDet"))
    settings = patch.settings
    conv.set(f"{prefix}_detune_range", settings.unison_range[slot - 1])
    tuning = settings.unison_tuning[slot - 1]
    conv.set(f"{prefix}_detune_power", UNISON_TUNING_TO_POWER.get(tuning, 0.0))
    if tuning in ("Super", "Random") and voices > 1:
        conv.note(f"approximation: osc {letter} unison tuning '{tuning}' has no Vital equivalent; linear spacing used")
    conv.set(f"{prefix}_unison_blend", _display(patch, f"{letter} UniBlend") / 100.0)
    conv.set(f"{prefix}_stereo_spread", _display(patch, f"{letter} Uni LR") / 100.0)
    conv.set(f"{prefix}_frame_spread", _display(patch, f"{letter} Uni WTPos") * 1.28)
    conv.set(f"{prefix}_distortion_spread", _display(patch, f"{letter} Uni Warp") / 200.0)

    conv.set(f"{prefix}_wave_frame", _p(patch, f"{letter} WTPos") * 256.0)
    # Serum starts reading a frame at phase * 2048, Vital at (phase + 0.5) * 2048
    # (measured on both plugins with the same table), so the knob is shifted
    # by half a cycle to start the waveform where Serum does.
    conv.set(f"{prefix}_phase", serum_phase_to_vital(_p(patch, f"{letter} Phase")))
    conv.set(f"{prefix}_random_phase", _display(patch, f"{letter} RandPhase") / 100.0)
    conv.set(f"{prefix}_midi_track", 1.0 if _p(patch, f"Osc{letter}PitchTrack") > 0.5 else 0.0)

    stack_index = st.indexed(_p(patch, f"{letter} Uni Stack"), (8,))
    stack_name = st.UNISON_STACK_NAMES[stack_index] if stack_index is not None and stack_index < 9 else "off"
    style, exact = STACK_TO_VITAL.get(stack_name, (0, True))
    conv.set(f"{prefix}_stack_style", style)
    if not exact:
        conv.note(f"approximation: osc {letter} unison stack '{stack_name}' -> Vital style {style}")

    # Warp / phase distortion.
    warp_index = st.indexed(_p(patch, f"WarpOsc{letter}"), (23,))
    warp_name = st.WARP_NAMES[warp_index] if warp_index is not None and warp_index < len(st.WARP_NAMES) else "Off"
    amount = _p(patch, f"{letter} Warp")
    mapped = WARP_TO_VITAL.get(warp_name)
    if mapped is None:
        conv.set(f"{prefix}_distortion_type", 0.0)
        if warp_name in WARP_UNSUPPORTED:
            conv.note(f"unsupported: osc {letter} warp '{warp_name}' (amount {amount:.2f}) has no Vital equivalent; left off")
        else:
            conv.note(f"unknown: osc {letter} warp index {warp_index} not recognised; left off")
    else:
        vital_type, transform, exact = mapped
        if warp_name in ("FM (Noise)",) and _p(patch, "Osc N On") < 0.5:
            conv.note(f"approximation: osc {letter} FM from noise with the noise oscillator off; FM source is the sample")
        if warp_name == "FM (Sub)" and _p(patch, "Osc S On") < 0.5:
            conv.note(f"approximation: osc {letter} FM from sub with the sub oscillator off")
        conv.set(f"{prefix}_distortion_type", vital_type)
        conv.set(f"{prefix}_distortion_amount", warp_amount(transform, amount))
        if not exact:
            conv.note(f"approximation: osc {letter} warp '{warp_name}' -> Vital distortion type {vital_type}")

    # Routing: Serum's Osc>Fil switch decides filter vs. dry.
    to_filter = _p(patch, f"Osc{letter}>Fil") > 0.5
    conv.set(f"{prefix}_destination", 0.0 if to_filter else 3.0)


def _filter_from_serum1(conv: Conversion, patch: serum1.Serum1Patch) -> None:
    on = _p(patch, "Filter On") > 0.5
    conv.set("filter_1_on", 1.0 if on else 0.0)
    if not on:
        return

    cutoff = serum_cutoff_to_note(_p(patch, "Fil Cutoff"))
    conv.set("filter_1_cutoff", cutoff)
    conv.set("filter_1_resonance", _display(patch, "Fil Reso") / 100.0)
    conv.set("filter_1_drive", 20.0 * _display(patch, "Fil Driv") / 100.0)
    conv.set("filter_1_mix", _display(patch, "Fil Mix") / 100.0)
    conv.set("filter_1_filter_input", 0.0)
    conv.set("filter_1_keytrack", 1.0 if patch.settings.filter_keytrack else 0.0)

    index = serum_filter_index(_p(patch, "Fil Type"))
    if index is None:
        conv.set("filter_1_model", 0.0)
        conv.set("filter_1_style", 0.0)
        conv.note("unknown: filter type value did not decode; analog 12 dB low-pass substituted")
        return
    apply_filter_target(conv, "filter_1", index, _p(patch, "Fil Var"), cutoff)


def _envelopes_from_serum1(conv: Conversion, patch: serum1.Serum1Patch) -> None:
    sources = [
        (1, "Env1 Atk", "Env1 Hold", "Env1 Dec", "Env1 Sus", "Env1 Rel", 1),
        (2, "Env2 Atk", "Env2 Hld", "Env2 Dec", "Env2 Sus", "Env2 Rel", 2),
        (3, "Env3 Atk", "Env3 Hld", "Env3 Dec", "Env3 Sus", "Env3 Rel", 3),
    ]
    for slot, atk, hold, dec, sus, rel, curve_set in sources:
        conv.set(f"env_{slot}_attack", env_time(_p(patch, atk)))
        conv.set(f"env_{slot}_hold", env_time(_p(patch, hold), ENV_HOLD_MAX))
        conv.set(f"env_{slot}_decay", env_time(_p(patch, dec)))
        conv.set(f"env_{slot}_release", env_time(_p(patch, rel)))
        # Env 1 sustain is quadratic in amplitude and so is Vital's amplitude
        # envelope; envs 2/3 are plain percentages.
        conv.set(f"env_{slot}_sustain", _p(patch, sus) if slot == 1 else _display(patch, sus) / 100.0)

        for serum_curve, vital_curve in (
            (f"A curve{curve_set}", "attack_power"),
            (f"D curve{curve_set}", "decay_power"),
            (f"R curve{curve_set}", "release_power"),
        ):
            curve = _display(patch, serum_curve) / 100.0
            conv.set(f"env_{slot}_{vital_curve}", env_power(curve, vital_curve.split("_")[0], slot == 1))


def _lfos_from_serum1(conv: Conversion, patch: serum1.Serum1Patch) -> None:
    from .wavetables import lfo_to_vital

    used = {m.source_name for m in patch.mod_slots if m.active}
    for slot in range(1, 9):
        shape = patch.lfo_shapes[slot - 1] if slot - 1 < len(patch.lfo_shapes) else None
        if shape is None:
            continue
        conv.lfos[slot - 1] = lfo_to_vital(
            shape, name=f"Serum LFO {slot}", invert_y=CALIB["lfo_invert"],
            close_loop=CALIB["lfo_wrap"],
            power_sign=-1.0 if CALIB["lfo_power_flip"] else 1.0,
        ) if len(shape.xs) >= 2 else None
        apply_lfo_settings(conv, slot, shape.settings, _p(patch, f"LFO{slot}Rate"), used=f"lfo_{slot}" in used)

        # Serum's SMOOTH knob is nearly inert until its top: rendering a
        # triangle LFO through the plugin, 10-50% shift its peak by less than
        # 5 ms while 100% delays it 175 ms and cuts it to a third; Vital's
        # smooth time of 0.2 s delays the same peak by 55 ms. 0.5*s^6 seconds
        # reproduces that (8 ms at 50%, 0.5 s at 100%); the old 0.5*s turned
        # a 10% setting into 50 ms, which smeared step sequences.
        smooth = _p(patch, f"LFO{slot} smooth")
        smooth_seconds = 0.5 * smooth ** 6
        conv.set(f"lfo_{slot}_smooth_mode", 1.0 if smooth_seconds > 0.003 else 0.0)
        if smooth_seconds > 0.003:
            conv.set(f"lfo_{slot}_smooth_time", math.log2(smooth_seconds))
        conv.set(f"lfo_{slot}_fade_time", 4.0 * _p(patch, f"LFO{slot} Rise"))
        conv.set(f"lfo_{slot}_delay_time", 4.0 * _p(patch, f"LFO{slot} Delay"))


def _chaos_from_serum1(conv: Conversion, patch: serum1.Serum1Patch) -> None:
    """Serum's Chaos 1/2 become Vital random LFOs 1/2 (Lorenz attractor)."""
    for number in (1, 2):
        prefix = f"random_{number}"
        # S&H steps the chaos output; Mono shares one generator between voices,
        # which is what Vital's random "sync" mode does.
        conv.set(f"{prefix}_style", 1.0 if patch.settings.chaos_sh[number - 1] else 3.0)  # S&H / Lorenz
        conv.set(f"{prefix}_sync_type", 1.0 if patch.settings.chaos_mono[number - 1] else 0.0)
        rate = _p(patch, f"Chaos{number} Rate")
        if _p(patch, f"Chaos{number} BPM") > 0.5:
            conv.set(f"{prefix}_sync", SYNC_TEMPO)
            conv.set(f"{prefix}_tempo", division_to_tempo(st.lfo_division(rate_step(rate)), conv, f"Chaos {number}"))
        else:
            conv.set(f"{prefix}_sync", SYNC_SECONDS)
            conv.set(f"{prefix}_frequency", max(-7.0, min(9.0, log2_hz(st.chaos_hz(rate)))))


def _fx_rate(conv: Conversion, prefix: str, synced: bool, rate: float, what: str) -> None:
    """Chorus/flanger/phaser rate: 20 Hz quartic knob, or the 31-entry synced ladder (fx_common.FX_RATE_RUNS)."""
    if synced:
        sync, tempo = fx_common.fx_rate_sync(rate_step(rate))
        conv.set(f"{prefix}_sync", float(sync))
        conv.set(f"{prefix}_tempo", float(max(0, min(10, tempo))))
        if tempo > 10:
            conv.note(f"approximation: {what} synced rate 1/32 clamped to Vital's 1/16")
    else:
        conv.set(f"{prefix}_sync", SYNC_SECONDS)
        conv.set(f"{prefix}_frequency", log2_hz(st.fx_rate_hz(rate), 2.0 ** -6))


def _effects_from_serum1(conv: Conversion, patch: serum1.Serum1Patch) -> None:
    # --- reverb ---
    if _p(patch, "Rev Enable") > 0.5:
        conv.set("reverb_on", 1.0)
        conv.set("reverb_dry_wet", fx_common.serum_wet_to_vital(_display(patch, "Verb Wet") / 100.0, fx_common.REVERB_WET_SCALE))
        size = _display(patch, "VerbSize") / 100.0
        conv.set("reverb_size", size)
        # Serum's DECAY (0.8..12 s displayed) and SIZE give the tail's RT60 (measured law);
        # Vital's decay_time is set so its tail measures the same RT60 at that size.
        rt60 = fx_common.serum1_reverb_rt60(size, _display(patch, "VerbDecay"))
        conv.set("reverb_decay_time", fx_common.vital_decay_for_rt60(rt60, size))
        pre_high, pre_low = fx_common.reverb_tone(_display(patch, "VerbHiCt") / 100.0, _display(patch, "VerbLoCt") / 100.0)
        conv.set("reverb_pre_high_cutoff", pre_high)
        conv.set("reverb_pre_low_cutoff", pre_low)
        conv.set("reverb_high_shelf_gain", 0.0)   # Serum's tail is brighter than Vital's default (-1 dB shelf)
        conv.set("reverb_chorus_amount", _display(patch, "VerbSpinDepth") / 100.0)
        conv.set("reverb_chorus_frequency", log2_hz(st.fx_rate_hz(_p(patch, "VerbSpinRate")), 2.0 ** -8))
        conv.note("approximation: reverb size/decay/damping mapped by ear; Vital's reverb is a different algorithm")
        if not patch.settings.reverb_hall:
            conv.note("approximation: Serum's Plate reverb mode has no Vital equivalent; Hall settings used")

    # --- delay ---
    if _p(patch, "Dly Enable") > 0.5:
        conv.set("delay_on", 1.0)
        conv.set("delay_feedback", _display(patch, "Dly_Feed") / 100.0)
        mode_index = st.indexed(_p(patch, "Dly_Mode"), (2,)) or 0
        mode = st.DELAY_MODE_NAMES[min(mode_index, 2)]
        linked = _p(patch, "Dly_Link") > 0.5
        wet_scale = 1.0
        if mode == "Ping-Pong":
            conv.set("delay_style", 2.0)
            wet_scale = 0.707   # Vital's ping-pong echoes sit 3 dB above its plain delay; Serum's do not
        elif mode == "Tap->Delay":
            conv.set("delay_style", 0.0)
            conv.note("approximation: delay mode Tap->Delay has no Vital equivalent; mono delay used")
        else:
            conv.set("delay_style", 0.0 if linked else 1.0)
        conv.set("delay_dry_wet", fx_common.serum_wet_to_vital(_display(patch, "Dly_Wet") / 100.0, wet_scale))
        synced = _p(patch, "Dly_BPM_Sync") > 0.5
        for side, param, offset_param, key in (("L", "Dly_TimL", "Dly_Off L", ""), ("R", "Dly_TimR", "Dly_Off R", "aux_")):
            if linked:
                param, offset_param = "Dly_TimL", "Dly_Off L"
            time = _p(patch, param)
            multiplier = st.delay_offset(_p(patch, offset_param))
            if synced:
                division = st.delay_division(rate_step(time))
                sync, tempo = fx_common.synced_delay(int(division_to_tempo(division, conv, f"delay {side}")), multiplier)
                conv.set(f"delay_{key}sync", float(sync))
                conv.set(f"delay_{key}tempo", float(tempo))
            else:
                # Unsynced Serum delay: 1 + 500 n^4 ms (plugin read-out), times the offset knob.
                seconds = max(0.001, min(4.0, st.delay_seconds(time) * multiplier))
                conv.set(f"delay_{key}sync", SYNC_SECONDS)
                conv.set(f"delay_{key}frequency", math.log2(1.0 / seconds))
        conv.set("delay_filter_cutoff", hz_to_note(st.log_hz(_p(patch, "Dly_Freq"), 40.0, 18000.0)))
        conv.set("delay_filter_spread", (_display(patch, "Dly_BW") - 0.8) / 7.4)

    # --- chorus ---
    if _p(patch, "Cho Enable") > 0.5:
        conv.set("chorus_on", 1.0)
        conv.chorus_busy = True
        conv.set("chorus_dry_wet", fx_common.serum_wet_to_vital(_display(patch, "Cho_Wet") / 100.0))
        conv.set("chorus_feedback", 0.95 * _p(patch, "Cho_Feed"))
        conv.set("chorus_mod_depth", _p(patch, "Cho_Dep") ** 2)
        conv.set("chorus_voices", 2.0)
        conv.set("chorus_delay_1", math.log2(max(0.001, 0.02 * _p(patch, "Cho_Dly") ** 2)))
        conv.set("chorus_delay_2", math.log2(max(0.001, 0.02 * _p(patch, "Cho_Dly2") ** 2)))
        # Serum's chorus FILTER is a low-pass on the wet path (1 kHz by default).
        cutoff, spread = fx_common.chorus_lowpass(st.log_hz(_p(patch, "Cho_Filt"), 50.0, 20000.0))
        conv.set("chorus_cutoff", cutoff)
        conv.set("chorus_spread", spread)
        _fx_rate(conv, "chorus", _p(patch, "Cho_BPM_Sync") > 0.5, _p(patch, "Cho_Rate"), "chorus")
        if patch.settings.chorus_mono:
            # Serum's switch runs the chorus LFO in phase on both channels; Vital's
            # chorus always offsets the right channel's LFO by a quarter cycle.
            conv.note("approximation: chorus mono switch (in-phase L/R LFO) has no Vital equivalent")

    # --- distortion ---
    if _p(patch, "Dist Enable") > 0.5:
        conv.set("distortion_on", 1.0)
        conv.set("distortion_mix", fx_common.serum_wet_gain(_display(patch, "Dist_Wet") / 100.0) if fx_common else _display(patch, "Dist_Wet") / 100.0)
        mode_index = st.indexed(_p(patch, "Dist_Mode"), (15, 12))
        mode = st.DIST_MODE_NAMES[mode_index] if mode_index is not None and mode_index < 16 else "Tube"
        if fx_common is not None:
            # Per-mode drive law measured on a saw: Serum pads every mode by -6 dB
            # at zero drive and each shaper has its own gain curve (fx_common.DIST_SERUM_LEVEL).
            vital_type, drive_db, exact = fx_common.dist_settings(mode, _p(patch, "Dist_Drv"))
        else:
            vital_type, drive_db, exact = 0, 16.0 * _p(patch, "Dist_Drv"), mode in ("SoftClip",)
        conv.set("distortion_drive", drive_db)
        conv.set("distortion_type", vital_type)
        if not exact:
            conv.note(f"approximation: distortion mode '{mode}' -> Vital type {vital_type}")
        pre_post = st.indexed(_p(patch, "Dist_PrePost"), (2,)) or 0
        conv.set("distortion_filter_order", pre_post)
        if pre_post:
            conv.set("distortion_filter_cutoff", hz_to_note(st.log_hz(_p(patch, "Dist_Freq"), 8.0, 13290.0)))
            conv.set("distortion_filter_resonance", _p(patch, "Dist_BW"))
            conv.set("distortion_filter_blend", 2.0 * _p(patch, "Dist_L/B/H"))

    # --- phaser / flanger ---
    if _p(patch, "Phs Enable") > 0.5:
        conv.set("phaser_on", 1.0)
        conv.set("phaser_dry_wet", fx_common.serum_wet_gain(_display(patch, "Phs_Wet") / 100.0))
        conv.set("phaser_feedback", _display(patch, "Phs_Feed") / 100.0)
        conv.set("phaser_center", hz_to_note(st.log_hz(_p(patch, "Phs_Frq"), 20.0, 18000.0)))
        conv.set("phaser_mod_depth", 48.0 * _display(patch, "Phs_Dpth") / 100.0)
        conv.set("phaser_phase_offset", fx_common.PHASER_OFFSET_PER_180 * _display(patch, "Phs_Stereo") / 180.0)
        _fx_rate(conv, "phaser", _p(patch, "Phs_BPM_Sync") > 0.5, _p(patch, "Phs_Rate"), "phaser")

    if _p(patch, "Flg Enable") > 0.5:
        conv.set("flanger_on", 1.0)
        conv.set("flanger_dry_wet", 0.5 * fx_common.serum_wet_gain(_display(patch, "Flg_Wet") / 100.0))
        conv.set("flanger_feedback", 2.0 * _display(patch, "Flg_Feed") / 100.0 - 1.0)
        conv.set("flanger_mod_depth", _display(patch, "Flg_Dep") / 100.0)
        conv.set("flanger_center", fx_common.FLANGER_CENTER_NOTE)   # Serum's flanger sits at ~16 ms (measured)
        conv.set("flanger_phase_offset", fx_common.FLANGER_OFFSET_PER_180 * _display(patch, "Flg_Stereo") / 180.0)
        _fx_rate(conv, "flanger", _p(patch, "Flg_BPM_Sync") > 0.5, _p(patch, "Flg_Rate"), "flanger")

    # --- compressor ---
    if _p(patch, "Comp Enable") > 0.5:
        conv.set("compressor_on", 1.0)
        conv.set("compressor_mix", _display(patch, "Comp_Wet") / 100.0)
        # Vital's follower time is base_ms * exp(8x - 4) (1.4 / 28 ms bases); Serum's knobs are 1000 n^2 ms.
        conv.set("compressor_attack", fx_common.comp_time_to_vital(st.comp_ms(_p(patch, "Cmp_Att")), "attack"))
        conv.set("compressor_release", fx_common.comp_time_to_vital(st.comp_ms(_p(patch, "Cmp_Rel")), "release"))
        threshold = fx_common.comp_threshold_db(_p(patch, "Cmp_Thr")) if fx_common else st.master_db(max(1e-3, 1.0 - _p(patch, "Cmp_Thr")))
        ratio = _p(patch, "Cmp_Rat")            # Serum stores 1 - 1/r, Vital's own scale
        makeup = fx_common.comp_makeup_db(_p(patch, "CmpGain"))
        multiband = _p(patch, "CmpMBnd") > 0.5
        conv.set("compressor_enabled_bands", 0.0 if multiband else 3.0)
        # With no upward (lower) compression, Vital's band gain of 0 dB is unity:
        # the +16/+12 dB defaults only exist to undo Vital's own default upward
        # compression, so Serum's makeup goes in directly.  Serum's detector reads
        # about 4 dB lower than Vital's RMS follower on the same signal (fixtures:
        # 3.4 vs 5.8 dB reduction at -25.8 dB, 15.1 vs 18.5 dB at -41.9 dB).
        if multiband:
            # Serum's multiband mode is an OTT-style upward + downward compressor with
            # per-band L/M/H level knobs (0..200 %); Vital's multiband compressor is the
            # same design, matched on quiet / normal / loud fixtures (fx_common MB_*).
            for band, knob in (("low", "CompMB L"), ("band", "CompMB M"), ("high", "CompMB H")):
                values = fx_common.mb_band_settings(threshold, ratio, band)
                for key in ("upper_threshold", "lower_threshold", "upper_ratio", "lower_ratio"):
                    conv.set(f"compressor_{band}_{key}", values[key])
                gain = makeup + values["gain"] + fx_common.mb_band_gain_db(_display(patch, knob))
                conv.set(f"compressor_{band}_gain", max(-30.0, min(30.0, gain)))
        else:
            threshold += fx_common.COMP_THRESHOLD_OFFSET_DB
            for band in ("low", "band", "high"):
                conv.set(f"compressor_{band}_upper_threshold", max(-80.0, min(0.0, threshold)))
                conv.set(f"compressor_{band}_upper_ratio", max(0.0, min(1.0, ratio)))
                conv.set(f"compressor_{band}_lower_threshold", -80.0)   # no upward compression in Serum
                conv.set(f"compressor_{band}_lower_ratio", 0.0)
                conv.set(f"compressor_{band}_gain", max(-30.0, min(30.0, makeup)))
        conv.note("approximation: compressor threshold/ratio/makeup mapped onto Vital's multiband compressor")

    # --- EQ ---
    if _p(patch, "EQ Enable") > 0.5:
        conv.set("eq_on", 1.0)
        low_type = st.indexed(_p(patch, "EQ TypL"), (2,)) or 0
        high_type = st.indexed(_p(patch, "EQ TypH"), (2,)) or 0
        low_note = hz_to_note(st.log_hz(_p(patch, "EQ FrqL"), 22.0, 20000.0))
        high_note = hz_to_note(st.log_hz(_p(patch, "EQ FrqH"), 22.0, 20000.0))
        low_q, high_q = _display(patch, "EQ Q L") / 100.0, _display(patch, "EQ Q H") / 100.0
        shift = fx_common.EQ_SHELF_SHIFT_SEMITONES  # Vital's shelves sit half an octave above Serum's
        if low_type == 1:   # peak: use Vital's band section
            conv.set("eq_band_cutoff", low_note)
            conv.set("eq_band_gain", _display(patch, "EQ VolL"))
            conv.set("eq_band_resonance", fx_common.eq_resonance(low_q, "peak"))
        else:
            conv.set("eq_low_mode", 1.0 if low_type == 2 else 0.0)
            conv.set("eq_low_cutoff", low_note if low_type == 2 else low_note + shift)
            conv.set("eq_low_gain", _display(patch, "EQ VolL"))
            conv.set("eq_low_resonance", fx_common.eq_resonance(low_q, "pass" if low_type == 2 else "shelf"))
        if high_type == 1:
            if low_type == 1:
                conv.note("conflict: both EQ bands are peaks; Vital has one peak band, high band used as shelf")
                conv.set("eq_high_mode", 0.0)
                conv.set("eq_high_cutoff", high_note + shift)
                conv.set("eq_high_gain", _display(patch, "EQ VolH"))
                conv.set("eq_high_resonance", 0.0)
            else:
                conv.set("eq_band_cutoff", high_note)
                conv.set("eq_band_gain", _display(patch, "EQ VolH"))
                conv.set("eq_band_resonance", fx_common.eq_resonance(high_q, "peak"))
        else:
            conv.set("eq_high_mode", 1.0 if high_type == 2 else 0.0)
            conv.set("eq_high_cutoff", high_note if high_type == 2 else high_note + shift)
            conv.set("eq_high_gain", _display(patch, "EQ VolH"))
            conv.set("eq_high_resonance", fx_common.eq_resonance(high_q, "pass" if high_type == 2 else "shelf"))

    # --- FX filter ---
    if _p(patch, "FX Fil Enable") > 0.5:
        conv.set("filter_fx_on", 1.0)
        cutoff = serum_cutoff_to_note(_p(patch, "FX Fil Freq"))
        conv.set("filter_fx_cutoff", cutoff)
        conv.set("filter_fx_resonance", _display(patch, "FX Fil Reso") / 100.0)
        conv.set("filter_fx_drive", 20.0 * _display(patch, "FX Fil Drive") / 100.0)
        conv.set("filter_fx_mix", _display(patch, "FX Fil Wet") / 100.0)
        index = serum_filter_index(_p(patch, "FX Fil Type"))
        if index is not None:
            apply_filter_target(conv, "filter_fx", index, _p(patch, "FX Fil Var"), cutoff)

    # --- Hyper / Dimension ---
    if _p(patch, "Hyp Enable") > 0.5:
        voices = st.indexed(_p(patch, "Hyp_Unison"), (7,))
        if fx_common is not None:
            fx_common.hyper_to_chorus(
                conv,
                wet=_p(patch, "Hyp_Wet"),
                rate_hz=st.fx_rate_hz(_p(patch, "Hyp_Rate")),
                detune=_p(patch, "Hyp_Detune"),
                voices=voices if voices is not None else 4,
                retrig=_p(patch, "Hyp_Retrig") > 0.5,
                dim_size=_p(patch, "HypDim_Size"),
                dim_mix=_p(patch, "HypDim_Mix"),
                chorus_busy=conv.chorus_busy,
            )
        else:
            conv.note("unsupported: Hyper/Dimension dropped (fx_common unavailable)")

    set_effect_order(conv, patch.fx_rack)


def _modulations_from_serum1(conv: Conversion, patch: serum1.Serum1Patch) -> None:
    """Translate Serum's 32 modulation slots into Vital modulation routings."""
    for slot in patch.mod_slots:
        if not slot.active:
            continue
        dest_name = slot.dest_name
        vital_dest = SERUM_DEST_TO_VITAL.get(dest_name) if dest_name else None
        if vital_dest is None:
            label = dest_name if dest_name else f"index {slot.dest}"
            conv.note(f"unsupported: modulation destination {label} has no Vital equivalent")
            continue
        if callable(vital_dest):
            vital_dest = vital_dest(conv)
        amount = slot.amount * max(0.0, min(1.0, slot.out_range))
        # A Serum amount is a fraction of the Serum parameter's range and a
        # Vital amount a fraction of the Vital parameter's range; rescale where
        # the two ranges differ (pitch: Semi is +-12 st, CoarsePit +-64 st,
        # Octave +-4 oct, all landing on Vital's +-48 st transpose).
        amount *= DEST_AMOUNT_SCALE.get(dest_name, 1.0)
        route(conv, slot.source_name, vital_dest, amount, slot.aux_source_name,
              what=f"id {slot.source}", bipolar=slot.bipolar)


def _lfo_rate_dest(number: int):
    return lambda conv: f"lfo_{number}_frequency" if conv.lfo_hz_mode[number - 1] else f"lfo_{number}_tempo"


# Serum range / Vital range for destinations whose ranges differ (see
# _modulations_from_serum1).  Measured: CoarsePit reads -64..+64 semitones.
DEST_AMOUNT_SCALE = {
    "A Semi": 24.0 / 96.0, "B Semi": 24.0 / 96.0,
    "A CoarsePit": 128.0 / 96.0, "B CoarsePit": 128.0 / 96.0,
}

# Serum modulation destinations (by parameter name) -> Vital parameter ids.
SERUM_DEST_TO_VITAL = {
    "MasterVol": "volume",
    "A Vol": "osc_1_level",
    "A Pan": "osc_1_pan",
    "A Fine": "osc_1_tune",
    "A Octave": "osc_1_transpose",
    "A Semi": "osc_1_transpose",
    "A CoarsePit": "osc_1_transpose",
    "A UniDet": "osc_1_unison_detune",
    "A UniBlend": "osc_1_unison_blend",
    "A Warp": "osc_1_distortion_amount",
    "A WTPos": "osc_1_wave_frame",
    "A Phase": "osc_1_phase",
    "B Vol": "osc_2_level",
    "B Pan": "osc_2_pan",
    "B Fine": "osc_2_tune",
    "B Octave": "osc_2_transpose",
    "B Semi": "osc_2_transpose",
    "B CoarsePit": "osc_2_transpose",
    "B UniDet": "osc_2_unison_detune",
    "B UniBlend": "osc_2_unison_blend",
    "B Warp": "osc_2_distortion_amount",
    "B WTPos": "osc_2_wave_frame",
    "B Phase": "osc_2_phase",
    "Noise Level": "sample_level",
    "Noise Pan": "sample_pan",
    "Noise Pitch": "sample_transpose",
    "Noise Fine": "sample_tune",
    "Sub Osc Level": "osc_3_level",
    "Sub Osc Pan": "osc_3_pan",
    "Fil Cutoff": "filter_1_cutoff",
    "Fil Reso": "filter_1_resonance",
    "Fil Driv": "filter_1_drive",
    "Fil Mix": "filter_1_mix",
    "Fil Var": "filter_1_blend",
    "Env1 Atk": "env_1_attack",
    "Env1 Dec": "env_1_decay",
    "Env1 Sus": "env_1_sustain",
    "Env1 Rel": "env_1_release",
    "Env2 Atk": "env_2_attack",
    "Env2 Dec": "env_2_decay",
    "Env2 Sus": "env_2_sustain",
    "Env2 Rel": "env_2_release",
    "Env3 Atk": "env_3_attack",
    "Env3 Dec": "env_3_decay",
    "Env3 Sus": "env_3_sustain",
    "Env3 Rel": "env_3_release",
    **{f"LFO{i}Rate": _lfo_rate_dest(i) for i in range(1, 9)},
    "Verb Wet": "reverb_dry_wet",
    "VerbSize": "reverb_size",
    "Dly_Wet": "delay_dry_wet",
    "Dly_Feed": "delay_feedback",
    "Cho_Wet": "chorus_dry_wet",
    "Cho_Dep": "chorus_mod_depth",
    "Dist_Drv": "distortion_drive",
    "Dist_Wet": "distortion_mix",
    "Phs_Wet": "phaser_dry_wet",
    "Phs_Frq": "phaser_center",
    "Flg_Wet": "flanger_dry_wet",
    "FX Fil Freq": "filter_fx_cutoff",
    "FX Fil Reso": "filter_fx_resonance",
    "Macro 1": "macro_control_1",
    "Macro 2": "macro_control_2",
    "Macro 3": "macro_control_3",
    "Macro 4": "macro_control_4",
    "PortTime": "portamento_time",
    "Mast.Tun": "voice_tune",
    "A Uni Warp": "osc_1_distortion_spread",
    "B Uni Warp": "osc_2_distortion_spread",
    "A Uni WTPos": "osc_1_frame_spread",
    "B Uni WTPos": "osc_2_frame_spread",
    "FX Fil Var": "filter_fx_blend",
    "FX Fil Wet": "filter_fx_mix",
    "FX Fil Drive": "filter_fx_drive",
    "Dist_Freq": "distortion_filter_cutoff",
    "Cmp_Thr": "compressor_band_upper_threshold",
    "EQ FrqL": "eq_low_cutoff",
    "EQ FrqH": "eq_high_cutoff",
    "EQ VolL": "eq_low_gain",
    "EQ VolH": "eq_high_gain",
    "EQ Q L": "eq_low_resonance",
    "EQ Q H": "eq_high_resonance",
    "VerbDecay": "reverb_decay_time",
    "VerbSpinDepth": "reverb_chorus_amount",
    "Cmp_Rat": "compressor_band_upper_ratio",
    "Dly_TimL": "delay_tempo",
    "Dly_TimR": "delay_aux_tempo",
    "Cho_Rate": "chorus_frequency",
    "Cho_Feed": "chorus_feedback",
    "Phs_Dpth": "phaser_mod_depth",
    "Phs_Feed": "phaser_feedback",
    "Flg_Feed": "flanger_feedback",
    "Flg_Dep": "flanger_mod_depth",
    "VerbLoCt": "reverb_pre_low_cutoff",
    "VerbHiCt": "reverb_high_shelf_cutoff",
    "Amp.": "volume",
    "Hyp_Wet": "chorus_dry_wet",
    "Hyp_Detune": "chorus_mod_depth",
    "Hyp_Rate": "chorus_frequency",
    "HypDim_Mix": "chorus_dry_wet",
    "HypDim_Size": "chorus_delay_1",
}


def convert_serum1(patch: serum1.Serum1Patch) -> Conversion:
    """Build a :class:`Conversion` from a parsed Serum 1 preset."""
    conv = Conversion(
        name=patch.name,
        author=patch.author,
        comments=f"Converted from Serum: {patch.menu}".strip().rstrip(":").strip(),
        macro_names=[n or f"MACRO {i + 1}" for i, n in enumerate(patch.macro_names)],
    )

    # Master volume is cubic in amplitude; keep Serum's default (-9.3 dB) at
    # Vital's default (-6.02 dB) and preserve the relative level otherwise.
    # -1.6 dB: measured level offset between the two synths at equal settings.
    master_db = st.master_db(_p(patch, "MasterVol")) - st.master_db(0.7) - 1.6
    # Serum's filter drive is a plain gain into the filter (+7.6 dB at 25%,
    # +16 dB at 100% measured); Vital's drive is level-compensated, so the
    # difference is applied at the master when something is routed through it.
    if _p(patch, "Filter On") > 0.5 and _p(patch, "Fil Driv") > 0.0 and (
        _p(patch, "OscA>Fil") > 0.5 or _p(patch, "OscB>Fil") > 0.5 or _p(patch, "OscS>Fil") > 0.5
    ):
        # Measured on a cutoff x drive grid (MG Low 12/24): with 12 dB*n at the
        # master Vital still came out 1.9 / 3.4 / 4.3 dB quieter than Serum at
        # drive 25 / 50 / 100%, so that residual is added on top.
        drive = _p(patch, "Fil Driv")
        drive_gain = 12.0 * drive + (4.4 * drive ** 0.6 if CALIB["drive_residual"] else 0.0)
        if -6.02 + master_db + drive_gain > 6.0:
            conv.note("approximation: filter drive gain exceeds Vital's headroom; master clamped at +6 dB")
        master_db += drive_gain
    conv.set("volume", db_to_volume(-6.02 + master_db))

    _osc_from_serum1(conv, patch, "A", 1)
    _osc_from_serum1(conv, patch, "B", 2)

    # Serum's sub oscillator becomes Vital oscillator 3.
    sub_on = _p(patch, "Osc S On") > 0.5
    conv.set("osc_3_on", 1.0 if sub_on else 0.0)
    if sub_on:
        # Measured against Serum: the sub's level knob is linear in amplitude
        # (A/B Vol and Vital's level are quadratic) and its full scale sits
        # 3.7 dB below Vital's osc 3 playing sin.wav at level 1.
        sub_level = _p(patch, "Sub Osc Level")
        conv.set("osc_3_level", math.sqrt(sub_level) * 10 ** (-3.7 / 40) if CALIB["sub_linear"] else sub_level)
        conv.set("osc_3_pan", _display(patch, "Sub Osc Pan") / 50.0)
        conv.set("osc_3_transpose", 12 * round(_display(patch, "SubOscOctave")))
        conv.set("osc_3_destination", 0.0 if _p(patch, "OscS>Fil") > 0.5 else 3.0)
        # Serum's sub is phase-locked at note-on (measured on all five shapes).
        conv.set("osc_3_phase", serum_phase_to_vital(0.5))
        conv.set("osc_3_random_phase", 0.0)
        shape_index = st.indexed(_p(patch, "SubOscShape"), (4,))
        shape = st.SUB_SHAPE_NAMES[shape_index] if shape_index is not None and shape_index < 5 else "Sine"
        conv.wavetable_refs[2] = SUB_SHAPE_FILES.get(shape, "sin.wav")

    # Serum's noise oscillator becomes Vital's sample source.
    noise_on = _p(patch, "Osc N On") > 0.5
    conv.set("sample_on", 1.0 if noise_on else 0.0)
    if noise_on:
        conv.set("sample_level", _p(patch, "Noise Level"))
        conv.set("sample_pan", _display(patch, "Noise Pan") / 50.0)
        conv.set("sample_loop", 0.0 if patch.settings.noise_one_shot else 1.0)
        conv.set("sample_random_phase", 1.0 if _p(patch, "Noise RandPhase") > 0.5 else 0.0)
        conv.set("sample_keytrack", 1.0 if patch.settings.noise_pitch_track else 0.0)
        conv.set("sample_destination", 0.0 if _p(patch, "OscN>Fil") > 0.5 else 3.0)
        # Serum's noise pitch knob: +48 semitones at the top (centroids and
        # levels match Vital's sample transpose at 60/75/100%), but below the
        # centre the playback rate collapses much faster, about 100*log2(2v)
        # semitones (-35 st at 40%, -100 st at 25%), so Vital's -48 floor is
        # reached below 36%.
        pitch = _p(patch, "Noise Pitch")
        if pitch >= 0.5:
            semis = (pitch - 0.5) * 96.0
        else:
            semis = max(-48.0, 100.0 * math.log2(max(2.0 * pitch, 1e-3)))
        conv.set("sample_transpose", round(semis))
        conv.set("sample_tune", _display(patch, "Noise Fine"))

    _filter_from_serum1(conv, patch)
    _envelopes_from_serum1(conv, patch)
    _lfos_from_serum1(conv, patch)
    _chaos_from_serum1(conv, patch)
    _effects_from_serum1(conv, patch)

    for index in range(1, 5):
        conv.set(f"macro_control_{index}", _p(patch, f"Macro {index}"))

    porta = st.portamento_seconds(_p(patch, "PortTime"))
    conv.set("portamento_time", -10.0 if porta < 0.001 else max(-10.0, math.log2(porta)))
    conv.set("pitch_bend_range", abs(_display(patch, "Bend U")))
    settings = patch.settings
    if settings.mono:
        conv.set("polyphony", 1.0)
        conv.set("legato", 1.0 if settings.legato else 0.0)
    else:
        conv.set("polyphony", float(max(1, min(32, settings.polyphony))))
    conv.set("portamento_force", 1.0 if settings.porta_always else 0.0)
    conv.set("portamento_scale", 1.0 if settings.porta_scaled else 0.0)
    # Serum's Global page: oversampling 1x/2x/4x (Vital: 1x/2x/4x/8x) and the
    # A4 reference (430..450 Hz), which Vital only has as a global fine tune.
    conv.set("oversampling", float(settings.oversampling))
    if abs(settings.a4_hz - 440.0) > 0.01:
        cents = 1200.0 * math.log2(settings.a4_hz / 440.0)
        conv.set("voice_tune", max(-1.0, min(1.0, cents / 100.0)))
    if not settings.known:
        conv.note("approximation: preset predates Serum's voicing/unison/noise switch block; defaults assumed")

    # An empty table name means Serum's built-in default table (saw first).
    conv.wavetable_refs[0] = patch.wavetable_a or (DEFAULT_TABLE if _p(patch, "Osc A On") > 0.5 else None)
    conv.wavetable_refs[1] = patch.wavetable_b or (DEFAULT_TABLE if _p(patch, "Osc B On") > 0.5 else None)
    conv.sample_ref = patch.noise_sample or None

    _modulations_from_serum1(conv, patch)
    return conv


# --------------------------------------------------------------------------
# Serum 2
# --------------------------------------------------------------------------

# Serum 2 modulation sources, verified by correlating source ids against which
# module a preset actually edits (LFO block matched at 0.86-1.00).
SERUM2_SOURCES = {
    # Menu ids captured with the fixtures DebugPresets/12 sources.SerumPreset
    # and 12b sources extra.SerumPreset (one known source per matrix row).
    1: "mod_wheel", 16: "velocity", 17: "note", 18: "aftertouch",
    19: "poly_aftertouch", 20: "noise_osc",
    21: "note_random_1", 22: "note_random_2", 23: "note_alt_1", 24: "note_alt_2",
    33: "pitch_bend", 34: "mpe_x", 35: "mpe_y", 36: "mpe_z",
    37: "release_velocity", 38: "fixed",
}
for _i in range(4):
    SERUM2_SOURCES[2 + _i] = f"env_{_i + 1}"
for _i in range(8):  # Vital only has 8 LFOs; Serum 2 has 10
    SERUM2_SOURCES[6 + _i] = f"lfo_{_i + 1}"
for _i in range(4):  # Vital only has 4 macros; Serum 2 has 8
    SERUM2_SOURCES[25 + _i] = f"macro_{_i + 1}"

# Serum 2 sources that Vital cannot provide (audio-rate and voice bookkeeping
# sources), named so the conversion report can say what was dropped.
SERUM2_UNSUPPORTED_SOURCES = {
    14: "LFO 9", 15: "LFO 10",
    29: "Macro 5", 30: "Macro 6", 31: "Macro 7", 32: "Macro 8",
    49: "OSC A audio", 50: "OSC B audio", 51: "OSC C audio", 52: "Sub OSC audio",
    53: "Filter 1 audio", 54: "Filter 2 audio", 55: "Active Voices",
    56: "Voice Mod 1", 57: "Voice Mod 2", 58: "Voice Index", 59: "NoteOn Rand (Discrete)",
}

# Serum 2 range / Vital range for destinations whose ranges differ: the pitch
# controls are +-64 st (CoarsePit), +-12 st (Pitch) and +-4 oct (Octave) and
# all land on Vital's +-48 st transpose.
SERUM2_AMOUNT_SCALE = {
    ("Oscillator", "kParamCoarsePit"): 128.0 / 96.0,
    ("Oscillator", "kParamPitch"): 24.0 / 96.0,
    ("Oscillator", "kParamOctave"): 1.0,
}

# Serum 2 destinations, addressed as (module type, module index, parameter).
SERUM2_DEST = {
    ("Oscillator", "kParamVolume"): "osc_{n}_level",
    ("Oscillator", "kParamPan"): "osc_{n}_pan",
    ("Oscillator", "kParamFine"): "osc_{n}_tune",
    ("Oscillator", "kParamCoarsePit"): "osc_{n}_transpose",
    ("Oscillator", "kParamPitch"): "osc_{n}_transpose",
    ("Oscillator", "kParamOctave"): "osc_{n}_transpose",
    ("Oscillator", "kParamDetune"): "osc_{n}_unison_detune",
    ("WTOsc", "kParamTablePos"): "osc_{n}_wave_frame",
    ("WTOsc", "kParamWarp"): "osc_{n}_distortion_amount",
    ("VoiceFilter", "kParamFreq"): "filter_{n}_cutoff",
    ("VoiceFilter", "kParamReso"): "filter_{n}_resonance",
    ("VoiceFilter", "kParamDrive"): "filter_{n}_drive",
    ("VoiceFilter", "kParamWet"): "filter_{n}_mix",
    ("VoiceFilter", "kParamVar"): "filter_{n}_blend",
    ("Global", "kParamMasterTuning"): "voice_tune",
    ("LFO", "kParamRate"): "lfo_{n}_rate",
    ("Env", "kParamAttack"): "env_{n}_attack",
    ("Env", "kParamDecay"): "env_{n}_decay",
    ("Env", "kParamSustain"): "env_{n}_sustain",
    ("Env", "kParamRelease"): "env_{n}_release",
    ("Macro", "kParamValue"): "macro_control_{n}",
    ("FXReverb", "kParamWet"): "reverb_dry_wet",
    ("FXDelay", "kParamWet"): "delay_dry_wet",
    ("FXChorus", "kParamWet"): "chorus_dry_wet",
    ("FXDistortion", "kParamDrive"): "distortion_drive",
    ("FXDistortion", "kParamWet"): "distortion_mix",
    ("FXFilter", "kParamFreq"): "filter_fx_cutoff",
    ("FXFilter", "kParamReso"): "filter_fx_resonance",
    ("FXFilter", "kParamWet"): "filter_fx_mix",
    ("Global", "kParamMasterVolume"): "volume",
}

# Serum 2 warp menu names -> Vital distortion type (see WARP_TO_VITAL for the
# Vital numbering).
SERUM2_WARP = {
    "kSync": (1, True), "kBendPos": (5, False), "kBendNeg": (5, False), "kBendPosNeg": (5, False),
    "kPWM": (6, True), "kASYMPos": (4, False), "kASYMNeg": (4, False), "kQuantize": (3, True),
    "kFM_OSC": (7, True), "kFM_OSC2": (8, True), "kFM_SUB": (8, True), "kFM_NOISE": (9, True),
    "kRM_OSC": (10, True), "kRM_OSC2": (11, True), "kRM_SUB": (11, True), "kRM_NOISE": (12, True),
    "kAM_OSC": (10, False), "kAM_OSC2": (11, False), "kAM_SUB": (11, False), "kAM_NOISE": (12, False),
    "kPD_OSC": (7, False), "kPD_OSC2": (8, False), "kPD_SUB": (8, False), "kPD_NOISE": (9, False),
    "kFMP_OSC": (7, False), "kFMP_NOISE": (9, False), "kFMX_OSC": (7, False), "kFMX_OSC2": (8, False),
}

# Serum 2 defaults for the parameters we read, since the format only stores
# values that differ from the default.
S2_DEFAULTS = {
    ("Env", "kParamAttack"): 0.005,
    ("Env", "kParamHold"): 0.0,
    ("Env", "kParamDecay"): 2.0,
    ("Env", "kParamSustain"): 1.0,
    ("Env", "kParamRelease"): 0.075,
    ("Env", "kParamCurve1"): 50.0,
    ("Env", "kParamCurve2"): 66.6,
    ("Env", "kParamCurve3"): 66.6,
    ("Oscillator", "kParamVolume"): 0.75,
    ("Oscillator", "kParamPan"): 0.0,
    ("Oscillator", "kParamOctave"): 0.0,
    ("Oscillator", "kParamSemi"): 0.0,
    ("Oscillator", "kParamFine"): 0.0,
    ("Oscillator", "kParamUnison"): 1.0,
    ("Oscillator", "kParamDetune"): 0.2,
    ("Oscillator", "kParamDetuneWid"): 100.0,
    ("VoiceFilter", "kParamFreq"): 1.0,
    ("VoiceFilter", "kParamReso"): 10.0,
    ("VoiceFilter", "kParamDrive"): 0.0,
    ("VoiceFilter", "kParamWet"): 100.0,
    ("VoiceFilter", "kParamLevelOut"): 1.0,
    ("Global", "kParamMasterVolume"): 0.7,
    ("Macro", "kParamValue"): 0.0,
    ("LFO", "kParamRate"): 6.25,   # 100 * 0.5**4: the 1/4-note default position
}

S2_STACKS = {"kOctave1": 3, "kOctave2": 4, "kOctave3": 4, "kOctaveFifth1": 5, "kOctaveFifth2": 6,
             "kOctaveFifth3": 6, "kCenter12": 1, "kCenter24": 2}
S2_SUB_SHAPES = {"kSine": "sin.wav", "kRoundRect": "roundrect.wav", "kTriangle": "triangle.wav",
                 "kSquare": "square.wav", "kSaw": "saw.wav", "kPulse": "pulse.wav"}


def _s2_default(module_type: str, key: str, fallback: float = 0.0) -> float:
    return S2_DEFAULTS.get((module_type, key), fallback)


# Serum 2 routing matrix (RoutingSlot<n>, one per sound source: 0-2 oscillators,
# 3 noise, 4 sub) -> Vital oscillator destinations (0 filter 1, 3 effects,
# 4 direct out).  Slot 0 defaults to the filter, the others to the effects
# chain; "None" means the source only reaches the output through the FX
# buses, which the converter flattens into the effect chain.
S2_ROUTING_DEST = {
    "kRoutingDestFilter": 0.0,
    "kRoutingDestDirect": 3.0,
    "kRoutingDestNone": 3.0,
    "kRoutingDestMaster": 4.0,
}


def _s2_routing(conv: "Conversion", patch, slot: int, volume: float, what: str) -> tuple[float, float]:
    """Return (level, destination) for Serum 2 source `slot`.

    A source whose level knob is at zero but which is sent to an FX bus is
    audible in Serum through that bus; its send level is used as the level.
    """
    routing = patch.plain_params(f"RoutingSlot{slot}")
    dest_name = routing.get("kParamRoutingDest", "kRoutingDestFilter" if slot == 0 else "kRoutingDestDirect")
    destination = S2_ROUTING_DEST.get(dest_name, 0.0 if slot == 0 else 3.0)
    bus = max(float(routing.get("kParamFXBus1Level", 0.0)), float(routing.get("kParamFXBus2Level", 0.0))) / 100.0
    level = max(volume, 0.0)
    if level < 0.05 and bus > 0.0:
        level = bus
        conv.note(f"approximation: {what} reaches the output only through an FX bus at {bus * 100:.0f}%; used as its level")
    return level, destination


def s2_lfo_settings(params: dict) -> serum1.LfoSettings:
    mode = params.get("kParamMode")
    return serum1.LfoSettings(
        hz_mode=params.get("kParamBeatSync", 1.0) < 0.5,
        dotted=params.get("kParamDotted", 0.0) > 0.5,
        triplet=params.get("kParamTriplets", 0.0) > 0.5,
        anchor=params.get("kParamAnchored", 1.0) > 0.5,
        mode={"Envelope": "env", "Free": "off"}.get(mode, "trig"),
    )


def s2_lfo_shape(module: dict, settings: serum1.LfoSettings) -> serum1.LfoShape:
    curve = module.get("curveData") if isinstance(module, dict) else None
    if not isinstance(curve, dict) or not curve.get("xVals"):
        # Serum 2's default shape is the same half-saw as Serum 1's.
        return serum1.LfoShape(xs=[0.0, 0.5, 1.0], ys=[0.0, 1.0, 1.0], curves=[0.5, 0.5], settings=settings)
    xs = [float(x) for x in curve.get("xVals", [])]
    ys = [float(y) for y in curve.get("yVals", [])]
    tension = [float(c) for c in curve.get("curveVals", [])]
    count = len(xs)
    for i, x in enumerate(xs):
        if x >= 1.0 - 1e-9:
            count = i + 1
            break
    return serum1.LfoShape(xs=xs[:count], ys=ys[:count], curves=tension[: max(count - 1, 1)], settings=settings)


def convert_serum2(patch) -> Conversion:
    """Build a :class:`Conversion` from a parsed Serum 2 preset.

    Serum 2's architecture is wider than Vital's (5 oscillator slots including
    granular/multisample/spectral engines, 10 LFOs, 8 macros, 3 FX racks), so
    this maps the parts that have a Vital counterpart and reports the rest.
    """
    from .wavetables import lfo_to_vital

    conv = Conversion(
        name=patch.name,
        author=patch.author,
        comments=(patch.description or "").strip(),
        style=patch.tags[0] if patch.tags else "",
    )

    master = patch.param("Global0", "kParamMasterVolume", _s2_default("Global", "kParamMasterVolume"))
    # Same 1.6 dB synth offset as the Serum 1 path, plus Serum 2 rendering 1.4 dB
    # below Serum 1 at identical Init settings (crafted-fixture baselines: the
    # converted Init came out 3.0 dB above Serum 2's own render).
    master_db = st.master_db(max(master, 1e-3)) - st.master_db(0.7) - S2_LEVEL_OFFSET_DB
    conv.set("volume", db_to_volume(-6.02 + master_db))

    # Oscillators: Serum 2 slots 0..2 are the general engines, 3 is noise and
    # 4 is the sub.  Vital gets 1..3 plus its sample source.
    for source_index, vital_slot in ((0, 1), (1, 2), (2, 3)):
        module = f"Oscillator{source_index}"
        params = patch.plain_params(module)
        enabled = params.get("kParamEnable", 1.0 if source_index == 0 else 0.0)
        conv.set(f"osc_{vital_slot}_on", 1.0 if enabled > 0.5 else 0.0)
        if enabled <= 0.5:
            continue

        kind = patch.osc_type(source_index)
        if kind not in ("kOsc_Wavetable", "kOsc_Sample"):
            conv.note(
                f"unsupported: oscillator {source_index + 1} uses Serum 2's {kind} engine; "
                "converted as a wavetable oscillator only"
            )

        volume = params.get("kParamVolume", _s2_default("Oscillator", "kParamVolume"))
        level, destination = _s2_routing(conv, patch, source_index, volume, f"oscillator {source_index + 1}")
        conv.set(f"osc_{vital_slot}_level", level)
        conv.set(f"osc_{vital_slot}_destination", destination)
        conv.set(f"osc_{vital_slot}_pan", params.get("kParamPan", 0.0) / 50.0)
        # Serum 2 splits pitch into an octave switch and a semitone control
        # named kParamPitch (there is no kParamSemi).
        octave = params.get("kParamOctave", 0.0)
        conv.set(f"osc_{vital_slot}_transpose", 12 * octave + params.get("kParamPitch", 0.0))
        conv.set(f"osc_{vital_slot}_tune", params.get("kParamFine", 0.0) / 100.0)
        conv.set(f"osc_{vital_slot}_unison_voices", max(1, round(params.get("kParamUnison", 1.0))))
        conv.set(f"osc_{vital_slot}_unison_detune", 10.0 * math.sqrt(max(0.0, params.get("kParamDetune", 0.2))))
        conv.set(f"osc_{vital_slot}_stereo_spread", params.get("kParamDetuneWid", 100.0) / 100.0)
        stack = params.get("kParamUnisonStack")
        if isinstance(stack, str):
            conv.set(f"osc_{vital_slot}_stack_style", S2_STACKS.get(stack, 0))

        wt = patch.module(module).get(f"WTOsc{source_index}", {})
        if isinstance(wt, dict) and isinstance(wt.get("relativePathToWT"), str):
            conv.wavetable_refs[vital_slot - 1] = wt["relativePathToWT"]
        wt_params = wt.get("plainParams") if isinstance(wt, dict) else None
        phase_params = wt_params if isinstance(wt_params, dict) else {}
        conv.set(f"osc_{vital_slot}_random_phase", phase_params.get("kParamRandomPhase", 100.0) / 100.0)
        conv.set(f"osc_{vital_slot}_phase", serum_phase_to_vital(phase_params.get("kParamInitialPhase", 180.0) / 360.0))
        if isinstance(wt_params, dict):
            # kParamTablePos is a 1-based frame index, so normalise it against
            # the table's own frame count before scaling to Vital's 0..256.
            frames = 1
            if isinstance(wt, dict) and isinstance(wt.get("numFrames"), int):
                frames = max(1, wt["numFrames"] // 2048)
            position = (wt_params.get("kParamTablePos", 1.0) - 1.0) / max(frames - 1, 1)
            conv.set(f"osc_{vital_slot}_wave_frame", 256.0 * max(0.0, min(1.0, position)))
            warp = wt_params.get("kParamWarpMenu")
            amount = wt_params.get("kParamWarp", 0.0) / 100.0
            if isinstance(warp, str):
                mapped = SERUM2_WARP.get(warp)
                if mapped is None:
                    conv.set(f"osc_{vital_slot}_distortion_type", 0.0)
                    conv.note(f"unsupported: oscillator {source_index + 1} warp '{warp}' has no Vital equivalent; left off")
                else:
                    vital_type, exact = mapped
                    conv.set(f"osc_{vital_slot}_distortion_type", vital_type)
                    if vital_type in (4, 5) and warp.endswith(("Pos", "Neg")):
                        amount = 0.5 + 0.5 * amount if warp.endswith("Pos") else 0.5 - 0.5 * amount
                    conv.set(f"osc_{vital_slot}_distortion_amount", amount)
                    if not exact:
                        conv.note(f"approximation: oscillator {source_index + 1} warp '{warp}' -> Vital distortion type {vital_type}")
            if wt_params.get("kParamWarpMenu2"):
                conv.note(f"conflict: oscillator {source_index + 1} second warp slot '{wt_params['kParamWarpMenu2']}' dropped (Vital has one)")

    # Sub and noise oscillators.
    sub = patch.plain_params("Oscillator4")
    if sub.get("kParamEnable", 0.0) > 0.5 and conv.get("osc_3_on") < 0.5:
        conv.set("osc_3_on", 1.0)
        level, destination = _s2_routing(conv, patch, 4, sub.get("kParamVolume", 0.75), "sub oscillator")
        conv.set("osc_3_level", level)
        conv.set("osc_3_destination", destination)
        conv.set("osc_3_transpose", 12 * sub.get("kParamOctave", 0.0))
        shape = patch.module("Oscillator4").get("SubOsc4", {}).get("plainParams", {})
        conv.wavetable_refs[2] = S2_SUB_SHAPES.get(shape.get("kParamShape") if isinstance(shape, dict) else None, "sin.wav")
        sub_phase = shape.get("kParamInitialPhase", 180.0) if isinstance(shape, dict) else 180.0
        conv.set("osc_3_phase", serum_phase_to_vital(float(sub_phase) / 360.0))
        conv.set("osc_3_random_phase", 0.0)
    elif sub.get("kParamEnable", 0.0) > 0.5:
        conv.note("conflict: Serum 2 sub oscillator dropped (Vital's third oscillator is taken by oscillator 3)")
    noise = patch.plain_params("Oscillator3")
    if noise.get("kParamEnable", 0.0) > 0.5:
        conv.set("sample_on", 1.0)
        level, destination = _s2_routing(conv, patch, 3, noise.get("kParamVolume", 0.75), "noise oscillator")
        conv.set("sample_level", level)
        conv.set("sample_destination", destination)
        conv.set("sample_pan", noise.get("kParamPan", 0.0) / 50.0)
        conv.set("sample_loop", 1.0)
        noise_module = patch.module("Oscillator3").get("NoiseOsc3", {})
        if isinstance(noise_module, dict) and isinstance(noise_module.get("relativePathToNoiseSample"), str):
            conv.sample_ref = noise_module["relativePathToNoiseSample"]

    # Envelopes.
    for source_index in range(4):
        vital_slot = source_index + 1
        params = patch.plain_params(f"Env{source_index}")
        attack = params.get("kParamAttack", _s2_default("Env", "kParamAttack"))
        decay = params.get("kParamDecay", _s2_default("Env", "kParamDecay"))
        release = params.get("kParamRelease", _s2_default("Env", "kParamRelease"))
        hold = params.get("kParamHold", 0.0)
        sustain = params.get("kParamSustain", _s2_default("Env", "kParamSustain"))

        # Serum 2 stores seconds; Vital stores seconds ** (1/4).
        conv.set(f"env_{vital_slot}_attack", max(attack, 0.0) ** 0.25)
        conv.set(f"env_{vital_slot}_hold", min(ENV_HOLD_MAX, max(hold, 0.0) ** 0.25))
        conv.set(f"env_{vital_slot}_decay", max(decay, 0.0) ** 0.25)
        conv.set(f"env_{vital_slot}_release", max(release, 0.0) ** 0.25)
        conv.set(f"env_{vital_slot}_sustain", sustain)

        for key, vital_key in (
            ("kParamCurve1", "attack_power"),
            ("kParamCurve2", "decay_power"),
            ("kParamCurve3", "release_power"),
        ):
            curve = params.get(key, _s2_default("Env", key)) / 100.0
            conv.set(f"env_{vital_slot}_{vital_key}", env_power(curve, vital_key.split("_")[0], vital_slot == 1))

    # Filters.
    for source_index, vital_slot in ((0, 1), (1, 2)):
        params = patch.plain_params(f"VoiceFilter{source_index}")
        enabled = params.get("kParamEnable", 0.0)
        conv.set(f"filter_{vital_slot}_on", 1.0 if enabled > 0.5 else 0.0)
        if enabled <= 0.5:
            continue
        cutoff = serum_cutoff_to_note(params.get("kParamFreq", 1.0))
        conv.set(f"filter_{vital_slot}_cutoff", cutoff)
        conv.set(f"filter_{vital_slot}_resonance", params.get("kParamReso", 10.0) / 100.0)
        conv.set(f"filter_{vital_slot}_drive", 20.0 * params.get("kParamDrive", 0.0) / 100.0)
        conv.set(f"filter_{vital_slot}_mix", params.get("kParamWet", 100.0) / 100.0)
        conv.set(f"filter_{vital_slot}_filter_input", 0.0)
        conv.set(f"filter_{vital_slot}_keytrack", params.get("kParamKeyTrack", 0.0) / 100.0)
        name = params.get("kParamType", "MgL12")
        apply_filter_target(conv, f"filter_{vital_slot}", name, params.get("kParamVar", 0.0) / 100.0, cutoff, serum2=True)

    # LFOs.
    for source_index in range(8):
        module = patch.module(f"LFO{source_index}")
        params = patch.plain_params(f"LFO{source_index}")
        settings = s2_lfo_settings(params)
        slot = source_index + 1
        kind = params.get("kParamType")
        if isinstance(kind, str) and kind != "Path":
            conv.note(f"approximation: LFO {slot} is a Serum 2 '{kind}' generator; converted as a shaped LFO")
        shape = s2_lfo_shape(module, settings)
        conv.lfos[source_index] = lfo_to_vital(shape, name=f"Serum LFO {slot}")
        rate = params.get("kParamRate", _s2_default("LFO", "kParamRate"))
        # Both modes store 100 * knob**4; the synced knob quantises to divisions.
        rate_norm = max(0.0, min(1.0, (max(rate, 0.0) / 100.0) ** 0.25))
        apply_lfo_settings(conv, slot, settings, rate_norm)
        if params.get("kParamRise"):
            conv.set(f"lfo_{slot}_fade_time", min(4.0, params["kParamRise"]))
        if params.get("kParamDelay"):
            conv.set(f"lfo_{slot}_delay_time", min(4.0, params["kParamDelay"]))
        if isinstance(params.get("kParamPhase"), (int, float)):
            conv.set(f"lfo_{slot}_phase", (float(params["kParamPhase"]) / 360.0) % 1.0)
    if any(patch.plain_params(f"LFO{i}") for i in (8, 9)):
        conv.note("unsupported: Serum 2 LFOs 9-10 have no Vital counterpart and were dropped")

    # Macros (Vital has 4, Serum 2 has 8).
    for source_index in range(4):
        params = patch.plain_params(f"Macro{source_index}")
        conv.set(f"macro_control_{source_index + 1}", params.get("kParamValue", 0.0) / 100.0)
        name = patch.module(f"Macro{source_index}").get("name")
        if isinstance(name, str) and name.strip():
            conv.macro_names[source_index] = name.strip()
    if any(patch.plain_params(f"Macro{i}") for i in range(4, 8)):
        conv.note("unsupported: Serum 2 macros 5-8 have no Vital counterpart and were dropped")

    glob = patch.plain_params("Global0")
    if glob.get("kParamPolyCount"):
        conv.set("polyphony", max(1.0, min(32.0, glob["kParamPolyCount"])))
    if glob.get("kParamMonoToggle", 0.0) > 0.5:
        conv.set("polyphony", 1.0)
        conv.set("legato", 1.0 if glob.get("kParamLegato", 0.0) > 0.5 else 0.0)
    if glob.get("kParamPortamentoTime"):
        conv.set("portamento_time", max(-10.0, math.log2(max(1e-3, glob["kParamPortamentoTime"]))))
    if glob.get("kParamBendRangeUp"):
        conv.set("pitch_bend_range", abs(glob["kParamBendRangeUp"]))

    _modulations_from_serum2(conv, patch)
    if serum2_fx is not None:
        try:
            serum2_fx.convert_fx_racks(patch, conv)
        except Exception as exc:  # keep the rest of the conversion
            conv.note(f"unknown: effect racks not converted ({exc})")
    else:
        conv.note("unsupported: Serum 2 effect racks are not converted (serum2_fx unavailable)")
    return conv


def _modulations_from_serum2(conv: Conversion, patch) -> None:
    for name in sorted(patch.state, key=lambda k: (len(k), k)):
        if not name.startswith("ModSlot"):
            continue
        slot = patch.state[name]
        if not isinstance(slot, dict) or not isinstance(slot.get("source"), list):
            continue

        source_id, aux_id = (list(slot["source"]) + [0, 0])[:2]
        source = SERUM2_SOURCES.get(source_id)
        if source is None:
            if 29 <= source_id <= 32:
                conv.note("unsupported: modulations from Serum 2 macros 5-8 dropped (Vital has 4 macros)")
            elif 14 <= source_id <= 15:
                conv.note("unsupported: modulations from Serum 2 LFOs 9-10 dropped (Vital has 8 LFOs)")
            elif source_id in SERUM2_UNSUPPORTED_SOURCES:
                conv.note(f"unsupported: Serum 2 source '{SERUM2_UNSUPPORTED_SOURCES[source_id]}' has no Vital equivalent; routing dropped")
            else:
                conv.note(f"unknown: Serum 2 modulation source id {source_id} not identified; routing dropped")
            continue

        module_type = slot.get("destModuleTypeString")
        module_index = slot.get("destModuleID", 0)
        param_name = slot.get("destModuleParamName")
        template = SERUM2_DEST.get((module_type, param_name))
        if template is None:
            conv.note(f"unsupported: modulation destination {module_type}.{param_name} has no Vital equivalent")
            continue

        n = int(module_index) + 1
        if module_type == "Oscillator" and n in (4, 5):
            # Serum 2 slot 4 is the noise oscillator, slot 5 the sub.
            leaf = template.split("_", 2)[2]
            destination = f"sample_{leaf}" if n == 4 else f"osc_3_{leaf}"
        elif template == "lfo_{n}_rate":
            destination = f"lfo_{n}_frequency" if n <= 8 and conv.lfo_hz_mode[n - 1] else f"lfo_{n}_tempo"
        else:
            destination = template.format(n=n) if "{n}" in template else template
        if destination not in DEFAULTS:
            conv.note(f"unsupported: modulation destination {destination!r} is outside Vital's parameter set")
            continue

        params = slot.get("plainParams")
        amount = params.get("kParamAmount", 0.0) if isinstance(params, dict) else 0.0
        if abs(amount) < 1e-6:
            continue
        amount *= SERUM2_AMOUNT_SCALE.get((module_type, param_name), 1.0)
        bipolar = isinstance(params, dict) and params.get("kParamBipolar", 0.0) > 0.5
        aux = SERUM2_SOURCES.get(aux_id) if aux_id else None
        if aux_id and aux is None:
            if aux_id in SERUM2_UNSUPPORTED_SOURCES:
                conv.note(f"approximation: aux source '{SERUM2_UNSUPPORTED_SOURCES[aux_id]}' has no Vital counterpart; routing applied without it")
            else:
                conv.note(f"unknown: Serum 2 aux source id {aux_id} not identified; routing applied without it")
        vital_source = SOURCE_TO_VITAL.get(source, source)
        if vital_source is None:
            conv.note(f"unsupported: modulation source '{source}' has no Vital counterpart; routing dropped")
            continue
        vital_aux = SOURCE_TO_VITAL.get(aux, aux) if aux else None
        if aux and vital_aux is None:
            conv.note(f"approximation: aux source '{aux}' has no Vital counterpart; routing applied without it")
        if vital_aux:
            index = conv.add_modulation(vital_source, destination, 0.0, bipolar)
            if index is not None:
                conv.add_modulation(vital_aux, f"modulation_{index}_amount", amount / 200.0, False)  # amount spans -1..1
        else:
            conv.add_modulation(vital_source, destination, amount / 100.0, bipolar)
