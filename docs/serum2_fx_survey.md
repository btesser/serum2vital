# Serum 2 FX rack survey

Survey of `FXRack0..2` across the 715 `.SerumPreset` files of a local Serum 2
installation (`Serum 2 Presets`; all parsed, 0 read errors), cross-checked
against the 240 factory module presets in `Effect Chains/*/Factory/*.SerumFX`
(whose names carry display values such as "310ms", "Dotted 8th", "Ping Pong -
4th") and the effects chapter of the Serum 2 user guide (pp. 157-182).
This is what `serum2vital/serum2_fx.py` (per-module mapping) and
`serum2vital/fx_common.py` (tables and chain ordering shared with the Serum 1
path) are built on.

## Container facts

* `FXRack0.FX` is an ordered list, top of the rack first.  Rack lengths seen:
  0-15 modules (median 5), plus one preset with 22.  Bus racks: rack 1 non-empty in
  179 presets, rack 2 in 110.
* An entry is `{"type": N, "<FXName>": {"plainParams": ...}, "kUIParamMixOrGain": 0/1}`.
  `type` 0 = FXDistortion (also carries a `flex` list with the X-Shaper
  curves), 1 Flanger, 2 Phaser, 3 Chorus, 4 Delay, 5 Comp, 6 Reverb, 7 EQ,
  8 Filter, 9 HyperD, 10 Bode, 11 Conv, 12 Utils, 13 Split, 14 Split3,
  15 SplitMS.  The name key is authoritative; `type` is only a fallback.
* `plainParams` is `"default"` or a dict.  It normally holds only non-default
  values, but rack presets and touched knobs also store default-valued
  entries, which is how the most common stored value reveals a default
  (Hyper `kParamRate` 40 / `kParamUnison` 4, EQ `kParamReso` 43.3, reverb
  `kParamDelay` 30.6).
* `kParamEnable` (rare, always 0 when present) is the bypass switch; every
  other module is active.
* `kParamWet` = 0 is common (delay 221, reverb 245, distortion 164, chorus 102
  modules) and in 90% of those cases the module's wet is a modulation
  destination (macro-controlled effect), so wet 0 is real and kept.
* `kParamLevelOut` (0..1, 0.5 = 0 dB) is the per-module LEVEL; Vital has no
  equivalent, it is reported when it differs from 0.5.
* Modulation slots address FX parameters as
  `destModuleTypeString="FXDelay"`, `destModuleParamName="kParamWet"`.

Duplicate module kinds in rack 0 (Vital has one instance of each): EQ 116
presets, Comp 94, Distortion 74, Filter 62, Reverb 30, Delay 16, Chorus 4,
Flanger 2, Hyper 1.  The converter keeps the first and reports the rest as
`resource-conflict`.

## Per-module keys, units and mapping

Numbers are min / median / max of the stored (non-default) values.

### FXDistortion (type 0, 506 modules)
| key | values | unit | mapped to |
|---|---|---|---|
| kParamMode | kOverdrive 58, kDownsample 50, kTapeSat 46, kDiode1 42, kSoftClip 33, kSoftSat 32, kDiode2 30, kAsym 22, kHardClip 18, kZeroSquare 18, kSineShaper 14, kRectify 9, kStompBox 8, kXShaper 6, kSinFold 6, kLinFold 4, kXShaperAsym 1; default kTube (guide) | name | `distortion_type` via `DIST_MODE_TO_VITAL` in `fx_common.py` (SoftClip/HardClip/LinFold/SinFold/Downsample exact, everything else soft clip + note) |
| kParamDrive | 0 / 37 / 100 | % | `distortion_drive` = 0.3 * drive (dB) |
| kParamWet | 0 / 0 / 99.6 | % | `distortion_mix` |
| kParamPrePost | 1 (108) / 2 (65); default 0 | 0 off, 1 pre, 2 post | `distortion_filter_order` |
| kParamFreq | 0 / 0.61 / 1 | knob 0..1 (measured Dist_Freq law: note = 128 * n) | `distortion_filter_cutoff` |
| kParamLPHP | 0.1 / 69 / 100 | 0 LP, 50 BP, 100 HP | `distortion_filter_blend` = LPHP / 50 |
| kParamBW | 0.075 / 0.57 / 7.6 | bandwidth (octaves) | `distortion_filter_resonance` = 1 - (BW - 0.075) / 7.5 |
| kParamNumStages | 2..16 | stages (Overdrive) | dropped, noted |
| flex | X-Shaper curves | | dropped, noted |

### FXFlanger (1, 64) and FXPhaser (2, 125)
| key | values | unit | mapped to |
|---|---|---|---|
| kParamRate | 0 / 0.13 / 8.5 (flanger), 0 / 0.17 / 20 (phaser) | Hz, quartic knob (20 * n^4) | `*_frequency` = log2(Hz); synced: `*_tempo` from knob position over 8/1..1/32 |
| kParamBeatSync | 1 when present | default off | `*_sync` |
| kParamDepth | 0 / 53 / 100 | % | flanger `mod_depth` = %/100; phaser `mod_depth` = 48 * %/100 semitones |
| kParamFeedback | 20 / 60 / 91 (flanger), 0 / 68 / 100 (phaser) | % | `*_feedback` = %/100 |
| kParamWidth | 0 / 167 / 360 | degrees (stereo LFO phase) | `*_phase_offset` = deg / 360 |
| kParamWet | 0 / 0 / 87 | % | flanger `dry_wet` = 0.5 * %/100 (Vital max 0.5); phaser `dry_wet` = %/100 |
| kParamFreq (phaser) | 20 / 361 / 18000 | Hz | `phaser_center` (note) |
| kParamNumPoles, kParamDepth2 (phaser) | 1..18, 0..1 | | dropped, noted |
| lfophasor | 0..1 | LFO phase state | ignored |

### FXChorus (3, 214)
| key | values | unit | mapped to |
|---|---|---|---|
| kParamRate | 0 / 0.06 / 15 | Hz (0..20) | `chorus_frequency` = log2(Hz) or synced tempo |
| kParamDelay / kParamDelay2 | 0 / 2.8 / 12.8 and 0.05 / 0.65 / 10.5 | ms | `chorus_delay_1/2` = log2(ms / 1000), floor 1 ms |
| kParamDepth | 0 / 6.6 / 25 | ms (Serum knob max 26) | `chorus_mod_depth` = depth / 26 |
| kParamFeedback | 0 / 15 / 72 | % | `chorus_feedback` = %/100 (cap 0.95) |
| kParamFilt | 50 / 4756 / 20000 | Hz | `chorus_cutoff` (note) |
| kParamFiltMode | 1 (HPF) when present | | Vital is LP only: cutoff opened, noted |
| kParamWet | 0 / 0 / 100 | % | `chorus_dry_wet` |
| voices | Serum: 2 stereo pairs | | `chorus_voices` = 2 |

### FXDelay (4, 469)
| key | values | unit | mapped to |
|---|---|---|---|
| kParamBeatSync | 0 when present (16) | default synced | `delay_sync` |
| kParamMode | 1 (198), 2 (37); default 0 | 0 Normal, 1 Ping-Pong, 2 Tap->Delay | `delay_style`: Normal -> Mono (equal times) or Stereo, Ping-Pong -> Ping Pong, Tap->Delay -> Mono using the right time (noted) |
| kParamTimeL/R | 0.001 / 0.051 / 0.34 | seconds, also when synced | free: `delay_frequency` = log2(1 / (time * offset)); synced: division from a geometric ladder anchored at 1/8 = 0.0387 s and 1/4 = 0.0832 s (factory presets "Dotted 8th Delay", "4th, Dotted 4th") -> `delay_tempo`, noted as approximate |
| kParamOffsetL/R | 1.5 (dotted, 89), 0.5, 1.333 (triplet) ... | time scalar | `delay_sync` 2 Dotted / 3 Triplet; other scalars multiply the free time |
| kParamLink | 1 when present | R follows L | right channel copies left |
| kParamFeedback | 0 / 40 / 94 | % | `delay_feedback` |
| kParamFreq | 40 / 979 / 18000 | Hz | `delay_filter_cutoff` (note) |
| kParamBW | 0.75 / 3 / 8.25 | bandwidth ("Q", larger = wider) | `delay_filter_spread` = (BW - 0.75) / 7.5 |
| kParamWet | 0 / 0 / 100 | % | `delay_dry_wet` |
| right channel | | | `delay_aux_sync/tempo/frequency` (used by Vital's Stereo style) |

### FXComp (5, 613)
| key | values | unit | mapped to |
|---|---|---|---|
| kParamThresh | 0 / 0.46 / 1 | knob 0..1 (0 dB .. -120 dB, measured Cmp_Thr law) | `compressor_*_upper_threshold` via `fx_common.comp_threshold_db`; lower threshold 10 dB below |
| kParamRatio | 1 / 4 / 1e6 (Limit) | ratio | `*_upper_ratio` = 1 - 1/r (Limit -> 1) |
| kParamRatioBelow, kParamRatioBelow0/1/2 | 0..1 | knob (same 1 - 1/r law) | `*_lower_ratio` |
| kParamRatio0/1/2 | 0..1 | per-band ratio knob | per-band `*_upper_ratio` |
| kParamAttack / kParamRelease | 0.1 / 48 / 1000 and 0.1 / 114 / 1000 | ms (knob law 1000 * n^2) | `compressor_attack/release` = sqrt(ms / 1000) |
| kParamMakeup | 1 / 2 / 31 | linear gain | makeup dB = 20 log10 -> added to every band gain |
| kParamMultiband | 1 when present | | `compressor_enabled_bands` 0 Multiband / 3 Single |
| kParamGain0/1/2 | -24 .. 24 | dB (low/mid/high) | `compressor_low/band/high_gain` |
| kParamThreshUD0/1/2 | 0 / ~80 / 200 | % of the main threshold | scales the per-band threshold |
| kParamXoverLow/Hi | 36..5000 / 300..10600 | Hz | dropped (Vital's crossovers are fixed), noted |
| kParamWet | 0 / 0.4 / 99 | % | `compressor_mix` |
| kParamDeadband*, kParamCompensatedWetDry | | | dropped |

### FXReverb (6, 543)
| key | values | unit | mapped to |
|---|---|---|---|
| kParamType | kHall 274, kVintage 93, kAbyss 42 (Nitrous), kSpace 24 (Basin); default kPlate | name | one Vital algorithm; non-plate types noted |
| kParamSize | 0 / 38 / 100 | % | `reverb_size` = %/100; `reverb_decay_time` = -1.74 + 5.5 * size (0.3 s .. 13 s) |
| kParamWet | 0 / 9 / 100 | % | `reverb_dry_wet` |
| kParamPreDelay | 0 / 0.015 / 2.5 | seconds (kParamPreDelayBeatSync = 1 when synced) | `reverb_delay` (cap 0.3 s); sync noted |
| kParamFreq | 4 / 37 / 100 | LO CUT % | `reverb_pre_low_cutoff` = 1.28 * % |
| kParamFreqB | 0 / 37 / 100 | HI CUT % | `reverb_high_shelf_cutoff` and `pre_high_cutoff` = 128 * (1 - %/100) |
| kParamFreqC | 0 / 49 / 100 | DAMP % | `reverb_high_shelf_gain` = -6 dB * % |
| kParamWidth | 0 / 20 / 100 | % | dropped, noted |
| kParamDelay | 0 / 31 / 250 | Hall/Vintage/Nitrous/Basin extra time control (guide: DECAY or PRE-DLY in ms; ambiguous) | dropped, noted |
| kParamFeedback | 0 / 28 / 100 | Nitrous/Basin feedback % | dropped, noted |
| kParamMode, kParamVintageScale(B) | 0..100 | Nitrous mode / Vintage ER size + diffusion | dropped, noted |

### FXEQ (7, 749)
| key | values | unit | mapped to |
|---|---|---|---|
| kParamFreq1 / kParamFreq2 | 22 / 186 / 9454 and 22 / 2696 / 20000 | Hz | `eq_low_cutoff` / `eq_high_cutoff` (note) |
| kParamGain1 / kParamGain2 | -24 .. 24 | dB | `eq_*_gain` clamped to Vital's +/-15 dB (noted) |
| kParamReso1 / kParamReso2 | 0 / 43 / 100 | Q % | `eq_*_resonance` = %/100 |
| kParamType1 / kParamType2 | 1 (peak) 221 / 182, 2 (pass) 218 / 64; default 0 shelf | 0 Shelf, 1 Peak, 2 HP (low) / LP (high) | shelf -> `eq_low/high_mode` 0; pass -> mode 1; peak -> `eq_band_*` when free, else a shelf (noted) |

A second EQ module can still land in unused Vital bands (low / band / high are
claimed individually).

### FXFilter (8, 394)
| key | values | unit | mapped to |
|---|---|---|---|
| kParamType | MgL12 30, Diffuser 19, H12 18, Reverb1 18, MgL18 15, H24 13, MgL24 13, CombP 12, L12 9, Allpasses 9, DirtyMg 8, Combs 8, ... (75 names); default MgL6 | name | `fx_common.filter_type_to_vital`: MgL* -> Ladder, L/H/B/P/N -> Analog + blend, LBH/LPH/LNH morphs -> blend from VAR, dual (LH12 ...) -> first stage, Comb*/Flange* -> Comb, Phase* -> Phaser, Formant* -> Formant, DirtyMg -> Dirty, Ladder* -> Ladder; Diffuser/Reverb1/Allpasses/Combs/RM/SNH/DJMixer/BandReject/PZ_SVF/Wsp/Exp -> analog LP + `unsupported` note |
| kParamFreq | 0 / 0.49 / 1 | knob 0..1 (note = 135 * n) | `filter_fx_cutoff` |
| kParamReso | 0.5 / 27 / 99 | % | `filter_fx_resonance` |
| kParamDrive | 0.4 / 19 / 100 | % | `filter_fx_drive` = 0.2 * % (dB) |
| kParamVar | 3 / 44 / 100 | % (type-dependent) | `filter_fx_blend` = VAR / 50 for morph types, else dropped |
| kParamWet | 0 / 0 / 100 | % | `filter_fx_mix` |
| kParamStereo, kParamPad, kParamX/Y, PZs | | pan offset, pad, PZ editor | dropped |

### FXHyperD (9, 189)
| key | values | unit | mapped to |
|---|---|---|---|
| kParamUnison | 0..7 (4 most common) | voices, 0 = Dimension only | `chorus_voices` = ceil(n / 2) |
| kParamRate | 0 / 40 / 100 | knob % (Hz = 20 * n^4) | `chorus_frequency` = log2(Hz) |
| kParamDetune | 0 / 35 / 100 | % | `chorus_mod_depth` |
| kParamWet | 0 / 0 / 100 | % (Hyper mix) | `chorus_dry_wet` |
| kParamDimESize | 0 / 11 / 100 | % | `chorus_delay_1/2` = log2(0.001 + 0.019 s), log2(0.002 + 0.019 s) |
| kParamDimEWet | 0.4 / 29 / 100 | % (Dimension mix) | added to `chorus_dry_wet`, feedback 0 |
| kParamRetrig | 1 when present | | `unsupported: Hyper retrig` |
| lfo | 8 x 8 floats | LFO phase state | ignored |

When the rack already used the chorus, Hyper goes to the flanger (half wet,
half detune, no feedback) and is reported as `resource-conflict`.

### FXConv (11, 256), FXUtils (12, 224), FXBode (10, 134), splitters (13-15, 86)
* Convolve: `relativePathToIR` (factory IRs), kParamWet 0 / 15 / 100 %,
  kParamDecay 0..40 s, kParamPredelay s, kParamSize 10..1000 %, kParamTone
  -100..100, kParamDamping %, kParamIpTrim dB.  Approximated with Vital's
  reverb when the reverb is free (wet, decay, pre-delay, tone -> high shelf),
  otherwise `resource-conflict`.
* Utility: kParamHPF 1..400 Hz, kParamLPF 50..20000 Hz, kParamWidth 0..800 %,
  kParamBalance, kParamLFMono/LFXover, kParamPolarityL/R.  HPF/LPF become
  Vital EQ pass bands when those bands are free; width/pan/mono/polarity are
  reported.
* Bode (shift/range/delay/blur ...) has no counterpart: reported.
* Splitters carry kParamFreq (crossover Hz) and kParamModuleCountN (modules
  per branch, which follow in the flat list).  The branches are converted as
  a flat chain and the split is reported.

## Chain order

`fx_common.vital_chain_from_rack` keeps the relative order of the first
occurrence of each mapped module (Hyper at the chorus position, Convolve at
the reverb, Utility at the EQ) and appends the unused Vital effects in Vital's
default order; `fx_common.encode_effect_order` implements Vital's
`utils::encodeOrderToFloat` factorial code (0 = default order, 362879 =
fully reversed).  Buses 1 and 2 are not converted; their module lists are
reported as `unsupported: FX bus N with ...`.

## Open items

Settled on 2026-09-10 with crafted presets rendered through `tools/serum2_host.py`
(see `FIXTURE_PRESETS_TASK.md`, Batch C, and `FINDINGS_AND_PLAN.md`, third pass):

* The synced delay-time law is a boundary table on the stored seconds
  (`fx_common.DELAY_SYNC_BOUNDS`), not a geometric ladder; the offset scalar
  4/3 is the triplet of the next longer division.
* The synced RATE knob of chorus/flanger/phaser steps through Serum 1's
  31-entry ladder by knob position (`fx_common.FX_RATE_RUNS`).
* Reverb `kParamDelay` is a decay control for Hall (and Abyss) and does
  nothing for Vintage; each type has its own RT60 law
  (`fx_common.serum2_reverb_rt60`). The `kSpace` type renders silence in the
  headless host and is mapped like Hall.
* The Serum 2 conversion path rendered 3 dB louder than Serum 2 itself on the
  Init preset (Serum 2 sits 1.4 dB below Serum 1 at identical settings, and
  the Serum 1 path's 1.6 dB synth offset was missing); corrected.

Still open:

* Module defaults that are not visible in the corpus (chorus delays, flanger
  width, delay time) are educated guesses in `S2_FX_DEFAULTS`
  (`serum2_fx.py`); they only matter when a preset leaves that knob untouched.
* The EQ Q knob (`kParamReso`, default 43.33) is assumed to follow Serum 1's
  Q law; it has not been measured on Serum 2.
