"""SQLite persistence layer.

The database is the agent's memory: raw source events, verified claims,
the post queue, every API call and every error. The Actions workflows
commit data/tffw.sqlite3 back to the repo after each run so state
survives between the ephemeral cron jobs.
"""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    kind        TEXT NOT NULL,            -- match_state | news_item | ...
    key         TEXT NOT NULL UNIQUE,     -- natural dedup key
    payload     TEXT NOT NULL,            -- JSON
    source      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claims (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_key   TEXT NOT NULL UNIQUE,
    first_seen  TEXT NOT NULL,
    headline    TEXT NOT NULL,
    sources     TEXT NOT NULL,            -- JSON list of {domain, url, title}
    confidence  REAL NOT NULL,
    status      TEXT NOT NULL             -- pending | posted | skipped_low_confidence
);

CREATE TABLE IF NOT EXISTS posts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT NOT NULL,
    format        TEXT NOT NULL,          -- LIVE WHISTLE / FINAL WHISTLE / ...
    headline      TEXT NOT NULL,
    caption       TEXT NOT NULL,
    hashtags      TEXT NOT NULL,
    alt_text      TEXT NOT NULL,
    image_path    TEXT,
    image_url     TEXT,
    status        TEXT NOT NULL,          -- queued | published | dry_run | skipped | failed
    scheduled_for TEXT NOT NULL,
    published_at  TEXT,
    external_id   TEXT,                   -- ID returned by Buffer / IG
    confidence    REAL NOT NULL,
    sources       TEXT NOT NULL,          -- JSON list
    content_hash  TEXT NOT NULL UNIQUE,   -- duplicate-post guard
    facts         TEXT NOT NULL           -- JSON facts used to build the post
);

CREATE TABLE IF NOT EXISTS api_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    service TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    status  INTEGER,
    ok      INTEGER NOT NULL,
    detail  TEXT
);

CREATE TABLE IF NOT EXISTS errors (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    context TEXT NOT NULL,
    message TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def content_hash(*parts: str) -> str:
    return hashlib.sha256("||".join(parts).encode("utf-8")).hexdigest()


# ── events ──────────────────────────────────────────────────────────────

def record_event(kind: str, key: str, payload: dict, source: str) -> bool:
    """Insert an event; returns True if it was new (dedup on key)."""
    with connect() as conn:
        try:
            conn.execute(
                "INSERT INTO events (ts, kind, key, payload, source) VALUES (?,?,?,?,?)",
                (now_iso(), kind, key, json.dumps(payload), source),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def get_event(key: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT payload FROM events WHERE key = ?", (key,)).fetchone()
    return json.loads(row["payload"]) if row else None


def upsert_event(kind: str, key: str, payload: dict, source: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO events (ts, kind, key, payload, source) VALUES (?,?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET payload=excluded.payload, ts=excluded.ts",
            (now_iso(), kind, key, json.dumps(payload), source),
        )


def recent_events(kind: str, hours: int) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM events WHERE kind = ? AND ts >= ? ORDER BY ts DESC",
            (kind, cutoff),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = json.loads(d["payload"])
        out.append(d)
    return out


# ── claims ──────────────────────────────────────────────────────────────

def get_claim(claim_key: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM claims WHERE claim_key = ?", (claim_key,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["sources"] = json.loads(d["sources"])
    return d


def upsert_claim(claim_key: str, headline: str, sources: list, confidence: float, status: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO claims (claim_key, first_seen, headline, sources, confidence, status) "
            "VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(claim_key) DO UPDATE SET sources=excluded.sources, "
            "confidence=excluded.confidence, status=excluded.status",
            (claim_key, now_iso(), headline, json.dumps(sources), confidence, status),
        )


# ── posts / queue ───────────────────────────────────────────────────────

def enqueue_post(
    fmt: str,
    headline: str,
    caption: str,
    hashtags: str,
    alt_text: str,
    confidence: float,
    sources: list,
    facts: dict,
    image_path: str | None = None,
    status: str = "queued",
    delay_minutes: int = 0,
) -> int | None:
    """Queue a post. Returns the post id, or None if it was a duplicate."""
    chash = content_hash(fmt, headline)
    scheduled = (datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)).isoformat(timespec="seconds")
    with connect() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO posts (created_at, format, headline, caption, hashtags, alt_text, "
                "image_path, status, scheduled_for, confidence, sources, content_hash, facts) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    now_iso(), fmt, headline, caption, hashtags, alt_text,
                    image_path, status, scheduled, confidence,
                    json.dumps(sources), chash, json.dumps(facts),
                ),
            )
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None


# ── published ledger ────────────────────────────────────────────────────
# One tiny marker file per published post. The SQLite DB is a binary file
# and can lose a concurrent-push race between the cron runners (a stale
# checkout rolling a 'published' row back to 'queued'); plain files merge
# trivially in git, so this ledger is the authoritative duplicate guard.

LEDGER_DIR = config.DATA_DIR / "published"


def ledger_mark(post_id: int, external_id: str) -> None:
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    (LEDGER_DIR / str(post_id)).write_text(f"{external_id}\n{now_iso()}\n")


def ledger_get(post_id: int) -> str | None:
    path = LEDGER_DIR / str(post_id)
    if path.exists():
        return path.read_text().splitlines()[0] if path.read_text() else "published"
    return None


def due_posts(limit: int) -> list[dict]:
    """Due queue items — time-sensitive formats (breaking news, live match
    moments) jump ahead of evergreen content (tables, fixture digests).
    Posts present in the published ledger are healed and never returned."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM posts WHERE status = 'queued' AND scheduled_for <= ? "
            "ORDER BY CASE "
            "WHEN format IN ('LIVE WHISTLE','FINAL WHISTLE') THEN 0 "
            "WHEN format IN ('BREAKING','TRANSFER WHISTLE','VAR CHECK') THEN 1 "
            "ELSE 2 END, confidence DESC, scheduled_for ASC",
            (now_iso(),),
        ).fetchall()
    out = []
    for r in rows:
        external = ledger_get(r["id"])
        if external is not None:  # DB row was rolled back by a sync race — heal it
            update_post(r["id"], status="published", external_id=external,
                        published_at=now_iso())
            continue
        if len(out) >= limit:
            continue
        d = dict(r)
        d["facts"] = json.loads(d["facts"])
        d["sources"] = json.loads(d["sources"])
        out.append(d)
    return out


def update_post(post_id: int, **fields) -> None:
    cols = ", ".join(f"{k} = ?" for k in fields)
    with connect() as conn:
        conn.execute(f"UPDATE posts SET {cols} WHERE id = ?", (*fields.values(), post_id))


def last_publish_time() -> datetime | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT MAX(published_at) AS last FROM posts WHERE status IN ('published','dry_run')"
        ).fetchone()
    if row and row["last"]:
        ts = datetime.fromisoformat(row["last"])
        # older rows may have stored a naive timestamp — treat as UTC so
        # arithmetic against tz-aware now() never raises
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return None


def expire_stale_news(hours: float) -> int:
    """Mark queued, non-live posts older than `hours` as expired. Time-
    sensitive news that has sat unpublished through an outage is no longer
    news; this stops a backlog flooding out as stale 'BREAKING' when
    publishing resumes. Live/full-time match moments are never expired here
    (run_live already scopes them to recent matches). Returns count expired."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    with connect() as conn:
        cur = conn.execute(
            "UPDATE posts SET status = 'expired' "
            "WHERE status = 'queued' "
            "AND format NOT IN ('LIVE WHISTLE','FINAL WHISTLE') "
            "AND COALESCE(scheduled_for, created_at) < ?",
            (cutoff,),
        )
        return cur.rowcount


def record_send(post_id: int, *, live: bool, what: str = "post") -> None:
    """Log one publish against the rolling-window budget. Buffer/Instagram
    count posts, reels AND stories toward the 24h limit, so every send is
    recorded — keyed so the same send is never counted twice."""
    record_event("send", f"send:{post_id}:{what}:{now_iso()}",
                 {"live": live, "what": what, "post": post_id}, config.PUBLISHER)


def sends_last_24h(live_only: bool | None = None) -> int:
    """Count publishes in the trailing 24h. live_only=False counts only
    non-live (news) sends; True counts only live; None counts everything."""
    evts = recent_events("send", 24)
    if live_only is None:
        return len(evts)
    return sum(1 for e in evts if bool(e["payload"].get("live")) == live_only)


def published_count_today() -> int:
    start = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00")
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM posts WHERE status = 'published' AND published_at >= ?",
            (start,),
        ).fetchone()
    return row["n"]


# ── logging ─────────────────────────────────────────────────────────────

def log_api(service: str, endpoint: str, status: int | None, ok: bool, detail: str = "") -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO api_log (ts, service, endpoint, status, ok, detail) VALUES (?,?,?,?,?,?)",
            (now_iso(), service, endpoint, status, int(ok), detail[:500]),
        )


def log_error(context: str, message: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO errors (ts, context, message) VALUES (?,?,?)",
            (now_iso(), context, message[:2000]),
        )


# ── dashboard queries ───────────────────────────────────────────────────

def dashboard_data() -> dict:
    with connect() as conn:
        def q(sql, *args):
            return [dict(r) for r in conn.execute(sql, args).fetchall()]

        return {
            "generated_at": now_iso(),
            "counts": {
                "queued": q("SELECT COUNT(*) n FROM posts WHERE status='queued'")[0]["n"],
                "published": q("SELECT COUNT(*) n FROM posts WHERE status='published'")[0]["n"],
                "dry_run": q("SELECT COUNT(*) n FROM posts WHERE status='dry_run'")[0]["n"],
                "skipped": q("SELECT COUNT(*) n FROM posts WHERE status='skipped'")[0]["n"],
                "failed": q("SELECT COUNT(*) n FROM posts WHERE status='failed'")[0]["n"],
                "claims_low_conf": q(
                    "SELECT COUNT(*) n FROM claims WHERE status='skipped_low_confidence'"
                )[0]["n"],
                "errors_24h": q(
                    "SELECT COUNT(*) n FROM errors WHERE ts >= datetime('now','-1 day')"
                )[0]["n"],
            },
            "queue": q(
                "SELECT id, format, headline, confidence, scheduled_for, image_path "
                "FROM posts WHERE status='queued' ORDER BY scheduled_for LIMIT 50"
            ),
            "recent_posts": q(
                "SELECT id, format, headline, status, confidence, published_at, external_id, sources "
                "FROM posts WHERE status != 'queued' ORDER BY id DESC LIMIT 50"
            ),
            "recent_claims": q(
                "SELECT claim_key, headline, confidence, status, sources, first_seen "
                "FROM claims ORDER BY id DESC LIMIT 50"
            ),
            "api_log": q("SELECT * FROM api_log ORDER BY id DESC LIMIT 80"),
            "errors": q("SELECT * FROM errors ORDER BY id DESC LIMIT 40"),
        }
