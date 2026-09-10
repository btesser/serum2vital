# File formats

Notes from reverse-engineering the three formats this converter touches. Every
claim below was checked against real files: 393 randomly sampled Serum 1 `.fxp`
presets, 250 Serum 2 `.SerumPreset` files and one Vital 1.5.5 `.vital` preset,
all from a local Serum/Vital installation, plus the single-change fixture
presets in `DebugPresets/` (see `FIXTURE_PRESETS_TASK.md`). Offsets and
tables below are the ones used by `serum2vital/serum1.py`, `serum2.py`,
`serum_tables.py`, `wavetables.py` and `writer.py`.

---

## Serum 1 — `.fxp`

A standard VST2 opaque-chunk preset wrapping one zlib stream.

### Container

| offset | size | meaning |
|--------|------|---------|
| 0x00 | 4 | `CcnK` |
| 0x04 | 4 | big-endian, file size − 8 |
| 0x08 | 4 | `FPCh` (opaque chunk) |
| 0x0C | 4 | format version (1) |
| 0x10 | 4 | plugin id `XfsX` |
| 0x14 | 4 | plugin version |
| 0x18 | 4 | program count |
| 0x1C | 28 | program name, NUL padded |
| 0x38 | 4 | big-endian chunk size |
| 0x3C | … | zlib stream |

The decompressed state is 20 KB – 170 KB depending on how much wavetable data
the preset embeds.

### Decompressed layout

| offset | contents |
|--------|----------|
| `0x0000` | modulation slots 1–16 (16 records × 40 bytes) |
| `0x0280` | LFO 1–4 shape block (12 arrays × 65 float64, stride 520) — classic layout only |
| `0x1AE0` | LFO 1–4 switches (see below) |
| `0x1B70` | LFO 5–8 shape block — classic layout only |
| `0x33D0` | LFO 5–8 switches: only the ANCH bytes are recognisable — classic layout only |
| `0x3460` | parameters 0–227, float32 normalised 0..1 |
| `0x3BE0` | FX rack order (10 × int32, see below) |
| `0x3C08` | oscillator A wavetable name (512-byte NUL-terminated) |
| `0x3E08` | oscillator B wavetable name |
| `0x4008` | noise sample name |
| `0x4972` | preset name (32) |
| `0x49A0` | author (48) |
| `0x49D0` | menu / bank (48) |
| `0x4A60` | macro 1–4 names, 0x20 apart |
| `0x4AE0` | parameters 228–298 |
| varies | global switches block (see below): `0x4C48` in current builds, `0x4C44` and `0x4B9C` in older ones |
| `0x84D8` | LFO 1–8 blocks, 0x2D28 bytes each — new layout only |
| varies | modulation slots 17–32 |

Between the parameters and the FX order block (`0x37F0`–`0x3BE0`) Serum keeps a
per-effect record mirroring each effect's knobs, mode and enable state as
bytes (distortion mode/enable at `0x396C`/`0x396E`, delay at `0x3A7C`/`0x3A7E`,
reverb at `0x3B04`/`0x3B06`, hyper unison/enable/retrig at
`0x3BD0`/`0x3BD2`/`0x3BD9`). Everything in it duplicates a parameter except the
reverb's Plate/Hall byte at `0x3B04` (1 = Hall, Init's value; 0 in about a
quarter of the library's reverb presets), which also mirrors the switches
block field at +0x5C; the reader uses the byte only when the block is absent.

### The chunk is two zlib streams

The opaque chunk after the 60-byte FXP header is not one zlib stream but

    zlib(state blob)        172,736 bytes in current builds
    zlib(second block)      16,384 bytes, identical in every preset examined
    uint32                  unknown, identical in every preset
    uint32 LE               length of the first zlib stream

and the header's byte-size field at offset 4 holds the whole file length.
Serum silently keeps its previous state when the trailer or the final length
word is missing, which is why earlier hand-crafted presets appeared to load as
Init. `tools/craft_fxp.py` writes edited copies that preserve the trailer;
that is how the noise and chaos switch bytes below were verified by rendering.

These offsets were stable across the whole sample (e.g. parameter 2, "A Pan",
read exactly 0.5 in 380 of 393 presets). The second parameter block exists
because Serum grew past 228 parameters after the format was fixed; presets
written by older builds simply end before it, and the reader falls back to the
documented defaults for 228–298.

Even when the second block is present it is only partly trustworthy in older
files: those builds wrote it before all of its entries existed, leaving
uninitialised memory that Serum itself ignores. Checked against the plugin's
own read-back, the reader (`serum1.read`) resets the tail of the block to the
documented defaults by decompressed size:

| decompressed size | trusted up to | reset to defaults from |
|-------------------|---------------|------------------------|
| under 21,000 bytes | parameter 227 | 228 (`Mod17 amt`) |
| under 28,000 bytes | parameter 259 (`Mod32 out`) | 260 (`LFO5Rate`) |
| under 33,000 bytes | parameter 272 (`Gain H`) | 273 (`LFO1 Rise`) |
| larger | all 299 | nothing |

### Parameters

299 float32 values, each normalised to 0..1, in VST parameter order. The
display value is `min + (max − min) × stored`. The name/range table comes from
Serum's own `SYParameters` listing for build 1.334 (see
[the reverse-engineering gist][gist]) and is reproduced in
`serum2vital/serum_params.py`.

Verification: taking the modal value of each parameter across the 393-preset
sample reproduces the documented factory default at every structural landmark —
`A Pan`/`A Semi`/`A Fine` at 0.5, `Bend U`/`Bend D` at 0.5417/0.4583,
`Mod 1..16 out` at 1.0, `LFO1-4 smooth` at 0.0.

The gist's names are wrong for a few slots in the current build (checked
against the plugin's own parameter list on 2026-09-10): 83 is the reverb's
**Decay** (0.8 .. 12 s, linear), 85 **Spin Rate** and 87 **Spin Depth** (the
gist says pre-delay, damp and width, which this reverb does not have); 193 is
`Mod 7 out` (the gist repeats `Mod 8 out`); 270-272 are the multiband
compressor's `CompMB L/M/H` band knobs (0 .. 200 %, 100 % neutral). Slots
289-298 (`FX Dist Level` ... `FX Hyper Level`) are per-effect output trims,
40·log10(2n) dB (0.5 = 0 dB); they are not converted (Vital's effects have no
output trim) and are non-default in about 1 % of presets, 8 % for the FX
filter. `serum2vital/serum_params.py` carries the corrected names.

Two parameters are stored as stepped indices rather than a continuous value
(the general rule for menu parameters is under "Indexed parameters" below):

* **Fil Type** — stored as `index / (count − 1)`, where `count` is the number
  of filter models in the Serum build that saved the file and differs between
  builds; divisors 95, 89 and 88 all appear in this library. The converter
  recovers the index by trying each divisor (`serum_tables.indexed`) and
  keeping the first that lands on an integer. Index 0 is `MG Low 6`; Serum's
  Init preset stores index 1, `MG Low 12` (checked on the `00 init.fxp`
  fixture).
* **LFO rate** — 229 steps (multiples of 1/228).  In BPM mode 16 steps make an
  octave from 32 bars (step 0) to 1/256 (step 225), with 1/4 at the 0.5
  default; in Hz mode the knob is `100·n⁴` Hz.

### Modulation matrix

32 records of 40 bytes: slots 1–16 at offset 0, slots 17–32 further in. Each
record is self-identifying — bytes `80 <slot> FF` sit at +0x21 — so the
reader scans for that marker (and, for slots 1–16, checks it sits at the
slot's fixed offset) instead of trusting a position. The byte at +0x20 is
0x80 in 99.4% of records but not part of the marker: 0xFF and arbitrary
values occur in about 3% of library presets, mostly on LFO → level routings,
and a reader that requires `80 80` there silently drops those routings (which
is how several factory sequences converted silent before 0.4.1).

| offset | type | meaning |
|--------|------|---------|
| +0x00 | float32 | current/smoothed amount (unverified; not read by the converter) |
| +0x04 | float32 | amount, bipolar −1..1 |
| +0x08 | float32 | output range (1.0 = 100%) |
| +0x0C | uint8 | matrix **type**: 0 unipolar, 1 bipolar. Set in 12% of active routings, mostly LFO → Fine/CoarsePit/Semi/Mast.Tun; measured on "SQ Minor Arp": an LFO → Semi routing at +100% with this byte set plays 12 − 24·y semitones, i.e. ±amount·range/2 around the knob |
| +0x14 | uint16 | source id |
| +0x16 | uint16 | auxiliary source id |
| +0x1A | uint16 | destination — an index into the 299-parameter list |
| +0x20 | uint16 | `0x8080` marker |
| +0x22 | uint16 | `0xFF00 \| slot` |

Bytes not listed here are uninitialised padding and leak fragments of unrelated
heap memory, which is why they vary between saves of the same patch.

**Destination** is the VST parameter index. Confirmed by the frequency ranking
across the corpus: the most common destination by a wide margin is 45
(`Fil Cutoff`, 419 uses), followed by 9 (`A Warp`), 11 (`A WTPos`), 22
(`B Warp`), 1 (`A Vol`) — exactly what you would expect of a real preset
library. (The neighbouring uint16 at +0x18 is a bijective remapping of the same
value, presumably Serum's internal menu ordering; unverified and not read by
the converter.)

**Source** ids. Envelopes, LFOs and macros were identified by correlating
"preset uses source S" against "preset has edited module M" over the corpus;
the rest come from the fixture preset `DebugPresets/serum1/11 sources.fxp`,
whose sixteen matrix slots use the remaining menu entries in a known order.
The full table is `MOD_SOURCES` in `serum2vital/serum1.py`:

| id | source | evidence |
|----|--------|----------|
| 1 | Mod Wheel | fixture |
| 2 | Env 1 | corpus: Env1 edited in 84% of users vs 51% baseline |
| 3 | Env 2 | corpus: 98% vs 11% |
| 4 | Env 3 | corpus: 100% vs 8% |
| 5–8 | LFO 1–4 | corpus: 84% / 82% / 81% / 76%, each against its own LFO |
| 9–12 | LFO 5–8 | by extension of the block |
| 13 | Velocity | fixture |
| 14 | Note | fixture |
| 15 | Aftertouch (channel) | fixture `11b sources extra.fxp` |
| 16 | Poly Aftertouch | fixture |
| 17, 18 | Chaos 1, Chaos 2 | fixture |
| 19 | Noise OSC | fixture `11b sources extra.fxp` |
| 20, 21 | NoteOn Rand 1, NoteOn Rand 2 | fixture |
| 22, 23 | NoteOn Alt, NoteOn Alt 2 | fixture |
| 24–27 | Macro 1–4 | corpus: correlates with each macro's own value being non-zero |
| 28 | Pitch Bend | fixture |
| 29–31 | MPE X, Y, Z | fixture |
| 32 | Release Velocity | fixture |
| 33 | Fixed | fixture |

Id 0 means the slot is unused. Every id in the table is now covered by a
fixture or by the corpus correlation.

### Global switches block

The controls that are not VST parameters (voicing, portamento switches, noise
buttons, filter keytrack, unison range/tuning, chaos switches) are float32
fields in a 0x64-byte block that directly follows the parameter array. The
array's length depends on the writing build, so the block moves: `0x4C48` in
the current build (318 internal parameters), `0x4C44` in the previous one,
`0x4B9C` in the 28 KB presets, and it does not exist in 20-21 KB files. The
reader locates it by its invariants (0.5 at +0x00 and +0x20, 1.0 at +0x30,
and a polyphony value that is an exact (n − 1)/31) rather than by offset.

| offset | field | encoding | evidence |
|--------|-------|----------|----------|
| +0x00 | A4 tuning reference | 430 + 20·v Hz (0.5 = 440 Hz) | crafted variants: 0 renders C4 at 255.7 Hz, 1 at 267.6 Hz (exactly 430/450 Hz references), and the Hz read-outs of cutoff shift with it |
| +0x08, +0x0C | unison tuning A, B | index / 4: Linear, Super, Exp, Inv, Random | fixture 20 (Super = 0.25), manual order |
| +0x10 | Mono | 0/1 | fixture 18 |
| +0x14 | Legato | 0/1 | fixture 18; only ever set with Mono in the library |
| +0x18 | Porta "Always" | 0/1 | fixture 24 (also: set in 27% of presets with portamento time, 0.7% without) |
| +0x1C | Porta "Scaled" | 0/1 | fixture 25 |
| +0x20 | Oversampling | index / 2: 1x, 2x (default), 4x | crafted variants: 0 aliases heavily on a Sync-warped note (+6.9 dB alias-to-harmonic ratio, and +6 dB level), 0.25/0.5 identical, 0.75/1.0 identical and cleaner (−4.7 dB); 1.0 in 12% of library presets |
| +0x24 | Noise one-shot | 0/1 | fixture 21 + render: the sample stops at its end |
| +0x28 | Noise pitch track | 0/1 | fixture 21 + render: Pitch knob reads in semitones, spectrum follows the note |
| +0x2C | Polyphony | (voices − 1) / 31 | fixture 18 (4 voices = 3/31); 8 and 16 dominate the library |
| +0x34 | Filter keytrack | 0/1 | fixture 17 |
| +0x38, +0x3C | Unison range A, B | semitones / 48 | fixture 20 (12 st = 0.25), default 2 st |
| +0x40, +0x44 | Chaos 1, 2 Mono | 0/1 | fixtures 19, 19b + render: no effect on a single voice |
| +0x48 | Chorus mono switch | 0/1 | crafted variant with the chorus on: the L/R LFO phase offset disappears (inter-channel lag 169 → 0 samples, stereo width 0.33 → 0.23, level −0.7 dB); set in 81% of presets that use the chorus vs 17% otherwise. The GUI label was not observed; treated as the chorus running its LFO in phase on both channels |
| +0x50, +0x54 | Chaos 1, 2 S&H | 0/1 | fixtures 19, 19c + render: stepped modulation |
| +0x5C | Reverb Hall (1) / Plate (0) | 0/1 | fixture 14b; the per-effect record byte at `0x3B04` is a copy |

Fields at +0x04 (0/1 in 1.5% of presets, leaning towards noise users),
+0x30 (always 1.0), +0x4C (0/1 in 3%, leaning towards compressor users),
+0x58 (junk in old builds) and +0x60 (0.1 default, 0–0.175, set in 23% of
presets, leaning towards envelope-curve editors) produce no change in any
rendered scenario — plain, velocity, release, chord, noise, Sync warp,
filter, portamento, fast retrigger, and every effect switched on — so they
are taken to be GUI-only state (display zoom, view options) and are not read.

### LFO shapes and switches

There are two layouts.  Which one a file uses is decided by whether the
classic region at `0x0280` holds data or zeros.

**Classic layout** (blobs of 20-34 KB, builds up to about 1.3): each LFO
shape is three arrays of 65 float64 values -- tension, x, y -- stored as
520-byte records.  A block covers four LFOs: arrays 0-3 are tension, 4-7 are
x, 8-11 are y.  LFO 1-4 start at `0x0280`, LFO 5-8 at `0x1B70`.

* x runs 0..1 left to right; the shape ends at the first point that reaches 1.0
  and the rest of the array is padding.
* y runs 0..1 **top to bottom** (screen coordinates), the same orientation
  as Vital's LFO JSON, so the value is copied as is. Serum ties the curve's
  last point to its first, so the default shape (0, 1, 1) plays as a triangle;
  the converter closes the loop the same way. Both facts were settled on
  2026-09-10 by rendering LFO-to-level routings through Serum and fitting
  polarity and loop closure against Vital renders (0.99 correlation); the
  earlier reading (invert, no loop) anti-correlated at −0.44.
* tension is 0..1 with 0.5 meaning a straight segment.

The LFO 1-4 switches live in a 144-byte record at `0x1AE0`:

| offset | contents |
|--------|----------|
| +0x00 | uint8 × 4: point count per LFO |
| +0x04 | float32 × 4: copy of the rate knob |
| +0x14 | uint8 × 4: ANCH |
| +0x18 | uint8 × 4: **Hz mode** (BPM switch off) |
| +0x1C | uint8 × 4: DOT |
| +0x20 | uint8 × 4: TRIP |
| +0x24 | uint8 × 4: mode is not OFF |
| +0x28 | uint8 × 4: mode is ENV (with the previous byte set) |

Mode therefore decodes as OFF (0,0), TRIG (1,0), ENV (1,1).  For LFO 5-8 only
the anchor bytes at `0x33D0` are recognisable; the rest of that record is
uninitialised in most files, so those four LFOs are assumed synced and
free-running and the converter says so when they are used.

**New layout** (172,736-byte blobs, current builds): the classic region is
zero and eight LFO blocks of `0x2D28` bytes start at `0x84D8`:

| offset in block | contents |
|-----------------|----------|
| +0x0000 | one float64, purpose unknown (0 in most files, a stray 0.2–0.3 in a few LFO 1 blocks) |
| +0x0008 | tension, 480 float64, 0.5 = straight |
| +0x0F08 | x, 480 float64 |
| +0x1E08 | y, 480 float64, 0 = top of the display (same as the classic layout; the default shape is `1, 0, 1`) |
| +0x2D08 | six flag bytes in the same order as the classic record: anchor, Hz, dotted, triplet, not-off, env |
| +0x2D10 | int32 point count |
| +0x2D18 | int32 array length (65 or 481), float32 rate copy (unverified; not read by the converter) |

Before 0.5.1 the converter read these arrays from +0x0000 / +0x0F08 /
+0x1E10 (481, 481 and 479 entries), which dropped the first y value and shifted
every tension by one segment: the default shape read as `0, 1, 1` and every
new-layout LFO came out upside down, with the wrong curvature. The three arrays
of 480 doubles plus the 8-byte header end exactly at the flag bytes
(8 + 3·480·8 = 0x2D08).

Blocks 9-12 follow the same layout and are not LFOs (probably the warp
remap graphs).  These flag positions were established with single-change
fixture presets and agree with the plugin's own rate read-out on 145 of 150
library presets.

The standalone `.shp` files in Serum's `LFO Shapes` folder use the same three
arrays (64 float64 each: tension, x, y, then 64 unused) with different units —
x in 0..388, y in 0..240 — followed by a uint32 point count at offset 2048
(`wavetables.read_shp`).

### FX rack order

Ten int32 values at `0x3BE0`, one per effect in enable-parameter order
(distortion, flanger, phaser, chorus, delay, compressor, reverb, EQ, filter,
hyper), each giving the effect's position in the rack.  The default
`1,2,3,4,5,6,7,8,9,0` puts Hyper first, matching Serum's default rack.

### Indexed parameters

Menu parameters are stored as `index / (count − 1)`.  Serum keeps the menu
order across builds, appends new entries at the end and re-bases the stored
value on load, so the index is comparable between builds: filter type has 96
entries (divisor 95; older files use 89 or 88), warp 24 (23), distortion mode
16 (15, older builds with 13 modes: 12), unison stack 9 (8), sub shape 5 (4),
EQ type 3 (2), delay mode 3 (2).  The full lists, read
back from the plugin, are in `tools/serum_display_tables.json` and
`serum2vital/serum_tables.py`.

### Wavetables

Referenced by name (`Analog/Basic Shapes.wav`), resolved against Serum's
`Tables` folder. The files are mono WAVs, normally float32 (the reader also
accepts 16/24/32-bit PCM), with a `clm ` chunk declaring the frame size:

```
<!>2048 01000000 wavetable (www.xferrecords.com)
```

Serum's basic shapes (`Triangle`, `Square`, …) live inside the plugin rather
than on disk, so the converter synthesises those.

---

## Serum 2 — `.SerumPreset`

```
b"XferJson\x00"
uint64   JSON metadata length
bytes    JSON metadata
uint32   decompressed payload size
uint32   payload encoding (2 = zstd)
bytes    zstd frame containing CBOR
```

The CBOR payload is a flat map of module name to module state: `Env0`–`Env3`,
`LFO0`–`LFO9`, `Oscillator0`–`Oscillator4`, `VoiceFilter0`/`1`, `Macro0`–`Macro7`,
`ModSlot0`–`ModSlot63`, `FXRack0`–`FXRack2`, and so on.

Each module has a `plainParams` entry that is either the string `"default"` or
a map containing **only** the parameters that differ from their default — so an
absent parameter means "at Serum's default", and a converter needs its own table
of those defaults. Values are in real units (seconds, Hz, dB, percent), not
normalised, which makes this the easier of the two formats to read.

Modulation slots carry their routing explicitly:

```json
{
  "source": [7, 31],
  "destModuleTypeString": "FXFilter",
  "destModuleID": 1,
  "destModuleParamName": "kParamY",
  "destModuleParamID": 10,
  "plainParams": {"kParamAmount": 100.0}
}
```

`source` is `[source_id, aux_id]`. The same correlation method as for Serum 1
identifies ids 2–5 as Env 1–4, 6–15 as LFO 1–10 (LFO0 matched id 6 in 99% of
presets, LFO1 id 7 in 98%, LFO4 id 10 in 100%) and 25–32 as Macro 1–8. The
rest of the menu was captured with the fixtures `DebugPresets/12 sources.SerumPreset`
and `12b sources extra.SerumPreset` (one known source per matrix row,
labels in `DebugPresets/NOTES.txt`):

| id | source | | id | source |
|----|--------|-|----|--------|
| 1 | Mod Wheel | | 33 | Pitch Bend |
| 16 | Velocity | | 34, 35, 36 | Expr X (Pan), Y (Timbre), Z (Press.) |
| 17 | Note | | 37 | Release Velocity |
| 18 | Aftertouch (channel) | | 38 | Fixed |
| 19 | Poly Aftertouch | | 49, 50, 51, 52 | OSC A, B, C, Sub audio |
| 20 | Noise OSC | | 53, 54 | Filter 1, 2 audio |
| 21, 22 | NoteOn Rand 1, 2 | | 55 | Active Voices |
| 23, 24 | NoteOn Alt, Alt 2 | | 56, 57 | Voice Mod 1, 2 |
| | | | 58 | Voice Index |
| | | | 59 | NoteOn Rand (Discrete) |

The build used has no Chaos entries (rows 4/5 of the fixture hold LFO 9/10).
Ids 39–44 occur in the library (about one routing per ten presets) and are
not in this menu capture; they are reported as unknown. LFO 9–10, Macro 5–8
and the audio-rate/voice sources are identified but dropped because Vital has
no counterpart (`SERUM2_SOURCES` / `SERUM2_UNSUPPORTED_SOURCES` in
`serum2vital/mapping.py`). The synced LFO rate stores `100·n⁴` on a 15-step
knob (`n = k/14`; 4 bar = 3, 1 bar = 5, 1/2 = 6, 1/16 = 9, 1/32 = 10), checked
with the `13 rate` fixtures.

Wavetable oscillators reference their table through `relativePathToWT`, e.g.
`S2 Tables/Digital/FM Piano.wav`, resolved against `Tables/` or
`Serum 2 Presets/Tables/` under the folder given with `--serum-root`.

---

## Known unknowns

What the readers still cannot interpret, as of 2026-09-09. None of it blocks
a conversion; each item is either preserved verbatim, defaulted, or reported
in the conversion notes. `FIXTURE_PRESETS_TASK.md` ("Batch C") lists the
fixtures that would settle the items marked *fixture*.

### Serum 1

| item | status | how to settle |
|------|--------|---------------|
| Global switches block fields +0x04, +0x30, +0x4C, +0x58, +0x60 | not read; none of them changes the rendered audio in any scenario (see the switches-block section), so they are taken to be GUI-only state | *fixture*: only worth it if a GUI control is found whose state is not covered elsewhere; +0x60 is probably a display zoom (its users edit envelope curves) |
| Chorus switch at +0x48: its GUI label | read and reported (its measured effect, an in-phase L/R chorus LFO, has no Vital counterpart; Vital's `chorus_spread` is the chorus *filter* spread, which the earlier mapping had set to 0) | a look at Serum's chorus panel |
| Per-effect output trims `FX * Level` (parameters 289-298) | read, not converted | nothing to settle; a Vital effect has no output trim |
| LFO 5–8 switches in the classic layout | confirmed absent: the record at 0x33D0 holds only the four ANCH bytes, then zeros or heap junk, in every one of the 611 classic-layout presets that route LFO 5–8; those builds did not save the switches, so "synced, free-running" is the only possible reading | nothing to settle |
| `Mast.Tun` parameter (index 80) range | measured at (v − 0.5) × 128 semitones on two points (±0.1 → ±12.8 st); never non-default in the 15k-preset library, so it is not converted statically | a third point with a wider pitch tracker if ever needed |
| Second zlib stream in the chunk (16 KB, identical in every preset) and the uint32 before the length word | preserved verbatim by `tools/craft_fxp.py` | not needed |
| New-layout LFO block +0x0000 (one float64 before the tension array; 0 in most files, 0.2–0.3 in a few LFO 1 blocks) | not read; no audible effect found | nothing to settle unless a shape mismatch points at it |
| Modulation record +0x00 (probably the smoothed amount) and +0x18 (a remapping of the destination index) | not read | not needed |
| Per-effect record bytes other than the reverb Plate/Hall copy | not read (all mirror parameters) | not needed |

### Serum 2

| item | status | how to settle |
|------|--------|---------------|
| Modulation source ids 39–44 (47, 48 also seen) | reported as unknown (about one routing per ten library presets, in factory presets of every 2.0.x version, including Steve Duda's own, so they are current sources that the `12`/`12b` menu capture missed rather than legacy ids). 39 and 41 mostly drive pan, fine tune and cutoff with small amounts; 40 and 42 drive LFO point mod buses and table position | *fixture*: a matrix with every Source menu entry (including any submenus) in order |
| Aux source ids | confirmed to share the source enum by the library: the aux column holds 1 (mod wheel, 232 uses), 16 (velocity), 18 (aftertouch) and 25–32 (macros) almost exclusively | nothing to settle |
| Hosting Serum 2 headlessly | solved (2026-09-10): `tools/serum2_host.py` loads Serum2.vst3 through DawDreamer, injects a `.SerumPreset` and renders. The VST3 state is two `XferJson` containers (processor and edit controller), each a JSON header (`hash` = md5 of the zstd payload) over a CBOR map keyed by module; a `.SerumPreset` is the union of both maps. Serum silently keeps its previous state when a container carries keys the other side owns (the naive "paste the whole preset into `<IComponent>`" that looked like a broken `load_state`), so the host splits the preset by each container's own key set. pedalboard still cannot scan the plugin (`unsupported plugin format or scan failure`); FX parameters are still only exposed as "FX Main Param N" proxies, but the FX rack state is readable from the processor document | nothing to settle |
| Synced delay time steps (`FXDelay.kParamTime` when beat-synced) | measured (2026-09-10, crafted presets rendered at 120 BPM): the stored seconds are quantised at render time, boundaries in `fx_common.DELAY_SYNC_BOUNDS`; offset 1.5 = dotted, 4/3 = triplet of the next longer division | nothing to settle |
| Synced RATE of chorus/flanger/phaser | measured: the knob position steps through Serum 1's 31-entry ladder (`fx_common.FX_RATE_RUNS`), confirmed on the dotted-quarter and quarter-triplet renders | nothing to settle |
| Reverb `kParamDelay` for the non-plate types | measured: a decay control for Hall and Abyss (Hall RT60 3 s at 30, 7 s at 60, runaway by 150), no effect on Vintage; per-type RT60 laws in `fx_common.serum2_reverb_rt60`. `kSpace` renders silence headlessly and is mapped like Hall | nothing to settle (Space would need a GUI render) |
| Module defaults never seen non-default in the corpus (chorus delays, flanger width, delay time) | educated guesses in `S2_FX_DEFAULTS` | a fixture with each module enabled at its defaults tells nothing; they only matter when a preset leaves the knob untouched |
| Modules without a Vital counterpart: `RoutingSlot` (FX buses), `MidiClip`, `Arp`, `ArpClip`, `ClipPlayer`, `VoicePanel`, `PitchQuantizer`, `LFOPointModBus`; the multisample, granular and spectral oscillator engines | dropped, reported | out of scope for a Vital target |

## Vital — `.vital`

Plain UTF-8 JSON, no compression:

```json
{
  "author": "...", "comments": "...",
  "macro1": "...", "macro2": "...", "macro3": "...", "macro4": "...",
  "preset_name": "...", "preset_style": "...",
  "synth_version": "1.5.5",
  "settings": { ... }
}
```

`settings` holds 775 scalar parameters in Vital 1.5.5 plus six structured
entries: `wavetables` (3), `lfos` (8), `modulations` (64), `custom_warps` (3),
`random_values` (3) and `sample`. Vital 1.5.5 saves exactly three
`random_values`; writing a fourth breaks its loader.

Parameter ids, ranges and defaults come straight from Vital's own
`synth_parameters.cpp`; `tools/gen_vital_defaults.py` parses that file and
expands the per-module lists the same way `ValueDetailsLookup`'s constructor
does. The generated key set matches a real 1.5.5 preset exactly, once the
1.0.x-only parameters are removed (`sub_*`, `filter_*_osc<n>_input`) and the
1.5.5-only `osc_<n>_spectral_morph_phase` is added.

Things worth knowing when writing a preset:

* **Oscillator phase is offset by half a cycle from Serum.** With random
  phase off, Serum starts a note reading its frame at `phase × N` and Vital at
  `(phase + 0.5) × N` (measured on both plugins with the same table: Serum's
  180° default puts the saw's discontinuity at the note start, Vital's 0.5
  puts it half a cycle in). The converter writes `(serum_phase + 0.5) mod 1`.
  Serum's sub oscillator has no phase knob and is phase-locked at note-on,
  starting at zero and falling for every shape; that is Vital phase 0.0 with
  random phase 0, which the converter sets (Vital's default would randomise it
  and make the sub's sum with the other oscillators change from note to note).
* **Values are stored post-scaling.** A `quartic` parameter such as
  `env_1_attack` stores `seconds ** (1/4)`; its maximum of 2.37842 is exactly
  `32 ** (1/4)`, so Vital's envelopes top out at 32 seconds.
* **Wavetable keyframes** are base64 of 2048 little-endian float32 time-domain
  samples. `interpolation_style` is 0 none / 1 linear / 2 cubic, and
  `interpolation` selects time (0) or frequency (1) domain morphing.
* **Samples** are base64 of int16 PCM, mono in `samples` and optionally
  `samples_stereo`.
* **LFOs** are `{name, num_points, points: [x0,y0,x1,y1,...], powers, smooth}`
  with **y = 0 at the top** (a curve held at 0 drives a level modulation to
  its maximum, one held at 1 to silence; measured through the plugin) and
  power 0 meaning a straight segment.
* **`settings["sample"]` must exist.** `LoadSave::jsonToState` reads it without
  a guard and then indexes `["length"]`, so a preset without one fails to load.
* **`synth_version` is checked.** A preset whose feature version is newer than
  the running Vital is rejected outright; an older one is put through a
  migration path that expects 1.0.x keys. Write the version you are targeting.

[gist]: https://gist.github.com/0xdevalias/135a18e979ac8e302ebbc700a50a8d74
