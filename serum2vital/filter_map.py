"""Serum filter type -> Vital filter model/style/blend table.

Self-contained (no imports from the rest of the package).  Facts about Vital's
engine were checked against the Vital source:

* ``filter_N_model``: 0 Analog (Sallen-Key), 1 Dirty, 2 Ladder, 3 Digital
  (SVF), 4 Diode, 5 Formant, 6 Comb, 7 Phaser.
* ``filter_N_style`` for Analog/Dirty/Ladder/Digital (5 styles): 0 "12dB",
  1 "24dB", 2 "Notch Blend", 3 "Notch Spread", 4 "B/P/N".  Diode (2):
  0 Low Shelf, 1 Low Cut.  Formant (2): 0 A/O/I/E, 1 A/I/U/O vowel squares.
  Comb (6): style % 3 is the feedback style (0 comb, 1 flange+, 2 flange-)
  and style // 3 is the feedback-filter style (0 low/high blend, 1 band
  spread).  Phaser (2): 0 Positive, 1 Negative (output polarity).
* ``filter_N_blend`` 0..2.  12dB/24dB styles: 0 low-pass, 1 band-pass,
  2 high-pass (``band = sqrt(1 - b^2)``, ``low = max(-b, 0)``,
  ``high = max(b, 0)`` with ``b = blend - 1``).  Notch Blend: 0 low-pass,
  1 notch (low + high summed), 2 high-pass.  B/P/N: 0 band, 1 peak, 2 notch.
  Comb low/high style: 0 low-pass in the feedback path, 2 high-pass.
  Comb band-spread style: blend widens the feedback band (+-blend*4 octaves).
  Phaser: 0 = 4 all-pass stages, 1 = 8, 2 = 12.
* ``filter_N_blend_transpose`` 0..84 semitones: comb feedback-filter cutoff =
  comb cutoff + blend_transpose (band spread: centre = cutoff + transpose).
* Comb feedback sign: comb style feedback = 2*resonance - 1 (resonance 0.5 is
  no feedback, above is positive, below negative); flange styles always use
  0..1 feedback and carry the sign in the style.  See ``map_resonance``.
* Formant: ``formant_x``/``formant_y`` 0..1 interpolate the vowel square,
  ``formant_transpose`` -12..12 semitones shifts every formant.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import re

# --------------------------------------------------------------------------
# Vital constants
# --------------------------------------------------------------------------

MODEL_ANALOG = 0
MODEL_DIRTY = 1
MODEL_LADDER = 2
MODEL_DIGITAL = 3
MODEL_DIODE = 4
MODEL_FORMANT = 5
MODEL_COMB = 6
MODEL_PHASER = 7

MODEL_NAMES = ("Analog", "Dirty", "Ladder", "Digital", "Diode", "Formant", "Comb", "Phaser")

# Styles per model, in Vital's menu order (FilterSection::getNumStyles).
STYLE_NAMES: dict[int, tuple[str, ...]] = {
    MODEL_ANALOG: ("12dB", "24dB", "Notch Blend", "Notch Spread", "B/P/N"),
    MODEL_DIRTY: ("12dB", "24dB", "Notch Blend", "Notch Spread", "B/P/N"),
    MODEL_LADDER: ("12dB", "24dB", "Notch Blend", "Notch Spread", "B/P/N"),
    MODEL_DIGITAL: ("12dB", "24dB", "Notch Blend", "Notch Spread", "B/P/N"),
    MODEL_DIODE: ("Low Shelf", "Low Cut"),
    MODEL_FORMANT: ("AOIE", "AIUO"),
    MODEL_COMB: (
        "Low High Comb", "Low High Flange+", "Low High Flange-",
        "Band Spread Comb", "Band Spread Flange+", "Band Spread Flange-",
    ),
    MODEL_PHASER: ("Positive", "Negative"),
}
STYLE_COUNTS = {model: len(names) for model, names in STYLE_NAMES.items()}

STYLE_12 = 0
STYLE_24 = 1
STYLE_NOTCH_BLEND = 2
STYLE_NOTCH_SPREAD = 3
STYLE_BPN = 4

DIODE_LOW_SHELF = 0
DIODE_LOW_CUT = 1

COMB_LH_COMB = 0
COMB_LH_FLANGE_POS = 1
COMB_LH_FLANGE_NEG = 2
COMB_BAND_COMB = 3
COMB_BAND_FLANGE_POS = 4
COMB_BAND_FLANGE_NEG = 5

PHASER_POSITIVE = 0
PHASER_NEGATIVE = 1

BLEND_LOW = 0.0
BLEND_BAND = 1.0
BLEND_HIGH = 2.0
# Notch Blend style
BLEND_NOTCH = 1.0
# B/P/N style
BPN_BAND = 0.0
BPN_PEAK = 1.0
BPN_NOTCH = 2.0

BLEND_TRANSPOSE_MIN = 0.0
BLEND_TRANSPOSE_MAX = 84.0
BLEND_TRANSPOSE_DEFAULT = 42.0
FORMANT_TRANSPOSE_RANGE = 12.0
CUTOFF_MIN_NOTE = 8.0
CUTOFF_MAX_NOTE = 136.0

# Serum's 0..1 cutoff / VAR-frequency knobs span MIDI note 0..135 (same
# constant the rest of the converter uses for filter_1_cutoff).
SERUM_CUTOFF_MAX_NOTE = 135.0

VAR_ROLES = (
    "none",             # VAR has no counterpart (or the type has no VAR)
    "second_cutoff",    # dual SVF: VAR is the cutoff of target.second
    "morph_blend",      # morphing SVF: blend = 2 * VAR
    "gain",             # EQ types: VAR is +/- dB gain of the pass band
    "formant",          # formant shift -> formant_transpose
    "width",            # notch width -> resonance
    "comb_freq",        # Dist.Comb: VAR is the comb frequency
    "feedback_filter",  # Cmb/Flg L6/H6/HL6: VAR is the feedback-filter cutoff / width
    "scream",           # Scream: VAR is the feedback-circuit cutoff (no counterpart)
    "thru",             # Add Bass: VAR mixes in phase-rotated dry signal -> mix
    "damp",             # Combs/Allpasses/Reverb: VAR damps the feedback path
    "boeuf",            # French LP: secondary resonance (no counterpart)
)
FIDELITIES = ("exact", "approximation", "character", "unsupported")


# --------------------------------------------------------------------------
# Target description
# --------------------------------------------------------------------------


@dataclass
class FilterTarget:
    model: int
    style: int
    blend: float
    var_role: str = "none"
    fidelity: str = "exact"
    note: str = ""
    second: "FilterTarget | None" = None
    formant_x: float | None = None
    formant_y: float | None = None
    # Extra slot defaults.  ``blend_transpose`` is only meaningful for comb
    # models; ``resonance_polarity`` -1 asks for negative comb feedback (see
    # ``map_resonance``); ``mix_hint`` is a suggested filter_N_mix for types
    # that only make sense partially wet (or an unsupported fallback).
    blend_transpose: float | None = None
    resonance_polarity: int = 1
    mix_hint: float | None = None
    drive_hint_db: float | None = None

    @property
    def model_name(self) -> str:
        return MODEL_NAMES[self.model]

    @property
    def style_name(self) -> str:
        return STYLE_NAMES[self.model][self.style]

    def slot_params(self) -> dict[str, float]:
        """Static Vital parameters for a filter slot (keys without filter_N_)."""
        params: dict[str, float] = {
            "model": float(self.model),
            "style": float(self.style),
            "blend": float(self.blend),
        }
        if self.blend_transpose is not None:
            params["blend_transpose"] = float(self.blend_transpose)
        if self.formant_x is not None:
            params["formant_x"] = float(self.formant_x)
        if self.formant_y is not None:
            params["formant_y"] = float(self.formant_y)
        if self.mix_hint is not None:
            params["mix"] = float(self.mix_hint)
        if self.drive_hint_db is not None:
            params["drive"] = float(self.drive_hint_db)
        return params


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def var_to_cutoff_note(var: float) -> float:
    """A Serum 0..1 frequency-type VAR knob as a Vital MIDI cutoff note."""
    return _clamp(var * SERUM_CUTOFF_MAX_NOTE, CUTOFF_MIN_NOTE, CUTOFF_MAX_NOTE)


def map_resonance(target: FilterTarget, resonance: float) -> float:
    """Serum resonance (0..1) -> Vital filter_N_resonance for this target.

    Vital's plain comb styles derive the feedback sign from resonance
    (0.5 = none, 1 = full positive, 0 = full negative), so Serum's separate
    +/- comb types are folded into the resonance value here.  Flange styles
    and every other model take resonance as-is.
    """
    resonance = _clamp(resonance, 0.0, 1.0)
    if target.model == MODEL_COMB and target.style % 3 == COMB_LH_COMB:
        return 0.5 + 0.5 * resonance * (1 if target.resonance_polarity >= 0 else -1)
    return resonance


# --------------------------------------------------------------------------
# Building blocks
# --------------------------------------------------------------------------

_SLOPE_STYLE = {6: STYLE_12, 12: STYLE_12, 18: STYLE_24, 24: STYLE_24}


def _slope_note(slope: int, family: str = "") -> tuple[str, str]:
    """Fidelity and note for a Serum dB/oct slope rendered by 12/24 dB styles."""
    if slope in (12, 24):
        return "exact", ""
    prefix = f"{family} " if family else ""
    if slope == 6:
        return "approximation", f"{prefix}6 dB/oct slope rendered with Vital's 12 dB style"
    return "approximation", f"{prefix}18 dB/oct slope rendered with Vital's 24 dB style"


def _svf(letter: str, slope: int, model: int = MODEL_ANALOG) -> FilterTarget:
    """Single SVF response letter (L/H/B/P/N) at a slope."""
    style = _SLOPE_STYLE[slope]
    fidelity, note = _slope_note(slope)
    if letter == "L":
        return FilterTarget(model, style, BLEND_LOW, fidelity=fidelity, note=note)
    if letter == "H":
        return FilterTarget(model, style, BLEND_HIGH, fidelity=fidelity, note=note)
    if letter == "B":
        return FilterTarget(model, style, BLEND_BAND, fidelity=fidelity, note=note)
    if letter == "P":
        target = FilterTarget(model, STYLE_BPN, BPN_PEAK, fidelity=fidelity, note=note)
    elif letter == "N":
        target = FilterTarget(model, STYLE_NOTCH_BLEND, BLEND_NOTCH, fidelity=fidelity, note=note)
    else:
        raise ValueError(f"unknown SVF response letter {letter!r}")
    if slope > 12:
        target.fidelity = "approximation"
        target.note = f"Vital's {target.style_name} style is 12 dB only; {slope} dB slope not available"
    return target


def _ladder(slope: int) -> FilterTarget:
    style = _SLOPE_STYLE[slope]
    fidelity, note = _slope_note(slope, "ladder")
    return FilterTarget(MODEL_LADDER, style, BLEND_LOW, fidelity=fidelity, note=note)


def _dual(primary: str, secondary: str, slope: int) -> FilterTarget:
    # The secondary stage is described by ``second`` (caller puts it into the
    # next free Vital filter slot in series, cutoff from VAR, same resonance).
    first = _svf(primary, slope)
    second = _svf(secondary, slope)
    return replace(first, var_role="second_cutoff", second=second)


def _morph(letters: str, slope: int) -> FilterTarget:
    style = _SLOPE_STYLE[slope]
    if letters == "LBH":
        return FilterTarget(MODEL_ANALOG, style, BLEND_LOW, var_role="morph_blend",
                            note="")
    if letters == "LNH":
        return FilterTarget(
            MODEL_ANALOG, STYLE_NOTCH_BLEND, BLEND_LOW, var_role="morph_blend",
            fidelity="approximation",
            note=(f"Notch Blend style morphs low -> notch -> high like L/N/H; "
                  f"{'12 dB only' if slope == 24 else 'morph curve may differ'}"))
    if letters == "BPN":
        return FilterTarget(
            MODEL_ANALOG, STYLE_BPN, BPN_BAND, var_role="morph_blend",
            fidelity="approximation",
            note=(f"B/P/N style morphs band -> peak -> notch like B/P/N; "
                  f"{'12 dB only' if slope == 24 else 'morph curve may differ'}"))
    if letters == "LPH":
        return FilterTarget(
            MODEL_ANALOG, style, BLEND_LOW, var_role="morph_blend",
            fidelity="approximation",
            note="no low -> peak -> high style in Vital; 12/24 dB blend used "
                 "(band-pass instead of peak at the middle VAR position)")
    raise ValueError(f"unknown morph family {letters!r}")


def _comb(kind: str, sub: str, positive: bool) -> FilterTarget:
    """Serum Cmb/Flg families.

    kind: "Cmb" or "Flg"; sub: "", "L6", "H6", "HL6"; positive: '+' polarity.
    """
    band = sub == "HL6"
    if kind == "Cmb":
        style = COMB_BAND_COMB if band else COMB_LH_COMB
    else:
        if band:
            style = COMB_BAND_FLANGE_POS if positive else COMB_BAND_FLANGE_NEG
        else:
            style = COMB_LH_FLANGE_POS if positive else COMB_LH_FLANGE_NEG
    if sub == "L6":
        blend = BLEND_LOW
    elif sub == "H6":
        blend = BLEND_HIGH
    elif sub == "HL6":
        blend = 0.5
    else:
        blend = BLEND_LOW
    label = "comb" if kind == "Cmb" else "flanger"
    note = f"Serum {label}{' with ' + sub + ' feedback filter' if sub else ''} -> Vital Comb "
    if kind == "Cmb":
        note += ("(polarity folded into resonance, see map_resonance)"
                 if positive else "(negative feedback folded into resonance, see map_resonance)")
    else:
        note += f"{STYLE_NAMES[MODEL_COMB][style]} style"
    if not sub:
        note += "; feedback path is a wide-open low-pass (blend_transpose 84)"
    target = FilterTarget(
        MODEL_COMB, style, blend,
        var_role="feedback_filter" if sub else "none",
        fidelity="approximation", note=note,
        resonance_polarity=1 if positive else -1,
        blend_transpose=BLEND_TRANSPOSE_MAX if not sub else (0.0 if band else BLEND_TRANSPOSE_DEFAULT),
        mix_hint=0.5,
    )
    return target


_PHASER_BLEND = {12: 0.0, 24: 0.0, 36: 0.5, 48: 1.0}


def _phaser(poles: int, sub: str, positive: bool, flanger: bool = False) -> FilterTarget:
    blend = _PHASER_BLEND.get(poles, 1.0)
    note = (f"Serum {poles}-pole phaser -> Vital Phaser "
            f"({'4' if blend == 0 else '8' if blend == 1 else '4-8'} all-pass stages)")
    if poles == 12:
        note += "; Vital's minimum is 4 stages (2 notches vs Serum's 1)"
    if sub:
        note += f"; {sub} feedback filter has no counterpart in Vital's phaser (VAR dropped)"
    if flanger:
        note += "; Serum flanger-phaser hybrid rendered as a plain phaser"
    return FilterTarget(
        MODEL_PHASER, PHASER_POSITIVE if positive else PHASER_NEGATIVE, blend,
        var_role="none", fidelity="approximation", note=note, mix_hint=0.5,
    )


def _eq(band: str, slope: int) -> FilterTarget:
    blend = {"Low": BLEND_LOW, "Band": BLEND_BAND, "High": BLEND_HIGH}[band]
    style = _SLOPE_STYLE[slope]
    return FilterTarget(
        MODEL_ANALOG, style, blend, var_role="gain", fidelity="approximation",
        note=(f"{band} EQ {slope}: Vital voice filters have no shelf gain; approximated "
              "by mixing dry with the pass band (boost) or its complement (cut). "
              "Consider Vital's EQ effect for a true shelf"),
    )


def _unsupported(what: str) -> FilterTarget:
    return FilterTarget(
        MODEL_ANALOG, STYLE_12, BLEND_LOW, var_role="none", fidelity="unsupported",
        note=f"{what} has no Vital filter counterpart; analog 12 dB low-pass placeholder "
             "(mix hint 0 keeps the sound dry)",
        mix_hint=0.0,
    )


def _formant(variant: int) -> FilterTarget:
    # Serum's cutoff walks a 1-D vowel path; Vital has a 2-D vowel square.
    # formant_x/y are filled in by ``formant_xy_from_cutoff`` (cutoff-dependent);
    # defaults here sit at the square's centre.
    style = 1 if variant == 2 else 0
    return FilterTarget(
        MODEL_FORMANT, style, 0.0, var_role="formant", fidelity="character",
        note=(f"Formant-{'I' * variant if variant < 4 else variant}: Serum's cutoff morphs "
              "between vowels; mapped onto a path across Vital's "
              f"{STYLE_NAMES[MODEL_FORMANT][style]} vowel square (see formant_xy_from_cutoff); "
              "VAR (formant shift) -> formant_transpose"),
        formant_x=0.5, formant_y=0.5,
    )


def formant_xy_from_cutoff(cutoff_note: float, variant: int = 1) -> tuple[float, float]:
    """Position on Vital's vowel square for a Serum formant-filter cutoff.

    Serum's cutoff (MIDI note 0..135) walks a 1-D path through vowels.  Each
    Serum variant takes a different straight path across Vital's square:
    I: bottom-left -> top-right, II: top-left -> bottom-right, III: left ->
    right through the middle.
    """
    t = _clamp((cutoff_note - CUTOFF_MIN_NOTE) / (SERUM_CUTOFF_MAX_NOTE - CUTOFF_MIN_NOTE), 0.0, 1.0)
    if variant == 2:
        return t, 1.0 - t
    if variant == 3:
        return t, 0.5
    return t, t


def _dist_comb(version: int, pass_kind: str) -> FilterTarget:
    positive = version == 1
    if pass_kind == "BP":
        style, blend = COMB_BAND_COMB, 0.5
    else:
        style, blend = COMB_LH_COMB, BLEND_LOW
    return FilterTarget(
        MODEL_COMB, style, blend, var_role="comb_freq", fidelity="approximation",
        note=(f"Dist.Comb {version} {pass_kind}: Serum puts a {'positive' if positive else 'negative'} "
              "comb in the feedback of a pass filter; Vital's Comb puts the pass filter in the "
              "comb's feedback. Comb frequency (VAR) -> cutoff, Serum cutoff -> blend_transpose"),
        resonance_polarity=1 if positive else -1,
        blend_transpose=BLEND_TRANSPOSE_DEFAULT,
    )


def _scream(pass_kind: str) -> FilterTarget:
    blend = BLEND_BAND if pass_kind == "BP" else BLEND_LOW
    return FilterTarget(
        MODEL_DIRTY, STYLE_24, blend, var_role="scream", fidelity="character",
        note=(f"Scream {pass_kind}: high-feedback screaming filter approximated by Vital's "
              "Dirty 24 dB with drive; SCREAM (feedback cutoff) has no counterpart"),
        drive_hint_db=14.0,
    )


# --------------------------------------------------------------------------
# Serum 1 table (index into serum_tables.FILTER_NAMES)
# --------------------------------------------------------------------------

SERUM1_FILTER_NAMES: tuple[str, ...] = (
    'MG Low 6', 'MG Low 12', 'MG Low 18', 'MG Low 24',
    'Low 6', 'Low 12', 'Low 18', 'Low 24',
    'High 6', 'High 12', 'High 18', 'High 24',
    'Band 12', 'Band 24', 'Peak 12', 'Peak 24', 'Notch 12', 'Notch 24',
    'LH 6', 'LH 12', 'LB 12', 'LP 12', 'LN 12', 'HB 12', 'HP 12', 'HN 12',
    'BP 12', 'BN 12', 'PP 12', 'PN 12', 'NN 12',
    'L/B/H 12', 'L/B/H 24', 'L/P/H 12', 'L/P/H 24', 'L/N/H 12', 'L/N/H 24',
    'B/P/N 12', 'B/P/N 24',
    'Cmb +', 'Cmb -', 'Cmb L6+', 'Cmb L6-', 'Cmb H6+', 'Cmb H6-', 'Cmb HL6+', 'Cmb HL6-',
    'Flg +', 'Flg -', 'Flg L6+', 'Flg L6-', 'Flg H6+', 'Flg H6-', 'Flg HL6+', 'Flg HL6-',
    'Phs 12+', 'Phs 12-', 'Phs 24+', 'Phs 24-', 'Phs 36+', 'Phs 36-', 'Phs 48+', 'Phs 48-',
    'Phs 48L6+', 'Phs 48L6-', 'Phs 48H6+', 'Phs 48H6-', 'Phs 48HL6+', 'Phs 48HL6-',
    'FPhs 12HL6+', 'FPhs 12HL6-',
    'Low EQ 6', 'Low EQ 12', 'Band EQ 12', 'High EQ 6', 'High EQ 12',
    'Ring Mod', 'Ring Modx2', 'SampHold', 'SampHold-',
    'Combs', 'Allpasses', 'Reverb',
    'French LP', 'German LP', 'Add Bass',
    'Formant-I', 'Formant-II', 'Formant-III',
    'Bandreject',
    'Dist.Comb 1 LP', 'Dist.Comb 1 BP', 'Dist.Comb 2 LP', 'Dist.Comb 2 BP',
    'Scream LP', 'Scream BP',
)

_RE_MG = re.compile(r"MG Low (\d+)")
_RE_SINGLE = re.compile(r"(Low|High|Band|Peak|Notch) (\d+)")
_RE_DUAL = re.compile(r"([LHBPN])([LHBPN]) (\d+)")
_RE_MORPH = re.compile(r"([LHBPN])/([LHBPN])/([LHBPN]) (\d+)")
_RE_COMB = re.compile(r"(Cmb|Flg) (L6|H6|HL6)?([+-])")
_RE_PHS = re.compile(r"(F?)Phs (\d+)(L6|H6|HL6)?([+-])")
_RE_EQ = re.compile(r"(Low|Band|High) EQ (\d+)")
_RE_DIST_COMB = re.compile(r"Dist\.Comb ([12]) (LP|BP)")
_RE_SCREAM = re.compile(r"Scream (LP|BP)")


def _target_for_serum1_name(name: str) -> FilterTarget | None:
    if m := _RE_MG.fullmatch(name):
        return _ladder(int(m.group(1)))
    if m := _RE_SINGLE.fullmatch(name):
        return _svf(m.group(1)[0], int(m.group(2)))
    if m := _RE_DUAL.fullmatch(name):
        return _dual(m.group(1), m.group(2), int(m.group(3)))
    if m := _RE_MORPH.fullmatch(name):
        return _morph(m.group(1) + m.group(2) + m.group(3), int(m.group(4)))
    if m := _RE_COMB.fullmatch(name):
        return _comb(m.group(1), m.group(2) or "", m.group(3) == "+")
    if m := _RE_PHS.fullmatch(name):
        return _phaser(int(m.group(2)), m.group(3) or "", m.group(4) == "+",
                       flanger=bool(m.group(1)))
    if m := _RE_EQ.fullmatch(name):
        return _eq(m.group(1), int(m.group(2)))
    if m := _RE_DIST_COMB.fullmatch(name):
        return _dist_comb(int(m.group(1)), m.group(2))
    if m := _RE_SCREAM.fullmatch(name):
        return _scream(m.group(1))

    if name in ("Ring Mod", "Ring Modx2"):
        target = _unsupported(f"{name} (ring modulation at the cutoff frequency)")
        target.note += "; use oscillator RM warp for a similar effect"
        return target
    if name in ("SampHold", "SampHold-"):
        return _unsupported(f"{name} (sample-and-hold distortion)")
    if name in ("Combs", "Allpasses", "Reverb"):
        return FilterTarget(
            MODEL_COMB, COMB_LH_COMB, BLEND_LOW, var_role="damp", fidelity="approximation",
            note=(f"{name}: Serum's delay/all-pass phase smearing network approximated by "
                  "a single Vital comb with a low-pass in the feedback; DAMP -> blend_transpose"),
            blend_transpose=BLEND_TRANSPOSE_MAX, mix_hint=0.5,
        )
    if name == "French LP":
        return FilterTarget(
            MODEL_DIODE, DIODE_LOW_CUT, BLEND_LOW, var_role="boeuf", fidelity="character",
            note=("French LP: non-linear distorting low-pass rendered by Vital's Diode Low Cut; "
                  "BOEUF (secondary resonance) has no counterpart"),
        )
    if name == "German LP":
        return FilterTarget(
            MODEL_LADDER, STYLE_24, BLEND_LOW, fidelity="approximation",
            note="German LP: clean zero-delay-feedback 4-pole low-pass rendered by Vital's Ladder 24 dB",
        )
    if name == "Add Bass":
        return FilterTarget(
            MODEL_ANALOG, STYLE_12, BLEND_LOW, var_role="thru", fidelity="character",
            note=("Add Bass: phase-rotated low-pass with drive rendered as Analog 12 dB low-pass; "
                  "THRU -> filter mix"),
            drive_hint_db=4.0,
        )
    if name.startswith("Formant-"):
        return _formant({"I": 1, "II": 2, "III": 3}[name.split("-", 1)[1]])
    if name == "Bandreject":
        return FilterTarget(
            MODEL_ANALOG, STYLE_NOTCH_BLEND, BLEND_NOTCH, var_role="width",
            fidelity="approximation",
            note="Bandreject: Notch Blend at the notch position; WIDTH -> resonance (wider = lower)",
        )
    return None


def target_for_serum1(index: int) -> FilterTarget:
    """Vital target for a Serum 1 filter type, by index into FILTER_NAMES."""
    if 0 <= index < len(SERUM1_FILTER_NAMES):
        target = _target_for_serum1_name(SERUM1_FILTER_NAMES[index])
        if target is not None:
            return target
        what = SERUM1_FILTER_NAMES[index]
    else:
        what = f"filter index {index}"
    return _unsupported(what)


def target_for_serum1_name(name: str) -> FilterTarget:
    """Vital target for a Serum 1 filter type, by its menu name."""
    target = _target_for_serum1_name(name.strip())
    return target if target is not None else _unsupported(f"filter {name!r}")


# --------------------------------------------------------------------------
# Serum 2 names
# --------------------------------------------------------------------------

_RE2_MG = re.compile(r"MgL(\d+)", re.I)
_RE2_SINGLE = re.compile(r"([LHBPN])(\d+)")
_RE2_DUAL = re.compile(r"([LHBPN])([LHBPN])(\d+)")
_RE2_MORPH = re.compile(r"(LBH|LPH|LNH|BPN)(\d+)")
_RE2_COMB = re.compile(r"(Comb|Flange)(L6|H6|HL6)?([PN])")
_RE2_PHS = re.compile(r"(Flange)?Phase(\d+)(L6|H6|HL6)?([PN])")
_RE2_EQ = re.compile(r"([LBH])EQ(\d+)")
_RE2_DIST_COMB = re.compile(r"DistComb([12])(LP|BP)")
_RE2_FORMANT = re.compile(r"Formant(ONE|TWO|THREE|I{1,3}|[123])", re.I)

_SERUM2_SPECIAL: dict[str, str] = {
    # Serum 2 name (lower-case) -> Serum 1 name
    "combs": "Combs",
    "allpasses": "Allpasses",
    "reverb": "Reverb",
    "reverb1": "Reverb",
    "diffuser": "Allpasses",
    "bandreject": "Bandreject",
    "add_bass": "Add Bass",
    "addbass": "Add Bass",
    "french": "French LP",
    "frenchlp": "French LP",
    "german": "German LP",
    "germanlp": "German LP",
    "scream": "Scream LP",
    "screamlp": "Scream LP",
    "screambp": "Scream BP",
    "scream3lp": "Scream LP",
    "rm": "Ring Mod",
    "ringmod": "Ring Mod",
    "rmx2": "Ring Modx2",
    "samphold": "SampHold",
    "sampholdn": "SampHold-",
    "comb2": "Cmb -",
    "combp": "Cmb +",
    "combn": "Cmb -",
    "flangep": "Flg +",
    "flangen": "Flg -",
}


def _target_for_serum2_name(name: str) -> FilterTarget | None:
    raw = name.strip()
    key = raw.lower().replace(" ", "").replace("-", "")

    if key in _SERUM2_SPECIAL:
        target = _target_for_serum1_name(_SERUM2_SPECIAL[key])
        if target is not None and key in ("diffuser", "reverb1", "scream3lp", "comb2"):
            target.note = f"Serum 2 {raw}: " + target.note
        return target

    if m := _RE2_MG.fullmatch(raw):
        return _ladder(int(m.group(1)))
    if m := _RE2_DUAL.fullmatch(raw):
        return _dual(m.group(1), m.group(2), int(m.group(3)))
    if m := _RE2_SINGLE.fullmatch(raw):
        return _svf(m.group(1), int(m.group(2)))
    if m := _RE2_MORPH.fullmatch(raw):
        return _morph(m.group(1), int(m.group(2)))
    if m := _RE2_COMB.fullmatch(raw):
        kind = "Cmb" if m.group(1) == "Comb" else "Flg"
        return _comb(kind, m.group(2) or "", m.group(3) == "P")
    if m := _RE2_PHS.fullmatch(raw):
        return _phaser(int(m.group(2)), m.group(3) or "", m.group(4) == "P",
                       flanger=bool(m.group(1)))
    if m := _RE2_EQ.fullmatch(raw):
        return _eq({"L": "Low", "B": "Band", "H": "High"}[m.group(1)], int(m.group(2)))
    if m := _RE2_DIST_COMB.fullmatch(raw):
        return _dist_comb(int(m.group(1)), m.group(2))
    if m := _RE2_FORMANT.fullmatch(raw):
        variant = {"one": 1, "two": 2, "three": 3, "i": 1, "ii": 2, "iii": 3,
                   "1": 1, "2": 2, "3": 3}[m.group(1).lower()]
        return _formant(variant)

    # Serum 2 only types.
    if key in ("ladderems", "ladderacid"):
        flavour = "EMS-style" if key == "ladderems" else "acid (TB-303-style)"
        return FilterTarget(
            MODEL_LADDER, STYLE_24, BLEND_LOW, fidelity="character",
            note=f"Serum 2 {raw}: {flavour} ladder low-pass rendered by Vital's Ladder 24 dB",
        )
    if key == "laddermg":
        return FilterTarget(
            MODEL_LADDER, STYLE_24, BLEND_LOW, fidelity="character",
            note=f"Serum 2 {raw}: Moog-style ladder low-pass rendered by Vital's Ladder 24 dB",
        )
    if key == "dirtymg":
        return FilterTarget(
            MODEL_DIRTY, STYLE_24, BLEND_LOW, fidelity="character",
            note=f"Serum 2 {raw}: saturating Moog-style low-pass rendered by Vital's Dirty 24 dB",
        )
    if key == "wsp":
        return FilterTarget(
            MODEL_DIRTY, STYLE_12, BLEND_LOW, fidelity="character",
            note=f"Serum 2 {raw}: Wasp-style dirty low-pass rendered by Vital's Dirty 12 dB",
            drive_hint_db=6.0,
        )
    if key == "exp":
        return FilterTarget(
            MODEL_ANALOG, STYLE_24, BLEND_LOW, fidelity="character",
            note=f"Serum 2 {raw}: expressive low-pass rendered by Vital's Analog 24 dB low-pass",
        )
    if key == "expbpf":
        return FilterTarget(
            MODEL_ANALOG, STYLE_24, BLEND_BAND, fidelity="character",
            note=f"Serum 2 {raw}: expressive band-pass rendered by Vital's Analog 24 dB band-pass",
        )
    if key == "djmixer":
        return FilterTarget(
            MODEL_ANALOG, STYLE_NOTCH_BLEND, BLEND_NOTCH, fidelity="character",
            note=(f"Serum 2 {raw}: DJ-mixer filter (low-pass below centre, high-pass above) has "
                  "no single Vital counterpart; Notch Blend at the notch position as a placeholder, "
                  "sweep blend 0..2 for the low-pass -> high-pass motion"),
        )
    if key == "pz_svf" or key == "pzsvf":
        return FilterTarget(
            MODEL_DIGITAL, STYLE_12, BLEND_LOW, fidelity="character",
            note=f"Serum 2 {raw}: pole-zero SVF rendered by Vital's Digital 12 dB low-pass",
        )
    return None


def target_for_serum2(name: str) -> FilterTarget:
    """Vital target for a Serum 2 filter type string (e.g. 'MgL24', 'CombHL6P')."""
    target = _target_for_serum2_name(name)
    return target if target is not None else _unsupported(f"Serum 2 filter {name!r}")


# --------------------------------------------------------------------------
# VAR knob
# --------------------------------------------------------------------------


def apply_var(target: FilterTarget, var: float, cutoff_note: float) -> dict[str, float]:
    """Extra Vital parameters for the filter slot derived from Serum's VAR knob.

    ``var`` is Serum's normalised 0..1 VAR value, ``cutoff_note`` the already
    converted Vital cutoff (MIDI note) of this slot.  Keys have no
    ``filter_N_`` prefix.  Values override whatever the caller set from the
    main Serum knobs (e.g. ``mix`` for EQ/thru types, ``resonance`` for
    width).  For ``second_cutoff`` nothing is returned here: the caller puts
    ``target.second`` into the next free filter slot with
    ``cutoff = var_to_cutoff_note(var)``.
    """
    var = _clamp(var, 0.0, 1.0)
    role = target.var_role

    if role == "morph_blend":
        return {"blend": _clamp(2.0 * var, 0.0, 2.0)}

    if role == "gain":
        gain = 2.0 * var - 1.0  # -1 cut .. 0 flat .. +1 boost
        amount = abs(gain)
        if amount < 1e-6:
            return {"mix": 0.0}
        if gain > 0:
            # Boost: dry + pass band (a high cut plus makeup for Low EQ, etc.)
            return {"style": float(target.style), "blend": target.blend, "mix": amount}
        # Cut: dry + complement of the pass band.
        if target.blend == BLEND_BAND:
            return {"style": float(STYLE_NOTCH_BLEND), "blend": BLEND_NOTCH, "mix": amount}
        return {"style": float(target.style), "blend": BLEND_HIGH - target.blend, "mix": amount}

    if role == "formant":
        return {"formant_transpose": (2.0 * var - 1.0) * FORMANT_TRANSPOSE_RANGE}

    if role == "width":
        # Wider notch = less resonance.
        return {"resonance": _clamp(1.0 - var, 0.0, 1.0)}

    if role == "comb_freq":
        comb_note = var_to_cutoff_note(var)
        offset = _clamp(cutoff_note - comb_note, BLEND_TRANSPOSE_MIN, BLEND_TRANSPOSE_MAX)
        return {"cutoff": comb_note, "blend_transpose": offset}

    if role == "feedback_filter":
        if target.style >= COMB_BAND_COMB:
            # HL WID: widen the feedback band around the comb cutoff.
            return {"blend": _clamp(2.0 * var, 0.0, 2.0), "blend_transpose": 0.0}
        filter_note = var_to_cutoff_note(var)
        offset = _clamp(filter_note - cutoff_note, BLEND_TRANSPOSE_MIN, BLEND_TRANSPOSE_MAX)
        return {"blend_transpose": offset}

    if role == "thru":
        return {"mix": _clamp(1.0 - 0.5 * var, 0.0, 1.0)}

    if role == "damp":
        return {"blend": BLEND_LOW,
                "blend_transpose": BLEND_TRANSPOSE_MAX * (1.0 - var)}

    # "none", "second_cutoff", "scream", "boeuf": nothing to add.
    return {}


__all__ = [
    "FilterTarget",
    "target_for_serum1",
    "target_for_serum1_name",
    "target_for_serum2",
    "apply_var",
    "map_resonance",
    "var_to_cutoff_note",
    "formant_xy_from_cutoff",
    "SERUM1_FILTER_NAMES",
    "MODEL_NAMES",
    "STYLE_NAMES",
    "STYLE_COUNTS",
    "VAR_ROLES",
    "FIDELITIES",
]
