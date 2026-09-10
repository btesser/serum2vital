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


# delay_seconds_to_tempo_index: see the measured DELAY_SYNC_BOUNDS table below.


# --------------------------------------------------------------------------
# Hyper / Dimension
# --------------------------------------------------------------------------


# Vital chorus wet per unit of Serum Hyper WET / Dimension MIX (side-level match, fixtures).
HYPER_WET_SCALE = 0.55
DIMENSION_WET_SCALE = 0.42


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
        # Serum's Dimension leaves the mid signal untouched and adds side only
        # (-10 dB side at MIX 50 %, -4 dB at 100 %); Vital's chorus needs ~0.4x.
        conv.set("chorus_dry_wet", min(1.0, DIMENSION_WET_SCALE * dim_mix))
        conv.note("approximation: Dimension expander mapped onto a one-pair chorus with 0.3 Hz / 5 % wobble")
    else:
        conv.set("chorus_voices", float(max(1, min(3, math.ceil(voices / 2)))))
        conv.set("chorus_frequency", log2_hz(rate_hz))
        conv.set("chorus_mod_depth", clamp01(detune))
        # Hyper adds its voices on top of the dry signal, so Serum's WET is not
        # a crossfade: at 100 % the mix is +2.5 dB and the side level -4.5 dB,
        # which Vital's equal-power chorus reaches at about wet 0.5 (fixtures).
        conv.set("chorus_dry_wet", min(1.0, HYPER_WET_SCALE * wet + DIMENSION_WET_SCALE * dim_mix))
        conv.note(
            f"approximation: Hyper ({voices} voices, {rate_hz:.2f} Hz) mapped onto Vital's chorus "
            f"with {max(1, min(3, math.ceil(voices / 2)))} voice pairs"
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


# Vital's follower reads a saw near its peak (-9.5 dBFS for a -17.4 dBFS RMS
# saw) while Serum's detector reads about -21.5 dBFS on the same signal, so a
# Serum threshold has to sit 12 dB higher in Vital (fixtures: 3.4 / 15.1 dB of
# reduction at -25.8 / -41.9 dB in Serum, reproduced within 0.2 dB).
COMP_THRESHOLD_OFFSET_DB = 12.0


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


def comp_time_to_vital(ms: float, kind: str = "release") -> float:
    """Serum attack/release in ms -> Vital's 0..1 knob.

    Vital's compressor (compressor.cpp) turns the knob x into a follower time of
    base_ms * exp(8x - 4); in single-band mode the band section runs, whose
    bases are 1.4 ms (attack) and 28 ms (release).  Serum's default 90 ms
    release therefore sits at x = 0.65, not at the knob position 0.3 that was
    passed through before (which gave Vital 5.6 ms).
    """
    base = 1.4 if kind == "attack" else 28.0
    return clamp01((math.log(max(ms, 0.05) / base) + 4.0) / 8.0)


def comp_makeup_db(knob: float) -> float:
    """Serum's compressor GAIN knob (0..1) in dB: 20 log10(1 + 31 n^2), read from the plugin
    (0.1 -> 2.3, 0.25 -> 9.4, 0.5 -> 18.8, 1.0 -> 30.1 dB)."""
    return 20.0 * math.log10(1.0 + 31.0 * clamp01(knob) ** 2)


# --------------------------------------------------------------------------
# wet/dry mix laws (measured with tools/fx_fixtures.py)
# --------------------------------------------------------------------------

# Serum's effect MIX knob w applies sin^2(pi w / 2) to the wet path and about
# (1 - w^2) to the dry path (delay, distortion and reverb fixtures agree);
# Vital's delay, chorus and reverb crossfade equal-power, sin(pi w'/2) wet and
# cos(pi w'/2) dry, while its distortion, phaser and flanger mix linearly.

# Serum 1's reverb level over the wet knob matches the plain law (sustained
# note: -0.8 / -2.7 / -6 dB at 33 / 50 / 75 %); Serum 2's plate runs ~6 dB hot.
REVERB_WET_SCALE = 1.0
S2_PLATE_WET_SCALE = 2.0


def serum_wet_gain(wet: float) -> float:
    """Wet-path gain of Serum's MIX knob (0..1)."""
    return math.sin(0.5 * math.pi * clamp01(wet)) ** 2


def serum_wet_to_vital(wet: float, scale: float = 1.0) -> float:
    """Vital equal-power wet position whose wet gain equals Serum's (times `scale`).

    The dry path then lands within about 1.5 dB of Serum's: at w = 0.5 Serum
    keeps the dry at -2.4 dB, Vital's w' = 1/3 keeps it at -1.2 dB.
    """
    gain = clamp01(scale * serum_wet_gain(wet))
    return 2.0 / math.pi * math.asin(gain)


def synced_delay(tempo_index: int, multiplier: float, lo: int = 4, hi: int = 12) -> tuple[int, int]:
    """Vital (sync mode, tempo index) closest to `multiplier` x a synced division.

    Serum's delay OFFSET knob scales the division by 0.5 .. 1.5 (Serum 1 shows
    "Dot 1/2" at 0.75, "Dot" at 1.5; Serum 2 stores 1.5 for dotted and 4/3 for
    triplet, i.e. the triplet of the next longer division).  Vital only has
    plain, dotted (1.5x) and triplet (2/3x) of each division, so the nearest
    (division, mode) pair in log time is chosen; a plain division wins ties.
    """
    best: tuple[float, int, int] | None = None
    for index in range(lo, hi + 1):
        for sync, m in ((SYNC_TEMPO, 1.0), (SYNC_DOTTED, 1.5), (SYNC_TRIPLET, 2.0 / 3.0)):
            relative = 2.0 ** (tempo_index - index) * m
            err = abs(math.log(relative / max(multiplier, 1e-3)))
            if best is None or err < best[0] - 1e-9:
                best = (err, sync, index)
    return best[1], best[2]


def chorus_lowpass(hz: float) -> tuple[float, float]:
    """(chorus_cutoff, chorus_spread) that put Vital's chorus delay filter at a low-pass of `hz`.

    Vital filters the chorus wet path with a one-pole low-pass at cutoff + spread*96
    semitones and a high-pass at cutoff - spread*96 (delay.cpp getFilterRadius), so
    a plain low-pass needs the pair centred between 20 Hz and `hz`.  Serum's chorus
    FILTER knob (default 1 kHz) is exactly such a low-pass; leaving Vital's spread
    at 1.0 (as before) disabled the filter entirely and made every converted chorus
    far brighter than Serum's.
    """
    lp = hz_to_note(max(30.0, min(20000.0, hz)))
    hp = hz_to_note(20.0)
    return (lp + hp) / 2.0, clamp01((lp - hp) / 2.0 / 96.0)


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


# --------------------------------------------------------------------------
# measured effect laws (tools/fx_fixtures.py, 2026-09-10) -- see docs/FINDINGS_AND_PLAN.md
# --------------------------------------------------------------------------


def _interp(x: float, points: list[tuple[float, float]]) -> float:
    """Piecewise-linear interpolation with clamped ends."""
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (x - x0) / (x1 - x0) * (y1 - y0)
    return points[-1][1]


def _interp_inverse(y: float, points: list[tuple[float, float]]) -> float:
    """x for a monotonically increasing table, clamped to its ends."""
    if y <= points[0][1]:
        return points[0][0]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if y <= y1:
            return x0 + (y - y0) / (y1 - y0) * (x1 - x0) if y1 > y0 else x1
    return points[-1][0]


# ---- synced modulation-effect rate (chorus / flanger / phaser) ------------
# Serum 1's RATE knob in BPM mode steps through 31 entries over its 229
# steps (plugin read-out): Off, then plain / dotted / triplet divisions from
# 16 bars down to 1/32.  Serum 2 keeps the knob as Hz (20 n^4) and quantises
# the same knob position (checked by rendering: knob 5/8 -> 1.333 Hz = dotted
# quarter, 6/8 -> 3.0 Hz = quarter triplet at 120 BPM).
FX_RATE_RUNS: list[tuple[int, int, int]] = [  # (first knob step, Vital tempo index, sync mode)
    (0, 0, SYNC_TEMPO),          # Off (LFO stopped) -> Freeze
    (4, 2, SYNC_DOTTED),         # 24 bar = dotted 16 bar
    (12, 1, SYNC_TRIPLET),       # 32 bar t
    (19, 2, SYNC_TEMPO),         # 16 bar
    (27, 3, SYNC_DOTTED),        # 12 bar
    (35, 2, SYNC_TRIPLET),       # 16 bar t
    (42, 3, SYNC_TEMPO),         # 8 bar
    (50, 4, SYNC_DOTTED),        # 6 bar
    (57, 3, SYNC_TRIPLET),       # 8 bar t
    (65, 4, SYNC_TEMPO),         # 4 bar
    (73, 5, SYNC_DOTTED),        # 3 bar
    (80, 4, SYNC_TRIPLET),       # 4 bar t
    (88, 5, SYNC_TEMPO),         # 2 bar
    (95, 6, SYNC_DOTTED),        # 1.5 bar
    (103, 5, SYNC_TRIPLET),      # 2 bar t
    (111, 6, SYNC_TEMPO),        # bar
    (118, 7, SYNC_DOTTED),       # 1/2.
    (126, 6, SYNC_TRIPLET),      # bar t
    (133, 7, SYNC_TEMPO),        # 1/2
    (141, 8, SYNC_DOTTED),       # 1/4.
    (149, 7, SYNC_TRIPLET),      # 1/2 t
    (156, 8, SYNC_TEMPO),        # 1/4
    (164, 9, SYNC_DOTTED),       # 1/8.
    (171, 8, SYNC_TRIPLET),      # 1/4 t
    (179, 9, SYNC_TEMPO),        # 1/8
    (187, 10, SYNC_DOTTED),      # 1/16.
    (194, 9, SYNC_TRIPLET),      # 1/8 t
    (202, 10, SYNC_TEMPO),       # 1/16
    (209, 11, SYNC_DOTTED),      # 1/32.
    (217, 10, SYNC_TRIPLET),     # 1/16 t
    (225, 11, SYNC_TEMPO),       # 1/32
]


def fx_rate_sync(step: int) -> tuple[int, int]:
    """(sync mode, Vital tempo index) for a synced RATE knob step (0..228)."""
    sync, tempo = SYNC_TEMPO, 0
    for first, index, mode in FX_RATE_RUNS:
        if step >= first:
            sync, tempo = mode, index
    return sync, tempo


def fx_rate_step_from_hz(hz: float) -> int:
    """Knob step (0..228) of a Serum 2 rate stored in Hz on the 20 n^4 law."""
    return int(round(clamp01((max(hz, 0.0) / 20.0) ** 0.25) * 228))


# ---- Serum 2 synced delay ladder -------------------------------------------
# The stored kParamTime (seconds) is the knob position; when beat-synced Serum
# quantises it to a division.  Boundaries measured by rendering a sweep of
# crafted presets at 120 BPM (upper bound of each division, seconds).
DELAY_SYNC_BOUNDS: list[tuple[float, int]] = [
    (0.007, 12),   # 1/64
    (0.014, 11),   # 1/32
    (0.0295, 10),  # 1/16
    (0.065, 9),    # 1/8   (factory "8th Delay" stores 0.0387)
    (0.11, 8),     # 1/4   (factory "4th Delay" stores 0.0832)
    (0.1795, 7),   # 1/2   (0.1787 renders as a half note, 0.18 as a bar)
    (0.27, 6),     # 1 bar
    (0.41, 5),     # 2 bars
]


def delay_seconds_to_tempo_index(seconds: float, lo: int = 4, hi: int = 12) -> int:
    for bound, index in DELAY_SYNC_BOUNDS:
        if seconds < bound:
            return max(lo, min(hi, index))
    return max(lo, min(hi, 4))   # 4 bars and beyond


# ---- distortion ------------------------------------------------------------
# Output level of Serum's distortion relative to its input on a -17 dBFS saw,
# per mode and DRIVE knob (every mode sits 6 dB below unity at zero drive).
DIST_SERUM_LEVEL: dict[str, list[tuple[float, float]]] = {
    "tube": [(0.0, -6.0), (0.25, -4.3), (0.5, -2.0), (0.66, -0.1), (0.75, 1.1), (1.0, 7.3)],
    "softclip": [(0.0, -6.0), (0.25, -5.6), (0.5, -3.3), (0.66, -0.7), (0.75, 0.8), (1.0, 4.3)],
    "hardclip": [(0.0, -6.0), (0.25, -5.5), (0.5, -2.5), (0.66, 0.6), (0.75, 2.5), (1.0, 6.0)],
    "diode1": [(0.0, 5.0), (0.25, 5.1), (0.5, 5.9), (0.66, 6.5), (0.75, 6.7), (1.0, 7.3)],
    "diode2": [(0.0, 5.6), (0.25, 5.6), (0.5, 5.4), (0.66, 5.1), (0.75, 5.0), (1.0, 4.8)],
    "zerosquare": [(0.0, -6.1), (0.25, 0.7), (0.5, 4.6), (0.66, 6.1), (0.75, 6.8), (1.0, 7.6)],
    "asym": [(0.0, -4.4), (0.25, 1.1), (0.5, 5.2), (0.66, 6.2), (0.75, 6.4), (1.0, 6.7)],
    "rectify": [(0.0, -6.0), (0.25, 1.0), (0.5, 6.4), (0.66, 7.1), (0.75, 7.4), (1.0, 7.7)],
    # X-Shaper's default (linear) curve is a -6 dB pad at any drive, but presets
    # draw their own saturating curve, which is dropped; the tube law is the
    # better guess for the level of a drawn curve (library check).
    "xshaper": [(0.0, -6.0), (0.25, -4.3), (0.5, -2.0), (0.66, -0.1), (0.75, 1.1), (1.0, 7.3)],
    "xshaperasym": [(0.0, -6.0), (0.25, -4.3), (0.5, -2.0), (0.66, -0.1), (0.75, 1.1), (1.0, 7.3)],
    "stompbox": [(0.0, -6.0), (0.25, 2.5), (0.5, 4.5), (0.66, 5.0), (0.75, 5.1), (1.0, 5.5)],
    "tapesat": [(0.0, -6.0), (0.25, -1.2), (0.5, 1.6), (0.66, 2.5), (0.75, 2.8), (1.0, 3.5)],
}
# Fold modes are matched on spectral centroid instead: Vital drive per knob.
DIST_FOLD_DRIVE: dict[str, list[tuple[float, float]]] = {
    "linfold": [(0.0, -6.0), (0.25, 21.0), (0.5, 27.0), (0.66, 28.0), (0.75, 29.0), (1.0, 30.0)],
    "linearfold": [(0.0, -6.0), (0.25, 21.0), (0.5, 27.0), (0.66, 28.0), (0.75, 29.0), (1.0, 30.0)],
    "sinfold": [(0.0, -6.0), (0.25, 18.0), (0.5, 19.0), (0.66, 21.0), (0.75, 21.0), (1.0, 22.0)],
    "sinefold": [(0.0, -6.0), (0.25, 18.0), (0.5, 19.0), (0.66, 21.0), (0.75, 21.0), (1.0, 22.0)],
    "sineshaper": [(0.0, 0.0), (0.25, 6.0), (0.5, 9.0), (0.66, 18.0), (0.75, 21.0), (1.0, 21.0)],
}
# Vital's output level per drive on the same saw (soft clip / hard clip).
VITAL_DRIVE_LEVEL: dict[int, list[tuple[float, float]]] = {
    DIST_SOFT_CLIP: [(-30.0, -30.0), (0.0, -0.5), (3.0, 2.0), (6.0, 4.2), (9.0, 6.0), (12.0, 7.3), (15.0, 8.1),
                     (18.0, 8.7), (21.0, 9.0), (24.0, 9.3), (27.0, 9.4), (30.0, 9.5)],
    DIST_HARD_CLIP: [(-30.0, -30.0), (0.0, 0.0), (3.0, 3.0), (6.0, 5.9), (9.0, 7.4), (12.0, 8.2), (15.0, 8.7),
                     (18.0, 9.1), (21.0, 9.3), (24.0, 9.4), (27.0, 9.5), (30.0, 9.6)],
}


def dist_settings(mode_name: str, knob: float) -> tuple[int, float, bool]:
    """(Vital distortion type, drive dB, exact) for a Serum mode name and DRIVE knob 0..1.

    Clipping modes are matched on output level (Serum's drive is a pre-gain
    behind a fixed -6 dB pad and a mode-specific shaper), fold modes on the
    spectral centroid, downsample on a linear guess.
    """
    key = normalise_dist_name(mode_name)
    knob = clamp01(knob)
    vital_type, exact = DIST_MODE_TO_VITAL.get(key, (DIST_SOFT_CLIP, False))
    if key in DIST_FOLD_DRIVE:
        return vital_type, _interp(knob, DIST_FOLD_DRIVE[key]), exact
    if key == "downsample":
        return DIST_DOWN_SAMPLE, -27.0 + 40.0 * knob, exact
    if key == "bitcrush":
        return DIST_BIT_CRUSH, -30.0 + 45.0 * knob, exact
    level = _interp(knob, DIST_SERUM_LEVEL.get(key, DIST_SERUM_LEVEL["tube"]))
    table = VITAL_DRIVE_LEVEL.get(vital_type, VITAL_DRIVE_LEVEL[DIST_SOFT_CLIP])
    return vital_type, max(-30.0, min(30.0, _interp_inverse(level, table))), exact


# ---- EQ --------------------------------------------------------------------
# Serum's Q knob (0..1) against Vital's resonance (0..1, Q = 0.5 + 15.5 r^3),
# matched on octave-band responses; Vital's shelves sit half an octave higher
# than Serum's and peak with any resonance, so they are shifted and left flat.
EQ_PEAK_RESONANCE = [(0.2, 0.0), (0.6, 0.8), (0.9, 1.0)]
EQ_PASS_RESONANCE = [(0.2, 0.0), (0.6, 0.7), (0.9, 0.93), (1.0, 1.0)]
EQ_SHELF_SHIFT_SEMITONES = -6.0


def eq_resonance(q: float, kind: str) -> float:
    if kind == "peak":
        return clamp01(_interp(q, EQ_PEAK_RESONANCE))
    if kind == "pass":
        return clamp01(_interp(q, EQ_PASS_RESONANCE))
    return 0.0


# ---- reverb ----------------------------------------------------------------
# RT60 as measured by the fixture tool's slope fit (same method on both synths).
# Serum 1: a floor set by SIZE, overtaken by the DECAY knob (0.8..12 s displayed)
# as 2000 / (12.5 - decay)^3; at 12 s the tail no longer decays.
SERUM1_REVERB_FLOOR = [(0.1, 0.7), (0.2, 0.88), (0.35, 1.14), (0.5, 1.81), (0.65, 3.2), (0.8, 5.3), (1.0, 7.0)]
# Vital: RT60 = 1.45 * decay_time * f(size).
VITAL_REVERB_SIZE_FACTOR = [(0.0, 1.52), (0.25, 1.16), (0.35, 1.0), (0.5, 0.9), (0.75, 0.81), (1.0, 0.76)]
REVERB_MAX_RT60 = 60.0


def serum1_reverb_rt60(size: float, decay_seconds: float) -> float:
    floor = _interp(clamp01(size), SERUM1_REVERB_FLOOR)
    if decay_seconds >= 12.4:
        return REVERB_MAX_RT60
    # The slope fit reads the floor up to 2.1 s of decay, but cutting the tail to
    # that floor made real presets worse (listening sets); the cubic term is
    # kept over the whole range, it only exceeds the floor slightly below 3 s.
    return min(REVERB_MAX_RT60, max(floor, 2000.0 / (12.5 - decay_seconds) ** 3))


def vital_decay_for_rt60(rt60: float, size: float) -> float:
    """Vital `reverb_decay_time` (log2 seconds) giving `rt60` at `size`."""
    seconds = max(0.05, rt60) / (1.45 * _interp(clamp01(size), VITAL_REVERB_SIZE_FACTOR))
    return max(-6.0, min(6.0, math.log2(seconds)))


# Serum 2 reverb types (library-median settings for the other knobs).
S2_PLATE_RT60 = [(0.0, 0.2), (10.0, 0.4), (20.0, 0.94), (35.0, 3.05), (50.0, 7.9), (65.0, 11.9), (100.0, 11.9)]
S2_HALL_FLOOR = [(0.0, 3.0), (50.0, 3.2), (80.0, 5.5), (100.0, 7.0)]
S2_VINTAGE_RT60 = [(0.0, 0.5), (20.0, 0.9), (45.0, 1.8), (80.0, 6.3), (100.0, 9.0)]
S2_ABYSS_GRID = {  # size -> [(kParamDelay, RT60)]
    0.0: [(0.0, 0.1), (30.0, 1.2), (100.0, 2.5)],
    15.0: [(0.0, 0.23), (30.0, 2.5), (100.0, 5.1)],
    34.0: [(0.0, 1.66), (30.0, 5.7), (100.0, 7.4)],
    65.0: [(0.0, 5.0), (30.0, 8.4), (100.0, 12.1)],
    100.0: [(0.0, 7.0), (30.0, 11.0), (100.0, 15.0)],
}


def serum2_reverb_rt60(kind: str, size: float, delay: float) -> float:
    """RT60 of a Serum 2 reverb module (kind = kPlate/kHall/kVintage/kAbyss/kSpace)."""
    if kind == "kPlate":
        return _interp(size, S2_PLATE_RT60)
    if kind == "kVintage":
        return _interp(size, S2_VINTAGE_RT60)
    if kind == "kAbyss":
        sizes = sorted(S2_ABYSS_GRID)
        rows = [(s, _interp(delay, S2_ABYSS_GRID[s])) for s in sizes]
        return _interp(size, rows)
    # Hall (and Space, which could not be rendered): floor by size, DECAY/PRE-DLY knob exponential.
    grown = 3.0 * math.exp((delay - 30.0) / 35.0)
    return min(REVERB_MAX_RT60, max(_interp(size, S2_HALL_FLOOR), grown))


def reverb_tone(hicut: float, locut: float) -> tuple[float, float]:
    """(reverb_pre_high_cutoff, reverb_pre_low_cutoff) for Serum 1 HI CUT / LO CUT knobs (0..1).

    Serum's tail is brighter than Vital's at any setting, so the high cut only
    starts closing Vital's pre-filter; the laws match the measured centroid
    shift (-0.8 octave at HI CUT 80 %, +0.37 octave and -6 dB at LO CUT 80 %).
    """
    return 128.0 - 35.0 * clamp01(hicut), 30.0 + 60.0 * clamp01(locut)


# ---- compressor ------------------------------------------------------------
# Serum's multiband mode is an OTT-style upward + downward compressor (quiet
# input +3 dB and bright, loud input -8 dB); Vital's multiband compressor is
# the same design.  Constants matched on quiet / normal / loud fixtures.
MB_UPPER_OFFSET_DB = 3.0      # Vital upper threshold above Serum's THRESH
MB_LOWER_GAP_DB = 5.0         # Vital lower threshold below the upper one
MB_LOWER_RATIO = 0.8
MB_BAND_TRIM_DB = {"low": -1.5, "band": -3.5, "high": 1.5}
# Below its default threshold Serum's multiband output falls faster than the
# threshold itself (-12.9 dB for an 8.2 dB lower THRESH, -21 dB for 16 dB more);
# Vital's downward compression cannot go below its threshold, so the difference
# is added as band gain.  Serum 2's multiband mode does not rise above the
# default the way Serum 1's does, so the term is one-sided.
MB_REFERENCE_THRESHOLD_DB = -17.6
MB_THRESHOLD_GAIN_SLOPE = 0.85


def mb_ratio_scale(ratio: float) -> float:
    """Serum's RATIO knob scales the whole multiband effect (upward and downward):
    at 1:1 the module is transparent apart from +1.9 dB (fixtures at 0 / 1.2:1 / 1.7:1 / 4:1)."""
    return clamp01(ratio / 0.75)


MB_UNITY_GAIN_DB = 1.9        # multiband output at ratio 1:1, any threshold
# Serum's multiband wet knob cancels against the band-split path (about -3 dB
# at 50 % on the fixture saw); a gain term for that pulled real presets down and
# silenced a preset with wet at 0, so the wet knob stays a plain Vital mix.


def mb_threshold_gain_db(threshold_db: float, ratio: float = 0.75) -> float:
    """Measured at Serum's default 4:1 ratio (0.75); scaled down towards 1:1."""
    scale = mb_ratio_scale(ratio)
    return max(-22.0, scale * MB_THRESHOLD_GAIN_SLOPE * min(0.0, threshold_db - MB_REFERENCE_THRESHOLD_DB))


def mb_band_settings(threshold_db: float, ratio: float, band: str, wet: float = 1.0) -> dict:
    """Vital compressor band values for Serum's multiband mode (before makeup / band knobs)."""
    scale = mb_ratio_scale(ratio)
    upper = max(-80.0, min(0.0, threshold_db + MB_UPPER_OFFSET_DB))
    gain = (scale * MB_BAND_TRIM_DB[band] + (1.0 - scale) * MB_UNITY_GAIN_DB
            + mb_threshold_gain_db(threshold_db, ratio))
    return {
        "upper_threshold": upper,
        "lower_threshold": max(-80.0, upper - MB_LOWER_GAP_DB),
        "upper_ratio": clamp01(ratio),
        "lower_ratio": MB_LOWER_RATIO * scale,
        "gain": gain,
    }


def mb_band_gain_db(percent: float) -> float:
    """Serum's per-band L/M/H knob (0..200 %, 100 % neutral) -> band gain dB (+10 at 200 %, -12 floor)."""
    return max(-12.0, min(10.0, 33.0 * math.log10(max(percent, 5.0) / 100.0)))


# ---- phaser / flanger ------------------------------------------------------
# Serum's STEREO 180 degrees measures like a Vital phase offset of 0.02 (phaser)
# and 0.1 (flanger) on side level and L/R correlation; Serum's flanger sits at
# a fixed ~16 ms base delay (Vital centre note 34).
PHASER_OFFSET_PER_180 = 0.02
FLANGER_OFFSET_PER_180 = 0.1
FLANGER_CENTER_NOTE = 34.0
