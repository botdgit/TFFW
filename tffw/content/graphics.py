"""Branded graphic rendering with Pillow.

Every visual is generated from scratch using the green-and-white template —
no third-party images or video are ever used, so there is nothing to
license. Output is 1080x1350 (Instagram portrait feed size).
"""

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .. import config
from ..logger import get_logger

log = get_logger("graphics")

W, H = 1080, 1350

GREEN = config.BRAND_GREEN
GREEN_DARK = config.BRAND_GREEN_DARK
WHITE = config.BRAND_WHITE
OFFWHITE = config.BRAND_OFFWHITE

FONT_CANDIDATES_BOLD = [
    str(config.FONT_DIR / "Inter-Bold.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]
FONT_CANDIDATES_REG = [
    str(config.FONT_DIR / "Inter-Regular.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def _font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def bold(size: int) -> ImageFont.FreeTypeFont:
    return _font(FONT_CANDIDATES_BOLD, size)


def regular(size: int) -> ImageFont.FreeTypeFont:
    return _font(FONT_CANDIDATES_REG, size)


def render(post_id: int, fmt: str, facts: dict) -> Path:
    """Render the graphic for a post; returns the file path."""
    if fmt in ("FINAL WHISTLE", "LIVE WHISTLE") and facts.get("home"):
        img = _scoreboard(fmt, facts)
    elif fmt == "TEAM SHEET" and facts.get("table_rows"):
        img = _table(fmt, facts)
    else:
        img = _headline_card(fmt, facts)

    path = config.MEDIA_DIR / f"post_{post_id}.png"
    img.save(path, "PNG", optimize=True)
    log.info("rendered %s -> %s", fmt, path.name)
    return path


# ── shared chrome ───────────────────────────────────────────────────────

def _canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), OFFWHITE)
    draw = ImageDraw.Draw(img)
    # vertical green gradient header band
    for y in range(0, 360):
        blend = y / 360
        c1 = _hex(GREEN_DARK)
        c2 = _hex(GREEN)
        col = tuple(int(a + (b - a) * blend) for a, b in zip(c1, c2))
        draw.line([(0, y), (W, y)], fill=col)
    return img, draw


def _hex(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _badge(draw: ImageDraw.ImageDraw, fmt: str) -> None:
    f = bold(54)
    text = f"●  {fmt}"
    tw = draw.textlength(text, font=f)
    x, y = 60, 70
    draw.rounded_rectangle([x - 24, y - 18, x + tw + 28, y + 78], radius=18, fill=WHITE)
    draw.text((x, y), text, font=f, fill=GREEN_DARK)


def _footer(draw: ImageDraw.ImageDraw, sub: str = "") -> None:
    draw.rectangle([0, H - 130, W, H], fill=GREEN_DARK)
    f = bold(40)
    draw.text((60, H - 100), config.BRAND_HANDLE, font=f, fill=WHITE)
    if sub:
        fr = regular(32)
        tw = draw.textlength(sub, font=fr)
        draw.text((W - 60 - tw, H - 94), sub[:48], font=fr, fill=OFFWHITE)


def _whistle_stripe(draw: ImageDraw.ImageDraw) -> None:
    draw.rectangle([0, 352, W, 368], fill=GREEN_DARK)


# ── templates ───────────────────────────────────────────────────────────

def _scoreboard(fmt: str, facts: dict) -> Image.Image:
    img, draw = _canvas()
    _badge(draw, fmt)
    comp = facts.get("competition", "")
    if comp:
        f = regular(40)
        draw.text((60, 240), comp.upper(), font=f, fill=OFFWHITE)
    _whistle_stripe(draw)

    home, away = facts.get("home", "?"), facts.get("away", "?")
    hs, as_ = facts.get("home_score"), facts.get("away_score")
    score = f"{hs} - {as_}" if hs is not None else "VS"

    fscore = bold(190)
    sw = draw.textlength(score, font=fscore)
    draw.text(((W - sw) / 2, 560), score, font=fscore, fill=GREEN_DARK)

    fteam = bold(64)
    for team, y in ((home, 450), (away, 820)):
        lines = textwrap.wrap(team, 22) or ["?"]
        for i, line in enumerate(lines[:2]):
            tw = draw.textlength(line, font=fteam)
            draw.text(((W - tw) / 2, y + i * 72), line, font=fteam, fill="#1A1A1A")

    status = "FULL-TIME" if fmt == "FINAL WHISTLE" else facts.get("status_label", "LIVE")
    fst = bold(48)
    tw = draw.textlength(status, font=fst)
    draw.rounded_rectangle(
        [(W - tw) / 2 - 36, 1010, (W + tw) / 2 + 36, 1100], radius=20, fill=GREEN
    )
    draw.text(((W - tw) / 2, 1028), status, font=fst, fill=WHITE)

    _footer(draw, facts.get("date_label", ""))
    return img


def _wrap_px(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    """Wrap text by measured pixel width rather than character count."""
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_w:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _headline_card(fmt: str, facts: dict) -> Image.Image:
    img, draw = _canvas()
    _badge(draw, fmt)
    f = regular(40)
    draw.text((60, 240), config.BRAND_NAME.upper(), font=f, fill=OFFWHITE)
    _whistle_stripe(draw)

    headline = facts.get("headline", "Football update")
    max_w = W - 120
    # pick the largest size whose wrapped text fits the body area
    for size in (92, 78, 64, 54):
        fh = bold(size)
        lines = _wrap_px(draw, headline, fh, max_w)
        if len(lines) * (size + 22) <= 620:
            break
    lines = lines[:8]
    y = 460
    for line in lines:
        draw.text((60, y), line, font=fh, fill="#1A1A1A")
        y += size + 22

    domains = facts.get("source_domains") or []
    if domains:
        fs = regular(36)
        draw.text((60, H - 220), "Sources: " + " · ".join(domains[:3]), font=fs, fill="#5A6B5F")

    _footer(draw, facts.get("date_label", ""))
    return img


def _table(fmt: str, facts: dict) -> Image.Image:
    img, draw = _canvas()
    _badge(draw, fmt)
    f = regular(40)
    draw.text((60, 240), facts.get("headline", "TABLE").upper()[:40], font=f, fill=OFFWHITE)
    _whistle_stripe(draw)

    rows = facts.get("table_rows", [])[:10]
    fhead = bold(40)
    frow = regular(42)
    y = 430
    draw.text((70, y), "#", font=fhead, fill=GREEN_DARK)
    draw.text((150, y), "TEAM", font=fhead, fill=GREEN_DARK)
    draw.text((760, y), "P", font=fhead, fill=GREEN_DARK)
    draw.text((860, y), "GD", font=fhead, fill=GREEN_DARK)
    draw.text((970, y), "PTS", font=fhead, fill=GREEN_DARK)
    y += 70
    for r in rows:
        if r["position"] % 2 == 0:
            draw.rectangle([50, y - 8, W - 50, y + 54], fill="#E4EFE7")
        draw.text((70, y), str(r["position"]), font=frow, fill="#1A1A1A")
        draw.text((150, y), str(r["team"])[:24], font=frow, fill="#1A1A1A")
        draw.text((760, y), str(r["played"]), font=frow, fill="#1A1A1A")
        draw.text((860, y), f'{r["gd"]:+d}', font=frow, fill="#1A1A1A")
        draw.text((970, y), str(r["points"]), font=bold(44), fill=GREEN_DARK)
        y += 74

    _footer(draw, facts.get("date_label", ""))
    return img
