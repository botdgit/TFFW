#!/usr/bin/env python3
"""One-shot Instagram Graph API setup.

Turns a short-lived Facebook token (from the Graph API Explorer) + your app
credentials into a PERMANENT Instagram publishing setup, written to .env:

    IG_USER_ID        the Instagram Business account id
    IG_ACCESS_TOKEN   a long-lived Page token (these do not expire)
    PUBLISHER=instagram

Usage:
    python scripts/ig_setup.py <APP_ID> <APP_SECRET> <SHORT_LIVED_TOKEN>

The short-lived token needs scopes: instagram_basic, instagram_content_publish,
pages_show_list, pages_read_engagement.
"""

import sys
from pathlib import Path

import requests

GRAPH = "https://graph.facebook.com/v21.0"
ENV = Path(__file__).resolve().parent.parent / ".env"


def _get(path: str, **params) -> dict:
    r = requests.get(f"{GRAPH}/{path}", params=params, timeout=30)
    data = r.json()
    if "error" in data:
        sys.exit(f"Meta API error on /{path}: {data['error'].get('message')}")
    return data


def main() -> None:
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    app_id, app_secret, short_token = sys.argv[1:4]

    # 1) short-lived -> long-lived user token (~60 days)
    long_user = _get("oauth/access_token", grant_type="fb_exchange_token",
                     client_id=app_id, client_secret=app_secret,
                     fb_exchange_token=short_token)["access_token"]

    # 2) pages this user manages — the Page token derived from a long-lived
    #    user token never expires
    pages = _get("me/accounts", access_token=long_user, fields="name,access_token,id").get("data", [])
    if not pages:
        sys.exit("No Facebook Pages found for this token. The Instagram account "
                 "must be linked to a Facebook Page you manage.")

    # 3) find the Page whose linked Instagram Business account we can publish to
    chosen = None
    for pg in pages:
        info = _get(pg["id"], access_token=pg["access_token"],
                    fields="instagram_business_account{id,username}")
        iba = info.get("instagram_business_account")
        if iba:
            chosen = (pg, iba)
            print(f"  Page '{pg['name']}' -> @{iba.get('username','?')} (ig id {iba['id']})")
            if len(pages) == 1:
                break
    if not chosen:
        sys.exit("None of your Pages has a linked Instagram Business/Creator account.")

    pg, iba = chosen
    ig_user_id, page_token = iba["id"], pg["access_token"]

    # 4) write to .env (create or replace the relevant keys)
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    updates = {"IG_USER_ID": ig_user_id, "IG_ACCESS_TOKEN": page_token, "PUBLISHER": "instagram"}
    out, seen = [], set()
    for ln in lines:
        key = ln.split("=", 1)[0] if "=" in ln else ""
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(ln)
    for key, val in updates.items():
        if key not in seen:
            out.append(f"{key}={val}")
    ENV.write_text("\n".join(out) + "\n")
    print(f"\n✓ Wrote IG_USER_ID and a permanent Page token to .env; PUBLISHER=instagram")
    print(f"  @{iba.get('username','?')} is ready to publish.")


if __name__ == "__main__":
    main()
