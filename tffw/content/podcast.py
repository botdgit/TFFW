"""Podcast-style reels: a two-presenter voiced clip over 2-3 full-bleed subject
photos, opening with a big clickbait hook and big karaoke-style subtitles
synced to the speech.

Voices: two women, mixed accents (British + American) on free Microsoft neural
voices. When a PAID ElevenLabs key is present the same dialogue is voiced with
ElevenLabs instead (see voice.py).

Used for recaps, news and full-time results. Live match moments stay as
instant Stories (speed matters there).
"""

import asyncio
import json
import re
import ssl
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from .. import config, db
from ..logger import get_logger
from . import graphics as g
from ..sources import commons

log = get_logger("podcast")

FPS = 24
# two women — Microsoft's most natural, conversational neural voices.
# A = British (Sonia), B = American (Ava, very natural). Override via env.
import os
VOICE_A = os.environ.get("POD_VOICE_A", "en-GB-SoniaNeural")
VOICE_B = os.environ.get("POD_VOICE_B", "en-US-AvaNeural")


# ── dialogue script ──────────────────────────────────────────────────────

def build_dialogue(facts: dict) -> list[tuple[int, str]]:
    """Returns spoken lines (speaker 0 = British woman, 1 = American woman).
    The FIRST line is a short clickbait hook (the main message, shown big at
    the start), then a two-host exchange. Grounded strictly in the facts."""
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
            "You script a punchy ~20-second two-host football podcast reel for "
            f"{config.BRAND_NAME}. Two women host it: HOST_A British, HOST_B American — "
            "they're funny, quick and a bit cheeky, like two mates who live and breathe "
            "football. Witty banter, a playful jab or dry one-liner is great. "
            "The FIRST line MUST be a short, scroll-stopping clickbait HOOK (4-9 words, "
            "host A) — the single most striking fact stated boldly (shows BIG on screen). "
            "Then 5-7 short alternating lines with real personality, building on each "
            "other, ending on a cheeky question to the viewer. Humour is welcome but the "
            "FACTS must stay true: use ONLY the supplied facts — invent no names, scores, "
            "quotes or stats, and jokes must not imply anything untrue. Output STRICT "
            'JSON: a list of {"host":"A"|"B","line":"..."} objects and nothing else.'
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
    """Witty two-host banter without an LLM — grounded in the facts. Match
    recaps get a result-aware exchange; news gets a reaction exchange. A bit
    of personality and light humour; a small hash picks line variants so it
    doesn't feel copy-pasted."""
    import hashlib
    pick = lambda opts, salt="": opts[int(hashlib.sha256(
        ((facts.get("headline", "")) + salt).encode()).hexdigest(), 16) % len(opts)]

    home, away = facts.get("home"), facts.get("away")
    if home and facts.get("home_score") is not None:  # ── match recap ──
        hs, as_ = facts.get("home_score"), facts.get("away_score")
        scs = [s for s in (facts.get("scorers") or []) if s.get("name")]
        if hs == as_:
            hook = f"{home} {hs}, {away} {as_} — honours even."
            react = pick(["Spoils shared, and nobody's happy in the changing room.",
                          "A draw that flatters one of them, doesn't it?"])
        else:
            win, lose = (home, away) if hs > as_ else (away, home)
            hook = f"{win} get the job done against {lose}."
            react = pick([f"{lose} will not want to watch that one back.",
                          f"Job done for {win} — {lose} have some thinking to do."], "r")
        lines = [(0, hook), (1, react)]
        if scs:
            sc = scs[0]; nm = re.sub(r"^[A-Z]\.\s*", "", sc["name"])
            team = home if sc.get("side") == "home" else away
            lines.append((0, pick([f"{nm} with the goal for {team} — take a bow.",
                                   f"{nm} pops up for {team}. Of course he does."], "g")))
        if len(scs) > 1:
            sc2 = scs[-1]; nm2 = re.sub(r"^[A-Z]\.\s*", "", sc2["name"])
            lines.append((1, f"And {nm2} got in on the act too. Goals everywhere."))
        else:
            lines.append((1, pick(["One goal the difference, but it felt bigger.",
                                   "Tight margins — that's tournament football."], "m")))
        lines.append((0, pick(["Fair result? Tell us below 👇",
                               "Where does this leave the group? Go on, have your say."], "q")))
        return lines

    # ── news / reaction ──
    headline = (facts.get("headline") or "").rstrip(".")
    summary = (facts.get("story_summary") or "").strip()
    sents = [s.strip() for s in summary.replace("\n", " ").split(". ") if len(s.strip()) > 12][:2]
    lines = [(0, f"{headline}.")]
    lines.append((1, pick(["Right, stop scrolling — this one's a proper talking point.",
                           "Okay, did NOT see that one coming.",
                           "Well, that's certainly woken the group chat up."], "n1")))
    if sents:
        lines.append((0, f"{sents[0]}."))
    if len(sents) > 1:
        lines.append((1, f"{sents[1]}."))
    lines.append((0, pick(["Bold move. Could be genius, could be chaos.",
                           "Football, eh? Never a dull moment.",
                           "You couldn't make it up."], "n2")))
    lines.append((1, pick(["What's your verdict? Comments are open 👇",
                           "Smart or madness? Let us know below."], "nq")))
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
            chunks = _chunk_text(line, 4 if i == 0 else 5)
            tot = sum(len(c) for c in chunks) or 1
            ct = t0
            for c in chunks:
                seg_dur = dur * len(c) / tot
                segments.append({"text": c, "host": host, "start": ct, "end": ct + seg_dur,
                                 "hook": i == 0})  # first line is the clickbait hook
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

def _gather_photos(post_id: int, facts: dict) -> list[Image.Image]:
    """2-3 distinct licensed photos for the story: the subject photo plus extra
    subject/team queries, topped up with rotating stadium imagery so the reel
    always has visual variety throughout."""
    imgs, seen = [], set()

    def add(path: Path | str) -> None:
        p = config.ROOT / path if not str(path).startswith("/") else Path(path)
        try:
            imgs.append(Image.open(p).convert("RGB"))
        except Exception:
            pass

    if facts.get("photo_path"):
        add(facts["photo_path"]); seen.add(Path(facts["photo_path"]).name)

    # match recaps: query the actual teams + scorers (NOT the headline, which
    # contains words like "full-time" that match unrelated photos). News: parse
    # the headline subjects.
    if facts.get("home"):
        queries, national = [], True
        for sc in (facts.get("scorers") or []):
            nm = (sc.get("name") or "").split(". ")[-1]
            if len(nm) > 3:
                queries.append(f"{nm} footballer")
        for side in ("home_full", "away_full", "home", "away"):
            if facts.get(side):
                queries.append(f"{facts[side]} national football team")
    else:
        queries, national = commons.entity_queries(facts.get("headline", "")), False
    try:
        for q in queries:
            if len(imgs) >= 3:
                break
            found = commons.find_photo(q, modern=national)
            if not found or found["url"] in seen:
                continue
            rel = commons.download(found, f"pod_{post_id}_{len(imgs)}.jpg")
            if rel:
                add(rel); seen.add(found["url"])
    except Exception as exc:
        db.log_error("podcast", f"gather photos: {exc}")

    # top up to 2-3 with varied stadium backgrounds
    bgs = sorted(g.BG_DIR.glob("stadium_*.jpg"))
    seed = sum(ord(c) for c in facts.get("headline", "x"))
    bi = 0
    while len(imgs) < 2 and bgs:
        add(bgs[(seed + bi) % len(bgs)]); bi += 1
    return imgs[:3] or [Image.new("RGB", (g.RW, g.RH), g._hex(g.PITCH_BOTTOM))]


def _subtitle_layer(text: str, host: int, hook: bool = False) -> Image.Image:
    """A caption block: big bold white words on a subtle scrim. The hook sits
    higher and larger (clickbait opener); normal captions sit lower-third."""
    layer = Image.new("RGBA", (g.RW, g.RH), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    margin = 80
    sizes = (140, 124, 108, 92, 80) if hook else (96, 86, 76, 66)
    for size in sizes:
        f = g.label(size)
        lines = g._wrap_px(d, text.upper(), f, g.RW - 2 * margin)
        line_h = int(size * 1.16)
        if len(lines) * line_h <= (760 if hook else 520) and len(lines) <= (4 if hook else 3):
            break
    block_h = len(lines) * line_h
    y0 = (g.RH - block_h) // 2 - 60 if hook else 1150
    sc = Image.new("RGBA", (g.RW, g.RH), (0, 0, 0, 0))
    ImageDraw.Draw(sc).rectangle([0, y0 - 70, g.RW, y0 + block_h + 50],
                                 fill=(*g._hex(g.PITCH_BOTTOM), 170 if hook else 150))
    layer = Image.alpha_composite(layer, sc.filter(ImageFilter.GaussianBlur(34)))
    d = ImageDraw.Draw(layer)
    accent = g.GREEN if host == 0 else g.GREEN_BRIGHT
    y = y0
    for ln in lines:
        w = d.textlength(ln, font=f)
        x = (g.RW - w) / 2
        for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3)):
            d.text((x + dx, y + dy), ln, font=f, fill=g._hex(g.PITCH_BOTTOM))
        d.text((x, y), ln, font=f, fill=(g.WHITE if not hook else g._hex(g.GREEN_BRIGHT)))
        y += line_h
    d.rectangle([(g.RW - 90) / 2, y0 - 42, (g.RW + 90) / 2, y0 - 26], fill=accent)
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

    # 2-3 photos, each shown for an equal slice of the reel with a Ken Burns
    # push-in and a short crossfade between them
    photos = _gather_photos(post_id, facts)
    zoom_max = 1.12
    bases = [g._cover(p, int(g.RW * zoom_max), int(g.RH * zoom_max), top_bias=0.12) for p in photos]
    n = len(bases)
    win = total / n
    fade = min(0.6, win / 3)

    def photo_frame(base: Image.Image, local_t: float) -> Image.Image:
        z = 1.0 + (zoom_max - 1.0) * max(0.0, min(1.0, local_t / win))
        w, h = int(g.RW * z), int(g.RH * z)
        left, top = (base.width - w) // 2, (base.height - h) // 2
        return base.crop((left, top, left + w, top + h)).resize((g.RW, g.RH), Image.BILINEAR)

    # static brand chrome: scrims, logo, kicker pill, handle footer
    chrome = Image.new("RGBA", (g.RW, g.RH), (0, 0, 0, 0))
    cd = ImageDraw.Draw(chrome)
    dark = g._hex(g.PITCH_BOTTOM)
    for y in range(0, 520):
        cd.line([(0, y), (g.RW, y)], fill=(*dark, int(215 * (1 - y / 520))))
    for y in range(1560, g.RH):
        cd.line([(0, y), (g.RW, y)], fill=(*dark, int(200 * ((y - 1560) / (g.RH - 1560)) ** 1.2)))
    badge = g._logo_white(150)
    if badge is not None:
        chrome.paste(badge, ((g.RW - badge.width) // 2, 110), badge)
        cd = ImageDraw.Draw(chrome)
    # kicker pill (navy brand accent) — e.g. MATCH RECAP / BREAKING
    kicker = {"FINAL WHISTLE": "MATCH RECAP", "LIVE WHISTLE": "MATCH RECAP",
              "TRANSFER WHISTLE": "TRANSFER", "VAR CHECK": "VAR"}.get(fmt, "BREAKING")
    kf = g.label(38)
    kt = g._tracked_width(cd, kicker, kf, 8)
    pad, dot = 38, 9
    tot = kt + pad * 2 + dot * 2 + 18
    kx = (g.RW - tot) / 2
    cd.rounded_rectangle([kx, 300, kx + tot, 392], radius=46, fill=g.GREEN)
    cd.ellipse([kx + pad - dot, 337, kx + pad + dot, 355], fill=g.PITCH_BOTTOM)
    g._tracked(cd, (kx + pad + dot * 2 + 18, 324), kicker, kf, g.PITCH_BOTTOM, 8)
    # handle footer
    hf = g.meta(46)
    hw = g._tracked_width(cd, config.BRAND_HANDLE.upper(), hf, 3)
    g._tracked(cd, ((g.RW - hw) / 2, g.RH - 110), config.BRAND_HANDLE.upper(), hf, g.WHITE, 3)

    seg_layers = [_subtitle_layer(s["text"], s["host"], s.get("hook", False)) for s in segments]

    frames = int(total * FPS)
    silent = config.MEDIA_DIR / f"_pod_silent_{post_id}.mp4"
    writer = imageio.get_writer(str(silent), fps=FPS, codec="libx264", quality=7,
                                macro_block_size=None, pixelformat="yuv420p")
    try:
        for i in range(frames):
            t = i / FPS
            idx = min(int(t / win), n - 1)
            local = t - idx * win
            frame = photo_frame(bases[idx], local)
            # crossfade into the next photo near the window boundary
            if idx < n - 1 and win - local < fade:
                nxt = photo_frame(bases[idx + 1], 0.0)
                a = (fade - (win - local)) / fade
                frame = Image.blend(frame, nxt, a)
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
