"""Render the weekly report as a single self-contained HTML page."""

import html
import json
from datetime import datetime, timezone

from .classify import CATEGORIES
from .config import CLAUDE_MODEL

ORDER = [c for c in CATEGORIES if c != "not relevant"]


def esc(s):
    return html.escape(str(s or ""))


def card(r, badge=None):
    c = r["classification"]
    gain = ""
    if badge == "rising":
        gain = f'<span class="gain">+{r["stars"] - r.get("shown_stars", 0)}★</span>'
    tags = []
    if r.get("language"):
        tags.append(f'<span class="tag">{esc(r["language"])}</span>')
    if r.get("license"):
        tags.append(f'<span class="tag">{esc(r["license"])}</span>')
    if c.get("needs_assets"):
        tags.append('<span class="tag warn">needs game data</span>')
    return f"""
<article class="card" data-cat="{esc(c['category'])}" data-text="{esc((r['full_name'] + ' ' + r.get('description','') + ' ' + c.get('summary','')).lower())}">
  <header>
    <a href="{esc(r['url'])}" target="_blank" rel="noopener">{esc(r['full_name'])}</a>
    <span class="stars">★ {r['stars']}</span>{gain}
  </header>
  <p class="sum">{esc(c.get('summary'))}</p>
  <p class="why">{esc(c.get('reason'))}</p>
  <footer>
    <span class="port p-{esc(c.get('portability'))}">port: {esc(c.get('portability'))}</span>
    <span class="tag cat">{esc(c['category'])}</span>
    {''.join(tags)}
  </footer>
</article>"""


def section(title, repos, badge=None, empty="Nothing this week."):
    if not repos:
        return f'<section><h2>{esc(title)}</h2><p class="empty">{esc(empty)}</p></section>'
    return f'<section><h2>{esc(title)} <small>{len(repos)}</small></h2><div class="grid">{"".join(card(r, badge) for r in repos)}</div></section>'


def excluded_section(repos):
    """Repos Claude rejected this run, collapsed, so wrong rejections are easy to spot."""
    if not repos:
        return ""
    rows = "".join(
        f'''<tr class="xrow" data-text="{esc((r['full_name'] + ' ' + r.get('description','') + ' ' + r['classification'].get('reason','')).lower())}">
  <td><a href="{esc(r['url'])}" target="_blank" rel="noopener">{esc(r['full_name'])}</a></td>
  <td class="num">{r['stars']}</td>
  <td>{esc(r['classification'].get('category'))}</td>
  <td>{esc(r['classification'].get('reason'))}</td>
</tr>'''
        for r in repos
    )
    return f'''<section><details><summary><h2>Excluded this run <small>{len(repos)}</small></h2></summary>
<p class="empty">Repos Claude classified as not relevant this run, with its reason. Use this to spot wrong rejections.</p>
<div class="xwrap"><table class="xtable"><thead><tr><th>Repo</th><th>★</th><th>Category</th><th>Reason</th></tr></thead><tbody>{rows}</tbody></table></div>
</details></section>'''


def render(new, rising, tracked, excluded, stats, path):
    now = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    by_cat = sorted(new, key=lambda r: (ORDER.index(r["classification"]["category"]) if r["classification"]["category"] in ORDER else 99, -r["stars"]))
    tracked = sorted(tracked, key=lambda r: -r["stars"])
    filters = "".join(f'<button data-f="{esc(c)}">{esc(c)}</button>' for c in ORDER)

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PortMaster Trending: weekly porting candidates</title>
<style>
:root {{ --bg:#0f1115; --panel:#181b22; --line:#262b36; --fg:#e6e8ee; --dim:#9aa3b2; --acc:#d97757; --ok:#5fb67a; --mid:#d6b04a; --bad:#d26a6a; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }}
.wrap {{ max-width:1200px; margin:0 auto; padding:28px 18px 60px; }}
h1 {{ margin:0; font-size:28px; letter-spacing:-.01em; }}
h1 span {{ color:var(--acc); }}
.meta {{ color:var(--dim); margin:6px 0 18px; }}
.stats {{ display:flex; flex-wrap:wrap; gap:10px; margin-bottom:22px; }}
.stat {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:10px 14px; min-width:120px; }}
.stat b {{ display:block; font-size:22px; }}
.stat span {{ color:var(--dim); font-size:13px; }}
.tools {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:8px; position:sticky; top:0; background:var(--bg); padding:10px 0; z-index:2; }}
.tools input {{ flex:1 1 220px; background:var(--panel); border:1px solid var(--line); color:var(--fg); border-radius:8px; padding:8px 10px; font:inherit; }}
.tools button {{ background:var(--panel); border:1px solid var(--line); color:var(--dim); border-radius:999px; padding:5px 11px; cursor:pointer; font:13px system-ui,sans-serif; }}
.tools button.on {{ color:var(--bg); background:var(--acc); border-color:var(--acc); }}
h2 {{ font-size:19px; margin:28px 0 12px; border-bottom:1px solid var(--line); padding-bottom:6px; }}
h2 small {{ color:var(--dim); font-weight:400; font-size:14px; margin-left:6px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:12px; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px; display:flex; flex-direction:column; gap:6px; }}
.card header {{ display:flex; gap:8px; align-items:baseline; flex-wrap:wrap; }}
.card header a {{ color:var(--fg); font-weight:600; text-decoration:none; word-break:break-all; }}
.card header a:hover {{ color:var(--acc); }}
.stars {{ color:var(--mid); font-size:13px; margin-left:auto; white-space:nowrap; }}
.gain {{ color:var(--ok); font-size:13px; font-weight:600; }}
.sum {{ margin:0; }}
.why {{ margin:0; color:var(--dim); font-size:13px; }}
.card footer {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:auto; padding-top:6px; }}
.tag, .port {{ font-size:12px; border:1px solid var(--line); border-radius:6px; padding:1px 7px; color:var(--dim); }}
.tag.cat {{ color:var(--acc); border-color:#5a3a2e; }}
.tag.warn {{ color:var(--mid); }}
.p-high {{ color:var(--ok); border-color:#2f5a3c; }}
.p-medium {{ color:var(--mid); border-color:#5c4f25; }}
.p-low {{ color:var(--bad); border-color:#5c2e2e; }}
.empty {{ color:var(--dim); }}
.hide {{ display:none !important; }}
details summary {{ cursor:pointer; list-style:none; }}
details summary::-webkit-details-marker {{ display:none; }}
details summary h2::before {{ content:"▸ "; color:var(--dim); }}
details[open] summary h2::before {{ content:"▾ "; }}
.xwrap {{ overflow-x:auto; }}
.xtable {{ width:100%; border-collapse:collapse; font-size:13px; }}
.xtable th, .xtable td {{ text-align:left; vertical-align:top; padding:6px 8px; border-bottom:1px solid var(--line); }}
.xtable th {{ color:var(--dim); font-weight:600; }}
.xtable td a {{ color:var(--fg); text-decoration:none; word-break:break-all; }}
.xtable td a:hover {{ color:var(--acc); }}
.xtable td.num {{ color:var(--mid); white-space:nowrap; }}
.xtable td:last-child {{ color:var(--dim); }}
.foot {{ color:var(--dim); font-size:13px; margin-top:40px; border-top:1px solid var(--line); padding-top:12px; }}
.foot a {{ color:var(--dim); }}
</style>
</head>
<body>
<div class="wrap">
  <h1>PortMaster <span>Trending</span></h1>
  <p class="meta">New GitHub projects that could be ported to retro handhelds, sorted by Claude. Updated {now}.</p>
  <div class="stats">
    <div class="stat"><b>{stats['scanned']}</b><span>repos scanned</span></div>
    <div class="stat"><b>{stats['classified']}</b><span>classified this run</span></div>
    <div class="stat"><b>{len(new)}</b><span>new candidates</span></div>
    <div class="stat"><b>{len(rising)}</b><span>rising</span></div>
    <div class="stat"><b>{len(tracked)}</b><span>tracked in total</span></div>
    <div class="stat"><b>{len(excluded)}</b><span>excluded this run</span></div>
  </div>
  <div class="tools">
    <input id="q" type="search" placeholder="Filter by name or text…">
    <button data-f="" class="on">all</button>{filters}
  </div>
  {section("Rising", rising, "rising", "No tracked repo grew enough this week.")}
  {section("New this week", by_cat)}
  {section("All tracked candidates", tracked, empty="Nothing tracked yet.")}
  {excluded_section(excluded)}
  <p class="foot">Classified by {esc(CLAUDE_MODEL)}. Rising = tracked repos that gained enough stars since they last appeared. Excluded = repos rejected this run. Data: <a href="https://github.com/monkeyx-net/portmaster-trending">monkeyx-net/portmaster-trending</a>. Inspired by <a href="https://github.com/Cebion/gh_trending_reports">Cebion/gh_trending_reports</a>.</p>
</div>
<script>
const q = document.getElementById('q');
let cat = '';
function apply() {{
  const t = q.value.trim().toLowerCase();
  document.querySelectorAll('.card').forEach(c => {{
    const ok = (!cat || c.dataset.cat === cat) && (!t || c.dataset.text.includes(t));
    c.classList.toggle('hide', !ok);
  }});
  // Excluded rows follow the text search only; category buttons are for candidates.
  document.querySelectorAll('.xrow').forEach(r => {{
    r.classList.toggle('hide', !!t && !r.dataset.text.includes(t));
  }});
}}
q.addEventListener('input', apply);
document.querySelectorAll('.tools button').forEach(b => b.addEventListener('click', () => {{
  document.querySelectorAll('.tools button').forEach(x => x.classList.remove('on'));
  b.classList.add('on'); cat = b.dataset.f; apply();
}}));
</script>
</body>
</html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
