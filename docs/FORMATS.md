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
| `0x84D8` | LFO 1–8 blocks, 0x2D28 bytes each — new layout only |
| varies | modulation slots 17–32 |

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
record is self-identifying — bytes `80 80 <slot> FF` sit at +0x20 — so the
reader scans for that marker instead of trusting a fixed offset.

| offset | type | meaning |
|--------|------|---------|
| +0x00 | float32 | current/smoothed amount (unverified; not read by the converter) |
| +0x04 | float32 | amount, bipolar −1..1 |
| +0x08 | float32 | output range (1.0 = 100%) |
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
| 15 | Aftertouch (channel) | probable: not in the fixture; Serum's menu lists it as a remaining source |
| 16 | Poly Aftertouch | fixture |
| 17, 18 | Chaos 1, Chaos 2 | fixture |
| 19 | Noise OSC | probable: not in the fixture |
| 20, 21 | NoteOn Rand 1, NoteOn Rand 2 | fixture |
| 22, 23 | NoteOn Alt, NoteOn Alt 2 | fixture |
| 24–27 | Macro 1–4 | corpus: correlates with each macro's own value being non-zero |
| 28 | Pitch Bend | fixture |
| 29–31 | MPE X, Y, Z | fixture |
| 32 | Release Velocity | fixture |
| 33 | Fixed | fixture |

Id 0 means the slot is unused. Ids 15 and 19 are the two menu entries the
fixture does not cover, so those two names are inferred from Serum's source
menu rather than measured.

### LFO shapes and switches

There are two layouts.  Which one a file uses is decided by whether the
classic region at `0x0280` holds data or zeros.

**Classic layout** (blobs of 20-34 KB, builds up to about 1.3): each LFO
shape is three arrays of 65 float64 values -- tension, x, y -- stored as
520-byte records.  A block covers four LFOs: arrays 0-3 are tension, 4-7 are
x, 8-11 are y.  LFO 1-4 start at `0x0280`, LFO 5-8 at `0x1B70`.

* x runs 0..1 left to right; the shape ends at the first point that reaches 1.0
  and the rest of the array is padding.
* y runs 0..1 **top to bottom** (screen coordinates), so Vital's y is `1 − y`.
  The last point's own y is used (the default shape is a half-saw: top, bottom
  at 50%, then flat), there is no wrap to the first point.
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
| +0x0000 | tension, 481 float64 |
| +0x0F08 | x, 481 float64 |
| +0x1E10 | y, 479 float64 |
| +0x2D08 | six flag bytes in the same order as the classic record: anchor, Hz, dotted, triplet, not-off, env |
| +0x2D10 | int32 point count |
| +0x2D18 | int32 array length (65 or 481), float32 rate copy (unverified; not read by the converter) |

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
presets, LFO1 id 7 in 98%, LFO4 id 10 in 100%) and 25–32 as Macro 1–8. Ids 1
(mod wheel), 16 (velocity), 17 (note), 18 (aftertouch), 21 and 23 (note-on
random 1/2) follow from what they modulate in the corpus (`SERUM2_SOURCES` in
`serum2vital/mapping.py`). Ids 19, 20, 22 and 24 remain unidentified and are
reported rather than guessed; LFO 9–10 and Macro 5–8 are identified but
dropped because Vital has only eight LFOs and four macros.

Wavetable oscillators reference their table through `relativePathToWT`, e.g.
`S2 Tables/Digital/FM Piano.wav`, resolved against `Tables/` or
`Serum 2 Presets/Tables/` under the folder given with `--serum-root`.

---

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

* **Values are stored post-scaling.** A `quartic` parameter such as
  `env_1_attack` stores `seconds ** (1/4)`; its maximum of 2.37842 is exactly
  `32 ** (1/4)`, so Vital's envelopes top out at 32 seconds.
* **Wavetable keyframes** are base64 of 2048 little-endian float32 time-domain
  samples. `interpolation_style` is 0 none / 1 linear / 2 cubic, and
  `interpolation` selects time (0) or frequency (1) domain morphing.
* **Samples** are base64 of int16 PCM, mono in `samples` and optionally
  `samples_stereo`.
* **LFOs** are `{name, num_points, points: [x0,y0,x1,y1,...], powers, smooth}`
  with y = 1 at the top and power 0 meaning a straight segment.
* **`settings["sample"]` must exist.** `LoadSave::jsonToState` reads it without
  a guard and then indexes `["length"]`, so a preset without one fails to load.
* **`synth_version` is checked.** A preset whose feature version is newer than
  the running Vital is rejected outright; an older one is put through a
  migration path that expects 1.0.x keys. Write the version you are targeting.

[gist]: https://gist.github.com/0xdevalias/135a18e979ac8e302ebbc700a50a8d74
