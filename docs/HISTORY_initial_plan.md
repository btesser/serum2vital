# Serum-to-Vital Converter Improvement Plan

> Superseded by `FINDINGS_AND_PLAN.md` (the validated investigation and plan); kept as the original, pre-investigation plan. This file was `CONVERTER_IMPROVEMENT_PLAN.md` at the repository root.

## Executive summary

The converter can be improved substantially. The highest-value changes are:

1. Preserve free-running, straight, dotted, and triplet LFO rates.
2. Approximate Hyper/Dimension with Vital's chorus, with conflict-aware fallbacks.
3. Expand filter mapping by response family and `VAR` behavior.
4. Replace numeric warp and unison-stack mappings with semantic mappings.
5. Convert compatible Serum 2 effects instead of dropping the entire rack.
6. Reserve "unconvertible" for genuinely unavailable synthesis engines, routing topologies, and nonlinear character.

The current limitations are partly genuine, but several are converter limitations rather than Vital limitations.

## LFO handling is a converter bug

Both Serum and Vital support free-running and tempo-synchronized LFOs.

Serum's LFO offers BPM/HZ operation plus dotted and triplet timing. Vital exposes:

- Seconds
- Tempo
- Tempo Dotted
- Tempo Triplets
- Keytrack

Vital also stores a continuous exponential `frequency` parameter separately from its 13 base tempo divisions.

Sources:

- Serum manual: <https://www.xferrecords.com/manual/serum-2/docs>
- Vital parameter source: <https://github.com/mtytel/vital/blob/main/src/common/synth_parameters.cpp>

The converter currently unconditionally writes:

```python
conv.set(f"lfo_{slot}_sync", 1.0)
conv.set(f"lfo_{slot}_tempo", ...)
```

This occurs in `serum2vital/mapping.py` for both Serum 1 and Serum 2. It loses HZ mode, dotted/triplet state, and possibly host-sync behavior.

For Serum 2, the required source fields are already available:

- `kParamBeatSync`
- `kParamDotted`
- `kParamTriplets`
- `kParamRate`
- `kParamRate10x`
- `kParamMode`
- `kParamAnchored`

Across the 714 locally available Serum 2 presets, nearly 1,000 LFO modules explicitly contained `kParamBeatSync = 0`, so free-running conversion is not an edge case.

### Proposed LFO mapping

- HZ mode -> Vital `sync = Seconds`; convert frequency to Vital's exponential representation.
- BPM straight -> `sync = Tempo`.
- BPM dotted -> `sync = Tempo Dotted`.
- BPM triplet -> `sync = Tempo Triplets`.
- Map musical duration by meaning, not by normalized knob position.
- Map Serum trigger/free/envelope behavior separately to Vital `sync_type`.
- Preserve rise, delay, smoothing, phase, and stereo where available.
- Log only unsupported details such as Serum 2 swing or host-anchored phase when they cannot be reproduced.

Serum 1 needs one reverse-engineering step: BPM/HZ and trigger-mode state is not part of the published 299 VST parameter list. Create controlled Serum fixtures—the same patch saved once per mode—and binary-diff them to locate those flags. Until that is established, Serum 1 should not claim exact LFO-rate conversion.

## Hyper/Dimension is highly approximable

Serum describes Hyper/Dimension as a micro-delay chorus. Hyper uses 1-7 modulated voices; Dimension uses four out-of-phase delay lines with slow amplitude modulation.

Source: <https://xferrecords.com/manual/serum-2>

Vital's chorus provides:

- 1-4 voices
- Approximately 1-20 ms delay range
- Two delay controls
- Modulation rate and depth
- Stereo spread
- Feedback
- Filter cutoff
- Wet/dry
- Free and synchronized rates

These capabilities appear in Vital's parameter source:
<https://github.com/mtytel/vital/blob/main/src/common/synth_parameters.cpp>

The converter already parses all relevant Serum 1 values:

- `Hyp_Wet`
- `Hyp_Rate`
- `Hyp_Detune`
- `Hyp_Unison`
- `Hyp_Retrig`
- `HypDim_Size`
- `HypDim_Mix`

It currently ignores them in `serum2vital/mapping.py`.

This is high impact: Hyper/Dimension is enabled in 4,038 of 7,364 readable local Serum 1 presets. Only 725 of those also enable Serum chorus, so most presets have Vital's chorus slot free.

### Recommended Hyper/Dimension approximation

| Serum component | Vital approximation |
|---|---|
| Hyper voices | Chorus voices, capped at four |
| Hyper rate | Chorus free frequency |
| Hyper detune | Chorus modulation depth |
| Hyper mix | Chorus wet/dry |
| Hyper width | Chorus spread |
| Dimension size | Base delay time and separation between delay 1 and 2 |
| Dimension mix | Additional contribution to chorus mix |
| Hyper output level | Compensating mix or output-gain calculation |
| Hyper retrigger | Not exactly reproducible in Vital's global FX chorus |

The mapping should be conditional:

- Hyper only: emphasize modulation depth/rate and voice count.
- Dimension only: use low modulation depth, very slow rate, wide spread, short unequal delays, and no feedback.
- Both: blend the two targets into a four-voice micro-chorus.
- Serum chorus already occupied: preserve the more audible effect in Vital chorus and approximate the other with Vital flanger or oscillator unison when suitable.
- If Hyper mostly provides oscillator-like thickening and all active sources are wavetable oscillators, optionally increase oscillator unison conservatively.
- Never silently drop it; emit a structured approximation note.

Remaining limitations:

- Vital chorus has four rather than seven voices.
- Effect-level Hyper applies to the mixed signal; oscillator unison does not affect noise, samples, or filter returns identically.
- Hyper note retrigger is not available in Vital's global chorus.
- Dimension's exact out-of-phase summing and amplitude-modulation topology cannot be duplicated.

This should be treated as a perceptual approximation, not an exact DSP port.

## Filters can map much more effectively

The current filter mapping handles only the first 18 Serum menu entries, then substitutes analog 12 dB low-pass for everything else. This is unnecessarily destructive.

Vital has eight filter models:

- Analog
- Dirty
- Ladder
- Digital
- Diode
- Formant
- Comb
- Phaser

It also has model-specific styles: five common response styles, two diode styles, and six comb/flange styles.

Source: <https://raw.githubusercontent.com/mtytel/vital/main/src/interface/look_and_feel/synth_strings.h>

The claim that Vital has "somewhere in the 40s" of filter configurations should not yet be placed in documentation. Vital's generic `style` range extends to 9, but not every model/style Cartesian combination is valid. Verify the DSP dispatch and real saved presets before claiming a total.

The following Serum families can clearly be handled better:

- MG filters -> Vital Ladder.
- Ordinary LP/HP/BP/notch/peak -> Analog or Digital, matching response and slope.
- Dirty/character ladder types -> Dirty, Ladder, or Diode.
- Dual SVFs -> one or two Vital filters, depending on routing availability.
- Comb/flange/allpass -> Comb or Phaser models.
- Formant/vowel -> Formant model with X/Y/transpose/resonance.
- Morphing LP/BP/HP families -> Vital blend control.
- Some EQ/shelf types -> filter shelf or Vital EQ.
- French/German/acid character types -> nearest topology plus an explicit character-loss note.
- Ring-mod and sample-and-hold filters -> likely remain approximate or unsupported.

Map filters by semantic attributes:

```text
family + response + slope + secondary response + VAR meaning + character
```

Do not rely only on raw menu indices.

Serum 2 is easier because presets store readable names such as `MgL24`, `LadderEMS`, `DirtyMg`, `H18`, and `Diffuser`. Serum 1 needs a version-aware menu catalog because its stored value is `index / filter_count`.

## Warp modes should use both Vital transformation axes

Vital exposes two independent oscillator transformation axes.

Phase distortion includes:

- Sync
- Formant
- Quantize
- Bend
- Squeeze
- Pulse
- FM/RM sources

Spectral morph includes:

- Vocode
- Formant Scale
- Harmonic Stretch
- Inharmonic Stretch
- Smear
- Random Amplitudes
- Spectral low-pass/high-pass
- Phase Disperse
- Shepard Tone
- Spectral Time Skew

Source: <https://raw.githubusercontent.com/mtytel/vital/main/src/interface/look_and_feel/synth_strings.h>

The converter currently considers only `distortion_type` and maps a guessed Serum numeric mode directly. This misses possible spectral mappings and is fragile across Serum versions.

### Warp strategy

- Build a semantic table for every Serum 1 warp name.
- Map temporal phase remapping to Vital phase distortion.
- Map genuinely frequency-domain operations to spectral morph.
- Map source-driven FM/RM when the same source routing exists.
- Preserve `A/B UniWarp` using Vital's distortion or spectral spread.
- Support Serum 2's two independent warp slots instead of collapsing them into one.
- Report loss only when two Serum transformations compete for one Vital axis, the modulation source is unavailable, or the algorithms fundamentally differ.

Mirror and flip are not automatically good spectral-morph matches because they operate on waveform phase/time structure. They can instead be baked into every wavetable frame when the warp amount is static. If the amount is modulated, baking cannot preserve the motion.

Use a three-tier strategy:

1. Native Vital control.
2. Statically bake the transformed wavetable.
3. Approximate or report unsupported dynamic behavior.

## Unison-stack modes do have Vital counterparts

The claim that Serum's octave/fifth/center-drop stacks have no Vital counterpart is incorrect.

Vital provides:

- Octave
- 2x Octave
- Power Chord
- 2x Power Chord
- Center Drop 12
- Center Drop 24
- Major and minor chords
- Harmonic stacks

Source: <https://raw.githubusercontent.com/mtytel/vital/main/src/interface/look_and_feel/synth_strings.h>

Serum's manual describes octave, octave-plus-fifth, and center-drop stacks. Most Serum 1 stack modes therefore have direct semantic Vital equivalents.

However, the converter currently takes Serum's numeric index and writes it directly to Vital. The menu order is not the same, so this likely produces incorrect stack types. Replace numeric passthrough with a named lookup table.

Serum 2 values are already named—for example `kOctave1`, `kOctaveFifth1`, and `kCenter12`—so their semantic mapping is straightforward.

## Serum 2 effect support is currently far too limited

The code parses Serum 2's structured FX racks but then drops all of them. The 714-preset local corpus contains readable instances of:

- Distortion
- Flanger
- Phaser
- Chorus
- Delay
- Compressor
- Reverb
- EQ
- Filter
- Hyper/Dimension
- Convolution
- Utility/width
- Bode/frequency shifting
- Splitter routing

Many of the first nine map to existing Vital effects. Hyper can be approximated. Utility width can partly map to stereo controls. Convolution, Bode, and arbitrary split routing remain genuine limitations.

Serum 2 FX conversion should therefore be a major workstream rather than permanently documented as unavailable.

## Proposed implementation sequence

### Phase 1: correctness and diagnostics

- Add semantic timing utilities for seconds/Hz, musical durations, dotted, and triplet modes.
- Decode all Serum 2 LFO mode fields.
- Create controlled Serum 1 fixtures to locate BPM/HZ, trigger mode, dotted/triplet, delay, and phase flags.
- Replace unison-stack numeric passthrough.
- Add structured fidelity classifications: `exact`, `native-approximation`, `baked`, `resource-conflict`, and `unsupported`.
- Add unit tests around every mapping.

This removes known incorrect behavior before introducing more ambitious sound-design heuristics.

### Phase 2: Hyper/Dimension approximation

- Implement the chorus-based mapping.
- Handle existing chorus occupancy through an explicit resource allocator.
- Preserve Vital's effect-chain order to match Serum's order as closely as possible.
- Add reference presets covering Hyper only, Dimension only, combined, seven voices, retrigger, and chorus conflict.
- Render matched note sweeps and compare stereo width, correlation, spectral balance, modulation rate, and loudness.

### Phase 3: filter expansion

- Build complete Serum 1 and Serum 2 filter catalogs.
- Inspect Vital's per-model style dispatch to establish valid configurations.
- Implement response-family mappings.
- Use Vital filter 2 only when it is genuinely spare and routing can reproduce the Serum topology.
- Map `VAR` according to each Serum model rather than always sending it to `blend`.
- Create impulse/frequency-response tests at several cutoff, resonance, drive, and VAR positions.

### Phase 4: warp improvements

- Establish named Serum warp catalogs by version.
- Implement phase-distortion mappings.
- Add spectral-morph mappings where the operations are actually analogous.
- Add static wavetable baking for otherwise-unavailable unmodulated transforms.
- Handle Serum 2's dual warp chain and report resource conflicts.

### Phase 5: Serum 2 FX rack

- Map compatible modules and parameters.
- Preserve serial ordering when possible.
- Detect splitters and parallel routing explicitly.
- Approximate Hyper and width utilities.
- Leave convolution, Bode shifting, complex splits, and unavailable modules reported.

## What should remain documented as irreducible

After these improvements, the honest remaining limitations are:

- Granular and multisample playback semantics.
- Serum 2 spectral resynthesis/transient processing where it cannot be baked acceptably.
- Convolution without a convolution effect in Vital.
- Arbitrary Serum 2 parallel/split/Mid-Side FX topology.
- More simultaneous resources than Vital owns: oscillators, LFOs, macros, filters, and effect instances.
- Exact filter and distortion nonlinearities.
- Exact Hyper retrigger and Dimension delay-line topology.
- Dynamic warps that lack a native Vital equivalent.
- Different wavetable interpolation/morphing algorithms.
- Some host-sync, swing, MPE, sequencer, and per-note behaviors.
- Modulation mappings whose source or destination is still unidentified.

## Recommended starting point

Start with Phase 1 and Hyper/Dimension together. They are bounded, high-impact, and testable:

- LFO conversion is demonstrably incorrect today.
- Hyper/Dimension affects more than half of the readable Serum 1 corpus.
- Vital already exposes the parameters needed for a useful Hyper/Dimension approximation.

Filters should follow once the semantic catalog and response-test harness exist.
