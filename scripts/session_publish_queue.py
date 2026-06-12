"""Print due queue items as JSON for an external publisher (e.g. a Claude
session publishing through the Buffer connector instead of an API token).

Honours the same pacing gates as tffw.pipeline.run_publish: daily cap,
minimum gap between posts, and MAX_POSTS_PER_RUN.

The publishing session may rewrite the caption BODY in the brand voice
(fast, sharp, opinionated-but-credible) using ONLY the headline and
story_summary fields below — never adding facts — and must keep the tail
(hashtags / Sources / 📸 credit lines) intact.

    python scripts/session_publish_queue.py
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tffw import config, db  # noqa: E402

BRANCH = "claude/football-whistle-instagram-agent-au8zqt"


def main() -> int:
    db.init_db()

    if (config.DATA_DIR / "PUBLISH_PAUSED").exists():
        print(json.dumps({"due": [], "reason": "publishing paused (data/PUBLISH_PAUSED)"}))
        return 0

    if db.published_count_today() >= config.MAX_POSTS_PER_DAY:
        print(json.dumps({"due": [], "reason": "daily cap reached"}))
        return 0

    last = db.last_publish_time()
    if last is not None:
        gap = datetime.now(timezone.utc) - last
        if gap < timedelta(minutes=config.MIN_MINUTES_BETWEEN_POSTS):
            print(json.dumps({"due": [], "reason": f"spacing gate ({gap})"}))
            return 0

    # one post per call: the session loop runs every couple of minutes, so
    # this paces a busy queue smoothly instead of bursting
    due = []
    for p in db.due_posts(1):
        filename = (p["image_path"] or "").split("/")[-1]
        base = f"https://raw.githubusercontent.com/botdgit/TFFW/{BRANCH}/output/media"
        item = {
            "id": p["id"],
            "format": p["format"],
            "headline": p["headline"],
            "caption": p["caption"],
            "story_summary": p["facts"].get("story_summary", ""),
            "engagement_prompt": p["caption"].split("\n.\n")[0].splitlines()[-1],
            "alt_text": p["alt_text"],
            "confidence": p["confidence"],
            "image_url": f"{base}/{filename}",
        }
        if (config.MEDIA_DIR / f"post_{p['id']}.mp4").exists():
            item["video_url"] = f"{base}/post_{p['id']}.mp4"
            item["instagram_type"] = "reel"
        if (config.MEDIA_DIR / f"story_{p['id']}.png").exists():
            item["story_url"] = f"{base}/story_{p['id']}.png"
        due.append(item)
    print(json.dumps({"due": due}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
