"""A/B render a Serum .fxp against a Vital .vital and print simple audio metrics.

Both hosts render MIDI note 48 for 2 s (note held for 1.5 s).  Serum runs in a
subprocess via tools/serum_host.py (DawDreamer crashes at interpreter exit);
Vital runs in-process via tools/vital_host.py.  For each render we print peak,
RMS (dBFS), spectral centroid (Hz) of the middle second, and L/R correlation.

    python tools/ab_render.py "preset.fxp" "preset.vital"
    python tools/ab_render.py serum_folder vital_folder      # pairs by stem
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

TOOLS = Path(__file__).resolve().parent
NOTE, SECONDS, HOLD, SR = 48, 2.0, 1.5, 44100


def metrics(audio: np.ndarray, sr: int = SR) -> dict:
    """audio: (channels, samples) float array.

    centroid is measured on the DC-removed middle second (0.5-1.5 s) and
    reported as NaN when that window is below -60 dBFS (silence would otherwise
    give a meaningless number).
    """
    audio = np.atleast_2d(np.asarray(audio, dtype=np.float64))
    mono = audio.mean(axis=0)
    peak = float(np.abs(audio).max()) if audio.size else 0.0
    rms_db = _db(np.sqrt(np.mean(mono ** 2))) if mono.size else float("-inf")

    mid = mono[int(0.5 * sr):int(1.5 * sr)]
    mid = mid - mid.mean() if mid.size else mid
    mid_db = _db(np.sqrt(np.mean(mid ** 2))) if mid.size else float("-inf")
    if mid.size and mid_db > -60:
        spec = np.abs(np.fft.rfft(mid * np.hanning(mid.size)))
        freqs = np.fft.rfftfreq(mid.size, 1.0 / sr)
        centroid = float((spec * freqs).sum() / spec.sum())
    else:
        centroid = float("nan")

    if audio.shape[0] >= 2 and np.std(audio[0]) > 0 and np.std(audio[1]) > 0:
        corr = float(np.corrcoef(audio[0], audio[1])[0, 1])
    else:
        corr = 1.0
    return {"peak": peak, "rms_db": rms_db, "mid_rms_db": mid_db, "centroid_hz": centroid, "stereo_corr": corr}


def _db(x: float) -> float:
    return float(20 * np.log10(x)) if x > 0 else float("-inf")


def render_serum(fxp: Path) -> np.ndarray:
    import soundfile as sf

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "serum.wav"
        cmd = [sys.executable, str(TOOLS / "serum_host.py"), str(fxp), "--params", "A Vol",
               "--render", str(wav), "--note", str(NOTE), "--seconds", str(SECONDS), "--sample-rate", str(SR)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not wav.exists():
            raise RuntimeError(f"serum_host failed (exit {proc.returncode}):\n{proc.stdout}\n{proc.stderr}")
        data, _ = sf.read(str(wav), dtype="float32")
    return data.T if data.ndim == 2 else data[None, :]


def render_vital(vital: Path, host) -> np.ndarray:
    host.load_file(vital)
    return host.render([(NOTE, 100, 0.0, HOLD)], SECONDS, SR)


def fmt(m: dict) -> str:
    return (f"peak={m['peak']:.4f}  rms={m['rms_db']:6.2f} dB  mid(0.5-1.5s)={m['mid_rms_db']:6.2f} dB"
            f"  centroid={m['centroid_hz']:7.1f} Hz  L/R corr={m['stereo_corr']:+.3f}")


def pairs(a: Path, b: Path) -> list[tuple[Path, Path]]:
    if a.is_file():
        return [(a, b)]
    vitals = {p.stem: p for p in b.rglob("*.vital")}
    return [(p, vitals[p.stem]) for p in sorted(a.rglob("*.fxp")) if p.stem in vitals]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("fxp", type=Path, help=".fxp file or folder")
    ap.add_argument("vital", type=Path, help=".vital file or folder")
    ap.add_argument("--save", type=Path, help="folder to write <stem>_serum.wav / <stem>_vital.wav")
    args = ap.parse_args(argv)

    todo = pairs(args.fxp, args.vital)
    if not todo:
        print("no matching pairs")
        return 1
    sys.path.insert(0, str(TOOLS))
    from vital_host import VitalHost

    host = VitalHost().load()
    for fxp, vital in todo:
        print(f"== {fxp.stem}")
        try:
            serum = render_serum(fxp)
            print(f"  serum  {fmt(metrics(serum))}")
        except Exception as exc:  # keep going for folder runs
            serum = None
            print(f"  serum  FAILED: {str(exc).splitlines()[0]}")
        try:
            vit = render_vital(vital, host)
            print(f"  vital  {fmt(metrics(vit))}")
        except Exception as exc:
            vit = None
            print(f"  vital  FAILED: {str(exc).splitlines()[0]}")
        if args.save:
            import soundfile as sf

            args.save.mkdir(parents=True, exist_ok=True)
            if serum is not None:
                sf.write(str(args.save / f"{fxp.stem}_serum.wav"), serum.T, SR)
            if vit is not None:
                sf.write(str(args.save / f"{fxp.stem}_vital.wav"), vit.T, SR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
