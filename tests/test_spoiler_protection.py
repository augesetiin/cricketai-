"""
Tests for Stage 8: Spoiler Protection & Delay-Enforced Sync
────────────────────────────────────────────────────────
Verifies:
1. /fan/data with ?delay=X returns reconstructed match state at (now - X).
2. /fan/timeline with ?delay=X strictly excludes deliveries bowled after cutoff.
3. /fan/commentary with ?delay=X strictly excludes commentary generated after cutoff.
4. /fan/ask with delay parameter grounds AI responses only in pre-cutoff facts.
"""
import datetime
import json
import os
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fan_commentary
import fan_engine
import fan_qa
import server
from test_http import HttpTestBase


class TestSpoilerProtection(HttpTestBase):
    def setUp(self):
        with fan_engine._fan_lock:
            fan_engine._fan_cache["data"] = None
            fan_engine._fan_cache["ts"] = 0.0
        with server._db_lock, server._db() as conn:
            fan_commentary.init_commentary_db(conn)
            fan_engine.init_fan_db(conn)
            conn.execute("DELETE FROM fan_timeline")
            conn.execute("DELETE FROM fan_commentary")

    def _insert_test_deliveries(self, mid=None):
        if mid is None:
            mid = server.current_match_id()

        now = time.time()
        # Delivery 1: 120s ago (4 runs, score 4/0, 0.1 ov)
        t1 = datetime.datetime.fromtimestamp(now - 120, tz=datetime.timezone.utc).isoformat()
        # Delivery 2: 45s ago (4 runs, score 8/0, 0.2 ov)
        t2 = datetime.datetime.fromtimestamp(now - 45, tz=datetime.timezone.utc).isoformat()
        # Delivery 3: 5s ago (Wicket, score 8/1, 0.3 ov)
        t3 = datetime.datetime.fromtimestamp(now - 5, tz=datetime.timezone.utc).isoformat()

        with server._db_lock, server._db() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO fan_timeline (
                    match_id, innings, seq, event_id, revision, timeline_version,
                    over_number, over_idx, ball_in_over, legal_ball_in_over, is_legal,
                    token, outcome, runs_batter, runs_extras, total_runs,
                    is_wicket, batter_name, bowler_name, score_after, wickets_after,
                    overs_after, timestamp
                ) VALUES 
                (?, 1, 1, 'del_1', 1, 1, 1, 0, 1, 1, 1, '4', '4', 4, 0, 4, 0, 'Virat Kohli', 'J Bumrah', 4, 0, '0.1', ?),
                (?, 1, 2, 'del_2', 1, 1, 1, 0, 2, 2, 1, '4', '4', 4, 0, 4, 0, 'Virat Kohli', 'J Bumrah', 8, 0, '0.2', ?),
                (?, 1, 3, 'del_3', 1, 1, 1, 0, 3, 3, 1, 'W', 'W', 0, 0, 0, 1, 'Virat Kohli', 'J Bumrah', 8, 1, '0.3', ?)
            """, (mid, t1, mid, t2, mid, t3))

            cur.execute("""
                INSERT INTO fan_commentary (
                    commentary_id, match_id, innings, commentary_seq, source_timeline_seq,
                    change_seq, over_number, ball_in_over, event_type, headline, text, audio_text,
                    created_at, updated_at
                ) VALUES
                ('c1', ?, 1, 1, 1, 1, 1, 1, 'boundary', 'FOUR', 'Kohli drives for four', 'Kohli four', ?, ?),
                ('c2', ?, 1, 2, 2, 2, 1, 2, 'boundary', 'FOUR', 'Kohli punches for four', 'Kohli four', ?, ?),
                ('c3', ?, 1, 3, 3, 3, 1, 3, 'wicket', 'WICKET', 'Kohli caught at slip!', 'Kohli out', ?, ?)
            """, (mid, t1, t1, mid, t2, t2, mid, t3, t3))
            conn.commit()

    def test_01_fan_data_respects_spoiler_delay(self):
        self._insert_test_deliveries()

        # 30s delay: cutoff is (now - 30s). Ball 3 occurred at (now - 5s).
        # Therefore, at (now - 30s), score was 8/0 (0.2 ov) and NO wicket had fallen!
        status, delayed = self.get_json("/fan/data?delay=30")
        self.assertEqual(status, 200)
        self.assertEqual(delayed["score"], 8)
        self.assertEqual(delayed["wickets"], 0, "Delayed state must not leak the wicket that occurred 5s ago")
        self.assertEqual(delayed["overs"], "0.2")
        self.assertEqual(delayed["spoiler_delay_sec"], 30)

        # 90s delay: cutoff is (now - 90s). Only Ball 1 (120s ago) had occurred!
        status2, deep_delay = self.get_json("/fan/data?delay=90")
        self.assertEqual(status2, 200)
        self.assertEqual(deep_delay["score"], 4)
        self.assertEqual(deep_delay["wickets"], 0)
        self.assertEqual(deep_delay["overs"], "0.1")

    def test_02_fan_timeline_endpoint_respects_spoiler_delay(self):
        self._insert_test_deliveries()

        # Live timeline (delay=0): 3 deliveries
        status, res_live = self.get_json("/fan/timeline?innings=1&delay=0")
        self.assertEqual(status, 200)
        self.assertTrue(res_live["ok"])
        self.assertEqual(len(res_live["deliveries"]), 3)

        # Delayed timeline (delay=30): Ball 3 (5s ago) must be excluded!
        status2, res_delayed = self.get_json("/fan/timeline?innings=1&delay=30")
        self.assertEqual(status2, 200)
        self.assertTrue(res_delayed["ok"])
        self.assertEqual(len(res_delayed["deliveries"]), 2)
        seqs = [d["seq"] for d in res_delayed["deliveries"]]
        self.assertNotIn(3, seqs)

    def test_03_fan_commentary_endpoint_respects_spoiler_delay(self):
        self._insert_test_deliveries()

        # Live commentary (delay=0): 3 commentary items
        status, res_live = self.get_json("/fan/commentary?innings=1&delay=0")
        self.assertEqual(status, 200)
        self.assertTrue(res_live["ok"])
        self.assertEqual(len(res_live["commentary"]), 3)

        # Delayed commentary (delay=30): wicket commentary must be excluded
        status2, res_delayed = self.get_json("/fan/commentary?innings=1&delay=30")
        self.assertEqual(status2, 200)
        self.assertTrue(res_delayed["ok"])
        self.assertEqual(len(res_delayed["commentary"]), 2)
        headlines = [c["headline"] for c in res_delayed["commentary"]]
        self.assertNotIn("WICKET", headlines)

    def test_04_fan_ask_respects_spoiler_delay(self):
        self._insert_test_deliveries()
        fan_qa.get_global_rate_limiter().reset_client("127.0.0.1")

        # Live QA (delay=0): Question about wickets
        status, ans_live = self.post_json("/fan/ask", {
            "question": "How many wickets have fallen?",
            "delay": 0
        })
        self.assertEqual(status, 200)
        self.assertTrue(ans_live["ok"])
        self.assertIn("1", ans_live["answer"])

        # Reset rate limiter for the second call
        fan_qa.get_global_rate_limiter().reset_client("127.0.0.1")

        # Delayed QA (delay=30): at (now - 30s) 0 wickets had fallen
        status2, ans_delayed = self.post_json("/fan/ask", {
            "question": "How many wickets have fallen?",
            "delay": 30
        })
        self.assertEqual(status2, 200)
        self.assertTrue(ans_delayed["ok"])
        self.assertIn("0", ans_delayed["answer"])
        self.assertNotIn("1 wicket", ans_delayed["answer"])


if __name__ == "__main__":
    unittest.main()
