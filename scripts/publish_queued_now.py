#!/usr/bin/env python3
"""Switch existing Buffer queue posts to immediate publication (without duplicates)."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any

import requests

BUFFER_URL = "https://api.buffer.com"
LOG = logging.getLogger("publish_now")


def inspect_post(post_id: str, api_key: str,
                 session: requests.Session | None = None) -> dict[str, Any]:
    """Read the current status and available actions for a Buffer post."""
    query = """query InspectPost($input: PostInput!) {
      post(input: $input) {
        id status shareMode dueAt sentAt sharedNow channelService allowedActions
      }
    }"""
    client = session or requests.Session()
    try:
        response = client.post(
            BUFFER_URL,
            json={"query": query, "variables": {"input": {"id": post_id}}},
            timeout=(10, 30),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        response.raise_for_status()
        result = response.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"Buffer status request failed for post {post_id}: {exc}") from exc
    except ValueError as exc:
        raise RuntimeError("Buffer returned invalid JSON") from exc

    if result.get("errors"):
        message = "; ".join(error.get("message", "GraphQL error") for error in result["errors"])
        raise RuntimeError(f"Buffer status query failed for post {post_id}: {message}")
    post = (result.get("data") or {}).get("post")
    if not post:
        raise RuntimeError(f"Buffer did not return post {post_id}.")
    return post


def publish_now(post_id: str, text: str, api_key: str,
                session: requests.Session | None = None,
                metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Set an existing queued post's ShareMode to shareNow using editPost."""
    query = """mutation PublishPostNow($input: EditPostInput!) {
      editPost(input: $input) {
        ... on PostActionSuccess { post { id text dueAt } }
        ... on MutationError { message }
      }
    }"""
    client = session or requests.Session()
    post_input: dict[str, Any] = {"id": post_id, "text": text, "mode": "shareNow"}
    if metadata:
        post_input["metadata"] = metadata
    try:
        response = client.post(
            BUFFER_URL,
            json={"query": query, "variables": {"input": post_input}},
            timeout=(10, 30),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        response.raise_for_status()
        result = response.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"Buffer request failed for post {post_id}: {exc}") from exc
    except ValueError as exc:
        raise RuntimeError("Buffer returned invalid JSON") from exc

    if result.get("errors"):
        message = "; ".join(error.get("message", "GraphQL error") for error in result["errors"])
        raise RuntimeError(f"Buffer GraphQL error for post {post_id}: {message}")
    action = (result.get("data") or {}).get("editPost") or {}
    if action.get("message"):
        raise RuntimeError(f"Buffer could not publish post {post_id} now: {action['message']}")
    post = action.get("post")
    if not post:
        raise RuntimeError(f"Buffer did not confirm the update for post {post_id}.")
    return post


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facebook-post-id", required=True, help="Existing queued Facebook post ID")
    parser.add_argument("--twitter-post-id", required=True, help="Existing queued X/Twitter post ID")
    parser.add_argument("--facebook-text", required=True, help="Approved Facebook post text")
    parser.add_argument("--twitter-text", required=True, help="Approved X post text")
    parser.add_argument("--check-only", action="store_true", help="Read status and allowed actions without changing either post")
    args = parser.parse_args()
    api_key = os.getenv("BUFFER_API_KEY", "").strip()
    if not api_key:
        parser.error("BUFFER_API_KEY environment variable is required")
    if args.facebook_post_id == args.twitter_post_id:
        parser.error("Facebook and X post IDs must be different")

    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(levelname)s: %(message)s")
    try:
        with requests.Session() as session:
            posts = (
                ("Facebook", args.facebook_post_id, args.facebook_text, {"facebook": {"type": "post"}}),
                ("X", args.twitter_post_id, args.twitter_text, None),
            )
            if args.check_only:
                for channel, post_id, _text, _metadata in posts:
                    post = inspect_post(post_id, api_key, session=session)
                    LOG.info(
                        "%s post %s: status=%s shareMode=%s sharedNow=%s dueAt=%s sentAt=%s allowedActions=%s",
                        channel, post.get("id", post_id), post.get("status"), post.get("shareMode"),
                        post.get("sharedNow"), post.get("dueAt"), post.get("sentAt"),
                        ",".join(post.get("allowedActions") or []),
                    )
                return 0
            for channel, post_id, text, metadata in posts:
                post = publish_now(post_id, text, api_key, session=session, metadata=metadata)
                LOG.info("Set existing %s post %s to publish now", channel, post.get("id", post_id))
        return 0
    except RuntimeError as exc:
        LOG.error("Immediate publishing stopped: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
