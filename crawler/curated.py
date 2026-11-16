"""Render data/curated.json (hand-picked candidates checked against
PortMaster's firmware limits) as build/curated.html.

Run on its own with:  python -m crawler.curated
"""

import json
import os

from .report import esc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "curated.json")

FIT_CLASS = {"Good": "ok", "Possible": "pos", "Check glibc": "mid", "Hard": "warn", "No": "bad"}


def link(url, text=None):
    if not url:
        return '<span class="dim">via suggestion</span>'
    label = text or url.split("://", 1)[-1].rstrip("/")
    return f'<a href="{esc(url)}" target="_blank" rel="noopener">{esc(label)}</a>'


def candidate_row(c, targets):
    cfw = "".join(
        f'<td><span class="pill {FIT_CLASS.get(v, "")}">{esc(v)}</span></td>' for v in c["cfw"]
    )
    text = " ".join(str(v) for v in c.values()).lower()
    return f"""<tr class="row" data-text="{esc(text)}" data-fit="{c['fit']}">
  <td><b>{esc(c['project'])}</b><div class="dim">{esc(c['game'])}</div></td>
  <td class="num"><span class="fit f{c['fit']}">{c['fit']}</span></td>
  <td>{esc(c['status'])}</td>
  {cfw}
  <td>{esc(c['render'])}<div class="dim">{esc(c['runtime'])}</div></td>
  <td>{esc(c['blockers'])}</td>
  <td>{esc(c['data'])}</td>
  <td>{link(c['repo'], c['repo'].split("://", 1)[-1].replace("github.com/", "").rstrip("/") if c['repo'] else None)}</td>
  <td class="dim">{esc(c['notes'])}<div>Suggestion: {esc(c['suggestion'])}</div></td>
</tr>"""


def render_curated(src=SRC, path=None):
    with open(src, encoding="utf-8") as f:
        d = json.load(f)
    path = path or os.path.join(ROOT, "build", "curated.html")
    os.makedirs(os.path.dirname(path), exist_ok=True)

    targets = d["targets"]
    cands = sorted(d["candidates"], key=lambda c: (-c["fit"], c["project"].lower()))
    rows = "".join(candidate_row(c, targets) for c in cands)
    heads = "".join(f"<th>{esc(t)}</th>" for t in targets)
    have = "".join(
        f"<tr><td>{esc(a['project'])}</td><td>{esc(a['engine'])}</td><td class=\"dim\">{esc(a['evidence'])}</td></tr>"
        for a in d["already_on_portmaster"]
    )
    rt = "".join(
        f"<tr><td><b>{esc(r['name'])}</b><div class=\"dim\">{esc(r['state'])}</div></td>"
        f"<td>{esc(r['unlocks'])}</td><td>{esc(r['limits'])}</td><td class=\"dim\">{esc(r['cfw'])}</td></tr>"
        for r in d["runtimes"]
    )
    srcs = " · ".join(link(u, t) for t, u in d["sources"])
    fits = "".join(f'<button data-f="{n}">{n}+</button>' for n in (5, 4, 3, 2))

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(d['title'])} · PortMaster Trending</title>
<style>
:root {{ --bg:#0f1115; --panel:#181b22; --line:#262b36; --fg:#e6e8ee; --dim:#9aa3b2; --acc:#d97757; --ok:#5fb67a; --mid:#d6b04a; --bad:#d26a6a; --pos:#6aa0d6; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }}
.wrap {{ max-width:1400px; margin:0 auto; padding:28px 18px 60px; }}
h1 {{ margin:0; font-size:28px; letter-spacing:-.01em; }}
h1 span {{ color:var(--acc); }}
.meta, .dim {{ color:var(--dim); }}
.meta {{ margin:6px 0 10px; }}
.intro {{ max-width:900px; color:var(--dim); }}
a {{ color:var(--fg); }} a:hover {{ color:var(--acc); }}
nav a {{ color:var(--acc); }}
h2 {{ font-size:19px; margin:30px 0 12px; border-bottom:1px solid var(--line); padding-bottom:6px; }}
h2 small {{ color:var(--dim); font-weight:400; font-size:14px; margin-left:6px; }}
.tools {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:8px 0; position:sticky; top:0; background:var(--bg); padding:10px 0; z-index:2; }}
.tools input {{ flex:1 1 220px; background:var(--panel); border:1px solid var(--line); color:var(--fg); border-radius:8px; padding:8px 10px; font:inherit; }}
.tools button {{ background:var(--panel); border:1px solid var(--line); color:var(--dim); border-radius:999px; padding:5px 11px; cursor:pointer; font:13px system-ui,sans-serif; }}
.tools button.on {{ color:var(--bg); background:var(--acc); border-color:var(--acc); }}
.xwrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:12px; background:var(--panel); }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th, td {{ text-align:left; vertical-align:top; padding:8px 10px; border-bottom:1px solid var(--line); }}
th {{ color:var(--dim); font-weight:600; white-space:nowrap; }}
tr:last-child td {{ border-bottom:0; }}
td.num {{ text-align:center; }}
.cand td:nth-child(7) {{ min-width:180px; }} .cand td:nth-child(1) {{ min-width:150px; }}
.cand {{ min-width:1700px; }} .cand td:nth-child(10) {{ min-width:320px; }}
.fit {{ display:inline-block; min-width:26px; border-radius:6px; padding:1px 7px; font-weight:700; }}
.f5 {{ background:#24452f; color:var(--ok); }} .f4 {{ background:#22394f; color:var(--pos); }}
.f3 {{ background:#4a3f1f; color:var(--mid); }} .f2 {{ background:#4a2f22; color:var(--acc); }} .f1 {{ background:#4a2525; color:var(--bad); }}
.pill {{ font-size:12px; border:1px solid var(--line); border-radius:999px; padding:1px 8px; white-space:nowrap; }}
.pill.ok {{ color:var(--ok); border-color:#2f5a3c; }} .pill.pos {{ color:var(--pos); border-color:#2e4a63; }}
.pill.mid {{ color:var(--mid); border-color:#5c4f25; }} .pill.warn {{ color:var(--acc); border-color:#5a3a2e; }} .pill.bad {{ color:var(--bad); border-color:#5c2e2e; }}
.hide {{ display:none !important; }}
.foot {{ color:var(--dim); font-size:13px; margin-top:40px; border-top:1px solid var(--line); padding-top:12px; }}
.foot a {{ color:var(--dim); }}
</style>
</head>
<body>
<div class="wrap">
  <nav><a href="./">← Weekly report</a></nav>
  <h1>PortMaster <span>candidates</span></h1>
  <p class="meta">{esc(d['title'])} · checked {esc(d['as_of'])} · targets: {esc(', '.join(targets))}</p>
  <p class="intro">{esc(d['intro'])}</p>

  <h2>Candidates <small>{len(cands)}</small></h2>
  <div class="tools">
    <input id="q" type="search" placeholder="Filter by name or text…">
    <button data-f="" class="on">all</button>{fits}
  </div>
  <div class="xwrap"><table class="cand">
    <thead><tr><th>Project</th><th>Fit</th><th>PortMaster</th>{heads}<th>Renderer / runtime</th><th>Blockers</th><th>Data</th><th>Source</th><th>Notes</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>

  <h2>Westonpack and gl4es <small>{len(d['runtimes'])}</small></h2>
  <div class="xwrap"><table>
    <thead><tr><th>Runtime / mode</th><th>What it unlocks</th><th>Limits</th><th>Firmware notes</th></tr></thead>
    <tbody>{rt}</tbody>
  </table></div>

  <h2>Checked: already on PortMaster <small>{len(d['already_on_portmaster'])}</small></h2>
  <div class="xwrap"><table>
    <thead><tr><th>Game</th><th>Engine / port</th><th>Evidence</th></tr></thead>
    <tbody>{have}</tbody>
  </table></div>

  <p class="foot">Hand-curated; edit <a href="https://github.com/monkeyx-net/portmaster-trending/blob/main/data/curated.json">data/curated.json</a> to update. Sources: {srcs}</p>
</div>
<script>
const q = document.getElementById('q');
let min = 0;
function apply() {{
  const t = q.value.trim().toLowerCase();
  document.querySelectorAll('tr.row').forEach(r => {{
    const ok = (+r.dataset.fit >= min) && (!t || r.dataset.text.includes(t));
    r.classList.toggle('hide', !ok);
  }});
}}
q.addEventListener('input', apply);
document.querySelectorAll('.tools button').forEach(b => b.addEventListener('click', () => {{
  document.querySelectorAll('.tools button').forEach(x => x.classList.remove('on'));
  b.classList.add('on'); min = +(b.dataset.f || 0); apply();
}}));
</script>
</body>
</html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    return path


if __name__ == "__main__":
    print("Wrote", render_curated())
