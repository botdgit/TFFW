"""TheSportsDB — free second source used to cross-check full-time results
before a FINAL WHISTLE post is published. The shared community key ("3")
works without registration."""

import unicodedata
from datetime import datetime

from .. import config
from ..http_client import get_json

SERVICE = "thesportsdb"


def _norm(name: str) -> str:
    """Loose team-name normalisation for cross-source matching."""
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = name.lower()
    for junk in (" fc", "fc ", " afc", "afc ", " cf", "club ", "."):
        name = name.replace(junk, " ")
    return " ".join(name.split())


def _names_match(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    if na == nb:
        return True
    ta, tb = set(na.split()), set(nb.split())
    return bool(ta & tb)  # share at least one significant token


def confirm_result(home: str, away: str, home_score: int, away_score: int, utc_date: str) -> bool | None:
    """Cross-check a final score.

    Returns True (confirmed), False (conflicting), or None (couldn't find
    the fixture — e.g. API gap), letting the caller decide on confidence.
    """
    try:
        day = datetime.fromisoformat(utc_date.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None

    data = get_json(
        SERVICE,
        f"{config.THESPORTSDB_BASE}/{config.THESPORTSDB_KEY}/eventsday.php",
        params={"d": day, "s": "Soccer"},
    )
    if not data or not data.get("events"):
        return None

    for ev in data["events"]:
        eh, ea = ev.get("strHomeTeam", ""), ev.get("strAwayTeam", "")
        if _names_match(home, eh) and _names_match(away, ea):
            hs, as_ = ev.get("intHomeScore"), ev.get("intAwayScore")
            if hs is None or as_ is None:
                return None
            return int(hs) == int(home_score) and int(as_) == int(away_score)
    return None
