"""Caption, alt-text and hashtag generation.

Captions are written by Claude in the brand voice when ANTHROPIC_API_KEY is
set; otherwise a deterministic template builder produces solid captions from
the same verified facts. Either way, the input is ONLY the verified facts
dict — the Claude prompt explicitly forbids adding any information that is
not in the facts, so the caption layer can never introduce misinformation.
"""

import json

from .. import config, db
from ..logger import get_logger
from . import formats

log = get_logger("captions")

BRAND_VOICE = f"""You write Instagram captions for "{config.BRAND_NAME}" \
({config.BRAND_HANDLE}), a football commentary page.

Voice: fast, sharp, modern. Opinionated but credible — strong takes, never
invented facts. Short punchy lines. Line breaks between thoughts. 1-3 fitting
emoji max. No clickbait, no "click link in bio", no hashtags (added separately).

CRAFT (this is what stops the scroll):
- Open on the single most interesting angle in the facts — the twist, the
  stakes, the number that jumps out — not a flat restatement of the headline.
- Have an actual opinion or framing. A caption that could sit under any match
  is a wasted caption.
- Vary how you start. Never lead with "Breaking:", "Official:" or the format
  name — the graphic already says that.
- Kill filler and cliché ("massive news", "here we go", "let that sink in").

HARD RULES:
- Use ONLY the facts provided in the JSON. Do not add players, scores,
  quotes, stats, fees or any detail that is not in the facts.
- If a fact is marked unconfirmed, reflect that ("reports say", "per ...").
- Maximum 500 characters.
- End with the engagement prompt provided, verbatim, as the final line.
"""


def build_caption(fmt: str, facts: dict, seed: int) -> tuple[str, str]:
    """Returns (caption_with_hashtags, alt_text)."""
    prompt_line = formats.engagement_prompt(fmt, seed, facts.get("event", ""))
    hashtags = formats.build_hashtags(
        fmt,
        facts.get("competition_code", ""),
        [t for t in (facts.get("home"), facts.get("away"),
                     facts.get("home_full"), facts.get("away_full")) if t],
        headline=facts.get("headline", ""),
    )

    body = None
    if config.ANTHROPIC_API_KEY:
        body = _claude_caption(fmt, facts, prompt_line)
    if not body:
        body = _template_caption(fmt, facts, prompt_line)

    # sources + photo attribution live at the bottom of the caption,
    # keeping the graphic itself clean (and satisfying CC license terms)
    tail = [hashtags]
    domains = facts.get("source_domains") or []
    if domains:
        tail.append("Sources: " + " · ".join(domains[:3]))
    if facts.get("photo_credit"):
        tail.append("📸 " + facts["photo_credit"].replace("PHOTO: ", "").title())

    caption = f"{body}\n.\n" + "\n".join(tail)
    return caption[:2200], _alt_text(fmt, facts)


def _claude_caption(fmt: str, facts: dict, prompt_line: str) -> str | None:
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=600,
            system=BRAND_VOICE,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Format: {fmt}\n"
                        f"Verified facts (use nothing else):\n{json.dumps(facts, indent=2)}\n"
                        f"Engagement prompt to end with: {prompt_line}\n\n"
                        "Write the caption."
                    ),
                }
            ],
        )
        db.log_api("anthropic", "messages.create", 200, True, f"model={config.CLAUDE_MODEL}")
        if response.stop_reason == "refusal":
            return None
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        return text or None
    except Exception as exc:
        log.warning("Claude caption failed, falling back to template: %s", exc)
        db.log_error("captions", f"claude fallback: {exc}")
        return None


def _template_caption(fmt: str, facts: dict, prompt_line: str) -> str:
    f = facts

    def _scorer_line() -> str:
        names = [
            f"{sc['name']} {sc.get('minute','')}" + (" (pen)" if sc.get("pen") else "")
            for sc in (f.get("scorers") or []) if sc.get("name")
        ]
        return ("⚽ " + " · ".join(names[:5])) if names else ""

    if fmt == "FINAL WHISTLE":
        lines = [
            f"FT: {f.get('home')} {f.get('home_score')}-{f.get('away_score')} {f.get('away')} 🏁",
            _scorer_line(),
            f"{f.get('competition', '')}".strip(),
        ]
    elif fmt == "LIVE WHISTLE":
        if not f.get("home"):  # headline-style live post (no match facts)
            lines = ["LIVE WHISTLE 🟢", f.get("headline", "")]
        elif f.get("event") == "kickoff":
            lines = [
                f"WE'RE LIVE: {f.get('home')} vs {f.get('away')} 🟢",
                f"{f.get('competition', '')}".strip(),
            ]
        elif f.get("event") == "red_card":
            rc = f.get("red_card") or {}
            lines = [
                f"RED CARD 🟥 {rc.get('name')} ({f.get('red_card_team')}) {rc.get('minute')}",
                f"{f.get('home')} {f.get('home_score')}-{f.get('away_score')} {f.get('away')} — LIVE",
            ]
        else:
            scorer = f.get("goal_scorer") or {}
            goal_line = (
                f"GOAL ⚽ {scorer.get('name')} {scorer.get('minute')}"
                if scorer.get("name") else ""
            )
            lines = [
                goal_line,
                f"{f.get('home')} {f.get('home_score')}-{f.get('away_score')} {f.get('away')}",
                f"{f.get('competition', '')} — LIVE".strip(),
            ]
    elif fmt == "TRANSFER WHISTLE":
        lines = ["TRANSFER WHISTLE 🔁", f.get("headline", ""), _context_line(f)]
    elif fmt == "VAR CHECK":
        lines = ["VAR CHECK 📺", f.get("headline", ""), _context_line(f)]
    elif fmt == "TEAM SHEET":
        lines = ["TEAM SHEET 📋", f.get("headline", ""), _context_line(f)]
    elif fmt == "MATCHDAY":
        lines = ["MATCHDAY 🗓️", f.get("headline", "")]
    else:  # BREAKING
        lines = ["BREAKING 🚨", f.get("headline", ""), _context_line(f)]
    body = "\n\n".join(l for l in lines if l)
    return f"{body}\n\n{prompt_line}"


def _context_line(facts: dict) -> str:
    """Editorial context straight from the source outlet's own summary —
    adds substance without inventing anything."""
    summary = (facts.get("story_summary") or "").strip()
    if not summary:
        return ""
    headline_tokens = set((facts.get("headline") or "").lower().split())
    # skip summaries that just restate the headline
    if len(set(summary.lower().split()) - headline_tokens) < 5:
        return ""
    if len(summary) > 220:
        summary = summary[:217].rsplit(" ", 1)[0] + "…"
    return summary


def _alt_text(fmt: str, facts: dict) -> str:
    f = facts
    if fmt in ("FINAL WHISTLE", "LIVE WHISTLE") and f.get("home"):
        score = (
            f" {f.get('home_score')}-{f.get('away_score')}"
            if f.get("home_score") is not None
            else ""
        )
        return (
            f"Green and white {config.BRAND_NAME} graphic: {fmt} — "
            f"{f.get('home')}{score} {f.get('away')}, {f.get('competition', 'football')}."
        )[:1000]
    return (
        f"Green and white {config.BRAND_NAME} graphic: {fmt} — {f.get('headline', 'football update')}"
    )[:1000]
