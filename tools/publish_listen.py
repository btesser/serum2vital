"""Turn tools/listen.py output folders into a static site (MP3 + HTML).

    python tools/publish_listen.py out/listen/reese out/listen/reese-lead --site site

Each listen folder becomes <site>/<folder name>/ with 128 kbps MP3 versions of
the clips (encoded with ffmpeg) and an index.html; <site>/index.html links the
categories. Push the site folder to a `gh-pages` branch to serve it.
"""

from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_URL = "https://github.com/btesser/serum2vital"

STYLE = """
body{font:15px/1.4 system-ui,sans-serif;margin:0;padding:24px;background:#141418;color:#eee}
a{color:#7dd3fc} h1{margin:0 0 4px} p{margin:6px 0} small{color:#999}
table{border-collapse:collapse;width:100%;margin-top:16px}
td,th{padding:6px 8px;border-bottom:1px solid #333;text-align:left;vertical-align:middle}
audio{width:100%;max-width:320px;height:32px} .cat{color:#999}
@media (max-width:700px){table,thead,tbody,tr,td,th{display:block} th{display:none} td{padding:3px 0} tr{border-bottom:1px solid #333;padding:8px 0}}
"""


def encode(wav: Path, mp3: Path) -> None:
    if mp3.exists() and mp3.stat().st_mtime >= wav.stat().st_mtime:
        return
    mp3.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(wav), "-codec:a", "libmp3lame",
                    "-b:a", "128k", str(mp3)], check=True)


def build_category(src: Path, dest: Path, title: str) -> dict:
    rows = json.loads((src / "index.json").read_text(encoding="utf-8"))
    dest.mkdir(parents=True, exist_ok=True)
    for row in rows:
        for key in ("serum", "vital"):
            if row[key]:
                mp3 = Path(row[key]).with_suffix(".mp3").name
                encode(src / row[key], dest / mp3)
                row[key] = mp3
    phrase = ""
    index_html = (src / "index.html").read_text(encoding="utf-8") if (src / "index.html").exists() else ""
    if "Phrase:" in index_html:
        phrase = html.unescape(index_html.split("Phrase:", 1)[1].split("<", 1)[0]).split(" (", 1)[0].strip()
        phrase = "MIDI note:start:duration " + phrase
    n_serum = sum(1 for r in rows if r["serum"])
    parts = [
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>serum2vital: {html.escape(title)}</title><style>{STYLE}</style></head><body>",
        f"<p><a href='../'>&larr; all categories</a> &middot; <a href='{REPO_URL}'>serum2vital on GitHub</a></p>",
        f"<h1>{html.escape(title)}</h1>",
        f"<p>{len(rows)} presets converted from Serum to Vital with <a href='{REPO_URL}'>serum2vital</a>. "
        f"Left: the Serum original. Right: the converted preset played in Vital. Both are headless renders of the same MIDI phrase"
        + (f" ({html.escape(phrase)})" if phrase else "") + ". "
        f"Presets that come from Serum 2 have no original clip here because Serum 2 cannot be rendered headlessly.</p>",
        f"<p><small>{n_serum} with a Serum original &middot; {sum(1 for r in rows if r['source'] == 'serum2')} from Serum 2 &middot; MP3 128 kbps</small></p>",
        "<table><thead><tr><th>#</th><th>preset</th><th>Serum</th><th>Vital</th></tr></thead><tbody>",
    ]
    for i, r in enumerate(rows, 1):
        serum_cell = (f"<audio controls preload='none' src='{html.escape(r['serum'])}'></audio>" if r["serum"]
                      else "<small>Serum 2 source: no original render</small>")
        vital_cell = f"<audio controls preload='none' src='{html.escape(r['vital'])}'></audio>" if r["vital"] else "<small>render failed</small>"
        parts.append(f"<tr><td>{i}</td><td>{html.escape(r['name'])}<br><small class='cat'>{html.escape(r['category'])}</small></td>"
                     f"<td>{serum_cell}</td><td>{vital_cell}</td></tr>")
    parts.append(f"</tbody></table><p><small>Rendered with tools/listen.py; published with tools/publish_listen.py.</small></p></body></html>")
    (dest / "index.html").write_text("\n".join(parts), encoding="utf-8")
    return {"title": title, "count": len(rows), "with_serum": n_serum, "folder": dest.name}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folders", nargs="+", type=Path, help="tools/listen.py output folders")
    ap.add_argument("--site", type=Path, required=True)
    ap.add_argument("--title", default="serum2vital: hear the conversions")
    args = ap.parse_args(argv)
    if shutil.which("ffmpeg") is None:
        print("ffmpeg is required", file=sys.stderr)
        return 1
    args.site.mkdir(parents=True, exist_ok=True)
    cats = []
    for folder in args.folders:
        title = folder.name.replace("-", " ").replace("_", " ").title()
        cats.append(build_category(folder, args.site / folder.name, title))
    items = "".join(f"<li><a href='{html.escape(c['folder'])}/'>{html.escape(c['title'])}</a> "
                    f"<small>{c['count']} presets, {c['with_serum']} with a Serum original</small></li>" for c in cats)
    (args.site / "index.html").write_text(
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(args.title)}</title><style>{STYLE}</style></head><body>"
        f"<h1>{html.escape(args.title)}</h1>"
        f"<p><a href='{REPO_URL}'>serum2vital</a> converts Xfer Serum presets into Vital presets. "
        f"These pages play the Serum original next to the converted preset in Vital, rendered headlessly from the same MIDI phrase, "
        f"so you can judge how close a conversion gets before installing anything.</p>"
        f"<ul>{items}</ul>"
        f"<p><small>Renders are demos of the conversion only. The presets belong to their respective authors.</small></p>"
        f"</body></html>", encoding="utf-8")
    (args.site / ".nojekyll").write_text("", encoding="utf-8")
    total = sum(p.stat().st_size for p in args.site.rglob("*") if p.is_file())
    print(f"site: {args.site} ({total / 1e6:.1f} MB, {len(cats)} categories)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
