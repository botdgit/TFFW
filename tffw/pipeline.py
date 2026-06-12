"""Orchestration: detect -> verify -> generate -> queue -> publish.

Modes (invoked by the GitHub Actions schedules via tffw.main):
  live     — poll match data; kick-offs, goals, full-time results
  news     — ingest RSS, two-source verification, breaking/transfer posts
  digest   — daily league-table + fixtures content
  publish  — flush due queue items through the configured publisher
"""

from datetime import datetime, timedelta, timezone

from . import config, db, verification
from .content import captions, graphics
from .logger import get_logger
from .sources import espn, football_data, rss_news

log = get_logger("pipeline")


def _date_label() -> str:
    return datetime.now(timezone.utc).strftime("%d %b %Y").upper()


def _is_recent(utc_date: str, hours: int = 24) -> bool:
    try:
        when = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
    except ValueError:
        return False
    return datetime.now(timezone.utc) - when < timedelta(hours=hours)


def _queue(fmt: str, headline: str, facts: dict, confidence: float, sources: list) -> None:
    """Verification gate + content generation + queue insert (deduped)."""
    if confidence < config.MIN_CONFIDENCE:
        log.info("SKIP (confidence %.2f < %.2f): %s", confidence, config.MIN_CONFIDENCE, headline)
        return

    facts = {**facts, "date_label": _date_label()}
    seed = sum(ord(c) for c in headline)
    caption, alt_text = captions.build_caption(fmt, facts, seed)
    hashtags = ""  # hashtags are embedded in the caption by build_caption

    post_id = db.enqueue_post(
        fmt=fmt,
        headline=headline,
        caption=caption,
        hashtags=hashtags,
        alt_text=alt_text,
        confidence=confidence,
        sources=sources,
        facts=facts,
    )
    if post_id is None:
        log.info("duplicate, not queued: %s", headline)
        return
    path = graphics.render(post_id, fmt, facts)
    db.update_post(post_id, image_path=str(path.relative_to(config.ROOT)))
    log.info("QUEUED #%d [%s] %s (conf %.2f)", post_id, fmt, headline, confidence)


# ── live match pipeline ─────────────────────────────────────────────────

def run_live() -> None:
    matches = (
        football_data.matches_window(days_back=0, days_forward=0)
        if football_data.configured()
        else espn.todays_matches()
    )
    log.info("live: %d matches in window", len(matches))

    for m in matches:
        key = f"matchstate:{m['id']}"
        prev = db.get_event(key) or {}
        cur = {
            "status": m["status"],
            "home_score": m["home_score"],
            "away_score": m["away_score"],
        }
        if prev == cur:
            continue

        base_facts = {
            "home": m["home"], "away": m["away"],
            "home_score": m["home_score"], "away_score": m["away_score"],
            "competition": m["competition"], "competition_code": m["competition_code"],
        }
        teams = f"{m['home']} vs {m['away']}"

        # Kick-off
        if m["status"] in ("IN_PLAY", "LIVE") and prev.get("status") in (None, "TIMED", "SCHEDULED"):
            _queue(
                "LIVE WHISTLE",
                f"KICK-OFF: {teams}",
                {**base_facts, "event": "kickoff", "status_label": "KICK-OFF",
                 "home_score": None, "away_score": None},
                verification.score_live_update(),
                [{"domain": m["source"], "title": "official match feed"}],
            )

        # Goal / score change while in play
        elif m["status"] in ("IN_PLAY", "PAUSED", "LIVE") and (
            prev.get("home_score") is not None
            and (cur["home_score"], cur["away_score"]) != (prev.get("home_score"), prev.get("away_score"))
        ):
            _queue(
                "LIVE WHISTLE",
                f"GOAL: {m['home']} {m['home_score']}-{m['away_score']} {m['away']}",
                {**base_facts, "event": "goal", "status_label": "LIVE"},
                verification.score_live_update(),
                [{"domain": m["source"], "title": "official match feed"}],
            )

        # Full-time — only for matches played in the last 24h, so stale
        # results from a scoreboard's previous round never post on the
        # agent's first sight of them.
        elif m["status"] == "FINISHED" and prev.get("status") != "FINISHED" \
                and m["home_score"] is not None and _is_recent(m["utc_date"]):
            if m["source"] == "football-data.org":
                conf, sources = verification.score_final_result(m)
            else:
                # ESPN scoreboard; try TheSportsDB as a second source
                conf, sources = verification.score_final_result(m)
                sources[0] = {"domain": m["source"], "title": "official scoreboard"}
            _queue(
                "FINAL WHISTLE",
                f"FT: {m['home']} {m['home_score']}-{m['away_score']} {m['away']}",
                {**base_facts, "event": "full_time"},
                conf,
                sources,
            )

        db.upsert_event("match_state", key, cur, m["source"])


# ── news pipeline ───────────────────────────────────────────────────────

def run_news() -> None:
    rss_news.fetch_all()
    items = [e["payload"] for e in db.recent_events("news_item", config.NEWS_WINDOW_HOURS)]
    clusters = verification.cluster_news(items)
    log.info("news: %d items -> %d clusters", len(items), len(clusters))

    for c in clusters:
        existing = db.get_claim(c["claim_key"])
        if existing and existing["status"] == "posted":
            continue

        verified = c["confidence"] >= config.MIN_CONFIDENCE
        status = "posted" if verified else "skipped_low_confidence"
        db.upsert_claim(c["claim_key"], c["headline"], c["sources"], c["confidence"], status)

        if not verified:
            log.info(
                "claim parked (1 source, conf %.2f): %s", c["confidence"], c["headline"]
            )
            continue

        fmt = verification.classify_news(c["headline"])
        _queue(
            fmt,
            c["headline"],
            {
                "headline": c["headline"],
                "source_domains": c["domains"],
                "story_summary": c["items"][0].get("summary", "")[:280],
                "confirmed_by_sources": len(c["domains"]),
            },
            c["confidence"],
            c["sources"],
        )


# ── daily digest ────────────────────────────────────────────────────────

def run_digest() -> None:
    today = datetime.now(timezone.utc).date().isoformat()

    # League table (needs football-data; skipped gracefully without a token)
    if football_data.configured():
        rows = football_data.standings("PL")
        if rows:
            _queue(
                "TEAM SHEET",
                f"Premier League table — {today}",
                {
                    "headline": "PREMIER LEAGUE TABLE",
                    "table_rows": rows,
                    "competition_code": "PL",
                    "source_domains": ["football-data.org"],
                },
                1.0,
                [{"domain": "football-data.org", "title": "official standings"}],
            )

    # Today's fixtures preview
    fixtures = (
        [m for m in football_data.matches_window(0, 0) if m["status"] in ("TIMED", "SCHEDULED")]
        if football_data.configured()
        else [
            m for m in espn.todays_matches()
            if m["status"] == "TIMED" and m["utc_date"][:10] == today
        ]
    )
    if fixtures:
        lines = [f"{m['home']} v {m['away']}" for m in fixtures[:6]]
        n = len(fixtures)
        _queue(
            "TEAM SHEET",
            f"Matchday — {n} fixture{'s' if n != 1 else ''} on {today}",
            {
                "headline": "TODAY'S FIXTURES: " + " · ".join(lines),
                "competition_code": fixtures[0]["competition_code"],
                "source_domains": [fixtures[0]["source"]],
            },
            1.0,
            [{"domain": fixtures[0]["source"], "title": "official fixtures"}],
        )


# ── publishing ──────────────────────────────────────────────────────────

def run_publish() -> None:
    # Daily cap
    if db.published_count_today() >= config.MAX_POSTS_PER_DAY:
        log.info("publish: daily cap reached (%d)", config.MAX_POSTS_PER_DAY)
        return

    # Spacing between posts
    last = db.last_publish_time()
    if last is not None:
        gap = datetime.now(timezone.utc) - last
        if gap < timedelta(minutes=config.MIN_MINUTES_BETWEEN_POSTS):
            log.info("publish: spacing gate (%s since last post)", gap)
            return

    for post in db.due_posts(config.MAX_POSTS_PER_RUN):
        _publish_one(post)


def _publish_one(post: dict) -> None:
    image_name = (post["image_path"] or "").split("/")[-1]
    image_url = config.media_public_url(image_name) if image_name else ""
    db.update_post(post["id"], image_url=image_url)

    if config.DRY_RUN:
        db.update_post(post["id"], status="dry_run", published_at=db.now_iso())
        log.info("DRY RUN — would publish #%d [%s] %s", post["id"], post["format"], post["headline"])
        return

    if config.PUBLISHER == "buffer":
        from .publish import buffer_api as backend
    elif config.PUBLISHER == "instagram":
        from .publish import instagram_graph as backend
    else:
        log.info("publish: PUBLISHER=none, leaving #%d queued", post["id"])
        return

    if not backend.configured():
        log.warning("publish: %s not configured, leaving #%d queued", config.PUBLISHER, post["id"])
        return
    if not image_url:
        db.log_error("publish", f"post {post['id']}: no public image URL")
        return

    external_id = backend.publish(post["caption"], image_url, post["alt_text"])
    if external_id:
        db.update_post(
            post["id"], status="published", published_at=db.now_iso(), external_id=str(external_id)
        )
        log.info("PUBLISHED #%d via %s -> %s", post["id"], config.PUBLISHER, external_id)
    else:
        db.update_post(post["id"], status="failed")
        db.log_error("publish", f"post {post['id']} failed via {config.PUBLISHER}")
