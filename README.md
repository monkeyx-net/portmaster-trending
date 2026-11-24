# PortMaster Trending

Weekly crawler that scouts GitHub for new [PortMaster](https://portmaster.games) porting candidates: open-source games, SDL1/SDL2 games and source ports, engine reimplementations, decompilations and emulators. Candidates are classified by **Claude (Haiku 5.5)** and published as a report on GitHub Pages.

**Report:** https://monkeyx-net.github.io/portmaster-trending/

A Claude-based take on [Cebion/gh_trending_reports](https://github.com/Cebion/gh_trending_reports), which uses Gemini.

## Hand-picked candidates

Alongside the weekly crawl, [`data/curated.json`](data/curated.json) holds a hand-checked list of open-source ports and remakes, scored for ArkOS/dArkOS, muOS/Knulli and AmberELEC/JELOS/uOS against PortMaster's limits (GLES only, OpenGL 2.1 via gl4es, no Vulkan, often 1 GB RAM), plus notes on Westonpack, gl4es and the [SDL3-over-SDL2 shim](https://github.com/bmdhacks/SDL/tree/sdl2-backend) (an *SDL3 shim* column marks the SDL3 projects it can serve on SDL2-only firmwares) and a list of projects already on PortMaster. It is rendered to `build/curated.html` on every run and published at https://monkeyx-net.github.io/portmaster-trending/curated.html.

Each run also refreshes every curated project's star count and last commit date (default branch) from the GitHub API and commits them back to the JSON. Both tables show a screenshot where one is available: a hand-set `screenshot` URL wins; otherwise each run picks `screenshot_auto` from the PortMaster port folder named in `pm_port` (`PortMaster-New/<dir>` or `PortMaster-MV-New/<dir>`), or failing that the first non-badge, non-logo image in the project's README, then the image on the matching PortMaster suggestion. Images are hotlinked, not stored here.

Every run also downloads PortMaster's suggestion list ([`suggestions_new.json`](https://github.com/PortsMaster/PortMaster-Wiki-New/blob/main/docs/assets/json/suggestions_new.json) in PortMaster-Wiki-New) and matches each candidate to a suggestion by its GitHub repo or exact title, storing the status, feasibility and votes as `pm_suggestion`. Where the names differ, pin the match with `suggestion_id`. Edit the JSON to change the list; preview with `python -m crawler.curated`.

## Backfill: older and smaller projects

The weekly crawl only sees repos created in the last 14 days with 5+ stars, which misses most SDL games: they are older, rarely tagged, and slow to collect stars. `backfill.py` is a one-off pass over every repo created in the last **6 years** with **3+ stars** that matches the weekly searches plus keyword searches for `sdl`/`sdl2` in names, descriptions and READMEs. Each repo is classified by Claude like the weekly ones (verdicts already in the watchlist are reused) and the candidates are published at https://monkeyx-net.github.io/portmaster-trending/backfill.html, with filters for SDL, portability, game data and category.

GitHub search returns at most 1,000 results per query, so each query is split into date ranges until every range fits. The run is resumable: progress goes to [`data/backfill.json`](data/backfill.json) (rejected repos keep only a short reason), and `--max-minutes` stops it cleanly. Run the **Backfill** workflow from the Actions tab, and run it again until its log says `0 left to classify`. Expect roughly 20,000 repos, a few hours of GitHub API time (use a `GH_TOKEN` personal token: the built-in token's 1,000 requests an hour would take days) and about $8–10 of Haiku calls. The weekly run re-renders the page from the JSON so it stays on the site.

```sh
python backfill.py --max-minutes 60     # resume, stop after an hour
python backfill.py --render-only        # rebuild build/backfill.html
```

## How it works

`run.py` runs these steps in order:

1. **Discover**: search the GitHub API for recently created repos matching game/SDL/emulator/decomp topics and keywords (`crawler/config.py`), paging up to `PER_QUERY` results per query.
2. **Recheck**: refresh star counts for repos already tracked as candidates. Repos are looked up by their numeric GitHub id, so renames and transfers are followed instead of creating a duplicate entry.
3. **Classify**: send each new repo's metadata and README excerpt to Claude, which decides whether it's relevant, its category, how portable it looks, and whether it needs original game data. Tutorials, unrelated tools and trivial clones are filtered out. Earlier failures, and repos left over from the `MAX_CLASSIFY` cap, are retried. Bumping `CLASSIFIER_VERSION` after a prompt change redoes older verdicts.
4. **Promote**: any candidate that has never been shown appears as **New**, even if it was discovered on an earlier run. Shown candidates that gained at least 10 stars and either grew 50% or gained 50 stars since they last appeared show up as **Rising**.
5. **Render**: write `build/index.html`, including a collapsed **Excluded this run** table of rejected repos and Claude's reason, for spotting wrong rejections.
6. **Save**: commit `data/watchlist.json`, which records every repo seen, its star history and its classification, so slow-burn projects can resurface later.

Only the Python standard library is used; there are no dependencies.

## Setup

1. **Secrets** (Settings → Secrets and variables → Actions):
   - `ANTHROPIC_API_KEY`: your Claude API key from console.anthropic.com.
   - `GH_TOKEN` (optional): a personal access token. Without it, the workflow's built-in token is used, which works but has a lower search rate limit.
2. **Pages** (Settings → Pages): set *Source* to **GitHub Actions**.
3. Run the **Weekly report** workflow once from the Actions tab. After that it runs every Monday at 06:17 UTC.

## Run locally

```sh
export GH_TOKEN=...
export ANTHROPIC_API_KEY=...
python run.py            # or: python run.py --no-classify
open build/index.html
```

## Cost

Each new repo is one Haiku call with a ~4 KB README excerpt, roughly a fraction of a cent. `MAX_CLASSIFY` in `crawler/config.py` caps calls per run (default 120).
