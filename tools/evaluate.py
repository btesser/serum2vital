"""Fast closeness loop: convert presets in-process, render Vital, score against Serum clips.

    python tools/evaluate.py out/listen/factory-* out/listen/reese --tier clean common-fx --tag baseline
    python tools/evaluate.py ... --tag after --compare baseline

Uses the Serum renders that tools/listen.py already made (so only the Vital
side is re-rendered) and the same MIDI phrase.  Results go to out/eval/<tag>.json;
--compare prints the per-preset and median change against an earlier tag.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS.parent))
from analyze_listen import load, metrics, note_family, tier  # noqa: E402
from listen import DEFAULT_PHRASE, SR  # noqa: E402


def phrase_notes(text: str, transpose: int = 0):
    notes = []
    for item in text.split(","):
        n, s, d = item.split(":")
        notes.append((int(n) + transpose, 100, float(s), float(d)))
    return notes, max(s + d for _, _, s, d in notes) + 0.8


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folders", nargs="+", type=Path)
    ap.add_argument("--tier", nargs="*", default=["clean", "common-fx"], help="tiers to include (clean, common-fx, approximated)")
    ap.add_argument("--match", help="regex on preset name to include")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--compare", help="earlier tag to diff against")
    ap.add_argument("--serum-root", type=Path, default=Path("D:/VSTData/serum"))
    ap.add_argument("--out", type=Path, default=Path("out/eval"))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--calib", nargs="*", default=[], help="mapping.CALIB overrides, e.g. unison_gain=0")
    args = ap.parse_args(argv)

    from serum2vital import convert, mapping, writer
    from vital_host import VitalHost

    for item in args.calib:
        key, value = item.split("=")
        mapping.CALIB[key] = value not in ("0", "false", "False")

    jobs = []
    for folder in args.folders:
        for row in json.loads((folder / "index.json").read_text(encoding="utf-8")):
            if not (row.get("serum") and row.get("source_path")):
                continue
            row_tier = row.get("tier") or tier(sorted({note_family(n) for n in row.get("notes", [])}))
            if args.tier and row_tier not in args.tier:
                continue
            if args.match and not re.search(args.match, row["name"], re.I):
                continue
            jobs.append((folder, row, row_tier))
    if args.limit:
        jobs = jobs[: args.limit]
    notes, seconds = phrase_notes(DEFAULT_PHRASE)
    options = convert.Options(serum_root=args.serum_root, max_frames=16)
    host = VitalHost().load()
    cache: dict = {}
    results = []
    for folder, row, row_tier in jobs:
        try:
            conv = convert.convert_file(Path(row["source_path"]), options, cache)
            host.set_preset(writer.build(conv))
            audio = host.render(notes, seconds, SR)
            m = metrics(load(folder / row["serum"]), audio.astype(np.float32))
        except Exception as exc:  # keep the loop going
            m = {"error": str(exc)[:120]}
        results.append({"set": folder.name, "name": row["name"], "tier": row_tier, "metrics": m})
        if "error" not in m:
            print(f"{row['name'][:36]:36} {row_tier:10} dist {m['distance']:6.2f}  spec {m['spec_db']:5.2f}  level {m['level_db']:+6.2f}  env {m['env_corr']:.3f}")
        else:
            print(f"{row['name'][:36]:36} ERROR {m['error']}")
    ok = [r for r in results if "error" not in r["metrics"]]
    med = lambda k: float(np.median([r["metrics"][k] for r in ok])) if ok else float("nan")
    summary = {"count": len(ok), "distance": med("distance"), "spec_db": med("spec_db"), "level_abs": float(np.median([abs(r["metrics"]["level_db"]) for r in ok])) if ok else 0,
               "level_signed": med("level_db"), "env_corr": med("env_corr"), "within_3": sum(r["metrics"]["distance"] <= 3 for r in ok)}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{args.tag}.json").write_text(json.dumps({"summary": summary, "results": results}, indent=1), encoding="utf-8")
    print(f"\n[{args.tag}] {summary['count']} presets: median distance {summary['distance']:.2f}, spectral {summary['spec_db']:.2f} dB, "
          f"|level| {summary['level_abs']:.2f} dB (signed {summary['level_signed']:+.2f}), env corr {summary['env_corr']:.3f}, within 3: {summary['within_3']}")
    if args.compare:
        before = json.loads((args.out / f"{args.compare}.json").read_text(encoding="utf-8"))
        prev = {(r["set"], r["name"]): r["metrics"] for r in before["results"]}
        deltas = []
        for r in ok:
            p = prev.get((r["set"], r["name"]))
            if p and "error" not in p:
                deltas.append((r["name"], p["distance"], r["metrics"]["distance"]))
        better = sum(1 for _, a, b in deltas if b < a - 0.3)
        worse = sum(1 for _, a, b in deltas if b > a + 0.3)
        bs = before["summary"]
        print(f"[vs {args.compare}] median distance {bs['distance']:.2f} -> {summary['distance']:.2f}, spectral {bs['spec_db']:.2f} -> {summary['spec_db']:.2f}, "
              f"|level| {bs['level_abs']:.2f} -> {summary['level_abs']:.2f}, env {bs['env_corr']:.3f} -> {summary['env_corr']:.3f}; better {better}, worse {worse}, same {len(deltas) - better - worse}")
        for name, a, b in sorted(deltas, key=lambda t: t[2] - t[1])[:5] + sorted(deltas, key=lambda t: t[1] - t[2])[:5]:
            print(f"   {name[:40]:40} {a:6.2f} -> {b:6.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
