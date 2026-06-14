"""World Cup group-standings carousel.

Renders a cover + one clean table slide per group that has played, reusing the
brand table template. With --post, pushes the slides to the repo and publishes
the carousel via Buffer (counts against the rolling send budget).

    python scripts/wc_standings_carousel.py          # render only (prints JSON)
    python scripts/wc_standings_carousel.py --post    # render + publish
"""

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tffw import config, db  # noqa: E402
from tffw.content import graphics as g  # noqa: E402
from tffw.sources import espn  # noqa: E402


def _gd_int(value) -> int:
    try:
        return int(str(value).replace("+", "").strip())
    except (TypeError, ValueError):
        return 0


def render_cover(n_groups: int) -> Path:
    img, draw = g._canvas(texture_seed=4)
    g._kicker(draw, "MATCHDAY")
    g._competition(draw, "WORLD CUP 2026")
    f1 = g.display(118)
    for text, y in (("GROUP", 520), ("STANDINGS", 660)):
        tw = draw.textlength(text, font=f1)
        draw.text(((g.W - tw) / 2, y), text, font=f1, fill=g.WHITE)
    f3 = g.meta(46)
    sub = f"THE GROUPS SO FAR · SWIPE >>"
    tw = g._tracked_width(draw, sub, f3, 6)
    g._tracked(draw, ((g.W - tw) / 2, 860), sub, f3, g.GREEN_BRIGHT, 6)
    g._footer(draw, date.today().strftime("%d %b %Y").upper())
    path = config.MEDIA_DIR / "wc_standings_0.png"
    img.save(path, "PNG", optimize=True)
    return path


def render_group(idx: int, group: dict) -> Path:
    rows = [
        {"position": r["rank"], "team": r["team"], "played": r["played"],
         "gd": _gd_int(r["gd"]), "points": r["points"]}
        for r in group["rows"]
    ]
    facts = {
        "headline": group["name"].upper(),
        "table_rows": rows,
        "advance_places": 2,  # top two advance from a World Cup group
        "date_label": date.today().strftime("%d %b %Y").upper(),
    }
    img = g._table("MATCHDAY", facts)
    path = config.MEDIA_DIR / f"wc_standings_{idx}.png"
    img.save(path, "PNG", optimize=True)
    return path


def main() -> int:
    groups = espn.standings()
    if not groups:
        print(json.dumps({"error": "no standings with games yet"}))
        return 0

    # reel-first: an animated navy standings reel (cover + one table per group)
    reel = g.render_standings_reel(0, groups)
    reel_path = config.MEDIA_DIR / "wc_standings_reel.mp4"
    thumb_path = config.MEDIA_DIR / "wc_standings_reel.png"
    if reel.name != reel_path.name:
        reel.replace(reel_path)
    g._standings_slide("GROUP STANDINGS", "THE GROUPS SO FAR", None).save(thumb_path, "PNG", optimize=True)

    caption = (
        "📊 WORLD CUP 2026 — GROUP STANDINGS\n\n"
        "How the groups look so far 🔵 Top two advance. Where does your nation sit? 👇\n\n"
        "#FIFAWorldCup #WorldCup2026 #Standings #Football #Soccer #Groups"
    )
    result = {"reel": str(reel_path.relative_to(config.ROOT)), "groups": len(groups), "caption": caption}

    if "--post" in sys.argv:
        for pth in (reel_path, thumb_path):
            subprocess.run(["git", "add", str(pth)], cwd=config.ROOT, check=False)
        subprocess.run(["git", "-c", "user.name=Claude", "-c", "user.email=noreply@anthropic.com",
                        "commit", "-q", "-m", "agent: world cup standings reel"],
                       cwd=config.ROOT, check=False)
        subprocess.run(["git", "push", "-q"], cwd=config.ROOT, check=False)
        from tffw.publish import buffer_api
        ext = buffer_api.publish(
            caption, config.media_public_url(thumb_path.name), "World Cup group standings reel",
            video_url=config.media_public_url(reel_path.name),
        )
        result["posted"] = ext
        if ext:
            db.record_send(0, live=False, what="post")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
