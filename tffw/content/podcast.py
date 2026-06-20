"""Podcast-style reels: a two-presenter voiced clip over a full-bleed subject
photo, with big karaoke-style subtitles synced to the speech.

Voices: a "mixed duo" — a British host and an American host — using free
Microsoft neural voices (multi-speaker). When a PAID ElevenLabs key is present
the same dialogue is voiced with ElevenLabs instead (see voice.py).

Used for recaps, news and full-time results. Live match moments stay as
instant Stories (speed matters there).
"""

import asyncio
import json
import ssl
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from .. import config, db
from ..logger import get_logger
from . import graphics as g

log = get_logger("podcast")

FPS = 24
# mixed duo: host A British, host B American
VOICE_A = "en-GB-RyanNeural"
VOICE_B = "en-US-AriaNeural"


# ── dialogue script ──────────────────────────────────────────────────────

def build_dialogue(facts: dict) -> list[tuple[int, str]]:
    """A short two-host exchange (speaker 0 = British, 1 = American) grounded
    strictly in the verified facts. Claude writes it when a key is present;
    otherwise a deterministic template does."""
    if config.ANTHROPIC_API_KEY:
        lines = _claude_dialogue(facts)
        if lines:
            return lines
    return _template_dialogue(facts)


def _claude_dialogue(facts: dict) -> list[tuple[int, str]]:
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        sys_prompt = (
            "You write a punchy ~20-second two-host football podcast exchange for "
            f"{config.BRAND_NAME}. HOST_A is British (play-by-play), HOST_B is American "
            "(analyst). 6-8 short spoken lines, alternating, natural banter, building on "
            "each other. Use ONLY the supplied facts — invent no names, scores, quotes or "
            "stats. End on a quick question to the viewer. Output STRICT JSON: a list of "
            '{"host":"A"|"B","line":"..."} objects and nothing else.'
        )
        resp = client.messages.create(
            model=config.CLAUDE_MODEL, max_tokens=700, system=sys_prompt,
            messages=[{"role": "user", "content":
                       f"Facts (use nothing else):\n{json.dumps(facts, indent=2)}"}],
        )
        if resp.stop_reason == "refusal":
            return []
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        text = text[text.find("["): text.rfind("]") + 1]
        data = json.loads(text)
        out = [(0 if d.get("host", "A").upper() == "A" else 1, d["line"].strip())
               for d in data if d.get("line")]
        return out[:8] or []
    except Exception as exc:
        db.log_error("podcast", f"claude dialogue: {exc}")
        return []


def _template_dialogue(facts: dict) -> list[tuple[int, str]]:
    headline = (facts.get("headline") or "").rstrip(".")
    summary = (facts.get("story_summary") or "").strip()
    sents = [s.strip() for s in summary.replace("\n", " ").split(". ") if len(s.strip()) > 12][:2]
    lines = [(0, f"Big one for you here — {headline}.")]
    if sents:
        lines.append((1, f"Yeah, and here's why it matters. {sents[0]}."))
    if len(sents) > 1:
        lines.append((0, f"{sents[1]}."))
    lines.append((1, "Could be a real talking point this tournament."))
    lines.append((0, "What do you make of it? Let us know below."))
    return lines


# ── multi-voice synthesis with word timing ───────────────────────────────

def _ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


async def _synth_line(text: str, voice: str) -> bytes:
    import edge_tts.communicate as ec
    ec._SSL_CTX = _ssl_ctx()
    import edge_tts

    comm = edge_tts.Communicate(text, voice=voice, rate="+4%")
    audio = bytearray()
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            audio += chunk["data"]
    return bytes(audio)


def _chunk_text(line: str, n: int) -> list[str]:
    """Split a spoken line into caption chunks of ~n words."""
    words = line.split()
    return [" ".join(words[i:i + n]) for i in range(0, len(words), n)] or [line]


def _duration(path: Path) -> float:
    import imageio_ffmpeg
    import wave
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    wav = path.with_suffix(".probe.wav")
    subprocess.run([ffmpeg, "-y", "-i", str(path), "-ar", "24000", "-ac", "1", str(wav)],
                   capture_output=True, check=True)
    with wave.open(str(wav)) as w:
        d = w.getnframes() / w.getframerate()
    wav.unlink(missing_ok=True)
    return d


def synth_dialogue(post_id: int, lines: list[tuple[int, str]]) -> tuple[Path | None, list[dict]]:
    """Synthesize each line with its host's voice, concatenate, and return the
    combined audio path plus subtitle segments [{text,start,end,host}] timed to
    the speech (a few words per caption chunk)."""
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    tmp = config.MEDIA_DIR / f"_pod_{post_id}"
    tmp.mkdir(exist_ok=True)
    parts, segments, t0 = [], [], 0.0
    try:
        for i, (host, line) in enumerate(lines):
            voice = VOICE_A if host == 0 else VOICE_B
            audio = asyncio.run(_synth_line(line, voice))
            if len(audio) < 800:
                continue
            part = tmp / f"{i}.mp3"
            part.write_bytes(audio)
            dur = _duration(part)
            parts.append(part)
            # split into ~5-word caption chunks; distribute this line's measured
            # duration across them by length (robust without word-boundary data)
            chunks = _chunk_text(line, 5)
            tot = sum(len(c) for c in chunks) or 1
            ct = t0
            for c in chunks:
                seg_dur = dur * len(c) / tot
                segments.append({"text": c, "host": host, "start": ct, "end": ct + seg_dur})
                ct += seg_dur
            t0 += dur
        if not parts:
            return None, []
        listfile = tmp / "list.txt"
        listfile.write_text("".join(f"file '{p.name}'\n" for p in parts))
        out = config.MEDIA_DIR / f"podaudio_{post_id}.mp3"
        subprocess.run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
                        "-c:a", "libmp3lame", "-q:a", "3", str(out)],
                       cwd=str(tmp), capture_output=True, check=True)
        return out, segments
    except Exception as exc:
        db.log_error("podcast", f"synth: {exc}")
        return None, []
    finally:
        for p in tmp.glob("*"):
            p.unlink(missing_ok=True)
        tmp.rmdir()


# ── render ───────────────────────────────────────────────────────────────

def _background(facts: dict) -> Image.Image:
    """Full-bleed subject photo (or stadium) with dark scrims for legibility."""
    src = None
    if facts.get("photo_path"):
        try:
            src = Image.open(config.ROOT / facts["photo_path"]).convert("RGB")
        except Exception:
            src = None
    if src is None:
        bgs = sorted(g.BG_DIR.glob("stadium_*.jpg"))
        src = Image.open(bgs[0]).convert("RGB") if bgs else Image.new("RGB", (g.RW, g.RH), g._hex(g.PITCH_BOTTOM))
    return src


def _subtitle_layer(text: str, host: int) -> Image.Image:
    """A caption block: big bold white words on a subtle scrim, lower-third."""
    layer = Image.new("RGBA", (g.RW, g.RH), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    margin = 90
    for size in (96, 86, 76, 66):
        f = g.label(size)
        lines = g._wrap_px(d, text.upper(), f, g.RW - 2 * margin)
        line_h = int(size * 1.2)
        if len(lines) * line_h <= 520 and len(lines) <= 3:
            break
    block_h = len(lines) * line_h
    y0 = 1150
    # scrim
    sc = Image.new("RGBA", (g.RW, g.RH), (0, 0, 0, 0))
    ImageDraw.Draw(sc).rectangle([0, y0 - 60, g.RW, y0 + block_h + 50], fill=(*g._hex(g.PITCH_BOTTOM), 150))
    layer = Image.alpha_composite(layer, sc.filter(__import__("PIL.ImageFilter", fromlist=["GaussianBlur"]).GaussianBlur(30)))
    d = ImageDraw.Draw(layer)
    # accent tab in host colour
    accent = g.GREEN if host == 0 else g.GREEN_BRIGHT
    y = y0
    for ln in lines:
        w = d.textlength(ln, font=f)
        x = (g.RW - w) / 2
        for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3)):  # outline for pop
            d.text((x + dx, y + dy), ln, font=f, fill=g._hex(g.PITCH_BOTTOM))
        d.text((x, y), ln, font=f, fill=g.WHITE)
        y += line_h
    d.rectangle([(g.RW - 90) / 2, y0 - 36, (g.RW + 90) / 2, y0 - 22], fill=accent)
    return layer


def render_podcast_reel(post_id: int, facts: dict, fmt: str = "BREAKING") -> Path | None:
    """Two-host podcast reel: Ken Burns subject photo + synced subtitles +
    voiced dialogue. Returns the mp4 path (post_{id}.mp4) or None."""
    import imageio.v2 as imageio
    import imageio_ffmpeg
    import numpy as np

    lines = build_dialogue(facts)
    if not lines:
        return None
    audio, segments = synth_dialogue(post_id, lines)
    if audio is None or not segments:
        log.warning("podcast: no audio")
        return None
    total = segments[-1]["end"] + 0.6

    # Ken Burns base + static chrome (logo, top/bottom scrims)
    zoom_max = 1.12
    base = g._cover(_background(facts), int(g.RW * zoom_max), int(g.RH * zoom_max), top_bias=0.12)
    chrome = Image.new("RGBA", (g.RW, g.RH), (0, 0, 0, 0))
    cd = ImageDraw.Draw(chrome)
    dark = g._hex(g.PITCH_BOTTOM)
    for y in range(0, 460):
        cd.line([(0, y), (g.RW, y)], fill=(*dark, int(200 * (1 - y / 460))))
    for y in range(1620, g.RH):
        cd.line([(0, y), (g.RW, y)], fill=(*dark, int(150 * ((y - 1620) / (g.RH - 1620)))))
    badge = g._logo_white(150)
    if badge is not None:
        chrome.paste(badge, ((g.RW - badge.width) // 2, 120), badge)

    # pre-render one subtitle layer per segment (cheap reuse across frames)
    seg_layers = [_subtitle_layer(s["text"], s["host"]) for s in segments]

    frames = int(total * FPS)
    silent = config.MEDIA_DIR / f"_pod_silent_{post_id}.mp4"
    writer = imageio.get_writer(str(silent), fps=FPS, codec="libx264", quality=7,
                                macro_block_size=None, pixelformat="yuv420p")
    try:
        for i in range(frames):
            t = i / FPS
            z = 1.0 + (zoom_max - 1.0) * (t / total)
            w, h = int(g.RW * z), int(g.RH * z)
            left, top = (base.width - w) // 2, (base.height - h) // 2
            frame = base.crop((left, top, left + w, top + h)).resize((g.RW, g.RH), Image.BILINEAR)
            frame = Image.alpha_composite(frame.convert("RGBA"), chrome)
            for s, layer in zip(segments, seg_layers):
                if s["start"] <= t < s["end"]:
                    frame = Image.alpha_composite(frame, layer)
                    break
            writer.append_data(np.asarray(frame.convert("RGB")))
    finally:
        writer.close()

    out = config.MEDIA_DIR / f"post_{post_id}.mp4"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.run([ffmpeg, "-y", "-i", str(silent), "-i", str(audio),
                           "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", str(out)],
                          capture_output=True)
    silent.unlink(missing_ok=True)
    audio.unlink(missing_ok=True)
    if proc.returncode != 0 or not out.exists():
        db.log_error("podcast", f"mux failed: {proc.stderr[-200:]}")
        return None
    log.info("rendered podcast reel -> %s (%.1fs, %d lines)", out.name, total, len(lines))
    return out
