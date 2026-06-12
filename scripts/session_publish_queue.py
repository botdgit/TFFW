"""Print due queue items as JSON for an external publisher (e.g. a Claude
session publishing through the Buffer connector instead of an API token).

Honours the same pacing gates as tffw.pipeline.run_publish: daily cap,
minimum gap between posts, and MAX_POSTS_PER_RUN.

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

    if db.published_count_today() >= config.MAX_POSTS_PER_DAY:
        print(json.dumps({"due": [], "reason": "daily cap reached"}))
        return 0

    last = db.last_publish_time()
    if last is not None:
        gap = datetime.now(timezone.utc) - last
        if gap < timedelta(minutes=config.MIN_MINUTES_BETWEEN_POSTS):
            print(json.dumps({"due": [], "reason": f"spacing gate ({gap})"}))
            return 0

    due = []
    for p in db.due_posts(config.MAX_POSTS_PER_RUN):
        filename = (p["image_path"] or "").split("/")[-1]
        due.append(
            {
                "id": p["id"],
                "format": p["format"],
                "headline": p["headline"],
                "caption": p["caption"],
                "alt_text": p["alt_text"],
                "confidence": p["confidence"],
                "image_url": f"https://raw.githubusercontent.com/botdgit/TFFW/{BRANCH}/output/media/{filename}",
            }
        )
    print(json.dumps({"due": due}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
