"""Build a World Cup "this week's fixtures" carousel, grouped by WC group.

Produces output/media/wc_week_0.png (cover) + one slide per pair of groups,
and prints a JSON summary (slide paths + suggested caption). Reusable any
week:

    python scripts/wc_week_carousel.py
"""

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402
from PIL import ImageDraw  # noqa: E402

from tffw import config  # noqa: E402
from tffw.content import graphics as g  # noqa: E402

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
STANDINGS = "https://site.api.espn.com/apis/v2/sports/soccer/fifa.world/standings"


def fetch_week():
    start = date.today()
    end = start + timedelta(days=7)
    r = requests.get(
        SCOREBOARD,
        params={"dates": f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"},
        timeout=25,
    ).json()
    fixtures = []
    for e in r.get("events") or []:
        comp = e["competitions"][0]
        sides = {c["homeAway"]: c["team"]["shortDisplayName"] for c in comp["competitors"]}
        when = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
        fixtures.append({"home": sides.get("home", "?"), "away": sides.get("away", "?"), "when": when})
    return fixtures, start, end


def fetch_groups():
    r = requests.get(STANDINGS, timeout=25).json()
    mapping, order = {}, []
    for ch in r.get("children") or []:
        name = ch.get("name", "")
        order.append(name)
        for entry in (ch.get("standings") or {}).get("entries") or []:
            mapping[entry["team"]["shortDisplayName"]] = name
    return mapping, order


def _slide_canvas(title: str):
    img, draw = g._canvas(texture_seed=hash(title) % 3)
    g._kicker(draw, "MATCHDAY")
    g._competition(draw, title)
    return img, draw


def render_cover(start: date, end: date, n_fixtures: int) -> Path:
    img, draw = _slide_canvas("WORLD CUP 2026")
    f1 = g.display(120)
    f2 = g.display(72)
    for text, font, y in (
        ("THIS WEEK'S", f1, 540),
        ("FIXTURES", f1, 690),
        (f"{start.strftime('%d %b').upper()} — {end.strftime('%d %b').upper()}", f2, 880),
    ):
        tw = draw.textlength(text, font=font)
        draw.text(((g.W - tw) / 2, y), text, font=font, fill=g.WHITE if font is f1 else g.GREEN_BRIGHT)
    f3 = g.meta(46)
    sub = f"{n_fixtures} MATCHES · SWIPE FOR YOUR GROUP >>"
    tw = g._tracked_width(draw, sub, f3, 6)
    g._tracked(draw, ((g.W - tw) / 2, 1030), sub, f3, g.META, 6)
    g._footer(draw, date.today().strftime("%d %b %Y").upper())
    path = config.MEDIA_DIR / "wc_week_0.png"
    img.save(path, "PNG", optimize=True)
    return path


def render_group_slide(idx: int, sections: list[tuple[str, list[dict]]]) -> Path:
    img, draw = _slide_canvas("WORLD CUP 2026 — THIS WEEK")
    y = 440
    for group_name, fixtures in sections:
        fh = g.display(58)
        tw = draw.textlength(group_name.upper(), font=fh)
        draw.text(((g.W - tw) / 2, y), group_name.upper(), font=fh, fill=g.GREEN_BRIGHT)
        y += 86
        frow = g.meta(42)
        for fx in fixtures:
            line = (
                f"{fx['when'].strftime('%a %d').upper()}  ·  "
                f"{fx['home'].upper()} v {fx['away'].upper()}  ·  "
                f"{fx['when'].strftime('%H:%M')} UTC"
            )
            font = frow
            while draw.textlength(line, font=font) > g.W - 2 * g.MARGIN and font.size > 30:
                font = g.meta(font.size - 2)
            tw = draw.textlength(line, font=font)
            draw.text(((g.W - tw) / 2, y), line, font=font, fill=g.WHITE)
            y += 62
        y += 44
    g._footer(draw, date.today().strftime("%d %b %Y").upper())
    path = config.MEDIA_DIR / f"wc_week_{idx}.png"
    img.save(path, "PNG", optimize=True)
    return path


def main() -> int:
    fixtures, start, end = fetch_week()
    mapping, group_order = fetch_groups()

    by_group: dict[str, list] = {}
    for fx in fixtures:
        group = mapping.get(fx["home"]) or mapping.get(fx["away"]) or "Other"
        by_group.setdefault(group, []).append(fx)
    for fixtures_list in by_group.values():
        fixtures_list.sort(key=lambda f: f["when"])

    ordered = [(name, by_group[name]) for name in group_order if name in by_group]
    if "Other" in by_group:
        ordered.append(("Other fixtures", by_group["Other"]))

    paths = [str(render_cover(start, end, len(fixtures)))]
    slide_idx = 1
    for i in range(0, len(ordered), 2):
        sections = ordered[i : i + 2]
        paths.append(str(render_group_slide(slide_idx, sections)))
        slide_idx += 1

    print(json.dumps({"slides": paths, "fixtures": len(fixtures), "groups": len(ordered)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
