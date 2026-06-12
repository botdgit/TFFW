"""Recurring brand formats and the per-format hashtag/engagement kits."""

import re

FORMATS = (
    "LIVE WHISTLE",      # kick-off, goals, red cards, in-play updates
    "FINAL WHISTLE",     # full-time results
    "TRANSFER WHISTLE",  # verified transfer news
    "VAR CHECK",         # VAR / officiating talking points
    "TEAM SHEET",        # line-ups / squad & team news
    "MATCHDAY",          # fixtures, previews, league tables
    "BREAKING",          # verified breaking news, injuries, big stories
)

BASE_HASHTAGS = ["#football", "#footballnews", "#soccer"]

FORMAT_HASHTAGS = {
    "LIVE WHISTLE": ["#livescore", "#matchday"],
    "FINAL WHISTLE": ["#fulltime", "#results", "#matchday"],
    "TRANSFER WHISTLE": ["#transfernews", "#transferwindow", "#deadlineday"],
    "VAR CHECK": ["#var", "#refwatch"],
    "TEAM SHEET": ["#teamnews", "#startingxi"],
    "MATCHDAY": ["#matchday", "#fixtures"],
    "BREAKING": ["#breakingnews"],
}

COMPETITION_HASHTAGS = {
    "PL": ["#premierleague", "#epl"],
    "CL": ["#championsleague", "#ucl"],
    "WC": ["#worldcup", "#fifaworldcup"],
    "EC": ["#euros"],
    "PD": ["#laliga"],
    "SA": ["#seriea"],
    "BL1": ["#bundesliga"],
    "FL1": ["#ligue1"],
}

ENGAGEMENT_PROMPTS = {
    "LIVE WHISTLE": [
        "Who's running this game? Drop it below 👇",
        "Calling the final score now — comments open ⬇️",
        "Rate the first half out of 10 👇",
    ],
    "FINAL WHISTLE": [
        "Player of the match? Comments below 👇",
        "Fair result? Have your say ⬇️",
        "Rate your team's performance /10 👇",
    ],
    "TRANSFER WHISTLE": [
        "Good business or panic buy? 👇",
        "Hit or flop? Call it now ⬇️",
        "What's the right fee here? Comments 👇",
    ],
    "VAR CHECK": [
        "Right call or robbery? 👇",
        "You're the ref — what do you give? ⬇️",
    ],
    "TEAM SHEET": [
        "Happy with this XI? 👇",
        "One change you'd make? ⬇️",
    ],
    "MATCHDAY": [
        "Which one are you watching? 👇",
        "Call your scores for today ⬇️",
        "Game of the day? 👇",
    ],
    "BREAKING": [
        "Thoughts? 👇",
        "How big is this? Comments below ⬇️",
    ],
}


def team_hashtag(team: str) -> str:
    slug = re.sub(r"[^a-z0-9]", "", team.lower())
    return f"#{slug}" if slug else ""


def build_hashtags(fmt: str, competition_code: str = "", teams: list[str] | None = None) -> str:
    tags = list(BASE_HASHTAGS) + FORMAT_HASHTAGS.get(fmt, [])
    tags += COMPETITION_HASHTAGS.get(competition_code, [])
    for t in teams or []:
        ht = team_hashtag(t)
        if ht:
            tags.append(ht)
    seen, out = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return " ".join(out[:15])


def engagement_prompt(fmt: str, seed: int) -> str:
    prompts = ENGAGEMENT_PROMPTS.get(fmt, ENGAGEMENT_PROMPTS["BREAKING"])
    return prompts[seed % len(prompts)]
