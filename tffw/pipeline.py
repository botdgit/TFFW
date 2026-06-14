"""Orchestration: detect -> verify -> generate -> queue -> publish.

Modes (invoked by the GitHub Actions schedules via tffw.main):
  live     — poll match data; kick-offs, goals, full-time results
  news     — ingest RSS, two-source verification, breaking/transfer posts
  digest   — daily league-table + fixtures content
  publish  — flush due queue items through the configured publisher
"""

import time
from datetime import datetime, timedelta, timezone

from . import config, db, verification
from .content import captions, graphics
from .logger import get_logger
from .sources import commons, espn, football_data, rss_news

log = get_logger("pipeline")


def _date_label() -> str:
    return datetime.now(timezone.utc).strftime("%d %b %Y").upper()


def _is_recent(utc_date: str, hours: int = 24) -> bool:
    try:
        when = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
    except ValueError:
        return False
    return datetime.now(timezone.utc) - when < timedelta(hours=hours)


def _parse_dt(value: str) -> datetime:
    """Parse a stored timestamp to a tz-aware datetime (assume UTC if naive)."""
    try:
        dt = datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _queue(fmt: str, headline: str, facts: dict, confidence: float, sources: list) -> None:
    """Verification gate + content generation + queue insert (deduped)."""
    if confidence < config.MIN_CONFIDENCE:
        log.info("SKIP (confidence %.2f < %.2f): %s", confidence, config.MIN_CONFIDENCE, headline)
        return

    # near-duplicate guard: the same NEWS story phrased differently by
    # another outlet must not post twice. Match events (kick-off, goals,
    # FT) are exempt — their headlines legitimately share team names.
    if fmt not in ("LIVE WHISTLE", "FINAL WHISTLE") and _near_duplicate(headline):
        log.info("near-duplicate, not queued: %s", headline)
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

    # Reels drive far more reach than statics, so animate aggressively:
    # every match moment gets the score-reveal reel; news with imagery
    # gets a Ken Burns photo reel.
    if config.REELS_ENABLED:
        try:
            if fmt in ("LIVE WHISTLE", "FINAL WHISTLE") and facts.get("home"):
                graphics.render_reel(post_id, fmt, facts)
            elif fmt in ("BREAKING", "TRANSFER WHISTLE", "VAR CHECK") and facts.get("photo_path"):
                graphics.render_news_reel(post_id, fmt, facts)
        except Exception as exc:
            db.log_error("reel", f"post {post_id}: {exc}")

    # match moments and fixture digests also get a 9:16 story card,
    # posted to Stories alongside the feed post
    if (fmt in ("LIVE WHISTLE", "FINAL WHISTLE") and facts.get("home")) or facts.get("fixture_rows"):
        graphics.render_story(post_id, fmt, facts)

    log.info("QUEUED #%d [%s] %s (conf %.2f)", post_id, fmt, headline, confidence)


def _near_duplicate(headline: str) -> bool:
    """True when a recent post (any status except skipped) already covers
    this story — token overlap across differently-phrased headlines."""
    tokens = verification.tokenize(headline)
    if not tokens:
        return False
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT headline FROM posts WHERE status != 'skipped' "
            "AND created_at >= datetime('now', '-1 day')"
        ).fetchall()
    for r in rows:
        if verification.similarity(tokens, verification.tokenize(r["headline"])) >= 0.5:
            return True
    return False


def _attach_photo(facts: dict, headline: str, claim_key: str) -> dict:
    """Best-effort licensed photo for a news story (never blocks posting).
    Tries several subject queries: full name run, then individual names.
    Falls back to a licensed stadium/football image so EVERY post has a
    photo background — the brand's reel-first, image-led format."""
    try:
        for query in commons.entity_queries(headline):
            photo = commons.find_photo(query)
            if not photo:
                continue
            rel = commons.download(photo, f"src_{claim_key.split(':')[-1]}.jpg")
            if not rel:
                continue
            credit = f"PHOTO: {photo['artist']} / WIKIMEDIA COMMONS ({photo['license']})"
            return {**facts, "photo_path": rel, "photo_credit": credit}
    except Exception as exc:
        db.log_error("commons", f"attach_photo: {exc}")

    # no subject photo — use a rotating licensed stadium/football background
    # so the post is still image-led and can become a reel
    backgrounds = sorted((config.ROOT / "assets" / "backgrounds").glob("stadium_*.jpg"))
    if backgrounds:
        import hashlib
        idx = int(hashlib.sha256(claim_key.encode()).hexdigest(), 16) % len(backgrounds)
        rel = str(backgrounds[idx].relative_to(config.ROOT))
        return {**facts, "photo_path": rel, "photo_credit": "PHOTO: WIKIMEDIA COMMONS (CC0)"}
    return facts


# ── live match pipeline ─────────────────────────────────────────────────

def run_live() -> None:
    matches = (
        football_data.matches_window(days_back=0, days_forward=0)
        if football_data.configured()
        else espn.todays_matches()
    )
    log.info("live: %d matches in window", len(matches))

    # fast-mode marker: while any monitored match is in play, the session
    # loop polls every ~20s instead of every 2 minutes
    marker = config.DATA_DIR / "LIVE_MATCH"
    if any(m["status"] in ("IN_PLAY", "PAUSED") for m in matches):
        marker.touch()
    else:
        marker.unlink(missing_ok=True)

    for m in matches:
        key = f"matchstate:{m['id']}"
        prev = db.get_event(key) or {}
        scorers = m.get("scorers") or []
        reds = m.get("red_cards") or []
        cur = {
            "status": m["status"],
            "home_score": m["home_score"],
            "away_score": m["away_score"],
            "reds": len(reds),
        }
        if {k: prev.get(k) for k in cur} == cur:
            continue

        base_facts = {
            "home": m["home"], "away": m["away"],
            "home_full": m["home_full"], "away_full": m["away_full"],
            "home_score": m["home_score"], "away_score": m["away_score"],
            "competition": m["competition"], "competition_code": m["competition_code"],
            "scorers": scorers,
            "match_minute": m.get("minute", ""),
        }
        teams = f"{m['home']} vs {m['away']}"

        # Red card — name + minute from the official feed
        if m["status"] in ("IN_PLAY", "PAUSED", "LIVE") and "reds" in prev \
                and cur["reds"] > prev["reds"]:
            rc = reds[-1]
            rc_team = m["home"] if rc.get("side") == "home" else m["away"]
            _queue(
                "LIVE WHISTLE",
                f"RED CARD: {rc.get('name')} ({rc_team}) {rc.get('minute')}",
                {**base_facts, "event": "red_card", "status_label": "RED CARD",
                 "red_card": rc, "red_card_team": rc_team},
                verification.score_live_update(),
                [{"domain": m["source"], "title": "official match feed"}],
            )

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
            latest = scorers[-1] if scorers else {}
            scorer_tag = f" — {latest.get('name')} {latest.get('minute')}" if latest.get("name") else ""
            _queue(
                "LIVE WHISTLE",
                f"GOAL: {m['home']} {m['home_score']}-{m['away_score']} {m['away']}{scorer_tag}",
                {**base_facts, "event": "goal", "status_label": "LIVE",
                 "goal_scorer": latest},
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
            # voiced ~30s recap reel, a few minutes after the FT card
            if conf >= config.MIN_CONFIDENCE:
                try:
                    from .content import recap

                    recap.queue_recap({**base_facts, "event": "full_time",
                                       "date_label": _date_label()}, sources)
                except Exception as exc:
                    db.log_error("recap", f"queue_recap: {exc}")

        db.upsert_event("match_state", key, cur, m["source"])


# ── news pipeline ───────────────────────────────────────────────────────

def run_news() -> None:
    rss_news.fetch_all()
    items = [e["payload"] for e in db.recent_events("news_item", config.NEWS_WINDOW_HOURS)]
    clusters = verification.cluster_news(items)
    log.info("news: %d items -> %d clusters", len(items), len(clusters))

    for c in clusters:
        existing = db.get_claim(c["claim_key"])
        if existing and existing["status"] in ("posted", "skipped_irrelevant"):
            continue

        # check the summary too — sport giveaways ("Grand Prix", "McLaren")
        # often only appear there
        if not verification.is_relevant(
            c["headline"] + " " + c["items"][0].get("summary", "")
        ):
            db.upsert_claim(c["claim_key"], c["headline"], c["sources"],
                            c["confidence"], "skipped_irrelevant")
            continue

        newest = max(i["published"] for i in c["items"])
        if not _is_recent(newest, hours=config.NEWS_MAX_AGE_HOURS):
            db.upsert_claim(c["claim_key"], c["headline"], c["sources"],
                            c["confidence"], "expired")
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
        # trending = multi-outlet velocity: several outlets on one story in
        # the window is football's "what's hot" signal. Trending stories
        # rank first in the publish queue (confidence is the sort key).
        trending = len(c["domains"]) >= 2
        facts = {
            "headline": c["headline"],
            "source_domains": c["domains"],
            "story_summary": c["items"][0].get("summary", "")[:280],
            "confirmed_by_sources": len(c["domains"]),
            "trending": trending,
        }
        facts = _attach_photo(facts, c["headline"], c["claim_key"])
        _queue(fmt, c["headline"], facts, c["confidence"], c["sources"])


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
        rows = [
            {
                "home": m["home"],
                "away": m["away"],
                "time": m["utc_date"][11:16] + " UTC" if len(m["utc_date"]) >= 16 else "",
            }
            for m in fixtures[:7]
        ]
        n = len(fixtures)
        _queue(
            "TEAM SHEET",
            f"Matchday — {n} fixture{'s' if n != 1 else ''} on {today}",
            {
                "headline": "TODAY'S FIXTURES",
                "fixture_rows": rows,
                "competition_code": fixtures[0]["competition_code"],
                "source_domains": [fixtures[0]["source"]],
            },
            1.0,
            [{"domain": fixtures[0]["source"], "title": "official fixtures"}],
        )


# ── publishing ──────────────────────────────────────────────────────────

def run_publish() -> None:
    # Manual kill switch: `data/PUBLISH_PAUSED` parks the whole queue
    # (used e.g. while the correct Instagram channel is being connected).
    if (config.DATA_DIR / "PUBLISH_PAUSED").exists():
        log.info("publish: paused via data/PUBLISH_PAUSED")
        return

    # Two publishers run: the session loop (low latency, when a session is
    # active) and the GitHub Actions cron (always on). BOTH publish — the
    # published-ledger dedups, so we prioritise never-miss over the small
    # chance of a duplicate. (A flapping "defer to primary" scheme silently
    # dropped posts when the loop died, which is worse for a live feed.)
    # Still record a pulse so we can tell from state whether a loop is alive.
    try:
        (config.DATA_DIR / "loop_pulse").write_text(str(int(time.time()) // 300 * 300))
    except OSError:
        pass

    # Publisher daily-limit backoff: when Buffer reports its free-plan cap,
    # a marker is dropped; hold off until the allowance window resets rather
    # than hammering the API every cycle. Auto-clears after BUFFER_BACKOFF_H.
    cap_marker = config.DATA_DIR / "BUFFER_CAPPED"
    if cap_marker.exists():
        try:
            since = time.time() - int(cap_marker.read_text().strip() or 0)
        except (OSError, ValueError):
            since = 1e9
        if since < config.BUFFER_BACKOFF_H * 3600:
            log.info("publish: holding off — publisher daily limit reached (%.1fh ago)", since / 3600)
            return
        cap_marker.unlink(missing_ok=True)  # window elapsed, try again

    # Drop stale news first: if publishing stalled (outage, dead loop), the
    # backlog is no longer timely and must not flood out as fake "breaking".
    expired = db.expire_stale_news(config.PUBLISH_STALE_HOURS)
    if expired:
        log.info("publish: expired %d stale queued post(s)", expired)

    # Rolling 24h send budget — Buffer counts posts, reels AND stories within
    # any 24h window (limit 50; we hold a margin). Live match commentary is
    # the priority, so news gets only a small slice and the rest stays free
    # for live events.
    sends_24h = db.sends_last_24h()
    if sends_24h >= config.DAILY_SEND_LIMIT:
        log.info("publish: 24h send budget reached (%d/%d) — holding", sends_24h, config.DAILY_SEND_LIMIT)
        return
    budget = config.DAILY_SEND_LIMIT - sends_24h
    news_24h = db.sends_last_24h(live_only=False)

    # Spacing between posts — live match moments bypass the gate. Non-live
    # posts go at most ONE per run (shareNow posts immediately; the loop
    # cadence provides the pacing).
    last = db.last_publish_time()
    gap_ok = last is None or (
        datetime.now(timezone.utc) - last >= timedelta(minutes=config.MIN_MINUTES_BETWEEN_POSTS)
    )

    published_news = 0
    for post in db.due_posts(config.MAX_POSTS_PER_RUN):
        if budget <= 0:
            break
        is_live = post["format"] in ("LIVE WHISTLE", "FINAL WHISTLE")
        if not is_live:
            # only a few of the highest-confidence breaking items per day;
            # the feed stays focused on live events, not dated news
            if news_24h + published_news >= config.NEWS_SEND_LIMIT:
                log.info("publish: news budget reached (%d) — reserving for live", config.NEWS_SEND_LIMIT)
                continue
            if not gap_ok or published_news >= 1:
                log.info("publish: pacing holds #%d", post["id"])
                continue
        sent = _publish_one(post)
        budget -= sent
        if not is_live and sent:
            published_news += 1


def _route(post: dict) -> str:
    """Where a post goes: live match commentary → Instagram Stories; the
    voiced recap reel and significant breaking news → the feed."""
    fmt = post["format"]
    headline = (post["headline"] or "").upper()
    if fmt == "FINAL WHISTLE" and headline.startswith("RECAP"):
        return "feed"      # the match recap reel
    if fmt in ("LIVE WHISTLE", "FINAL WHISTLE"):
        return "story"     # live commentary (kick-off, goals, cards, FT result)
    return "feed"          # breaking news


def _publish_one(post: dict) -> int:
    """Publish one queued item; returns the number of sends it consumed
    (each post, reel or story counts as one against the 24h budget)."""
    image_name = (post["image_path"] or "").split("/")[-1]
    image_url = config.media_public_url(image_name) if image_name else ""
    db.update_post(post["id"], image_url=image_url)
    is_live = post["format"] in ("LIVE WHISTLE", "FINAL WHISTLE")
    route = _route(post)

    if config.DRY_RUN:
        db.update_post(post["id"], status="dry_run", published_at=db.now_iso())
        log.info("DRY RUN — would publish #%d [%s] as %s", post["id"], post["format"], route)
        return 1

    if config.PUBLISHER == "buffer":
        from .publish import buffer_api as backend
    elif config.PUBLISHER == "instagram":
        from .publish import instagram_graph as backend
    else:
        log.info("publish: PUBLISHER=none, leaving #%d queued", post["id"])
        return 0

    if not backend.configured():
        log.warning("publish: %s not configured, leaving #%d queued", config.PUBLISHER, post["id"])
        return 0
    if not image_url:
        db.log_error("publish", f"post {post['id']}: no public image URL")
        return 0

    if route == "story":
        # live commentary as a 9:16 story card (fall back to the feed image)
        story_file = config.MEDIA_DIR / f"story_{post['id']}.png"
        story_url = config.media_public_url(story_file.name) if story_file.exists() else image_url
        external_id = backend.publish_story(story_url)
        what = "story"
    else:
        # feed post — a reel when an animated version exists
        video_file = config.MEDIA_DIR / f"post_{post['id']}.mp4"
        is_recap = post["format"] == "FINAL WHISTLE" and (post["headline"] or "").upper().startswith("RECAP")
        if is_recap and not video_file.exists():
            # a recap's value is the voiced reel — render it on demand here
            # (whichever publisher handles it), then hold ONE cycle: Buffer/IG
            # fetch the video from the public repo URL, so it must be pushed
            # before we can publish it. The next cycle publishes the reel.
            age_min = (datetime.now(timezone.utc) - _parse_dt(post["scheduled_for"])).total_seconds() / 60
            try:
                from .content import recap, voice
                recap.render_recap(post["id"], post["facts"], voice.build_recap_script(post["facts"]))
            except Exception as exc:
                db.log_error("publish", f"recap render #{post['id']}: {exc}")
            if video_file.exists():
                log.info("publish: rendered recap #%d — publishing next cycle once pushed", post["id"])
                return 0
            # rendering unavailable (e.g. cron runner can't do TTS): don't hold
            # forever — after a short grace, post the static recap card.
            if age_min < config.RECAP_RENDER_GRACE_MIN:
                log.info("publish: recap #%d video not ready — retrying (%.0fm)", post["id"], age_min)
                return 0
            log.info("publish: recap #%d video unavailable — posting static card", post["id"])
        # the reel must already be live on the CDN; if a fresh render hasn't
        # propagated yet Buffer 404s, the post stays queued and retries.
        video_url = config.media_public_url(video_file.name) if video_file.exists() else None
        external_id = backend.publish(post["caption"], image_url, post["alt_text"], video_url=video_url)
        what = "post"

    if external_id:
        db.update_post(
            post["id"], status="published", published_at=db.now_iso(), external_id=str(external_id)
        )
        db.ledger_mark(post["id"], str(external_id))
        db.record_send(post["id"], live=is_live, what=what)
        log.info("PUBLISHED #%d via %s as %s -> %s", post["id"], config.PUBLISHER, route, external_id)
        return 1
    # left queued on failure (transient cap/error) — retried next cycle,
    # and expired by the staleness sweep if it never succeeds
    return 0
