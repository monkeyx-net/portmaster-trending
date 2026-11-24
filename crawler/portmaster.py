"""Match GitHub repos against PortMaster's published port list (ports.json),
so projects that are already ports can be left out of the reports.

A repo matches a port when:
  1. the port's description, store entry or URL links to that GitHub repo
     (install instructions are skipped: they often link tools, not the game), or
  2. the repo's name equals the port's title, the title without a trailing
     "(...)", or the port's zip name, after lower-casing and dropping
     everything but letters and digits (devilutionX = DevilutionX).
"""

import json
import re
import urllib.request

PORTS_URL = "https://raw.githubusercontent.com/PortsMaster/PortMaster-Info/refs/heads/main/ports.json"
LINK_FIELDS = ("url", "desc", "desc_md")
GH_LINK = re.compile(r"github\.com/([\w.-]+/[\w.-]+)", re.I)
MIN_NAME = 3  # shorter normalised names are too ambiguous to match on

_cache = {}


def norm(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _repo(slug):
    slug = slug.lower().rstrip(".")
    return slug.removesuffix(".git")


class Ports:
    def __init__(self, ports):
        self.count = len(ports)
        self.by_repo = {}
        self.by_name = {}
        for zip_name, p in ports.items():
            a = p.get("attr") or {}
            title = a.get("title") or zip_name
            texts = [str(a.get(f) or "") for f in LINK_FIELDS] + [json.dumps(a.get("store") or [])]
            for t in texts:
                for m in GH_LINK.findall(t):
                    if not m.lower().startswith(("portsmaster/", "portsmaster-mv/")):
                        self.by_repo.setdefault(_repo(m), title)
            names = {norm(title), norm(re.sub(r"\s*\([^)]*\)\s*$", "", title)), norm(zip_name.removesuffix(".zip"))}
            for n in names:
                if len(n) >= MIN_NAME:
                    self.by_name.setdefault(n, title)

    def match(self, full_name=None, *names):
        """Title of the matching port, or None. `full_name` is "owner/repo";
        `names` are extra names to try (curated project / game names)."""
        if full_name:
            hit = self.by_repo.get(_repo(full_name))
            if hit:
                return hit
            names = (full_name.split("/")[-1],) + names
        for n in names:
            hit = self.by_name.get(norm(n))
            if hit:
                return hit
        return None


def load(url=PORTS_URL):
    """The port index, fetched once per process. None if the download fails,
    in which case nothing is filtered."""
    if "ports" not in _cache:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "portmaster-trending"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            _cache["ports"] = Ports(data["ports"])
            print(f"  ports.json: {_cache['ports'].count} PortMaster ports loaded")
        except Exception as e:
            print(f"  ! ports.json: {e} (not filtering ports already on PortMaster)")
            _cache["ports"] = None
    return _cache["ports"]


def split(repos, ports, names=lambda r: (r["full_name"],)):
    """(kept, ported) where ported is [(repo, port title)]."""
    if ports is None:
        return list(repos), []
    kept, ported = [], []
    for r in repos:
        hit = ports.match(*names(r))
        if hit:
            ported.append((r, hit))
        else:
            kept.append(r)
    return kept, ported
