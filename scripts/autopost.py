#!/usr/bin/env python3
"""Publish newly discovered Sports 803 feed entries through Buffer."""
from __future__ import annotations

import html
import json
import logging
import os
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

SITE_URL = "https://www.sport803.online/"
FEED_URL = "https://www.sport803.online/feeds/posts/default?alt=rss&max-results=100"
BUFFER_URL = "https://api.buffer.com"
ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / ".autopost-state.json"
DOCS_PATH = ROOT / "docs" / "index.html"
EVENTS_DATA_PATH = ROOT / "events.json"
LOG = logging.getLogger("autopost")


@dataclass(frozen=True)
class Event:
    """A single linked entry read from the publisher's RSS feed."""
    title: str
    url: str
    updated: str

    @property
    def fingerprint(self) -> str:
        return f"{self.url}::{self.updated}"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].split(":")[-1]


def parse_feed(xml_text: str) -> list[Event]:
    """Parse RSS or Atom entries, tolerating XML namespaces and malformed items."""
    root = ET.fromstring(xml_text)
    events: list[Event] = []
    for item in root.iter():
        if _local_name(item.tag) not in {"item", "entry"}:
            continue
        fields: dict[str, str] = {}
        link = ""
        for child in item:
            name = _local_name(child.tag)
            if name == "link":
                link = child.attrib.get("href", "") or (child.text or "").strip()
            elif name in {"title", "pubDate", "published", "updated", "id"}:
                fields[name] = " ".join("".join(child.itertext()).split())
        title = html.unescape(fields.get("title", "")).strip()
        link = html.unescape(link).strip()
        if title and _is_http_url(link):
            stamp = fields.get("updated") or fields.get("pubDate") or fields.get("published") or ""
            events.append(Event(title=title, url=link, updated=stamp))
    # Preserve feed order while removing duplicate URLs.
    unique: dict[str, Event] = {}
    for event in events:
        unique.setdefault(event.url, event)
    return list(unique.values())


def _is_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def fetch_events(session: requests.Session | None = None) -> list[Event]:
    """Fetch RSS with bounded timeouts; raise a useful error on bad responses."""
    client = session or requests.Session()
    response = client.get(FEED_URL, timeout=(10, 30), headers={"User-Agent": "sport803-autopost/1.0"})
    response.raise_for_status()
    return parse_feed(response.text)


class _OpenGraphParser(HTMLParser):
    """Collect the first non-empty value for each Open Graph metadata tag."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "meta":
            return
        values = dict(attrs)
        key = (values.get("property") or "").lower()
        content = (values.get("content") or "").strip()
        # Some Blogger themes emit a later, empty duplicate; keep the first useful value.
        if key.startswith("og:") and content:
            self.tags.setdefault(key, content)


def fetch_facebook_link_attachment(event: Event,
                                   session: requests.Session | None = None) -> dict[str, Any]:
    """Build Buffer's explicit Facebook link card from an article's Open Graph tags."""
    client = session or requests.Session()
    attachment: dict[str, Any] = {
        "url": event.url,
        "title": event.title,
        "description": "Live and upcoming sports events from Sports 803.",
    }
    try:
        response = client.get(event.url, timeout=(10, 25), headers={"User-Agent": "Mozilla/5.0 (compatible; Sports803Preview/1.0)"})
        response.raise_for_status()
        parser = _OpenGraphParser()
        parser.feed(response.text)
    except requests.RequestException as exc:
        LOG.warning("Could not read Open Graph tags for %s: %s; using fallback card details", event.url, exc)
        return attachment

    attachment["title"] = parser.tags.get("og:title") or event.title
    attachment["description"] = parser.tags.get("og:description") or attachment["description"]
    image_url = parser.tags.get("og:image", "")
    if _is_http_url(image_url):
        attachment["thumbnail"] = {"url": image_url}
    else:
        LOG.warning("No usable og:image for %s; Facebook link card will have no thumbnail", event.url)
    return attachment


def render_index(events: list[Event], generated_at: datetime | None = None) -> str:
    """Render a self-contained, escaped HTML list for GitHub Pages."""
    now = generated_at or datetime.now(timezone.utc)
    list_items = "\n".join(
        f'      <li><a href="{html.escape(event.url, quote=True)}" '
        f'target="_blank" rel="noopener noreferrer">{html.escape(event.title)}</a></li>'
        for event in events
    ) or '      <li class="empty">No events are currently listed. Check back soon.</li>'
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Today's live and upcoming sports events from Sports 803.">
  <meta property="og:type" content="website">
  <meta property="og:title" content="Today's Events · Sports 803">
  <meta property="og:description" content="Live and upcoming sports events, updated automatically.">
  <meta property="og:url" content="https://sport803.github.io/Today/">
  <title>Today's Events · Sports 803</title>
  <style>
    :root {{ color-scheme: dark; font-family: system-ui, sans-serif; background: #0b0d12; color: #f4f6fa; }}
    body {{ max-width: 860px; margin: 0 auto; padding: 2rem 1.25rem 4rem; }}
    header {{ border-bottom: 1px solid #343945; padding-bottom: 1.25rem; }}
    h1 {{ margin-bottom: .35rem; }} p, time {{ color: #a8b0bf; }}
    ol {{ list-style: none; padding: 0; }} li {{ margin: .7rem 0; }}
    li a {{ display: block; padding: 1rem; border: 1px solid #343945; border-radius: .7rem; color: #fff; text-decoration: none; }}
    li a:hover, li a:focus {{ border-color: #ef4444; background: #171a22; }}
    .empty {{ color: #a8b0bf; padding: 1rem 0; }} footer {{ margin-top: 2rem; color: #8991a0; font-size: .9rem; }}
  </style>
</head>
<body>
  <header>
    <p>SPORTS 803 · EVENT GUIDE</p>
    <h1>Today's Events</h1>
    <p>Live and upcoming listings from <a href="{SITE_URL}">sport803.online</a>.</p>
    <time datetime="{now.isoformat()}">Updated {now.strftime('%b %-d, %Y at %H:%M UTC')}</time>
  </header>
  <main><ol aria-label="Current sports events">
{list_items}
  </ol></main>
  <footer>Listings link to their original Sports 803 pages. Always check the source for the latest details.</footer>
</body>
</html>
'''


def load_state(path: Path = STATE_PATH) -> dict[str, dict[str, bool]]:
    """Load per-event, per-channel delivery state; an absent file is a clean start."""
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read posting state at {path}: {exc}") from exc


def select_pending_events(events: list[Event], state: dict[str, dict[str, bool]],
                          channel_names: tuple[str, ...], limit: int,
                          post_date: str | None = None) -> list[Event]:
    """Select unhandled events in source order, optionally restricted to an update date."""
    pending = [event for event in events
               if (post_date is None or event_date(event) == post_date)
               and not all(state.get(event.fingerprint, {}).get(name) for name in channel_names)]
    return pending[:limit]


def event_date(event: Event) -> str | None:
    """Return the feed item's calendar date, supporting ISO and RFC 822 timestamps."""
    stamp = event.updated.strip()
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(stamp)
        except (TypeError, ValueError, OverflowError):
            return None
    return parsed.date().isoformat()


def render_events_json(events: list[Event], generated_at: datetime | None = None) -> str:
    """Render the latest feed entries as safe JSON for the repository-root homepage."""
    now = generated_at or datetime.now(timezone.utc)
    ordered = sorted(events, key=lambda event: (event_date(event) or "", event.updated), reverse=True)
    return json.dumps({
        "updated_at": now.isoformat(),
        "events": [asdict(event) for event in ordered],
    }, ensure_ascii=False, indent=2) + "\n"


def save_state(state: dict[str, dict[str, bool]], path: Path = STATE_PATH) -> None:
    """Write state atomically so an interrupted run cannot truncate the file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _retry_delay(response: requests.Response | None, attempt: int) -> float:
    """Respect Buffer rate-limit reset/retry hints, otherwise use exponential backoff."""
    if response is not None:
        for name in ("Retry-After", "RateLimit-Reset", "X-RateLimit-Reset"):
            value = response.headers.get(name)
            if value:
                try:
                    numeric = float(value)
                    if name != "Retry-After" and numeric > time.time():
                        numeric -= time.time()
                    if numeric >= 0:
                        return min(numeric, 60.0)
                except ValueError:
                    pass
    return min(2**attempt, 30)


def buffer_create_post(text: str, channel_id: str, api_key: str,
                       session: requests.Session | None = None,
                       max_attempts: int = 5,
                       metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create one immediate Buffer post, retrying transient and rate-limit errors."""
    client = session or requests.Session()
    query = """mutation CreatePost($input: CreatePostInput!) {
      createPost(input: $input) {
        ... on PostActionSuccess { post { id text dueAt } }
        ... on MutationError { message }
      }
    }"""
    post_input: dict[str, Any] = {
        "text": text, "channelId": channel_id,
        "schedulingType": "automatic", "mode": "shareNow",
    }
    if metadata:
        post_input["metadata"] = metadata
    payload = {"query": query, "variables": {"input": post_input}}
    for attempt in range(max_attempts):
        response: requests.Response | None = None
        try:
            response = client.post(BUFFER_URL, json=payload, timeout=(10, 30), headers={
                "Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
            })
            if response.status_code == 429 or response.status_code >= 500:
                if attempt + 1 < max_attempts:
                    delay = _retry_delay(response, attempt)
                    LOG.warning("Buffer returned HTTP %s; retrying in %.1fs", response.status_code, delay)
                    time.sleep(delay)
                    continue
            response.raise_for_status()
            result = response.json()
        except requests.RequestException as exc:
            if attempt + 1 >= max_attempts:
                raise RuntimeError(f"Buffer request failed after {max_attempts} attempts: {exc}") from exc
            delay = _retry_delay(response, attempt)
            LOG.warning("Buffer request failed; retrying in %.1fs", delay)
            time.sleep(delay)
            continue
        except ValueError as exc:
            raise RuntimeError("Buffer returned invalid JSON") from exc

        if result.get("errors"):
            messages = "; ".join(error.get("message", "GraphQL error") for error in result["errors"])
            lowered = messages.lower()
            if ("rate limit" in lowered or "too many" in lowered) and attempt + 1 < max_attempts:
                delay = _retry_delay(response, attempt)
                LOG.warning("Buffer GraphQL rate limit; retrying in %.1fs", delay)
                time.sleep(delay)
                continue
            if "unauthorized" in lowered or "unauthenticated" in lowered:
                raise RuntimeError("Buffer authentication failed; verify BUFFER_API_KEY.")
            raise RuntimeError(f"Buffer GraphQL error: {messages}")
        action = (result.get("data") or {}).get("createPost") or {}
        if action.get("message"):
            raise RuntimeError(f"Buffer could not create the post: {action['message']}")
        post = action.get("post")
        if not post:
            raise RuntimeError("Buffer response did not include a created post.")
        return post
    raise RuntimeError("Buffer request exhausted its retry attempts")


def run(*, dry_run: bool = False) -> int:
    """Refresh Pages, post unhandled feed entries and persist successful deliveries."""
    events = fetch_events()
    DOCS_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOCS_PATH.write_text(render_index(events), encoding="utf-8")
    LOG.info("Wrote Pages index with %d feed entries", len(events))
    EVENTS_DATA_PATH.write_text(render_events_json(events), encoding="utf-8")
    LOG.info("Wrote root homepage event data with %d feed entries", len(events))
    if not events:
        LOG.info("Feed is empty; no social posts to send")
        return 0

    post_date = os.getenv("POST_DATE", "").strip() or None
    if post_date:
        try:
            if datetime.strptime(post_date, "%Y-%m-%d").date().isoformat() != post_date:
                raise ValueError
        except ValueError as exc:
            raise RuntimeError("POST_DATE must use YYYY-MM-DD format.") from exc
        LOG.info("Restricting Buffer posts to feed items updated on %s", post_date)

    state = load_state()
    first_run = not state
    key = os.getenv("BUFFER_API_KEY", "").strip()
    channels = {
        "facebook": os.getenv("BUFFER_FACEBOOK_CHANNEL_ID", "").strip(),
        "twitter": os.getenv("BUFFER_TWITTER_CHANNEL_ID", "").strip(),
    }
    if not dry_run:
        missing = [name for name, value in {"BUFFER_API_KEY": key, **{
            "BUFFER_FACEBOOK_CHANNEL_ID": channels["facebook"],
            "BUFFER_TWITTER_CHANNEL_ID": channels["twitter"],
        }}.items() if not value]
        if missing:
            raise RuntimeError("Missing required environment variable(s): " + ", ".join(missing))

    per_run_limit = max(1, int(os.getenv("MAX_POSTS_PER_RUN", "10")))
    if post_date and not dry_run:
        stale_count = 0
        for event in events:
            day = event_date(event)
            if day and day < post_date:
                state.setdefault(event.fingerprint, {}).update({name: True for name in channels})
                stale_count += 1
        if stale_count:
            save_state(state)
            LOG.info("Marked %d older feed items as handled without posting", stale_count)

    if first_run and not post_date:
        # Avoid queueing a historical backlog when the workflow is first enabled.
        # The feed is newest-first; older items remain in the public index only.
        for older_event in events[1:]:
            state[older_event.fingerprint] = {name: True for name in channels}
        pending = events[:1]
        if not dry_run:
            save_state(state)
        LOG.info("First run: bootstrapping from the newest feed item only")
    else:
        pending = select_pending_events(events, state, tuple(channels), per_run_limit, post_date)
    selected = pending[:per_run_limit]
    if not selected:
        LOG.info("No new or updated entries; nothing to post")
        return 0

    for event in selected:
        progress = state.setdefault(event.fingerprint, {})
        for name, channel in channels.items():
            if progress.get(name):
                continue
            text = f"{event.title}\n{event.url if name == 'facebook' else os.getenv('GITHUB_PAGES_URL', 'https://sport803.github.io/Today/')}"
            if dry_run:
                LOG.info("DRY RUN [%s] %s", name, text.replace("\n", " | "))
                continue
            metadata = None
            if name == "facebook":
                metadata = {
                    "facebook": {
                        "type": "post",
                        "linkAttachment": fetch_facebook_link_attachment(event),
                    }
                }
            post = buffer_create_post(text, channel, key, metadata=metadata)
            progress[name] = True
            save_state(state)
            LOG.info("Published %s post %s with shareNow for %s", name, post.get("id", "(no id)"), event.title)
    if not dry_run:
        # Keep state bounded without dropping recent outstanding fingerprints.
        if len(state) > 500:
            state = dict(list(state.items())[-500:])
        save_state(state)
    return 0


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="log planned posts without calling Buffer or saving state")
    args = parser.parse_args()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(levelname)s: %(message)s")
    try:
        return run(dry_run=args.dry_run or os.getenv("DRY_RUN", "").lower() in {"1", "true", "yes"})
    except (requests.RequestException, RuntimeError, ValueError, ET.ParseError) as exc:
        LOG.error("Autopost run failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
