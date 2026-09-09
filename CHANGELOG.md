# Changelog

## Unreleased

* Listening site: `tools/publish_listen.py` encodes `tools/listen.py` output
  to MP3 and builds the static pages served from the `gh-pages` branch at
  https://btesser.github.io/serum2vital/ (Reese sets published first).

## 0.4.0 (2026-09-09)

* Oscillator phase now matches Serum. Serum reads a frame from `phase × N`
  and Vital from `(phase + 0.5) × N`, so converted oscillators started half a
  cycle off; the sub oscillator, which Serum phase-locks at note-on, was left
  at Vital's random phase and its sum with the other oscillators changed from
  note to note (audible as phasing on bass patches). Both Serum 1 and Serum 2
  paths shift the phase, lock the sub, and Serum 2's LFO phase is mapped.
* Serum 2: sources whose level knob is at zero but which are sent to an FX
  bus (94 oscillators in the factory library, e.g. "BA - The Even Odds") now
  use the send level instead of converting silent; the routing matrix's
  per-source destination (filter / effects / master / none) is applied.
* CLI: the end-of-run summary no longer aborts on a preset name or note that
  the console encoding cannot represent (which also lost the JSON report).
* `tools/listen.py`: renders a folder of converted presets next to their
  Serum originals (matched by the preset's internal name) with a short
  phrase and writes an HTML player for A/B listening.

## 0.3.0 (2026-09-09)

* README: project artwork.
* Serum 1: three more switch-block fields identified by rendering crafted
  presets through the plugin and now converted: the A4 tuning reference
  (430–450 Hz → Vital global fine tune), oversampling (1x/2x/4x → Vital's
  oversampling setting) and the chorus mono switch (→ `chorus_spread` 0).
  The five remaining fields change nothing audible and are documented as
  GUI-only; the LFO 5–8 switches of pre-1.3 presets were shown never to have
  been saved. Serum 2 aux ids confirmed from the library; ids 39–48 and the
  FX unit laws remain fixture-only because no headless host on this machine
  can push state into Serum2.vst3 (`docs/FORMATS.md`, "Known unknowns").

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
