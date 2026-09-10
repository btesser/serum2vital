# Fixture presets: single-change presets saved from Serum

## Goal

The converter learns where Serum stores settings that are not automatable
parameters (LFO mode/BPM/dotted/triplet switches, modulation source ids, FX
rack order, ...) by diffing small "fixture" presets, each differing from the
Init preset by exactly one setting. This document is the recipe for making
them, so anyone with Serum installed can reproduce or extend the set.

Two batches:

* **Batch A: Serum 1** (the original Serum plugin, `.fxp` files).
* **Batch B: Serum 2** (`.SerumPreset` files).

Any host or DAW that can load the plugin works; nothing is recorded, only
presets are saved from the plugin's own GUI. Saving from a current Serum 1
build produces the 172,736-byte "new" preset layout described in
`FORMATS.md`.

## Output locations (relative to the repository root)

* Serum 1 files: `DebugPresets/serum1/`
* Serum 2 files: `DebugPresets/` (files `1.SerumPreset` ... `11.SerumPreset`
  already exist there; do not overwrite them)

File names below are exact; the tests look them up by name.

## What already exists

`DebugPresets/serum1/` (Serum 1, all in the new layout):

| file | change from Init | test |
|---|---|---|
| `00 init.fxp` | none | `tests/test_serum1_fixtures.py` (init flags, default rack order) |
| `01 lfo1 bpm off.fxp` | LFO 1 BPM off (6.2 Hz) | yes (Hz mode, frequency) |
| `02 lfo1 env.fxp` | LFO 1 mode ENV | yes |
| `03 lfo1 off.fxp` | LFO 1 mode OFF | not tested: Init already has mode OFF, so this equals `00 init` |
| `03b lfo1 trig.fxp` | LFO 1 mode TRIG (added to cover the non-default value) | yes |
| `04 lfo1 trip.fxp` | LFO 1 TRIP on | yes |
| `05 lfo1 dot.fxp` | LFO 1 DOT on | yes |
| `06 lfo1 anch.fxp` | LFO 1 ANCH on | not tested: Init already has ANCH on, so this equals `00 init` |
| `06b lfo1 anch off.fxp` | LFO 1 ANCH off (added to cover the non-default value) | yes |
| `07 lfo1 rate 1-16.fxp` | LFO 1 RATE at 1/16 | yes (rate step table, `lfo_1_tempo`) |
| `08 lfo1 shape.fxp` | three points added to the LFO 1 graph (by double-click) | yes (481-point array reading) |
| `11 sources.fxp` | matrix rows 1-16 with the sources listed below | yes (source ids 1, 13, 14, 16-18, 20-23, 28-33) |
| `11b sources extra.fxp` | rows 1-2: channel Aftertouch, Noise OSC | yes (source ids 15, 19) |
| `12 aux.fxp` | LFO 1 -> A Fine with Mod Wheel as aux source | yes (aux id) |
| `13 fx order.fxp` | Reverb enabled and dragged to the rack top | yes (rack order block) |
| `14 reverb hall.fxp` | Reverb enabled, Hall (already the default) | yes (Plate/Hall byte reads Hall) |
| `15 delay pingpong.fxp` | Delay enabled, Ping-Pong (LINK was already off) | yes (parameters) |
| `16 hyper.fxp` | Hyper on, unison 7, retrig, Dimension mix 50% | yes (parameters) |
| `17 filter keytrack.fxp` | Filter on, keytrack on | yes (switch block +0x34) |
| `18 mono legato.fxp` | polyphony 4, Mono, Legato | yes (switch block +0x10/+0x14/+0x2C) |
| `19 chaos sh mono.fxp` | Chaos 1 BPM sync, Mono, S&H | yes (switch block +0x40/+0x50, told apart by rendering) |
| `20 unison range super.fxp` | OSC A range 12, tuning Super, stack 12+7(1x) | yes (switch block +0x08/+0x38) |
| `21 noise.fxp` | Noise on, one-shot, pitch track | yes (switch block +0x24/+0x28, told apart by rendering) |
| `22 dist mode.fxp` | Distortion on, Tape Sat. | yes (parameters) |
| `23 filter type.fxp` | Filter on, Scream BP | yes (parameters) |

Fixtures `09`/`10` (LFO 5) were skipped because the LFO 5-8 tab could not be
found in the build used. Fixtures `11b` and `12`-`23` were captured on
2026-09-09; what they revealed is written up in `FORMATS.md` ("Global
switches block") and the reader exposes it as `Serum1Patch.settings`.

Additional fixtures captured from fresh Init through the Serum 1 GUI on
2026-09-09, with isolated-switch assertions in `tests/test_serum1_fixtures.py`:

* `14b reverb plate.fxp`: Reverb enabled, switched to **Plate**.
* `19b chaos2 mono.fxp` and `19c chaos2 sh.fxp`: Chaos 2 Mono only / S&H only;
  BPM Sync remains off. These confirm the Chaos 2 switch identities.
* `24 porta always.fxp` and `25 porta scaled.fxp`: portamento **Always** only /
  **Scaled** only. These confirm the previously inferred switch identities.

All five decode as requested with no unrelated parameter or global-setting
changes. This follow-up batch is complete.

`DebugPresets/` (Serum 2), covered by `tests/test_serum2_fixtures.py`:

| file | change from Init |
|---|---|
| `1.SerumPreset` | none |
| `2.SerumPreset` | LFO 1 BPM off (Hz mode) |
| `3.SerumPreset` | LFO 1 mode Envelope |
| `4 - lfo1 free.SerumPreset` | LFO 1 mode Free (off) |
| `5.SerumPreset` | LFO 1 triplet |
| `6.SerumPreset` | LFO 1 dotted |
| `7 - anchor off.SerumPreset` | LFO 1 anchor off |
| `8.SerumPreset` | LFO 1 synced rate 1/16 |
| `9.SerumPreset` | LFO 1 custom shape (5 points) |
| `10.SerumPreset` | LFO 5 BPM off |
| `11.SerumPreset` | LFO 5 mode Envelope |

The Serum 2 `12`/`13` fixtures below were captured on 2026-09-09, including
`12b sources extra`. This build has no Chaos source entries: rows 4/5 of
`12 sources` use LFO 9/10 as documented substitutes. See `DebugPresets/NOTES.txt`
for exact source labels, IDs, and deviations.

`DebugPresets/NOTES.txt` is the log kept while the existing fixtures were
saved; it records the deviations noted above.

## Rules that apply to every preset

1. **Always start from Init.** In Serum 1, click the preset name at the top and
   choose *Init Preset* (or use the menu next to the preset name). In Serum 2,
   use the preset browser's *Init* entry. Do this before every preset, so that
   each file contains exactly one change relative to the base.
2. Change **only** what the step says. Do not touch anything else, do not
   audition with the mouse on knobs, do not resize the window.
3. Save with the plugin's own save function (Serum 1: the disk/save icon or
   *Save Preset As...* in the preset menu; Serum 2: *Save As...* in the preset
   browser). In the file dialog, navigate to the output folder and type the
   exact file name.
4. If a control named below cannot be found, save the preset anyway with the
   closest match and record what was actually done in
   `DebugPresets/NOTES.txt` (one line per preset).
5. Note that Serum 1's Init preset already has LFO mode OFF and ANCH on, so a
   fixture that "turns those on" is identical to Init; add a fixture for the
   opposite value instead (as `03b` and `06b` do).

## Serum 1 UI orientation

* Top tabs: **OSC**, **MATRIX**, **FX**, **GLOBAL**.
* The OSC tab holds OSC A/B, SUB, NOISE, FILTER, the envelopes and the LFO
  panel (LFO 1-4 tabs; LFO 5-8 appear via the arrows/tabs next to them in
  builds that expose them).
* LFO panel controls (left to right, small buttons under the graph): folder
  (presets), **GRID** number box, **MODE** (cycles TRIG, ENV, OFF when
  clicked), **BPM** button, **ANCH** button, **TRIP** and **DOT** buttons,
  then the **RATE**, **RISE**, **DELAY**, **SMOOTH** knobs.
* MATRIX tab: 16 rows of Source / Curve / Amount / Destination / Mod Src
  (aux) / Mod Type / Mod Amt. Click a Source cell for a dropdown menu.
* FX tab: the rack on the left lists the ten effects; each has an enable
  button on its left; drag an effect's name to reorder.
* GLOBAL tab: unison settings for OSC A/B (Range, Width, Warp, WT Pos, Stack,
  Mode), Chaos 1/2 (Rate, BPM Sync, Mono, S&H), voicing (Mono/Legato/Poly).

## Batch A: Serum 1 presets (save as `.fxp` in `DebugPresets/serum1/`)

| File name | What to change from Init |
|---|---|
| `00 init.fxp` | Nothing. Just save Init. |
| `01 lfo1 bpm off.fxp` | LFO 1: click **BPM** so it is off. |
| `02 lfo1 env.fxp` | LFO 1: click **MODE** until it reads **ENV**. |
| `03 lfo1 off.fxp` | LFO 1: click **MODE** until it reads **OFF**. |
| `03b lfo1 trig.fxp` | LFO 1: click **MODE** until it reads **TRIG**. |
| `04 lfo1 trip.fxp` | LFO 1: turn **TRIP** on (BPM stays on). |
| `05 lfo1 dot.fxp` | LFO 1: turn **DOT** on. |
| `06 lfo1 anch.fxp` | LFO 1: turn **ANCH** on. |
| `06b lfo1 anch off.fxp` | LFO 1: turn **ANCH** off. |
| `07 lfo1 rate 1-16.fxp` | LFO 1: turn the **RATE** knob until the readout shows **1/16**. |
| `08 lfo1 shape.fxp` | LFO 1: add three points to the graph at different heights (any positions; double-click if a single click does not insert a point). |
| `09 lfo5 bpm off.fxp` | Select **LFO 5** (arrow/tab next to LFO 4), click **BPM** off. |
| `10 lfo5 env.fxp` | LFO 5: click **MODE** until it reads **ENV**. |
| `11 sources.fxp` | MATRIX tab: fill rows 1-16. For every row set **Destination = A Vol** (under OSC A in the destination menu) and drag **Amount** to roughly +50. Sources, in row order: 1 Velocity, 2 Note, 3 Poly Aftertouch (use "Aftertouch" if only one exists), 4 Chaos 1, 5 Chaos 2, 6 NoteOn Rand 1, 7 NoteOn Rand 2, 8 NoteOn Alt, 9 NoteOn Alt 2, 10 MPE X, 11 MPE Y, 12 MPE Z, 13 Rel. Velo, 14 Fixed, 15 Mod Wheel, 16 Pitch Bend. Record the exact menu labels used in NOTES.txt. |
| `11b sources extra.fxp` | Only if the Source menu contains entries not used above (for example a channel *Aftertouch* separate from Poly, or *Noise OSC*): row 1 = first extra, row 2 = second extra, destination A Vol, amount +50. Note the labels. |
| `12 aux.fxp` | MATRIX row 1: Source **LFO 1**, Destination **A Fine**, Amount +50, and set the **Mod Src** (aux) column of that row to **Mod Wheel**. |
| `13 fx order.fxp` | FX tab: enable **Reverb**, then drag Reverb to the **top** of the rack. |
| `14 reverb hall.fxp` | FX tab: enable **Reverb**, switch its **Plate/Hall** selector to **Hall**. |
| `15 delay pingpong.fxp` | FX tab: enable **Delay**, turn **LINK** off, set mode to **Ping-Pong**. |
| `16 hyper.fxp` | FX tab: enable **Hyper/Dimension**, set **UNISON** to 7, turn **RETRIG** on, set Dimension **MIX** to 50%. |
| `17 filter keytrack.fxp` | OSC tab: enable the **FILTER** module (its power button), then click the small keyboard icon next to the cutoff so keytracking is on. |
| `18 mono legato.fxp` | GLOBAL tab (or the voicing controls at the top of OSC tab): set voice mode to **Mono**, turn **Legato** on, set polyphony/voices to **4**. |
| `19 chaos sh mono.fxp` | GLOBAL tab, Chaos 1: turn **BPM Sync** on, **Mono** on, **S&H** on. |
| `20 unison range super.fxp` | GLOBAL tab, OSC A unison: **Range** 12, **Mode** Super, **Stack** "12+7(1x)". |
| `21 noise.fxp` | OSC tab: enable the **NOISE** oscillator, turn on its one-shot button (the arrow/loop icon) and its pitch-tracking button (keyboard icon). |
| `22 dist mode.fxp` | FX tab: enable **Distortion**, set its **MODE** menu to **Tape Sat.** (last entry). |
| `23 filter type.fxp` | OSC tab: enable **FILTER**, choose type **Scream BP** (last entry in the filter menu). |

## Batch B: Serum 2 presets (save in `DebugPresets/`)

| File name | What to change from Init |
|---|---|
| `12 sources.SerumPreset` | Matrix: rows 1-16, destination **Osc A Level/Volume**, amount +50, sources in this order: Velocity, Note, Poly Aftertouch (or Aftertouch), Chaos 1, Chaos 2, NoteOn Rand 1, NoteOn Rand 2, NoteOn Alt, NoteOn Alt 2, MPE X, MPE Y, MPE Z, Rel. Velo, Fixed, Mod Wheel, Pitch Bend. Record the exact labels in NOTES.txt. |
| `12b sources extra.SerumPreset` | Any further source entries Serum 2 offers that were not used above, one per row from row 1, destination Osc A Level. Note the labels. |
| `13 rate 4bar.SerumPreset` | LFO 1 synced, RATE readout **4 bar**. |
| `13 rate 1bar.SerumPreset` | LFO 1 synced, RATE readout **1 bar** (or **bar**). |
| `13 rate 1-2.SerumPreset` | LFO 1 synced, RATE readout **1/2**. |
| `13 rate 1-32.SerumPreset` | LFO 1 synced, RATE readout **1/32**. |

## Batch C: fixtures still wanted (as of 2026-09-09)

Everything in batches A and B exists. These would settle the remaining items
in `FORMATS.md` ("Known unknowns"); all are single changes from Init unless
stated. Serum 2 files go in `DebugPresets/`, Serum 1 files in
`DebugPresets/serum1/`.

| File name | What to change from Init | Settles |
|---|---|---|
| `14 sources rest.SerumPreset` | Matrix rows 1-n: every Source menu entry **not** used in `12 sources` / `12b sources extra` (the labels are listed in `NOTES.txt`), in menu order, destination Osc A Level, amount +50. Record the labels. | source ids 39-44 |
| `15 aux.SerumPreset` | Matrix row 1: Source **LFO 1**, Destination Osc A Level, amount +50, aux/"Mod Src" column set to **Mod Wheel**. | Serum 2 aux id encoding |
| `16 delay 1-64.SerumPreset` … `16 delay 4bar.SerumPreset` | Delay enabled, beat sync on, time set to **1/64**, **1/16**, **1/4**, **1 bar**, **4 bar** (one file each; keep L/R linked). | synced delay-time law |
| `17 chorus rate 1-32.SerumPreset`, `17 chorus rate 8bar.SerumPreset` | Chorus enabled, rate synced, RATE at **1/32** and at **8 bar**. | synced FX rate law |
| `18 reverb hall decay.SerumPreset` | Reverb enabled, type **Hall**, DECAY at maximum, PRE-DLY at 100 ms (or another pair of values you note). | whether `kParamDelay` is decay or pre-delay |
| `26 chorus switch.fxp` (Serum 1) | FX tab: enable **Chorus** and toggle the one button on its panel that is not BPM; write down its label. | the GUI name of switch-block field +0x48 (its effect, no L/R LFO offset, is already measured and mapped) |

Not needed any more: the A4 reference (+0x00) and oversampling (+0x20) were
identified by rendering crafted presets, the LFO 5-8 switches of old builds
were shown never to have been saved, and the aux id encoding is settled by the
library. The remaining Serum 1 block fields (+0x04, +0x30, +0x4C, +0x58,
+0x60) change nothing audible; no fixture is requested for them.

The Serum 2 rows above are no longer the only route to those laws: since
2026-09-10 `tools/serum2_host.py` loads a `.SerumPreset` into Serum2.vst3
headlessly (DawDreamer) and renders it, so a crafted preset (edit the CBOR
document, rebuild the container) can replace a GUI-saved fixture for the
delay-time, FX-rate and reverb questions. Source ids 39-44 still need the
menu capture, since the id-to-label mapping is not observable from audio.

## After saving new fixtures

* Add a line per file to `DebugPresets/NOTES.txt` describing any deviation.
* Run `python -m pytest tests/test_serum1_fixtures.py tests/test_serum2_fixtures.py`;
  the existing tests must still pass, and a new fixture should get its own
  assertion there once the reader understands it.
