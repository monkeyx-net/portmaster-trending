"""Small GitHub REST client using only the standard library."""

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"


class GitHub:
    def __init__(self, token=None):
        self.token = token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

    def _get(self, path, params=None, retries=3):
        url = API + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "portmaster-trending",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        for attempt in range(retries):
            req = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                if e.code in (403, 429) and attempt < retries - 1:
                    reset = e.headers.get("X-RateLimit-Reset")
                    wait = max(5, int(reset) - int(time.time()) + 1) if reset else 30
                    wait = min(wait, 90)
                    print(f"  rate limited, sleeping {wait}s")
                    time.sleep(wait)
                    continue
                if e.code >= 500 and attempt < retries - 1:
                    time.sleep(5)
                    continue
                raise
            except urllib.error.URLError:
                if attempt < retries - 1:
                    time.sleep(5)
                    continue
                raise
        return None

    def search_repos(self, query, per_page=50):
        data = self._get(
            "/search/repositories",
            {"q": query, "sort": "stars", "order": "desc", "per_page": per_page},
        )
        # Search API allows 30 requests/minute when authenticated.
        time.sleep(2.2)
        return (data or {}).get("items", [])

    def repo(self, full_name):
        return self._get(f"/repos/{full_name}")

    def readme(self, full_name, limit=4000):
        data = self._get(f"/repos/{full_name}/readme")
        if not data or "content" not in data:
            return ""
        try:
            text = base64.b64decode(data["content"]).decode("utf-8", "replace")
        except Exception:
            return ""
        return text[:limit]


def slim(item):
    """Keep only the repo fields we store."""
    return {
        "full_name": item["full_name"],
        "url": item["html_url"],
        "description": (item.get("description") or "")[:300],
        "language": item.get("language"),
        "topics": item.get("topics", [])[:12],
        "license": (item.get("license") or {}).get("spdx_id"),
        "stars": item.get("stargazers_count", 0),
        "forks": item.get("forks_count", 0),
        "created_at": item.get("created_at"),
        "pushed_at": item.get("pushed_at"),
        "archived": item.get("archived", False),
        "fork": item.get("fork", False),
    }
