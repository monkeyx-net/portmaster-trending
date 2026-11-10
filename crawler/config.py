"""Tunable settings for the crawler."""

# Claude model used to classify candidates.
CLAUDE_MODEL = "claude-haiku-5-5"

# How far back to look for newly created repos on each run.
LOOKBACK_DAYS = 14

# Minimum stars for a brand-new repo to be considered at all.
MIN_STARS_NEW = 5

# Max results kept per search query (GitHub caps at 100 per page).
PER_QUERY = 50

# Max new candidates sent to Claude per run (keeps cost predictable).
MAX_CLASSIFY = 120

# Max tracked repos re-checked for star growth per run.
MAX_RECHECK = 300

# A tracked repo is "Rising" when, since it was last shown, it gained at least
# RISING_MIN_GAIN stars AND grew by at least RISING_MIN_RATIO.
RISING_MIN_GAIN = 25
RISING_MIN_RATIO = 0.5

# GitHub search qualifiers. "{since}" is replaced with the lookback date.
SEARCH_QUERIES = [
    "topic:sdl2 created:>{since}",
    "topic:sdl created:>{since}",
    "topic:game-engine created:>{since}",
    "topic:emulator created:>{since}",
    "topic:decompilation created:>{since}",
    "topic:decomp created:>{since}",
    "topic:reverse-engineering topic:game created:>{since}",
    "topic:reimplementation created:>{since}",
    "topic:game language:C created:>{since}",
    "topic:game language:C++ created:>{since}",
    "topic:game language:Rust created:>{since}",
    "topic:love2d created:>{since}",
    "topic:godot topic:game created:>{since}",
    "decompilation in:name,description created:>{since}",
    "reimplementation in:name,description created:>{since}",
    "\"source port\" in:name,description created:>{since}",
    "emulator in:name,description created:>{since}",
    "SDL2 game in:name,description created:>{since}",
]
