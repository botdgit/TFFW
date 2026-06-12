"""Offline self-check: exercises DB, verification, captions (template path),
graphics and dashboard without any network calls. Run after cloning:

    python scripts/selfcheck.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tffw import db, dashboard  # noqa: E402
from tffw.content import captions, graphics  # noqa: E402
from tffw import verification  # noqa: E402


def main() -> int:
    db.init_db()
    print("✓ database initialised")

    # verification
    a = verification.tokenize("Arsenal agree £80m deal for striker")
    b = verification.tokenize("Striker set for £80m Arsenal move as deal agreed")
    assert verification.similarity(a, b) > 0.2
    clusters = verification.cluster_news(
        [
            {"title": "Arsenal agree £80m deal for striker", "domain": "bbc.co.uk",
             "link": "https://x/1", "published": "2026-01-01T10:00:00", "summary": ""},
            {"title": "Striker agrees £80m Arsenal deal", "domain": "skysports.com",
             "link": "https://x/2", "published": "2026-01-01T10:05:00", "summary": ""},
        ]
    )
    assert clusters and clusters[0]["confidence"] == 1.0, clusters
    assert verification.classify_news("Club agree transfer fee for star") == "TRANSFER WHISTLE"
    print("✓ verification clustering + classification")

    # captions (template fallback path)
    facts = {
        "home": "Arsenal", "away": "Chelsea", "home_score": 2, "away_score": 1,
        "competition": "Premier League", "competition_code": "PL",
    }
    caption, alt = captions.build_caption("FINAL WHISTLE", facts, 7)
    assert "2-1" in caption and "#premierleague" in caption and alt
    print("✓ caption + alt text:", caption.splitlines()[0])

    # graphics — one render per template family
    p1 = graphics.render(9001, "FINAL WHISTLE", {**facts, "date_label": "01 JAN 2026"})
    p2 = graphics.render(9002, "BREAKING", {
        "headline": "Star striker ruled out for six weeks with hamstring injury",
        "source_domains": ["bbc.co.uk", "skysports.com"], "date_label": "01 JAN 2026",
    })
    p3 = graphics.render(9003, "TEAM SHEET", {
        "headline": "Premier League table",
        "table_rows": [
            {"position": i, "team": f"Team {i}", "played": 20, "gd": 10 - i, "points": 50 - i}
            for i in range(1, 11)
        ],
        "date_label": "01 JAN 2026",
    })
    for p in (p1, p2, p3):
        assert p.exists() and p.stat().st_size > 10_000, p
    print("✓ graphics rendered:", p1.name, p2.name, p3.name)

    # queue + dashboard
    pid = db.enqueue_post(
        "FINAL WHISTLE", "selfcheck post", caption, "", alt, 1.0,
        [{"domain": "selfcheck"}], facts,
    )
    dashboard.build()
    assert (db.dashboard_data()["counts"]["queued"]) >= 0
    if pid:
        db.update_post(pid, status="skipped")
    print("✓ queue + dashboard")

    # clean up sample renders
    for p in (p1, p2, p3):
        p.unlink(missing_ok=True)
    print("\nSELF-CHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
