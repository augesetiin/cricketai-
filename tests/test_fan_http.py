"""
Integration tests for /fan and /fan/data HTTP endpoints (Phase 1)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server
from test_http import HttpTestBase


class TestFanHttp(HttpTestBase):
    def test_fan_dashboard_served(self):
        status, headers, body = self.request("GET", "/fan")
        self.assertEqual(status, 200)
        content_type = headers.get("Content-Type") or headers.get("content-type") or ""
        self.assertIn("text/html", content_type)
        html = body.decode("utf-8")
        self.assertIn("CricketStream Fan", html)
        self.assertIn("/fan/data", html)
        # Invariant: Never poll /live or /commands from fan application
        self.assertNotIn("/live", html)
        self.assertNotIn("/commands", html)

    def test_fan_data_endpoint_contract(self):
        status, data = self.get_json("/fan/data")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        self.assertIn("batting_team", data)
        self.assertIn("bowling_team", data)
        self.assertIn("score", data)
        self.assertIn("wickets", data)
        self.assertIn("overs", data)
        self.assertIn("run_rate", data)
        self.assertIn("batters", data)
        self.assertIn("bowler", data)
        self.assertIn("feed_fresh", data)
        self.assertIn("feed_source", data)
        self.assertIn("recent_balls", data)

    def test_fan_data_has_no_side_effects_on_overlay_or_live(self):
        # Seed an event in server._event_buffer
        with server._event_buffer_lock:
            server._event_buffer.append({"type": "wicket", "player": "Test Batter"})
            initial_count = len(server._event_buffer)

        # Call /fan/data multiple times
        status1, _ = self.get_json("/fan/data")
        status2, _ = self.get_json("/fan/data")
        self.assertEqual(status1, 200)
        self.assertEqual(status2, 200)

        # Confirm _event_buffer was NOT drained
        with server._event_buffer_lock:
            self.assertEqual(len(server._event_buffer), initial_count)
            server._event_buffer.clear()


if __name__ == "__main__":
    unittest.main()
