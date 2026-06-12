"""Voiced match recap reels: ~30s podcast-style narrated summary published
a few minutes after full-time. Slides (intro → one per goal → FT outro)
are timed to the narration audio and crossfaded."""

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from .. import config, db
from ..logger import get_logger
from . import graphics as g
from . import voice

log = get_logger("recap")

FPS = 24  # Instagram requires >=23fps for Reels
FADE = 0.45  # seconds of crossfade between slides


def _audio_duration(path: Path) -> float:
    """Exact duration via ffmpeg decode to wav."""
    import imageio_ffmpeg
    import wave

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    wav = path.with_suffix(".wav")
    subprocess.run([ffmpeg, "-y", "-i", str(path), "-ar", "24000", "-ac", "1", str(wav)],
                   capture_output=True, check=True)
    with wave.open(str(wav)) as w:
        dur = w.getnframes() / w.getframerate()
    wav.unlink(missing_ok=True)
    return dur


def _slide_intro(facts: dict) -> Image.Image:
    img = g._reel_background()
    draw = ImageDraw.Draw(img)
    badge = g._logo_white(200)
    if badge is not None:
        img.paste(badge, ((g.RW - badge.width) // 2, 280), badge)
        draw = ImageDraw.Draw(img)
    f = g.label(44)
    text = "MATCH RECAP"
    tw = g._tracked_width(draw, text, f, 8)
    pad = 46
    x0 = (g.RW - tw - pad * 2) / 2
    draw.rounded_rectangle([x0, 600, x0 + tw + pad * 2, 700], radius=50, fill=g.GREEN)
    g._tracked(draw, (x0 + pad, 624), text, f, g.PITCH_BOTTOM, 8)

    teams = f"{facts.get('home','')}  v  {facts.get('away','')}".upper()
    fh = g._fit_display(draw, teams, g.RW - 160, 84)
    tw = draw.textlength(teams, font=fh)
    draw.text(((g.RW - tw) / 2, 860), teams, font=fh, fill=g.WHITE)
    comp = (facts.get("competition") or "").upper()
    if comp:
        fc = g.meta(52)
        cw = g._tracked_width(draw, comp, fc, 10)
        g._tracked(draw, ((g.RW - cw) / 2, 1010), comp, fc, g.META, 10)
    return img


def _slide_goal(facts: dict, scorer: dict, running: tuple[int, int]) -> Image.Image:
    img = g._reel_background()
    draw = ImageDraw.Draw(img)
    team = facts.get("home") if scorer.get("side") == "home" else facts.get("away")

    f = g.label(40)
    tag = "OWN GOAL" if scorer.get("og") else ("PENALTY" if scorer.get("pen") else "GOAL")
    tw = g._tracked_width(draw, tag, f, 8)
    pad = 42
    x0 = (g.RW - tw - pad * 2) / 2
    draw.rounded_rectangle([x0, 480, x0 + tw + pad * 2, 572], radius=46, fill=g.GREEN)
    g._tracked(draw, (x0 + pad, 504), tag, f, g.PITCH_BOTTOM, 8)

    name = (scorer.get("name") or "").upper()
    fh = g._fit_display(draw, name, g.RW - 180, 120)
    tw = draw.textlength(name, font=fh)
    draw.text(((g.RW - tw) / 2, 720), name, font=fh, fill=g.WHITE)

    minute = (scorer.get("minute") or "").upper()
    sub = f"{team}  ·  {minute}".upper()
    fm = g.meta(56)
    sw = g._tracked_width(draw, sub, fm, 6)
    g._tracked(draw, ((g.RW - sw) / 2, 900), sub, fm, g.META, 6)

    score = f"{running[0]} - {running[1]}"
    fs = g.display(170)
    sw = draw.textlength(score, font=fs)
    draw.text(((g.RW - sw) / 2, 1050), score, font=fs, fill=g.GREEN_BRIGHT)
    return img


def _slide_outro(facts: dict) -> Image.Image:
    img = g._reel_frame(g._reel_background(), 1.0, "FINAL WHISTLE", facts)
    draw = ImageDraw.Draw(img)
    f = g.meta(48)
    cta = "FOLLOW FOR EVERY GOAL"
    tw = g._tracked_width(draw, cta, f, 8)
    g._tracked(draw, ((g.RW - tw) / 2, 1600), cta, f, g.GREEN_BRIGHT, 8)
    return img


def render_recap(post_id: int, facts: dict, script: str) -> Path | None:
    """TTS + slides + mux. Returns the mp4 path or None."""
    import imageio.v2 as imageio
    import imageio_ffmpeg
    import numpy as np

    audio = config.MEDIA_DIR / f"recap_{post_id}.mp3"
    if not voice.tts(script, audio):
        log.warning("recap: no voice available")
        return None
    duration = _audio_duration(audio) + 0.6  # small tail

    # slides: intro, one per goal, outro
    scorers = [s for s in (facts.get("scorers") or []) if s.get("name")]
    slides = [_slide_intro(facts)]
    h = a = 0
    for sc in scorers[:4]:
        if sc.get("side") == "home":
            h += 1
        else:
            a += 1
        slides.append(_slide_goal(facts, sc, (h, a)))
    slides.append(_slide_outro(facts))
    arrays = [np.asarray(s.convert("RGB")) for s in slides]

    seg = duration / len(arrays)
    total_frames = int(duration * FPS)
    fade_frames = max(1, int(FADE * FPS))

    silent = config.MEDIA_DIR / f"recap_{post_id}_silent.mp4"
    writer = imageio.get_writer(str(silent), fps=FPS, codec="libx264", quality=7,
                                macro_block_size=None, pixelformat="yuv420p")
    try:
        for i in range(total_frames):
            t = i / FPS
            idx = min(int(t / seg), len(arrays) - 1)
            frame = arrays[idx]
            into = t - idx * seg
            if idx > 0 and into < FADE:  # crossfade from previous slide
                alpha = into / FADE
                frame = (arrays[idx - 1] * (1 - alpha) + frame * alpha).astype("uint8")
            writer.append_data(frame)
    finally:
        writer.close()

    out = config.MEDIA_DIR / f"post_{post_id}.mp4"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.run(
        [ffmpeg, "-y", "-i", str(silent), "-i", str(audio),
         "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", str(out)],
        capture_output=True,
    )
    silent.unlink(missing_ok=True)
    audio.unlink(missing_ok=True)
    if proc.returncode != 0 or not out.exists():
        db.log_error("recap", f"mux failed: {proc.stderr[-200:]}")
        return None
    log.info("rendered voiced recap -> %s (%.1fs)", out.name, duration)
    return out


def queue_recap(facts: dict, sources: list) -> None:
    """Create the recap post a few minutes after full-time (autonomous
    path — narration text comes from the fact-grounded template)."""
    headline = f"RECAP: {facts.get('home')} {facts.get('home_score')}-{facts.get('away_score')} {facts.get('away')}"
    script = voice.build_recap_script(facts)
    from . import captions

    caption, alt = captions.build_caption("FINAL WHISTLE", facts, 11)
    caption = caption.replace("FT:", "🎙️ MATCH RECAP —", 1)
    post_id = db.enqueue_post(
        fmt="FINAL WHISTLE", headline=headline, caption=caption, hashtags="",
        alt_text=f"Voiced match recap video: {headline}", confidence=1.0,
        sources=sources, facts=facts, delay_minutes=4,
    )
    if post_id is None:
        return
    path = g.render(post_id, "FINAL WHISTLE", facts)  # thumbnail/fallback image
    db.update_post(post_id, image_path=str(path.relative_to(config.ROOT)))
    render_recap(post_id, facts, script)
    log.info("QUEUED recap #%d", post_id)
