"""Central configuration. Everything is read from environment variables
(.env is loaded for local runs) so the same code runs locally and in
GitHub Actions without changes."""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # dotenv is a convenience, not a hard dependency
    pass

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MEDIA_DIR = ROOT / "output" / "media"
DASHBOARD_DIR = ROOT / "dashboard"
FONT_DIR = ROOT / "assets" / "fonts"
DB_PATH = DATA_DIR / "tffw.sqlite3"

for d in (DATA_DIR, MEDIA_DIR, DASHBOARD_DIR):
    d.mkdir(parents=True, exist_ok=True)


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


# ── Safety ──────────────────────────────────────────────────────────────
DRY_RUN = _bool("DRY_RUN", True)
MIN_CONFIDENCE = _float("MIN_CONFIDENCE", 0.8)

# ── Sports data ─────────────────────────────────────────────────────────
FOOTBALL_DATA_TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN", "")
FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"
COMPETITIONS = [c.strip() for c in os.environ.get("COMPETITIONS", "PL,CL,WC").split(",") if c.strip()]
THESPORTSDB_KEY = os.environ.get("THESPORTSDB_KEY", "3")
THESPORTSDB_BASE = "https://www.thesportsdb.com/api/v1/json"

# ── News ────────────────────────────────────────────────────────────────
DEFAULT_FEEDS = [
    "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "https://www.skysports.com/rss/11095",  # Sky Sports *football* feed
    "https://www.theguardian.com/football/rss",
    "https://www.espn.com/espn/rss/soccer/news",
]
RSS_FEEDS = [
    f.strip()
    for f in os.environ.get("RSS_FEEDS", ",".join(DEFAULT_FEEDS)).split(",")
    if f.strip()
]
# Outlets required before a story is posted. 1 = any single tier-1 outlet
# (BBC/Sky/Guardian/ESPN) is trusted; 2 restores strict cross-verification.
NEWS_MIN_SOURCES = _int("NEWS_MIN_SOURCES", 1)
NEWS_SIMILARITY = _float("NEWS_SIMILARITY", 0.45)
NEWS_WINDOW_HOURS = _int("NEWS_WINDOW_HOURS", 18)
# A story must be fresher than this to be posted (clusters keep building
# in the wider window above, but stale news never goes out).
NEWS_MAX_AGE_HOURS = _int("NEWS_MAX_AGE_HOURS", 4)

# ── Captions / Claude ───────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")

# ── Publishing ──────────────────────────────────────────────────────────
PUBLISHER = os.environ.get("PUBLISHER", "none").strip().lower()  # none|buffer|instagram
BUFFER_ACCESS_TOKEN = os.environ.get("BUFFER_ACCESS_TOKEN", "")
BUFFER_CHANNEL_ID = os.environ.get("BUFFER_CHANNEL_ID", "")
IG_USER_ID = os.environ.get("IG_USER_ID", "")
IG_ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "")
MEDIA_BASE_URL = os.environ.get("MEDIA_BASE_URL", "")

REELS_ENABLED = _bool("REELS_ENABLED", True)
COMPANION_STORIES = _bool("COMPANION_STORIES", True)
MAX_POSTS_PER_RUN = _int("MAX_POSTS_PER_RUN", 5)
MIN_MINUTES_BETWEEN_POSTS = _int("MIN_MINUTES_BETWEEN_POSTS", 12)
MAX_POSTS_PER_DAY = _int("MAX_POSTS_PER_DAY", 60)
# queued news older than this (e.g. after a publishing outage) is expired
# rather than posted, so the feed never floods with stale "breaking" news
PUBLISH_STALE_HOURS = _float("PUBLISH_STALE_HOURS", 6.0)
# how long to stop publishing after a publisher reports its daily limit
BUFFER_BACKOFF_H = _float("BUFFER_BACKOFF_H", 3.0)
# Buffer/Instagram count posts + reels + stories toward a rolling 24h limit
# (Buffer free = 50). Hold a margin, and reserve most of it for live events.
DAILY_SEND_LIMIT = _int("DAILY_SEND_LIMIT", 45)
NEWS_SEND_LIMIT = _int("NEWS_SEND_LIMIT", 16)
# Two publishers can run: the session loop (low latency, "primary") and the
# GitHub Actions cron ("backstop"). The backstop only publishes when the
# primary has gone silent, so they never double-post the same queue.
PUBLISH_ROLE = os.environ.get("PUBLISH_ROLE", "primary").strip().lower()
LOOP_PULSE_STALE_S = _int("LOOP_PULSE_STALE_S", 900)
# a recap waits this long for its voiced reel to render; after that it posts
# as a static card rather than getting stuck forever
RECAP_RENDER_GRACE_MIN = _int("RECAP_RENDER_GRACE_MIN", 15)

# ── Brand ───────────────────────────────────────────────────────────────
BRAND_HANDLE = os.environ.get("BRAND_HANDLE", "@thefootballfinalwhistle")
BRAND_NAME = os.environ.get("BRAND_NAME", "The Football Final Whistle")
# Palette derived from the brand logo (assets/brand/logo.png)
BRAND_GREEN = "#5E8BCB"
BRAND_GREEN_DARK = "#091627"
BRAND_WHITE = "#FFFFFF"
BRAND_OFFWHITE = "#F4F9EF"

# Accent palette. The deep navy stays the base identity; the accent is the
# punchy, scroll-stopping colour used for chips, scores, ticks and CTAs.
# An electric lime on navy is a classic high-energy sports pairing and reads
# far stronger in-feed than the previous muted blue. Both are env-overridable
# so the whole look can be re-tuned without touching the render code.
BRAND_ACCENT = os.environ.get("BRAND_ACCENT", "#C6F24E")
BRAND_ACCENT_BRIGHT = os.environ.get("BRAND_ACCENT_BRIGHT", "#DBFF73")


def media_public_url(filename: str) -> str:
    """Public URL for a generated image. Instagram/Buffer fetch media over
    HTTP, so images committed by the Actions workflow are served from
    raw.githubusercontent.com unless MEDIA_BASE_URL overrides it."""
    if MEDIA_BASE_URL:
        return MEDIA_BASE_URL.rstrip("/") + "/" + filename
    repo = os.environ.get("GITHUB_REPOSITORY")  # e.g. botdgit/TFFW
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    if repo:
        return f"https://raw.githubusercontent.com/{repo}/{branch}/output/media/{filename}"
    return ""
