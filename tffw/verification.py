"""Claim verification — the misinformation firewall.

Two rules the whole agent obeys:

1. A claim is only posted when its confidence is >= MIN_CONFIDENCE.
2. Confidence is earned from sources, never assumed:

   * Match data (scores, kick-offs, results) comes from football-data.org's
     official feed. Live in-play updates from that single official feed get
     0.85. Full-time results are cross-checked against TheSportsDB:
     confirmed -> 1.0, fixture not found -> 0.85, conflicting -> 0.4 (never
     posted, logged for review).

   * News/transfer claims need NEWS_MIN_SOURCES (default 2) *distinct*
     outlets reporting the same story within NEWS_WINDOW_HOURS. One outlet
     alone -> 0.5, parked as `skipped_low_confidence` until corroborated.

Nothing in the content layer can invent facts: captions are generated from
the verified facts dict only, and the prompt forbids adding information.
"""

import hashlib
import re

from . import config
from .sources import thesportsdb

STOPWORDS = {
    "the", "a", "an", "to", "of", "in", "on", "for", "and", "as", "at", "is",
    "are", "with", "after", "over", "by", "from", "his", "her", "its", "be",
    "have", "has", "will", "would", "could", "new", "says", "say", "said",
    "live", "watch", "video", "report", "reports", "latest", "news", "update",
    "football", "soccer", "premier", "league", "champions", "cup", "world",
    "how", "why", "what", "who", "this", "that", "it", "up", "out", "but",
    "vs", "v", "amid", "into", "during", "their", "your", "our", "not", "no",
}


def tokenize(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9']+", title.lower())
    return {w for w in words if len(w) > 2 and w not in STOPWORDS}


def similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def cluster_news(items: list[dict]) -> list[dict]:
    """Group news items about the same story. Greedy clustering on token
    overlap; a cluster is identified by a stable key so it is only ever
    posted once."""
    clusters: list[dict] = []
    for item in sorted(items, key=lambda i: i["published"]):
        tokens = tokenize(item["title"])
        if len(tokens) < 3:
            continue
        placed = False
        for c in clusters:
            if similarity(tokens, c["tokens"]) >= config.NEWS_SIMILARITY:
                c["items"].append(item)
                c["tokens"] |= tokens
                placed = True
                break
        if not placed:
            clusters.append({"tokens": tokens, "items": [item]})

    out = []
    for c in clusters:
        domains = sorted({i["domain"] for i in c["items"]})
        lead = c["items"][0]
        key_tokens = "|".join(sorted(tokenize(lead["title"])))
        claim_key = "story:" + hashlib.sha256(key_tokens.encode()).hexdigest()[:20]
        confidence = 1.0 if len(domains) >= config.NEWS_MIN_SOURCES else 0.5
        out.append(
            {
                "claim_key": claim_key,
                "headline": lead["title"],
                "items": c["items"],
                "domains": domains,
                "confidence": confidence,
                "sources": [
                    {"domain": i["domain"], "url": i["link"], "title": i["title"]}
                    for i in c["items"]
                ][:6],
            }
        )
    return out


def score_live_update() -> float:
    """In-play updates from the official football-data.org feed."""
    return 0.85


def score_final_result(match: dict) -> tuple[float, list[dict]]:
    """Confidence for a full-time result, cross-checked with TheSportsDB."""
    sources = [{"domain": "football-data.org", "title": "official match feed"}]
    confirmed = thesportsdb.confirm_result(
        match["home_full"], match["away_full"],
        match["home_score"], match["away_score"], match["utc_date"],
    )
    if confirmed is True:
        sources.append({"domain": "thesportsdb.com", "title": "result confirmed"})
        return 1.0, sources
    if confirmed is False:
        sources.append({"domain": "thesportsdb.com", "title": "RESULT CONFLICT"})
        return 0.4, sources
    return 0.85, sources


def classify_news(headline: str) -> str:
    """Map a verified story to a recurring content format."""
    h = headline.lower()
    if "var" in h.split() or "var " in h or " var" in h:
        return "VAR CHECK"
    transfer_kw = (
        "transfer", "sign", "signs", "signing", "deal", "fee", "medical",
        "loan", "bid", "agree", "agreed", "contract", "release clause",
        "move to", "joins", "join ",
    )
    if any(k in h for k in transfer_kw):
        return "TRANSFER WHISTLE"
    lineup_kw = ("line-up", "lineup", "team news", "starting xi", "team sheet")
    if any(k in h for k in lineup_kw):
        return "TEAM SHEET"
    return "BREAKING"
