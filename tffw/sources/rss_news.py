"""RSS news ingestion — BBC Sport, Sky Sports, Guardian and ESPN by default.

Feeds are fetched through the logged/retrying HTTP client and parsed with
the standard library (no extra dependencies). Only headlines/summaries are
used (facts + link attribution). No article images or video are ever
downloaded or reposted, which keeps the page clear of copyright problems —
all visuals are generated from our own templates.
"""

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from .. import config, db
from ..http_client import request
from ..logger import get_logger

log = get_logger("rss")

ATOM = "{http://www.w3.org/2005/Atom}"


def fetch_all() -> list[dict]:
    """Fetch all configured feeds, store new items as events, return the
    new items. Dedup happens on a hash of the item link."""
    new_items = []
    for feed_url in config.RSS_FEEDS:
        resp = request("rss", "GET", feed_url, headers={"User-Agent": "tffw-agent/1.0"})
        if resp is None:
            continue
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as exc:
            db.log_error("rss", f"{feed_url}: parse error {exc}")
            continue

        domain = urlparse(feed_url).netloc.replace("www.", "").replace("feeds.", "")
        for entry in _entries(root)[:40]:
            if not entry["link"] or not entry["title"]:
                continue
            item = {**entry, "domain": domain}
            key = "news:" + hashlib.sha256(entry["link"].encode()).hexdigest()[:24]
            if db.record_event("news_item", key, item, domain):
                new_items.append(item)

    log.info("rss: %d new items across %d feeds", len(new_items), len(config.RSS_FEEDS))
    return new_items


def _entries(root: ET.Element) -> list[dict]:
    """Parse both RSS 2.0 (<item>) and Atom (<entry>) feeds."""
    out = []
    for item in root.iter("item"):  # RSS 2.0
        summary = _strip_html(_text(item, "description"))[:500]
        out.append(
            {
                "title": _repair_title(_text(item, "title"), summary),
                "summary": summary,
                "link": _text(item, "link"),
                "published": _parse_date(_text(item, "pubDate")),
            }
        )
    if not out:  # Atom
        for entry in root.iter(f"{ATOM}entry"):
            link_el = entry.find(f"{ATOM}link")
            out.append(
                {
                    "title": _clean_title(_text(entry, f"{ATOM}title")),
                    "summary": _strip_html(_text(entry, f"{ATOM}summary"))[:500],
                    "link": link_el.get("href", "") if link_el is not None else "",
                    "published": _parse_date(_text(entry, f"{ATOM}updated")),
                }
            )
    return out


def _text(el: ET.Element, tag: str) -> str:
    child = el.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _clean_title(title: str) -> str:
    """Some feeds (ESPN) truncate titles with a trailing ellipsis."""
    return title.rstrip(". ").rstrip("…").strip()


def _repair_title(title: str, summary: str) -> str:
    """A title cut off mid-sentence ("Was ref right to show three ...")
    reads broken on a graphic. When the feed truncated it, prefer the
    summary's first sentence if it is a sane headline length."""
    truncated = title.rstrip().endswith(("...", "…"))
    cleaned = _clean_title(title)
    if not truncated or not summary:
        return cleaned
    first_sentence = summary.split(". ")[0].strip().rstrip(".")
    if 20 <= len(first_sentence) <= 140:
        return first_sentence
    return cleaned


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def _parse_date(raw: str) -> str:
    if raw:
        try:  # RFC 822 (RSS)
            return parsedate_to_datetime(raw).astimezone(timezone.utc).isoformat(timespec="seconds")
        except (TypeError, ValueError):
            pass
        try:  # ISO 8601 (Atom)
            return (
                datetime.fromisoformat(raw.replace("Z", "+00:00"))
                .astimezone(timezone.utc)
                .isoformat(timespec="seconds")
            )
        except ValueError:
            pass
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
