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
    ],
    "LIVE WHISTLE:kickoff": [
        "Score predictions — lock them in now 👇",
        "Who takes this one? Call it ⬇️",
        "First scorer? Drop your pick 👇",
    ],
    "LIVE WHISTLE:goal": [
        "Who's running this game? Drop it below 👇",
        "Calling the final score now — comments open ⬇️",
        "Game over or game on? 👇",
    ],
    "LIVE WHISTLE:red_card": [
        "Right call or harsh? You decide 👇",
        "Does this change the game? ⬇️",
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
        "Does he start week one? ⬇️",
        "Upgrade or sideways move? 👇",
        "Who wins this deal? ⬇️",
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
        "Big story or nothing-burger? ⬇️",
        "Where does this leave them? 👇",
        "Saw this coming? ⬇️",
        "Your take in one line 👇",
        "Does this change anything? ⬇️",
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
