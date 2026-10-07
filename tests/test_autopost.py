"""Unit tests for feed parsing and safe static-page rendering."""
import sys
import unittest
from unittest.mock import Mock
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from autopost import Event, buffer_create_post, parse_feed, render_index
from publish_queued_now import publish_now

class FeedTests(unittest.TestCase):
    def test_rss_entries_and_duplicate_urls(self):
        xml = '''<rss><channel>
          <item><title>Alpha &amp; Beta</title><link>https://example.com/a</link><pubDate>Mon, 05 Oct 2026 10:00:00 GMT</pubDate></item>
          <item><title>Duplicate</title><link>https://example.com/a</link></item>
          <item><title>Invalid</title><link>javascript:alert(1)</link></item>
        </channel></rss>'''
        events = parse_feed(xml)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].title, "Alpha & Beta")
        self.assertEqual(events[0].url, "https://example.com/a")

    def test_atom_namespaced_links(self):
        xml = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
          <title>Event</title><link rel="alternate" href="https://example.com/event"/><updated>2026-10-06T12:00:00Z</updated>
        </entry></feed>'''
        event, = parse_feed(xml)
        self.assertEqual(event.title, "Event")
        self.assertEqual(event.updated, "2026-10-06T12:00:00Z")

    def test_index_escapes_untrusted_content_and_links_to_original(self):
        page = render_index([Event('<script>alert("x")</script>', 'https://example.com/?a=1&b=2', 'today')],
                            datetime(2026, 10, 7, tzinfo=timezone.utc))
        self.assertIn('&lt;script&gt;', page)
        self.assertNotIn('<script>alert', page)
        self.assertIn('https://example.com/?a=1&amp;b=2', page)
        self.assertIn('aria-label="Current sports events"', page)

    def test_empty_page_message(self):
        self.assertIn("No events are currently listed", render_index([]))

    def test_buffer_facebook_post_includes_standard_post_type(self):
        response = Mock(status_code=200, headers={})
        response.json.return_value = {"data": {"createPost": {"post": {"id": "post-1"}}}}
        session = Mock()
        session.post.return_value = response

        post = buffer_create_post(
            "Event title\nhttps://example.com/event", "facebook-channel", "test-key",
            session=session, metadata={"facebook": {"type": "post"}},
        )

        self.assertEqual(post["id"], "post-1")
        payload = session.post.call_args.kwargs["json"]
        self.assertEqual(
            payload["variables"]["input"]["metadata"],
            {"facebook": {"type": "post"}},
        )

    def test_publish_now_edits_existing_post_instead_of_creating_one(self):
        response = Mock(status_code=200, headers={})
        response.json.return_value = {"data": {"editPost": {"post": {"id": "existing-1"}}}}
        session = Mock()
        session.post.return_value = response

        post = publish_now(
            "existing-1", "Approved text", "test-key", session=session,
            metadata={"facebook": {"type": "post"}},
        )

        self.assertEqual(post["id"], "existing-1")
        payload = session.post.call_args.kwargs["json"]
        self.assertIn("editPost", payload["query"])
        self.assertNotIn("createPost", payload["query"])
        self.assertEqual(payload["variables"]["input"], {
            "id": "existing-1", "text": "Approved text", "mode": "shareNow",
            "metadata": {"facebook": {"type": "post"}},
        })

if __name__ == "__main__":
    unittest.main()
