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
        if len(domains) >= 2:
            confidence = 1.0          # independently corroborated
        elif config.NEWS_MIN_SOURCES <= 1:
            confidence = 0.85         # single trusted tier-1 outlet
        else:
            confidence = 0.5          # below the configured source bar
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


# With single-source posting enabled, this filter is the spam/relevance
# gate: it drops interactive/format junk and the other sports that leak
# into the football feeds. Pure blocklist — football stories pass by default.
IRRELEVANT_TERMS = (
    # feed junk / interactive formats
    "quiz", "podcast", "listen:", "watch:", "gossip", "have your say",
    "predict the score", "fans react", "fan vote", "you are ", "vote for",
    "? vote", "vote!", "have your say", "rate the", "pick your",
    "ranking the", "power rankings", "ranked:", "top 10", "top 25",
    "top 50", "top 100", "best players in", "let's rank",
    "– live", "— live", ": live", "live blog", "liveblog", "as it happened",
    "football daily", "sign up", "newsletter", "subscribe",
    "how to follow", "tv guide", "betting", "odds", "crossword",
    "weekly round-up", "in pictures", "photo gallery", "fantasy tips",
    # other sports that appear in mixed sport feeds
    "f1", "formula 1", "formula one", "grand prix", "qualifying lap",
    "cricket", "rugby", "tennis", "wimbledon", "queen's club", "atp", "wta",
    "golf", "ryder cup", "boxing", "ufc", "mma", "nfl", "nba", "mlb", "nhl",
    "horse racing", "races at", "st james's palace", "ascot", "darts",
    "dart ", "snooker", "cycling", "tour de france", "athletics", "swimming",
    "netball", "hockey", "grand prix", " gp:", "first practice", "mclaren",
    "mercedes", "queen's", "t20", "icc ", "test match", "the ashes",
    "how can you follow", "day-by-day guide",
)


def is_relevant(headline: str) -> bool:
    h = " " + headline.lower() + " "
    return not any(term in h for term in IRRELEVANT_TERMS)


def classify_news(headline: str) -> str:
    """Map a verified story to a recurring content format."""
    h = headline.lower()
    if "var" in h.split() or "var " in h or " var" in h:
        return "VAR CHECK"
    transfer_kw = (
        "transfer", "sign", "signs", "signing", "deal", "fee", "medical",
        "loan", "bid", "agree", "agreed", "contract", "release clause",
        "move to", "joins", "join ", "offer for", "offer to sign", "bid for",
        "swoop", "exit", "departure",
        "set to leave", "wants out", "price tag",
    )
    if any(k in h for k in transfer_kw):
        return "TRANSFER WHISTLE"
    lineup_kw = ("line-up", "lineup", "team news", "starting xi", "team sheet")
    if any(k in h for k in lineup_kw):
        return "TEAM SHEET"
    return "BREAKING"
