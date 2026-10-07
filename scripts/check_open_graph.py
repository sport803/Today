#!/usr/bin/env python3
"""Check a source page's Open Graph metadata for social link previews."""
from __future__ import annotations
import argparse
from html.parser import HTMLParser
import sys
import requests

class OpenGraphParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: dict[str, str] = {}
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "meta":
            return
        values = dict(attrs)
        key = values.get("property") or values.get("name")
        if key and values.get("content"):
            self.tags[key.lower()] = values["content"].strip()

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Sports 803 article URL (defaults to the example event)", nargs="?",
                        default="https://www.sport803.online/2026/10/argentina-vs-benin-intl-friendlies-live.html")
    args = parser.parse_args()
    try:
        response = requests.get(args.url, timeout=(10, 30), headers={"User-Agent": "Mozilla/5.0 (compatible; Sports803PreviewCheck/1.0)"})
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"ERROR: Could not fetch page: {exc}", file=sys.stderr)
        return 2
    og = OpenGraphParser()
    og.feed(response.text)
    required = ("og:title", "og:description", "og:image", "og:url")
    missing = [key for key in required if not og.tags.get(key)]
    for key in required:
        print(f"{'OK' if og.tags.get(key) else 'MISSING'} {key}: {og.tags.get(key, '')}")
    if missing:
        print("Facebook may not produce a complete link preview; missing: " + ", ".join(missing), file=sys.stderr)
        return 1
    print("Open Graph metadata is present. Facebook's cache may still require refreshing in Meta Sharing Debugger.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
