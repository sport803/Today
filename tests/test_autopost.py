"""Unit tests for feed parsing and safe static-page rendering."""
import sys
import unittest
from unittest.mock import Mock
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from autopost import Event, buffer_create_post, fetch_facebook_link_attachment, parse_feed, render_index, select_pending_events
from publish_queued_now import inspect_post, publish_now

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

    def test_pending_selection_keeps_newest_feed_item_first(self):
        newest = Event("Newest", "https://example.com/new", "2026-10-09")
        older = Event("Older", "https://example.com/old", "2026-10-08")
        selected = select_pending_events([newest, older], {}, ("facebook", "twitter"), 1)
        self.assertEqual(selected, [newest])

        state = {newest.fingerprint: {"facebook": True, "twitter": True}}
        self.assertEqual(select_pending_events([newest, older], state, ("facebook", "twitter"), 1), [older])

    def test_pending_selection_can_filter_to_rss_update_date(self):
        today = Event("Today", "https://example.com/today", "2026-10-09T02:00:00-07:00")
        yesterday = Event("Yesterday", "https://example.com/yesterday", "Thu, 08 Oct 2026 09:00:00 GMT")
        selected = select_pending_events(
            [today, yesterday], {}, ("facebook", "twitter"), 10, post_date="2026-10-09",
        )
        self.assertEqual(selected, [today])

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
            session=session, metadata={"facebook": {
                "type": "post",
                "linkAttachment": {
                    "url": "https://example.com/event", "title": "Event title",
                    "description": "Match details", "thumbnail": {"url": "https://example.com/card.jpg"},
                },
            }},
        )

        self.assertEqual(post["id"], "post-1")
        payload = session.post.call_args.kwargs["json"]
        self.assertEqual(
            payload["variables"]["input"]["metadata"],
            {"facebook": {
                "type": "post",
                "linkAttachment": {
                    "url": "https://example.com/event", "title": "Event title",
                    "description": "Match details", "thumbnail": {"url": "https://example.com/card.jpg"},
                },
            }},
        )
        self.assertEqual(payload["variables"]["input"]["mode"], "shareNow")

    def test_facebook_attachment_uses_first_nonempty_open_graph_values(self):
        response = Mock(status_code=200, headers={})
        response.text = '''<meta property="og:title" content="Card title">
          <meta property="og:description" content="Great match details">
          <meta property="og:image" content="https://example.com/card.jpg">
          <meta property="og:description" content="">'''
        session = Mock()
        session.get.return_value = response

        attachment = fetch_facebook_link_attachment(
            Event("Feed title", "https://example.com/event", "now"), session=session,
        )

        self.assertEqual(attachment, {
            "url": "https://example.com/event", "title": "Card title",
            "description": "Great match details", "thumbnail": {"url": "https://example.com/card.jpg"},
        })

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

    def test_inspect_post_is_read_only(self):
        response = Mock(status_code=200, headers={})
        response.json.return_value = {"data": {"post": {
            "id": "existing-1", "status": "scheduled", "shareMode": "shareNow",
            "allowedActions": ["viewPost"],
        }}}
        session = Mock()
        session.post.return_value = response

        post = inspect_post("existing-1", "test-key", session=session)

        self.assertEqual(post["status"], "scheduled")
        payload = session.post.call_args.kwargs["json"]
        self.assertIn("query InspectPost", payload["query"])
        self.assertNotIn("editPost", payload["query"])
        self.assertEqual(payload["variables"]["input"], {"id": "existing-1"})

if __name__ == "__main__":
    unittest.main()
