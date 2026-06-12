"""football-data.org v4 — primary structured source for fixtures, live
scores, results and league tables. Free tier covers the Premier League,
Champions League, World Cup, Euros and the other major leagues at
10 requests/minute, which the pipeline stays well under."""

from datetime import datetime, timedelta, timezone

from .. import config
from ..http_client import get_json

SERVICE = "football-data"


def _headers() -> dict:
    return {"X-Auth-Token": config.FOOTBALL_DATA_TOKEN}


def configured() -> bool:
    return bool(config.FOOTBALL_DATA_TOKEN)


def matches_window(days_back: int = 0, days_forward: int = 0) -> list[dict]:
    """Matches for the monitored competitions in a date window (UTC)."""
    today = datetime.now(timezone.utc).date()
    date_from = (today - timedelta(days=days_back)).isoformat()
    date_to = (today + timedelta(days=days_forward)).isoformat()
    data = get_json(
        SERVICE,
        f"{config.FOOTBALL_DATA_BASE}/matches",
        headers=_headers(),
        params={
            "dateFrom": date_from,
            "dateTo": date_to,
            "competitions": ",".join(config.COMPETITIONS),
        },
    )
    if not data:
        return []
    return [_normalise(m) for m in data.get("matches", [])]


def standings(competition: str) -> list[dict]:
    """League table rows for a competition code (e.g. 'PL')."""
    data = get_json(
        SERVICE,
        f"{config.FOOTBALL_DATA_BASE}/competitions/{competition}/standings",
        headers=_headers(),
    )
    if not data:
        return []
    for table in data.get("standings", []):
        if table.get("type") == "TOTAL":
            return [
                {
                    "position": row["position"],
                    "team": row["team"]["shortName"] or row["team"]["name"],
                    "played": row["playedGames"],
                    "gd": row["goalDifference"],
                    "points": row["points"],
                }
                for row in table.get("table", [])
            ]
    return []


def _normalise(m: dict) -> dict:
    score = m.get("score", {}) or {}
    full = score.get("fullTime", {}) or {}
    return {
        "id": m["id"],
        "competition": (m.get("competition") or {}).get("name", ""),
        "competition_code": (m.get("competition") or {}).get("code", ""),
        "utc_date": m.get("utcDate", ""),
        "status": m.get("status", ""),  # SCHEDULED/TIMED/IN_PLAY/PAUSED/FINISHED/...
        "minute": m.get("minute"),
        "home": (m.get("homeTeam") or {}).get("shortName")
        or (m.get("homeTeam") or {}).get("name", "?"),
        "away": (m.get("awayTeam") or {}).get("shortName")
        or (m.get("awayTeam") or {}).get("name", "?"),
        "home_full": (m.get("homeTeam") or {}).get("name", "?"),
        "away_full": (m.get("awayTeam") or {}).get("name", "?"),
        "home_score": full.get("home"),
        "away_score": full.get("away"),
        "matchday": m.get("matchday"),
    }
