"""
Tests for Stage 5: Low-Data Mode & Conditional HTTP Caching
─────────────────────────────────────────────────────────
Verifies:
1. Server emits valid ETag headers on /fan/data, /fan/timeline, and /fan/commentary.
2. Server responds with HTTP 304 Not Modified when client sends matching If-None-Match.
3. 304 response has exactly 0 body bytes, proving bandwidth savings.
4. Mismatched or absent ETag returns 200 with full payload.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fan_commentary
import fan_engine
import server
from test_http import HttpTestBase


class TestLowDataMode(HttpTestBase):
    def setUp(self):
        with fan_engine._fan_lock:
            fan_engine._fan_cache["data"] = None
            fan_engine._fan_cache["ts"] = 0.0
        with server._db_lock, server._db() as conn:
            fan_commentary.init_commentary_db(conn)
            fan_engine.init_fan_db(conn)

    def test_01_fan_data_emits_etag_and_304(self):
        # 1. First request: initial load without If-None-Match
        status, headers, data = self.request("GET", "/fan/data")
        self.assertEqual(status, 200)
        etag = headers.get("ETag") or headers.get("etag")
        self.assertIsNotNone(etag)
        body_len = len(data)
        self.assertGreater(body_len, 100)

        # 2. Second request: conditional request with matching If-None-Match
        status2, headers2, data2 = self.request("GET", "/fan/data", headers={"If-None-Match": etag})
        self.assertEqual(status2, 304)
        cached_body_len = len(data2)
        self.assertEqual(cached_body_len, 0, "HTTP 304 must transfer 0 body bytes")

        # Bandwidth reduction verification: 100% savings on unchanged content
        savings_pct = (body_len - cached_body_len) / body_len * 100
        self.assertEqual(savings_pct, 100.0)

    def test_02_fan_timeline_emits_etag_and_304(self):
        # Initial request
        status, headers, data = self.request("GET", "/fan/timeline?innings=1")
        self.assertEqual(status, 200)
        etag = headers.get("ETag") or headers.get("etag")
        self.assertIsNotNone(etag)
        body_len = len(data)
        self.assertGreater(body_len, 20)

        # Matching ETag
        status2, _, data2 = self.request("GET", "/fan/timeline?innings=1", headers={"If-None-Match": etag})
        self.assertEqual(status2, 304)
        self.assertEqual(len(data2), 0)

    def test_03_fan_commentary_emits_etag_and_304(self):
        # Initial request
        status, headers, data = self.request("GET", "/fan/commentary?innings=1")
        self.assertEqual(status, 200)
        etag = headers.get("ETag") or headers.get("etag")
        self.assertIsNotNone(etag)
        body_len = len(data)
        self.assertGreater(body_len, 20)

        # Matching ETag
        status2, _, data2 = self.request("GET", "/fan/commentary?innings=1", headers={"If-None-Match": etag})
        self.assertEqual(status2, 304)
        self.assertEqual(len(data2), 0)

    def test_04_mismatched_etag_returns_200_with_full_body(self):
        status, _, data = self.request("GET", "/fan/data", headers={"If-None-Match": '"obsolete-etag-12345"'})
        self.assertEqual(status, 200)
        self.assertGreater(len(data), 100)


if __name__ == "__main__":
    unittest.main()
