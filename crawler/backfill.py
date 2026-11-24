"""One-off backfill: search every repo created in the last N years with at least
M stars, classify each with Claude, and render build/backfill.html.

Unlike the weekly crawl (14-day window, 5+ stars), this looks at older and
smaller projects, which is where most SDL games sit. It is resumable: progress
is saved to data/backfill.json, and each run stops after --max-minutes so it
fits a GitHub Actions job. Run it again until "left" is 0.

  python backfill.py                      # 6 years, 3+ stars
  python backfill.py --render-only        # just rebuild the page
"""

import html
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone

from .classify import CATEGORIES, AuthError, classify
from .config import CLAUDE_MODEL
from . import portmaster
from .report import STYLE, ported_section, repo_pairs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "backfill.json")

ORDER = [c for c in CATEGORIES if c != "not relevant"]

# SDL and games only: the weekly crawl's emulator, decompilation and
# reimplementation searches are left out to keep the backfill small. The
# keyword searches catch SDL games whose authors never added topic tags.
SDL_QUERIES = [
    "topic:sdl2",
    "topic:sdl",
    "SDL2 game in:name,description",
    "sdl2 in:name,description,topics",
    "sdl in:name,description,topics",
    "sdl2 game in:name,description,readme",
    "sdl game in:name,description,readme",
]
GAME_QUERIES = [
    "topic:game language:C",
    "topic:game language:C++",
    "topic:game language:Rust",
    "topic:love2d",
    "topic:godot topic:game",
    "\"source port\" in:name,description",
]
QUERIES = SDL_QUERIES + GAME_QUERIES


# Fields kept for every repo. Rejected repos keep less, so the file stays small.
KEEP = ("id", "full_name", "url", "description", "language", "topics", "license",
        "stars", "created_at", "pushed_at", "archived")
KEEP_REJECTED = ("id", "full_name", "url", "language", "stars", "created_at")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load():
    if os.path.exists(DATA):
        with open(DATA, encoding="utf-8") as f:
            return json.load(f)
    return {"settings": {}, "done_queries": [], "repos": {}}


def save(d):
    """One repo per line: diffs stay readable and the file stays compact."""
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    tmp = DATA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        head = {k: v for k, v in d.items() if k != "repos"}
        f.write("{\n")
        for k in sorted(head):
            f.write(f"{json.dumps(k)}: {json.dumps(head[k], sort_keys=True)},\n")
        f.write('"repos": {\n')
        names = sorted(d["repos"])
        for i, n in enumerate(names):
            sep = "," if i < len(names) - 1 else ""
            f.write(f"{json.dumps(n)}: {json.dumps(d['repos'][n], sort_keys=True, ensure_ascii=False)}{sep}\n")
        f.write("}\n}\n")
    os.replace(tmp, DATA)


def is_sdl(e):
    text = " ".join([e.get("description") or "", " ".join(e.get("topics") or []), e["full_name"]]).lower()
    return bool(re.search(r"\bsdl[123]?\b|libsdl", text)) or any("sdl" in q.lower() for q in e.get("hits", []))


# ---------------------------------------------------------------- discover

def _windows(gh, query, start, end):
    """Split [start, end] into created-date windows of at most 1000 results,
    since GitHub search never returns more than that for one query."""
    q = f"{query} created:{start.isoformat()}..{end.isoformat()}"
    data = gh.search_page(q, 1)
    total = data.get("total_count", 0)
    if total > 1000 and start < end:
        mid = start + (end - start) // 2
        yield from _windows(gh, query, start, mid)
        yield from _windows(gh, query, mid + timedelta(days=1), end)
        return
    if total > 1000:
        print(f"    note: {total} results on {start} alone, keeping the top 1000")
    yield q, total, data


def discover(gh, d, deadline):
    s = d["settings"]
    start = date.fromisoformat(s["since"])
    end = datetime.now(timezone.utc).date()
    for query in QUERIES:
        if query in d["done_queries"]:
            continue
        if time.time() > deadline:
            return False
        full = f"{query} stars:>={s['min_stars']} fork:false"
        added = 0
        for q, total, first in _windows(gh, full, start, end):
            pages = [first] + [gh.search_page(q, p) for p in range(2, min(10, -(-total // 100)) + 1)]
            for page in pages:
                for it in page.get("items", []):
                    name = it["full_name"]
                    e = d["repos"].get(name)
                    if e is None:
                        e = d["repos"][name] = {"classification": None, "hits": []}
                        added += 1
                    if e.get("classification") is None or e["classification"].get("relevant"):
                        e.update(_slim(it, KEEP))
                    else:
                        e["stars"] = it.get("stargazers_count", 0)
                    if query not in e["hits"]:
                        e["hits"].append(query)
        d["done_queries"].append(query)
        print(f"  {added:5d} new  {query}")
        save(d)
    return True


def _slim(it, fields):
    out = {
        "id": it.get("id"),
        "full_name": it["full_name"],
        "url": it["html_url"],
        "description": (it.get("description") or "")[:300],
        "language": it.get("language"),
        "topics": (it.get("topics") or [])[:12],
        "license": (it.get("license") or {}).get("spdx_id"),
        "stars": it.get("stargazers_count", 0),
        "created_at": it.get("created_at"),
        "pushed_at": it.get("pushed_at"),
        "archived": it.get("archived", False),
    }
    return {k: out[k] for k in fields}


# ---------------------------------------------------------------- classify

def reuse_weekly(d, watchlist_path):
    """Copy verdicts the weekly crawler already paid for."""
    if not os.path.exists(watchlist_path):
        return 0
    with open(watchlist_path, encoding="utf-8") as f:
        wl = json.load(f)["repos"]
    by_id = {e.get("id"): e for e in wl.values() if e.get("id") and e.get("classification")}
    n = 0
    for name, e in d["repos"].items():
        if e.get("classification") is None:
            w = by_id.get(e.get("id")) or (wl.get(name) if (wl.get(name) or {}).get("classification") else None)
            if w:
                e["classification"] = w["classification"]
                _trim(e)
                n += 1
    return n


def _trim(e):
    """Rejected repos keep only what the page and a re-run need."""
    c = e["classification"]
    if not c.get("relevant"):
        for k in list(e):
            if k not in KEEP_REJECTED and k not in ("classification", "hits"):
                del e[k]
        e["classification"] = {k: c[k] for k in ("relevant", "category", "reason", "version") if k in c}


def run_classify(gh, d, deadline, workers=4, limit=None):
    pending = [n for n, e in d["repos"].items() if e.get("classification") is None]
    pending.sort(key=lambda n: -d["repos"][n].get("stars", 0))
    if limit is not None:
        pending = pending[:limit]
    print(f"  {len(pending)} to classify")

    def work(name):
        e = d["repos"][name]
        return name, classify(e, gh.readme(name))

    done = fails = 0
    with ThreadPoolExecutor(workers) as pool:
        it = iter(pending)
        futures = set()
        for name in it:
            futures.add(pool.submit(work, name))
            if len(futures) >= workers * 2:
                break
        while futures:
            fut = next(as_completed(futures))
            futures.remove(fut)
            try:
                name, c = fut.result()
                e = d["repos"][name]
                e["classification"] = c
                e["classified_at"] = now_iso()
                _trim(e)
                done += 1
                print(f"  {'+' if c['relevant'] else '-'} {name}: {c['category']}")
            except AuthError:
                save(d)
                raise
            except Exception as ex:
                fails += 1
                print(f"  ! {ex}")
            if done and done % 50 == 0:
                save(d)
            if time.time() < deadline:
                nxt = next(it, None)
                if nxt:
                    futures.add(pool.submit(work, nxt))
    save(d)
    if pending and not done:
        raise RuntimeError("Every Claude classification failed; see errors above.")
    return done, fails


# ---------------------------------------------------------------- render

def esc(s):
    return html.escape(str(s or ""))


def card(r):
    c = r["classification"]
    tags = []
    if r.get("language"):
        tags.append(f'<span class="tag">{esc(r["language"])}</span>')
    if r.get("license"):
        tags.append(f'<span class="tag">{esc(r["license"])}</span>')
    if r.get("sdl"):
        tags.append('<span class="tag sdl">SDL</span>')
    if c.get("needs_assets"):
        tags.append('<span class="tag warn">needs game data</span>')
    if r.get("archived"):
        tags.append('<span class="tag warn">archived</span>')
    text = " ".join([r["full_name"], r.get("description") or "", c.get("summary") or "", r.get("language") or ""]).lower()
    created = (r.get("created_at") or "")[:4]
    pushed = (r.get("pushed_at") or "")[:10]
    return f"""<article class="card" data-cat="{esc(c['category'])}" data-port="{esc(c.get('portability'))}" data-sdl="{1 if r.get('sdl') else 0}" data-assets="{1 if c.get('needs_assets') else 0}" data-stars="{r.get('stars', 0)}" data-pushed="{esc(pushed)}" data-created="{esc(r.get('created_at') or '')}" data-text="{esc(text)}">
  <header><a href="{esc(r['url'])}" target="_blank" rel="noopener">{esc(r['full_name'])}</a><span class="stars">★ {r.get('stars', 0)}</span></header>
  <p class="sum">{esc(c.get('summary'))}</p>
  <p class="why">{esc(c.get('reason'))}</p>
  <p class="dates">created {esc(created)} · last push {esc(pushed)}</p>
  <footer><span class="port p-{esc(c.get('portability'))}">port: {esc(c.get('portability'))}</span><span class="tag cat">{esc(c['category'])}</span>{''.join(tags)}</footer>
</article>"""


def render(d, path):
    s = d.get("settings", {})
    repos = list(d["repos"].values())
    classified = [e for e in repos if e.get("classification")]
    relevant = [e for e in classified if e["classification"].get("relevant")]
    relevant, ported = portmaster.split(relevant, portmaster.load())
    for e in relevant:
        e["sdl"] = is_sdl(e)
    relevant.sort(key=lambda e: -e.get("stars", 0))
    left = len(repos) - len(classified)
    sdl_count = sum(1 for e in relevant if e["sdl"])
    cats = "".join(f'<button data-f="{esc(c)}">{esc(c)}</button>' for c in ORDER)
    years = s.get("years", "?")
    progress = f" {left} repos are still waiting to be classified; the page fills in as the backfill runs." if left else ""
    now = datetime.now(timezone.utc).strftime("%d %b %Y")

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PortMaster Backfill</title>
<style>
{STYLE}
.dates {{ margin:0; color:var(--dim); font-size:12px; }}
.tag.sdl {{ color:var(--ok); border-color:#2f5a3c; }}
.tools select, .tools label {{ background:var(--panel); border:1px solid var(--line); color:var(--dim); border-radius:8px; padding:5px 8px; font:13px system-ui,sans-serif; }}
.tools label {{ display:flex; gap:5px; align-items:center; cursor:pointer; }}
#more {{ display:block; margin:18px auto; background:var(--panel); border:1px solid var(--line); color:var(--fg); border-radius:8px; padding:8px 18px; cursor:pointer; font:inherit; }}
nav a {{ color:var(--acc); margin-right:14px; }}
</style>
</head>
<body>
<div class="wrap">
  <nav><a href="./">← Weekly report</a><a href="curated.html">Hand-picked candidates</a></nav>
  <h1>PortMaster <span>Backfill</span></h1>
  <p class="meta">Every GitHub repo created since {esc(s.get('since'))} (about {esc(years)} years) with {esc(s.get('min_stars'))}+ stars that matched SDL and game searches (including SDL mentions in READMEs), sorted by Claude. Unlike the weekly report, this includes older and smaller projects.{esc(progress)} Updated {now}.</p>
  <div class="stats">
    <div class="stat"><b>{len(repos)}</b><span>repos found</span></div>
    <div class="stat"><b>{len(classified)}</b><span>classified</span></div>
    <div class="stat"><b>{len(relevant)}</b><span>candidates</span></div>
    <div class="stat"><b>{sdl_count}</b><span>SDL candidates</span></div>
    <div class="stat"><b>{len(ported)}</b><span>already on PortMaster</span></div>
  </div>
  <div class="tools">
    <input id="q" type="search" placeholder="Filter by name, language or text…">
    <label><input type="checkbox" id="sdl"> SDL only</label>
    <label><input type="checkbox" id="noassets"> no game data needed</label>
    <select id="port"><option value="">any portability</option><option>high</option><option>medium</option><option>low</option><option>unknown</option></select>
    <select id="sort"><option value="stars">most stars</option><option value="pushed">recently pushed</option><option value="created">newest</option></select>
    <button data-f="" class="on">all</button>{cats}
  </div>
  <p class="empty" id="count"></p>
  <div class="grid" id="grid">{''.join(card(e) for e in relevant)}</div>
  <button id="more">Show more</button>
  {ported_section(repo_pairs(ported))}
  <p class="foot">Classified by {esc(CLAUDE_MODEL)}. Repos Claude rejected are not listed, and repos that match a port in PortMaster's ports.json are hidden. Data: <a href="https://github.com/monkeyx-net/portmaster-trending/blob/main/data/backfill.json">data/backfill.json</a>.</p>
</div>
<script>
const PAGE = 120;
const grid = document.getElementById('grid');
const all = [...grid.children];
const q = document.getElementById('q'), sdl = document.getElementById('sdl'), noassets = document.getElementById('noassets');
const port = document.getElementById('port'), sort = document.getElementById('sort'), more = document.getElementById('more'), count = document.getElementById('count');
let cat = '', shown = PAGE, sorted = all;
function resort() {{
  const k = sort.value;
  sorted = [...all].sort((a, b) => k === 'stars' ? b.dataset.stars - a.dataset.stars : (b.dataset[k] || '').localeCompare(a.dataset[k] || ''));
  sorted.forEach(c => grid.appendChild(c));
}}
function apply() {{
  const t = q.value.trim().toLowerCase();
  let n = 0;
  for (const c of sorted) {{
    const ok = (!cat || c.dataset.cat === cat) && (!t || c.dataset.text.includes(t))
      && (!sdl.checked || c.dataset.sdl === '1') && (!noassets.checked || c.dataset.assets === '0')
      && (!port.value || c.dataset.port === port.value);
    if (ok) n++;
    c.classList.toggle('hide', !ok || n > shown);
  }}
  count.textContent = n + ' matching candidates';
  more.classList.toggle('hide', n <= shown);
}}
function reset() {{ shown = PAGE; apply(); }}
q.addEventListener('input', reset);
[sdl, noassets, port].forEach(el => el.addEventListener('change', reset));
sort.addEventListener('change', () => {{ resort(); reset(); }});
more.addEventListener('click', () => {{ shown += PAGE; apply(); }});
document.querySelectorAll('.tools button').forEach(b => b.addEventListener('click', () => {{
  document.querySelectorAll('.tools button').forEach(x => x.classList.remove('on'));
  b.classList.add('on'); cat = b.dataset.f; reset();
}}));
apply();
</script>
</body>
</html>"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    for e in relevant:
        e.pop("sdl", None)
    return len(relevant), left


def render_if_present(path):
    """Used by the weekly run so the page survives each Pages deploy."""
    if os.path.exists(DATA):
        render(load(), path)
        return True
    return False
