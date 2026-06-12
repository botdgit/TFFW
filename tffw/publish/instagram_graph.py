"""Direct Instagram publishing via the (free) Instagram Graph API.

Two-step container flow per Meta's docs:
  1. POST /{ig-user-id}/media          (image_url + caption)  -> creation_id
  2. POST /{ig-user-id}/media_publish  (creation_id)          -> media id

Requires an Instagram Business/Creator account linked to a Facebook Page
and a Meta app — see docs/DEPLOYMENT.md. Used when PUBLISHER=instagram.
"""

import time

from .. import config, db
from ..http_client import request
from ..logger import get_logger

log = get_logger("instagram")

GRAPH = "https://graph.facebook.com/v21.0"


def configured() -> bool:
    return bool(config.IG_USER_ID and config.IG_ACCESS_TOKEN)


def publish(caption: str, image_url: str, alt_text: str) -> str | None:
    """Publish an image post. Returns the IG media id or None."""
    create = request(
        "instagram",
        "POST",
        f"{GRAPH}/{config.IG_USER_ID}/media",
        params={
            "image_url": image_url,
            "caption": caption,
            "alt_text": alt_text,
            "access_token": config.IG_ACCESS_TOKEN,
        },
    )
    if create is None:
        return None
    container_id = create.json().get("id")
    if not container_id:
        db.log_error("instagram", f"no container id: {create.text[:200]}")
        return None

    # Wait for Meta to fetch + process the image before publishing.
    for _ in range(10):
        status = request(
            "instagram",
            "GET",
            f"{GRAPH}/{container_id}",
            params={"fields": "status_code", "access_token": config.IG_ACCESS_TOKEN},
        )
        code = status.json().get("status_code") if status is not None else None
        if code == "FINISHED":
            break
        if code == "ERROR":
            db.log_error("instagram", f"container {container_id} processing error")
            return None
        time.sleep(3)

    pub = request(
        "instagram",
        "POST",
        f"{GRAPH}/{config.IG_USER_ID}/media_publish",
        params={"creation_id": container_id, "access_token": config.IG_ACCESS_TOKEN},
    )
    if pub is None:
        return None
    media_id = pub.json().get("id")
    if media_id:
        log.info("instagram: published media %s", media_id)
    return media_id
