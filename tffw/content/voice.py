"""Voiceover for match recaps.

Primary: ElevenLabs (ELEVENLABS_API_KEY + ELEVENLABS_VOICE_ID) — the brand
presenter voice. Note: ElevenLabs blocks FREE-tier TTS from datacenter IPs,
so on free tier the fallback engages automatically from cloud runners; a
paid ElevenLabs plan activates the chosen voice with no code change.

Fallback: Microsoft Edge neural TTS (free, keyless). Default is
en-US-AvaMultilingualNeural — Microsoft's newest US-female voice, markedly
more lifelike and expressive than the older Aria newscast voice. Swap it
without a code change via EDGE_TTS_VOICE, or dial the pace with EDGE_TTS_RATE.
Other natural US-female options: en-US-EmmaMultilingualNeural (warmer),
en-US-JennyNeural (friendly), en-US-AriaNeural (classic newscast).
"""

import os
import re
import ssl

import requests

from .. import config, db
from ..logger import get_logger

log = get_logger("voice")

ELEVEN_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
# American woman presenter. ElevenLabs "Rachel" (a default US female voice)
# when the paid plan is active; on the free edge-tts fallback that actually
# runs from cloud runners, Microsoft "Ava" — a newer, more natural US-female
# neural voice than the previous Aria newscast default.
ELEVEN_VOICE = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
EDGE_VOICE = os.environ.get("EDGE_TTS_VOICE", "en-US-AvaMultilingualNeural")
# a touch of extra pace keeps the recap punchy without sounding rushed
EDGE_RATE = os.environ.get("EDGE_TTS_RATE", "+6%")


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
            await edge_tts.Communicate(text, voice=EDGE_VOICE, rate=EDGE_RATE).save(str(out_path))

        asyncio.run(_run())
        ok = out_path.exists() and out_path.stat().st_size > 10_000
        db.log_api("edge-tts", EDGE_VOICE, 200 if ok else None, ok)
        return ok
    except Exception as exc:
        db.log_error("voice", f"edge-tts: {exc}")
        return False


# Rotating openers/intros/closers so consecutive recaps don't all start and
# end with the identical line. Seeded from the match facts, so the choice is
# deterministic per game (the same match always narrates the same way) while
# the feed as a whole stops sounding like a template.
_OPENERS = (
    "Welcome back to The Football Final Whistle.",
    "This is The Football Final Whistle.",
    "The Football Final Whistle here.",
    "You're listening to The Football Final Whistle.",
)
_INTROS = (
    "{opener} Here's the story of {home} against {away}{comp}.",
    "{opener} Let's run through {home} and {away}{comp}.",
    "{opener} Here's how {home} and {away} played out{comp}.",
    "{opener} Your full-time recap of {home} against {away}{comp}.",
)
_CLOSERS = (
    "Follow The Football Final Whistle for every goal, every game.",
    "That's the full whistle — follow for every goal, every game.",
    "Stay with The Football Final Whistle, every goal, every game.",
    "Hit follow for every goal, every game.",
)


def build_recap_script(facts: dict) -> str:
    """Podcast-style ~30s narration built strictly from verified match
    facts (teams, score, scorers with minutes, competition). The phrasing
    follows the story of the game — deadlock broken, equalisers, leads
    extended, goals pulled back, late drama — never invented detail."""
    home = facts.get("home_full") or facts.get("home", "")
    away = facts.get("away_full") or facts.get("away", "")
    hs, as_ = facts.get("home_score"), facts.get("away_score")
    comp = facts.get("competition", "the match")
    scorers = [s for s in (facts.get("scorers") or []) if s.get("name")]

    def minute_n(sc) -> int:
        m = re.search(r"\d+", sc.get("minute") or "")
        return int(m.group()) if m else 0

    scorers = sorted(scorers, key=minute_n)
    # deterministic per-match rotation of the opening/closing lines
    seed = (int(hs or 0) * 7 + int(as_ or 0) * 13 + len(home) + len(away))
    comp_clause = f" in {comp}" if comp and comp != "the match" else ""
    intro = _INTROS[(seed // 3) % len(_INTROS)].format(
        opener=_OPENERS[seed % len(_OPENERS)], home=home, away=away, comp=comp_clause)
    lines = [intro]

    h = a = 0
    home_trailed = away_trailed = False
    for i, sc in enumerate(scorers[:4]):
        is_home = sc.get("side") == "home"
        team = home if is_home else away
        h, a = (h + 1, a) if is_home else (h, a + 1)
        home_trailed, away_trailed = home_trailed or h < a, away_trailed or a < h
        mn = minute_n(sc)
        stoppage = mn >= 90 or "+" in (sc.get("minute") or "")
        if stoppage:
            when = "deep in stoppage time"
        elif mn:
            when = f"in the {_minute_words(mn)} minute"
        else:
            when = "in the second half"
        pen = " from the penalty spot" if sc.get("pen") else ""
        lead = "Deep into the second half, " if 75 <= mn < 90 else ""

        if sc.get("og"):
            if i == 0:
                og = f"an own goal handed {team} the lead"
            elif h == a:
                og = f"an own goal dragged {team} level"
            elif (h > a) == is_home:
                og = f"an own goal put {team} ahead"
            else:
                og = f"an own goal pulled {team} back into it"
            clause = f"{lead}{og} {when}."
            lines.append(clause[0].upper() + clause[1:])
            continue
        # narrate surnames the way a commentator would ("Lukic", not "J. Lukic")
        name = re.sub(r"^[A-Z]\.\s*", "", sc["name"])
        if i == 0:
            phrase = f"{name} broke the deadlock for {team}{pen} {when}"
        elif h == a:
            phrase = f"{name} levelled it for {team}{pen} {when}"
        elif (h > a) == is_home and abs(h - a) == 1:
            phrase = f"{name} put {team} in front{pen} {when}"
        elif (h > a) == is_home:
            phrase = f"{name} stretched the lead for {team}{pen} {when}"
        else:
            phrase = f"{name} pulled one back for {team}{pen} {when}"
        clause = f"{lead}{phrase}."
        lines.append(clause[0].upper() + clause[1:])

    if hs is not None and as_ is not None:
        if hs == as_ == 0:
            lines.append("Chances at both ends, but no breakthrough — it finished goalless.")
        elif hs == as_:
            lines.append(f"It finished {_num(hs)}–{_num(as_)} — a point apiece.")
        else:
            winner = home if hs > as_ else away
            comeback = home_trailed if hs > as_ else away_trailed
            tail = " — a comeback to savour" if comeback else ""
            lines.append(f"It finished {_num(max(hs, as_))}–{_num(min(hs, as_))} to {winner}{tail}.")
    lines.append(_CLOSERS[seed % len(_CLOSERS)])
    return " ".join(lines)


def _minute_words(n: int) -> str:
    """Ordinal minute for natural speech ('twenty-first')."""
    ones = ["", "first", "second", "third", "fourth", "fifth", "sixth",
            "seventh", "eighth", "ninth"]
    teens = {10: "tenth", 11: "eleventh", 12: "twelfth", 13: "thirteenth",
             14: "fourteenth", 15: "fifteenth", 16: "sixteenth",
             17: "seventeenth", 18: "eighteenth", 19: "nineteenth"}
    tens = {2: "twent", 3: "thirt", 4: "fort", 5: "fift", 6: "sixt",
            7: "sevent", 8: "eight", 9: "ninet"}
    if 1 <= n <= 9:
        return ones[n]
    if n in teens:
        return teens[n]
    t, o = divmod(n, 10)
    if t in tens:
        return f"{tens[t]}ieth" if o == 0 else f"{tens[t]}y-{ones[o]}"
    return str(n)


def _num(n) -> str:
    words = ["nil", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
    try:
        return words[int(n)] if 0 <= int(n) <= 9 else str(n)
    except (TypeError, ValueError):
        return str(n)
