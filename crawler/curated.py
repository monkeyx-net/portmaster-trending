"""Render data/curated.json (hand-picked candidates checked against
PortMaster's firmware limits) as build/curated.html.

Run on its own with:  python -m crawler.curated
"""

import base64
import json
import os
import re
import urllib.parse
from datetime import datetime, timezone

from .report import esc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "curated.json")

# Screenshots: a hand-set `screenshot` URL wins; otherwise `screenshot_auto` is
# filled on refresh from the PortMaster port folder named by `pm_port`
# ("PortMaster-New/<dir>" or "PortMaster-MV-New/<dir>"), else from the first
# non-badge image in the project's README. Images are hotlinked.
PM_REPOS = {"PortMaster-New": "PortsMaster/PortMaster-New", "PortMaster-MV-New": "PortsMaster-MV/PortMaster-MV-New"}
IMG_RE = re.compile(r'!\[[^\]]*\]\(\s*<?([^)\s>]+)|<img[^>]+src=["\']([^"\']+)', re.I)
NOT_SHOT = re.compile(
    r"shields\.io|badge|/workflows?/|coverity|codecov|coveralls|travis|appveyor|discord|widget|"
    r"logo|icon|banner|button|sponsor|donate|ko-?fi|patreon|paypal|liberapay|download|\.svg(\?|$)",
    re.I,
)


def readme_image(text, raw_base):
    """First README image that looks like a screenshot, as an absolute URL.
    `raw_base` is the raw.githubusercontent.com URL of the README's folder."""
    for m in IMG_RE.finditer(text or ""):
        src = (m.group(1) or m.group(2)).replace("&amp;", "&")
        if NOT_SHOT.search(src):
            continue
        if src.startswith("//"):
            src = "https:" + src
        if not src.startswith(("http://", "https://")):
            root = "/".join(raw_base.split("/")[:6]) + "/"  # https://raw.../owner/repo/branch/
            src = urllib.parse.urljoin(root if src.startswith("/") else raw_base, src.lstrip("/") if src.startswith("/") else src)
        elif "github.com/" in src and "/blob/" in src:
            src = src.replace("/blob/", "/raw/", 1)
        return src
    return None


def pm_screenshot_url(pm_port, files):
    """Raw URL of screenshot.(png|jpg) in a PortMaster port folder, given its file names."""
    repo, _, port = pm_port.partition("/")
    for name in files:
        if re.fullmatch(r"screenshot\.(png|jpe?g|webp)", name, re.I):
            return f"https://raw.githubusercontent.com/{PM_REPOS[repo]}/main/ports/{port}/{name}"
    return None


def find_screenshot(gh, item):
    """Look up an automatic screenshot for a curated entry, or None."""
    if item.get("pm_port"):
        repo, _, port = item["pm_port"].partition("/")
        listing = gh._get(f"/repos/{PM_REPOS[repo]}/contents/ports/{port}") or []
        url = pm_screenshot_url(item["pm_port"], [f["name"] for f in listing if isinstance(f, dict)])
        if url:
            return url
    if item.get("github"):
        data = gh._get(f"/repos/{item['github']}/readme")
        if data and data.get("content") and data.get("download_url"):
            text = base64.b64decode(data["content"]).decode("utf-8", "replace")
            return readme_image(text, data["download_url"].rsplit("/", 1)[0] + "/")
    return None


def refresh_screenshots(gh, d):
    """Fill `screenshot_auto` on candidates and already-on-PortMaster entries.
    Failed lookups keep the previous value."""
    n = 0
    for item in d["candidates"] + d["already_on_portmaster"]:
        if item.get("screenshot"):
            continue
        try:
            url = find_screenshot(gh, item)
        except Exception as e:
            print(f"  ! screenshot {item.get('github') or item.get('pm_port')}: {e}")
            continue
        if url:
            item["screenshot_auto"] = url
            n += 1
        else:
            item.pop("screenshot_auto", None)
    print(f"  {n} curated screenshots found")

def refresh(gh, src=SRC):
    """Update stars and last default-branch commit date for each candidate
    that has a `github` repo, and save them back to the JSON. Lookups that
    fail keep the previous values."""
    with open(src, encoding="utf-8") as f:
        d = json.load(f)
    ok = 0
    for c in d["candidates"]:
        name = c.get("github")
        if not name:
            continue
        try:
            r = gh.repo(name)
            if not r:
                print(f"  ! {name}: not found")
                continue
            c["stars"] = r.get("stargazers_count")
            commits = gh._get(f"/repos/{r['full_name']}/commits", {"sha": r["default_branch"], "per_page": 1})
            if commits:
                c["last_commit"] = commits[0]["commit"]["committer"]["date"][:10]
            ok += 1
        except Exception as e:  # keep the old values
            print(f"  ! {name}: {e}")
    refresh_screenshots(gh, d)
    if ok:
        d["repo_stats_checked"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with open(src, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"  {ok} curated repos refreshed")
    return ok


def commit_age(date):
    """CSS class for how stale a last-commit date is."""
    if not date:
        return ""
    days = (datetime.now(timezone.utc).date() - datetime.strptime(date, "%Y-%m-%d").date()).days
    return "fresh" if days <= 90 else "stale" if days <= 365 else "old"


FIT_CLASS = {"Good": "ok", "Possible": "pos", "Check glibc": "mid", "Hard": "warn", "No": "bad"}
SHIM_CLASS = {"Helps": "ok", "In use": "pos", "Partial": "mid", "Not needed": ""}


def shim_cell(c):
    """Whether the SDL3-over-SDL2 shim helps this candidate (SDL3 projects only)."""
    s = c.get("sdl3_shim")
    if not s:
        return '<td class="shim"><span class="dim">– (not SDL3)</span></td>'
    return (f'<td class="shim"><span class="pill {SHIM_CLASS.get(s["fit"], "")}">{esc(s["fit"])}</span>'
            f'<div class="dim">{esc(s["note"])}</div></td>')


def link(url, text=None):
    if not url:
        return '<span class="dim">via suggestion</span>'
    label = text or url.split("://", 1)[-1].rstrip("/")
    return f'<a href="{esc(url)}" target="_blank" rel="noopener">{esc(label)}</a>'


def shot(item):
    """Thumbnail linking to the full-size screenshot, or a placeholder."""
    url = item.get("screenshot") or item.get("screenshot_auto")
    if not url:
        return '<span class="noshot dim">no screenshot</span>'
    return (f'<a class="shot" href="{esc(url)}" target="_blank" rel="noopener">'
            f'<img src="{esc(url)}" alt="{esc(item["project"])} screenshot" loading="lazy" '
            f'referrerpolicy="no-referrer" onerror="this.parentNode.classList.add(\'broken\')"></a>')


def candidate_row(c, targets):
    cfw = "".join(
        f'<td><span class="pill {FIT_CLASS.get(v, "")}">{esc(v)}</span></td>' for v in c["cfw"]
    )
    text = " ".join(str(v) for k, v in c.items() if not k.startswith("screenshot")).lower()
    shim = c.get("sdl3_shim", {}).get("fit", "")
    return f"""<tr class="row" data-text="{esc(text)}" data-fit="{c['fit']}" data-shim="{esc(shim)}">
  <td><b>{esc(c['project'])}</b><div class="dim">{esc(c['game'])}</div>{shot(c)}</td>
  <td>{link(c['repo'], c.get('github') or c['repo'].split("://", 1)[-1].rstrip("/") if c['repo'] else None)}</td>
  <td class="num stars" data-v="{c.get('stars') or -1}">{'★ ' + format(c['stars'], ',') if c.get('stars') is not None else '<span class="dim">–</span>'}</td>
  <td class="num {commit_age(c.get('last_commit'))}" data-v="{esc(c.get('last_commit') or '')}">{esc(c.get('last_commit') or '–')}</td>
  <td class="num"><span class="fit f{c['fit']}">{c['fit']}</span></td>
  <td>{esc(c['status'])}</td>
  {cfw}
  <td>{esc(c['render'])}<div class="dim">{esc(c['runtime'])}</div></td>
  {shim_cell(c)}
  <td class="blk">{esc(c['blockers'])}</td>
  <td>{esc(c['data'])}</td>
  <td class="dim notes">{esc(c['notes'])}<div>Suggestion: {esc(c['suggestion'])}</div></td>
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
        f"<tr><td>{shot(a)}</td><td>{esc(a['project'])}</td><td>{esc(a['engine'])}</td><td class=\"dim\">{esc(a['evidence'])}</td></tr>"
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
.cand td:nth-child(10) {{ min-width:180px; }} .cand td:nth-child(1) {{ min-width:200px; }}
.shot {{ display:block; margin-top:8px; }}
.shot img {{ display:block; width:192px; aspect-ratio:4/3; object-fit:cover; border-radius:8px; border:1px solid var(--line); background:#000; }}
.shot:hover img {{ border-color:var(--acc); }}
.noshot {{ display:block; margin-top:8px; font-size:12px; }}
.shot.broken {{ display:none; }}
.cand {{ min-width:2450px; }} .cand td.notes {{ min-width:320px; }} .cand td.shim {{ min-width:260px; }} .cand td.blk {{ min-width:220px; }}
.cand td:nth-child(2) {{ min-width:210px; }} .cand td:nth-child(2) a {{ overflow-wrap:anywhere; }}
.stars {{ color:var(--mid); white-space:nowrap; }}
td.fresh {{ color:var(--ok); white-space:nowrap; }} td.stale {{ color:var(--mid); white-space:nowrap; }} td.old {{ color:var(--bad); white-space:nowrap; }}
th.sort {{ cursor:pointer; user-select:none; }} th.sort::after {{ content:" ⇅"; color:var(--line); }}
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
  <p class="dim">Stars and last commit (default branch) {('refreshed ' + esc(d['repo_stats_checked'])) if d.get('repo_stats_checked') else 'not yet refreshed'}. Last commit: <span style="color:var(--ok)">≤ 90 days</span>, <span style="color:var(--mid)">≤ 1 year</span>, <span style="color:var(--bad)">older</span>. Click Stars, Last commit or Fit to sort.</p>

  <h2>Candidates <small>{len(cands)}</small></h2>
  <div class="tools">
    <input id="q" type="search" placeholder="Filter by name or text…">
    <button data-f="" class="on">all</button>{fits}<button id="shim" title="Only SDL3 projects the SDL3-over-SDL2 shim helps or already uses">SDL3 shim</button>
  </div>
  <div class="xwrap"><table class="cand">
    <thead><tr><th>Project</th><th>Repo</th><th class="sort" data-k="stars">Stars</th><th class="sort" data-k="commit">Last commit</th><th class="sort" data-k="fit">Fit</th><th>PortMaster</th>{heads}<th>Renderer / runtime</th><th>SDL3 shim</th><th>Blockers</th><th>Data</th><th>Notes</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>

  <h2>Runtimes: Westonpack, gl4es and the SDL3 shim <small>{len(d['runtimes'])}</small></h2>
  <div class="xwrap"><table>
    <thead><tr><th>Runtime / mode</th><th>What it unlocks</th><th>Limits</th><th>Firmware notes</th></tr></thead>
    <tbody>{rt}</tbody>
  </table></div>

  <h2>Checked: already on PortMaster <small>{len(d['already_on_portmaster'])}</small></h2>
  <div class="xwrap"><table>
    <thead><tr><th>Screenshot</th><th>Game</th><th>Engine / port</th><th>Evidence</th></tr></thead>
    <tbody>{have}</tbody>
  </table></div>

  <p class="foot">Hand-curated; edit <a href="https://github.com/monkeyx-net/portmaster-trending/blob/main/data/curated.json">data/curated.json</a> to update. Sources: {srcs}</p>
</div>
<script>
const q = document.getElementById('q');
let min = 0, shimOnly = false;
const shimBtn = document.getElementById('shim');
function apply() {{
  const t = q.value.trim().toLowerCase();
  document.querySelectorAll('tr.row').forEach(r => {{
    const ok = (+r.dataset.fit >= min) && (!t || r.dataset.text.includes(t))
      && (!shimOnly || ['Helps', 'Partial', 'In use'].includes(r.dataset.shim));
    r.classList.toggle('hide', !ok);
  }});
}}
q.addEventListener('input', apply);
const body = document.querySelector('table.cand tbody');
const col = {{stars: 2, commit: 3, fit: 4}};
let last = '';
document.querySelectorAll('th.sort').forEach(th => th.addEventListener('click', () => {{
  const k = th.dataset.k, i = col[k];
  const dir = last === k ? 1 : -1;  // first click: highest / newest first
  last = last === k ? '' : k;
  const val = r => {{ const c = r.children[i]; return k === 'fit' ? +c.textContent : k === 'stars' ? +c.dataset.v : c.dataset.v; }};
  [...body.rows].sort((a, b) => (val(a) > val(b) ? 1 : val(a) < val(b) ? -1 : 0) * dir).forEach(r => body.appendChild(r));
}}));
shimBtn.addEventListener('click', () => {{
  shimOnly = !shimOnly; shimBtn.classList.toggle('on', shimOnly); apply();
}});
document.querySelectorAll('.tools button[data-f]').forEach(b => b.addEventListener('click', () => {{
  document.querySelectorAll('.tools button[data-f]').forEach(x => x.classList.remove('on'));
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
