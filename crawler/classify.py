"""Classify candidate repos with Claude via the Messages API (stdlib only)."""

import json
import os
import time
import urllib.error
import urllib.request

from .config import CLAUDE_MODEL

API_URL = "https://api.anthropic.com/v1/messages"

CATEGORIES = [
    "open-source game",
    "sdl port",
    "engine reimplementation",
    "decompilation",
    "emulator",
    "game engine / framework",
    "not relevant",
]

SYSTEM = """You help the PortMaster project find GitHub repositories worth porting.
PortMaster packages games and emulators for Linux ARM retro handhelds (RK3326, H700,
RK3566 and similar: 1-4 GB RAM, OpenGL ES / SDL2, gamepad only, 480p-720p screens).

Good candidates: playable open-source games; SDL1/SDL2 games and source ports;
engine reimplementations of commercial games (OpenXcom-style); decompilations and
reverse-engineering projects that build a native executable; emulators and fantasy
consoles; small engines whose games could be packaged.

Not relevant: tutorials, course homework, game jam stubs with no gameplay, asset
packs, mod managers, cheats/trainers, launchers, bots, web-only or mobile-only
apps, Windows-only DirectX projects with no portable path, trivial clones (yet
another Snake/Pong/Tetris with nothing notable), AI-generated boilerplate, and
general tools unrelated to games.

Judge from the metadata and README. Be strict: when unsure, mark not relevant."""

TOOL = {
    "name": "record_classification",
    "description": "Record the classification of one GitHub repository.",
    "input_schema": {
        "type": "object",
        "properties": {
            "relevant": {"type": "boolean", "description": "Worth showing to PortMaster porters."},
            "category": {"type": "string", "enum": CATEGORIES},
            "portability": {
                "type": "string",
                "enum": ["high", "medium", "low", "unknown"],
                "description": "How easy a handheld ARM Linux port looks (SDL2/GLES/C/C++ = high; heavy desktop GL, Windows-only, huge RAM = low).",
            },
            "summary": {"type": "string", "description": "One plain sentence: what it is."},
            "reason": {"type": "string", "description": "One short sentence: why it is or is not a candidate."},
            "needs_assets": {"type": "boolean", "description": "Requires original commercial game data files."},
        },
        "required": ["relevant", "category", "portability", "summary", "reason", "needs_assets"],
    },
}


class AuthError(RuntimeError):
    pass


def _call(payload, api_key, retries=4):
    body = json.dumps(payload).encode()
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    for attempt in range(retries):
        req = urllib.request.Request(API_URL, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 529) and attempt < retries - 1:
                wait = int(e.headers.get("retry-after") or 2 ** (attempt + 2))
                time.sleep(min(wait, 60))
                continue
            detail = e.read().decode(errors="replace")[:300]
            if e.code in (401, 403):
                raise AuthError(f"Claude API rejected the key ({e.code}): {detail}") from e
            if e.code == 400 and "credit balance" in detail:
                raise AuthError(f"Claude API has no credits: {detail}") from e
            raise RuntimeError(f"Claude API error {e.code}: {detail}") from e


def classify(repo, readme, api_key=None):
    api_key = (api_key or os.environ["ANTHROPIC_API_KEY"]).strip()
    info = (
        f"Repository: {repo['full_name']}\n"
        f"Description: {repo.get('description') or '(none)'}\n"
        f"Language: {repo.get('language') or 'unknown'}\n"
        f"Topics: {', '.join(repo.get('topics') or []) or '(none)'}\n"
        f"License: {repo.get('license') or 'none'}\n"
        f"Stars: {repo.get('stars')}  Created: {repo.get('created_at')}\n\n"
        f"README (truncated):\n<readme>\n{readme or '(no README)'}\n</readme>"
    )
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 400,
        "system": SYSTEM,
        "tools": [TOOL],
        "tool_choice": {"type": "tool", "name": TOOL["name"]},
        "messages": [{"role": "user", "content": info}],
    }
    data = _call(payload, api_key)
    for block in data.get("content", []):
        if block.get("type") == "tool_use":
            result = block["input"]
            result["model"] = CLAUDE_MODEL
            return result
    raise RuntimeError("Claude returned no classification")
