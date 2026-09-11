# Changelog

## 0.6.1 (2026-09-11)

* Serum 1 classic layout: the LFO 5–8 switches (ANCH, BPM off, DOT, TRIP,
  TRIG/ENV mode) are now read from their record at `0x6DB8`, a second copy of
  the LFO 1–4 record. It was found by re-saving 319 classic presets through
  the current Serum build and correlating the plugin's flags with the old
  bytes, and confirmed with crafted single-flag fixtures read back through
  the plugin (`tools/lfo58_fixtures.py`; the reader agrees with the plugin on
  all 319 × 8 LFOs). Before this the reader took the junk after `0x33D0` for
  the record and treated every LFO 5–8 as synced and free-running, which
  mis-set 141 presets (BPM-off, envelope and trigger modes lost). Blobs from
  builds before LFO 5–8 existed (under 28 KB) still get Serum's defaults and
  the note now says so instead of "could not be read".
  Checked two ways: a crafted Init preset with LFO 1 driving oscillator level
  at 1 Hz renders within 0.2 dB per 100 ms of Serum in Vital for TRIG, ENV
  and free-running modes (so the mode mapping itself is right), and the 126
  corrected library presets rendered as a listening set move both ways on the
  distance metric (18 closer, 25 further, 83 unchanged; median 12.15 → 12.40,
  spectral 8.34 → 8.19 dB), with the one-shot ENV drums and screeches gaining
  the most (DR Snare 1 15.5 → 8.5, SY Screech 1 15.2 → 10.6) and the losses on
  heavily compressed hardstyle presets where the corrected LFO now drives the
  multiband compressor and distortion mix through laws that were already
  approximate.

## 0.6.0 (2026-09-10)

* Effect fixtures. `tools/fx_fixtures.py` crafts 477 single-purpose presets
  (Serum 1 from `00 init.fxp` via `tools/craft_fxp.py`, Serum 2 from
  `1.SerumPreset` by editing its CBOR document; files under
  `DebugPresets/crafted/`), renders them through both Serums and through the
  converter into Vital, and compares echo times, tail decay, octave bands,
  crest factor and stereo width. Every effect law below comes from it, with
  Vital's own effect source read alongside (`serum2vital/fx_common.py`,
  `docs/FINDINGS_AND_PLAN.md` third pass, `tests/test_fx_laws.py`).
  Over the 645 listening-set presets
  (tools/evaluate.py against the 0.5.1 metrics): median distance 13.53 → 12.63,
  spectral 8.84 → 8.00 dB, envelope correlation 0.706 → 0.733, |level| 4.25 →
  4.22 dB; 324 presets closer, 252 further, 69 unchanged.
* Reverb. The gist parameter table mislabels Serum 1's reverb: index 83 is
  DECAY (0.8 .. 12 s), 85 and 87 are SPIN RATE / SPIN DEPTH (there is no
  pre-delay, damp or width in this build). The converter had used 83 as
  pre-delay and derived the decay from SIZE. RT60 is now measured on both
  synths: Serum's is a floor set by SIZE overtaken by 2000/(12.5 − decay)³,
  Vital's is 1.45·decay_time·f(size), and decay_time is set to match; Serum 2
  gets per-type laws (plate and vintage by SIZE, hall/space by `kParamDelay`,
  abyss by both; the plate runs 6 dB hot). HI/LO CUT drive Vital's pre-filters
  by measured centroid shifts; SPIN maps onto Vital's reverb chorus.
* Mix law. Serum's MIX applies sin²(πw/2) to the wet path (and about 1 − w² to
  the dry); Vital's delay, chorus and reverb crossfade equal-power, its
  distortion, phaser and flanger mix linearly. Wet levels now match within
  0.5 dB (delay echoes were 3.5 dB hot at 50 %, reverb 12 dB too wet at 15 %).
* Delay. Serum 1's free time is 1 + 500·n⁴ ms, not n² seconds (75 % is 159 ms,
  it was 580); the OFFSET knob (0.5 .. 1.5×, "Dot 1/2", "Dot") was ignored and
  now picks the nearest plain / dotted / triplet division. Serum 2's synced
  ladder is a measured boundary table on the stored seconds and its 4/3
  "triplet" is the triplet of the next longer division. Vital's ping-pong
  echoes run 3 dB above its plain delay's; compensated.
* Synced modulation rate. Serum 1's RATE knob steps through a 31-entry ladder
  with dotted and triplet divisions (Off, 24 bar, 32 bar t, 16 bar ... 1/32),
  read from the plugin; the converter had used the LFO's plain table. Serum 2
  quantises the same knob position (checked on the dotted-quarter and
  quarter-triplet renders).
* Chorus. Serum's FILTER is a 1 kHz low-pass on the wet path by default; Vital's
  chorus filter was left fully open (its cutoff had been set but not its
  spread), and the "mono" switch had been mapped onto that spread, producing a
  band-pass. The low-pass is now applied; the switch is reported only.
* Distortion. Every Serum mode sits 6 dB below unity at zero drive with its own
  drive curve (Diode 1 clips hard at zero drive, the folds jump to full effect
  by 25 %); each mode carries a measured level table matched onto Vital's
  measured drive curve (folds by centroid). Clipping modes land within 0.2 dB
  of Serum at every drive; they were up to 7 dB hot.
* Compressor. Vital's attack/release are base_ms·exp(8x − 4) (1.4 / 28 ms), so
  Serum's 1000·n² ms knobs are mapped through that (the default 90 ms release
  had become 5.6 ms); its follower reads a saw 12 dB above Serum's detector, so
  thresholds shift +12 dB; band gains start from 0 dB instead of Vital's +12/+16
  defaults (which only undo Vital's own default upward compression); GAIN is
  20·log10(1 + 31n²) dB. Serum's multiband mode is an OTT-style upward and
  downward compressor scaled by the RATIO knob (transparent plus 1.9 dB at 1:1),
  with the L/M/H knobs as band level and a wet knob that cancels against the
  band split; all of it is modelled on Vital's multiband compressor and matches
  the fixtures within 0.5 dB across ratios, thresholds and wet.
* EQ. Vital's shelves sit half an octave above Serum's and peak with resonance
  (they are shifted −6 semitones and left flat); the Q knob maps onto Vital's
  resonance through measured tables. Peaks and passes match within 0.5 dB.
* Hyper / Dimension, phaser, flanger. Hyper adds its voices on top of the dry
  signal, so Vital's chorus wet is 0.55× Hyper's WET and 0.42× Dimension's MIX
  (matched on side level), with at most three voice pairs. Serum's STEREO 180°
  is a Vital phase offset of 0.02 (phaser) and 0.1 (flanger), and Serum's
  flanger sits at a fixed ~16 ms delay (Vital centre note 34).
* Serum 2 conversions were 3.0 dB louder than Serum 2's own render of the same
  preset (the Serum 1 path's 1.6 dB synth offset was missing and Serum 2 sits
  1.4 dB below Serum 1 at identical settings); corrected at the master.
* Parameter table fixes: 193 is `Mod 7 out` (the gist repeated `Mod 8 out`),
  270-272 are the multiband `CompMB L/M/H` knobs, and the per-effect
  `FX * Level` trims (289-298, 40·log10(2n) dB) default to 0 dB.

* Serum 2 can now be driven headlessly. `tools/serum2_host.py` loads
  Serum2.vst3 through DawDreamer, injects a `.SerumPreset`, reads parameters
  back and renders. The block was a state-format detail, not the host: Serum
  2's VST3 state is a processor container plus a controller container, a
  `.SerumPreset` is the union of both, and Serum silently keeps its previous
  state when a container carries the other side's keys. The host splits the
  preset by each container's own key set. `tools/listen.py` renders Serum 2
  originals next to their conversions like it does for Serum 1.

## 0.5.1 (2026-09-10)

* Pitch modulation ranges. A Serum modulation amount is a fraction of the
  Serum parameter's range, so routings to Semi (±12 st) and CoarsePit (±64 st,
  measured) must be rescaled onto Vital's ±48 st transpose; they were passed
  through 1:1, which played Semi-driven arpeggios and sequences four times too
  wide (e.g. "ARP - Fine Wine", whose LFO 5 steps A/B Semi). Same fix for the
  Serum 2 path, where Pitch and Octave routings were also unmapped. Serum 1's
  static CoarsePit value is now added to the oscillator transpose (it was
  ignored).
* Serum 1 matrix "type" column decoded: byte +0x0C of a matrix record is the
  unipolar/bipolar switch (set in 12% of routings, almost all LFO → pitch).
  A bipolar routing swings ±amount·range/2 around the knob (measured on "SQ
  Minor Arp": 12 − 24·y semitones), which is Vital's bipolar flag; it was
  being converted as one-sided, so bipolar arps and vibratos sat a whole
  modulation range too high.
* Serum 1 new-layout (1.3+) LFO shapes were read one entry off: each LFO
  block is an 8-byte header followed by 480 curve, 480 x and 480 y doubles,
  but the reader took y from 8 bytes too far and the curves from 8 bytes too
  early. The first y value was dropped, so the default shape read as 0,1,1
  instead of 1,0,1 and every new-layout LFO converted upside down (level and
  filter wobbles inverted, arps mirrored), and each segment took its
  neighbour's curvature. Confirmed by rendering crafted 1.3 fixtures: the
  converted default, trigger-mode and multi-point shapes now track Serum's
  level envelope cycle for cycle. The nine factory folders are older,
  classic-layout files, but about a third of a typical library (every pack
  saved from Serum 1.3 or later, e.g. "ARP - Fine Wine" and the Cyberpunk
  arps) uses this layout; on the 30-preset arp set the loudness-envelope
  correlation went from 0.33 to 0.68 and the median distance from 16.4 to
  13.8. Over the 600 factory clips the median distance moved 13.7 → 13.5.
* LFO smoothing law: Serum's Smooth knob is close to inaudible below 50%
  (measured on a step LFO), so it now maps as 0.5·s⁶ seconds instead of 0.5·s;
  the old law smeared every 10%-smoothed step arp by 50 ms.
* Serum 2 is now hosted headlessly (`tools/serum2_host.py`, DawDreamer with the
  VST3 state split into its processor/controller containers), so Serum 2 FX
  and modulation laws can be measured by rendering crafted presets, and
  `tools/listen.py` renders Serum 2 originals next to their conversions.
* Listening site: an "arp" set (the 30 Cyberpunk arps, all new-layout files)
  joins the nine factory sets and the reeses so the LFO fix can be heard.
* Aux-source routings were twice as strong as intended: Vital's per-routing
  amount parameter spans −1..1, so meta-modulating it by x moves the amount
  by 2x (measured: 23 st vs 41 st pitch swing). The aux link now carries half
  the Serum amount, in both the Serum 1 and Serum 2 paths.

## 0.5.0 (2026-09-10)

* Serum 1 LFO shapes were upside down. Rendering LFO-to-level routings through
  both plugins showed that Serum's stored y and Vital's LFO JSON share the
  same orientation (0 at the top), so the converter's inversion flipped every
  LFO, and that Serum ties the curve's last point to its first (the default
  shape plays as a triangle). Flat curves are avoided because Vital's voice
  collapses on them even when the LFO is unused. On the 89 factory presets
  without real approximations the loudness-envelope correlation went from 0.60
  to 0.72 and the median distance from 12.3 to 11.4; over all 599 scored
  factory presets the median distance went from 14.7 to 13.8 and the presets
  within 6 of their original from 44 to 55.
* Serum 1 levels measured against the plugin: the sub oscillator's level knob
  is linear in amplitude and 3.7 dB below Vital's sine; the noise Pitch knob
  drops about 100·log2(2v) semitones below its centre; FM from the sub needs
  1.5× the warp amount in Vital. A unison-count gain table and an extra
  filter-drive compensation were measured, tried and rejected by the same
  evaluation (they made the level spread worse).
* Serum 1 compressor: crafted presets finally let Serum's compressor be
  measured. Serum barely changes level as the threshold rises while Vital
  keeps its default band gains, leaving Vital up to +7 dB hot at high
  thresholds and +10.5 dB hot in multiband mode; half of that measured excess
  is now taken out of the band gains (the full amount over-corrected on real
  presets), which centres the library's level bias (+1.5 dB → +0.2 dB).
* `tools/evaluate.py`: converts a tier of presets in-process, renders Vital and
  scores against the Serum clips in about a minute, with `--calib` switches to
  ablate individual mapping changes.
* Listening site: every preset now shows its conversion notes (with kind
  badges) and its closeness metrics against the Serum render; pages filter by
  note kind, note family and tier, and sort by distance. `tools/analyze_listen.py`
  computes the metrics (level offset, 1/6-octave spectral distance, envelope
  correlation), groups presets by note family and writes the analysis that
  the site's `analysis/` page and `out/listen/analysis.md` present.

## 0.4.1 (2026-09-09)

* Serum 1 reader: matrix records are identified by `80 <slot> FF` at +0x21;
  the byte before it is not always 0x80, and requiring it dropped about 240
  routings in 3% of library presets, mostly LFO → level (several factory
  sequences converted silent). Slots 1–16 are also checked against their
  fixed offsets.
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
