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

# Engagement prompts are the last line of every caption. They should bait a
# specific opinion — a name, a scoreline, a verdict — not a limp "Thoughts?".
# Deeper pools mean the same line rarely shows up twice in a row.
ENGAGEMENT_PROMPTS = {
    "LIVE WHISTLE": [
        "Who's bossing this one? Drop it below 👇",
        "Call the final score right now ⬇️",
        "Who's holding on and who's cracking? 👇",
    ],
    "LIVE WHISTLE:kickoff": [
        "Lock your scoreline in before kickoff 👇",
        "First goalscorer — call it now ⬇️",
        "Winner, draw or upset? Predict it 👇",
        "Your exact scoreline in one comment ⬇️",
    ],
    "LIVE WHISTLE:goal": [
        "Game on or game over? Decide below 👇",
        "Can they hold this? Your call ⬇️",
        "Next goal wins it — who scores? 👇",
        "Enough to see it out? 👇",
    ],
    "LIVE WHISTLE:red_card": [
        "Red card — right call or a joke? 👇",
        "Does this decide the game now? ⬇️",
        "You're the ref: red, or never? 👇",
    ],
    "FINAL WHISTLE": [
        "Man of the match — one name, go 👇",
        "Deserved winners? Settle it below ⬇️",
        "Rate that performance out of 10 👇",
        "Who was your standout today? ⬇️",
        "Result the game deserved? Have your say 👇",
    ],
    "TRANSFER WHISTLE": [
        "Bargain or overpay? Give us the verdict 👇",
        "Nailed-on starter or squad filler? ⬇️",
        "Perfect fit or panic buy? 👇",
        "Would your club take him tomorrow? ⬇️",
        "Window winner or a miss? Call it 👇",
        "Who wins this deal? ⬇️",
    ],
    "VAR CHECK": [
        "You're the ref — what's your call? 👇",
        "Clear and obvious, or a robbery? ⬇️",
        "Overturn it or wave play on? 👇",
    ],
    "TEAM SHEET": [
        "Best XI, or a head-scratcher? 👇",
        "One name you'd rip out of this side? ⬇️",
        "Right shape for this one? Your call 👇",
    ],
    "MATCHDAY": [
        "Which game are you locked in for? 👇",
        "Banker of the day — one pick ⬇️",
        "Give us your upset shout for today 👇",
    ],
    "BREAKING": [
        "Your one-line reaction — go 👇",
        "Massive, or overblown? Decide below ⬇️",
        "Where does this leave them? 👇",
        "Called it, or did this blindside you? ⬇️",
        "Good move or a bad one? 👇",
        "Does this change the picture? ⬇️",
    ],
}


# entity fragments (lowercase) found in headlines/teams -> hashtags
ENTITY_HASHTAGS = {
    "manchester united": ["#manutd", "#mufc"], "man utd": ["#manutd", "#mufc"],
    "man united": ["#manutd"], "manchester city": ["#mancity"], "man city": ["#mancity"],
    "liverpool": ["#liverpool", "#lfc"], "chelsea": ["#chelsea", "#cfc"],
    "arsenal": ["#arsenal", "#afc"], "tottenham": ["#spurs", "#thfc"], "spurs": ["#spurs"],
    "newcastle": ["#nufc"], "aston villa": ["#avfc"], "west ham": ["#westham"],
    "everton": ["#everton"], "brighton": ["#bhafc"], "wolves": ["#wolves"],
    "leeds": ["#lufc"], "celtic": ["#celticfc"], "rangers": ["#rangersfc"],
    "real madrid": ["#realmadrid"], "barcelona": ["#barcelona", "#fcb"],
    "atletico": ["#atleticomadrid"], "bayern": ["#fcbayern"],
    "dortmund": ["#bvb"], "juventus": ["#juventus"], "inter": ["#intermilan"],
    "ac milan": ["#acmilan"], "napoli": ["#napoli"], "psg": ["#psg"],
    "paris saint-germain": ["#psg"], "ajax": ["#ajax"], "porto": ["#fcporto"],
    "benfica": ["#slbenfica"], "galatasaray": ["#galatasaray"],
    "usmnt": ["#usmnt"], "ronaldo": ["#ronaldo", "#cr7"], "messi": ["#messi"],
    "mbappe": ["#mbappe"], "mbappé": ["#mbappe"], "haaland": ["#haaland"],
    "bellingham": ["#bellingham"], "vinicius": ["#vinijr"], "yamal": ["#lamineyamal"],
    "england": ["#england", "#threelions"], "scotland": ["#scotland"],
    "wales": ["#wales"], "france": ["#france", "#lesbleus"],
    "germany": ["#germany"], "spain": ["#spain"], "italy": ["#italy"],
    "brazil": ["#brazil", "#selecao"], "argentina": ["#argentina"],
    "portugal": ["#portugal"], "netherlands": ["#netherlands"],
    "mexico": ["#mexico", "#eltri"], "canada": ["#canada", "#canmnt"],
    "usa": ["#usa", "#usmnt"], "united states": ["#usmnt"],
    "japan": ["#japan"], "south korea": ["#southkorea"],
    "morocco": ["#morocco"], "croatia": ["#croatia"], "bosnia": ["#bosnia"],
    "paraguay": ["#paraguay"], "australia": ["#australia", "#socceroos"],
    "türkiye": ["#turkiye"], "turkey": ["#turkiye"], "haiti": ["#haiti"],
    "switzerland": ["#switzerland"], "qatar": ["#qatar"],
}

_NAME_STOP = {
    "World", "Cup", "FIFA", "UEFA", "Premier", "League", "Champions",
    "United", "City", "Group", "Friday", "Saturday", "Sunday", "Madrid",
    "Whistle", "Football", "VAR", "Stadium", "The",
}


def entity_hashtags(text: str) -> list[str]:
    """Relevant hashtags from headline/team text: known clubs, nations and
    star players, plus likely player surnames from capitalised words."""
    low = text.lower()
    tags: list[str] = []
    for fragment, frag_tags in ENTITY_HASHTAGS.items():
        if fragment in low:
            tags.extend(frag_tags)
    # likely person names not already covered (e.g. "McTominay", "Pogba")
    for word in re.findall(r"[A-ZÀ-Þ][A-Za-zà-ÿ'']{4,}", text):
        if word in _NAME_STOP:
            continue
        slug = "#" + re.sub(r"[^a-z0-9]", "", word.lower())
        if len(tags) < 14 and not any(slug in t or t in slug for t in tags):
            tags.append(slug)
    return tags


def team_hashtag(team: str) -> str:
    slug = re.sub(r"[^a-z0-9]", "", team.lower())
    # long multi-word slugs ("bosniaandherzegovina") read like keyboard mash
    return f"#{slug}" if slug and len(slug) <= 14 else ""


def build_hashtags(fmt: str, competition_code: str = "", teams: list[str] | None = None,
                   headline: str = "") -> str:
    tags = list(BASE_HASHTAGS) + FORMAT_HASHTAGS.get(fmt, [])
    tags += COMPETITION_HASHTAGS.get(competition_code, [])
    # story-specific tags from the subjects involved
    tags += entity_hashtags(" ".join([headline or "", *(teams or [])]))
    for t in teams or []:
        ht = team_hashtag(t)
        if ht and len(ht) > 3:
            tags.append(ht)
    seen, out = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return " ".join(out[:15])


def engagement_prompt(fmt: str, seed: int, event: str = "") -> str:
    """Prompt pool keyed by format, refined by the match event so a
    kick-off post never asks viewers to rate a half that hasn't happened."""
    prompts = (ENGAGEMENT_PROMPTS.get(f"{fmt}:{event}") if event else None) \
        or ENGAGEMENT_PROMPTS.get(fmt, ENGAGEMENT_PROMPTS["BREAKING"])
    return prompts[seed % len(prompts)]
