"""Score converted presets against their Serum renders and group by conversion note.

    python tools/analyze_listen.py out/listen/factory-* out/listen/reese --out out/listen

For every preset in the given tools/listen.py folders that has both clips, the
Vital render is compared with the Serum render (level offset, 1/6-octave
spectral distance, loudness-envelope correlation) and the numbers are written
back into each folder's index.json.  The notes each preset carried through the
conversion are reduced to "families" (the note with names and numbers removed)
and the presets are then grouped: those with no notes at all should be close
to exact; every family's excess distance over that baseline says how much that
approximation costs.  Writes analysis.json and analysis.md into --out.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

SR = 44100
KINDS = ("approximation", "unsupported", "conflict", "resource-conflict", "character", "unknown", "other")


def note_kind(note: str) -> str:
    head = note.split(":", 1)[0].strip().lower()
    return head if head in KINDS else "other"


def note_family(note: str) -> str:
    """Collapse a note to its mechanism: drop names, numbers and trailing detail."""
    kind, _, body = note.partition(":")
    body = body.split(";", 1)[0]
    body = re.sub(r"'[^']*'", "'*'", body)
    body = re.sub(r"\([^)]*\)", "", body)
    body = re.sub(r"-?\d+(\.\d+)?", "N", body)
    body = re.sub(r"\b(osc|oscillator|LFO|env|envelope|macro|filter|Chaos)\s+(?:[A-D]|N)\b", r"\1 n", body, flags=re.I)
    body = re.sub(r"\s+", " ", body).strip(" .")
    return f"{kind.strip()}: {body}" if body else kind.strip()


# Notes that state a known, constant difference rather than a per-preset
# approximation; presets carrying only these count as "clean" for the baseline.
INFORMATIONAL = (
    "approximation: preset predates Serum's voicing/unison/noise switch block",
    "approximation: Serum's Plate reverb mode has no Vital equivalent",
)
# Effects that almost every preset uses and whose mapping is a known, global
# approximation; a second baseline tier allows these as well.
COMMON_FX = INFORMATIONAL + (
    "approximation: reverb size/decay/damping mapped by ear",
    "approximation: compressor threshold/ratio/makeup mapped onto Vital's multiband compressor",
)


def tier(families: list[str]) -> str:
    if all(f in INFORMATIONAL for f in families):
        return "clean"
    if all(f in COMMON_FX for f in families):
        return "common-fx"
    return "approximated"


def load(path: Path) -> np.ndarray:
    import soundfile as sf

    data, _ = sf.read(str(path), dtype="float32")
    return data.T if data.ndim == 2 else data[None, :]


def bands(a: np.ndarray) -> np.ndarray:
    mono = a.mean(axis=0)
    spec = np.abs(np.fft.rfft(mono * np.hanning(len(mono)))) ** 2
    freqs = np.fft.rfftfreq(len(mono), 1 / SR)
    edges = 30 * 2 ** (np.arange(0, 60) / 6)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        if hi > SR / 2:
            break
        sel = (freqs >= lo) & (freqs < hi)
        out.append(spec[sel].sum() + 1e-12)
    return 10 * np.log10(np.array(out))


def envelope(a: np.ndarray, win: int = 882) -> np.ndarray:
    mono = a.mean(axis=0)
    n = len(mono) // win
    return np.sqrt((mono[: n * win].reshape(n, win) ** 2).mean(axis=1))


def metrics(serum: np.ndarray, vital: np.ndarray) -> dict:
    n = min(serum.shape[1], vital.shape[1])
    serum, vital = serum[:, :n], vital[:, :n]
    rms_s, rms_v = np.sqrt(np.mean(serum ** 2)) + 1e-9, np.sqrt(np.mean(vital ** 2)) + 1e-9
    level = float(20 * np.log10(rms_v / rms_s))
    bs, bv = bands(serum), bands(vital)
    mask = bs > bs.max() - 60
    spec = float(np.mean(np.abs(bv - bs)[mask]))
    es, ev = envelope(serum), envelope(vital)
    env = float(np.corrcoef(es, ev)[0, 1]) if es.std() > 0 and ev.std() > 0 else 0.0
    return {"level_db": round(level, 2), "spec_db": round(spec, 2), "env_corr": round(env, 3),
            "distance": round(spec + abs(level), 2), "silent": bool(rms_v < 1e-4)}


def summarize(items: list[dict]) -> dict:
    if not items:
        return {"count": 0}
    d = np.array([i["metrics"]["distance"] for i in items])
    s = np.array([i["metrics"]["spec_db"] for i in items])
    lv = np.array([abs(i["metrics"]["level_db"]) for i in items])
    e = np.array([i["metrics"]["env_corr"] for i in items])
    return {"count": int(len(d)), "distance_median": round(float(np.median(d)), 2), "distance_mean": round(float(d.mean()), 2),
            "spec_median": round(float(np.median(s)), 2), "level_abs_median": round(float(np.median(lv)), 2),
            "env_corr_median": round(float(np.median(e)), 3), "within_3db": int((d <= 3).sum()),
            "silent": int(sum(i["metrics"]["silent"] for i in items))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folders", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)

    scored: list[dict] = []
    unscored = 0
    for folder in args.folders:
        index = folder / "index.json"
        rows = json.loads(index.read_text(encoding="utf-8"))
        for row in rows:
            row["families"] = sorted({note_family(n) for n in row.get("notes", [])})
            row["kinds"] = sorted({note_kind(n) for n in row.get("notes", [])})
            row["tier"] = tier(row["families"])
            if row.get("serum") and row.get("vital"):
                row["metrics"] = metrics(load(folder / row["serum"]), load(folder / row["vital"]))
                scored.append({"set": folder.name, **row})
            else:
                row.pop("metrics", None)
                unscored += 1
        index.write_text(json.dumps(rows, indent=1), encoding="utf-8")

    clean = [r for r in scored if r["tier"] == "clean"]
    baseline = summarize(clean)
    base_median = baseline.get("distance_median", 0.0)
    tiers = {t: summarize([r for r in scored if r["tier"] == t]) for t in ("clean", "common-fx", "approximated")}
    sets: dict[str, list[dict]] = defaultdict(list)
    for r in scored:
        sets[r["set"]].append(r)
    set_rows = []
    for name, items in sorted(sets.items()):
        s = summarize(items)
        s["set"] = name
        s["level_signed_median"] = round(float(np.median([i["metrics"]["level_db"] for i in items])), 2)
        set_rows.append(s)
    level_signed = np.array([r["metrics"]["level_db"] for r in scored])
    families: dict[str, list[dict]] = defaultdict(list)
    kinds: dict[str, list[dict]] = defaultdict(list)
    for r in scored:
        for fam in r["families"]:
            families[fam].append(r)
        for kind in r["kinds"]:
            kinds[kind].append(r)
    fam_rows = []
    for fam, items in families.items():
        s = summarize(items)
        s["family"] = fam
        s["excess_median"] = round(s["distance_median"] - base_median, 2)
        s["impact"] = round(max(s["excess_median"], 0.0) * s["count"], 1)
        s["worst"] = [(i["set"], i["name"], i["metrics"]["distance"])
                      for i in sorted(items, key=lambda i: -i["metrics"]["distance"])[:3]]
        fam_rows.append(s)
    fam_rows.sort(key=lambda s: -s["impact"])
    kind_rows = []
    for kind in KINDS:
        if kinds.get(kind):
            s = summarize(kinds[kind])
            s["kind"] = kind
            s["excess_median"] = round(s["distance_median"] - base_median, 2)
            kind_rows.append(s)
    counts: dict[int, int] = defaultdict(int)
    for r in scored:
        counts[min(len(r["notes"]), 10)] += 1
    analysis = {
        "scored": len(scored), "unscored": unscored, "overall": summarize(scored), "clean": baseline,
        "tiers": tiers, "by_set": set_rows,
        "level_signed": {"median": round(float(np.median(level_signed)), 2), "vital_louder": int((level_signed > 1).sum()),
                         "vital_quieter": int((level_signed < -1).sum()), "within_1db": int((np.abs(level_signed) <= 1).sum())},
        "informational": list(INFORMATIONAL), "common_fx": list(COMMON_FX),
        "clean_worst": [(r["set"], r["name"], r["metrics"]) for r in sorted(clean, key=lambda r: -r["metrics"]["distance"])[:15]],
        "clean_best": [(r["set"], r["name"], r["metrics"]) for r in sorted(clean, key=lambda r: r["metrics"]["distance"])[:5]],
        "by_kind": kind_rows, "by_family": fam_rows,
        "notes_per_preset": {str(k): counts[k] for k in sorted(counts)},
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "analysis.json").write_text(json.dumps(analysis, indent=1), encoding="utf-8")

    md = ["# Conversion closeness analysis", "",
          f"{len(scored)} presets scored against their Serum render ({unscored} without a Serum clip).",
          "Distance = spectral distance (mean |dB| over 1/6-octave bands) + |level offset dB|; lower is closer.", "",
          "## Overall", "", f"- all scored: {analysis['overall']}",
          f"- level offset (Vital minus Serum): median {analysis['level_signed']['median']:+} dB; "
          f"{analysis['level_signed']['vital_louder']} presets Vital louder by >1 dB, {analysis['level_signed']['vital_quieter']} quieter, "
          f"{analysis['level_signed']['within_1db']} within 1 dB", "",
          "## By tier", "", "Clean = no notes other than the two constant ones (old-build switch block, Plate reverb); "
          "common-fx = additionally only the reverb-by-ear and compressor notes.", "",
          "| tier | presets | median distance | median spectral dB | median abs level dB | median env corr | within 3 dB |", "|---|---|---|---|---|---|---|"]
    md += [f"| {t} | {s.get('count', 0)} | {s.get('distance_median', '')} | {s.get('spec_median', '')} | {s.get('level_abs_median', '')} | {s.get('env_corr_median', '')} | {s.get('within_3db', '')} |"
           for t, s in tiers.items()]
    md += ["", "## By set", "", "| set | presets | median distance | median spectral dB | median signed level dB | median env corr |", "|---|---|---|---|---|---|"]
    md += [f"| {s['set']} | {s['count']} | {s['distance_median']} | {s['spec_median']} | {s['level_signed_median']:+} | {s['env_corr_median']} |" for s in set_rows]
    md += ["", "## Clean presets, worst first", ""]
    md += [f"- {s}/{n}: {m}" for s, n, m in analysis["clean_worst"]]
    md += ["", "## By note kind", "", "| kind | presets | median distance | excess over clean | median env corr | silent |",
           "|---|---|---|---|---|---|"]
    md += [f"| {k['kind']} | {k['count']} | {k['distance_median']} | {k['excess_median']:+} | {k['env_corr_median']} | {k['silent']} |"
           for k in kind_rows]
    md += ["", "## By approximation family, ranked by impact (excess x count)", "",
           "| family | presets | median distance | excess | worst |", "|---|---|---|---|---|"]
    md += [f"| {f['family']} | {f['count']} | {f['distance_median']} | {f['excess_median']:+} | "
           f"{'; '.join(f'{n} ({d})' for _, n, d in f['worst'][:2])} |" for f in fam_rows[:40]]
    (args.out / "analysis.md").write_text("\n".join(md), encoding="utf-8")
    print(f"scored {len(scored)}; clean {baseline}; wrote {args.out / 'analysis.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
