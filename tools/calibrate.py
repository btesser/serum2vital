"""Calibration sweeps: the same parameter experiments through Serum and through
the converter into Vital, compared on level and spectral centroid.

    python tools/calibrate.py serum  results_serum.json     (run in its own process)
    python tools/calibrate.py vital  results_vital.json
    python tools/calibrate.py compare results_serum.json results_vital.json

Each experiment starts from DebugPresets/serum1/00 init.fxp with all effects
off and applies a few Serum parameter values.  The Serum run sets them on the
plugin; the Vital run sets them on the parsed patch and pushes it through the
real mapping, so what is measured is the converter's output.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

INIT = ROOT / "DebugPresets" / "serum1" / "00 init.fxp"
SERUM_ROOT = os.environ.get("SERUM_ROOT", "D:/VSTData/serum")

BASE = {
    "Osc A On": 1.0, "Osc B On": 0.0, "Osc N On": 0.0, "Osc S On": 0.0, "Filter On": 0.0,
    "A Vol": 0.75, "MasterVol": 0.7, "A Unison": 0.0, "WarpOscA": 0.0, "A Warp": 0.0,
    "Env1 Atk": 0.0, "Env1 Dec": 0.5, "Env1 Sus": 1.0, "Env1 Rel": 0.1,
    "Dist Enable": 0.0, "Flg Enable": 0.0, "Phs Enable": 0.0, "Cho Enable": 0.0, "Dly Enable": 0.0,
    "Comp Enable": 0.0, "Rev Enable": 0.0, "EQ Enable": 0.0, "FX Fil Enable": 0.0, "Hyp Enable": 0.0,
    "A WTPos": 0.0,
}


def experiments():
    ex = [("baseline", {})]
    ex += [(f"avol {v}", {"A Vol": v}) for v in (0.25, 0.5, 1.0)]
    ex += [(f"master {v}", {"MasterVol": v}) for v in (0.5, 1.0)]
    ex += [(f"fm {v}", {"Osc B On": 1.0, "B Vol": 0.0, "WarpOscA": 18 / 23, "A Warp": v}) for v in (0.1, 0.25, 0.5, 0.75, 1.0)]
    ex += [(f"sync {v}", {"WarpOscA": 1 / 23, "A Warp": v}) for v in (0.25, 0.5, 0.75, 1.0)]
    ex += [(f"bend+ {v}", {"WarpOscA": 4 / 23, "A Warp": v}) for v in (0.5, 1.0)]
    ex += [(f"pwm {v}", {"WarpOscA": 7 / 23, "A Warp": v}) for v in (0.5, 0.9)]
    filt = {"Filter On": 1.0, "Fil Type": 1 / 95, "Fil Cutoff": 0.5, "Fil Reso": 0.1, "Fil Driv": 0.0}
    ex += [("filter mg12 c0.5", filt)]
    ex += [(f"filter drive {v}", {**filt, "Fil Driv": v}) for v in (0.25, 0.5, 0.75, 1.0)]
    ex += [(f"filter reso {v}", {**filt, "Fil Reso": v}) for v in (0.4, 0.7, 0.95)]
    ex += [(f"filter cutoff {v}", {**filt, "Fil Cutoff": v}) for v in (0.3, 0.7)]
    ex += [("filter svf low12", {**filt, "Fil Type": 5 / 95})]
    ex += [("filter high12", {**filt, "Fil Type": 9 / 95})]
    dist = {"Dist Enable": 1.0, "Dist_Mode": 0.0, "Dist_Wet": 1.0}
    ex += [(f"dist tube {v}", {**dist, "Dist_Drv": v}) for v in (0.0, 0.25, 0.5, 1.0)]
    ex += [(f"dist hardclip {v}", {**dist, "Dist_Mode": 2 / 15, "Dist_Drv": v}) for v in (0.25, 0.75)]
    ex += [("comp default", {"Comp Enable": 1.0, "Cmp_Thr": 0.5, "Cmp_Rat": 0.75, "Cmp_Att": 0.3, "Cmp_Rel": 0.3, "CmpGain": 0.0, "Comp_Wet": 1.0})]
    ex += [("comp thr0.8", {"Comp Enable": 1.0, "Cmp_Thr": 0.8, "Cmp_Rat": 0.75, "CmpGain": 0.0, "Comp_Wet": 1.0})]
    ex += [(f"unison {n} det {d}", {"A Unison": n / 16, "A UniDet": d}) for n, d in ((4, 0.25), (4, 0.5), (7, 0.5))]
    ex += [("hyper default", {"Hyp Enable": 1.0, "Hyp_Wet": 0.5, "Hyp_Rate": 0.4, "Hyp_Detune": 0.25, "Hyp_Unison": 4 / 7, "HypDim_Mix": 0.0})]
    ex += [("chorus default", {"Cho Enable": 1.0, "Cho_Wet": 0.5})]
    ex += [("reverb default", {"Rev Enable": 1.0, "Verb Wet": 0.33, "VerbSize": 0.33})]
    ex += [("delay default", {"Dly Enable": 1.0, "Dly_Wet": 0.3, "Dly_Feed": 0.4, "Dly_BPM_Sync": 1.0, "Dly_TimL": 0.625, "Dly_TimR": 0.625})]
    ex += [("eq low+8", {"EQ Enable": 1.0, "EQ TypL": 0.0, "EQ FrqL": 0.333, "EQ VolL": (8 + 24) / 48.0})]
    ex += [("eq high-8", {"EQ Enable": 1.0, "EQ TypH": 0.0, "EQ FrqH": 0.666, "EQ VolH": (-8 + 24) / 48.0})]
    ex += [("eq low hpf", {"EQ Enable": 1.0, "EQ TypL": 1.0, "EQ FrqL": 0.5})]
    ex += [("sub on", {"Osc S On": 1.0, "Sub Osc Level": 0.75, "A Vol": 0.0})]
    ex += [("noise on", {"Osc N On": 1.0, "Noise Level": 0.75, "A Vol": 0.0})]
    return ex


def metrics(audio: np.ndarray, sr: int = 44100) -> dict:
    x = np.asarray(audio, dtype=np.float64)
    mono = x.mean(axis=0) if x.ndim == 2 else x
    mid = mono[int(0.5 * sr):int(1.5 * sr)]
    rms = 20 * np.log10(max(1e-9, float(np.sqrt(np.mean(mid ** 2)))))
    spec = np.abs(np.fft.rfft(mid * np.hanning(len(mid))))
    freqs = np.fft.rfftfreq(len(mid), 1 / sr)
    cent = float((spec * freqs).sum() / max(spec.sum(), 1e-9)) if rms > -70 else float("nan")
    return {"rms_db": round(rms, 2), "centroid": round(cent, 1), "peak": round(float(np.abs(x).max()), 4)}


def run_serum(out: str) -> None:
    from serum_host import SerumHost

    host = SerumHost()
    host.load()
    results = {}
    for label, changes in experiments():
        host.load_preset(str(INIT))
        for k, v in {**BASE, **changes}.items():
            host.set(k, v)
        results[label] = metrics(host.render([(48, 100, 0.0, 1.5)], 2.0))
        print(label, results[label], flush=True)
    Path(out).write_text(json.dumps(results, indent=1))
    sys.stdout.flush()
    os._exit(0)


def run_vital(out: str) -> None:
    from serum2vital import serum1, convert, writer
    from serum2vital.mapping import convert_serum1
    from serum2vital.serum_params import NAME_TO_INDEX
    from vital_host import VitalHost

    host = VitalHost()
    host.load()
    options = convert.Options(serum_root=Path(SERUM_ROOT), max_frames=16)
    cache: dict = {}
    results = {}
    for label, changes in experiments():
        patch = serum1.read(str(INIT))
        for k, v in {**BASE, **changes}.items():
            patch.params[NAME_TO_INDEX[k]] = float(v)
        conv = convert_serum1(patch)
        convert._attach_assets(conv, options, cache)
        host.set_preset(writer.build(conv))
        results[label] = metrics(host.render([(48, 100, 0.0, 1.5)], 2.0))
        print(label, results[label], flush=True)
    Path(out).write_text(json.dumps(results, indent=1))
    sys.stdout.flush()
    os._exit(0)


def compare(serum_file: str, vital_file: str) -> None:
    s = json.loads(Path(serum_file).read_text())
    v = json.loads(Path(vital_file).read_text())
    base_s, base_v = s["baseline"]["rms_db"], v["baseline"]["rms_db"]
    print(f"{'experiment':24s} {'serum dB':>9s} {'vital dB':>9s} {'d(dB)':>7s} {'rel d':>7s} {'serum Hz':>9s} {'vital Hz':>9s}")
    for label in s:
        if label not in v:
            continue
        a, b = s[label], v[label]
        d = b["rms_db"] - a["rms_db"]
        rel = (b["rms_db"] - base_v) - (a["rms_db"] - base_s)
        print(f"{label:24s} {a['rms_db']:9.1f} {b['rms_db']:9.1f} {d:7.1f} {rel:7.1f} {a['centroid']:9.0f} {b['centroid']:9.0f}")


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "serum":
        run_serum(sys.argv[2])
    elif mode == "vital":
        run_vital(sys.argv[2])
    else:
        compare(sys.argv[2], sys.argv[3])
