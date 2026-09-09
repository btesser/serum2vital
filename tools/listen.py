"""Render a set of converted presets side by side with their Serum originals.

    python tools/listen.py "out/Serum Converted/Presets/BASS/REESE" --serum-root D:/VSTData/serum --out out/listen/reese
                          [--phrase "48:0:2.5,48:2.7:0.35,51:3.2:0.35,53:3.7:0.35,55:4.2:0.35,48:4.7:2"] [--transpose 0]

The phrase is a list of note:start:duration triples (MIDI note, seconds); the
default holds C2, plays a short riff and holds C2 again so both the sustain and
the note-to-note behaviour can be heard.

For every .vital under the folder, finds the Serum source with the same stem
under the Serum root (.fxp or .SerumPreset), renders both (Serum 1 only; the
Serum 2 plugin cannot be driven headlessly here) and writes
"<name> - serum.wav" / "<name> - vital.wav" plus an index.html player.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
SR = 44100
DEFAULT_PHRASE = "48:0:2.5,48:2.7:0.35,51:3.2:0.35,53:3.7:0.35,55:4.2:0.35,48:4.7:2"

SERUM_BATCH = r'''
import os, sys, json
sys.path.insert(0, %(tools)r)
import numpy as np
from serum_host import SerumHost, write_wav
jobs = json.load(open(sys.argv[1], encoding="utf-8"))
host = SerumHost(sample_rate=%(sr)d).load()
notes = %(notes)r
for fxp, wav in jobs:
    try:
        host.load_preset(fxp)
        audio = host.render(notes, %(seconds)f)
        write_wav(wav, audio, %(sr)d)
        print("ok", wav)
    except Exception as exc:
        print("fail", fxp, exc)
    sys.stdout.flush()
os._exit(0)
'''


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _is_link(path: Path) -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return os.path.islink(path) or bool(getattr(st, "st_file_attributes", 0) & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT


def source_index(root: Path, cache: Path) -> dict:
    """Index every Serum preset under `root` by internal name, author and stem.

    Converted files are named after the preset's internal name (plus " (n)"
    for duplicates), not after the source file, so the lookup goes through the
    name stored in each source. The index is cached next to the output.
    """
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data.get("root") == str(root):
                return data
        except (OSError, ValueError):
            pass
    sys.path.insert(0, str(TOOLS.parent))
    from serum2vital import serum1, serum2

    by_name: dict[str, list] = {}
    by_stem: dict[str, list] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        # Do not descend into junctions/symlinks (the Serum 2 folder links back
        # to the Serum 1 library), or every preset would be found twice.
        dirnames[:] = [d for d in dirnames if not _is_link(Path(dirpath) / d)]
        for filename in filenames:
            path = Path(dirpath) / filename
            suffix = path.suffix.lower()
            if suffix not in (".fxp", ".serumpreset"):
                continue
            try:
                patch = serum1.read(str(path)) if suffix == ".fxp" else serum2.read(str(path))
                name, author = patch.name, patch.author
            except Exception:
                name, author = path.stem, ""
            entry = [str(path), name, author]
            by_name.setdefault(_norm(name), []).append(entry)
            by_stem.setdefault(_norm(path.stem), []).append(entry)
    data = {"root": str(root), "by_name": by_name, "by_stem": by_stem}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data), encoding="utf-8")
    return data


def match_source(index: dict, vital: Path) -> list[Path]:
    """Candidate source presets for a converted .vital (best first)."""
    try:
        meta = json.loads(vital.read_text(encoding="utf-8"))
        name, author = str(meta.get("preset_name", "")), str(meta.get("author", ""))
    except (OSError, ValueError):
        name, author = vital.stem, ""
    stem = re.sub(r" \(\d+\)$", "", vital.stem)
    candidates = index["by_name"].get(_norm(name), []) if name else []
    same_author = [c for c in candidates if _norm(c[2]) == _norm(author)]
    if same_author:
        candidates = same_author
    if not candidates:
        candidates = index["by_stem"].get(_norm(stem), [])
    return [Path(c[0]) for c in candidates]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("vital_folder", type=Path, help="folder of converted .vital files (or, with --sources, a label)")
    ap.add_argument("--sources", type=Path, help="render the conversions of the Serum presets under this folder instead")
    ap.add_argument("--report", type=Path, default=Path("logs/conversion_report.json"), help="conversion report mapping sources to outputs")
    ap.add_argument("--serum-root", type=Path, default=Path(os.environ.get("SERUM_ROOT", "D:/VSTData/serum")))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--phrase", default=DEFAULT_PHRASE, help="note:start:duration triples, comma separated")
    ap.add_argument("--transpose", type=int, default=0, help="semitones added to every note")
    ap.add_argument("--reuse", action="store_true", help="keep existing .wav files instead of re-rendering them")
    args = ap.parse_args(argv)
    notes = []
    for item in args.phrase.split(","):
        note, start, duration = item.split(":")
        notes.append((int(note) + args.transpose, 100, float(start), float(duration)))
    seconds = max(start + duration for _, _, start, duration in notes) + 0.8

    forced_sources: dict[Path, Path] = {}
    if args.sources:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        root = str(args.sources.resolve()).lower().rstrip("\/") + os.sep
        for item in report["results"]:
            if item.get("output") and str(Path(item["source"]).resolve()).lower().startswith(root):
                forced_sources[Path(item["output"])] = Path(item["source"])
        vitals = sorted(forced_sources, key=lambda p: p.stem.lower())
    else:
        vitals = sorted(args.vital_folder.rglob("*.vital"))
    index = source_index(args.serum_root, args.out.parent / "_source_index.json")
    args.out.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(TOOLS))
    from vital_host import VitalHost, write_wav

    host = VitalHost().load()
    rows = []
    serum_jobs = []
    for v in vitals:
        stem = v.stem
        vital_wav = args.out / f"{stem} - vital.wav"
        try:
            if not (args.reuse and vital_wav.exists()):
                host.load_file(v)
                write_wav(vital_wav, host.render(notes, seconds, SR), SR)
            vital_ok = True
        except Exception as exc:
            print(f"vital failed: {stem}: {exc}")
            vital_ok = False
        src = [forced_sources[v]] if v in forced_sources else match_source(index, v)
        kind = "none"
        serum_wav = None
        if src:
            s = src[0]
            kind = "serum1" if s.suffix.lower() == ".fxp" else "serum2"
            if kind == "serum1":
                serum_wav = args.out / f"{stem} - serum.wav"
                if not (args.reuse and serum_wav.exists()):
                    serum_jobs.append((str(s), str(serum_wav)))
        if v in forced_sources:
            category = str(forced_sources[v].parent.relative_to(args.sources.resolve())).replace("\\", "/").strip(".")
        else:
            category = str(v.relative_to(args.vital_folder).parent).replace("\\", "/")
        rows.append({"name": stem, "category": category,
                     "vital": vital_wav.name if vital_ok else None, "serum": serum_wav.name if serum_wav else None,
                     "source": kind, "source_path": str(src[0]) if src else "", "ambiguous": len(src) > 1})

    if serum_jobs:
        jobs_file = args.out / "_serum_jobs.json"
        jobs_file.write_text(json.dumps(serum_jobs), encoding="utf-8")
        script = SERUM_BATCH % {"tools": str(TOOLS), "sr": SR, "notes": notes, "seconds": seconds}
        proc = subprocess.run([sys.executable, "-c", script, str(jobs_file)], capture_output=True, text=True)
        failed = {line.split(" ", 2)[1] for line in proc.stdout.splitlines() if line.startswith("fail")}
        for row in rows:
            if row["serum"] and (row["source_path"] in failed or not (args.out / row["serum"]).exists()):
                row["serum"] = None
        jobs_file.unlink(missing_ok=True)

    parts = [
        "<!doctype html><meta charset='utf-8'><title>Listening: %s</title>" % html.escape(args.vital_folder.name),
        "<style>body{font:14px system-ui;margin:24px;background:#141418;color:#eee}table{border-collapse:collapse;width:100%}"
        "td,th{padding:6px 8px;border-bottom:1px solid #333;text-align:left;vertical-align:middle}audio{width:260px;height:32px}"
        "small{color:#999}</style>",
        f"<h1>{html.escape(args.vital_folder.name)}: {len(rows)} presets</h1>",
        f"<p><small>Phrase: {html.escape(args.phrase)} (MIDI note:start:duration; transpose {args.transpose:+d}), {seconds:g} s per clip.</small></p>",
        "<p>Left: the Serum original (Serum 1 only). Right: the converted Vital preset. Play them in Vital itself for the real thing; these are headless renders.</p>",
        "<table><tr><th>#</th><th>preset</th><th>category</th><th>Serum</th><th>Vital</th></tr>",
    ]
    for i, r in enumerate(rows, 1):
        serum_cell = f"<audio controls preload='none' src='{html.escape(r['serum'])}'></audio>" if r["serum"] else (
            "<small>Serum 2 source: no headless render</small>" if r["source"] == "serum2" else "<small>source not found</small>")
        vital_cell = f"<audio controls preload='none' src='{html.escape(r['vital'])}'></audio>" if r["vital"] else "<small>render failed</small>"
        note = " <small>(name shared by several source packs)</small>" if r["ambiguous"] else ""
        parts.append(f"<tr><td>{i}</td><td>{html.escape(r['name'])}{note}</td><td><small>{html.escape(r['category'])}</small></td><td>{serum_cell}</td><td>{vital_cell}</td></tr>")
    parts.append("</table>")
    (args.out / "index.html").write_text("\n".join(parts), encoding="utf-8")
    (args.out / "index.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    n_serum = sum(1 for r in rows if r["serum"])
    print(f"{len(rows)} presets: {n_serum} with Serum renders, {sum(1 for r in rows if r['source']=='serum2')} from Serum 2, "
          f"{sum(1 for r in rows if r['source']=='none')} without a source match -> {args.out / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
