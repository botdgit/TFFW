"""Branded graphic rendering with Pillow.

Design system ("Final Whistle" brand):
  • Palette from the club logo: brand green #73B633 on a deep pitch-green
    gradient, white type, muted green-grey for meta text.
  • Type: Anton (condensed display, headlines/scores), Archivo Black
    (kickers/labels), Barlow Condensed (meta/supporting).
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
GREEN = "#73B633"        # logo green
GREEN_BRIGHT = "#8FD146"
PITCH_TOP = "#0C3A17"    # background gradient
PITCH_BOTTOM = "#04150A"
WHITE = "#FFFFFF"
META = "#8FBF6B"         # muted green for meta text
LINE = (255, 255, 255, 22)  # faint pitch markings
INK = "#0B2310"          # dark text on light surfaces
CARD = "#F4F9EF"         # light surface

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
    card has imagery (heavy brand-green duotone keeps text legible)."""
    backgrounds = sorted(BG_DIR.glob("stadium_*.jpg"))
    if not backgrounds:
        return img
    try:
        photo = Image.open(backgrounds[seed % len(backgrounds)]).convert("L")
    except OSError:
        return img
    photo = _cover(photo.convert("RGB"), W, H)
    # duotone: map luminance into the pitch palette, then blend subtly
    photo = photo.convert("L")
    lo, hi = _hex(PITCH_BOTTOM), _hex("#2E6B3A")
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
    gd.ellipse([W // 2 - 520, 330, W // 2 + 520, 1180], fill=(115, 182, 51, 26))
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

    # logo badge, top centre
    badge = _logo_white(150)
    if badge is not None:
        img.paste(badge, ((W - badge.width) // 2, 56), badge)

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


def _kicker(draw: ImageDraw.ImageDraw, fmt: str, y: int = 252) -> None:
    """Centered format chip: ● FORMAT NAME on a green pill."""
    f = label(34)
    text = fmt.upper()
    tw = _tracked_width(draw, text, f, 8)
    pad, dot_r = 38, 9
    total = tw + pad * 2 + dot_r * 2 + 18
    x0 = (W - total) / 2
    draw.rounded_rectangle([x0, y, x0 + total, y + 78], radius=39, fill=GREEN)
    cy = y + 39
    draw.ellipse([x0 + pad - dot_r, cy - dot_r, x0 + pad + dot_r, cy + dot_r], fill=PITCH_BOTTOM)
    _tracked(draw, (x0 + pad + dot_r * 2 + 18, y + 17), text, f, PITCH_BOTTOM, 8)


def _footer(draw: ImageDraw.ImageDraw, sub: str = "") -> None:
    y = H - 118
    draw.line([(MARGIN, y), (W - MARGIN, y)], fill=(255, 255, 255, 38), width=2)
    f = meta(44)
    _tracked(draw, (MARGIN, y + 28), config.BRAND_HANDLE.upper(), f, WHITE, 2)
    if sub:
        fr = meta_light(42)
        tw = _tracked_width(draw, sub.upper(), fr, 4)
        _tracked(draw, (W - MARGIN - tw, y + 30), sub.upper(), fr, META, 4)


def _competition(draw: ImageDraw.ImageDraw, text: str, y: int = 372) -> None:
    if not text:
        return
    f = meta(46)
    t = text.upper()
    tw = _tracked_width(draw, t, f, 10)
    _tracked(draw, ((W - tw) / 2, y), t, f, META, 10)


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

def _flag_band(img: Image.Image, team: str, y0: int, y1: int) -> Image.Image:
    """Paste a darkened national flag behind a team row (no-op for clubs)."""
    from . import flags

    path = flags.flag_path(team)
    if path is None:
        return img
    try:
        flag = Image.open(path).convert("RGB")
    except OSError:
        return img
    band = _cover(flag, W, y1 - y0).filter(ImageFilter.GaussianBlur(2))
    overlay = Image.new("RGBA", (W, y1 - y0), (*_hex(PITCH_BOTTOM), 195))
    band = Image.alpha_composite(band.convert("RGBA"), overlay).convert("RGB")
    img.paste(band, (0, y0))
    return img


def _scoreboard(fmt: str, facts: dict) -> Image.Image:
    img, draw = _canvas()

    home, away = facts.get("home", "?"), facts.get("away", "?")
    # national-team matches get flag panels behind the team rows
    img = _flag_band(img, facts.get("home_full", home), 560, 850)
    img = _flag_band(img, facts.get("away_full", away), 852, 1142)
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

    for name, score, y in rows:
        ny = y + (150 - size) // 2 + 10
        draw.text((MARGIN, ny), name.upper(), font=fname, fill=WHITE)
        if has_score:
            s = str(score)
            sw = draw.textlength(s, font=fscore)
            draw.text((score_x - sw, y), s, font=fscore, fill=GREEN_BRIGHT)

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
    img, draw = _canvas(texture_seed=len(facts.get("headline", "")))
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

    # green tick mark above the headline
    draw.rectangle([MARGIN, y - 36, MARGIN + 110, y - 22], fill=GREEN)

    for line in lines:
        draw.text((MARGIN, y), line, font=fh, fill=WHITE)
        y += line_h

    _footer(draw, facts.get("date_label", ""))
    return img


def _photo_card(fmt: str, facts: dict) -> Image.Image:
    """News card with a licensed Commons photo: image fills the upper
    two-thirds, blends into the pitch gradient, headline below, license
    attribution rendered on-card (license requirement)."""
    img, _ = _canvas()
    photo_file = config.ROOT / facts["photo_path"]
    try:
        photo = Image.open(photo_file).convert("RGB")
    except Exception:  # corrupt file, oversized image, missing path, ...
        return _headline_card(fmt, facts)

    # cover-crop to 1080 x 720
    target_w, target_h = W, 720
    scale = max(target_w / photo.width, target_h / photo.height)
    photo = photo.resize((int(photo.width * scale) + 1, int(photo.height * scale) + 1), Image.LANCZOS)
    left = (photo.width - target_w) // 2
    top = max((photo.height - target_h) // 3, 0)  # bias crop towards faces
    photo = photo.crop((left, top, left + target_w, top + target_h))

    img.paste(photo, (0, 0))

    # gradient overlays: darken the top (chrome legibility) and dissolve
    # the bottom of the photo into the pitch background
    overlay = Image.new("RGBA", (W, target_h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for y in range(300):
        od.line([(0, y), (W, y)], fill=(4, 21, 10, int(190 * (1 - y / 300))))
    bottom = _hex(PITCH_TOP)
    for y in range(400, target_h):
        a = int(255 * ((y - 400) / (target_h - 400)) ** 1.1)
        od.line([(0, y), (W, y)], fill=(*bottom, a))
    img.paste(Image.alpha_composite(img.convert("RGBA").crop((0, 0, W, target_h)), overlay).convert("RGB"), (0, 0))

    draw = ImageDraw.Draw(img)
    badge = _logo_white(150)
    if badge is not None:
        img.paste(badge, ((W - badge.width) // 2, 56), badge)
        draw = ImageDraw.Draw(img)
    _kicker(draw, fmt)

    # headline sits fully below the photo, on the solid gradient — never
    # over the photo's subject. Sources/credits go in the caption instead.
    headline = (facts.get("headline") or "Football update").upper()
    band_top, band_bottom = 790, 1180
    for size in (86, 74, 64, 56, 48):
        fh = display(size)
        lines = _wrap_px(draw, headline, fh, W - 2 * MARGIN)
        line_h = int(size * 1.18)
        if len(lines) * line_h <= (band_bottom - band_top):
            break
    lines = lines[:6]
    block_h = len(lines) * line_h
    y = band_top + (band_bottom - band_top - block_h) // 2
    draw.rectangle([MARGIN, y - 32, MARGIN + 110, y - 18], fill=GREEN)
    for line in lines:
        draw.text((MARGIN, y), line, font=fh, fill=WHITE)
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
    """1080x1920 story card. Match formats reuse the reel composition's
    final frame; headline formats get a centered story layout."""
    try:
        if facts.get("home"):
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
        draw.text((margin, y), line, font=fh, fill=WHITE)
        y += line_h

    fy = RH - 150
    draw.line([(margin, fy), (RW - margin, fy)], fill=(255, 255, 255, 38), width=2)
    _tracked(draw, (margin, fy + 30), config.BRAND_HANDLE.upper(), meta(52), WHITE, 2)
    return img


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
        _tracked(cd, ((RW - cw) / 2, 580), comp, fc, META, 10)
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
    draw.text((pos_x, hy), "#", font=fhead, fill="#5E7A52")
    draw.text((team_x, hy), "TEAM", font=fhead, fill="#5E7A52")
    rtext(p_r, hy, "P", fhead, "#5E7A52")
    rtext(gd_r, hy, "GD", fhead, "#5E7A52")
    rtext(pts_r, hy, "PTS", fhead, "#5E7A52")

    y = card_y0 + 70
    for i, r in enumerate(rows):
        if i % 2 == 1:
            draw.rectangle([card_x0 + 14, y - 4, card_x1 - 14, y + row_h - 12], fill="#E8F2DF")
        if r["position"] <= 4:  # CL places marker
            draw.rectangle([card_x0 + 14, y - 4, card_x0 + 22, y + row_h - 12], fill=GREEN)
        draw.text((pos_x, y), str(r["position"]), font=frow, fill=INK)
        draw.text((team_x, y), str(r["team"])[:22].upper(), font=frow, fill=INK)
        rtext(p_r, y, str(r["played"]), frow, INK)
        rtext(gd_r, y, f'{r["gd"]:+d}', frow, INK)
        rtext(pts_r, y + 6, str(r["points"]), fpts, "#3E7A1E")
        y += row_h

    _footer(draw, facts.get("date_label", ""))
    return img
