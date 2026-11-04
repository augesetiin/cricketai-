"""
Integration tests for GET /fan/timeline HTTP API (Phase 2 Stage 2)
──────────────────────────────────────────────────────────────────
Verifies:
- Empty timeline handling
- Default latest-deliveries pagination (limit 30)
- Incremental updates with since_seq
- Older history retrieval with before_seq
- Parameter validations (innings, limit, negative cursors, duplicates, conflicting cursors)
- Clamping of limits above 100
- Version mismatch detection and reset_required handling
- Delivery correction and revocation persistence
- Thread-safe concurrent access
- Strict non-interference with OBS and server event buffer
"""
import concurrent.futures
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fan_engine
import server
from test_http import HttpTestBase


def _insert_ball(conn, match_id=None, innings=1, seq=1, over_num=1, ball_in_over=1,
                 token="1", outcome="1", runs_batter=1, runs_extras=0, total_runs=1,
                 is_legal=1, is_wicket=0, score_after=1, wickets_after=0, overs_after="0.1",
                 timeline_version=1, revision=1, is_corrected=0, is_uncertain=0, is_adjustment=0):
    if match_id is None:
        match_id = server.current_match_id()
    conn.execute("""
        INSERT INTO fan_timeline (
            match_id, innings, seq, event_id, revision, timeline_version,
            over_number, over_idx, ball_in_over, legal_ball_in_over, is_legal,
            token, outcome, runs_batter, runs_extras, total_runs, extra_type,
            is_wicket, wicket_type, dismissal_desc, batter_name, non_striker_name,
            bowler_name, score_after, wickets_after, overs_after, is_boundary,
            boundary_type, is_corrected, is_uncertain, is_adjustment, adjustment_desc,
            timestamp
        ) VALUES (
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?
        )
    """, (
        match_id, innings, seq, f"del_{match_id}_i{innings}_s{seq}", revision, timeline_version,
        over_num, over_num - 1, ball_in_over, ball_in_over, is_legal,
        token, outcome, runs_batter, runs_extras, total_runs, None,
        is_wicket, None, None, "Batter A", "Batter B",
        "Bowler X", score_after, wickets_after, overs_after, 0,
        None, is_corrected, is_uncertain, is_adjustment, None,
        "2026-11-01T12:00:00Z"
    ))


class TestFanTimelineHttp(HttpTestBase):
    def setUp(self):
        super().setUp()
        with server._db_lock, server._db() as conn:
            fan_engine.init_fan_db(conn)
            conn.execute("DELETE FROM fan_timeline")
            conn.execute("DELETE FROM fan_reconciler_checkpoint")
            conn.commit()
        # Reset in-memory reconciler state if needed
        rec = fan_engine.get_fan_reconciler()
        with rec.lock:
            rec.timeline = []
            rec.seq = 0
            rec.timeline_version = 1
            rec.prev = {}

    def test_empty_timeline(self):
        status, data = self.get_json("/fan/timeline")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("total_deliveries"), 0)
        self.assertEqual(data.get("deliveries"), [])
        self.assertFalse(data.get("has_more"))
        self.assertFalse(data.get("reset_required"))
        self.assertIsNone(data.get("next_since_seq"))
        self.assertIsNone(data.get("next_before_seq"))
        self.assertEqual(data.get("innings"), 1)

    def test_latest_30_deliveries(self):
        with server._db_lock, server._db() as conn:
            for s in range(1, 41):
                over = (s - 1) // 6 + 1
                b = (s - 1) % 6 + 1
                _insert_ball(conn, seq=s, over_num=over, ball_in_over=b, score_after=s)
            conn.commit()

        status, data = self.get_json("/fan/timeline")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("total_deliveries"), 40)
        deliveries = data.get("deliveries", [])
        self.assertEqual(len(deliveries), 30)
        # Chronological order ascending (balls 11 to 40)
        seqs = [d["seq"] for d in deliveries]
        self.assertEqual(seqs, list(range(11, 41)))
        self.assertTrue(data.get("has_more"))
        self.assertEqual(data.get("next_since_seq"), 40)
        self.assertEqual(data.get("next_before_seq"), 11)

    def test_incremental_updates(self):
        with server._db_lock, server._db() as conn:
            for s in range(1, 41):
                over = (s - 1) // 6 + 1
                b = (s - 1) % 6 + 1
                _insert_ball(conn, seq=s, over_num=over, ball_in_over=b, score_after=s)
            conn.commit()

        # Polling when no new deliveries exist
        status, data = self.get_json("/fan/timeline?since_seq=40")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        self.assertEqual(len(data.get("deliveries", [])), 0)
        self.assertFalse(data.get("has_more"))
        self.assertEqual(data.get("next_since_seq"), 40)

        # 2 new deliveries occur
        with server._db_lock, server._db() as conn:
            _insert_ball(conn, seq=41, over_num=7, ball_in_over=5, score_after=41)
            _insert_ball(conn, seq=42, over_num=7, ball_in_over=6, score_after=42)
            conn.commit()

        status, data = self.get_json("/fan/timeline?since_seq=40")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        self.assertEqual(len(data.get("deliveries", [])), 2)
        seqs = [d["seq"] for d in data["deliveries"]]
        self.assertEqual(seqs, [41, 42])
        self.assertFalse(data.get("has_more"))
        self.assertEqual(data.get("next_since_seq"), 42)

    def test_older_page_retrieval(self):
        with server._db_lock, server._db() as conn:
            for s in range(1, 41):
                over = (s - 1) // 6 + 1
                b = (s - 1) % 6 + 1
                _insert_ball(conn, seq=s, over_num=over, ball_in_over=b, score_after=s)
            conn.commit()

        # Query older balls before seq 11 with limit 30
        status, data = self.get_json("/fan/timeline?before_seq=11&limit=30")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        deliveries = data.get("deliveries", [])
        self.assertEqual(len(deliveries), 10)
        # Should be seq 1 to 10 in chronological ascending order
        seqs = [d["seq"] for d in deliveries]
        self.assertEqual(seqs, list(range(1, 11)))
        self.assertFalse(data.get("has_more"))
        self.assertIsNone(data.get("next_before_seq"))

    def test_invalid_innings(self):
        for bad in ["3", "0", "-1", "abc"]:
            status, data = self.get_json(f"/fan/timeline?innings={bad}")
            self.assertEqual(status, 400)
            self.assertFalse(data.get("ok"))
            self.assertIn("error", data)

    def test_invalid_limit(self):
        for bad in ["0", "-5", "xyz"]:
            status, data = self.get_json(f"/fan/timeline?limit={bad}")
            self.assertEqual(status, 400)
            self.assertFalse(data.get("ok"))
            self.assertIn("error", data)

    def test_limit_above_100(self):
        with server._db_lock, server._db() as conn:
            for s in range(1, 121):
                over = (s - 1) // 6 + 1
                b = (s - 1) % 6 + 1
                _insert_ball(conn, seq=s, over_num=over, ball_in_over=b, score_after=s)
            conn.commit()

        status, data = self.get_json("/fan/timeline?limit=150")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        # Clamped to 100
        self.assertEqual(len(data.get("deliveries", [])), 100)
        self.assertTrue(data.get("has_more"))

    def test_negative_cursor(self):
        status, data = self.get_json("/fan/timeline?since_seq=-1")
        self.assertEqual(status, 400)
        self.assertFalse(data.get("ok"))

        status, data = self.get_json("/fan/timeline?before_seq=-10")
        self.assertEqual(status, 400)
        self.assertFalse(data.get("ok"))

    def test_duplicate_parameters(self):
        status, data = self.get_json("/fan/timeline?limit=10&limit=20")
        self.assertEqual(status, 400)
        self.assertFalse(data.get("ok"))
        self.assertIn("Ambiguous", data.get("error", ""))

        status, data = self.get_json("/fan/timeline?innings=1&innings=2")
        self.assertEqual(status, 400)
        self.assertFalse(data.get("ok"))

    def test_conflicting_cursors(self):
        status, data = self.get_json("/fan/timeline?since_seq=10&before_seq=20")
        self.assertEqual(status, 400)
        self.assertFalse(data.get("ok"))
        self.assertIn("Conflicting", data.get("error", ""))

    def test_version_mismatch_and_reset(self):
        mid = server.current_match_id()
        with server._db_lock, server._db() as conn:
            for s in range(1, 11):
                _insert_ball(conn, seq=s, timeline_version=2)
            conn.execute("""
                INSERT OR REPLACE INTO fan_reconciler_checkpoint
                (match_id, innings, timeline_version, updated)
                VALUES (?, 1, 2, '2026-11-01T12:00:00Z')
            """, (mid,))
            conn.commit()

        # Client queries with outdated version=1 and cursor since_seq=5
        status, data = self.get_json("/fan/timeline?version=1&since_seq=5")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("reset_required"))
        self.assertEqual(data.get("timeline_version"), 2)
        # Client cursor overridden; authoritative latest page returned
        self.assertEqual(len(data.get("deliveries", [])), 10)

    def test_corrected_and_revoked_deliveries(self):
        mid = server.current_match_id()
        with server._db_lock, server._db() as conn:
            for s in range(1, 7):
                _insert_ball(conn, seq=s, ball_in_over=s)
            conn.commit()

        # Correct ball 4
        with server._db_lock, server._db() as conn:
            conn.execute("""
                UPDATE fan_timeline
                SET revision=2, total_runs=4, runs_batter=4, is_corrected=1, is_boundary=1, boundary_type='four'
                WHERE match_id=? AND innings=1 AND seq=4
            """, (mid,))
            conn.commit()

        status, data = self.get_json("/fan/timeline")
        self.assertEqual(status, 200)
        deliveries = data.get("deliveries", [])
        ball_4 = next(d for d in deliveries if d["seq"] == 4)
        self.assertEqual(ball_4["revision"], 2)
        self.assertTrue(ball_4["is_corrected"])
        self.assertEqual(ball_4["total_runs"], 4)
        self.assertTrue(ball_4["is_boundary"])

        # Revoke ball 6 (e.g. undo)
        with server._db_lock, server._db() as conn:
            conn.execute("DELETE FROM fan_timeline WHERE match_id=? AND innings=1 AND seq=6", (mid,))
            conn.commit()

        status, data = self.get_json("/fan/timeline")
        self.assertEqual(status, 200)
        deliveries = data.get("deliveries", [])
        self.assertEqual(len(deliveries), 5)
        self.assertNotIn(6, [d["seq"] for d in deliveries])

    def test_concurrent_requests(self):
        with server._db_lock, server._db() as conn:
            for s in range(1, 35):
                _insert_ball(conn, seq=s)
            conn.commit()

        def fetch_page(query):
            s, d = self.get_json(f"/fan/timeline{query}")
            return s, d.get("ok")

        queries = [
            "",
            "?limit=10",
            "?since_seq=15",
            "?before_seq=25&limit=5",
            "?innings=1",
            "?version=1",
            "?limit=100",
            "?since_seq=30",
        ] * 4

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(fetch_page, queries))

        for status, ok in results:
            self.assertEqual(status, 200)
            self.assertTrue(ok)

    def test_obs_event_buffer_non_interference(self):
        with server._event_buffer_lock:
            server._event_buffer.append({"type": "wicket", "player": "Key Striker"})
            initial_count = len(server._event_buffer)

        # Issue multiple timeline API queries
        for q in ["", "?limit=5", "?innings=1"]:
            status, data = self.get_json(f"/fan/timeline{q}")
            self.assertEqual(status, 200)

        with server._event_buffer_lock:
            self.assertEqual(len(server._event_buffer), initial_count)
            server._event_buffer.clear()


if __name__ == "__main__":
    unittest.main()
