"""Effect helpers shared by the Serum 1 and Serum 2 conversion paths.

Everything here is about Vital's effect section: the chain-order encoding,
the Hyper/Dimension -> chorus approximation, distortion mode and filter
type tables, and a few knob laws measured from Serum 1 (which Serum 2 kept).
Nothing in this module reads a preset; callers pass real units in.
"""

from __future__ import annotations

import math
import re

# --------------------------------------------------------------------------
# effect chain order
# --------------------------------------------------------------------------

# Vital's effect indices (the order used by utils::encodeOrderToFloat).
VITAL_EFFECTS = [
    "chorus",
    "compressor",
    "delay",
    "distortion",
    "eq",
    "filter_fx",
    "flanger",
    "phaser",
    "reverb",
]
VITAL_EFFECT_INDEX = {name: i for i, name in enumerate(VITAL_EFFECTS)}

# Serum rack module names -> the Vital effect that hosts them.
SERUM_TO_VITAL_EFFECT = {
    "distortion": "distortion",
    "flanger": "flanger",
    "phaser": "phaser",
    "chorus": "chorus",
    "delay": "delay",
    "compressor": "compressor",
    "reverb": "reverb",
    "eq": "eq",
    "filter": "filter_fx",
    "hyper": "chorus",
}


def encode_effect_order(order: list[str]) -> float:
    """Vital's `effect_chain_order` for a permutation of the 9 effect names.

    Implements utils::encodeOrderToFloat: a factorial-number-system code where
    digit i counts how many earlier chain positions hold a larger index.
    """
    if sorted(order) != sorted(VITAL_EFFECTS):
        raise ValueError(f"order must be a permutation of {VITAL_EFFECTS}, got {order}")
    indices = [VITAL_EFFECT_INDEX[name] for name in order]
    code = 0
    for i in range(1, len(indices)):
        index = sum(1 for j in range(i) if indices[i] < indices[j])
        code = code * (i + 1) + index
    return float(code)


def vital_chain_from_rack(rack_names: list[str]) -> list[str]:
    """Vital effect order that preserves the relative order of a Serum rack.

    `rack_names` are Serum module names ("hyper", "distortion", ...) or Vital
    effect names; duplicates keep their first position, and effects that are
    not in the rack are appended in Vital's default order.
    """
    chain: list[str] = []
    for name in rack_names:
        vital = SERUM_TO_VITAL_EFFECT.get(name, name)
        if vital in VITAL_EFFECT_INDEX and vital not in chain:
            chain.append(vital)
    for name in VITAL_EFFECTS:
        if name not in chain:
            chain.append(name)
    return chain


# --------------------------------------------------------------------------
# units
# --------------------------------------------------------------------------


def hz_to_note(hz: float) -> float:
    return 69.0 + 12.0 * math.log2(max(hz, 1e-6) / 440.0)


def note_to_hz(note: float) -> float:
    return 440.0 * 2.0 ** ((note - 69.0) / 12.0)


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def log2_hz(hz: float, floor: float = 0.01) -> float:
    return math.log2(max(hz, floor))


# Vital's synced frequency table (kSyncedFrequencyNames), shared by every
# effect's *_tempo parameter: 0 Freeze, 1 = 32/1 ... 12 = 1/64.
VITAL_TEMPO_NAMES = ["Freeze", "32/1", "16/1", "8/1", "4/1", "2/1", "1/1", "1/2", "1/4", "1/8", "1/16", "1/32", "1/64"]
VITAL_TEMPO_INDEX = {name: i for i, name in enumerate(VITAL_TEMPO_NAMES)}

# Vital's *_sync parameters (kFrequencySyncNames).
SYNC_FREE, SYNC_TEMPO, SYNC_DOTTED, SYNC_TRIPLET = 0, 1, 2, 3


def offset_to_sync(offset: float) -> int:
    """Serum's delay-time scalar (1.5 = dotted, 1.333 = triplet) -> Vital sync mode."""
    if abs(offset - 1.5) < 0.02:
        return SYNC_DOTTED
    if abs(offset - 4.0 / 3.0) < 0.02:
        return SYNC_TRIPLET
    return SYNC_TEMPO


# Serum's modulation-effect rate knob is 0..20 Hz on a quartic law
# (measured Cho_Rate/Phs_Rate/Flg_Rate tables: Hz = 20 * n**4).  In BPM mode
# the same knob snaps to nine divisions from 8 bars to 1/32.
RATE_SYNC_DIVISIONS = ["8/1", "4/1", "2/1", "1/1", "1/2", "1/4", "1/8", "1/16", "1/32"]


def rate_hz_to_tempo_index(rate_hz: float) -> int:
    """Synced division for a Serum mod-effect rate knob stored as Hz (0..20)."""
    knob = (max(rate_hz, 0.0) / 20.0) ** 0.25
    slot = int(round(clamp01(knob) * (len(RATE_SYNC_DIVISIONS) - 1)))
    return VITAL_TEMPO_INDEX[RATE_SYNC_DIVISIONS[slot]]


# Serum 2 keeps the delay-time knob in seconds even when synced; the factory
# module presets pin 1/8 to 0.0387 s and 1/4 to 0.0832 s, so divisions sit on
# a geometric ladder with that ratio (approximate outside those two anchors).
DELAY_SYNC_ANCHOR_SECONDS = 0.03869670710330132  # "Dotted 8th Delay" / "8th Delay"
DELAY_SYNC_RATIO = 0.08316586760018929 / DELAY_SYNC_ANCHOR_SECONDS  # 1/4 over 1/8
DELAY_SYNC_ANCHOR_INDEX = VITAL_TEMPO_INDEX["1/8"]


def delay_seconds_to_tempo_index(seconds: float, lo: int = 4, hi: int = 12) -> int:
    steps = math.log(max(seconds, 1e-4) / DELAY_SYNC_ANCHOR_SECONDS) / math.log(DELAY_SYNC_RATIO)
    return max(lo, min(hi, DELAY_SYNC_ANCHOR_INDEX - int(round(steps))))


# --------------------------------------------------------------------------
# Hyper / Dimension
# --------------------------------------------------------------------------


def hyper_rate_to_hz(knob_percent: float) -> float:
    """Serum's Hyper RATE knob (0..100 %) to Hz: the knob is 20 * n**4 Hz."""
    return 20.0 * clamp01(knob_percent / 100.0) ** 4


def hyper_to_chorus(
    conv,
    *,
    wet: float,
    rate_hz: float,
    detune: float,
    voices: int,
    retrig: bool,
    dim_size: float,
    dim_mix: float,
    chorus_busy: bool,
) -> str:
    """Approximate Serum's Hyper/Dimension with Vital's chorus (or flanger).

    wet/detune/dim_size/dim_mix are 0..1, voices 0..7 (0 = Dimension only).
    Returns the Vital effect that received the module ("chorus" or "flanger").
    """
    if retrig:
        conv.note("unsupported: Hyper retrig (Vital's chorus LFO cannot restart per note)")

    if chorus_busy:
        conv.set("flanger_on", 1.0)
        conv.set("flanger_dry_wet", wet * 0.5)
        conv.set("flanger_sync", SYNC_FREE)
        conv.set("flanger_frequency", log2_hz(rate_hz))
        conv.set("flanger_mod_depth", detune * 0.5)
        conv.set("flanger_feedback", 0.0)
        conv.note("resource-conflict: chorus already used, Hyper/Dimension routed to Vital's flanger")
        conv.note("approximation: Hyper placed in the flanger (wet halved, detune halved, no feedback)")
        return "flanger"

    conv.set("chorus_on", 1.0)
    conv.set("chorus_sync", SYNC_FREE)
    if voices <= 0:
        # Dimension only: a static micro-delay widener with a slow wobble.
        conv.set("chorus_voices", 1.0)
        conv.set("chorus_mod_depth", 0.05)
        conv.set("chorus_frequency", math.log2(0.3))
        conv.set("chorus_dry_wet", min(1.0, dim_mix))
        conv.note("approximation: Dimension expander mapped onto a one-pair chorus with 0.3 Hz / 5 % wobble")
    else:
        conv.set("chorus_voices", float(max(1, min(4, math.ceil(voices / 2)))))
        conv.set("chorus_frequency", log2_hz(rate_hz))
        conv.set("chorus_mod_depth", clamp01(detune))
        conv.set("chorus_dry_wet", min(1.0, wet + dim_mix))
        conv.note(
            f"approximation: Hyper ({voices} voices, {rate_hz:.2f} Hz) mapped onto Vital's chorus "
            f"with {max(1, min(4, math.ceil(voices / 2)))} voice pairs"
        )
    conv.set("chorus_delay_1", math.log2(0.001 + 0.019 * clamp01(dim_size)))
    conv.set("chorus_delay_2", math.log2(0.002 + 0.019 * clamp01(dim_size)))
    conv.set("chorus_feedback", 0.0)
    if dim_mix > 0.0:
        conv.note("approximation: Dimension size/mix folded into the chorus base delays and wet amount")
    return "chorus"


# --------------------------------------------------------------------------
# distortion modes
# --------------------------------------------------------------------------

# Vital distortion types.
DIST_SOFT_CLIP, DIST_HARD_CLIP, DIST_LINEAR_FOLD, DIST_SINE_FOLD, DIST_BIT_CRUSH, DIST_DOWN_SAMPLE = range(6)

# Keyed by normalised name (lowercase, punctuation stripped, no leading "k").
# Value: (vital type, exact).  "exact" means the same waveshaper family.
DIST_MODE_TO_VITAL: dict[str, tuple[int, bool]] = {
    "tube": (DIST_SOFT_CLIP, False),
    "softclip": (DIST_SOFT_CLIP, True),
    "softsat": (DIST_SOFT_CLIP, False),
    "overdrive": (DIST_SOFT_CLIP, False),
    "hardclip": (DIST_HARD_CLIP, True),
    "diode1": (DIST_SOFT_CLIP, False),
    "diode2": (DIST_SOFT_CLIP, False),
    "linfold": (DIST_LINEAR_FOLD, True),
    "linearfold": (DIST_LINEAR_FOLD, True),
    "sinfold": (DIST_SINE_FOLD, True),
    "sinefold": (DIST_SINE_FOLD, True),
    "zerosquare": (DIST_HARD_CLIP, False),
    "downsample": (DIST_DOWN_SAMPLE, True),
    "bitcrush": (DIST_BIT_CRUSH, True),
    "asym": (DIST_SOFT_CLIP, False),
    "rectify": (DIST_SOFT_CLIP, False),
    "xshaper": (DIST_SOFT_CLIP, False),
    "xshaperasym": (DIST_SOFT_CLIP, False),
    "sineshaper": (DIST_SINE_FOLD, False),
    "stompbox": (DIST_SOFT_CLIP, False),
    "tapesat": (DIST_SOFT_CLIP, False),
}

# Modes whose character is genuinely absent from Vital (worth a louder note).
DIST_MODES_WITHOUT_COUNTERPART = {"rectify", "xshaper", "xshaperasym"}


def normalise_dist_name(name: str) -> str:
    key = re.sub(r"[^a-z0-9]", "", name.lower())
    if key.startswith("k") and key[1:] in DIST_MODE_TO_VITAL:
        key = key[1:]
    return key


def dist_mode_index(name: str) -> tuple[int, bool]:
    """(Vital distortion type, exact) for a Serum distortion mode name."""
    return DIST_MODE_TO_VITAL.get(normalise_dist_name(name), (DIST_SOFT_CLIP, False))


# --------------------------------------------------------------------------
# compressor knob laws (measured on Serum 1, kept by Serum 2)
# --------------------------------------------------------------------------

# Serum's threshold knob 0..1 -> dB, sampled from the measured Cmp_Thr table
# (0 = 0 dB, 1 = -120 dB, with a steep tail).
_COMP_THRESHOLD_TABLE = [
    (0.000, 0.0), (0.048, -1.3), (0.096, -2.6), (0.145, -4.1), (0.193, -5.6), (0.241, -7.2),
    (0.289, -8.9), (0.338, -10.7), (0.386, -12.7), (0.434, -14.8), (0.482, -17.2), (0.531, -19.7),
    (0.579, -22.5), (0.627, -25.7), (0.675, -29.3), (0.724, -33.5), (0.772, -38.5), (0.820, -44.7),
    (0.868, -52.8), (0.917, -64.7), (0.965, -87.1), (1.000, -120.0),
]


def comp_threshold_db(knob: float) -> float:
    knob = clamp01(knob)
    for (x0, y0), (x1, y1) in zip(_COMP_THRESHOLD_TABLE, _COMP_THRESHOLD_TABLE[1:]):
        if knob <= x1:
            t = (knob - x0) / (x1 - x0) if x1 > x0 else 0.0
            return y0 + t * (y1 - y0)
    return -120.0


def serum_ratio_to_vital(ratio: float) -> float:
    """Serum ratio (1:1 .. Limit) -> Vital's 0..1 ratio (1 - 1/r).

    Serum's own ratio knob is stored as 1 - 1/r as well (2:1 at 0.478, 4:1 at
    0.75, 10:1 at 0.9), so per-band knob values can be passed straight through.
    """
    if ratio >= 1e5:
        return 1.0
    return clamp01(1.0 - 1.0 / max(ratio, 1.0))


def comp_time_to_vital(ms: float) -> float:
    """Serum attack/release in ms (0.1..1000, knob law 1000 * n**2) -> Vital 0..1."""
    return clamp01(math.sqrt(max(ms, 0.0) / 1000.0))


# --------------------------------------------------------------------------
# filter types
# --------------------------------------------------------------------------

# Vital filter models and analog/dirty/ladder/digital styles.
FILTER_ANALOG, FILTER_DIRTY, FILTER_LADDER, FILTER_DIGITAL, FILTER_DIODE, FILTER_FORMANT, FILTER_COMB, FILTER_PHASER = range(8)
STYLE_12DB, STYLE_24DB, STYLE_NOTCH_BLEND, STYLE_NOTCH_SPREAD, STYLE_BPN = range(5)
BLEND_LP, BLEND_BP, BLEND_HP = 0.0, 1.0, 2.0

_LETTER_BLEND = {"L": BLEND_LP, "B": BLEND_BP, "H": BLEND_HP, "P": BLEND_BP, "N": BLEND_BP}


class FilterMapping:
    __slots__ = ("model", "style", "blend", "morph", "exact", "supported", "label")

    def __init__(self, model, style, blend, *, morph=False, exact=False, supported=True, label=""):
        self.model = model
        self.style = style
        self.blend = blend
        self.morph = morph  # blend should follow Serum's VAR knob
        self.exact = exact
        self.supported = supported
        self.label = label


def _slope_style(slope: int) -> int:
    return STYLE_24DB if slope >= 18 else STYLE_12DB


def _single_letter(letter: str, slope: int) -> FilterMapping:
    if letter == "P":
        return FilterMapping(FILTER_ANALOG, STYLE_BPN, BLEND_BP, exact=False, label=f"Peak {slope}")
    if letter == "N":
        style = STYLE_NOTCH_SPREAD if slope >= 18 else STYLE_NOTCH_BLEND
        return FilterMapping(FILTER_ANALOG, style, BLEND_BP, exact=True, label=f"Notch {slope}")
    names = {"L": "Low", "B": "Band", "H": "High"}
    return FilterMapping(FILTER_ANALOG, _slope_style(slope), _LETTER_BLEND[letter], exact=True, label=f"{names[letter]} {slope}")


def filter_type_to_vital(name: str) -> FilterMapping:
    """Map a Serum 2 filter type name (MgL12, LNH24, CombP, ...) onto Vital.

    Serum 1 display names ("MG Low 12", "L/B/H 24") are accepted too.
    """
    key = re.sub(r"[\s./_-]", "", name)
    key = re.sub(r"^MGLow", "MgL", key, flags=re.IGNORECASE)

    m = re.fullmatch(r"MgL(6|12|18|24)", key)
    if m:
        return FilterMapping(FILTER_LADDER, _slope_style(int(m.group(1))), BLEND_LP, exact=True, label=f"MG Low {m.group(1)}")
    if key == "DirtyMg":
        return FilterMapping(FILTER_DIRTY, STYLE_24DB, BLEND_LP, exact=False, label="Dirty MG")
    if key in ("LadderMg", "LadderAcid", "LadderEMS"):
        return FilterMapping(FILTER_LADDER, STYLE_24DB, BLEND_LP, exact=False, label=key)
    if key in ("ADDBASS", "German", "French"):
        return FilterMapping(FILTER_DIODE, STYLE_24DB, BLEND_LP, exact=False, label=key)

    m = re.fullmatch(r"([LHBPN])(6|12|18|24)", key)
    if m:
        return _single_letter(m.group(1), int(m.group(2)))

    # Morphing L/B/H, L/P/H, L/N/H, B/P/N: Vital's blend follows the VAR knob.
    m = re.fullmatch(r"([LB])([BPN])([HN])(12|24)", key)
    if m:
        mid = m.group(2)
        style = {"B": _slope_style(int(m.group(4))), "P": STYLE_BPN, "N": STYLE_NOTCH_SPREAD if int(m.group(4)) >= 18 else STYLE_NOTCH_BLEND}[mid]
        return FilterMapping(FILTER_ANALOG, style, BLEND_LP, morph=True, exact=False, label=f"{key} morph")

    # Dual filters (LH12, LB12, HP12, PP12, NN12 ...): keep the first stage.
    m = re.fullmatch(r"([LHBPN])([LHBPN])(12|24)", key)
    if m:
        first = _single_letter(m.group(1), int(m.group(3)))
        first.exact = False
        first.label = f"{key} (first stage only)"
        return first

    m = re.fullmatch(r"([LHB])EQ(6|12)", key)
    if m:
        return FilterMapping(FILTER_ANALOG, STYLE_12DB, _LETTER_BLEND[m.group(1)], exact=False, label=f"{key} as {m.group(1)} 12")

    if key.startswith("Formant"):
        return FilterMapping(FILTER_FORMANT, 0, 0.0, exact=False, label=key)
    if key.startswith("Comb") and key not in ("Combs",):
        return FilterMapping(FILTER_COMB, 0, 0.0, exact=False, label=key)
    if key.startswith("Flange"):
        return FilterMapping(FILTER_COMB, 1, 0.0, exact=False, label=key)
    if key.startswith("Phase"):
        return FilterMapping(FILTER_PHASER, 0, 0.0, exact=False, label=key)
    if key.startswith("DistComb") or key.startswith("Scream"):
        return FilterMapping(FILTER_COMB, 0, 0.0, exact=False, label=key)

    # Reverb1, Diffuser, Allpasses, Combs, RM, RMT, SNH1, DJMixer, BandReject,
    # PZ_SVF, Wsp, Exp, ExpBPF, ZDF_A ...: no Vital counterpart.
    return FilterMapping(FILTER_ANALOG, STYLE_12DB, BLEND_LP, exact=False, supported=False, label=name)
