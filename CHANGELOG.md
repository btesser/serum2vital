# Changelog

## 0.2.0 (2026-09-09)

* Serum 1: the non-automatable switches are now read from the global switches
  block that follows the parameter array (located by content, since it moves
  between builds): voicing (mono, legato, polyphony), portamento Always/Scaled,
  noise one-shot and pitch tracking, filter keytrack, unison detune range and
  tuning mode, Chaos Mono/S&H and the reverb Plate/Hall switch. Every field
  is pinned by a single-change fixture preset (`DebugPresets/serum1`, 27 files)
  and the noise/chaos pairs were told apart by rendering crafted variants
  through the plugin. They drive Vital's polyphony/legato, portamento
  switches, sample loop/keytrack, filter keytrack, detune range/power and
  random-LFO style/sync.
* Documentation: `docs/FORMATS.md` gains the switch-block layout, the chunk
  structure and a "Known unknowns" section; `docs/FIXTURE_PRESETS_TASK.md`
  lists the fixtures that would settle each remaining item (Batch C).
* Serum 1 unison spacing: Serum's Linear tuning is now linear in Vital (detune
  power 0 instead of Vital's default 1.5, which matches Serum's Exp).
* Serum 2: modulation source ids completed from the new fixtures (poly
  aftertouch, noise, NoteOn Rand 2 / Alt 2, pitch bend, MPE, release velocity,
  fixed); audio-rate and voice sources are dropped with a named note instead
  of "unknown", and sources without a Vital counterpart no longer produce
  routings with an empty source.
* `tools/craft_fxp.py`: writes edited `.fxp` copies that Serum accepts (the
  chunk is two zlib streams plus a length word; see `docs/FORMATS.md`).

## 0.1.0 (2026-09-08)

First public release.

* Serum 1 `.fxp` and Serum 2 `.SerumPreset` readers, including both Serum 1
  LFO layouts, the LFO switch flags (Hz/BPM, dotted, triplet, TRIG/ENV/OFF),
  the FX rack order block and the full modulation-source table.
* Menu lists and unit curves measured from the Serum plugin
  (`tools/serum_display_tables.json`), with a 96-entry filter catalog, 24 warp
  modes, 16 distortion modes, unison stacks and sub shapes mapped onto Vital.
* Modulation matrix conversion with velocity, note, wheel, aftertouch, pitch
  bend, chaos (Vital random LFOs), note-on random and aux sources.
* Hyper/Dimension approximated with Vital's chorus, effect chain order
  preserved, Serum 2 FX racks converted module by module.
* Level, envelope, warp and filter-drive calibration from rendered A/B
  comparisons; headless Serum and Vital hosts and an A/B renderer under
  `tools/`.
* `--organize` writes presets into an `INSTRUMENT/TYPE/MODIFIER` tree.
