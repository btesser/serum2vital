"""Turn tools/listen.py output folders into a static site (MP3 + HTML).

    python tools/publish_listen.py out/listen/reese out/listen/factory-bass --site site [--analysis out/listen/analysis.json]

Each listen folder becomes <site>/<folder name>/ with 128 kbps MP3 versions of
the clips (encoded with ffmpeg) and an index.html that lists every preset with
its conversion notes, its closeness metrics (from tools/analyze_listen.py) and
filters by note kind / note family / tier.  <site>/index.html links the
categories and, when --analysis is given, an analysis page summarises the
metrics by tier, set and note family.  Push the site folder to `gh-pages`.
"""

from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_listen import KINDS, note_family, note_kind, tier  # noqa: E402

REPO_URL = "https://github.com/btesser/serum2vital"

STYLE = """
:root{--bg:#141418;--fg:#eee;--mute:#999;--line:#333;--card:#1d1d24;--acc:#7dd3fc}
body{font:15px/1.4 system-ui,sans-serif;margin:0;padding:24px;background:var(--bg);color:var(--fg)}
a{color:var(--acc)} h1{margin:0 0 4px} h2{margin:24px 0 8px} p{margin:6px 0} small{color:var(--mute)}
table{border-collapse:collapse;width:100%;margin-top:12px}
td,th{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{position:sticky;top:0;background:var(--bg)}
audio{width:100%;max-width:300px;height:32px}
.cat{color:var(--mute)} .notes{margin:4px 0 0;padding:0;list-style:none;font-size:13px;color:#ccc}
.notes li{margin:2px 0} .badge{display:inline-block;font-size:11px;padding:1px 6px;border-radius:8px;margin-right:4px;background:#333;color:#ddd}
.badge.approximation{background:#3b4a6b}.badge.unsupported{background:#6b3b3b}.badge.conflict{background:#6b5a3b}
.badge.resource-conflict{background:#5a4b3b}.badge.character{background:#3b6b4f}.badge.unknown{background:#5b3b6b}.badge.other{background:#444}
.metric{display:inline-block;font-size:12px;padding:1px 6px;border-radius:4px;margin-right:4px;background:#26262e;color:#ddd}
.metric.good{background:#234d33}.metric.bad{background:#5a2a2a}
.controls{display:flex;flex-wrap:wrap;gap:16px;align-items:flex-start;background:var(--card);padding:12px;border-radius:8px;margin-top:12px}
.controls fieldset{border:1px solid var(--line);border-radius:6px;padding:6px 10px;margin:0;min-width:180px}
.controls legend{color:var(--mute);font-size:12px} .controls label{display:block;font-size:13px;white-space:nowrap}
.families{max-height:220px;overflow:auto;min-width:340px} .families label{white-space:normal}
input[type=search],select{background:#26262e;color:#eee;border:1px solid var(--line);border-radius:4px;padding:4px 6px}
.count{color:var(--mute);font-size:13px;margin-left:8px}
@media (max-width:800px){table,thead,tbody,tr,td,th{display:block} th{display:none} td{padding:3px 0} tr{border-bottom:1px solid var(--line);padding:8px 0}}
"""

SCRIPT = r"""
const rows = ROWS;
const famCounts = {};
rows.forEach(r => (r.families || []).forEach(f => famCounts[f] = (famCounts[f] || 0) + 1));
const fams = Object.keys(famCounts).sort((a, b) => famCounts[b] - famCounts[a]);
const famBox = document.getElementById('families');
fams.forEach(f => {
  const id = 'f' + Math.random().toString(36).slice(2);
  famBox.insertAdjacentHTML('beforeend', `<label><input type="checkbox" value="${f.replace(/"/g,'&quot;')}" class="fam"> ${f} <small>(${famCounts[f]})</small></label>`);
});
function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function metric(m){
  if (!m) return '<small>no Serum clip</small>';
  const cls = v => v <= 3 ? 'good' : v >= 12 ? 'bad' : '';
  return `<span class="metric ${cls(m.distance)}" title="spectral distance + |level offset|">distance ${m.distance}</span>`
       + `<span class="metric" title="mean |dB| over 1/6-octave bands">spec ${m.spec_db} dB</span>`
       + `<span class="metric" title="Vital minus Serum, whole clip">level ${m.level_db > 0 ? '+' : ''}${m.level_db} dB</span>`
       + `<span class="metric" title="loudness envelope correlation">env ${m.env_corr}</span>`
       + (m.silent ? '<span class="metric bad">silent</span>' : '');
}
function render(){
  const q = document.getElementById('q').value.toLowerCase();
  const kinds = [...document.querySelectorAll('.kind:checked')].map(e => e.value);
  const selFams = [...document.querySelectorAll('.fam:checked')].map(e => e.value);
  const famMode = document.getElementById('fammode').value;
  const tierSel = document.getElementById('tier').value;
  const onlyScored = document.getElementById('scored').checked;
  const sort = document.getElementById('sort').value;
  let list = rows.filter(r => {
    if (q && !(r.name + ' ' + r.category + ' ' + (r.notes||[]).join(' ')).toLowerCase().includes(q)) return false;
    if (tierSel !== 'all' && r.tier !== tierSel) return false;
    if (onlyScored && !r.metrics) return false;
    const rk = r.kinds || [];
    if (rk.length && !rk.some(k => kinds.includes(k))) return false;
    if (selFams.length){
      const rf = r.families || [];
      const hit = famMode === 'all' ? selFams.every(f => rf.includes(f)) : selFams.some(f => rf.includes(f));
      if (famMode === 'exclude' ? hit : !hit) return false;
    }
    return true;
  });
  const key = {name: r => r.name.toLowerCase(), distance: r => r.metrics ? r.metrics.distance : 1e9, spec: r => r.metrics ? r.metrics.spec_db : 1e9,
               level: r => r.metrics ? Math.abs(r.metrics.level_db) : 1e9, env: r => r.metrics ? -r.metrics.env_corr : 1e9, notes: r => -(r.notes||[]).length}[sort];
  list.sort((a, b) => key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0);
  document.getElementById('count').textContent = `${list.length} of ${rows.length} presets`;
  const body = list.map((r, i) => `<tr><td>${i + 1}</td>
    <td><b>${esc(r.name)}</b><br><small class="cat">${esc(r.category || '')}</small><div>${metric(r.metrics)}</div>
      <ul class="notes">${(r.notes||[]).map(n => `<li><span class="badge ${esc(noteKind(n))}">${esc(noteKind(n))}</span>${esc(n.replace(/^[^:]*:\s*/, ''))}</li>`).join('')}</ul></td>
    <td>${r.serum ? `<audio controls preload="none" src="${encodeURIComponent(r.serum)}"></audio>` : (r.source !== 'none' ? '<small>no original render</small>' : '<small>no source</small>')}</td>
    <td>${r.vital ? `<audio controls preload="none" src="${encodeURIComponent(r.vital)}"></audio>` : '<small>render failed</small>'}</td></tr>`).join('');
  document.getElementById('tbody').innerHTML = body;
}
function noteKind(n){ const k = n.split(':')[0].trim().toLowerCase(); return KINDS.includes(k) ? k : 'other'; }
document.querySelectorAll('input,select').forEach(e => e.addEventListener('input', render));
document.getElementById('clearfams').addEventListener('click', () => { document.querySelectorAll('.fam').forEach(e => e.checked = false); render(); });
render();
"""


def encode(wav: Path, mp3: Path) -> None:
    if mp3.exists() and mp3.stat().st_mtime >= wav.stat().st_mtime:
        return
    mp3.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(wav), "-codec:a", "libmp3lame",
                    "-b:a", "128k", str(mp3)], check=True)


def page(title: str, body: str, up: str = "../") -> str:
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{STYLE}</style></head><body>"
            f"<p><a href='{up}'>&larr; all categories</a> &middot; <a href='{up}analysis/'>analysis</a> &middot; <a href='{REPO_URL}'>serum2vital on GitHub</a></p>"
            f"{body}</body></html>")


def build_category(src: Path, dest: Path, title: str) -> dict:
    rows = json.loads((src / "index.json").read_text(encoding="utf-8"))
    dest.mkdir(parents=True, exist_ok=True)
    for row in rows:
        row.setdefault("notes", [])
        row["families"] = sorted({note_family(n) for n in row["notes"]})
        row["kinds"] = sorted({note_kind(n) for n in row["notes"]})
        row["tier"] = tier(row["families"])
        for key in ("serum", "vital"):
            if row[key]:
                mp3 = Path(row[key]).with_suffix(".mp3").name
                encode(src / row[key], dest / mp3)
                row[key] = mp3
        row.pop("source_path", None)
    phrase = ""
    index_html = (src / "index.html").read_text(encoding="utf-8") if (src / "index.html").exists() else ""
    if "Phrase:" in index_html:
        phrase = html.unescape(index_html.split("Phrase:", 1)[1].split("<", 1)[0]).split(" (", 1)[0].strip()
    n_serum = sum(1 for r in rows if r["serum"])
    kind_boxes = "".join(f"<label><input type='checkbox' class='kind' value='{k}' checked> {k}</label>" for k in KINDS)
    body = (
        f"<h1>{html.escape(title)}</h1>"
        f"<p>{len(rows)} presets converted from Serum to Vital with <a href='{REPO_URL}'>serum2vital</a>. "
        f"Left: the Serum original. Right: the converted preset played in Vital, both headless renders of the same MIDI phrase"
        + (f" ({html.escape(phrase)}, note:start:duration)" if phrase else "") + ". "
        f"Under each name: the closeness metrics against the Serum clip and every note the converter left about that preset. "
        f"<b>Distance</b> = mean |dB| difference over 1/6-octave bands + |level offset|; lower is closer, under 3 is near exact. "
        f"Presets from Serum 2 have no original clip because Serum 2 cannot be rendered headlessly.</p>"
        f"<p><small>{n_serum} with a Serum original &middot; {sum(1 for r in rows if r['source'] == 'serum2')} from Serum 2 &middot; MP3 128 kbps</small></p>"
        f"<div class='controls'>"
        f"<fieldset><legend>search</legend><input type='search' id='q' placeholder='name, category or note text'></fieldset>"
        f"<fieldset><legend>sort by</legend><select id='sort'><option value='name'>name</option><option value='distance'>distance (closest first)</option>"
        f"<option value='spec'>spectral distance</option><option value='level'>level offset</option><option value='env'>envelope correlation</option><option value='notes'>most notes</option></select>"
        f"<label style='margin-top:6px'><input type='checkbox' id='scored'> only presets with a Serum clip</label></fieldset>"
        f"<fieldset><legend>tier</legend><select id='tier'><option value='all'>all</option><option value='clean'>clean: no notes beyond the constant ones</option>"
        f"<option value='common-fx'>common fx: reverb / compressor notes only</option><option value='approximated'>approximated: anything else</option></select></fieldset>"
        f"<fieldset><legend>note kinds (a preset with notes must have one of these)</legend>{kind_boxes}</fieldset>"
        f"<fieldset class='families'><legend>note families <select id='fammode'><option value='any'>show presets with any selected</option><option value='all'>show presets with all selected</option>"
        f"<option value='exclude'>hide presets with any selected</option></select> <button id='clearfams' type='button'>clear</button></legend><div id='families'></div></fieldset>"
        f"</div><p class='count' id='count'></p>"
        f"<table><thead><tr><th>#</th><th>preset, metrics and notes</th><th>Serum</th><th>Vital</th></tr></thead><tbody id='tbody'></tbody></table>"
        f"<p><small>Rendered with tools/listen.py, scored with tools/analyze_listen.py, published with tools/publish_listen.py.</small></p>"
        f"<script>const KINDS={json.dumps(list(KINDS))};const ROWS={json.dumps(rows)};</script><script>{SCRIPT}</script>"
    )
    (dest / "index.html").write_text(page(f"serum2vital: {title}", body), encoding="utf-8")
    return {"title": title, "count": len(rows), "with_serum": n_serum, "folder": dest.name}


def fmt(v) -> str:
    return "" if v is None else (f"{v:+}" if isinstance(v, float) and False else str(v))


def build_analysis(analysis: dict, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)

    def table(headers, rows):
        head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
        body = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows)
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    ov, cl, ls = analysis["overall"], analysis["clean"], analysis["level_signed"]
    tiers = analysis["tiers"]
    body = [
        "<h1>How close are the conversions?</h1>",
        f"<p>{analysis['scored']} presets scored against their Serum render ({analysis['unscored']} had no Serum clip). "
        "<b>Distance</b> = mean |dB| difference over 1/6-octave bands (whole clip) + |level offset in dB|; lower is closer. "
        "<b>env corr</b> is the correlation of the two loudness envelopes (20 ms windows), 1 = same shape in time.</p>",
        f"<p>Overall median distance {ov['distance_median']} (spectral {ov['spec_median']} dB, level {ov['level_abs_median']} dB), median envelope correlation {ov['env_corr_median']}; "
        f"{ov['within_3db']} presets within 3. Level offset (Vital minus Serum): median {ls['median']:+} dB; {ls['vital_louder']} presets Vital louder by more than 1 dB, "
        f"{ls['vital_quieter']} quieter, {ls['within_1db']} within 1 dB.</p>",
        "<h2>By tier</h2>",
        "<p><b>clean</b> = no notes other than two constant ones (old-build switch block defaults, Plate reverb); "
        "<b>common fx</b> = additionally only the reverb-by-ear and compressor notes; <b>approximated</b> = anything else. "
        "If the clean tier is not near exact, the gap is in the core mapping (oscillators, filters, envelopes, levels), not in any listed approximation.</p>",
        table(["tier", "presets", "median distance", "median spectral dB", "median |level| dB", "median env corr", "within 3"],
              [[t, s.get("count", 0), s.get("distance_median", ""), s.get("spec_median", ""), s.get("level_abs_median", ""), s.get("env_corr_median", ""), s.get("within_3db", "")] for t, s in tiers.items()]),
        "<h2>Clean presets, worst first</h2>",
        table(["set", "preset", "distance", "spectral dB", "level dB", "env corr"],
              [[s, n, m["distance"], m["spec_db"], m["level_db"], m["env_corr"]] for s, n, m in analysis["clean_worst"]]),
        "<h2>By set</h2>",
        table(["set", "presets", "median distance", "median spectral dB", "median signed level dB", "median env corr"],
              [[s["set"], s["count"], s["distance_median"], s["spec_median"], f"{s['level_signed_median']:+}", s["env_corr_median"]] for s in analysis["by_set"]]),
        "<h2>By note kind</h2>",
        table(["kind", "presets", "median distance", "excess over clean", "median env corr", "silent"],
              [[k["kind"], k["count"], k["distance_median"], f"{k['excess_median']:+}", k["env_corr_median"], k["silent"]] for k in analysis["by_kind"]]),
        "<h2>By note family, ranked by impact (excess over clean × presets)</h2>",
        "<p>Names and numbers are stripped from the notes so that one row is one mechanism. Excess is the family's median distance minus the clean tier's median.</p>",
        table(["family", "presets", "median distance", "excess", "median env corr", "worst examples"],
              [[f["family"], f["count"], f["distance_median"], f"{f['excess_median']:+}", f["env_corr_median"], "; ".join(f"{n} ({d})" for _, n, d in f["worst"][:2])] for f in analysis["by_family"]]),
    ]
    (dest / "index.html").write_text(page("serum2vital: closeness analysis", "\n".join(body)), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folders", nargs="+", type=Path, help="tools/listen.py output folders")
    ap.add_argument("--site", type=Path, required=True)
    ap.add_argument("--analysis", type=Path, help="analysis.json from tools/analyze_listen.py")
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
    analysis_link = ""
    if args.analysis and args.analysis.exists():
        build_analysis(json.loads(args.analysis.read_text(encoding="utf-8")), args.site / "analysis")
        analysis_link = "<p><a href='analysis/'>How close are the conversions? Metrics by tier, set and kind of approximation.</a></p>"
    items = "".join(f"<li><a href='{html.escape(c['folder'])}/'>{html.escape(c['title'])}</a> "
                    f"<small>{c['count']} presets, {c['with_serum']} with a Serum original</small></li>" for c in cats)
    (args.site / "index.html").write_text(
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(args.title)}</title><style>{STYLE}</style></head><body>"
        f"<h1>{html.escape(args.title)}</h1>"
        f"<p><a href='{REPO_URL}'>serum2vital</a> converts Xfer Serum presets into Vital presets. "
        f"These pages play the Serum original next to the converted preset in Vital, rendered headlessly from the same MIDI phrase, "
        f"with the converter's notes and closeness metrics for every preset, so you can judge how close a conversion gets and where it falls short.</p>"
        f"{analysis_link}<ul>{items}</ul>"
        f"<p><small>Renders are demos of the conversion only. The presets belong to their respective authors.</small></p>"
        f"</body></html>", encoding="utf-8")
    (args.site / ".nojekyll").write_text("", encoding="utf-8")
    total = sum(p.stat().st_size for p in args.site.rglob("*") if p.is_file())
    print(f"site: {args.site} ({total / 1e6:.1f} MB, {len(cats)} categories)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
