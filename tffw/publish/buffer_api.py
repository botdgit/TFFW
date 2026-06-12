"""Publish to Instagram through Buffer's GraphQL API.

Schema verified against Buffer's live API (June 2026):
    mutation createPost(input: CreatePostInput!) -> PostActionPayload
Auth: personal access token from https://publish.buffer.com/settings/api,
sent as a Bearer token. The endpoint can be overridden with
BUFFER_GRAPHQL_URL if Buffer moves it.
"""

import os

from .. import config, db
from ..http_client import request
from ..logger import get_logger

log = get_logger("buffer")

GRAPHQL_URL = os.environ.get("BUFFER_GRAPHQL_URL", "https://api.buffer.com/graphql")

CREATE_POST = """
mutation TffwCreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    __typename
    ... on PostActionSuccess { post { id status dueAt } }
    ... on InvalidInputError { message }
    ... on UnauthorizedError { message }
    ... on NotFoundError { message }
    ... on UnexpectedError { message }
    ... on LimitReachedError { message }
    ... on RestProxyError { message code }
  }
}
"""


def configured() -> bool:
    return bool(config.BUFFER_ACCESS_TOKEN and config.BUFFER_CHANNEL_ID)


def split_caption(caption: str) -> tuple[str, str | None]:
    """Move the hashtag line to a first comment (cleaner captions).
    Returns (caption_without_hashtags, hashtag_line_or_None)."""
    if "\n.\n" not in caption:
        return caption, None
    body, tail = caption.split("\n.\n", 1)
    tail_lines = tail.splitlines()
    hashtags = next((l for l in tail_lines if l.startswith("#")), None)
    rest = [l for l in tail_lines if l != hashtags]
    cleaned = body + ("\n.\n" + "\n".join(rest) if rest else "")
    return cleaned, hashtags


def publish(caption: str, image_url: str, alt_text: str, video_url: str | None = None) -> str | None:
    """Queue the post on the Instagram channel (image post, or reel when a
    video URL is provided). Hashtags go in the first comment. Returns the
    Buffer post id or None on failure."""
    # firstComment needs a paid Buffer plan — keep hashtags in the caption
    if video_url:
        assets = [{"video": {"url": video_url, "thumbnailUrl": image_url}}]
        ig_meta = {"type": "reel", "shouldShareToFeed": True}
    else:
        assets = [{"image": {"url": image_url, "metadata": {"altText": alt_text}}}]
        ig_meta = {"type": "post", "shouldShareToFeed": True}
    variables = {
        "input": {
            "channelId": config.BUFFER_CHANNEL_ID,
            "schedulingType": "automatic",
            "mode": "shareNow",
            "text": caption,
            "assets": assets,
            "metadata": {"instagram": ig_meta},
            "source": "tffw-agent",
        }
    }
    resp = request(
        "buffer",
        "POST",
        GRAPHQL_URL,
        headers={
            "Authorization": f"Bearer {config.BUFFER_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        json_body={"query": CREATE_POST, "variables": variables},
    )
    if resp is None:
        return None
    try:
        payload = resp.json()
    except ValueError:
        db.log_error("buffer", "non-JSON response")
        return None

    result = (payload.get("data") or {}).get("createPost") or {}
    if result.get("__typename") == "PostActionSuccess":
        post_id = result["post"]["id"]
        log.info("buffer: queued post %s", post_id)
        return post_id

    message = result.get("message") or str(payload.get("errors", payload))[:300]
    db.log_error("buffer", f"createPost failed: {message}")
    log.error("buffer createPost failed: %s", message)
    return None


def publish_story(image_url: str) -> str | None:
    """Post a 9:16 card to Instagram Stories."""
    variables = {
        "input": {
            "channelId": config.BUFFER_CHANNEL_ID,
            "schedulingType": "automatic",
            "mode": "shareNow",
            "text": "",
            "assets": [{"image": {"url": image_url, "metadata": {"altText": "story card"}}}],
            "metadata": {"instagram": {"type": "story", "shouldShareToFeed": False}},
            "source": "tffw-agent",
        }
    }
    resp = request(
        "buffer", "POST", GRAPHQL_URL,
        headers={
            "Authorization": f"Bearer {config.BUFFER_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        json_body={"query": CREATE_POST, "variables": variables},
    )
    if resp is None:
        return None
    result = (resp.json().get("data") or {}).get("createPost") or {}
    if result.get("__typename") == "PostActionSuccess":
        return result["post"]["id"]
    db.log_error("buffer", f"story failed: {result.get('message', '?')}")
    return None
