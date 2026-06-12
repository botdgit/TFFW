"""Wikimedia Commons — free, properly licensed imagery for news posts.

Only images whose metadata declares a free license (CC BY / CC BY-SA /
CC0 / public domain) are ever used, and the artist + license are rendered
as an attribution line on the graphic itself, satisfying the license
terms. Club crests/logos are skipped (trademark, not copyright, risk).
"""

import re

import requests

from .. import config, db
from ..logger import get_logger

log = get_logger("commons")

API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "tffw-agent/1.0 (https://github.com/botdgit/TFFW)"}

FREE_LICENSES = ("cc by", "cc-by", "cc0", "public domain", "pd")
SKIP_TITLE_WORDS = ("logo", "crest", "badge", "kit ", "flag of", "map", "stadium plan",
                    "poster", "illustration", "painting", "drawing", "cartoon", "statue")

STOPWORDS = {
    "the", "a", "an", "after", "before", "with", "over", "for", "and", "as",
    "premier", "league", "champions", "world", "cup", "uefa", "fifa", "var",
    "breaking", "transfer", "new", "live", "club", "fc",
}


def entity_queries(headline: str) -> list[str]:
    """Candidate Commons queries for a headline's subject, best first:
    the full capitalised run, then its individual names (surnames find
    player photos that 'Scotland's McTominay' never would)."""
    words = re.findall(r"[A-Za-zÀ-ÿ'.-]+", headline)
    words = [re.sub(r"[''']s$", "", w) for w in words]  # Scotland's -> Scotland
    runs, current = [], []
    for i, w in enumerate(words):
        if w[0].isupper() and w.lower() not in STOPWORDS:
            current.append((i, w))
        else:
            if current:
                runs.append(current)
            current = []
    if current:
        runs.append(current)

    candidates = []
    for run in runs:
        toks = [w for i, w in run if not (i == 0 and len(run) == 1)]
        if toks:
            candidates.append(" ".join(toks))
    candidates.sort(key=lambda c: (-len(c.split()), -len(c)))

    queries: list[str] = []
    for c in candidates:
        if len(c) > 3 and c not in queries:
            queries.append(c)
        # also try each individual name word (longest first → surnames)
        for tok in sorted(c.split(), key=len, reverse=True):
            if len(tok) > 4 and tok not in queries:
                queries.append(tok)
    return queries[:4]


def entity_from_headline(headline: str) -> str | None:
    """Back-compat single-query helper."""
    queries = entity_queries(headline)
    return queries[0] if queries else None


def find_photo(query: str) -> dict | None:
    """Search Commons for a freely licensed photo. Returns metadata dict
    or None when nothing suitably licensed/sized is found."""
    try:
        resp = requests.get(
            API,
            params={
                "action": "query", "format": "json",
                "generator": "search",
                "gsrsearch": f"{query} filetype:bitmap",
                "gsrlimit": 8, "gsrnamespace": 6,
                "prop": "imageinfo",
                "iiprop": "url|extmetadata|size",
            },
            headers=UA, timeout=20,
        )
        db.log_api("commons", f"search:{query}", resp.status_code, resp.ok)
        pages = (resp.json().get("query") or {}).get("pages") or {}
    except (requests.RequestException, ValueError) as exc:
        db.log_error("commons", f"search {query}: {exc}")
        return None

    q_tokens = {t for t in re.findall(r"[a-zà-ÿ0-9']+", query.lower()) if len(t) > 2}
    best = None
    for page in pages.values():
        title = (page.get("title") or "").lower()
        if any(w in title for w in SKIP_TITLE_WORDS):
            continue
        # relevance guard: the photo title must actually be about the
        # queried subject, and never silently swap men's/women's teams
        t_tokens = set(re.findall(r"[a-zà-ÿ0-9']+", title))
        if q_tokens and len(q_tokens & t_tokens) < max(2, len(q_tokens) // 2):
            continue
        # the lead token (player surname-first / club name) must be present
        lead = next(iter(re.findall(r"[a-zà-ÿ0-9']+", query.lower())), "")
        if len(lead) > 2 and lead not in t_tokens:
            continue
        if ("women" in t_tokens or "women's" in title) != ("women" in q_tokens):
            continue
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        license_name = (meta.get("LicenseShortName", {}) or {}).get("value", "")
        if not any(t in license_name.lower() for t in FREE_LICENSES):
            continue
        width, height = info.get("width", 0), info.get("height", 0)
        if width < 800 or height < 500:
            continue
        if width * height > 40_000_000:  # skip enormous scans/panoramas
            continue
        artist = _strip_html((meta.get("Artist", {}) or {}).get("value", ""))[:60]
        candidate = {
            "url": info.get("url"),
            "title": page.get("title", ""),
            "license": license_name,
            "artist": artist or "Wikimedia Commons",
            "width": width,
        }
        if best is None or width > best["width"]:
            best = candidate
    return best


def download(photo: dict, dest_name: str) -> str | None:
    """Download a found photo into the media dir; returns relative path."""
    try:
        resp = requests.get(photo["url"], headers=UA, timeout=30)
        db.log_api("commons", "download", resp.status_code, resp.ok)
        if not resp.ok or len(resp.content) < 20_000:
            return None
        dest = config.MEDIA_DIR / dest_name
        dest.write_bytes(resp.content)
        return str(dest.relative_to(config.ROOT))
    except requests.RequestException as exc:
        db.log_error("commons", f"download: {exc}")
        return None


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()
