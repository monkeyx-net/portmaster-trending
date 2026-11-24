#!/usr/bin/env python3
"""One-off backfill of older and smaller repos into build/backfill.html.
See crawler/backfill.py for details. Resumable: run again until nothing is left.

Env vars: GH_TOKEN, ANTHROPIC_API_KEY (not needed with --no-classify / --render-only)
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone

from crawler import backfill as bf
from crawler.classify import AuthError
from crawler.github import GitHub

ROOT = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=6)
    ap.add_argument("--min-stars", type=int, default=3)
    ap.add_argument("--max-minutes", type=float, default=0, help="stop and save after this long (0 = no limit)")
    ap.add_argument("--max-classify", type=int, default=None, help="cap Claude calls this run")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--no-classify", action="store_true")
    ap.add_argument("--render-only", action="store_true")
    ap.add_argument("--restart", action="store_true", help="run the searches again from scratch (keeps verdicts)")
    args = ap.parse_args()

    out = os.path.join(ROOT, "build", "backfill.html")
    d = bf.load()
    if args.render_only:
        n, left = bf.render(d, out)
        print(f"{out}: {n} candidates, {left} unclassified")
        return

    if not (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")):
        sys.exit("GH_TOKEN is not set")
    if not args.no_classify and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set")

    deadline = time.time() + args.max_minutes * 60 if args.max_minutes else float("inf")
    since = (datetime.now(timezone.utc) - timedelta(days=365 * args.years)).date().isoformat()
    s = d["settings"]
    if args.restart or s.get("min_stars") != args.min_stars or s.get("years") != args.years:
        d["done_queries"] = []
        d["settings"] = {"years": args.years, "min_stars": args.min_stars, "since": since, "started": bf.now_iso()}
    elif not s.get("since"):
        s["since"] = since

    gh = GitHub()
    gh.max_wait = 3700  # sit out the hourly REST limit instead of failing

    print("Discover")
    finished = bf.discover(gh, d, deadline)
    print(f"  {len(d['repos'])} repos{'' if finished else ' so far (time limit hit, resume next run)'}")

    n = bf.reuse_weekly(d, os.path.join(ROOT, "data", "watchlist.json"))
    if n:
        print(f"  reused {n} verdicts from the weekly watchlist")
    bf.save(d)

    if finished and not args.no_classify:
        print("Classify")
        try:
            done, fails = bf.run_classify(gh, d, deadline, args.workers, args.max_classify)
        except AuthError as ex:
            sys.exit(f"::error::{ex}\nCheck the ANTHROPIC_API_KEY secret (and that API credits are linked).")
        except RuntimeError as ex:
            sys.exit(f"::error::{ex}")
        print(f"  {done} classified, {fails} failed")

    d["settings"]["last_run"] = bf.now_iso()
    bf.save(d)
    n, left = bf.render(d, out)
    print(f"Done: {out}: {n} candidates, {left} left to classify")
    if left:
        print("Run again to continue.")


if __name__ == "__main__":
    main()
