"""Reader for Xfer Serum 1.x presets (VST2 ``.fxp``).

Layout, as verified against the preset library and against the plugin itself
(see docs/FORMATS.md and docs/FINDINGS_AND_PLAN.md):

    60-byte VST2 FXP header ('CcnK' / 'FPCh', plugin id 'XfsX')
    zlib-compressed opaque chunk

Inside the decompressed chunk (all variants):

    0x0000  modulation slots  1..16   (16 records of 40 bytes)
    0x3460  parameters 0..227         (float32, normalised 0..1)
    0x3BE0  FX rack order             (10 int32: rack position per effect)
    0x3C08  oscillator A wavetable name   (512-byte NUL-terminated)
    0x3E08  oscillator B wavetable name
    0x4008  noise sample name
    0x4972  preset name  / 0x49A0 author / 0x49D0 menu
    0x4A60  macro 1..4 names (0x20 apart)
    0x4AE0  parameters 228..298
    varies  global switches block (voicing, noise flags, filter keytrack,
            unison range/tuning, chaos flags): it follows the parameter array,
            whose length depends on the build, so it is located by content
            (0x4C48 in current builds, 0x4C44 and 0x4B9C in older ones)
    varies  modulation slots 17..32, located by their 80 80 <n> FF marker

Between the parameters and the FX order block (0x37F0..0x3BE0) Serum keeps a
per-effect record; the only byte read from it is the reverb's Plate/Hall
switch.

LFO shapes and per-LFO switches come in two layouts:

  * "classic" (blobs of 20-34 KB, written by builds up to ~1.3):
      0x0280  LFO 1-4 shapes: 12 arrays x 65 float64 (tension x4, x x4, y x4)
      0x1AE0  LFO 1-4 settings record (point counts, rate copies, six flag
              groups of four bytes: anchor, Hz mode, dotted, triplet,
              not-off, envelope)
      0x1B70  LFO 5-8 shapes, same layout as the first block
      0x33D0  LFO 5-8: only the anchor bytes are recognisable
  * "new" (172,736-byte blobs, current builds): the classic region is zero and
      eight blocks of 0x2D28 bytes start at 0x84D8, each holding tension[481],
      x[481], y[479], six flag bytes, a point count and a copy of the rate.

The flag semantics were established with single-change fixture presets saved
from the plugin (DebugPresets/serum1) and checked against the plugin's own
rate read-out over the library.
"""

from __future__ import annotations

import re
import struct
import zlib
from dataclasses import dataclass, field

from .serum_params import PARAMS

FXP_HEADER = 60
PLUGIN_ID = b"XfsX"

# Fixed offsets inside the decompressed chunk.
OFF_PARAMS_LOW = 0x3460     # parameters 0..227
OFF_PARAMS_HIGH = 0x4AE0    # parameters 228..298
N_PARAMS_LOW = 228

OFF_FX_ORDER = 0x3BE0
OFF_WT_A = 0x3C08
OFF_WT_B = 0x3E08
OFF_NOISE = 0x4008
OFF_PRESET_NAME = 0x4972
OFF_AUTHOR = 0x49A0
OFF_MENU = 0x49D0
OFF_MACRO_NAMES = 0x4A60
MACRO_NAME_STRIDE = 0x20

# Classic LFO layout.
CLASSIC_BLOCKS = (0x0280, 0x1B70)          # LFO 1-4, LFO 5-8 shape blocks
CLASSIC_ARRAY_STRIDE = 520                 # 65 float64
CLASSIC_ARRAY_LEN = 65
CLASSIC_SETTINGS = 0x1AE0                  # LFO 1-4 settings record
CLASSIC_SETTINGS_FLAGS = 0x14              # six groups of 4 bytes from here
CLASSIC_SETTINGS_5_8 = 0x33D0              # LFO 5-8: anchor bytes only

# New LFO layout.
NEW_LFO_BASE = 0x84D8
NEW_LFO_STRIDE = 0x2D28
NEW_ARRAY_LEN = 481
NEW_OFF_X = 0xF08
NEW_OFF_Y = 0x1E10
NEW_OFF_FLAGS = 0x2D08
NEW_OFF_NPTS = 0x2D10

# Global switches block: float32 fields, one per non-automatable control.  The
# block follows the parameter array and moves with the number of parameters
# in the writing build; SETTINGS_BASES lists the starts seen in the library
# (current builds first).  Field meanings come from the single-change fixtures
# in DebugPresets/serum1 (17-21), from rendering crafted variants through the
# plugin (noise flags, chaos flags) and from the library-wide correlation of
# each field with the parameters it belongs to (docs/FORMATS.md).
SETTINGS_BASES = (0x4C48, 0x4C44, 0x4B9C)
SETTINGS_SIZE = 0x64
SET_TUNING_REF = 0x00        # A4 reference: 430 + 20 * v Hz (0.5 = 440 Hz)
SET_UNISON_TUNING_A = 0x08   # index / 4: Linear, Super, Exp, Inv, Random
SET_UNISON_TUNING_B = 0x0C
SET_MONO = 0x10
SET_LEGATO = 0x14
SET_PORTA_ALWAYS = 0x18
SET_PORTA_SCALED = 0x1C
SET_OVERSAMPLING = 0x20      # index / 2: 1x, 2x (default), 4x
SET_NOISE_ONE_SHOT = 0x24
SET_NOISE_PITCH_TRACK = 0x28
SET_POLYPHONY = 0x2C         # (voices - 1) / 31
SET_FILTER_KEYTRACK = 0x34
SET_UNISON_RANGE_A = 0x38    # semitones / 48
SET_UNISON_RANGE_B = 0x3C
SET_CHAOS_MONO = (0x40, 0x44)
SET_CHORUS_MONO = 0x48       # 1 = chorus LFO in phase on both channels (no L/R offset)
SET_CHAOS_SH = (0x50, 0x54)
SET_REVERB_HALL = 0x5C       # 1 = Hall (default), 0 = Plate
UNISON_TUNING_NAMES = ("Linear", "Super", "Exp", "Inv", "Random")

# Per-effect record region: a byte copy of the reverb's Plate/Hall switch
# (1 = Hall) sits two bytes before the reverb enable mirror at 0x3B06.  Used
# when the switches block is absent (20-21 KB presets).
OFF_REVERB_HALL = 0x3B04

# Modulation record: 40 bytes, self-identified by 80 <slot> FF at +0x21.  The
# byte at +0x20 is usually 0x80 but not always (0xFF and arbitrary values occur
# in about 3% of library presets, typically on LFO -> level routings), so it
# is not part of the marker; a match is validated against the record's fields.
MOD_RECORD_SIZE = 40
MOD_MARKER = re.compile(rb"(?=\x80(.)\xff)", re.S)   # lookahead: markers may overlap
MOD_MARKER_OFFSET = 0x21
MOD_OFF_AMOUNT = 0x04       # float32, bipolar -1..1
MOD_OFF_OUT = 0x08          # float32, output range scaler (1.0 = 100%)
MOD_OFF_SOURCE = 0x14       # uint16, Serum source enum
MOD_OFF_AUX_SOURCE = 0x16   # uint16, secondary ("aux") source
MOD_OFF_DEST = 0x1A         # uint16, index into the 299-parameter list

# Serum modulation source enum.  Env/LFO/Macro were established by corpus
# correlation; the rest come from fixture presets with matrix slots assigned
# in a known order (DebugPresets/serum1/11 sources.fxp and 11b sources extra.fxp).
MOD_SOURCES = {
    1: "mod_wheel",
    2: "env_1", 3: "env_2", 4: "env_3",
    5: "lfo_1", 6: "lfo_2", 7: "lfo_3", 8: "lfo_4",
    9: "lfo_5", 10: "lfo_6", 11: "lfo_7", 12: "lfo_8",
    13: "velocity",
    14: "note",
    15: "aftertouch",        # channel aftertouch (fixture 11b)
    16: "poly_aftertouch",
    17: "chaos_1",
    18: "chaos_2",
    19: "noise_osc",         # fixture 11b
    20: "note_random_1",
    21: "note_random_2",
    22: "note_alt_1",
    23: "note_alt_2",
    24: "macro_1", 25: "macro_2", 26: "macro_3", 27: "macro_4",
    28: "pitch_bend",
    29: "mpe_x", 30: "mpe_y", 31: "mpe_z",
    32: "release_velocity",
    33: "fixed",
}

# Effects in the order of their enable parameters / the FX order block.
FX_ORDER_NAMES = (
    "distortion", "flanger", "phaser", "chorus", "delay",
    "compressor", "reverb", "eq", "filter", "hyper",
)


class SerumReadError(Exception):
    """Raised when a Serum 1 preset is present but cannot be parsed."""


class NotASerumPreset(SerumReadError):
    """The file is some other plugin's preset (Sylenth1, Nexus, ...).

    Preset libraries are routinely mixed, so a batch run reports these as
    skipped rather than as conversion failures.
    """


@dataclass
class ModSlot:
    slot: int
    source: int
    aux_source: int
    dest: int
    amount: float          # -1..1
    out_range: float       # 1.0 == full range

    @property
    def source_name(self) -> str | None:
        return MOD_SOURCES.get(self.source)

    @property
    def aux_source_name(self) -> str | None:
        return MOD_SOURCES.get(self.aux_source) if self.aux_source else None

    @property
    def dest_name(self) -> str | None:
        if 0 <= self.dest < len(PARAMS):
            return PARAMS[self.dest][0]
        return None

    @property
    def active(self) -> bool:
        return abs(self.amount) > 1e-6 and self.source != 0


@dataclass
class LfoSettings:
    """The LFO panel switches that are not VST parameters."""

    hz_mode: bool = False        # BPM switch off: rate knob is 0..100 Hz
    dotted: bool = False
    triplet: bool = False
    anchor: bool = True
    mode: str = "off"            # "trig", "env" or "off"
    known: bool = True           # False when the layout could not be read

    @classmethod
    def from_flags(cls, flags: bytes | list[int]) -> "LfoSettings":
        anchor, hz, dot, trip, not_off, env = (int(x) for x in flags[:6])
        if not_off and env:
            mode = "env"
        elif not_off:
            mode = "trig"
        else:
            mode = "off"
        return cls(hz_mode=hz == 1, dotted=dot == 1, triplet=trip == 1, anchor=anchor == 1, mode=mode)


@dataclass
class GlobalSettings:
    """Non-automatable switches: voicing, noise, filter, unison, chaos, reverb."""

    mono: bool = False
    legato: bool = False
    polyphony: int = 8
    porta_always: bool = False
    porta_scaled: bool = False
    noise_one_shot: bool = False
    noise_pitch_track: bool = False
    filter_keytrack: bool = False
    unison_range: tuple[float, float] = (2.0, 2.0)      # semitones, osc A / B
    unison_tuning: tuple[str, str] = ("Linear", "Linear")
    chaos_mono: tuple[bool, bool] = (False, False)
    chaos_sh: tuple[bool, bool] = (False, False)
    reverb_hall: bool = True
    a4_hz: float = 440.0         # tuning reference, 430..450 Hz
    oversampling: int = 1        # 0 = 1x, 1 = 2x, 2 = 4x
    chorus_mono: bool = False    # chorus LFO without the L/R phase offset
    known: bool = True           # False when the block could not be located


@dataclass
class LfoShape:
    """A Serum LFO curve: points in 0..1 with a per-segment tension value."""

    xs: list[float] = field(default_factory=list)   # 0..1, non-decreasing
    ys: list[float] = field(default_factory=list)   # 0..1, 0 == top of display
    curves: list[float] = field(default_factory=list)  # 0.5 == linear
    settings: LfoSettings = field(default_factory=LfoSettings)

    @property
    def is_default(self) -> bool:
        return len(self.xs) <= 2 and all(abs(c - 0.5) < 1e-6 for c in self.curves)


@dataclass
class Serum1Patch:
    name: str
    author: str
    menu: str
    macro_names: list[str]
    params: list[float]           # 299 values, normalised 0..1
    wavetable_a: str
    wavetable_b: str
    noise_sample: str
    mod_slots: list[ModSlot]
    lfo_shapes: list[LfoShape]    # 8 entries
    fx_order: list[int] | None = None   # rack position per FX_ORDER_NAMES entry
    settings: GlobalSettings = field(default_factory=GlobalSettings)
    layout: str = "classic"       # "classic" or "new"
    source_path: str = ""
    version: str = "serum1"

    def value(self, index: int) -> float:
        return self.params[index]

    @property
    def fx_rack(self) -> list[str]:
        """Effect names in rack order (top first)."""
        if not self.fx_order:
            return ["hyper", "distortion", "flanger", "phaser", "chorus",
                    "delay", "compressor", "reverb", "eq", "filter"]
        return [name for _, name in sorted(zip(self.fx_order, FX_ORDER_NAMES))]


def _cstring(blob: bytes, offset: int, length: int) -> str:
    if offset + length > len(blob):
        return ""
    raw = blob[offset : offset + length].split(b"\x00", 1)[0]
    return raw.decode("utf-8", "replace").strip()


def _doubles(blob: bytes, offset: int, count: int) -> list[float] | None:
    if offset < 0 or offset + count * 8 > len(blob):
        return None
    return list(struct.unpack_from("<%dd" % count, blob, offset))


def _build_shape(curves, xs, ys, settings: LfoSettings) -> LfoShape:
    """Trim raw arrays to the points actually used and validate them."""
    if xs is None or ys is None or curves is None:
        return LfoShape(settings=settings)

    # Points run left to right; the shape ends at the first point that reaches
    # the right edge, and everything after is padding.
    count = len(xs)
    for i, x in enumerate(xs):
        if x >= 1.0 - 1e-9:
            count = i + 1
            break

    if count < 2 or not all(-0.001 <= v <= 1.001 for v in xs[:count] + ys[:count]):
        return LfoShape(settings=settings)
    return LfoShape(
        xs=xs[:count], ys=ys[:count], curves=curves[: max(count - 1, 1)], settings=settings
    )


def _read_classic_shape(blob: bytes, block: int, lfo: int, settings: LfoSettings) -> LfoShape:
    """One LFO from a 12-array classic block (arrays 0-3 tension, 4-7 x, 8-11 y)."""
    def array(slot: int):
        return _doubles(blob, block + CLASSIC_ARRAY_STRIDE * slot, CLASSIC_ARRAY_LEN)

    return _build_shape(array(lfo), array(4 + lfo), array(8 + lfo), settings)


def _read_classic_settings(blob: bytes) -> list[LfoSettings]:
    """Per-LFO switches for the classic layout (LFO 1-4 fully, 5-8 anchor only)."""
    out: list[LfoSettings] = []
    base = CLASSIC_SETTINGS + CLASSIC_SETTINGS_FLAGS
    for i in range(4):
        if base + 0x18 > len(blob):
            out.append(LfoSettings(known=False))
            continue
        flags = [blob[base + 4 * k + i] for k in range(6)]
        if all(f in (0, 1) for f in flags):
            out.append(LfoSettings.from_flags(flags))
        else:
            out.append(LfoSettings(known=False))
    for i in range(4):
        anchor = blob[CLASSIC_SETTINGS_5_8 + i] if CLASSIC_SETTINGS_5_8 + 4 <= len(blob) else 1
        out.append(LfoSettings(anchor=anchor == 1, mode="off", known=False))
    return out


def _read_new_lfo(blob: bytes, index: int) -> LfoShape:
    base = NEW_LFO_BASE + NEW_LFO_STRIDE * index
    flags = blob[base + NEW_OFF_FLAGS : base + NEW_OFF_FLAGS + 6]
    if len(flags) == 6 and all(f in (0, 1) for f in flags):
        settings = LfoSettings.from_flags(flags)
    else:
        settings = LfoSettings(known=False)
    curves = _doubles(blob, base, NEW_ARRAY_LEN)
    xs = _doubles(blob, base + NEW_OFF_X, NEW_ARRAY_LEN)
    ys = _doubles(blob, base + NEW_OFF_Y, NEW_ARRAY_LEN - 2)
    return _build_shape(curves, xs, ys, settings)


def _uses_new_layout(blob: bytes) -> bool:
    if len(blob) < NEW_LFO_BASE + 8 * NEW_LFO_STRIDE:
        return False
    return not any(blob[CLASSIC_BLOCKS[0] : CLASSIC_BLOCKS[0] + 1024])


def _read_lfos(blob: bytes) -> tuple[list[LfoShape], str]:
    if _uses_new_layout(blob):
        return [_read_new_lfo(blob, i) for i in range(8)], "new"

    settings = _read_classic_settings(blob)
    shapes: list[LfoShape] = []
    for block_index, block in enumerate(CLASSIC_BLOCKS):
        for lfo in range(4):
            shapes.append(_read_classic_shape(blob, block, lfo, settings[block_index * 4 + lfo]))
    return shapes, "classic"


def _read_fx_order(blob: bytes) -> list[int] | None:
    if OFF_FX_ORDER + 40 > len(blob):
        return None
    order = list(struct.unpack_from("<10i", blob, OFF_FX_ORDER))
    return order if sorted(order) == list(range(10)) else None


def _f32(blob: bytes, offset: int) -> float:
    return struct.unpack_from("<f", blob, offset)[0]


def _settings_base(blob: bytes) -> int | None:
    """Locate the global switches block by its invariants.

    Four landmarks identify it: 0.5 at +0x00 and +0x20, 1.0 at +0x30 and a
    polyphony value at +0x2C that is an exact (n - 1)/31.  Three of the four
    are enough (a handful of presets have the +0x00 field at zero).
    """
    best: tuple[int, int] | None = None
    for base in SETTINGS_BASES:
        if base + SETTINGS_SIZE > len(blob):
            continue
        poly = _f32(blob, base + SET_POLYPHONY)
        score = (
            int(abs(_f32(blob, base) - 0.5) < 1e-5)
            + int(abs(_f32(blob, base + 0x20) - 0.5) < 1e-5)
            + int(abs(_f32(blob, base + 0x30) - 1.0) < 1e-5)
            + int(0.0 < poly <= 1.0 and abs(poly * 31 - round(poly * 31)) < 1e-3)
        )
        if best is None or score > best[0]:
            best = (score, base)
    return best[1] if best is not None and best[0] >= 3 else None


def _flag(blob: bytes, offset: int) -> bool:
    return _f32(blob, offset) > 0.5


def _read_settings(blob: bytes) -> GlobalSettings:
    base = _settings_base(blob)
    hall = blob[OFF_REVERB_HALL] == 1 if len(blob) > OFF_REVERB_HALL and blob[OFF_REVERB_HALL] in (0, 1) else True
    if base is None:
        return GlobalSettings(reverb_hall=hall, known=False)

    def tuning(offset: int) -> str:
        index = round(_f32(blob, base + offset) * 4)
        return UNISON_TUNING_NAMES[index] if 0 <= index < len(UNISON_TUNING_NAMES) else "Linear"

    def semitones(offset: int) -> float:
        return max(0.0, min(48.0, 48.0 * _f32(blob, base + offset)))

    poly = int(round(_f32(blob, base + SET_POLYPHONY) * 31)) + 1
    return GlobalSettings(
        mono=_flag(blob, base + SET_MONO),
        legato=_flag(blob, base + SET_LEGATO),
        polyphony=max(1, min(32, poly)),
        porta_always=_flag(blob, base + SET_PORTA_ALWAYS),
        porta_scaled=_flag(blob, base + SET_PORTA_SCALED),
        noise_one_shot=_flag(blob, base + SET_NOISE_ONE_SHOT),
        noise_pitch_track=_flag(blob, base + SET_NOISE_PITCH_TRACK),
        filter_keytrack=_flag(blob, base + SET_FILTER_KEYTRACK),
        unison_range=(semitones(SET_UNISON_RANGE_A), semitones(SET_UNISON_RANGE_B)),
        unison_tuning=(tuning(SET_UNISON_TUNING_A), tuning(SET_UNISON_TUNING_B)),
        chaos_mono=tuple(_flag(blob, base + o) for o in SET_CHAOS_MONO),
        chaos_sh=tuple(_flag(blob, base + o) for o in SET_CHAOS_SH),
        reverb_hall=_flag(blob, base + SET_REVERB_HALL),
        a4_hz=430.0 + 20.0 * max(0.0, min(1.0, _f32(blob, base + SET_TUNING_REF))),
        oversampling=max(0, min(2, int(round(_f32(blob, base + SET_OVERSAMPLING) * 2)))),
        chorus_mono=_flag(blob, base + SET_CHORUS_MONO),
    )


def _read_mod_slots(blob: bytes) -> list[ModSlot]:
    """Find every modulation record by its 80 80 <slot> FF marker."""
    slots: dict[int, ModSlot] = {}
    for match in MOD_MARKER.finditer(blob):
        index = match.group(1)[0]
        base = match.start() - MOD_MARKER_OFFSET
        if base < 0 or index > 31 or base + MOD_RECORD_SIZE > len(blob):
            continue
        if index < 16 and base != index * MOD_RECORD_SIZE:
            continue                       # slots 1-16 sit at fixed offsets
        if index in slots:
            continue
        amount, out_range = struct.unpack_from("<2f", blob, base + MOD_OFF_AMOUNT)
        if not (-8.0 <= amount <= 8.0) or amount != amount:  # reject NaN / garbage
            continue
        source, aux = struct.unpack_from("<2H", blob, base + MOD_OFF_SOURCE)
        dest = struct.unpack_from("<H", blob, base + MOD_OFF_DEST)[0]
        if source > 64 or aux > 64 or dest >= 1024:
            continue                       # a marker-shaped byte run inside other data
        slots[index] = ModSlot(
            slot=index + 1,
            source=source,
            aux_source=aux,
            dest=dest,
            amount=amount,
            out_range=out_range,
        )
    return [slots[i] for i in sorted(slots)]


def decompress(path: str) -> bytes:
    """Return the decompressed Serum state chunk of a ``.fxp`` file."""
    with open(path, "rb") as handle:
        data = handle.read()

    if not data:
        raise NotASerumPreset("file is empty")
    if len(data) < FXP_HEADER or data[:4] != b"CcnK":
        raise NotASerumPreset("not a VST2 .fxp file (no CcnK header)")
    if data[8:12] != b"FPCh":
        raise NotASerumPreset("not an opaque-chunk .fxp (fxMagic %r)" % data[8:12])
    if data[16:20] != PLUGIN_ID:
        raise NotASerumPreset(
            "another plugin's preset (id %s)" % data[16:20].decode("latin-1")
        )

    chunk_size = struct.unpack_from(">I", data, 56)[0]
    chunk = data[FXP_HEADER : FXP_HEADER + chunk_size]
    try:
        return zlib.decompress(chunk)
    except zlib.error as exc:
        raise SerumReadError(f"chunk is not zlib data: {exc}") from exc


def read(path: str) -> Serum1Patch:
    """Parse a Serum 1 ``.fxp`` into a :class:`Serum1Patch`."""
    blob = decompress(path)
    if len(blob) < OFF_PARAMS_LOW + N_PARAMS_LOW * 4:
        raise SerumReadError("state chunk too small to hold a parameter block")

    params = list(struct.unpack_from("<%df" % N_PARAMS_LOW, blob, OFF_PARAMS_LOW))
    high_count = len(PARAMS) - N_PARAMS_LOW
    if len(blob) >= OFF_PARAMS_HIGH + high_count * 4:
        params += list(struct.unpack_from("<%df" % high_count, blob, OFF_PARAMS_HIGH))
    else:
        # Presets written by older Serum builds stop before the second block.
        from .serum_params import normalised_default

        params += [normalised_default(i) for i in range(N_PARAMS_LOW, len(PARAMS))]

    params = [0.0 if v != v else max(0.0, min(1.0, v)) for v in params]

    # Older builds wrote the second parameter block before all of its entries
    # existed, leaving uninitialised memory that Serum itself ignores (checked
    # against the plugin's read-back per blob size): 21 KB files are valid up
    # to the slot 17-32 amounts, 28 KB files up to the compressor gains.
    from .serum_params import normalised_default

    if len(blob) < 21000:
        unreliable_from = N_PARAMS_LOW
    elif len(blob) < 28000:
        unreliable_from = 260      # LFO 5-8 rates and everything after
    elif len(blob) < 33000:
        unreliable_from = 273      # LFO rise/delay and the FX level slots
    else:
        unreliable_from = len(PARAMS)
    for i in range(unreliable_from, len(PARAMS)):
        params[i] = normalised_default(i)

    shapes, layout = _read_lfos(blob)

    macro_names = [
        _cstring(blob, OFF_MACRO_NAMES + MACRO_NAME_STRIDE * i, MACRO_NAME_STRIDE)
        for i in range(4)
    ]

    from pathlib import Path

    name = _cstring(blob, OFF_PRESET_NAME, 32) or Path(path).stem
    return Serum1Patch(
        name=name,
        author=_cstring(blob, OFF_AUTHOR, 48),
        menu=_cstring(blob, OFF_MENU, 48),
        macro_names=macro_names,
        params=params,
        wavetable_a=_cstring(blob, OFF_WT_A, 512),
        wavetable_b=_cstring(blob, OFF_WT_B, 512),
        noise_sample=_cstring(blob, OFF_NOISE, 512),
        mod_slots=_read_mod_slots(blob),
        lfo_shapes=shapes,
        fx_order=_read_fx_order(blob),
        settings=_read_settings(blob),
        layout=layout,
        source_path=path,
    )
