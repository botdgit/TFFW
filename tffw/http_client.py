"""HTTP wrapper with retries, exponential backoff, rate-limit handling and
API-call logging. Every outbound request the agent makes goes through here
so the dashboard has a complete audit trail."""

import time

import requests

from . import db
from .logger import get_logger

log = get_logger("http")

RETRYABLE = {429, 500, 502, 503, 504}


def request(
    service: str,
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    params: dict | None = None,
    json_body: dict | None = None,
    timeout: int = 20,
    max_retries: int = 4,
) -> requests.Response | None:
    """Perform a request with backoff. Returns the Response on success
    (2xx) or None after exhausting retries. Never raises."""
    delay = 2.0
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.request(
                method, url, headers=headers, params=params, json=json_body, timeout=timeout
            )
        except requests.RequestException as exc:
            log.warning("%s %s failed (attempt %d): %s", service, url, attempt, exc)
            db.log_api(service, url, None, False, f"network error: {exc}")
            time.sleep(delay)
            delay *= 2
            continue

        if resp.ok:
            db.log_api(service, url, resp.status_code, True)
            return resp

        db.log_api(service, url, resp.status_code, False, resp.text[:300])
        if resp.status_code in RETRYABLE and attempt < max_retries:
            # Honour Retry-After when the API tells us how long to wait.
            wait = delay
            ra = resp.headers.get("Retry-After")
            if ra and ra.isdigit():
                wait = min(int(ra) + 1, 90)
            log.warning(
                "%s %s -> %d, retrying in %.0fs (attempt %d/%d)",
                service, url, resp.status_code, wait, attempt, max_retries,
            )
            time.sleep(wait)
            delay *= 2
            continue

        log.error("%s %s -> %d: %s", service, url, resp.status_code, resp.text[:200])
        if service != "rss":  # feed outages are routine; api_log already records them
            db.log_error(f"http:{service}", f"{method} {url} -> {resp.status_code}: {resp.text[:300]}")
        return None

    db.log_error(f"http:{service}", f"{method} {url} exhausted {max_retries} retries")
    return None


def get_json(service: str, url: str, *, headers: dict | None = None, params: dict | None = None) -> dict | None:
    resp = request(service, "GET", url, headers=headers, params=params)
    if resp is None:
        return None
    try:
        return resp.json()
    except ValueError:
        db.log_error(f"http:{service}", f"non-JSON response from {url}")
        return None
