"""Branded graphic rendering with Pillow.

Design system ("Final Whistle" brand):
  • Palette: an electric-lime accent (#C6F24E) on a deep navy gradient,
    white type, muted blue-grey for meta text. Lime-on-navy is a punchy,
    high-energy sports pairing that stops the scroll far better than the
    old muted blue accent. The accent is env-tunable (config.BRAND_ACCENT).
  • Type: Anton (condensed display, headlines/scores), Archivo Black
    (kickers/labels), Barlow Condensed (meta/supporting).
  • Headlines set over photography carry a dark stroke so they stay legible
    on any image, never relying on the gradient alone.
  • Every post carries the same chrome: white logo badge top-centre,
    format kicker chip, faint pitch markings, footer with handle + date.

Every visual is generated from scratch from these templates — no
third-party images or video are ever used, so there is nothing to license.
Output is 1080x1350 (Instagram portrait feed size).
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .. import config
from ..logger import get_logger

log = get_logger("graphics")

W, H = 1080, 1350
MARGIN = 80

# ── palette ─────────────────────────────────────────────────────────────
# Accent is an electric lime on deep navy (names kept for compatibility).
# Sourced from config so it can be re-tuned via env without a code change.
GREEN = config.BRAND_ACCENT          # primary accent (electric lime)
GREEN_BRIGHT = config.BRAND_ACCENT_BRIGHT  # brighter accent for scores / CTAs
PITCH_TOP = "#1C3A5E"    # background gradient (navy)
PITCH_BOTTOM = "#091627"  # deep navy
WHITE = "#FFFFFF"
META = "#8FA8CC"         # muted blue for meta text
LINE = (255, 255, 255, 22)  # faint pitch markings
INK = "#0A1A2E"          # dark navy text on light surfaces
CARD = "#EFF4FB"         # light blue-tinted surface

FONT_DISPLAY = config.FONT_DIR / "Anton-Regular.ttf"
FONT_LABEL = config.FONT_DIR / "ArchivoBlack-Regular.ttf"
FONT_META = config.FONT_DIR / "BarlowCondensed-SemiBold.ttf"
FONT_META_LIGHT = config.FONT_DIR / "BarlowCondensed-Medium.ttf"
LOGO = config.ROOT / "assets" / "brand" / "logo.png"
_LOGO_WHITE_CACHE = config.ROOT / "assets" / "brand" / "logo_white.png"

_FALLBACK = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    for candidate in (path, Path(_FALLBACK)):
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def display(size: int) -> ImageFont.FreeTypeFont:
    return _font(FONT_DISPLAY, size)


def label(size: int) -> ImageFont.FreeTypeFont:
    return _font(FONT_LABEL, size)


def meta(size: int) -> ImageFont.FreeTypeFont:
    return _font(FONT_META, size)


def meta_light(size: int) -> ImageFont.FreeTypeFont:
    return _font(FONT_META_LIGHT, size)


def _hex(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


# ── shared chrome ───────────────────────────────────────────────────────

def _logo_white(height: int) -> Image.Image | None:
    """Logo recoloured to white (it is single-colour green on alpha)."""
    if not LOGO.exists():
        return None
    if not _LOGO_WHITE_CACHE.exists():
        src = Image.open(LOGO).convert("RGBA")
        white = Image.new("RGBA", src.size, (255, 255, 255, 0))
        white.putalpha(src.getchannel("A"))
        _LOGO_WHITE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        white.save(_LOGO_WHITE_CACHE)
    img = Image.open(_LOGO_WHITE_CACHE).convert("RGBA")
    w = int(img.width * height / img.height)
    return img.resize((w, height), Image.LANCZOS)


BG_DIR = config.ROOT / "assets" / "backgrounds"


def _cover(photo: Image.Image, w: int, h: int, top_bias: float = 0.5) -> Image.Image:
    """Cover-crop an image to exactly (w, h)."""
    scale = max(w / photo.width, h / photo.height)
    photo = photo.resize((int(photo.width * scale) + 1, int(photo.height * scale) + 1), Image.LANCZOS)
    left = (photo.width - w) // 2
    top = int((photo.height - h) * top_bias)
    return photo.crop((left, top, left + w, top + h))


def _stadium_texture(img: Image.Image, seed: int) -> Image.Image:
    """Blend a licensed stadium photo into the pitch background so every
    card has imagery (heavy brand-green duotone keeps text legible).
    Seed is spread so consecutive posts cycle different backgrounds and
    crop positions."""
    backgrounds = sorted(BG_DIR.glob("stadium_*.jpg"))
    if not backgrounds:
        return img
    spread = (seed * 2654435761) & 0xFFFFFFFF  # Knuth multiplicative hash
    try:
        photo = Image.open(backgrounds[spread % len(backgrounds)]).convert("L")
    except OSError:
        return img
    photo = _cover(photo.convert("RGB"), W, H, top_bias=((spread >> 8) % 70) / 100)
    # duotone: map luminance into the pitch palette, then blend subtly
    photo = photo.convert("L")
    lo, hi = _hex(PITCH_BOTTOM), _hex("#2E4D75")
    duo = Image.merge("RGB", [
        photo.point(lambda v, a=a, b=b: int(a + (b - a) * v / 255))
        for a, b in zip(lo, hi)
    ])
    return Image.blend(img, duo, 0.5)


def _canvas(texture_seed: int | None = None) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), PITCH_BOTTOM)
    draw = ImageDraw.Draw(img)

    # vertical pitch gradient
    top, bottom = _hex(PITCH_TOP), _hex(PITCH_BOTTOM)
    for y in range(H):
        t = y / H
        draw.line(
            [(0, y), (W, y)],
            fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)),
        )

    if texture_seed is not None:
        img = _stadium_texture(img, texture_seed)
        draw = ImageDraw.Draw(img)

    # soft radial glow behind the content area
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W // 2 - 520, 330, W // 2 + 520, 1180], fill=(*_hex(GREEN), 26))
    glow = glow.filter(ImageFilter.GaussianBlur(180))
    img.paste(Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB"), (0, 0))
    draw = ImageDraw.Draw(img)

    # faint pitch markings: centre circle + halfway line, off-canvas right
    marks = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    md = ImageDraw.Draw(marks)
    md.ellipse([W - 420, -260, W + 320, 480], outline=LINE, width=3)
    md.ellipse([W - 300, -140, W + 200, 360], outline=LINE, width=3)
    md.line([(0, 132), (W, 132)], fill=(255, 255, 255, 0))
    md.ellipse([-260, H - 420, 300, H + 140], outline=LINE, width=3)
    img.paste(Image.alpha_composite(img.convert("RGBA"), marks).convert("RGB"), (0, 0))
    draw = ImageDraw.Draw(img)

    # logo badge top-left (kicker pill lives top-right)
    badge = _logo_white(140)
    if badge is not None:
        img.paste(badge, (56, 56), badge)

    return img, draw


def _tracked(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str,
             font: ImageFont.FreeTypeFont, fill, tracking: int = 6) -> float:
    """Draw text with letterspacing; returns end x."""
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking
    return x


def _tracked_width(draw: ImageDraw.ImageDraw, text: str,
                   font: ImageFont.FreeTypeFont, tracking: int = 6) -> float:
    return sum(draw.textlength(c, font=font) + tracking for c in text) - (tracking if text else 0)


def _display_line(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str,
                  font: ImageFont.FreeTypeFont, fill=WHITE, stroke: int = 0) -> None:
    """Draw a headline line. A dark stroke keeps white type legible over
    photography (and gives all display text a crisper, bolder edge) without
    relying on the background gradient alone."""
    if stroke:
        draw.text(xy, text, font=font, fill=fill,
                  stroke_width=stroke, stroke_fill=PITCH_BOTTOM)
    else:
        draw.text(xy, text, font=font, fill=fill)


def _kicker(draw: ImageDraw.ImageDraw, fmt: str, y: int = 70) -> None:
    """Format chip: ● FORMAT NAME on a green pill, top-right corner so it
    never covers the middle of a photo background."""
    f = label(30)
    text = fmt.upper()
    tw = _tracked_width(draw, text, f, 7)
    pad, dot_r = 32, 8
    total = tw + pad * 2 + dot_r * 2 + 16
    x0 = W - 60 - total
    draw.rounded_rectangle([x0, y, x0 + total, y + 68], radius=34, fill=GREEN)
    cy = y + 34
    draw.ellipse([x0 + pad - dot_r, cy - dot_r, x0 + pad + dot_r, cy + dot_r], fill=PITCH_BOTTOM)
    _tracked(draw, (x0 + pad + dot_r * 2 + 16, y + 16), text, f, PITCH_BOTTOM, 7)


def _footer(draw: ImageDraw.ImageDraw, sub: str = "") -> None:
    y = H - 118
    draw.line([(MARGIN, y), (W - MARGIN, y)], fill=(255, 255, 255, 38), width=2)
    f = meta(44)
    _tracked(draw, (MARGIN, y + 28), config.BRAND_HANDLE.upper(), f, WHITE, 2)
    if sub:
        fr = meta_light(42)
        tw = _tracked_width(draw, sub.upper(), fr, 4)
        _tracked(draw, (W - MARGIN - tw, y + 30), sub.upper(), fr, META, 4)


def _trophy(draw: ImageDraw.ImageDraw, cx: float, cy: float, h: int, color) -> None:
    """Stylised trophy glyph (our own drawing — official tournament logos
    are trademarks and are never used). cx,cy = top-centre, h = height."""
    w = h * 0.78
    bowl_h = h * 0.46
    # bowl
    draw.pieslice([cx - w / 2, cy - bowl_h * 0.35, cx + w / 2, cy + bowl_h * 1.4],
                  start=0, end=180, fill=color)
    # handles
    lw = max(2, int(h * 0.07))
    draw.arc([cx - w * 0.82, cy - bowl_h * 0.1, cx - w * 0.18, cy + bowl_h * 0.9],
             start=90, end=270, fill=color, width=lw)
    draw.arc([cx + w * 0.18, cy - bowl_h * 0.1, cx + w * 0.82, cy + bowl_h * 0.9],
             start=270, end=90, fill=color, width=lw)
    # stem + base
    draw.rectangle([cx - w * 0.09, cy + bowl_h * 1.05, cx + w * 0.09, cy + h * 0.78], fill=color)
    draw.rectangle([cx - w * 0.30, cy + h * 0.78, cx + w * 0.30, cy + h * 0.92], fill=color)


def _competition(draw: ImageDraw.ImageDraw, text: str, y: int = 372) -> None:
    if not text:
        return
    f = meta(46)
    t = text.upper()
    tw = _tracked_width(draw, t, f, 10)
    is_wc = "world cup" in text.lower()
    icon = 44 if is_wc else 0
    gap = 18 if is_wc else 0
    x0 = (W - tw - icon - gap) / 2
    if is_wc:
        _trophy(draw, x0 + icon / 2, y + 4, icon, GREEN_BRIGHT)
    _tracked(draw, (x0 + icon + gap, y), t, f, META, 10)


def _fit_display(draw: ImageDraw.ImageDraw, text: str, max_w: int,
                 start: int, floor: int = 40) -> ImageFont.FreeTypeFont:
    size = start
    while size > floor and draw.textlength(text, font=display(size)) > max_w:
        size -= 4
    return display(size)


def _wrap_px(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
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


# ── entry point ─────────────────────────────────────────────────────────

def render(post_id: int, fmt: str, facts: dict) -> Path:
    """Render the graphic for a post; returns the file path."""
    if facts.get("table_rows"):
        img = _table(fmt, facts)
    elif facts.get("fixture_rows"):
        img = _fixtures(fmt, facts)
    elif fmt in ("FINAL WHISTLE", "LIVE WHISTLE") and facts.get("home"):
        img = _scoreboard(fmt, facts)
    elif facts.get("photo_path"):
        img = _photo_card(fmt, facts)
    else:
        img = _headline_card(fmt, facts)

    path = config.MEDIA_DIR / f"post_{post_id}.png"
    img.save(path, "PNG", optimize=True)
    log.info("rendered %s -> %s", fmt, path.name)
    return path


# ── templates ───────────────────────────────────────────────────────────

def _flag_band(img: Image.Image, flag_file: Path, y0: int, y1: int) -> Image.Image:
    """Paste a darkened national flag behind a team row. A strong
    left-to-right scrim keeps the darkest area under the left-aligned team
    name and scorer credits, so a busy flag crest (e.g. the Argentina sun)
    can never wash the text out."""
    try:
        flag = Image.open(flag_file).convert("RGB")
    except OSError:
        return img
    h = y1 - y0
    band = _cover(flag, W, h).filter(ImageFilter.GaussianBlur(3))
    # base darkening so the whole band recedes behind the type
    overlay = Image.new("RGBA", (W, h), (*_hex(PITCH_BOTTOM), 172))
    # extra left-anchored scrim (opaque under the text column, fading right)
    scrim = Image.new("RGBA", (W, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scrim)
    text_col = W * 0.72
    for x in range(W):
        a = int(220 * max(0.0, 1 - x / text_col))
        sd.line([(x, 0), (x, h)], fill=(*_hex(PITCH_BOTTOM), a))
    band = Image.alpha_composite(band.convert("RGBA"), overlay)
    band = Image.alpha_composite(band, scrim).convert("RGB")
    img.paste(band, (0, y0))
    return img


def _scoreboard(fmt: str, facts: dict) -> Image.Image:
    img, draw = _canvas()

    home, away = facts.get("home", "?"), facts.get("away", "?")
    # national-team matches get flag panels behind the team rows — but only
    # when BOTH teams resolve to a flag, so the card is never lopsided (one
    # row with imagery, the other flat) when a flag hasn't been cached yet.
    from . import flags

    home_flag = flags.flag_path(facts.get("home_full", home))
    away_flag = flags.flag_path(facts.get("away_full", away))
    has_flags = bool(home_flag and away_flag)
    if has_flags:
        img = _flag_band(img, home_flag, 560, 850)
        img = _flag_band(img, away_flag, 852, 1142)
    draw = ImageDraw.Draw(img)

    _kicker(draw, fmt)
    _competition(draw, facts.get("competition", ""))
    hs, as_ = facts.get("home_score"), facts.get("away_score")
    has_score = hs is not None

    status = "FULL-TIME" if fmt == "FINAL WHISTLE" else facts.get("status_label", "LIVE")

    # status pill
    f = label(30)
    tw = _tracked_width(draw, status, f, 6)
    pad = 30
    x0 = (W - tw - pad * 2) / 2
    y0 = 478
    draw.rounded_rectangle([x0, y0, x0 + tw + pad * 2, y0 + 64], radius=14,
                           outline=GREEN, width=3)
    _tracked(draw, (x0 + pad, y0 + 14), status, f, GREEN_BRIGHT, 6)

    # team rows — names left, scores right, divider between
    score_x = W - MARGIN
    name_max = W - 2 * MARGIN - 220 if has_score else W - 2 * MARGIN
    rows = [(home, hs, 640), (away, as_, 880)]

    # one shared name size so both rows match
    size = 110
    for name, _, _ in rows:
        f_try = _fit_display(draw, name.upper(), name_max, size)
        size = min(size, f_try.size)
    fname = display(size)
    fscore = display(150)

    # over a flag band, stroke the name and brighten the scorer credits so
    # they stay crisp against the imagery; on plain navy no stroke is needed
    name_stroke = 3 if has_flags else 0
    scorer_fill = "#E4ECF8" if has_flags else META
    scorer_stroke = 2 if has_flags else 0

    scorers = facts.get("scorers") or []
    for side, (name, score, y) in zip(("home", "away"), rows):
        ny = y + (150 - size) // 2 + 10
        _display_line(draw, (MARGIN, ny), name.upper(), fname, WHITE, name_stroke)
        if has_score:
            s = str(score)
            sw = draw.textlength(s, font=fscore)
            _display_line(draw, (score_x - sw, y), s, fscore, GREEN_BRIGHT, name_stroke)
        # scorer credits under the team name (from the official feed)
        side_scorers = [sc for sc in scorers if sc.get("side") == side and sc.get("name")]
        if side_scorers:
            fsc = meta_light(34)
            line = "  ·  ".join(
                f"{sc['name'].upper()} {sc.get('minute','')}"
                + (" (P)" if sc.get("pen") else "")
                + (" (OG)" if sc.get("og") else "")
                for sc in side_scorers[:3]
            )
            while draw.textlength(line, font=fsc) > W - 2 * MARGIN - 200 and fsc.size > 26:
                fsc = meta_light(fsc.size - 2)
            draw.text((MARGIN + 4, ny + size + 14), line, font=fsc, fill=scorer_fill,
                      stroke_width=scorer_stroke, stroke_fill=PITCH_BOTTOM)

    if not has_score:
        # kick-off card: "VS" divider between the rows
        f = display(64)
        tw = draw.textlength("VS", font=f)
        draw.text(((W - tw) / 2, 808), "VS", font=f, fill=GREEN)
        # nudge rows apart visually by drawing nothing else
    else:
        draw.line([(MARGIN, 850), (W - MARGIN, 850)], fill=(255, 255, 255, 36), width=2)

    _footer(draw, facts.get("date_label", ""))
    return img


def _headline_card(fmt: str, facts: dict) -> Image.Image:
    img, draw = _canvas(texture_seed=sum(ord(c) for c in facts.get("headline", "x")))
    _kicker(draw, fmt)

    headline = (facts.get("headline") or "Football update").upper()
    max_w = W - 2 * MARGIN

    # choose largest display size whose wrapped block fits the body band
    band_top, band_bottom = 420, 1090
    for size in (118, 102, 88, 76, 64, 54):
        fh = display(size)
        lines = _wrap_px(draw, headline, fh, max_w)
        line_h = int(size * 1.18)
        if len(lines) * line_h <= (band_bottom - band_top - 80):
            break
    lines = lines[:8]
    block_h = len(lines) * line_h
    y = band_top + (band_bottom - band_top - block_h) // 2

    # accent tick mark above the headline
    draw.rectangle([MARGIN, y - 36, MARGIN + 110, y - 22], fill=GREEN)

    # the headline card can sit over a stadium texture, so stroke for safety
    for line in lines:
        _display_line(draw, (MARGIN, y), line, fh, WHITE, stroke=2)
        y += line_h

    _footer(draw, facts.get("date_label", ""))
    return img


def _photo_card(fmt: str, facts: dict) -> Image.Image:
    """News card with a licensed Commons photo as the FULL background:
    image fills the entire canvas, brand-green gradient overlays keep the
    chrome and headline legible. Credits go in the caption."""
    photo_file = config.ROOT / facts["photo_path"]
    try:
        photo = Image.open(photo_file).convert("RGB")
    except Exception:  # corrupt file, oversized image, missing path, ...
        return _headline_card(fmt, facts)

    # full-bleed cover crop, biased towards faces (keep the top of frame)
    img = _cover(photo, W, H, top_bias=0.08)

    # subtle brand tint to unify the feed, then top + bottom gradients
    tint = Image.new("RGB", (W, H), _hex(PITCH_BOTTOM))
    img = Image.blend(img, tint, 0.22)

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    dark = _hex(PITCH_BOTTOM)
    for y in range(0, 420):
        od.line([(0, y), (W, y)], fill=(*dark, int(215 * (1 - y / 420))))
    for y in range(620, H):
        a = int(235 * ((y - 620) / (H - 620)) ** 1.4)
        od.line([(0, y), (W, y)], fill=(*dark, a))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(img)
    badge = _logo_white(140)
    if badge is not None:
        img.paste(badge, (56, 56), badge)
        draw = ImageDraw.Draw(img)
    _kicker(draw, fmt)

    # headline over the lower third, where the gradient is strongest
    headline = (facts.get("headline") or "Football update").upper()
    band_top, band_bottom = 840, 1190
    for size in (84, 72, 62, 54, 46):
        fh = display(size)
        lines = _wrap_px(draw, headline, fh, W - 2 * MARGIN)
        line_h = int(size * 1.18)
        if len(lines) * line_h <= (band_bottom - band_top):
            break
    lines = lines[:5]
    block_h = len(lines) * line_h
    y = band_bottom - block_h
    draw.rectangle([MARGIN, y - 32, MARGIN + 110, y - 18], fill=GREEN)
    # full-bleed photo behind the type — stroke every line so it reads on
    # any image, not just where the gradient happens to be strong
    for line in lines:
        _display_line(draw, (MARGIN, y), line, fh, WHITE, stroke=3)
        y += line_h

    _footer(draw, facts.get("date_label", ""))
    return img


def _fixtures(fmt: str, facts: dict) -> Image.Image:
    img, draw = _canvas(texture_seed=len(facts.get("headline", "")) + 1)
    _kicker(draw, fmt)
    _competition(draw, facts.get("headline", "TODAY'S FIXTURES"))

    rows = facts.get("fixture_rows", [])[:7]
    n = max(len(rows), 1)
    row_h = min(150, 620 // n)
    total_h = row_h * n
    y = 470 + (640 - total_h) // 2

    fteam = display(min(58, row_h - 64))
    ftime = meta(44)
    for r in rows:
        line = f"{r.get('home', '?')}  v  {r.get('away', '?')}".upper()
        f = _fit_display(draw, line, W - 2 * MARGIN, fteam.size)
        tw = draw.textlength(line, font=f)
        draw.text(((W - tw) / 2, y), line, font=f, fill=WHITE)
        when = (r.get("time") or "").upper()
        if when:
            tw2 = _tracked_width(draw, when, ftime, 4)
            _tracked(draw, ((W - tw2) / 2, y + f.size + 14), when, ftime, META, 4)
        y += row_h

    _footer(draw, facts.get("date_label", ""))
    return img


# ── stories (9:16 static cards) ─────────────────────────────────────────

def render_story(post_id: int, fmt: str, facts: dict) -> Path | None:
    """1080x1920 story card. Goal/red-card moments get a punchy event layout
    (the high-engagement live content); other match formats reuse the reel
    composition's final frame; headline formats get a centered layout."""
    try:
        if facts.get("fixture_rows"):
            img = _story_fixtures(fmt, facts)
        elif facts.get("event") in ("goal", "red_card") and facts.get("home"):
            img = _story_event(fmt, facts)
        elif facts.get("home"):
            img = _reel_frame(_reel_background(), 1.0, fmt, facts)
        else:
            img = _story_headline(fmt, facts)
        path = config.MEDIA_DIR / f"story_{post_id}.png"
        img.save(path, "PNG", optimize=True)
        log.info("rendered story -> %s", path.name)
        return path
    except Exception as exc:
        log.warning("story render failed: %s", exc)
        return None


def _story_event(fmt: str, facts: dict) -> Image.Image:
    """Goal / red-card moment, 9:16 — the live-commentary hero card: big
    event tag, scorer, minute and the running score."""
    img = _reel_background()
    draw = ImageDraw.Draw(img)
    badge = _logo_white(170)
    if badge is not None:
        img.paste(badge, ((RW - badge.width) // 2, 150), badge)
        draw = ImageDraw.Draw(img)

    red = facts.get("event") == "red_card"
    if red:
        who = facts.get("red_card") or {}
        team = facts.get("red_card_team") or ""
        tag, tag_bg, tag_fg = "RED CARD", "#D33A2C", WHITE
    else:
        who = facts.get("goal_scorer") or {}
        side = who.get("side")
        team = facts.get("home") if side == "home" else (facts.get("away") if side == "away" else "")
        tag = "OWN GOAL" if who.get("og") else ("PENALTY" if who.get("pen") else "GOAL")
        tag_bg, tag_fg = GREEN, PITCH_BOTTOM

    comp = (facts.get("competition") or "").upper()
    if comp:
        fc = meta(48)
        cw = _tracked_width(draw, comp, fc, 10)
        _tracked(draw, ((RW - cw) / 2, 430), comp, fc, META, 10)

    f = label(56)
    tw = _tracked_width(draw, tag, f, 8)
    pad = 50
    x0 = (RW - tw - pad * 2) / 2
    draw.rounded_rectangle([x0, 560, x0 + tw + pad * 2, 672], radius=56, fill=tag_bg)
    _tracked(draw, (x0 + pad, 588), tag, f, tag_fg, 8)

    name = (who.get("name") or "").upper()
    if name:
        fh = _fit_display(draw, name, RW - 150, 130)
        nw = draw.textlength(name, font=fh)
        draw.text(((RW - nw) / 2, 800), name, font=fh, fill=WHITE)

    sub = "  ·  ".join(p for p in [(team or "").upper(), (who.get("minute") or "").upper()] if p)
    if sub:
        fm = meta(56)
        sw = _tracked_width(draw, sub, fm, 6)
        _tracked(draw, ((RW - sw) / 2, 980), sub, fm, META, 6)

    score = f"{facts.get('home_score', 0)} - {facts.get('away_score', 0)}"
    fs = display(150)
    sw = draw.textlength(score, font=fs)
    draw.text(((RW - sw) / 2, 1120), score, font=fs, fill=GREEN_BRIGHT)
    teams = f"{facts.get('home','')}  v  {facts.get('away','')}".upper()
    ft = meta(44)
    tw2 = _tracked_width(draw, teams, ft, 4)
    _tracked(draw, ((RW - tw2) / 2, 1330), teams, ft, WHITE, 4)

    f2 = meta(46)
    cta = "FOLLOW FOR EVERY GOAL"
    cw2 = _tracked_width(draw, cta, f2, 8)
    _tracked(draw, ((RW - cw2) / 2, 1640), cta, f2, GREEN_BRIGHT, 8)
    return img


def _story_fixtures(fmt: str, facts: dict) -> Image.Image:
    img = _reel_background()
    draw = ImageDraw.Draw(img)
    badge = _logo_white(190)
    if badge is not None:
        img.paste(badge, ((RW - badge.width) // 2, 170), badge)
        draw = ImageDraw.Draw(img)

    f = label(40)
    text = fmt.upper()
    tw = _tracked_width(draw, text, f, 8)
    pad, dot_r = 42, 10
    total = tw + pad * 2 + dot_r * 2 + 20
    x0 = (RW - total) / 2
    draw.rounded_rectangle([x0, 430, x0 + total, 522], radius=46, fill=GREEN)
    cy = 476
    draw.ellipse([x0 + pad - dot_r, cy - dot_r, x0 + pad + dot_r, cy + dot_r], fill=PITCH_BOTTOM)
    _tracked(draw, (x0 + pad + dot_r * 2 + 20, 452), text, f, PITCH_BOTTOM, 8)

    title = (facts.get("headline") or "FIXTURES").upper()
    fc = meta(54)
    cw = _tracked_width(draw, title, fc, 10)
    _tracked(draw, ((RW - cw) / 2, 590), title, fc, META, 10)

    rows = facts.get("fixture_rows", [])[:8]
    n = max(len(rows), 1)
    row_h = min(190, 900 // n)
    y = 760 + (900 - row_h * n) // 2
    for r in rows:
        line = f"{r.get('home', '?')}  v  {r.get('away', '?')}".upper()
        font = display(64)
        while draw.textlength(line, font=font) > RW - 160 and font.size > 36:
            font = display(font.size - 4)
        tw = draw.textlength(line, font=font)
        draw.text(((RW - tw) / 2, y), line, font=font, fill=WHITE)
        when = (r.get("time") or "").upper()
        if when:
            ft = meta(48)
            tw2 = _tracked_width(draw, when, ft, 4)
            _tracked(draw, ((RW - tw2) / 2, y + font.size + 16), when, ft, META, 4)
        y += row_h

    fy = RH - 150
    draw.line([(90, fy), (RW - 90, fy)], fill=(255, 255, 255, 38), width=2)
    _tracked(draw, (90, fy + 30), config.BRAND_HANDLE.upper(), meta(52), WHITE, 2)
    return img


def _story_headline(fmt: str, facts: dict) -> Image.Image:
    img = _reel_background()
    draw = ImageDraw.Draw(img)
    badge = _logo_white(190)
    if badge is not None:
        img.paste(badge, ((RW - badge.width) // 2, 190), badge)
        draw = ImageDraw.Draw(img)

    f = label(40)
    text = fmt.upper()
    tw = _tracked_width(draw, text, f, 8)
    pad, dot_r = 42, 10
    total = tw + pad * 2 + dot_r * 2 + 20
    x0 = (RW - total) / 2
    draw.rounded_rectangle([x0, 460, x0 + total, 552], radius=46, fill=GREEN)
    cy = 506
    draw.ellipse([x0 + pad - dot_r, cy - dot_r, x0 + pad + dot_r, cy + dot_r], fill=PITCH_BOTTOM)
    _tracked(draw, (x0 + pad + dot_r * 2 + 20, 482), text, f, PITCH_BOTTOM, 8)

    headline = (facts.get("headline") or "Football update").upper()
    margin = 90
    for size in (104, 90, 78, 66, 56):
        fh = display(size)
        lines = _wrap_px(draw, headline, fh, RW - 2 * margin)
        line_h = int(size * 1.18)
        if len(lines) * line_h <= 760:
            break
    lines = lines[:8]
    block_h = len(lines) * line_h
    y = 700 + (760 - block_h) // 2
    draw.rectangle([margin, y - 36, margin + 120, y - 20], fill=GREEN)
    for line in lines:
        _display_line(draw, (margin, y), line, fh, WHITE, stroke=2)
        y += line_h

    fy = RH - 150
    draw.line([(margin, fy), (RW - margin, fy)], fill=(255, 255, 255, 38), width=2)
    _tracked(draw, (margin, fy + 30), config.BRAND_HANDLE.upper(), meta(52), WHITE, 2)
    return img


def render_news_reel(post_id: int, fmt: str, facts: dict) -> Path | None:
    """Animated news reel: Ken Burns zoom on the story photo (or stadium
    texture) with kicker drop + headline reveal. ~6s, 1080x1920."""
    try:
        import imageio.v2 as imageio
        import numpy as np
    except ImportError:
        return None

    # background source: story photo, else a stadium texture
    src = None
    if facts.get("photo_path"):
        try:
            src = Image.open(config.ROOT / facts["photo_path"]).convert("RGB")
        except Exception:
            src = None
    if src is None:
        backgrounds = sorted(BG_DIR.glob("stadium_*.jpg"))
        if not backgrounds:
            return None
        seed = sum(ord(c) for c in facts.get("headline", "x"))
        src = Image.open(backgrounds[(seed * 2654435761) % len(backgrounds)]).convert("RGB")
        tint = Image.new("RGB", src.size, _hex(PITCH_BOTTOM))
        src = Image.blend(src, tint, 0.45)

    # pre-scale once: cover 1080x1920 with 10% headroom for the zoom
    zoom_max = 1.10
    base = _cover(src, int(RW * zoom_max), int(RH * zoom_max), top_bias=0.15)

    # static overlay: gradients + chrome + headline (alpha-animated in)
    overlay = Image.new("RGBA", (RW, RH), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    dark = _hex(PITCH_BOTTOM)
    for y in range(0, 560):
        od.line([(0, y), (RW, y)], fill=(*dark, int(220 * (1 - y / 560))))
    for y in range(980, RH):
        od.line([(0, y), (RW, y)], fill=(*dark, int(245 * ((y - 980) / (RH - 980)) ** 1.3)))
    badge = _logo_white(170)
    if badge is not None:
        overlay.paste(badge, ((RW - badge.width) // 2, 150), badge)
        od = ImageDraw.Draw(overlay)

    chip = Image.new("RGBA", (RW, RH), (0, 0, 0, 0))
    cd = ImageDraw.Draw(chip)
    f = label(40)
    text = fmt.upper()
    tw = _tracked_width(cd, text, f, 8)
    pad, dot_r = 42, 10
    total = tw + pad * 2 + dot_r * 2 + 20
    x0 = (RW - total) / 2
    cd.rounded_rectangle([x0, 380, x0 + total, 472], radius=46, fill=GREEN)
    cy = 426
    cd.ellipse([x0 + pad - dot_r, cy - dot_r, x0 + pad + dot_r, cy + dot_r], fill=PITCH_BOTTOM)
    _tracked(cd, (x0 + pad + dot_r * 2 + 20, 402), text, f, PITCH_BOTTOM, 8)

    headline = (facts.get("headline") or "").upper()
    text_layer = Image.new("RGBA", (RW, RH), (0, 0, 0, 0))
    td = ImageDraw.Draw(text_layer)
    margin = 90
    for size in (92, 80, 70, 60, 52):
        fh = display(size)
        lines = _wrap_px(td, headline, fh, RW - 2 * margin)
        line_h = int(size * 1.18)
        if len(lines) * line_h <= 620:
            break
    lines = lines[:6]
    y = 1680 - len(lines) * line_h - 90
    td.rectangle([margin, y - 36, margin + 120, y - 20], fill=GREEN)
    for line in lines:
        _display_line(td, (margin, y), line, fh, WHITE, stroke=3)
        y += line_h
    fy = RH - 140
    td.line([(margin, fy), (RW - margin, fy)], fill=(255, 255, 255, 38), width=2)
    _tracked(td, (margin, fy + 26), config.BRAND_HANDLE.upper(), meta(50), WHITE, 2)

    fps, dur = 24, 6.0  # Instagram requires >=23fps for Reels
    frames = int(fps * dur)
    path = config.MEDIA_DIR / f"post_{post_id}.mp4"
    try:
        writer = imageio.get_writer(str(path), fps=fps, codec="libx264", quality=7,
                                    macro_block_size=None, pixelformat="yuv420p")
        try:
            for i in range(frames):
                t = i / (frames - 1)
                z = 1.0 + (zoom_max - 1.0) * t  # slow push-in
                w, h = int(RW * z), int(RH * z)
                left = (base.width - w) // 2
                top = (base.height - h) // 2
                frame = base.crop((left, top, left + w, top + h)).resize((RW, RH), Image.BILINEAR)
                frame = Image.alpha_composite(frame.convert("RGBA"), overlay)
                frame = Image.alpha_composite(frame, _with_alpha(chip, _ease_out(_phase(t, 0.04, 0.22))))
                frame = Image.alpha_composite(frame, _with_alpha(text_layer, _ease_out(_phase(t, 0.18, 0.45))))
                writer.append_data(np.asarray(frame.convert("RGB")))
        finally:
            writer.close()
    except Exception as exc:
        log.warning("news reel failed: %s", exc)
        path.unlink(missing_ok=True)
        return None
    log.info("rendered news reel -> %s", path.name)
    return path


# ── reels (animated score reveal) ───────────────────────────────────────

RW, RH = 1080, 1920  # 9:16 reel canvas
FPS = 24
DURATION = 4.0


def render_reel(post_id: int, fmt: str, facts: dict) -> Path | None:
    """Animated MP4 for Reels: chrome fades in, team rows slide in from
    the sides, the score counts up. Returns None if video deps are
    unavailable (posting then falls back to the static image)."""
    try:
        import imageio.v2 as imageio
    except ImportError:
        log.info("imageio not installed — skipping reel render")
        return None

    base = _reel_background()
    frames = int(DURATION * FPS)
    path = config.MEDIA_DIR / f"post_{post_id}.mp4"
    try:
        writer = imageio.get_writer(
            str(path), fps=FPS, codec="libx264", quality=7,
            macro_block_size=None, pixelformat="yuv420p",
        )
        try:
            import numpy as np
            for i in range(frames):
                frame = _reel_frame(base.copy(), i / (frames - 1), fmt, facts)
                writer.append_data(np.asarray(frame))
        finally:
            writer.close()
    except Exception as exc:  # never block posting on a failed reel
        log.warning("reel render failed: %s", exc)
        path.unlink(missing_ok=True)
        return None
    log.info("rendered reel -> %s", path.name)
    return path


def _ease_out(t: float) -> float:
    return 1 - (1 - max(0.0, min(t, 1.0))) ** 3


def _phase(t: float, start: float, end: float) -> float:
    if t <= start:
        return 0.0
    if t >= end:
        return 1.0
    return (t - start) / (end - start)


def _reel_background() -> Image.Image:
    img = Image.new("RGB", (RW, RH), PITCH_BOTTOM)
    draw = ImageDraw.Draw(img)
    top, bottom = _hex(PITCH_TOP), _hex(PITCH_BOTTOM)
    for y in range(RH):
        t = y / RH
        draw.line([(0, y), (RW, y)],
                  fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    marks = Image.new("RGBA", (RW, RH), (0, 0, 0, 0))
    md = ImageDraw.Draw(marks)
    md.ellipse([RW - 460, -220, RW + 360, 600], outline=LINE, width=3)
    md.ellipse([-300, RH - 500, 340, RH + 140], outline=LINE, width=3)
    return Image.alpha_composite(img.convert("RGBA"), marks).convert("RGB")


def _with_alpha(layer: Image.Image, alpha: float) -> Image.Image:
    if alpha >= 1.0:
        return layer
    faded = layer.copy()
    faded.putalpha(faded.getchannel("A").point(lambda v: int(v * alpha)))
    return faded


def _reel_frame(img: Image.Image, t: float, fmt: str, facts: dict) -> Image.Image:
    rgba = img.convert("RGBA")
    layer = Image.new("RGBA", (RW, RH), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    # chrome fade-in
    a_chrome = _ease_out(_phase(t, 0.0, 0.18))
    badge = _logo_white(190)
    chrome = Image.new("RGBA", (RW, RH), (0, 0, 0, 0))
    cd = ImageDraw.Draw(chrome)
    if badge is not None:
        chrome.paste(badge, ((RW - badge.width) // 2, 170), badge)
    f = label(40)
    text = fmt.upper()
    tw = _tracked_width(cd, text, f, 8)
    pad, dot_r = 42, 10
    total = tw + pad * 2 + dot_r * 2 + 20
    x0 = (RW - total) / 2
    cd.rounded_rectangle([x0, 430, x0 + total, 522], radius=46, fill=GREEN)
    cy = 476
    cd.ellipse([x0 + pad - dot_r, cy - dot_r, x0 + pad + dot_r, cy + dot_r], fill=PITCH_BOTTOM)
    _tracked(cd, (x0 + pad + dot_r * 2 + 20, 452), text, f, PITCH_BOTTOM, 8)
    comp = (facts.get("competition") or "").upper()
    if comp:
        fc = meta(54)
        cw = _tracked_width(cd, comp, fc, 10)
        is_wc = "world cup" in comp.lower()
        icon = 52 if is_wc else 0
        gap = 20 if is_wc else 0
        cx0 = (RW - cw - icon - gap) / 2
        if is_wc:
            _trophy(cd, cx0 + icon / 2, 584, icon, GREEN_BRIGHT)
        _tracked(cd, (cx0 + icon + gap, 580), comp, fc, META, 10)
    rgba = Image.alpha_composite(rgba, _with_alpha(chrome, a_chrome))

    # team rows slide in
    home, away = facts.get("home", "?").upper(), facts.get("away", "?").upper()
    hs, as_ = facts.get("home_score"), facts.get("away_score")
    margin = 90
    name_max = RW - 2 * margin - 240
    size = 120
    for name in (home, away):
        f_try = _fit_display(draw, name, name_max, size)
        size = min(size, f_try.size)
    fname = display(size)
    fscore = display(170)

    slide = _ease_out(_phase(t, 0.22, 0.5))
    rows = Image.new("RGBA", (RW, RH), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rows)
    hx = int(-700 + (margin + 700) * slide)
    ax = int((RW + 700) - (RW + 700 - margin) * slide)
    rd.text((hx, 900), home, font=fname, fill=WHITE)
    rd.text((ax, 1180), away, font=fname, fill=WHITE)
    rd.line([(margin, 1130), (RW - margin, 1130)], fill=(255, 255, 255, int(36 * slide)), width=2)
    rgba = Image.alpha_composite(rgba, _with_alpha(rows, max(slide, 0.01)))

    # score count-up
    if hs is not None:
        reveal = _phase(t, 0.55, 0.8)
        cur_h, cur_a = round(hs * reveal), round(as_ * reveal)
        scores = Image.new("RGBA", (RW, RH), (0, 0, 0, 0))
        sd = ImageDraw.Draw(scores)
        for val, y in ((cur_h, 870), (cur_a, 1150)):
            s = str(val)
            sw = sd.textlength(s, font=fscore)
            sd.text((RW - margin - sw, y), s, font=fscore, fill=GREEN_BRIGHT)
        rgba = Image.alpha_composite(rgba, _with_alpha(scores, _ease_out(_phase(t, 0.5, 0.62))))

    # status pill
    a_pill = _ease_out(_phase(t, 0.8, 0.92))
    if a_pill > 0:
        status = "FULL-TIME" if fmt == "FINAL WHISTLE" else facts.get("status_label", "LIVE")
        pill = Image.new("RGBA", (RW, RH), (0, 0, 0, 0))
        pd_ = ImageDraw.Draw(pill)
        fp = label(38)
        tw = _tracked_width(pd_, status, fp, 6)
        pad = 36
        x0 = (RW - tw - pad * 2) / 2
        pd_.rounded_rectangle([x0, 1430, x0 + tw + pad * 2, 1510], radius=16, outline=GREEN, width=4)
        _tracked(pd_, (x0 + pad, 1448), status, fp, GREEN_BRIGHT, 6)
        rgba = Image.alpha_composite(rgba, _with_alpha(pill, a_pill))

    # footer
    footer = Image.new("RGBA", (RW, RH), (0, 0, 0, 0))
    fd = ImageDraw.Draw(footer)
    fy = RH - 150
    fd.line([(margin, fy), (RW - margin, fy)], fill=(255, 255, 255, 38), width=2)
    _tracked(fd, (margin, fy + 30), config.BRAND_HANDLE.upper(), meta(52), WHITE, 2)
    rgba = Image.alpha_composite(rgba, _with_alpha(footer, a_chrome))

    return rgba.convert("RGB")


def _table(fmt: str, facts: dict) -> Image.Image:
    img, draw = _canvas(texture_seed=2)
    _kicker(draw, fmt)
    _competition(draw, facts.get("headline", "TABLE"))

    rows = facts.get("table_rows", [])[:10]
    card_x0, card_x1 = 60, W - 60
    card_y0 = 460
    row_h = 64
    card_y1 = card_y0 + 70 + row_h * len(rows) + 26
    draw.rounded_rectangle([card_x0, card_y0, card_x1, card_y1], radius=26, fill=CARD)

    fhead = label(26)
    frow = meta(46)
    fpts = label(34)
    # numeric columns right-aligned to fixed edges, well inside the card
    pos_x, team_x = 104, 168
    p_r, gd_r, pts_r = 790, 905, card_x1 - 40

    def rtext(x_right, y_, s, font, fill):
        draw.text((x_right - draw.textlength(s, font=font), y_), s, font=font, fill=fill)

    hy = card_y0 + 26
    draw.text((pos_x, hy), "#", font=fhead, fill="#6E84B0")
    draw.text((team_x, hy), "TEAM", font=fhead, fill="#6E84B0")
    rtext(p_r, hy, "P", fhead, "#6E84B0")
    rtext(gd_r, hy, "GD", fhead, "#6E84B0")
    rtext(pts_r, hy, "PTS", fhead, "#6E84B0")

    advance = facts.get("advance_places", 4)  # CL top-4 by default; WC groups = 2
    y = card_y0 + 70
    for i, r in enumerate(rows):
        if i % 2 == 1:
            draw.rectangle([card_x0 + 14, y - 4, card_x1 - 14, y + row_h - 12], fill="#E6EEF8")
        if r["position"] <= advance:  # qualification/advancement marker
            draw.rectangle([card_x0 + 14, y - 4, card_x0 + 22, y + row_h - 12], fill=GREEN)
        draw.text((pos_x, y), str(r["position"]), font=frow, fill=INK)
        draw.text((team_x, y), str(r["team"])[:22].upper(), font=frow, fill=INK)
        rtext(p_r, y, str(r["played"]), frow, INK)
        rtext(gd_r, y, f'{r["gd"]:+d}', frow, INK)
        rtext(pts_r, y + 6, str(r["points"]), fpts, "#2E5AA0")
        y += row_h

    _footer(draw, facts.get("date_label", ""))
    return img


def _standings_slide(title: str, subtitle: str, group: dict | None) -> Image.Image:
    """A single 9:16 navy slide: cover (group=None) or a group table."""
    img = _reel_background()
    draw = ImageDraw.Draw(img)
    badge = _logo_white(150)
    if badge is not None:
        img.paste(badge, ((RW - badge.width) // 2, 130), badge)
        draw = ImageDraw.Draw(img)

    f = label(46)
    tw = _tracked_width(draw, title, f, 8)
    pad = 48
    x0 = (RW - tw - pad * 2) / 2
    draw.rounded_rectangle([x0, 360, x0 + tw + pad * 2, 462], radius=50, fill=GREEN)
    _tracked(draw, (x0 + pad, 386), title, f, PITCH_BOTTOM, 8)

    if group is None:  # cover
        fh = display(150)
        for text, y in (("GROUP", 760), ("STANDINGS", 920)):
            w = draw.textlength(text, font=fh)
            draw.text(((RW - w) / 2, y), text, font=fh, fill=WHITE)
        fc = meta(50)
        cw = _tracked_width(draw, subtitle, fc, 8)
        _tracked(draw, ((RW - cw) / 2, 1140), subtitle, fc, GREEN_BRIGHT, 8)
        return img

    fg = display(96)
    gw = draw.textlength(group["name"].upper(), font=fg)
    draw.text(((RW - gw) / 2, 560), group["name"].upper(), font=fg, fill=WHITE)

    rows = group["rows"][:4]
    card_x0, card_x1 = 90, RW - 90
    card_y0, row_h = 760, 150
    card_y1 = card_y0 + 90 + row_h * len(rows) + 30
    draw.rounded_rectangle([card_x0, card_y0, card_x1, card_y1], radius=30, fill=CARD)

    fhead, frow, fpts = label(30), meta(60), label(46)
    pos_x, team_x = 150, 240
    p_r, gd_r, pts_r = RW - 430, RW - 280, card_x1 - 60

    def rtext(xr, y_, s, font, fill):
        draw.text((xr - draw.textlength(s, font=font), y_), s, font=font, fill=fill)

    hy = card_y0 + 34
    draw.text((pos_x, hy), "#", font=fhead, fill="#6E84B0")
    draw.text((team_x, hy), "TEAM", font=fhead, fill="#6E84B0")
    rtext(p_r, hy, "P", fhead, "#6E84B0")
    rtext(gd_r, hy, "GD", fhead, "#6E84B0")
    rtext(pts_r, hy, "PTS", fhead, "#6E84B0")

    y = card_y0 + 92
    for i, r in enumerate(rows):
        if i % 2 == 1:
            draw.rectangle([card_x0 + 18, y - 6, card_x1 - 18, y + row_h - 18], fill="#E6EEF8")
        if r["rank"] <= 2:  # top two advance
            draw.rectangle([card_x0 + 18, y - 6, card_x0 + 30, y + row_h - 18], fill=GREEN)
        draw.text((pos_x, y), str(r["rank"]), font=frow, fill=INK)
        draw.text((team_x, y), str(r["team"])[:16].upper(), font=frow, fill=INK)
        gd = r["gd"] if str(r["gd"]).startswith(("+", "-")) else f'+{r["gd"]}'
        rtext(p_r, y, str(r["played"]), frow, INK)
        rtext(gd_r, y, gd, frow, INK)
        rtext(pts_r, y + 8, str(r["points"]), fpts, "#2E5AA0")
        y += row_h

    fcta = meta(46)
    cta = "TOP TWO ADVANCE"
    cw = _tracked_width(draw, cta, fcta, 8)
    _tracked(draw, ((RW - cw) / 2, card_y1 + 70), cta, fcta, GREEN_BRIGHT, 8)
    return img


def render_standings_reel(post_id: int, groups: list[dict], subtitle: str = "THE GROUPS SO FAR") -> Path | None:
    """Animated navy standings reel: cover + one table per group, crossfaded."""
    import imageio.v2 as imageio
    import numpy as np

    slides = [_standings_slide("GROUP STANDINGS", subtitle, None)]
    for grp in groups[:8]:
        slides.append(_standings_slide("WORLD CUP 2026", subtitle, grp))
    arrays = [np.asarray(s.convert("RGB")) for s in slides]

    seg, fade = 2.6, 0.5
    total = seg * len(arrays)
    frames = int(total * FPS)
    fade_n = max(1, int(fade * FPS))
    out = config.MEDIA_DIR / f"post_{post_id}.mp4"
    writer = imageio.get_writer(str(out), fps=FPS, codec="libx264", quality=7,
                                macro_block_size=None, pixelformat="yuv420p")
    try:
        for i in range(frames):
            t = i / FPS
            idx = min(int(t / seg), len(arrays) - 1)
            frame = arrays[idx]
            into = t - idx * seg
            if idx > 0 and into < fade:
                a = into / fade
                frame = (arrays[idx - 1] * (1 - a) + frame * a).astype("uint8")
            writer.append_data(frame)
    finally:
        writer.close()
    log.info("rendered standings reel -> %s (%.1fs)", out.name, total)
    return out
