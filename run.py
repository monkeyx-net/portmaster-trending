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


def rename(wl, old, new):
    """Move a renamed/transferred repo's entry from `old` to `new`. If both
    names already have entries (a duplicate from before ids were tracked),
    the one seen first keeps its history and the other is dropped."""
    e = wl["repos"].pop(old)
    other = wl["repos"].get(new)
    if other is not None and (other.get("first_seen") or "") <= (e.get("first_seen") or ""):
        print(f"  renamed {old} -> {new} (merged into existing entry)")
        return other
    print(f"  renamed {old} -> {new}")
    e["renamed_from"] = old
    e["full_name"] = new
    wl["repos"][new] = e
    return e


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

    by_id = {e["id"]: n for n, e in wl["repos"].items() if e.get("id")}
    new = []
    for name, data in found.items():
        old = by_id.get(data["id"])
        if old and old != name and old in wl["repos"]:
            rename(wl, old, name)
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
        data = gh.repo_by_id(e["id"]) if e.get("id") else gh.repo(e["full_name"])
        if data is None:
            e["gone"] = True
            continue
        s = slim(data)
        if s["full_name"] != e["full_name"] and e["full_name"] in wl["repos"]:
            e = rename(wl, e["full_name"], s["full_name"])
        e.pop("gone", None)
        e.update({k: v for k, v in s.items() if k != "stars"})
        record_stars(e, s["stars"], ts)
        e["last_checked"] = ts
    return len(tracked[: config.MAX_RECHECK])


def needs_classify(e):
    c = e.get("classification")
    return c is None or c.get("version", 1) < config.CLASSIFIER_VERSION


def run_classify(gh, wl):
    """Classify new repos, retry earlier failures, and redo verdicts from an
    older CLASSIFIER_VERSION. Returns the names classified this run."""
    pending = [n for n, e in wl["repos"].items() if needs_classify(e) and not e.get("gone")]
    # Never-classified repos first, then outdated verdicts; most stars first.
    pending.sort(key=lambda n: (wl["repos"][n].get("classification") is not None, -wl["repos"][n]["stars"]))
    done = []
    for name in pending[: config.MAX_CLASSIFY]:
        e = wl["repos"][name]
        try:
            readme = gh.readme(name)
            e["classification"] = classify(e, readme)
            e["classified_at"] = now_iso()
            done.append(name)
            c = e["classification"]
            print(f"  {'+' if c['relevant'] else '-'} {name}: {c['category']}")
        except AuthError as ex:
            sys.exit(f"::error::{ex}\nCheck the ANTHROPIC_API_KEY secret (and that API credits are linked).")
        except Exception as ex:
            print(f"  ! {name}: {ex}")
    if pending and not done:
        sys.exit("::error::Every Claude classification failed; see errors above.")
    left = len(pending) - len(done)
    if left:
        print(f"  {left} left for next run")
    return done


def is_candidate(e):
    c = e.get("classification") or {}
    return c.get("relevant") and not e.get("gone") and not e.get("archived")


def promote(wl):
    """New = candidates that have never been shown, however long ago they were
    discovered (e.g. classification failed or was capped on an earlier run).
    Rising = already-shown candidates that grew enough since last shown."""
    new, rising = [], []
    for e in wl["repos"].values():
        if not is_candidate(e):
            continue
        if not e.get("shown_at"):
            new.append(e)
            continue
        base = e.get("shown_stars", e["stars"])
        gain = e["stars"] - base
        if gain >= config.RISING_MIN_GAIN and (
            gain >= base * config.RISING_MIN_RATIO or gain >= config.RISING_HIGH_GAIN
        ):
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

    classified = []
    if not args.no_classify:
        print("Classify")
        classified = run_classify(gh, wl)
    excluded = sorted(
        (wl["repos"][n] for n in classified if not wl["repos"][n]["classification"].get("relevant")),
        key=lambda e: -e["stars"],
    )

    print("Promote")
    new, rising = promote(wl)
    print(f"  {len(new)} new candidates, {len(rising)} rising")

    print("Render")
    os.makedirs(BUILD, exist_ok=True)
    tracked = [e for e in wl["repos"].values() if is_candidate(e)]
    stats = {"scanned": len(found), "classified": len(classified)}
    render(new, rising, tracked, excluded, stats, os.path.join(BUILD, "index.html"))
    # Remember what each candidate looked like when shown, for next week's Rising.
    for e in new + rising:
        e["shown_stars"] = e["stars"]
        e["shown_at"] = ts

    print("Save")
    wl["runs"].append({"at": ts, "scanned": len(found), "new": len(new), "rising": len(rising), "classified": len(classified), "excluded": len(excluded)})
    del wl["runs"][:-52]
    save_watchlist(wl)
    print("Done: build/index.html")


if __name__ == "__main__":
    main()
