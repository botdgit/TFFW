"""Direct Instagram publishing via the (free) Instagram Graph API.

This is the zero-cost production publisher: no third-party scheduler, no
free-tier post cap. Instagram's own limit is 50 published posts per rolling
24h — far above anything we post.

Container flow per Meta's docs:
  1. POST /{ig-user-id}/media          (image_url|video_url + caption)  -> creation_id
  2. poll  /{creation_id}?fields=status_code  until FINISHED (videos take longer)
  3. POST /{ig-user-id}/media_publish  (creation_id)                    -> media id

Supports feed images, Reels (video) and Stories — a full Buffer replacement.

Requires an Instagram Business/Creator account linked to a Facebook Page and
a Meta app long-lived token with instagram_basic + instagram_content_publish
(see docs/DEPLOYMENT.md). Enabled with PUBLISHER=instagram.
"""

import time

from .. import config, db
from ..http_client import request
from ..logger import get_logger

log = get_logger("instagram")

GRAPH = "https://graph.facebook.com/v21.0"


def configured() -> bool:
    return bool(config.IG_USER_ID and config.IG_ACCESS_TOKEN)


def _create_container(params: dict) -> str | None:
    params["access_token"] = config.IG_ACCESS_TOKEN
    create = request("instagram", "POST", f"{GRAPH}/{config.IG_USER_ID}/media", params=params)
    if create is None:
        return None
    container_id = create.json().get("id")
    if not container_id:
        db.log_error("instagram", f"no container id: {create.text[:200]}")
    return container_id


def _await_ready(container_id: str, *, attempts: int, wait: float) -> bool:
    """Meta fetches/transcodes the asset before it can be published. Images
    are near-instant; Reels need several seconds of transcoding."""
    for _ in range(attempts):
        status = request(
            "instagram", "GET", f"{GRAPH}/{container_id}",
            params={"fields": "status_code", "access_token": config.IG_ACCESS_TOKEN},
        )
        code = status.json().get("status_code") if status is not None else None
        if code == "FINISHED":
            return True
        if code == "ERROR":
            db.log_error("instagram", f"container {container_id} processing error")
            return False
        time.sleep(wait)
    db.log_error("instagram", f"container {container_id} not ready after {attempts} polls")
    return False


def _publish_container(container_id: str) -> str | None:
    pub = request(
        "instagram", "POST", f"{GRAPH}/{config.IG_USER_ID}/media_publish",
        params={"creation_id": container_id, "access_token": config.IG_ACCESS_TOKEN},
    )
    if pub is None:
        return None
    media_id = pub.json().get("id")
    if media_id:
        log.info("instagram: published media %s", media_id)
    return media_id


def publish(caption: str, image_url: str, alt_text: str, video_url: str | None = None) -> str | None:
    """Publish a feed post — a Reel when a video URL is supplied, otherwise a
    single image. Returns the IG media id or None. (Instagram's API has no
    alt-text field on creation, so alt_text is unused but kept for parity.)"""
    if video_url:
        params = {"media_type": "REELS", "video_url": video_url,
                  "caption": caption, "share_to_feed": "true"}
        attempts, wait = 30, 4  # transcoding can take ~a minute
    else:
        params = {"image_url": image_url, "caption": caption}
        attempts, wait = 12, 3
    container_id = _create_container(params)
    if not container_id or not _await_ready(container_id, attempts=attempts, wait=wait):
        return None
    return _publish_container(container_id)


def publish_story(image_url: str) -> str | None:
    """Post a 9:16 card to Instagram Stories."""
    container_id = _create_container({"image_url": image_url, "media_type": "STORIES"})
    if not container_id or not _await_ready(container_id, attempts=12, wait=3):
        return None
    return _publish_container(container_id)
