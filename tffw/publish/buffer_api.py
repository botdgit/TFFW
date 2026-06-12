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

GRAPHQL_URL = os.environ.get("BUFFER_GRAPHQL_URL", "https://graph.buffer.com/")

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


def publish(caption: str, image_url: str, alt_text: str) -> str | None:
    """Queue the post on the Instagram channel. Returns the Buffer post id
    or None on failure."""
    variables = {
        "input": {
            "channelId": config.BUFFER_CHANNEL_ID,
            "schedulingType": "automatic",
            "mode": "addToQueue",
            "text": caption,
            "assets": [
                {"image": {"url": image_url, "metadata": {"altText": alt_text}}}
            ],
            "metadata": {
                "instagram": {"type": "post", "shouldShareToFeed": True}
            },
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
