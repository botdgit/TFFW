"""ESPN public scoreboard JSON — keyless live scores, fixtures and results
for the monitored competitions. Used as the primary match source when no
football-data.org token is configured (and as a cross-check source when
one is)."""

from .. import config
from ..http_client import get_json

SERVICE = "espn"
BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

# football-data.org competition codes -> ESPN league slugs
LEAGUES = {
    "WC": "fifa.world",
    "PL": "eng.1",
    "CL": "uefa.champions",
    "EC": "uefa.euro",
    "PD": "esp.1",
    "SA": "ita.1",
    "BL1": "ger.1",
    "FL1": "fra.1",
}

STATE_MAP = {"pre": "TIMED", "in": "IN_PLAY", "post": "FINISHED"}


def todays_matches() -> list[dict]:
    """Current scoreboard for every monitored competition, normalised to
    the same match shape football_data produces."""
    out = []
    for code in config.COMPETITIONS:
        slug = LEAGUES.get(code)
        if not slug:
            continue
        data = get_json(SERVICE, f"{BASE}/{slug}/scoreboard")
        if not data:
            continue
        league_name = (data.get("leagues") or [{}])[0].get("name", code)
        for ev in data.get("events") or []:
            comp = (ev.get("competitions") or [{}])[0]
            sides = {c.get("homeAway"): c for c in comp.get("competitors", [])}
            home, away = sides.get("home", {}), sides.get("away", {})
            team_side = {
                (c.get("team") or {}).get("id"): c.get("homeAway")
                for c in comp.get("competitors", [])
            }
            scorers, reds = [], []
            for d in comp.get("details") or []:
                athletes = d.get("athletesInvolved") or [{}]
                entry = {
                    "name": athletes[0].get("shortName") or athletes[0].get("displayName", ""),
                    "minute": (d.get("clock") or {}).get("displayValue", ""),
                    "side": team_side.get((d.get("team") or {}).get("id"), ""),
                }
                if d.get("scoringPlay"):
                    entry["pen"] = d.get("penaltyKick", False)
                    entry["og"] = d.get("ownGoal", False)
                    scorers.append(entry)
                elif d.get("redCard"):
                    reds.append(entry)
            state = ((ev.get("status") or {}).get("type") or {}).get("state", "pre")
            status = STATE_MAP.get(state, "TIMED")
            completed = ((ev.get("status") or {}).get("type") or {}).get("completed", False)
            scores_live = status == "IN_PLAY" or (status == "FINISHED" and completed)
            out.append(
                {
                    "id": f"espn-{ev.get('id')}",
                    "competition": league_name,
                    "competition_code": code,
                    "utc_date": ev.get("date", ""),
                    "status": status,
                    "home": (home.get("team") or {}).get("shortDisplayName", "?"),
                    "away": (away.get("team") or {}).get("shortDisplayName", "?"),
                    "home_full": (home.get("team") or {}).get("displayName", "?"),
                    "away_full": (away.get("team") or {}).get("displayName", "?"),
                    "home_score": int(home["score"]) if scores_live and home.get("score") is not None else None,
                    "away_score": int(away["score"]) if scores_live and away.get("score") is not None else None,
                    "scorers": scorers,
                    "red_cards": reds,
                    "minute": ((ev.get("status") or {}).get("type") or {}).get("shortDetail", ""),
                    "source": "espn.com",
                }
            )
    return out


STANDINGS_URL = "https://site.api.espn.com/apis/v2/sports/soccer/{code}/standings"


def standings(code: str = "fifa.world") -> list[dict]:
    """World Cup group tables. Returns a list of groups, each with ordered
    rows: {rank, team, played, win, draw, loss, gd, points}. Only groups
    that have played at least one game are returned."""
    data = get_json("espn", STANDINGS_URL.format(code=code))
    if not data:
        return []
    groups = []
    for child in data.get("children", []):
        rows = []
        for e in ((child.get("standings") or {}).get("entries") or []):
            stat = {s.get("abbreviation"): s.get("displayValue") for s in e.get("stats", [])}
            played = _to_int(stat.get("GP"))
            rows.append({
                "rank": _to_int(stat.get("R")),
                "team": (e.get("team") or {}).get("displayName", "?"),
                "played": played,
                "win": _to_int(stat.get("W")),
                "draw": _to_int(stat.get("D")),
                "loss": _to_int(stat.get("L")),
                "gd": stat.get("GD", "0"),
                "points": _to_int(stat.get("P")),
            })
        if any(r["played"] for r in rows):
            rows.sort(key=lambda r: r["rank"] or 99)
            groups.append({"name": child.get("name", ""), "rows": rows})
    return groups


def _to_int(value) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0
