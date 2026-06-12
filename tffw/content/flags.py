"""National-team flags for match graphics.

Flags come from flagcdn.com (flag images of sovereign states are public
domain) and are cached in assets/flags/ so each is downloaded once and
committed with the repo. Club teams have no flag — match cards then fall
back to the standard pitch background.
"""

from pathlib import Path

import requests

from .. import config
from ..logger import get_logger

log = get_logger("flags")

FLAG_DIR = config.ROOT / "assets" / "flags"
CDN = "https://flagcdn.com/w1280/{code}.png"

# team-name fragment (lowercase) -> flagcdn / ISO 3166 code
COUNTRY_CODES = {
    "england": "gb-eng", "scotland": "gb-sct", "wales": "gb-wls",
    "northern ireland": "gb-nir", "ireland": "ie",
    "france": "fr", "germany": "de", "spain": "es", "italy": "it",
    "portugal": "pt", "netherlands": "nl", "belgium": "be", "croatia": "hr",
    "denmark": "dk", "sweden": "se", "norway": "no", "poland": "pl",
    "switzerland": "ch", "austria": "at", "turkey": "tr", "türkiye": "tr",
    "ukraine": "ua", "serbia": "rs", "czech": "cz", "slovakia": "sk",
    "slovenia": "si", "hungary": "hu", "romania": "ro", "greece": "gr",
    "albania": "al", "georgia": "ge", "bosnia": "ba",
    "brazil": "br", "argentina": "ar", "uruguay": "uy", "colombia": "co",
    "chile": "cl", "ecuador": "ec", "peru": "pe", "paraguay": "py",
    "bolivia": "bo", "venezuela": "ve",
    "usa": "us", "united states": "us", "mexico": "mx", "canada": "ca",
    "costa rica": "cr", "panama": "pa", "honduras": "hn", "jamaica": "jm",
    "haiti": "ht", "curacao": "cw", "curaçao": "cw",
    "japan": "jp", "south korea": "kr", "korea republic": "kr", "iran": "ir",
    "saudi arabia": "sa", "qatar": "qa", "australia": "au", "uzbekistan": "uz",
    "jordan": "jo", "iraq": "iq", "china": "cn", "india": "in",
    "morocco": "ma", "senegal": "sn", "ghana": "gh", "nigeria": "ng",
    "cameroon": "cm", "egypt": "eg", "tunisia": "tn", "algeria": "dz",
    "ivory coast": "ci", "cote d'ivoire": "ci", "côte d'ivoire": "ci",
    "mali": "ml", "south africa": "za", "cape verde": "cv",
    "new zealand": "nz",
}


def code_for(team_name: str) -> str | None:
    name = team_name.lower()
    # longest fragment first so "south korea" beats "korea", etc.
    for fragment in sorted(COUNTRY_CODES, key=len, reverse=True):
        if fragment in name:
            return COUNTRY_CODES[fragment]
    return None


def flag_path(team_name: str) -> Path | None:
    """Local path to the team's flag PNG, downloading once if needed."""
    code = code_for(team_name)
    if not code:
        return None
    FLAG_DIR.mkdir(parents=True, exist_ok=True)
    dest = FLAG_DIR / f"{code}.png"
    if dest.exists():
        return dest
    try:
        resp = requests.get(CDN.format(code=code), timeout=20)
        if resp.ok and len(resp.content) > 5_000:
            dest.write_bytes(resp.content)
            log.info("cached flag %s for %s", code, team_name)
            return dest
    except requests.RequestException as exc:
        log.warning("flag fetch failed for %s: %s", team_name, exc)
    return None
