"""Mark a queued post as published (or failed) after an external publisher
handled it, then rebuild the dashboard.

    python scripts/mark_published.py <post_id> <external_id_or_url> [failed]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tffw import db, dashboard  # noqa: E402


def main() -> int:
    post_id = int(sys.argv[1])
    external_id = sys.argv[2]
    failed = len(sys.argv) > 3 and sys.argv[3] == "failed"
    db.init_db()
    db.update_post(
        post_id,
        status="failed" if failed else "published",
        published_at=db.now_iso(),
        external_id=external_id,
    )
    if not failed:
        db.ledger_mark(post_id, external_id)
    dashboard.build()
    print(f"post {post_id} -> {'failed' if failed else 'published'} ({external_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
