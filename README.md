# PortMaster Trending

Weekly crawler that scouts GitHub for new [PortMaster](https://portmaster.games) porting candidates: open-source games, SDL1/SDL2 games and source ports, engine reimplementations, decompilations and emulators. Candidates are classified by **Claude (Haiku 5.5)** and published as a report on GitHub Pages.

**Report:** https://monkeyx-net.github.io/portmaster-trending/

A Claude-based take on [Cebion/gh_trending_reports](https://github.com/Cebion/gh_trending_reports), which uses Gemini.

## How it works

`run.py` runs these steps in order:

1. **Discover**: search the GitHub API for recently created repos matching game/SDL/emulator/decomp topics and keywords (`crawler/config.py`).
2. **Recheck**: refresh star counts for repos already tracked as candidates.
3. **Classify**: send each new repo's metadata and README excerpt to Claude, which decides whether it's relevant, its category, how portable it looks, and whether it needs original game data. Tutorials, unrelated tools and trivial clones are filtered out.
4. **Promote**: tracked repos whose stars grew enough since they last appeared show up as **Rising**.
5. **Render**: write `build/index.html`.
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
