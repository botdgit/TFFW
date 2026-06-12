"""Voiceover for match recaps.

Primary: ElevenLabs (ELEVENLABS_API_KEY + ELEVENLABS_VOICE_ID) — the brand
presenter voice. Note: ElevenLabs blocks FREE-tier TTS from datacenter IPs,
so on free tier the fallback engages automatically from cloud runners; a
paid ElevenLabs plan activates the chosen voice with no code change.

Fallback: Microsoft Edge neural TTS (free, keyless): en-GB-RyanNeural.
"""

import os
import ssl

import requests

from .. import config, db
from ..logger import get_logger

log = get_logger("voice")

ELEVEN_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVEN_VOICE = os.environ.get("ELEVENLABS_VOICE_ID", "lUTamkMw7gOzZbFIwmq4")
EDGE_VOICE = os.environ.get("EDGE_TTS_VOICE", "en-GB-RyanNeural")


def tts(text: str, out_path) -> bool:
    """Synthesize narration to out_path (mp3). Returns True on success."""
    if ELEVEN_KEY and _elevenlabs(text, out_path):
        return True
    return _edge(text, out_path)


def _elevenlabs(text: str, out_path) -> bool:
    try:
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE}"
            "?output_format=mp3_44100_128",
            headers={"xi-api-key": ELEVEN_KEY, "Content-Type": "application/json"},
            json={
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.3},
            },
            timeout=120,
        )
        db.log_api("elevenlabs", "text-to-speech", r.status_code, r.ok)
        if r.ok and len(r.content) > 10_000:
            out_path.write_bytes(r.content)
            return True
        log.warning("elevenlabs tts failed (%s): %s — falling back to edge-tts",
                    r.status_code, r.text[:120])
        return False
    except requests.RequestException as exc:
        db.log_error("voice", f"elevenlabs: {exc}")
        return False


def _edge(text: str, out_path) -> bool:
    try:
        import asyncio

        import edge_tts.communicate as ec

        # the sandbox egress proxy intercepts the TTS websocket TLS;
        # verification must be relaxed for this stream only
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ec._SSL_CTX = ctx
        import edge_tts

        async def _run():
            await edge_tts.Communicate(text, voice=EDGE_VOICE, rate="+3%").save(str(out_path))

        asyncio.run(_run())
        ok = out_path.exists() and out_path.stat().st_size > 10_000
        db.log_api("edge-tts", EDGE_VOICE, 200 if ok else None, ok)
        return ok
    except Exception as exc:
        db.log_error("voice", f"edge-tts: {exc}")
        return False


def build_recap_script(facts: dict) -> str:
    """Podcast-style ~30s narration built strictly from verified match
    facts (teams, score, scorers with minutes, competition)."""
    home, away = facts.get("home", ""), facts.get("away", "")
    hs, as_ = facts.get("home_score"), facts.get("away_score")
    comp = facts.get("competition", "the match")
    scorers = [s for s in (facts.get("scorers") or []) if s.get("name")]

    lines = [f"Welcome back to The Football Final Whistle — your recap of {home} against {away} in {comp}."]
    for sc in scorers[:4]:
        side_team = home if sc.get("side") == "home" else away
        pen = " from the penalty spot" if sc.get("pen") else ""
        og = " — an own goal" if sc.get("og") else ""
        lines.append(f"{sc['name']} scored for {side_team}{pen} in the {sc.get('minute','')} minute{og}.")
    if hs is not None:
        if hs == as_:
            lines.append(f"It finished {_num(hs)}–{_num(as_)} — a point apiece.")
        else:
            winner, ls, ws = (home, as_, hs) if hs > as_ else (away, hs, as_)
            lines.append(f"It finished {_num(max(hs,as_))}–{_num(min(hs,as_))} to {winner}.")
    lines.append("Follow The Football Final Whistle for every goal, every game.")
    return " ".join(lines)


def _num(n) -> str:
    words = ["nil", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
    try:
        return words[int(n)] if 0 <= int(n) <= 9 else str(n)
    except (TypeError, ValueError):
        return str(n)
