"""Effect fixtures: crafted single-purpose presets rendered through Serum and through the converter into Vital.

Each fixture is the Init preset plus a handful of effect settings.  Serum 1
fixtures are written with tools/craft_fxp.py (parameter edits into the
decompressed state), Serum 2 fixtures by editing the CBOR document of
DebugPresets/1.SerumPreset and rebuilding the container.  Both hosts render
the same MIDI event, the same effect-specific metrics are taken from each
render (reverb tail slope, echo times and levels, level / centroid / octave
bands, modulation rate ...), and `compare` prints them side by side so an
effect law can be fitted to Serum's behaviour and checked against Vital's.

    python tools/fx_fixtures.py craft                  # DebugPresets/crafted/{serum1,serum2}/
    python tools/fx_fixtures.py serum [--group reverb] # out/fixtures/<name> - serum.wav, serum.json
    python tools/fx_fixtures.py vital [--group reverb] # convert + render Vital, vital.json
    python tools/fx_fixtures.py compare [--group ...]  # table, also written to out/fixtures/compare.md

The Serum renders happen in a subprocess per plugin generation (DawDreamer
hosts crash at interpreter exit); results are collected from JSON the child
writes before exiting, so the child's exit code is ignored.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT))

SR = 44100
INIT_S1 = ROOT / "DebugPresets" / "serum1" / "00 init.fxp"
INIT_S2 = ROOT / "DebugPresets" / "1.SerumPreset"
CRAFTED = ROOT / "DebugPresets" / "crafted"
OUT = ROOT / "out" / "fixtures"
SERUM_ROOT = Path(os.environ.get("SERUM_ROOT", "D:/VSTData/serum"))

# Serum 1 base: one saw oscillator, no filter, flat sustain (same as tools/calibrate.py).
S1_BASE = {
    "Osc A On": 1.0, "Osc B On": 0.0, "Osc N On": 0.0, "Osc S On": 0.0, "Filter On": 0.0,
    "A Vol": 0.75, "MasterVol": 0.7, "A Unison": 0.0, "WarpOscA": 0.0, "A Warp": 0.0,
    "Env1 Atk": 0.0, "Env1 Dec": 0.5, "Env1 Sus": 1.0, "Env1 Rel": 0.1,
}

# Render shapes per metric kind: (midi note, hold seconds, total seconds).
KINDS = {
    "level": (48, 1.5, 2.5),   # steady tone: level, centroid, octave bands, crest, stereo
    "tail": (60, 0.3, 6.0),    # 0.3 s note (a 30 ms blip does not excite Serum's reverb at large sizes): tail slope (RT60), tail tone
    "echo": (60, 0.03, 3.0),   # short blip: echo times and levels
    "mod": (48, 2.0, 2.5),     # steady tone: modulation rate/depth, width, level
}


# --------------------------------------------------------------------------- #
# fixture recipes
# --------------------------------------------------------------------------- #
FIXTURES: list[dict] = []


def s1(name: str, group: str, kind: str, changes: dict, **extra) -> None:
    FIXTURES.append({"name": name, "engine": "serum1", "group": group, "kind": kind, "changes": changes, **extra})


def s2(name: str, group: str, kind: str, modules: list[dict], env: dict | None = None, **extra) -> None:
    if env is None and kind in ("tail", "echo"):
        env = {"kParamRelease": 0.005}   # Serum 2's default 75 ms release would smear the dry blip
    FIXTURES.append({"name": name, "engine": "serum2", "group": group, "kind": kind, "modules": modules,
                     "env": env or {}, **extra})


def fx(module: str, type_id: int, **params) -> dict:
    """One Serum 2 rack entry."""
    return {module: {"plainParams": params}, "kUIParamMixOrGain": 0.0, "type": type_id}


def _build_recipes() -> None:
    fast_release = {"Env1 Rel": 0.05}

    # ---- Serum 1 reverb: see _build_recipes_2 (the gist mislabels the reverb's Decay/Spin knobs;
    # the first batch was built on those names and is superseded)

    # ---- Serum 1 delay: free time law, feedback, wet, modes, filter
    dly = {"Dly Enable": 1.0, "Dly_Wet": 0.5, "Dly_Feed": 0.0, "Dly_BPM_Sync": 0.0, "Dly_Link": 1.0,
           "Dly_TimL": 0.75, "Dly_TimR": 0.75, "Dly_Mode": 0.0, **fast_release}
    for t in (0.5, 0.75, 0.9):
        s1(f"s1 delay time {t:.2f}", "delay", "echo", {**dly, "Dly_TimL": t, "Dly_TimR": t})
    for fb in (0.25, 0.4, 0.6, 0.8):
        s1(f"s1 delay feedback {fb:.2f}", "delay", "echo", {**dly, "Dly_Feed": fb})
    for wet in (0.18, 0.3, 1.0):
        s1(f"s1 delay wet {wet:.2f}", "delay", "echo", {**dly, "Dly_Wet": wet})
    s1("s1 delay synced 1-4", "delay", "echo", {**dly, "Dly_BPM_Sync": 1.0, "Dly_TimL": 0.625, "Dly_TimR": 0.625})
    s1("s1 delay synced 1-8 dotted", "delay", "echo",
       {**dly, "Dly_BPM_Sync": 1.0, "Dly_TimL": 0.55, "Dly_TimR": 0.55, "Dly_Off L": 1.0, "Dly_Off R": 1.0})
    s1("s1 delay pingpong", "delay", "echo", {**dly, "Dly_Mode": 0.5, "Dly_Feed": 0.5})
    s1("s1 delay unlinked", "delay", "echo", {**dly, "Dly_Link": 0.0, "Dly_TimR": 0.6, "Dly_Feed": 0.4})
    s1("s1 delay filter 850 bw 6.8", "delay", "echo", {**dly, "Dly_Feed": 0.6, "Dly_Freq": 0.5, "Dly_BW": 0.81})
    s1("s1 delay filter 850 bw 2.6", "delay", "echo", {**dly, "Dly_Feed": 0.6, "Dly_Freq": 0.5, "Dly_BW": 0.25})

    # ---- Serum 1 distortion: modes, drive law, wet, pre-gain probe
    dist = {"Dist Enable": 1.0, "Dist_Wet": 1.0, "Dist_Drv": 0.66, "Dist_Mode": 0.0, "Dist_PrePost": 0.0}
    modes = ["Tube", "SoftClip", "HardClip", "Diode 1", "Diode 2", "Lin.Fold", "Sin Fold", "Zero-Square",
             "Downsample", "Asym", "Rectify", "X-Shaper", "X-Shaper (Asym)", "Sine Shaper", "Stomp Box", "Tape Sat."]
    for i, mode in enumerate(modes):
        s1(f"s1 dist mode {i:02d} {mode}", "distortion", "level", {**dist, "Dist_Mode": i / 15})
    for drv in (0.0, 0.25, 0.5, 0.75, 1.0):
        s1(f"s1 dist tube drive {drv:.2f}", "distortion", "level", {**dist, "Dist_Drv": drv})
        s1(f"s1 dist hard drive {drv:.2f}", "distortion", "level", {**dist, "Dist_Mode": 2 / 15, "Dist_Drv": drv})
    for drv in (0.25, 0.5, 0.75, 1.0):
        # quiet input: the shaper is close to linear, so the level change is the drive pre-gain
        s1(f"s1 dist tube pregain {drv:.2f}", "distortion", "level", {**dist, "Dist_Drv": drv, "A Vol": 0.1})
    s1("s1 dist tube pregain off", "distortion", "level", {**dist, "Dist Enable": 0.0, "A Vol": 0.1})
    s1("s1 dist tube wet 0.5", "distortion", "level", {**dist, "Dist_Wet": 0.5})
    s1("s1 dist tube post lp 330", "distortion", "level", {**dist, "Dist_PrePost": 1.0, "Dist_Freq": 0.5, "Dist_L/B/H": 0.0})
    s1("s1 dist tube post hp 330", "distortion", "level", {**dist, "Dist_PrePost": 1.0, "Dist_Freq": 0.5, "Dist_L/B/H": 1.0})

    # ---- Serum 1 compressor: normal vs multiband, threshold, makeup, ratio, wet
    comp = {"Comp Enable": 1.0, "Cmp_Thr": 0.49, "Cmp_Rat": 0.75, "Cmp_Att": 0.3, "Cmp_Rel": 0.3,
            "CmpGain": 0.0, "CmpMBnd": 0.0, "Comp_Wet": 1.0}
    for thr in (0.25, 0.49, 0.61, 0.8):
        s1(f"s1 comp thr {thr:.2f}", "compressor", "level", {**comp, "Cmp_Thr": thr})
        s1(f"s1 comp mb thr {thr:.2f}", "compressor", "level", {**comp, "Cmp_Thr": thr, "CmpMBnd": 1.0})
    for gain in (0.16, 0.39):
        s1(f"s1 comp gain {gain:.2f}", "compressor", "level", {**comp, "CmpGain": gain})
        s1(f"s1 comp mb gain {gain:.2f}", "compressor", "level", {**comp, "CmpGain": gain, "CmpMBnd": 1.0})
    s1("s1 comp ratio 0.39", "compressor", "level", {**comp, "Cmp_Rat": 0.39})
    s1("s1 comp wet 0.5", "compressor", "level", {**comp, "Comp_Wet": 0.5})
    s1("s1 comp mb wet 0.5", "compressor", "level", {**comp, "Comp_Wet": 0.5, "CmpMBnd": 1.0})
    s1("s1 comp loud input", "compressor", "level", {**comp, "A Vol": 1.0, "MasterVol": 1.0})
    s1("s1 comp mb loud input", "compressor", "level", {**comp, "A Vol": 1.0, "MasterVol": 1.0, "CmpMBnd": 1.0})
    s1("s1 comp off loud input", "compressor", "level", {"A Vol": 1.0, "MasterVol": 1.0})

    # ---- Serum 1 Hyper / Dimension
    hyp = {"Hyp Enable": 1.0, "Hyp_Wet": 0.5, "Hyp_Rate": 0.4, "Hyp_Detune": 0.25, "Hyp_Unison": 4 / 7,
           "HypDim_Mix": 0.0, "HypDim_Size": 0.5, "Hyp_Retrig": 0.0}
    for wet in (0.15, 0.5, 1.0):
        s1(f"s1 hyper wet {wet:.2f}", "hyper", "mod", {**hyp, "Hyp_Wet": wet})
    for uni in (1, 2, 4, 7):
        s1(f"s1 hyper unison {uni}", "hyper", "mod", {**hyp, "Hyp_Unison": uni / 7})
    for det in (0.1, 0.32, 0.64, 1.0):
        s1(f"s1 hyper detune {det:.2f}", "hyper", "mod", {**hyp, "Hyp_Detune": det})
    for rate in (0.2, 0.6):
        s1(f"s1 hyper rate {rate:.2f}", "hyper", "mod", {**hyp, "Hyp_Rate": rate})
    for mix in (0.5, 1.0):
        s1(f"s1 dimension mix {mix:.2f}", "hyper", "mod", {**hyp, "Hyp_Wet": 0.0, "HypDim_Mix": mix})
        s1(f"s1 dimension size 0.2 mix {mix:.2f}", "hyper", "mod", {**hyp, "Hyp_Wet": 0.0, "HypDim_Mix": mix, "HypDim_Size": 0.2})
    s1("s1 hyper wet 0.5 dim 0.5", "hyper", "mod", {**hyp, "HypDim_Mix": 0.5})

    # ---- Serum 1 EQ
    eq = {"EQ Enable": 1.0, "EQ TypL": 0.0, "EQ TypH": 0.0, "EQ FrqL": 0.333, "EQ FrqH": 0.666,
          "EQ Q L": 0.6, "EQ Q H": 0.6, "EQ VolL": 0.5, "EQ VolH": 0.5}
    for g in (-12.0, -6.0, 6.0, 12.0):
        s1(f"s1 eq low shelf {g:+.0f}", "eq", "level", {**eq, "EQ VolL": (g + 24) / 48})
        s1(f"s1 eq high shelf {g:+.0f}", "eq", "level", {**eq, "EQ VolH": (g + 24) / 48})
    for q in (0.2, 0.6, 0.9):
        s1(f"s1 eq peak +12 q {q:.1f}", "eq", "level", {**eq, "EQ TypL": 0.5, "EQ FrqL": 0.5, "EQ VolL": 36 / 48, "EQ Q L": q})
    s1("s1 eq peak -12 q 0.6", "eq", "level", {**eq, "EQ TypL": 0.5, "EQ FrqL": 0.5, "EQ VolL": 12 / 48})
    for q in (0.2, 0.6, 0.9):
        s1(f"s1 eq hpf 656 q {q:.1f}", "eq", "level", {**eq, "EQ TypL": 1.0, "EQ FrqL": 0.5, "EQ Q L": q})
    s1("s1 eq lpf 656", "eq", "level", {**eq, "EQ TypH": 1.0, "EQ FrqH": 0.5})

    # ---- Serum 1 chorus
    cho = {"Cho Enable": 1.0, "Cho_Wet": 0.5, "Cho_Rate": 0.25, "Cho_Dly": 0.5, "Cho_Dly2": 0.0, "Cho_Dep": 1.0,
           "Cho_Feed": 0.1, "Cho_Filt": 0.5, "Cho_BPM_Sync": 0.0}
    for dep in (0.29, 0.6, 1.0):
        s1(f"s1 chorus depth {dep:.2f}", "chorus", "mod", {**cho, "Cho_Dep": dep})
    for wet in (0.26, 1.0):
        s1(f"s1 chorus wet {wet:.2f}", "chorus", "mod", {**cho, "Cho_Wet": wet})
    for rate in (0.45, 0.6):
        s1(f"s1 chorus rate {rate:.2f}", "chorus", "mod", {**cho, "Cho_Rate": rate})
    s1("s1 chorus delay 0.1", "chorus", "mod", {**cho, "Cho_Dly": 0.1})
    s1("s1 chorus delay2 0.36", "chorus", "mod", {**cho, "Cho_Dly2": 0.36})
    s1("s1 chorus feed 0.43", "chorus", "mod", {**cho, "Cho_Feed": 0.43})
    s1("s1 chorus filt 1000", "chorus", "mod", {**cho, "Cho_Filt": 0.5, "Cho_Wet": 1.0})

    # ---- Serum 1 phaser / flanger
    phs = {"Phs Enable": 1.0, "Phs_Wet": 1.0, "Phs_Rate": 0.4, "Phs_Dpth": 0.5, "Phs_Frq": 0.5, "Phs_Feed": 0.8,
           "Phs_Stereo": 0.5, "Phs_BPM_Sync": 0.0}
    s1("s1 phaser default", "phaser", "mod", phs)
    s1("s1 phaser wet 0.5", "phaser", "mod", {**phs, "Phs_Wet": 0.5})
    s1("s1 phaser feed 0.3", "phaser", "mod", {**phs, "Phs_Feed": 0.3})
    s1("s1 phaser depth 1.0", "phaser", "mod", {**phs, "Phs_Dpth": 1.0})
    flg = {"Flg Enable": 1.0, "Flg_Wet": 1.0, "Flg_Rate": 0.4, "Flg_Dep": 1.0, "Flg_Feed": 0.5, "Flg_Stereo": 0.5,
           "Flg_BPM_Sync": 0.0}
    s1("s1 flanger default", "flanger", "mod", flg)
    s1("s1 flanger wet 0.5", "flanger", "mod", {**flg, "Flg_Wet": 0.5})
    s1("s1 flanger feed 0.9", "flanger", "mod", {**flg, "Flg_Feed": 0.9})
    s1("s1 flanger depth 0.4", "flanger", "mod", {**flg, "Flg_Dep": 0.4})

    # ---- baselines
    s1("s1 baseline level", "baseline", "level", {})
    s1("s1 baseline tail", "baseline", "tail", {**fast_release})
    s1("s1 baseline mod", "baseline", "mod", {})

    # ---- Serum 2: Batch C of docs/FIXTURE_PRESETS_TASK.md, now crafted instead of GUI-saved
    q = 0.08316586760018929   # stored kParamTime of a 1/4 note in the factory delay presets
    e = 0.03869670710330132   # 1/8
    ratio = q / e
    for k, label in ((-4, "1-64"), (-3, "1-32"), (-2, "1-16"), (-1, "1-8"), (0, "1-4"), (1, "1-2"), (2, "1bar"), (3, "2bar"), (4, "4bar")):
        t = q * ratio ** k
        s2(f"s2 delay sync {label}", "s2delay", "echo",
           [fx("FXDelay", 4, kParamBeatSync=1.0, kParamTimeL=t, kParamTimeR=t, kParamLink=1.0, kParamWet=50.0, kParamFeedback=0.0)],
           seconds=9.0 if k >= 3 else 3.0)
    for off, label in ((1.5, "dotted"), (4.0 / 3.0, "triplet")):
        s2(f"s2 delay sync 1-4 {label}", "s2delay", "echo",
           [fx("FXDelay", 4, kParamBeatSync=1.0, kParamTimeL=q, kParamTimeR=q, kParamOffsetL=off, kParamOffsetR=off,
               kParamLink=1.0, kParamWet=50.0, kParamFeedback=0.0)])
    for fb in (25.0, 50.0, 75.0):
        s2(f"s2 delay feedback {fb:.0f}", "s2delay", "echo",
           [fx("FXDelay", 4, kParamBeatSync=0.0, kParamTimeL=0.25, kParamTimeR=0.25, kParamLink=1.0, kParamWet=50.0, kParamFeedback=fb)])
    for wet in (15.0, 30.0, 100.0):
        s2(f"s2 delay wet {wet:.0f}", "s2delay", "echo",
           [fx("FXDelay", 4, kParamBeatSync=0.0, kParamTimeL=0.25, kParamTimeR=0.25, kParamLink=1.0, kParamWet=wet, kParamFeedback=0.0)])
    s2("s2 delay pingpong", "s2delay", "echo",
       [fx("FXDelay", 4, kParamBeatSync=0.0, kParamTimeL=0.25, kParamTimeR=0.25, kParamLink=1.0, kParamWet=50.0, kParamFeedback=50.0, kParamMode=1.0)])

    # chorus / flanger / phaser synced rate: the knob keeps its Hz value when synced
    for k in range(9):
        hz = 20.0 * (k / 8) ** 4
        s2(f"s2 chorus sync knob {k}-8", "s2rate", "mod",
           [fx("FXChorus", 3, kParamBeatSync=1.0, kParamRate=hz, kParamDepth=20.0, kParamWet=100.0)], seconds=9.0, hold=8.5)
    for hz in (0.25, 1.0, 4.0):
        s2(f"s2 chorus free {hz:.2f} Hz", "s2rate", "mod",
           [fx("FXChorus", 3, kParamBeatSync=0.0, kParamRate=hz, kParamDepth=20.0, kParamWet=100.0)], seconds=5.0, hold=4.5)
    for hz in (0.0, 5.0, 20.0):
        s2(f"s2 phaser sync knob {hz:.0f}", "s2rate", "mod",
           [fx("FXPhaser", 2, kParamBeatSync=1.0, kParamRate=hz, kParamDepth=100.0, kParamWet=100.0)], seconds=9.0, hold=8.5)

    # reverb: kParamDelay identity, types, size, pre-delay
    for kind_name in ("kPlate", "kHall", "kVintage", "kAbyss", "kSpace"):
        for size in (20.0, 50.0, 80.0):
            s2(f"s2 reverb {kind_name[1:].lower()} size {size:.0f}", "s2reverb", "tail",
               [fx("FXReverb", 6, kParamType=kind_name, kParamSize=size, kParamWet=100.0)])
    for d in (100.0, 250.0):
        s2(f"s2 reverb hall delay {d:.0f}", "s2reverb", "tail",
           [fx("FXReverb", 6, kParamType="kHall", kParamSize=50.0, kParamWet=100.0, kParamDelay=d)])
        s2(f"s2 reverb vintage delay {d:.0f}", "s2reverb", "tail",
           [fx("FXReverb", 6, kParamType="kVintage", kParamSize=50.0, kParamWet=100.0, kParamDelay=d)])
    s2("s2 reverb hall predelay 0.2", "s2reverb", "tail",
       [fx("FXReverb", 6, kParamType="kHall", kParamSize=50.0, kParamWet=100.0, kParamPreDelay=0.2)])
    s2("s2 reverb plate predelay 0.2", "s2reverb", "tail",
       [fx("FXReverb", 6, kParamType="kPlate", kParamSize=50.0, kParamWet=100.0, kParamPreDelay=0.2)])
    for wet in (15.0, 30.0, 60.0):
        s2(f"s2 reverb plate wet {wet:.0f}", "s2reverb", "level",
           [fx("FXReverb", 6, kParamType="kPlate", kParamSize=50.0, kParamWet=wet)])
    s2("s2 reverb hall freqb 60", "s2reverb", "tail",
       [fx("FXReverb", 6, kParamType="kHall", kParamSize=50.0, kParamWet=100.0, kParamFreqB=60.0)])
    s2("s2 reverb hall freq 50", "s2reverb", "tail",
       [fx("FXReverb", 6, kParamType="kHall", kParamSize=50.0, kParamWet=100.0, kParamFreq=50.0)])
    s2("s2 reverb hall freqc 80", "s2reverb", "tail",
       [fx("FXReverb", 6, kParamType="kHall", kParamSize=50.0, kParamWet=100.0, kParamFreqC=80.0)])

    # distortion drive law and compressor sanity
    for drv in (0.0, 25.0, 50.0, 75.0, 100.0):
        s2(f"s2 dist tube drive {drv:.0f}", "s2dist", "level", [fx("FXDistortion", 0, kParamMode="kTube", kParamDrive=drv, kParamWet=100.0)])
    s2("s2 dist hard drive 66", "s2dist", "level", [fx("FXDistortion", 0, kParamMode="kHardClip", kParamDrive=66.0, kParamWet=100.0)])
    for thr in (0.25, 0.49, 0.61):
        s2(f"s2 comp thr {thr:.2f}", "s2comp", "level", [fx("FXComp", 5, kParamThresh=thr, kParamRatio=4.0, kParamWet=100.0)])
        s2(f"s2 comp mb thr {thr:.2f}", "s2comp", "level", [fx("FXComp", 5, kParamThresh=thr, kParamRatio=4.0, kParamWet=100.0, kParamMultiband=1.0)])
    s2("s2 comp makeup 2", "s2comp", "level", [fx("FXComp", 5, kParamThresh=0.49, kParamRatio=4.0, kParamWet=100.0, kParamMakeup=2.0)])

    s2("s2 baseline level", "baseline", "level", [])
    s2("s2 baseline tail", "baseline", "tail", [])
    s2("s2 baseline mod", "baseline", "mod", [])


_build_recipes()

def _build_recipes_2() -> None:
    """Second batch (after the first renders): the reverb around its real DECAY
    knob, per-mode distortion drive curves, the multiband compressor."""
    fast_release = {"Env1 Rel": 0.05}
    verb = {"Rev Enable": 1.0, "Verb Wet": 1.0, "VerbSize": 0.35, "VerbDecay": 0.12, **fast_release}
    for d in (0.0, 0.05, 0.12, 0.25, 0.5, 0.75, 1.0):
        s1(f"s1 reverb decay {d:.2f}", "reverb", "tail", {**verb, "VerbDecay": d})
    for size in (0.1, 0.2, 0.35, 0.5, 0.65, 0.8, 1.0):
        s1(f"s1 reverb size2 {size:.2f}", "reverb", "tail", {**verb, "VerbSize": size})
    for size in (0.2, 0.65):
        for d in (0.05, 0.5):
            s1(f"s1 reverb size {size:.2f} decay {d:.2f}", "reverb", "tail", {**verb, "VerbSize": size, "VerbDecay": d})
    for size in (0.2, 0.35, 0.65):
        s1(f"s1 reverb plate2 size {size:.2f}", "reverb", "tail", {**verb, "VerbSize": size}, plate=True)
    s1("s1 reverb plate2 decay 0.50", "reverb", "tail", {**verb, "VerbDecay": 0.5}, plate=True)
    for hi in (0.0, 0.8):
        s1(f"s1 reverb hicut2 {hi:.2f}", "reverb", "tail", {**verb, "VerbHiCt": hi})
    for lo in (0.4, 0.8):
        s1(f"s1 reverb locut2 {lo:.2f}", "reverb", "tail", {**verb, "VerbLoCt": lo})
    s1("s1 reverb spin depth 0", "reverb", "tail", {**verb, "VerbSpinDepth": 0.0})
    s1("s1 reverb spin depth 1", "reverb", "tail", {**verb, "VerbSpinDepth": 1.0})
    s1("s1 reverb spin rate 1 depth 1", "reverb", "tail", {**verb, "VerbSpinDepth": 1.0, "VerbSpinRate": 1.0})
    for wet in (0.17, 0.33, 0.5, 0.75, 1.0):
        s1(f"s1 reverb wet2 {wet:.2f}", "reverb", "level", {"Rev Enable": 1.0, "Verb Wet": wet, "VerbSize": 0.35, "VerbDecay": 0.12})

    dist = {"Dist Enable": 1.0, "Dist_Wet": 1.0, "Dist_Drv": 0.66, "Dist_Mode": 0.0, "Dist_PrePost": 0.0}
    modes = ["Tube", "SoftClip", "HardClip", "Diode 1", "Diode 2", "Lin.Fold", "Sin Fold", "Zero-Square",
             "Downsample", "Asym", "Rectify", "X-Shaper", "X-Shaper (Asym)", "Sine Shaper", "Stomp Box", "Tape Sat."]
    for i, mode in enumerate(modes):
        for drv in (0.0, 0.25, 0.5, 0.75, 1.0):
            s1(f"s1 dist mode {i:02d} {mode} drive {drv:.2f}", "dist2", "level", {**dist, "Dist_Mode": i / 15, "Dist_Drv": drv})
    for wet in (0.25, 0.75):
        s1(f"s1 dist tube wet {wet:.2f}", "dist2", "level", {**dist, "Dist_Wet": wet})
    for drv in (0.0, 0.25, 0.5, 0.75, 0.9, 1.0):
        s1(f"s1 dist hard quiet drive {drv:.2f}", "dist2", "level", {**dist, "Dist_Mode": 2 / 15, "Dist_Drv": drv, "A Vol": 0.03})
        s1(f"s1 dist tube quiet drive {drv:.2f}", "dist2", "level", {**dist, "Dist_Drv": drv, "A Vol": 0.03})
    s1("s1 dist off quiet", "dist2", "level", {"A Vol": 0.03})


    # distortion on a loud input (-3 dBFS saw): do the drive tables hold when the shaper is driven hard?
    loud = {"A Vol": 1.0, "MasterVol": 1.0}
    for i, mode in ((0, "Tube"), (2, "HardClip"), (3, "Diode 1"), (14, "Stomp Box"), (15, "Tape Sat.")):
        for drv in (0.25, 0.66, 1.0):
            s1(f"s1 dist loud {mode} drive {drv:.2f}", "dist3", "level", {**dist, **loud, "Dist_Mode": i / 15, "Dist_Drv": drv})
    s1("s1 dist loud off", "dist3", "level", {**loud})


    # multiband compressor at other ratios (the library uses 1:1 and 1.2:1 there too)
    mb = {"Comp Enable": 1.0, "Cmp_Thr": 0.49, "Cmp_Rat": 0.75, "Cmp_Att": 0.3, "Cmp_Rel": 0.3,
          "CmpGain": 0.0, "CmpMBnd": 1.0, "Comp_Wet": 1.0}
    for thr in (0.49, 0.81):
        for ratio in (0.0, 0.16, 0.39):
            s1(f"s1 comp mb ratio {ratio:.2f} thr {thr:.2f}", "comp3", "level", {**mb, "Cmp_Rat": ratio, "Cmp_Thr": thr})
        s1(f"s1 comp sb ratio 0.16 thr {thr:.2f}", "comp3", "level", {**mb, "Cmp_Rat": 0.16, "Cmp_Thr": thr, "CmpMBnd": 0.0})
    s1("s1 comp mb ratio 0.00 thr 0.49 wet 0.5", "comp3", "level", {**mb, "Cmp_Rat": 0.0, "Comp_Wet": 0.5})

    comp = {"Comp Enable": 1.0, "Cmp_Thr": 0.49, "Cmp_Rat": 0.75, "Cmp_Att": 0.3, "Cmp_Rel": 0.3,
            "CmpGain": 0.0, "CmpMBnd": 1.0, "Comp_Wet": 1.0}
    s1("s1 comp mb thr 0.00", "comp2", "level", {**comp, "Cmp_Thr": 0.0})
    s1("s1 comp mb thr 0.10", "comp2", "level", {**comp, "Cmp_Thr": 0.1})
    for l, m, h in ((0.0, 0.5, 0.5), (1.0, 0.5, 0.5), (0.5, 0.0, 0.5), (0.5, 1.0, 0.5), (0.5, 0.5, 0.0), (0.5, 0.5, 1.0)):
        s1(f"s1 comp mb bands {l:.1f} {m:.1f} {h:.1f}", "comp2", "level", {**comp, "CompMB L": l, "CompMB M": m, "CompMB H": h})
    s1("s1 comp mb quiet input", "comp2", "level", {**comp, "A Vol": 0.3})
    s1("s1 comp quiet input", "comp2", "level", {**comp, "CmpMBnd": 0.0, "A Vol": 0.3})
    s1("s1 comp off quiet input", "comp2", "level", {"A Vol": 0.3})
    s1("s1 comp mb thr 0.00 loud", "comp2", "level", {**comp, "Cmp_Thr": 0.0, "A Vol": 1.0, "MasterVol": 1.0})

    # Serum 2: the synced delay ladder (stored seconds -> division), fine sweep
    for t in (0.001, 0.002, 0.004, 0.006, 0.01, 0.015, 0.02, 0.03, 0.045, 0.06, 0.1, 0.12, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.7, 1.0):
        s2(f"s2 delay sync t {t:.3f}", "s2delay2", "echo",
           [fx("FXDelay", 4, kParamBeatSync=1.0, kParamTimeL=t, kParamTimeR=t, kParamLink=1.0, kParamWet=50.0, kParamFeedback=0.0)],
           seconds=9.0)


    # finer sweep around the division boundaries found by s2delay2
    for t in (0.008, 0.012, 0.016, 0.018, 0.022, 0.026, 0.033, 0.036, 0.04, 0.07, 0.08, 0.09, 0.105, 0.115, 0.16, 0.18, 0.19, 0.26, 0.28, 0.42, 0.47):
        s2(f"s2 delay sync t {t:.3f}", "s2delay3", "echo",
           [fx("FXDelay", 4, kParamBeatSync=1.0, kParamTimeL=t, kParamTimeR=t, kParamLink=1.0, kParamWet=50.0, kParamFeedback=0.0)],
           seconds=9.0)

    # Serum 2 reverb types: RT60 over (size, kParamDelay) with the library's median settings per type
    hall = dict(kParamType="kHall", kParamWet=100.0, kParamFreqB=35.0)
    for size in (20.0, 50.0, 80.0):
        for d in (30.0, 60.0, 150.0):
            s2(f"s2 reverb hall size {size:.0f} delay {d:.0f}", "s2reverb2", "tail", [fx("FXReverb", 6, **hall, kParamSize=size, kParamDelay=d)])
    for fb in (28.0, 60.0):
        s2(f"s2 reverb hall feedback {fb:.0f}", "s2reverb2", "tail", [fx("FXReverb", 6, **hall, kParamSize=50.0, kParamDelay=36.0, kParamFeedback=fb)])
    for size in (10.0, 35.0, 65.0, 100.0):
        s2(f"s2 reverb plate size2 {size:.0f}", "s2reverb2", "tail", [fx("FXReverb", 6, kParamType="kPlate", kParamWet=100.0, kParamSize=size)])
    for fb in (47.0, 90.0):
        s2(f"s2 reverb plate feedback {fb:.0f}", "s2reverb2", "tail", [fx("FXReverb", 6, kParamType="kPlate", kParamWet=100.0, kParamSize=30.0, kParamFeedback=fb)])
    vintage = dict(kParamType="kVintage", kParamWet=100.0, kParamMode=50.0, kParamVintageScale=50.0, kParamVintageScaleB=55.0,
                   kParamFeedback=18.0, kParamFreq=42.0, kParamFreqB=36.0, kParamFreqC=47.0)
    for size in (20.0, 45.0, 80.0):
        for d in (12.0, 72.0, 200.0):
            s2(f"s2 reverb vintage size {size:.0f} delay {d:.0f}", "s2reverb2", "tail", [fx("FXReverb", 6, **vintage, kParamSize=size, kParamDelay=d)])
    abyss = dict(kParamType="kAbyss", kParamWet=100.0, kParamMode=50.0, kParamFeedback=17.5, kParamFreq=32.0, kParamFreqB=34.0, kParamFreqC=54.0)
    for size in (15.0, 34.0, 65.0):
        for d in (0.0, 30.0, 100.0):
            s2(f"s2 reverb abyss size {size:.0f} delay {d:.0f}", "s2reverb2", "tail", [fx("FXReverb", 6, **abyss, kParamSize=size, kParamDelay=d)])
    space = dict(kParamType="kSpace", kParamWet=100.0, kParamMode=47.5, kParamVintageScale=70.0, kParamVintageScaleB=70.0,
                 kParamFeedback=13.0, kParamFreq=70.0, kParamFreqB=42.0, kParamFreqC=24.0)
    for size in (10.0, 24.0, 50.0):
        for d in (0.0, 11.0, 100.0):
            s2(f"s2 reverb space size {size:.0f} delay {d:.0f}", "s2reverb2", "tail", [fx("FXReverb", 6, **space, kParamSize=size, kParamDelay=d)])


_build_recipes_2()


def render_shape(fixture: dict) -> tuple[int, float, float]:
    note, hold, seconds = KINDS[fixture["kind"]]
    return fixture.get("note", note), fixture.get("hold", hold), fixture.get("seconds", seconds)


def fixture_path(fixture: dict) -> Path:
    if fixture["engine"] == "serum1":
        return CRAFTED / "serum1" / f"{fixture['name']}.fxp"
    return CRAFTED / "serum2" / f"{fixture['name']}.SerumPreset"


def selected(groups: list[str] | None, match: str | None = None) -> list[dict]:
    import re

    out = []
    for f in FIXTURES:
        if groups and f["group"] not in groups and f["group"] != "baseline":
            continue
        if match and not re.search(match, f["name"], re.I):
            continue
        out.append(f)
    return out


# --------------------------------------------------------------------------- #
# crafting
# --------------------------------------------------------------------------- #
def craft_serum1(fixture: dict) -> Path:
    from craft_fxp import f32, write
    from serum2vital.serum1 import OFF_REVERB_HALL, SETTINGS_BASES, decompress
    from serum2vital.serum_params import NAME_TO_INDEX

    def offset(name: str) -> int:
        i = NAME_TO_INDEX[name]
        return 0x3460 + 4 * i if i < 228 else 0x4AE0 + 4 * (i - 228)

    edits = [(offset(k), f32(v)) for k, v in {**S1_BASE, **fixture["changes"]}.items()]
    if fixture.get("plate"):
        # Plate/Hall lives in the switch block (+0x5C) and its per-effect mirror byte.
        blob = decompress(str(INIT_S1))
        base = next(b for b in SETTINGS_BASES if b + 0x60 <= len(blob))
        edits.append((base + 0x5C, bytes([0])))
        edits.append((OFF_REVERB_HALL, bytes([0])))
    dst = fixture_path(fixture)
    dst.parent.mkdir(parents=True, exist_ok=True)
    write(INIT_S1, dst, edits)
    return dst


def craft_serum2(fixture: dict) -> Path:
    from serum2_host import build_xfer, parse_xfer

    meta, doc = parse_xfer(INIT_S2.read_bytes())
    doc = copy.deepcopy(doc)
    doc["FXRack0"] = {"FX": copy.deepcopy(fixture["modules"]), "displayName": "", "plainParams": "default"}
    if fixture.get("env"):
        env = doc.setdefault("Env0", {})
        params = env.get("plainParams")
        env["plainParams"] = {**(params if isinstance(params, dict) else {}), **fixture["env"]}
    meta = dict(meta, presetName=fixture["name"], presetDescription="serum2vital effect fixture (crafted)")
    dst = fixture_path(fixture)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(build_xfer(meta, doc))
    return dst


def craft_all(fixtures: list[dict]) -> None:
    for f in fixtures:
        path = craft_serum1(f) if f["engine"] == "serum1" else craft_serum2(f)
        print("wrote", path.relative_to(ROOT))
    manifest = [{k: v for k, v in f.items()} for f in fixtures]
    (CRAFTED / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #
def _db(x: float) -> float:
    return float(20 * np.log10(max(x, 1e-9)))


def _env_db(mono: np.ndarray, win: int) -> np.ndarray:
    n = len(mono) // win
    return 20 * np.log10(np.sqrt((mono[: n * win].reshape(n, win) ** 2).mean(axis=1)) + 1e-9)


def octave_bands(mono: np.ndarray) -> list[float]:
    spec = np.abs(np.fft.rfft(mono * np.hanning(len(mono)))) ** 2
    freqs = np.fft.rfftfreq(len(mono), 1 / SR)
    out = []
    for lo in (31.25, 62.5, 125, 250, 500, 1000, 2000, 4000, 8000):
        sel = (freqs >= lo) & (freqs < 2 * lo)
        out.append(round(10 * np.log10(spec[sel].sum() + 1e-12), 1))
    return out


def centroid(mono: np.ndarray) -> float:
    spec = np.abs(np.fft.rfft(mono * np.hanning(len(mono))))
    freqs = np.fft.rfftfreq(len(mono), 1 / SR)
    return float((spec * freqs).sum() / max(spec.sum(), 1e-9))


def mod_rate(mono: np.ndarray, start: float, end: float) -> tuple[float, float]:
    """(modulation rate Hz, flux depth) from spectral-flux periodicity."""
    seg = mono[int(start * SR): int(end * SR)]
    win, hop = 2048, 256
    frames = [np.abs(np.fft.rfft(seg[i: i + win] * np.hanning(win))) for i in range(0, len(seg) - win, hop)]
    if len(frames) < 32:
        return 0.0, 0.0
    spec = np.log(np.array(frames) + 1e-6)
    flux = np.abs(np.diff(spec, axis=0)).mean(axis=1)
    flux = flux - flux.mean()
    ac = np.correlate(flux, flux, "full")[len(flux) - 1:]
    ac /= max(ac[0], 1e-12)
    fps = SR / hop
    lo = int(fps / 30)
    peaks = [i for i in range(max(lo, 2), len(ac) - 1) if ac[i] > ac[i - 1] and ac[i] >= ac[i + 1] and ac[i] > 0.15]
    rate = fps / peaks[0] if peaks else 0.0
    depth = float(np.std(np.abs(np.diff(spec, axis=0)).mean(axis=1)))
    return round(rate, 3), round(depth, 4)


def analyse(audio: np.ndarray, kind: str, hold: float) -> dict:
    x = np.atleast_2d(np.asarray(audio, dtype=np.float64))
    mono = x.mean(axis=0)
    corr = float(np.corrcoef(x[0], x[1])[0, 1]) if x.shape[0] > 1 and x[0].std() > 0 and x[1].std() > 0 else 1.0
    m: dict = {"peak": round(float(np.abs(x).max()), 4), "corr": round(corr, 3)}
    if kind in ("level", "mod"):
        a, b = int(0.5 * SR), int(min(hold, 1.5) * SR)
        mid = mono[a:b]
        m["rms_db"] = round(_db(np.sqrt(np.mean(mid ** 2))), 2)
        m["centroid"] = round(centroid(mid))
        m["bands"] = octave_bands(mid)
        m["crest_db"] = round(_db(np.abs(mid).max()) - m["rms_db"], 2)
        side = (x[0] - x[1]) / 2 if x.shape[0] > 1 else np.zeros_like(mono)
        m["side_db"] = round(_db(np.sqrt(np.mean(side[a:b] ** 2))) - m["rms_db"], 2)
        if kind == "mod":
            m["mod_hz"], m["flux"] = mod_rate(mono, 0.3, hold)
    else:
        win = int(0.005 * SR)
        env = _env_db(mono, win)
        t = np.arange(len(env)) * win / SR
        floor = max(float(np.percentile(env, 5)), -100.0)
        m["dry_db"] = round(float(env[t < hold + 0.01].max()), 2)
        after = t > hold + 0.012
        tail = env[after]
        tt = t[after]
        m["tail_peak_db"] = round(float(tail.max()), 2) if tail.size else -100.0
        # onset: first window after the dry that rises 6 dB over the local minimum before it
        onset = None
        run_min = tail[0] if tail.size else 0
        for i in range(1, len(tail)):
            run_min = min(run_min, tail[i - 1])
            if tail[i] > run_min + 6.0 and tail[i] > floor + 12.0:
                onset = float(tt[i])
                break
        m["onset_s"] = round(onset, 3) if onset is not None else None
        for at in (0.2, 0.5, 1.0, 2.0, 4.0):
            idx = int(at * SR / win)
            m[f"at_{at:.1f}s_db"] = round(float(env[idx]), 1) if idx < len(env) else None
        if kind == "tail":
            # RT60 from a straight line through the decaying part of the tail
            start = max((onset or hold) + 0.15, 0.25)
            sel = (t >= start) & (env > floor + 8.0)
            if sel.sum() > 20:
                slope, _ = np.polyfit(t[sel], env[sel], 1)
                m["rt60_s"] = round(-60.0 / slope, 2) if slope < -0.5 else None
            else:
                m["rt60_s"] = None
            a, b = int(0.3 * SR), int(0.8 * SR)
            seg = mono[a:b]
            m["tail_centroid"] = round(centroid(seg)) if np.abs(seg).max() > 1e-4 else None
            m["tail_bands"] = octave_bands(seg) if np.abs(seg).max() > 1e-4 else None
            tail_x = x[:, a:b]
            m["tail_corr"] = round(float(np.corrcoef(tail_x[0], tail_x[1])[0, 1]), 3) if x.shape[0] > 1 and tail_x[0].std() > 0 else 1.0
        else:
            # echoes: local maxima of the envelope after the dry blip, 20 ms apart
            peaks = []
            i = int((hold + 0.015) / (win / SR))
            while i < len(env) - 1 and len(peaks) < 8:
                if env[i] >= env[i - 1] and env[i] > env[i + 1] and env[i] > floor + 15.0 and env[i] == env[max(0, i - 4): i + 5].max():
                    peaks.append((round(float(t[i]), 3), round(float(env[i]), 1)))
                    i += 4
                i += 1
            m["echoes"] = peaks
            if x.shape[0] > 1:
                lr = []
                for ch in range(2):
                    e = _env_db(x[ch], win)
                    lr.append([round(float(e[int(p * SR / win)]), 1) for p, _ in peaks[:4]])
                m["echo_lr_db"] = lr
    return m


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
SERUM_CHILD = r'''
import json, os, sys
sys.path.insert(0, %(tools)r); sys.path.insert(0, %(root)r)
import numpy as np
from %(module)s import %(cls)s as Host, write_wav
from fx_fixtures import analyse
jobs = json.load(open(sys.argv[1], encoding="utf-8"))
host = Host(sample_rate=%(sr)d).load()
try:
    host.engine.set_bpm(120.0)
except Exception:
    pass
results = {}
for name, preset, wav, kind, note, hold, seconds in jobs:
    try:
        if hasattr(host, "reset"):
            host.reset()
        else:
            host.load_preset(%(init)r)
        host.load_preset(preset)
        audio = host.render([(note, 100, 0.0, hold)], seconds)
        write_wav(wav, audio, %(sr)d)
        results[name] = analyse(audio, kind, hold)
        print("ok", name, flush=True)
    except Exception as exc:
        results[name] = {"error": str(exc)}
        print("fail", name, exc, flush=True)
json.dump(results, open(sys.argv[2], "w", encoding="utf-8"), indent=1)
sys.stdout.flush()
os._exit(0)
'''


def render_serum(fixtures: list[dict]) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    results: dict = {}
    hosts = {"serum1": ("serum_host", "SerumHost"), "serum2": ("serum2_host", "Serum2Host")}
    for engine, (module, cls) in hosts.items():
        jobs = []
        for f in fixtures:
            if f["engine"] != engine:
                continue
            note, hold, seconds = render_shape(f)
            jobs.append([f["name"], str(fixture_path(f)), str(OUT / f"{f['name']} - serum.wav"), f["kind"], note, hold, seconds])
        if not jobs:
            continue
        job_file = OUT / f"_jobs_{engine}.json"
        res_file = OUT / f"_results_{engine}.json"
        job_file.write_text(json.dumps(jobs), encoding="utf-8")
        script = SERUM_CHILD % {"tools": str(TOOLS), "root": str(ROOT), "module": module, "cls": cls, "sr": SR, "init": str(INIT_S1)}
        proc = subprocess.run([sys.executable, "-c", script, str(job_file), str(res_file)], capture_output=True, text=True,
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        print(proc.stdout)
        if not res_file.exists():
            raise RuntimeError(f"{engine} render produced no results:\n{proc.stderr[-2000:]}")
        results.update(json.loads(res_file.read_text(encoding="utf-8")))
    return results


def render_vital(fixtures: list[dict]) -> dict:
    from serum2vital import convert, writer
    from vital_host import VitalHost, write_wav

    OUT.mkdir(parents=True, exist_ok=True)
    host = VitalHost().load()
    options = convert.Options(serum_root=SERUM_ROOT, max_frames=16)
    cache: dict = {}
    results = {}
    for f in fixtures:
        note, hold, seconds = render_shape(f)
        try:
            conv = convert.convert_file(fixture_path(f), options, cache)
            host.set_preset(writer.build(conv))
            audio = host.render([(note, 100, 0.0, hold)], seconds, SR)
            write_wav(OUT / f"{f['name']} - vital.wav", audio, SR)
            results[f["name"]] = analyse(audio, f["kind"], hold)
            results[f["name"]]["notes"] = [n for n in conv.notes if not n.startswith("approximation: preset predates")]
            print("ok", f["name"], flush=True)
        except Exception as exc:
            results[f["name"]] = {"error": str(exc)}
            print("fail", f["name"], exc, flush=True)
    return results


def _merge(path: Path, new: dict) -> None:
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    old.update(new)
    path.write_text(json.dumps(old, indent=1), encoding="utf-8")


# --------------------------------------------------------------------------- #
# compare
# --------------------------------------------------------------------------- #
KEYS = {
    "level": ["rms_db", "centroid", "crest_db", "side_db", "corr", "bands"],
    "mod": ["rms_db", "centroid", "side_db", "corr", "mod_hz", "flux"],
    "tail": ["dry_db", "tail_peak_db", "onset_s", "rt60_s", "at_0.5s_db", "at_1.0s_db", "at_2.0s_db", "tail_centroid", "tail_corr"],
    "echo": ["dry_db", "onset_s", "echoes", "echo_lr_db", "corr"],
}


def compare(fixtures: list[dict]) -> str:
    serum = json.loads((OUT / "serum.json").read_text(encoding="utf-8")) if (OUT / "serum.json").exists() else {}
    vital = json.loads((OUT / "vital.json").read_text(encoding="utf-8")) if (OUT / "vital.json").exists() else {}
    lines = []
    for f in fixtures:
        s, v = serum.get(f["name"]), vital.get(f["name"])
        lines.append(f"\n## {f['name']}  [{f['kind']}]")
        for key in KEYS[f["kind"]]:
            sv = s.get(key) if s else None
            vv = v.get(key) if v else None
            delta = ""
            if isinstance(sv, (int, float)) and isinstance(vv, (int, float)):
                delta = f"  d={vv - sv:+.2f}"
            lines.append(f"  {key:14s} serum={sv!s:<40} vital={vv!s:<40}{delta}")
        if v and v.get("notes"):
            lines.append("  notes: " + " | ".join(v["notes"]))
    text = "\n".join(lines)
    (OUT / "compare.md").write_text(text, encoding="utf-8")
    return text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["craft", "serum", "vital", "compare", "list"])
    ap.add_argument("--group", nargs="*", help="fixture groups (reverb, delay, distortion, compressor, hyper, eq, chorus, phaser, flanger, s2delay, s2rate, s2reverb, s2dist, s2comp)")
    ap.add_argument("--match", help="regex on fixture names")
    args = ap.parse_args(argv)

    fixtures = selected(args.group, args.match)
    if args.command == "list":
        for f in fixtures:
            print(f["engine"], f["group"], f["kind"], f["name"])
        print(len(fixtures), "fixtures")
    elif args.command == "craft":
        craft_all(fixtures)
    elif args.command == "serum":
        _merge(OUT / "serum.json", render_serum(fixtures))
    elif args.command == "vital":
        _merge(OUT / "vital.json", render_vital(fixtures))
    else:
        print(compare(fixtures))
    return 0


if __name__ == "__main__":
    sys.exit(main())
