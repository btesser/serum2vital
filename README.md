# serum2vital

<p align="center">
  <img src="marketing/serum2vital-launch.png" alt="serum2vital: Serum presets, new life in Vital. Free and open source, Serum 1 + 2 to Vital." width="640">
</p>

Converts Xfer **Serum 1** (`.fxp`) and **Serum 2** (`.SerumPreset`) presets into
**Vital** (`.vital`) presets: wavetables, noise samples, LFO shapes and switches,
envelopes, filters, warp modes, effects and the modulation matrix.

The mapping is measured rather than guessed. Menu orders and knob curves were
read back from the Serum plugin itself, the file formats were verified against
single-change fixture presets, and levels, envelopes and warp depths were
calibrated by rendering the same notes through both synths. Every preset comes
with a list of what was approximated or dropped.

**Hear it first:** [btesser.github.io/serum2vital](https://btesser.github.io/serum2vital/)
plays Serum originals next to their Vital conversions, category by category.

Not affiliated with Xfer Records or Vital Audio. You need your own copies of
the Serum presets and (for the wavetables) Serum's data folder.

## Install

```bash
pip install .            # Serum 1 only needs the standard library
pip install .[serum2]    # adds zstandard + cbor2 for Serum 2 presets
```

Python 3.9 or newer. This installs a `serum2vital` command; `python -m serum2vital`
works from a checkout without installing.

## Usage

Nothing is written unless you pass `--out`, so start with a dry run that only
reports what would be lost. `SERUM` below is Serum's data folder, the one that
holds `Presets/`, `Tables/` and `Noises/` (Serum calls it "Serum Presets"; on
Windows it is usually under `Documents/Xfer`).

```bash
serum2vital "SERUM/Presets" --serum-root "SERUM"
```

Convert everything into an organised pack, with smaller embedded wavetables:

```bash
serum2vital "SERUM/Presets" "SERUM/Serum 2 Presets/Presets" --serum-root "SERUM"     --out "./out/Serum Converted/Presets" --organize --max-frames 16 --report report.json
```

Start with a handful before committing to the whole library:

```bash
serum2vital "SERUM/Presets/Some Pack" --serum-root "SERUM" --out ./out --limit 20 --verbose
```

To use the result in Vital, copy the `Serum Converted` folder into Vital's user
data directory (the `data_directory` in Vital's config; `Documents/Vital` by
default) so it appears as a pack, or point Vital's browser at it.

A full library of about 8,000 presets takes a few minutes and about 3 GB with
`--max-frames 16`.

### Options

| flag | effect |
|------|--------|
| `--out DIR` | write `.vital` files here, mirroring the input folder structure |
| `--serum-root DIR` | Serum data folder holding `Tables/` and `Noises/`; without it oscillators get a placeholder waveform |
| `--organize` | sort output into `INSTRUMENT/TYPE/MODIFIER/` folders instead of mirroring (see below) |
| `--max-frames N` | wavetable keyframes to embed, default 64. `--max-frames 16` shrinks output to roughly a quarter |
| `--max-sample-seconds S` | trim embedded noise samples, default 4 |
| `--no-wavetables`, `--no-samples` | skip embedding audio entirely (small files, generic sound) |
| `--flatten` | write everything into one folder instead of mirroring |
| `--overwrite` | replace existing `.vital` files |
| `--limit N` | only process the first N presets |
| `--report FILE.json` | per-preset record of what converted, what was dropped, and the category |
| `-v` | log every preset |

The run ends with a summary of conversion notes grouped by fidelity class:
`approximation`, `conflict`, `unsupported` and `unknown`.

### `--organize`

Serum libraries are organised by pack, not by sound.  `--organize` classifies
each preset and writes it to `<out>/<INSTRUMENT>/<TYPE>/<MODIFIER>/<name>.vital`
instead of mirroring the input folders:

```
out/
├── BASS/
│   ├── REESE/DARK/Reese 01.vital
│   ├── GROWL/DISTORTED/AU_HM_bass_growl_distorted.vital
│   └── 808/CLEAN/808 Electric [KARRA].vital
├── LEAD/
│   ├── SCREECH/AGGRESSIVE/SC - Elephant.vital
│   └── HARDSTYLE/WIDE/LD - Good Vibs.vital
├── PAD/GENERAL/WET/PD Compass [KARRA].vital
└── KEYS/ORGAN/CLEAN/OR - Leslie Organ.vital
```

- **INSTRUMENT** (`BASS`, `LEAD`, `PAD`, `PLUCK`, `KEYS`, `FX`, `DRUM`, `SEQ`,
  `CHORD`, `VOCAL`, `SYNTH`, `INSTRUMENT`) comes from the preset name's prefix or
  keywords (`BA`/`BS`/`808`/`REESE`…, `LD`/`SCREECH`…), then the Serum bank
  string, then the source folder names, and finally the sound itself (long
  attack → `PAD`, short decay with no sustain → `PLUCK`, …).
- **TYPE** is a sub-type keyword when the name has one (`REESE`, `WOBBLE`,
  `SCREECH`, `SUPERSAW`, `PIANO`, `RISER`, `KICK`, `ARP`, …), otherwise the genre
  the pack folder implies (`DUBSTEP`, `HARDSTYLE`, `TRAP`, `DNB`, `TECHNO`, …),
  otherwise `GENERAL`.
- **MODIFIER** is a descriptive keyword when present (`HARD`, `DIRTY`, `SOFT`,
  `DARK`, `WIDE`, `ANALOG`, `GATED`, …), otherwise derived from the converted
  parameters: heavy distortion or FM/RM warp → `AGGRESSIVE`, wide unison or chorus
  → `WIDE`, low filter cutoff → `DARK`, reverb plus delay → `WET`, else `CLEAN`.

Presets with the same name in one folder get ` (author)` or ` (2)` appended.
The run summary prints a category histogram, and `--report` entries carry a
`"category"` field with the three parts.

## What converts

Every unit curve and menu order below was read back from the Serum 1 plugin
itself (`tools/serum_display_tables.json`); nothing is inferred from knob
positions.  The CLI report groups its notes into `approximation`, `conflict`,
`unsupported` and `unknown`.

**Exact** — the two synths agree on the underlying quantity:

- oscillator A/B → Vital osc 1/2: level, pan, octave/semi/fine, unison voices,
  detune (both quadratic over a 2-semitone range), blend, stereo spread, unison
  warp/WT-pos spread, wavetable position, phase (Vital reads a frame half a
  cycle later than Serum for the same knob value, which is compensated) and
  phase randomisation; the sub is phase-locked at note-on, as in Serum
- Serum's sub oscillator → Vital osc 3 (Sine, RoundRect, Saw, Square, Pulse),
  noise oscillator → Vital's sample source
- envelopes 1–3: Serum's knobs are `t = 32·n⁵` seconds and Vital stores
  `t^(1/4)`; sustain and curve controls; env 1's quadratic amplitude sustain
  matches Vital's squared amplitude envelope
- LFO shapes (point lists with per-segment tension, both file layouts), and the
  LFO switches: Hz mode → Vital *Seconds* with the exact frequency (`100·n⁴` Hz),
  BPM mode → Vital tempo divisions with dotted/triplet, TRIG/ENV/OFF →
  Vital Trigger/Envelope/Sync, rise and delay
- the modulation matrix: sources (envelopes, LFOs, macros, mod wheel,
  velocity, note, aftertouch, pitch bend, release velocity, MPE slide/pressure,
  Chaos 1/2 as Vital random LFOs, note-on random as Vital's per-note random),
  destinations, amounts, and Serum's aux source as a modulation of the
  routing's own amount
- FX rack order (Vital's effect chain order is set to match), wet/dry,
  feedback and cutoff amounts of reverb, delay, chorus, distortion, phaser,
  flanger, compressor and EQ; delay modes and synced divisions
- macro values and names, preset name, author, bank
- the Serum 1 controls that are not VST parameters, read from the preset's
  switch block: Mono/Legato and the polyphony count, portamento Always/Scaled,
  noise one-shot and pitch tracking, filter keytrack, unison detune range and
  tuning mode (Linear/Exp/Inv → Vital's detune power), Chaos Mono (Vital
  random-LFO sync) and S&H (Vital's S&H style), the A4 tuning reference,
  oversampling (1x/2x/4x) and the chorus mono switch

**Approximated** — reported per preset:

- **Filter type.** All 96 Serum types are catalogued (`serum2vital/filter_map.py`):
  MG → Ladder, SVF types → Analog with blend/style, dual SVFs → Vital filters
  1+2 in series with VAR as the second cutoff, morphing types → blend driven by
  VAR, comb/flanger/phaser types → Comb and Phaser models, formants → Formant,
  EQ types → shelf/pass approximations. Ring Mod and SampHold have no
  counterpart and are reported.
- **Warp.** Sync, Bend, PWM, Asym, Quantize, FM/AM/RM from the other
  oscillator, FM from noise/sub all map onto Vital's phase distortion; AM is
  rendered as RM. Flip, Mirror and Remap are reported.
- **Hyper/Dimension** (on in half the library) → Vital's chorus: voices, rate,
  detune, mix and Dimension size/mix. When Serum's own chorus is also on, the
  Hyper goes to the flanger and the conflict is reported. Retrigger is not
  reproducible.
- **Distortion** modes map onto Vital's six types; reverb and compressor are
  different algorithms and are matched by their main controls.
- **Serum 2** effect racks are converted module by module where Vital has the
  effect; buses, convolution, Bode shifting and splitters are reported.

**Not converted** — dropped and reported:

- Serum 2 granular/spectral/multisample engines, arpeggiator, clips, MPE
  per-note settings, macros 5–8 and LFOs 9–10
- the LFO 5–8 sync switches in presets from old Serum builds (assumed synced
  and free-running; only reported when those LFOs are used)
- Serum 1's Note-on Alt, Noise-osc and Fixed modulation sources; Serum 2's
  audio-rate (oscillator/filter) and voice-bookkeeping sources
- the reverb's Plate mode (Vital's reverb has no plate); reported

What the readers still cannot interpret in either file format, and the fixture
presets that would settle each item, are listed in
[docs/FORMATS.md](docs/FORMATS.md#known-unknowns) and
[docs/FIXTURE_PRESETS_TASK.md](docs/FIXTURE_PRESETS_TASK.md).

A converted preset is a structurally faithful starting point, not a bit-exact
clone. Levels, envelope curves, warp depths and filter drive were calibrated
by rendering both synths (`tools/calibrate.py`, `tools/ab_render.py`); on a
random batch most presets land within 3 dB of Serum, heavy-drive and
fast-decay patches drift most, so expect to touch up drive and decay on
anything you care about.

## Checking a conversion by ear or by numbers

`tools/` holds headless hosts for both synths so that mappings can be measured
instead of argued about:

* `tools/vital_host.py preset.vital --render out.wav` loads Vital (VST3, via
  pedalboard), injects a preset, reads the parameters back and renders a note.
* `tools/serum_host.py preset.fxp --render out.wav` does the same for Serum
  (VST2, via DawDreamer) and can print any parameter's display text.
* `tools/serum2_host.py preset.SerumPreset --render out.wav` does the same
  for Serum 2 (VST3, via DawDreamer); it rebuilds the plugin's two `XferJson`
  state containers from the preset, which is the part a plain state load
  gets wrong.
* `tools/ab_render.py preset.fxp preset.vital` renders the same note through
  both and prints level, spectral centroid and stereo correlation.
* `tools/listen.py "out/.../BASS/REESE" --out out/listen/reese` renders every
  converted preset in a folder next to its Serum original (a held note, a
  short riff, a held note again) and writes an `index.html` with side-by-side
  players, so a whole category can be auditioned in one sitting.
  `tools/publish_listen.py out/listen/reese --site site` turns those folders
  into the MP3 + HTML site served from the `gh-pages` branch.
* `tools/calibrate.py` runs the parameter sweeps the unit curves were fitted from.
* `tools/fx_fixtures.py craft|serum|vital|compare` builds single-purpose effect
  presets for both Serum generations, renders them through Serum and through the
  converter into Vital, and compares echo times, tail decay, octave bands and
  stereo width; the effect laws in `serum2vital/fx_common.py` come from it.
* `tools/verify.py out/` checks the structural invariants Vital's loader needs.

Install them with `pip install .[hosts]` and set `SERUM_VST2`, `VITAL_VST3` and
`SERUM_ROOT` if your plugins and library are not in the default locations.

## Layout

```
serum2vital/
  serum1.py          .fxp reader (container, parameters, mod matrix, LFO shapes)
  serum2.py          .SerumPreset reader (XferJson + zstd + CBOR)
  serum_params.py    Serum's 299-parameter name/range table
  serum_tables.py    generated: Serum menu lists, rate tables and unit curves
  filter_map.py      the 96-entry filter catalog -> Vital filter targets
  fx_common.py       Hyper->chorus, distortion table, effect-order encoder
  serum2_fx.py       Serum 2 FX rack conversion
  mapping.py         Serum -> Vital parameter mapping, with fidelity notes
  wavetables.py      Serum wavetable/sample/.shp -> Vital JSON fragments
  vital_defaults.py  generated Vital parameter table (do not edit)
  writer.py          assembles the .vital document
  convert.py         CLI
tools/
  gen_vital_defaults.py   regenerates vital_defaults.py from Vital's source
  gen_serum_tables.py     regenerates serum_tables.py from serum_display_tables.json
  serum_display_tables.json  what the Serum plugin displays, captured headlessly
  serum_host.py / serum2_host.py / vital_host.py / ab_render.py   headless hosts for validation
docs/
  FORMATS.md         how all three formats are laid out, and how that was verified
  FINDINGS_AND_PLAN.md   the investigation log: what was measured and why
  FIXTURE_PRESETS_TASK.md   how to save fixture presets that pin down non-parameter state
  serum2_fx_survey.md    what the Serum 2 effect racks store
tests/                   fixtures under DebugPresets/ plus unit tests (pytest)
```

`vital_defaults.py` is generated from Vital's own `synth_parameters.cpp`:

```bash
curl -o tools/synth_parameters.cpp https://raw.githubusercontent.com/mtytel/vital/main/src/common/synth_parameters.cpp
python tools/gen_vital_defaults.py tools/synth_parameters.cpp serum2vital/vital_defaults.py
```

## Contributing and license

See `CONTRIBUTING.md`. The project is licensed under the GPL-3.0-or-later
(`LICENSE`): the Vital parameter table it ships and regenerates from is GPL-3.0
code from the Vital repository.

## Credits

Serum's `.fxp` parameter list comes from
[0xdevalias' reverse-engineering notes](https://gist.github.com/0xdevalias/135a18e979ac8e302ebbc700a50a8d74);
the Serum 2 container layout matches
[serum-preset-packager](https://github.com/KennethWussmann/serum-preset-packager).
Everything else in `docs/FORMATS.md` was worked out against a large preset
library and the Serum plugin's own read-outs (see `docs/FINDINGS_AND_PLAN.md`
for the investigation). Vital's parameter table is taken from
[mtytel/vital](https://github.com/mtytel/vital) (GPLv3). Headless hosting uses
[DawDreamer](https://github.com/DBraun/DawDreamer) and
[pedalboard](https://github.com/spotify/pedalboard).
