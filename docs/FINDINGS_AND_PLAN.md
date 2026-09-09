> **Historical investigation record.** This file is the log of how the Serum
> formats and the Vital mapping were worked out, kept largely as written.
> Sections 10 and 11 supersede the "open" and "unresolved" remarks in earlier
> sections; notes marked *Resolution* point at them. The current reference is
> `FORMATS.md` (file layouts and tables) and the top-level `README.md` (what
> the converter does and where it stops).

# Converter findings and plan (validated against Serum, Vital source and the corpus)

This consolidates the earlier plan, now kept as `HISTORY_initial_plan.md`
(whose direction stands), with a deeper investigation. Everything below was checked against one of:

* the installed Serum 1 plugin itself, driven headlessly through DawDreamer
  (VST2 build at `C:/Program Files/VstPlugins/Serum_x64.dll`), which loads
  `.fxp` files and reports every parameter's display text;
* Vital's own source (`synth_parameters.cpp`, `synth_strings.h`,
  `synth_oscillator.h`, `synth_lfo.h`, `synth_voice_handler.cpp`,
  `chorus_module.cpp`, `utils.cpp`);
* the local libraries: 7,578 Serum 1 presets, 714 Serum 2 presets and 6,845
  Vital presets.

Measured Serum tables live in `tools/serum_display_tables.json` (filter, warp,
distortion, stack, sub-shape, EQ, delay-mode and compressor-ratio lists; LFO
rate step tables for both BPM and Hz modes; unit sweeps for 55 parameters).

---

## 1. Verdict on the feedback

| Claim | Verdict |
|---|---|
| Vital has a free LFO rate; "13 divisions" is a converter bug | **Correct.** Vital `lfo_N_sync` = Seconds / Tempo / Tempo Dotted / Tempo Triplets / Keytrack; `lfo_N_frequency` is continuous (stored as log2 Hz). The Serum 1 Hz/BPM, dotted and triplet flags were located in the preset (section 4). |
| Filter types undersold | **Correct.** Vital: Analog/Dirty/Ladder/Digital each with 12dB, 24dB, Notch Blend, Notch Spread, B/P/N; Diode with Low Shelf/Low Cut; Comb with six comb/flange styles; Formant; Phaser. Plus blend, blend_transpose, formant X/Y, keytrack, two voice filters with routing, and an FX filter. |
| Warp has two axes | **Correct.** Distortion type (None, Sync, Formant, Quantize, Bend, Squeeze, Pulse, FM/RM from either other oscillator or sample) and spectral morph (12 types). The converter currently ignores FM/RM entirely. |
| Unison stack has no counterpart | **Wrong.** Vital has Unison, Center Drop 12/24, Octave, 2x Octave, Power Chord, 2x Power Chord, Major/Minor, Harmonics, Odd Harmonics. Serum's nine modes all map. |
| Hyper cannot be approximated | **Wrong.** Hyper is a 1-7 voice micro-delay chorus; Vital's chorus has up to 4 delay pairs (8 taps), two base delays, depth, rate, feedback, filter. Hyper is enabled in 54% of Serum 1 presets, so this is the single most audible gap. |

---

## 2. Bugs in the current converter (all confirmed, ordered by impact)

| # | Bug | Evidence | Affects |
|---|---|---|---|
| 1 | Macro modulation sources are written as `macro_1..4`; Vital's name is `macro_control_N` | 1,290 uses of `macro_control_1` in real Vital presets, zero of `macro_1`; parameter list in `synth_parameters.cpp` | every macro routing is silently dead |
| 2 | Synced LFO rate two octaves too slow: knob 0.5 mapped to 1 bar, Serum's 0.5 is **1/4** | Serum text table: steps 112-127 = "1/4"; 79-94 = "bar"; 16 steps per octave from 32 bar to 1/256 | every synced LFO |
| 3 | Envelope time curve: code assumes `t = 32·n⁴`; Serum is `t = 32·n⁵` | Serum text: n=0.5 gives 1.00 s, n=0.75 gives 7.59 s, n=0.25 gives 31 ms | every envelope (a 0.5 knob becomes 2 s instead of 1 s) |
| 4 | Filter table is 1-based; Serum is 0-based (index 0 = MG Low 6, 1 = MG Low 12) | Serum text at value 1/95 = "MG Low 12"; most common corpus value is index 1 | every preset with a filter (88%) |
| 5 | Warp mode read as `round(v·12)`; real list has 24 entries (`v·23`) | corpus values are multiples of 1/23; Serum text table | every non-Off warp (45% of active oscillators); mode 18 "FM (from B)" is the second most used warp and is unmapped |
| 6 | LFO shapes in the newer 172,736-byte preset variant are read from a region that is all zeros, producing flat LFOs | 34% of the library is this variant; shapes actually live at 0x84D8 with a different layout (section 4) | one third of all presets |
| 7 | LFOs 5-8 shape block read from 0x1CE8; actual start is 0x1B70 | float64 run analysis; LFO 5-8 parse fails in 66% of the older variants | any preset using LFO 5-8 |
| 8 | Distortion mode read as `round(v·11)`; list has 16 entries (`v·15`), 13 in older builds | Serum text table; Serum re-bases legacy indices on load, index order is preserved | distortion presets |
| 9 | Unison stack index passed straight through; Serum has 9 modes (`v·8`) in a different order from Vital's 11 | Serum text table vs Vital strings | stacked-unison presets |
| 10 | Sub oscillator shapes wrong: Serum list is Sine, RoundRect, Saw, Square, Pulse (code assumes sine/tri/square/saw/pulse) | Serum text table | sub-osc presets |
| 11 | LFO rise/delay scaled to 8 s; Serum range is 0-4 s | Serum text | minor |
| 12 | Master volume assumed 70% = 0 dB; Serum is `n³` (70% = -9.3 dB, 100% = 0 dB) | Serum text | level calibration |

Smaller confirmed unit facts (all in the tables file): cutoff is `8 Hz · (22050/8)^n`,
so the "MIDI note 0-135" assumption was fine; oscillator level is `n²`
(the existing sqrt is right); env 1 sustain is `n²` in amplitude and Vital squares
its amplitude envelope too, so passing `n` straight through is right; effect rates
in Hz are `20·n⁴`; chaos rate is `1000·n⁵`; portamento is `8 s·n⁵`; compressor
attack/release are `1000 ms·n²`; unison detune is `n²` of the detune range.

---

## 3. Vital capabilities validated from source

* Modulation sources: `lfo_1..8`, `env_1..6`, `random_1..4`, `random`,
  `macro_control_1..4`, `velocity`, `note`, `note_in_octave`, `mod_wheel`,
  `pitch_wheel`, `aftertouch`, `slide`, `lift`, `stereo`.
* LFO: `sync` 0-4 as above; `sync_type` Trigger / Sync / Envelope / Sustain Env /
  Loop Point / Loop Hold (Serum TRIG, OFF, ENV map onto the first three);
  `tempo` 0-12 = Freeze, 32/1 … 1/64; `fade_time` 0-8 s; `delay_time` 0-4 s;
  `smooth_mode` + `smooth_time`; `stereo`; `phase`.
* Random LFOs: Perlin, S&H, Sine Interpolate, Lorenz Attractor. Serum Chaos 1/2
  map to `random_1/2` (Lorenz, or S&H when Serum's S&H is on); Serum Note-on
  Random maps to Vital's `random` per-note source.
* Filter models and styles as in section 1; blend 0-2 selects LP/BP/HP (or
  the notch/peak variants per style); `filter_N_keytrack`.
* Oscillator: 13 distortion types (FM/RM from the other two oscillators and the
  sample), 12 spectral morph types, 11 stack styles, `detune_power`,
  `detune_range`, `frame_spread`, `distortion_spread`.
* Effects: chorus 1-4 voice pairs with two base delays (1-20 ms), feedback,
  cutoff, depth, free or synced rate; flanger; phaser; delay with Mono /
  Stereo / Ping Pong / Mid Ping Pong styles and synced or free time; reverb;
  multiband compressor; 3-band EQ with shelf / pass / notch modes;
  distortion with pre/post filter. `effect_chain_order` is a permutation code
  (`utils::encodeOrderToFloat`, factorial encoding) so Serum's rack order can
  be reproduced exactly.
* Amplitude is `(env_1 · level)²`; envelopes store `t^(1/4)`.

---

## 4. Serum 1 binary discoveries

The published 299-parameter block is exactly what Serum reads (host readback
matches the block for 225-228 of 228 values; the only differences are enum
values Serum re-bases and defaults for fields older builds lack).

**Per-LFO settings record** (older variants, 20,704-34,016 bytes), 144 bytes
at 0x1AE0 for LFO 1-4, laid out as four-byte groups (one byte per LFO):

| offset | meaning | evidence |
|---|---|---|
| +0x00 | point count | 2 default; matches shape edits at 0.9+ |
| +0x04 | float32 rate copy ×4 | equals the rate parameter |
| +0x14 | flag A, default 1 | unresolved at the time: probably TRIG mode. *Resolution (section 10): ANCH* |
| +0x18 | **Hz mode** (BPM off) | Serum shows "x.x Hz" iff this byte is 1 (5/5 and 0/14 counter-examples) |
| +0x1C | **dotted** | Serum shows "1/4." iff set |
| +0x20 | **triplet** | Serum shows "1/4 t" iff set |
| +0x24 | flag E (59% of LFO 1) | unresolved at the time: ENV mode or "custom shape". *Resolution: mode is not OFF (TRIG or ENV)* |
| +0x28 | flag F (25%) | unresolved at the time. *Resolution: mode is ENV (together with +0x24)* |
| +0x40 | int32 -1 ×4 | loopback point, probably |
| +0x50 | int32 65 ×4 | grid or array length |

LFO 5-8 shapes start at 0x1B70 (12 arrays × 65 float64, 520-byte stride). Their
settings record is not the same layout at 0x33D0 and is still open. *(Still
true: the reader only uses the anchor bytes at 0x33D0 for LFO 5-8.)*

**FX rack order**: ten int32 at 0x3BE0, one per effect in enable-parameter order
(Dist, Flg, Phs, Cho, Dly, Comp, Rev, EQ, Filter, Hyper), value = rack position.
Default `(1,2,3,4,5,6,7,8,9,0)` = Hyper first, matching Serum's default rack.

**Newer variant (172,736 bytes, 34% of the library)**: the 0x0280-0x3460 LFO
region is zero. Shapes are 12 blocks from 0x84C8, stride 0x2D28: a 16-byte
header (int32 array length 65 or 481, float32 rate) then tension, x, y arrays of
481 float64 each. Blocks 1-8 are the LFOs; 9-12 are probably the Remap graphs.
The Hz/dotted/triplet flags for this variant were **not** found by byte or bit
scans over the first 0x8400 bytes; they need fixture files (section 7).
*Resolution (section 10): the fixtures placed the six flag bytes at block
offset +0x2D08. `FORMATS.md` describes the same blocks as starting at 0x84D8
with the arrays first (y is 479 long) and the flags, point count and the
array-length/rate pair in the trailing 32 bytes; the "16-byte header" above is
that trailer seen from the next block.*

**Enum encodings** (index/(count-1), append-only across builds):
filter 96 entries (`v·95`, older builds `v·89`, `v·88`), warp 24 (`v·23`),
distortion 16 (`v·15`, older 13), stack 9 (`v·8`), sub shape 5 (`v·4`),
EQ type 3, delay mode 3 (Normal, Ping-Pong, Tap->Delay), Hyper voices 8.

**Mod source ids**: 1 = Mod Wheel, 13 = Velocity, 14 = Note (all from routing
statistics: wheel-as-aux vibrato, velocity to amp, note to cutoff). Serum's
menu order from the binary is Env 1-3, LFO 1-8, Velo, Note#, Poly Aftertouch,
Chaos 1, Chaos 2, NoteOn Rand 1, NoteOn Rand 2, NoteOn Alt, NoteOn Alt 2,
Macro 1-4, MPE X/Y/Z, Rel. Velo, Fixed; ids 15-23 and 28-33 need one fixture
preset to pin down (section 7). *Resolution (section 10): pinned down by
`11 sources.fxp`; the full table is in `FORMATS.md`.*

---

## 5. Serum 2 facts that matter

* LFO: `kParamBeatSync` (absent = synced), `kParamDotted`, `kParamTriplets`,
  `kParamRate` in Hz when unsynced (0-100), `kParamMode` Free/Envelope,
  `kParamType` Lorenz/Rossler/RandomSH/Path. The synced `kParamRate` is a
  continuous knob value whose division is only known from Serum 2's rate
  table; that table still needs one fixture set from Serum 2.
* Filters are named strings (`MgL24`, `LadderEMS`, `H18`, `LH12`, `CombP`,
  `Diffuser`, `FormantTWO`, `Scream`...), so a name-keyed table is enough.
* Warp menus are named (`kPD_OSC`, `kSync`, `kBendPos`, `kPWM`, `kFM_OSC`,
  `kDistTube`, `kAM_SUB`...), two slots per oscillator.
* FX racks are ordered lists of `{type, FXName: {plainParams}}`; types seen:
  1 Flanger, 2 Phaser, 3 Chorus, 4 Delay, 5 Comp, 6 Reverb, 7 EQ, 8 Filter,
  9 HyperD, 10 Bode, 11 Conv, 12 Utils, 13-15 splitters, plus Distortion keyed
  `FXDistortion`. Rack 0 is the main chain; racks 1-2 are FX buses.
* Sources 2-5 Env, 6-15 LFO, 25-32 Macro; ids 1 and 16-24 unresolved.
  *Resolution: 1 (mod wheel), 16 (velocity), 17 (note), 18 (aftertouch), 21
  and 23 (note-on random) were identified later from what they modulate
  (`SERUM2_SOURCES` in `mapping.py`); 19, 20, 22 and 24 remain open.*

---

## 6. Validation harness (both halves proven working)

* **Serum side**: DawDreamer loads Serum VST2, `load_preset(fxp)` works, every
  parameter's display text is readable, and MIDI files render to audio.
  The host also loads Vital and Serum 2 VST3.
* **Vital side**: pedalboard loads Vital VST3; its state is JUCE base64
  (`<size>.<data>`, alphabet `.A-Za-z0-9+/`) wrapping `VstW` + `CcnK/FBCh`
  with the `.vital` JSON at offset 176. Decoding works; encoding is the inverse.
* This enables: (a) regression tests that read enum text and units straight
  from Serum instead of guessing; (b) A/B rendering of the same MIDI through
  Serum and through Vital with the converted preset, comparing loudness,
  spectral centroid, modulation period and stereo correlation.

One caveat: crafted `.fxp` files (recompressed, single-parameter edits) load
fine, but the batch-edited fixtures used for behavioural tests were rejected by
Serum and fell back to the init patch for a reason not yet isolated. Manual
fixtures from the real GUI avoid this entirely.

---

## 7. Fixtures to save manually in Serum (fastest path to close the open items)

*This list became `FIXTURE_PRESETS_TASK.md`, which records which fixtures
exist; the numbering there differs from the one below.*

Each is "Init preset, change one thing, save". Saving from the installed build
produces the 172,736-byte variant, which is exactly the variant whose flags are
unknown, and the diff against `00 init` isolates each field.

1. `00 init`
2. `01 lfo1 bpm off` (LFO 1 BPM switch off)
3. `02 lfo1 env` (LFO 1 mode ENV) and `03 lfo1 off` (mode OFF)
4. `04 lfo1 trip`, `05 lfo1 dot`, `06 lfo1 anch`
5. `07 lfo5 bpm off`, `08 lfo5 env`
6. `09 sources`: matrix slots 1-16 with sources in this order, all to A Vol:
   Velocity, Note, Poly AT, Chaos 1, Chaos 2, NoteOn Rand 1, NoteOn Rand 2,
   NoteOn Alt, NoteOn Alt 2, MPE X, MPE Y, MPE Z, Rel Velo, Fixed, Mod Wheel,
   Pitch Bend (and a second file with Aftertouch and Noise OSC if the menu has them)
7. `10 fx order`: drag Reverb to the top of the rack
8. `11 filter keytrack on`, `12 mono legato poly4` (Global: mono/legato and a
   poly count), `13 chaos sh mono` (Chaos 1 S&H and Mono on), `14 unison range
   12 super` (Global unison range 12, mode Super), `15 reverb hall`,
   `16 noise oneshot pitchtrack`, `17 delay link off`
9. `18 lfo1 custom shape 5 points` (any drawn shape) to confirm the 481-point
   array reading.

Drop them in a folder and I will diff and wire them into the reader and tests.

---

## 8. Implementation plan

### Phase 0: harness and tables (foundation, half a day)
* Add `tools/serum_host.py` (DawDreamer) and `tools/vital_host.py`
  (pedalboard + JUCE codec) with a `render(preset, midi) -> audio` API.
* Load `tools/serum_display_tables.json` as the single source of enum names
  and unit curves; add tests that regenerate it from the plugin when present.
* Save the fixture set from section 7 and keep it under `tests/fixtures`.

### Phase 1: correctness fixes (bugs 1-12)
* `macro_control_N` sources; index-based enum tables with build-aware counts;
  `n⁵` envelope curve; LFO rate step tables (BPM: 16 steps per octave, 1/4 at
  0.5; Hz: `100·n⁴`); Hz/dotted/triplet flags for LFO 1-4; correct LFO 5-8
  block; newer-variant LFO reader (481-point arrays); rise/delay 0-4 s; master
  volume `n³`; effect chain order via the factorial encoder.
* Emit fidelity classes on every note: `exact`, `approximation`, `baked`,
  `resource-conflict`, `unsupported`.

### Phase 2: modulation coverage
* Sources: mod wheel, velocity, note, chaos → `random_1/2`, note-on random →
  `random`, aftertouch/pitch wheel once the fixture confirms ids.
* Aux sources: Vital has no aux, but the common case (LFO → pitch with wheel
  or macro as aux) becomes a routing whose amount is modulated by the aux
  source, using `modulation_N_amount` as a destination (Vital supports this;
  real presets use it).
* Curve/bipolar flags where present (Serum 2 `kParamBipolar`, `kParamCurveIn`).

### Phase 3: Hyper / Dimension and effects
* Hyper → chorus: voices `ceil(n/2)` pairs, rate `20·n⁴` Hz → `log2`, detune →
  `chorus_mod_depth`, wet → `chorus_dry_wet`, retrig noted as unsupported.
* Dimension → chorus base delays (`chorus_delay_1/2` from size, depth 0) when
  Hyper is off; when both are on, fold size into the delay times.
* Serum chorus present as well → keep the louder of the two in chorus and
  route the other to flanger with zero feedback; note the conflict.
* Distortion: 16-mode table onto Soft/Hard/Lin Fold/Sine Fold/Bit Crush/Down
  Sample; delay modes onto Vital styles; EQ types onto shelf/pass/notch; delay
  time table (fast … 4 bar) onto `delay_tempo` with clamping.

### Phase 4: filters and warp
* Filter table keyed by name for all 96 entries: MG → Ladder; Low/High/Band/
  Peak/Notch → Analog with blend; dual SVF → filter 1 + filter 2 in series
  when filter 2 is free; morphing L/B/H → blend driven by VAR; Cmb/Flg/Phs →
  Comb/Phaser models with `blend_transpose`; Formant I-III → Formant model;
  EQ 6/12 → Vital EQ; French/German/Add Bass → Ladder/Diode with a character
  note; Ring Mod, SampHold, Combs/Allpasses/Reverb, Dist.Comb, Scream →
  nearest response with `unsupported` character note.
* Warp by name: Sync/Sync windowed → Sync; Bend +/-/± → Bend; PWM → Pulse;
  Asym → Squeeze; Quantize → Quantize; FM/AM/RM from B → FM/RM from osc;
  FM Noise → FM from sample; FM Sub → FM from osc 3; Flip/Mirror/Remap →
  baked into the wavetable when the warp amount is unmodulated, otherwise
  reported.
* Unison: stack table by name; detune `n²·range` onto `unison_detune` with
  `detune_power` 1.5 for Super mode; `Uni WTPos`/`Uni Warp` → frame/distortion
  spread (already present).

### Phase 5: Serum 2 effects racks and dual warps
* Map rack 0 module by module (types 1-9 and Distortion); Bode, Conv, Utils
  width and splitters reported; buses summed with a note.

### Phase 6: A/B measurement loop
* For 200 presets per phase, render C2/C4/C6 for 2 s through both synths and
  compare loudness, centroid, modulation period and stereo width; publish the
  deltas in the report so approximations are ranked by audible error.

---

## 9. Genuinely irreducible after the plan

* Serum 2 granular, multisample and spectral engines; convolution; Bode shift;
  split/mid-side routing.
* Resource limits: more than 3 oscillators, 8 LFOs, 4 macros, 2 voice filters,
  one instance of each effect (Serum 2 buses can hold duplicates).
* Character: filter drive and distortion transfer curves, Dimension's exact
  delay topology, Hyper note-retrigger, Serum's per-frame wavetable
  interpolation, mod-slot curves beyond what `modulation_N_power` covers.
* Serum 2 swing, arp/clip sequencing, MPE per-note settings.

---

## 10. Status (2026-09-08, end of day)

Resolved since the sections above were written:

* Fixture presets (`DebugPresets/serum1`, `DebugPresets/*.SerumPreset`) settled
  the LFO switch bytes in both Serum 1 layouts (anchor, Hz, dotted, triplet,
  not-off, env; TRIG = 1,0, ENV = 1,1, OFF = 0,0), the newer layout's LFO
  block structure (481-point arrays, flags at block +0x2D08), Serum 1's mod
  source ids (13 velocity, 14 note, 16 poly AT, 17/18 chaos, 20/21 note-on
  random, 22/23 alt, 28 pitch bend, 29-31 MPE, 32 release velocity, 33 fixed,
  1 mod wheel), and Serum 2's LFO fields (`kParamBeatSync`, `kParamMode`
  Free/Envelope, `kParamDotted`/`kParamTriplets`, synced `kParamRate` =
  `100·n⁴` on the same knob as Serum 1).
* Serum 2's LFO y axis is also 0 at the top ("saw down" stores 0 → 1).
* Serum uses an LFO shape's final point as drawn (no wrap to the first point).
* Phase 1 (bugs 1-12), the modulation-source work of Phase 2, the filter
  catalog, warp/stack/sub tables and effect ordering are implemented; the
  fixture and unit tests live in `tests/`.

Resolved on 2026-09-09 with the second fixture batch (Serum 1 `11b`-`23`,
Serum 2 `12`, `12b`, `13 rate ×4`):

* The non-automatable switches live in a float32 "global switches block"
  after the parameter array (`FORMATS.md`): mono/legato/polyphony, porta
  Always/Scaled, noise one-shot/pitch-track, filter keytrack, unison
  range/tuning, chaos Mono/S&H. The converter now sets Vital's polyphony,
  legato, portamento switches, sample loop/keytrack, filter keytrack, unison
  detune range/power and random-LFO style/sync from it. The reverb Plate/Hall
  byte sits in the per-effect record at `0x3B04` (note only: Vital has no plate).
* The `.fxp` chunk is two zlib streams plus a length word; keeping the second
  stream makes crafted presets load (`tools/craft_fxp.py`). Rendering crafted
  single-flag variants through Serum told the noise and chaos flags apart.
* Serum 2 source ids are complete for the fixture menu (19 poly AT, 20 noise,
  22 rand 2, 24 alt 2, 33 bend, 34-36 MPE, 37 release velocity, 38 fixed,
  49-59 audio-rate/voice sources, which are dropped with a named note). The
  synced-rate table holds at 4 bar, 1 bar, 1/2 and 1/32.
* Serum's unison tuning modes measured against Vital's detune power: Linear
  = power 0 (Vital's default 1.5 corresponds to Serum's Exp), Inv ≈ −2.

* Follow-up fixtures `14b`, `19b`, `19c`, `24`, `25` (same day) confirmed the
  Plate/Hall switch (block +0x5C, mirrored at `0x3B04`), chaos 2 Mono/S&H at
  +0x44/+0x54 and porta Always/Scaled at +0x18/+0x1C by raw byte diff.

Still open (the full list, with how to settle each item, is the "Known
unknowns" section of `FORMATS.md`; the fixtures that would do it are Batch C
of `FIXTURE_PRESETS_TASK.md`):

* Five fields of the Serum 1 switches block (+0x04, +0x30, +0x4C, +0x58,
  +0x60) that change nothing audible; +0x00 (A4 reference), +0x20
  (oversampling) and +0x48 (chorus mono switch) were identified on 2026-09-09
  by rendering crafted variants and are now converted.
* Serum 2 source ids 39-48, the synced delay-time and FX rate laws, and the
  meaning of the reverb `kParamDelay` for non-plate types. Headless Serum 2
  hosting is blocked (DawDreamer cannot set its state, pedalboard cannot scan
  it), so these need fixtures. The aux id encoding is settled by the library.
* Serum's unison detune width is narrower than Vital's at low knob values
  (±6 vs ±12 cents at 25%, equal at 75%); the amount curve was left as
  calibrated.

## 11. Calibration (measured with the host harness)

`tools/calibrate.py` renders the same parameter experiments through Serum
(host-set on the init preset) and through the converter into Vital, and
compares level and spectral centroid.  Results folded into the mapping:

* Level: the two synths sit 1.6 dB apart at equal settings; the master is
  offset accordingly.  Oscillator level, master volume, cutoff, sub and noise
  levels track within 0.2 dB.
* Warp: Serum's Bend brightens and drops level like Vital's Squeeze, while
  Vital's Bend darkens in both directions, so Serum Bend maps to Squeeze and
  Serum Asym to Vital Bend.  FM index uses `amount^0.8` (Serum is stronger
  below the midpoint), Sync uses `1.3·amount`.  PWM matches as is.
* Filter drive: Serum's drive is a plain gain (+7.6 dB at 25%, +16 dB at
  100%); Vital's is level-compensated.  Half the measured difference
  (`12 dB·n`) is added at the master, since full compensation overshoots on
  closed filters.
* Envelopes: Vital squares its amplitude envelope, so Serum's curve knob maps
  to Vital powers of `+2 − 17.5·(c − 0.5)` for decay/release and `+3 − …` for
  attack on envelope 1; modulation envelopes use `−17.5·(c − 0.5)`.
* Compressor: Vital's default band gains are its unity reference; Serum's
  makeup is added on top (minus 3.5 dB measured overshoot), thresholds come
  from the Cmp_Thr read-out table and Serum's ratio knob is already `1 − 1/r`.
* Reverb: Vital's wet path runs about 2 dB hot; wet is scaled by 0.75.
* Distortion drive: `16 dB·n` (Serum's own rows could not be measured because
  effect enables set through the host do not engage Serum's distortion,
  compressor or EQ; only chorus/reverb/delay/hyper respond).

On a random 16-preset A/B batch, 9 presets now land within 3 dB of Serum's
sustained level; the outliers are heavy-drive patches (still up to +9 dB) and
decaying plucks (up to −17 dB), which is where remaining tuning would go.

