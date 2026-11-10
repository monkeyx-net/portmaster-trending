#!/usr/bin/env python3
"""Weekly crawler: find new PortMaster porting candidates on GitHub, classify
them with Claude, and render build/index.html.

Steps: discover -> recheck -> classify -> promote -> render -> save.

Env vars:
  GH_TOKEN           GitHub token (search + contents read)
  ANTHROPIC_API_KEY  Claude API key
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from crawler import config
from crawler.classify import AuthError, classify
from crawler.github import GitHub, slim
from crawler.report import render

ROOT = os.path.dirname(os.path.abspath(__file__))
WATCHLIST = os.path.join(ROOT, "data", "watchlist.json")
BUILD = os.path.join(ROOT, "build")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_watchlist():
    if os.path.exists(WATCHLIST):
        with open(WATCHLIST, encoding="utf-8") as f:
            return json.load(f)
    return {"repos": {}, "runs": []}


def save_watchlist(wl):
    os.makedirs(os.path.dirname(WATCHLIST), exist_ok=True)
    with open(WATCHLIST, "w", encoding="utf-8") as f:
        json.dump(wl, f, indent=1, sort_keys=True)
        f.write("\n")


def record_stars(entry, stars, ts):
    entry["stars"] = stars
    hist = entry.setdefault("star_history", [])
    if not hist or hist[-1][1] != stars:
        hist.append([ts[:10], stars])
        del hist[:-30]


def discover(gh, wl, ts):
    since = (datetime.now(timezone.utc) - timedelta(days=config.LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    found = {}
    for q in config.SEARCH_QUERIES:
        query = q.format(since=since) + f" stars:>={config.MIN_STARS_NEW} fork:false archived:false"
        try:
            items = gh.search_repos(query, config.PER_QUERY)
        except Exception as e:  # keep going if one query fails
            print(f"  search failed: {query!r}: {e}")
            continue
        print(f"  {len(items):3d}  {query}")
        for it in items:
            found[it["full_name"]] = slim(it)

    new = []
    for name, data in found.items():
        entry = wl["repos"].get(name)
        if entry is None:
            entry = dict(data, first_seen=ts, classification=None)
            wl["repos"][name] = entry
            new.append(name)
        else:
            entry.update({k: v for k, v in data.items() if k != "stars"})
        record_stars(entry, data["stars"], ts)
        entry["last_checked"] = ts
    return found, new


def recheck(gh, wl, ts, skip):
    tracked = [
        e for n, e in wl["repos"].items()
        if n not in skip and (e.get("classification") or {}).get("relevant")
    ]
    tracked.sort(key=lambda e: e.get("last_checked") or "")
    for e in tracked[: config.MAX_RECHECK]:
        data = gh.repo(e["full_name"])
        if data is None:
            e["gone"] = True
            continue
        s = slim(data)
        e.update({k: v for k, v in s.items() if k != "stars"})
        record_stars(e, s["stars"], ts)
        e["last_checked"] = ts
    return len(tracked[: config.MAX_RECHECK])


def run_classify(gh, wl, names):
    pending = [n for n in names if wl["repos"][n].get("classification") is None]
    # Also retry earlier failures.
    pending += [n for n, e in wl["repos"].items() if e.get("classification") is None and n not in pending]
    pending.sort(key=lambda n: -wl["repos"][n]["stars"])
    done = 0
    for name in pending[: config.MAX_CLASSIFY]:
        e = wl["repos"][name]
        try:
            readme = gh.readme(name)
            e["classification"] = classify(e, readme)
            e["classified_at"] = now_iso()
            done += 1
            c = e["classification"]
            print(f"  {'+' if c['relevant'] else '-'} {name}: {c['category']}")
        except AuthError as ex:
            sys.exit(f"::error::{ex}\nCheck the ANTHROPIC_API_KEY secret (and that API credits are linked).")
        except Exception as ex:
            print(f"  ! {name}: {ex}")
    if pending and not done:
        sys.exit("::error::Every Claude classification failed; see errors above.")
    return done


def is_candidate(e):
    c = e.get("classification") or {}
    return c.get("relevant") and not e.get("gone") and not e.get("archived")


def promote(wl, new_names, ts):
    new = [wl["repos"][n] for n in new_names if is_candidate(wl["repos"][n])]
    rising = []
    for n, e in wl["repos"].items():
        if n in new_names or not is_candidate(e):
            continue
        base = e.get("shown_stars", e.get("star_history", [[None, e["stars"]]])[0][1])
        gain = e["stars"] - base
        if gain >= config.RISING_MIN_GAIN and gain >= base * config.RISING_MIN_RATIO:
            e["shown_stars"] = base  # used for the "+N" label, updated below
            rising.append(e)
    rising.sort(key=lambda e: -(e["stars"] - e["shown_stars"]))
    return new, rising


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-classify", action="store_true", help="skip Claude calls")
    args = ap.parse_args()

    if not (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")):
        sys.exit("GH_TOKEN is not set")
    if not args.no_classify and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set")

    ts = now_iso()
    gh = GitHub()
    wl = load_watchlist()

    print("Discover")
    found, new_names = discover(gh, wl, ts)
    print(f"  {len(found)} matched, {len(new_names)} new")

    print("Recheck")
    rechecked = recheck(gh, wl, ts, set(found))
    print(f"  {rechecked} tracked repos refreshed")

    classified = 0
    if not args.no_classify:
        print("Classify")
        classified = run_classify(gh, wl, new_names)

    print("Promote")
    new, rising = promote(wl, new_names, ts)
    print(f"  {len(new)} new candidates, {len(rising)} rising")

    print("Render")
    os.makedirs(BUILD, exist_ok=True)
    tracked = [e for e in wl["repos"].values() if is_candidate(e)]
    stats = {"scanned": len(found), "classified": classified}
    render(new, rising, tracked, stats, os.path.join(BUILD, "index.html"))
    # Remember what each candidate looked like when shown, for next week's Rising.
    for e in new + rising:
        e["shown_stars"] = e["stars"]
        e["shown_at"] = ts

    print("Save")
    wl["runs"].append({"at": ts, "scanned": len(found), "new": len(new), "rising": len(rising), "classified": classified})
    del wl["runs"][:-52]
    save_watchlist(wl)
    print("Done: build/index.html")


if __name__ == "__main__":
    main()
