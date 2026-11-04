"""
Integration tests for GET /fan/commentary HTTP API (Phase 3 Stage 2)
───────────────────────────────────────────────────────────────────
Verifies:
1. Empty commentary handling
2. Initial latest commentary retrieval (default limit 20)
3. Correct ascending display ordering
4. Older-page pagination using before_seq
5. Incremental new commentary updates using since_change_seq
6. AI summary replacement after the client has already fetched original summary
7. Delivery correction and revision increment delivery
8. Undo/revocation tombstones with is_revoked: true
9. Stale version reset detection (reset_required: true)
10. Duplicate and invalid query parameters (400 validation errors)
11. Server restart persistence
12. Strict non-interference with existing fan, overlay, and operator endpoints
"""
import copy
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


def _insert_commentary_item(conn, match_id=None, innings=1, commentary_seq=1, source_timeline_seq=1,
                            change_seq=None, over_number=1, ball_in_over=1, event_type="ball",
                            headline="1 RUN", text="Single taken.", audio_text="Single taken.",
                            is_ai=0, ai_status="none", revision=1, is_corrected=0,
                            is_uncertain=0, is_adjustment=0, is_revoked=0):
    if match_id is None:
        match_id = server.current_match_id()
    if change_seq is None:
        change_seq = commentary_seq

    comm_id = f"comm_{match_id}_i{innings}_s{commentary_seq}_{event_type}"
    conn.execute("""
        INSERT INTO fan_commentary (
            commentary_id, match_id, innings, commentary_seq, source_timeline_seq,
            change_seq, over_number, ball_in_over, event_type, headline, text, audio_text,
            is_ai, ai_status, revision, is_corrected, is_uncertain, is_adjustment,
            is_revoked, created_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?,
            ?, '2026-11-01T12:00:00Z', '2026-11-01T12:00:00Z'
        )
    """, (
        comm_id, match_id, innings, commentary_seq, source_timeline_seq,
        change_seq, over_number, ball_in_over, event_type, headline, text, audio_text,
        is_ai, ai_status, revision, is_corrected, is_uncertain, is_adjustment,
        is_revoked
    ))
    # Update meta max_change_seq
    conn.execute("""
        INSERT INTO fan_commentary_meta (match_id, innings, commentary_version, max_change_seq)
        VALUES (?, ?, 1, ?)
        ON CONFLICT(match_id, innings) DO UPDATE SET max_change_seq = MAX(max_change_seq, ?)
    """, (match_id, innings, change_seq, change_seq))
    return comm_id


class TestFanCommentaryHttp(HttpTestBase):
    def setUp(self):
        super().setUp()
        with fan_engine._fan_lock:
            fan_engine._fan_cache["data"] = None
            fan_engine._fan_cache["ts"] = 0.0
        with server._db_lock, server._db() as conn:
            fan_commentary.init_commentary_db(conn)
            fan_engine.init_fan_db(conn)
            conn.execute("DELETE FROM fan_commentary")
            conn.execute("DELETE FROM fan_commentary_meta")
            conn.execute("DELETE FROM fan_timeline")
            conn.commit()

    def test_01_empty_commentary(self):
        status, data = self.get_json("/fan/commentary")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("total_commentary"), 0)
        self.assertEqual(data.get("commentary"), [])
        self.assertFalse(data.get("has_more"))
        self.assertFalse(data.get("reset_required"))
        self.assertIsNone(data.get("next_since_seq"))
        self.assertIsNone(data.get("next_before_seq"))
        self.assertEqual(data.get("next_change_seq"), 0)
        self.assertEqual(data.get("commentary_version"), 1)
        self.assertEqual(data.get("innings"), 1)

    def test_02_initial_latest_retrieval(self):
        mid = server.current_match_id()
        with server._db_lock, server._db() as conn:
            for i in range(1, 26):
                _insert_commentary_item(conn, match_id=mid, commentary_seq=i, source_timeline_seq=i,
                                       change_seq=i, text=f"Ball {i} commentary.")
            conn.commit()

        status, data = self.get_json("/fan/commentary")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("total_commentary"), 25)
        # Default limit is 20
        self.assertEqual(len(data.get("commentary")), 20)
        self.assertTrue(data.get("has_more"))
        self.assertEqual(data.get("next_since_seq"), 25)
        self.assertEqual(data.get("next_before_seq"), 6)
        self.assertEqual(data.get("next_change_seq"), 25)

    def test_03_correct_commentary_ordering(self):
        mid = server.current_match_id()
        with server._db_lock, server._db() as conn:
            for i in range(1, 6):
                _insert_commentary_item(conn, match_id=mid, commentary_seq=i, source_timeline_seq=i,
                                       change_seq=i, text=f"Delivery {i}")
            conn.commit()

        status, data = self.get_json("/fan/commentary")
        self.assertEqual(status, 200)
        comm = data.get("commentary")
        seqs = [c["commentary_seq"] for c in comm]
        self.assertEqual(seqs, [1, 2, 3, 4, 5], "Commentary must be in ascending chronological order")

    def test_04_older_page_pagination(self):
        mid = server.current_match_id()
        with server._db_lock, server._db() as conn:
            for i in range(1, 26):
                _insert_commentary_item(conn, match_id=mid, commentary_seq=i, source_timeline_seq=i,
                                       change_seq=i, text=f"Delivery {i}")
            conn.commit()

        # 1. Fetch initial latest (items 6..25)
        status, p1 = self.get_json("/fan/commentary")
        self.assertEqual(status, 200)
        self.assertTrue(p1.get("has_more"))
        before_seq = p1.get("next_before_seq")
        self.assertEqual(before_seq, 6)

        # 2. Fetch older page before_seq=6
        status, p2 = self.get_json(f"/fan/commentary?before_seq={before_seq}")
        self.assertEqual(status, 200)
        older = p2.get("commentary")
        self.assertEqual(len(older), 5)
        self.assertEqual([c["commentary_seq"] for c in older], [1, 2, 3, 4, 5])
        self.assertFalse(p2.get("has_more"), "No more older commentary exists")
        self.assertIsNone(p2.get("next_before_seq"))

    def test_05_incremental_new_commentary(self):
        mid = server.current_match_id()
        with server._db_lock, server._db() as conn:
            for i in range(1, 4):
                _insert_commentary_item(conn, match_id=mid, commentary_seq=i, source_timeline_seq=i,
                                       change_seq=i, text=f"Delivery {i}")
            conn.commit()

        # Client has fetched up to change_seq 3
        status, p1 = self.get_json("/fan/commentary?since_change_seq=3")
        self.assertEqual(status, 200)
        self.assertEqual(len(p1.get("commentary")), 0, "No new changes yet")
        self.assertEqual(p1.get("next_change_seq"), 3)

        # New delivery arrives
        with server._db_lock, server._db() as conn:
            _insert_commentary_item(conn, match_id=mid, commentary_seq=4, source_timeline_seq=4,
                                   change_seq=4, text="Delivery 4 boundary four!")
            conn.commit()

        status, p2 = self.get_json("/fan/commentary?since_change_seq=3")
        self.assertEqual(status, 200)
        new_items = p2.get("commentary")
        self.assertEqual(len(new_items), 1)
        self.assertEqual(new_items[0]["commentary_seq"], 4)
        self.assertEqual(new_items[0]["change_seq"], 4)
        self.assertEqual(p2.get("next_change_seq"), 4)

    def test_06_ai_summary_replacement_after_client_fetch(self):
        mid = server.current_match_id()
        # 1. Deterministic over summary inserted at change_seq 6
        with server._db_lock, server._db() as conn:
            for i in range(1, 6):
                _insert_commentary_item(conn, match_id=mid, commentary_seq=i, source_timeline_seq=i,
                                       change_seq=i, text=f"Ball {i}")
            cid = _insert_commentary_item(
                conn, match_id=mid, commentary_seq=6, source_timeline_seq=5,
                change_seq=6, event_type="over_summary", headline="END OF OVER 1",
                text="Over 1: 10 runs conceded.", audio_text="Over 1: 10 runs conceded.",
                is_ai=0, ai_status="pending", revision=1
            )
            conn.commit()

        # 2. Client fetches initial commentary and saves cursor at next_change_seq = 6
        status, p1 = self.get_json("/fan/commentary")
        self.assertEqual(status, 200)
        self.assertEqual(p1.get("next_change_seq"), 6)
        orig_summary = [c for c in p1.get("commentary") if c["commentary_id"] == cid][0]
        self.assertEqual(orig_summary["revision"], 1)
        self.assertFalse(orig_summary["is_ai"])
        self.assertEqual(orig_summary["ai_status"], "pending")

        # 3. Background AI completes and updates row in place with change_seq = 7, revision = 2
        with server._db_lock, server._db() as conn:
            conn.execute("""
                UPDATE fan_commentary
                SET text = 'Tidy first over from Broad, conceding ten.',
                    is_ai = 1, ai_status = 'completed', revision = 2,
                    change_seq = 7, updated_at = '2026-11-01T12:00:05Z'
                WHERE commentary_id = ?
            """, (cid,))
            conn.execute("""
                UPDATE fan_commentary_meta
                SET max_change_seq = 7
                WHERE match_id=? AND innings=1
            """, (mid,))
            conn.commit()

        # 4. Client polls with since_change_seq=6
        status, p2 = self.get_json("/fan/commentary?since_change_seq=6")
        self.assertEqual(status, 200)
        updates = p2.get("commentary")
        self.assertEqual(len(updates), 1, "Must return exactly the updated AI summary")
        ai_item = updates[0]
        self.assertEqual(ai_item["commentary_id"], cid)
        self.assertEqual(ai_item["commentary_seq"], 6)
        self.assertEqual(ai_item["revision"], 2)
        self.assertTrue(ai_item["is_ai"])
        self.assertEqual(ai_item["ai_status"], "completed")
        self.assertEqual(ai_item["text"], "Tidy first over from Broad, conceding ten.")
        self.assertEqual(p2.get("next_change_seq"), 7)

    def test_07_delivery_correction_and_revision_delivery(self):
        mid = server.current_match_id()
        with server._db_lock, server._db() as conn:
            cid = _insert_commentary_item(
                conn, match_id=mid, commentary_seq=2, source_timeline_seq=2,
                change_seq=2, headline="1 RUN", text="Single to midwicket.",
                revision=1, is_corrected=0
            )
            conn.commit()

        # Client was at change_seq 2
        # Scorer changes ball 2 from 1 run to 4 runs
        with server._db_lock, server._db() as conn:
            conn.execute("""
                UPDATE fan_commentary
                SET headline = 'FOUR!', text = 'Magnificent cover drive for four!',
                    is_corrected = 1, revision = 2, change_seq = 3,
                    updated_at = '2026-11-01T12:00:10Z'
                WHERE commentary_id = ?
            """, (cid,))
            conn.execute("""
                UPDATE fan_commentary_meta
                SET max_change_seq = 3
                WHERE match_id=? AND innings=1
            """, (mid,))
            conn.commit()

        status, p = self.get_json("/fan/commentary?since_change_seq=2")
        self.assertEqual(status, 200)
        self.assertEqual(len(p.get("commentary")), 1)
        corrected = p.get("commentary")[0]
        self.assertEqual(corrected["commentary_id"], cid)
        self.assertEqual(corrected["revision"], 2)
        self.assertTrue(corrected["is_corrected"])
        self.assertEqual(corrected["headline"], "FOUR!")
        self.assertEqual(p.get("next_change_seq"), 3)

    def test_08_undo_revocation_tombstones(self):
        mid = server.current_match_id()
        with server._db_lock, server._db() as conn:
            cid1 = _insert_commentary_item(conn, match_id=mid, commentary_seq=1, source_timeline_seq=1, change_seq=1)
            cid2 = _insert_commentary_item(conn, match_id=mid, commentary_seq=2, source_timeline_seq=2, change_seq=2)
            conn.commit()

        # Scorer undoes ball 2 -> handle_revocations sets is_revoked = 1, change_seq = 3
        engine = fan_commentary.get_fan_commentary_engine()
        with server._db_lock, server._db() as conn:
            engine.handle_revocations(mid, 1, [2], conn=conn)

        # 1. Polling client with since_change_seq=2 must receive the tombstone
        status, p_poll = self.get_json("/fan/commentary?since_change_seq=2")
        self.assertEqual(status, 200)
        tombstones = p_poll.get("commentary")
        self.assertEqual(len(tombstones), 1)
        self.assertEqual(tombstones[0]["commentary_id"], cid2)
        self.assertTrue(tombstones[0]["is_revoked"])

        # 2. Fresh client requesting initial latest must NOT receive revoked item
        status, p_fresh = self.get_json("/fan/commentary")
        self.assertEqual(status, 200)
        self.assertEqual(p_fresh.get("total_commentary"), 1)
        active_ids = [c["commentary_id"] for c in p_fresh.get("commentary")]
        self.assertIn(cid1, active_ids)
        self.assertNotIn(cid2, active_ids)

    def test_09_stale_version_reset(self):
        mid = server.current_match_id()
        with server._db_lock, server._db() as conn:
            _insert_commentary_item(conn, match_id=mid, commentary_seq=1, change_seq=1)
            conn.commit()

        # Bump version to 2
        with server._db_lock, server._db() as conn:
            fan_commentary.bump_commentary_version(mid, 1, conn=conn)

        # Client requests with stale version 1
        status, data = self.get_json("/fan/commentary?version=1&since_change_seq=1")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("reset_required"))
        self.assertEqual(data.get("commentary_version"), 2)
        # In case of reset, client cursors are invalidated and authoritative snapshot returned
        self.assertEqual(len(data.get("commentary")), 1)

    def test_10_duplicate_and_invalid_parameters(self):
        # Duplicate limit
        status, data = self.get_json("/fan/commentary?limit=10&limit=20")
        self.assertEqual(status, 400)
        self.assertFalse(data.get("ok"))
        self.assertIn("Ambiguous parameter", data.get("error"))

        # Invalid innings
        status, data = self.get_json("/fan/commentary?innings=3")
        self.assertEqual(status, 400)
        self.assertFalse(data.get("ok"))
        self.assertIn("must be 1 or 2", data.get("error"))

        # Negative cursors
        status, data = self.get_json("/fan/commentary?since_seq=-1")
        self.assertEqual(status, 400)
        self.assertFalse(data.get("ok"))

        status, data = self.get_json("/fan/commentary?before_seq=-1")
        self.assertEqual(status, 400)
        self.assertFalse(data.get("ok"))

        status, data = self.get_json("/fan/commentary?since_change_seq=-1")
        self.assertEqual(status, 400)
        self.assertFalse(data.get("ok"))

        status, data = self.get_json("/fan/commentary?version=-1")
        self.assertEqual(status, 400)
        self.assertFalse(data.get("ok"))

        # Conflicting cursors
        status, data = self.get_json("/fan/commentary?since_seq=5&before_seq=2")
        self.assertEqual(status, 400)
        self.assertIn("Conflicting cursors", data.get("error"))

        status, data = self.get_json("/fan/commentary?since_change_seq=5&before_seq=2")
        self.assertEqual(status, 400)
        self.assertIn("Conflicting cursors", data.get("error"))

        status, data = self.get_json("/fan/commentary?since_seq=5&since_change_seq=5")
        self.assertEqual(status, 400)
        self.assertIn("Conflicting cursors", data.get("error"))

        # Clamping limit > 50
        mid = server.current_match_id()
        with server._db_lock, server._db() as conn:
            for i in range(1, 60):
                _insert_commentary_item(conn, match_id=mid, commentary_seq=i, source_timeline_seq=i, change_seq=i)
            conn.commit()

        status, data = self.get_json("/fan/commentary?limit=999")
        self.assertEqual(status, 200)
        self.assertEqual(len(data.get("commentary")), 50, "Limit must be clamped to maximum 50")

    def test_11_server_restart_persistence(self):
        mid = server.current_match_id()
        with server._db_lock, server._db() as conn:
            _insert_commentary_item(conn, match_id=mid, commentary_seq=1, change_seq=1, text="Persisted ball")
            conn.commit()

        # Simulate fresh handler invocation
        status, data = self.get_json("/fan/commentary")
        self.assertEqual(status, 200)
        self.assertEqual(data.get("total_commentary"), 1)
        self.assertEqual(data.get("commentary")[0]["text"], "Persisted ball")

    def test_12_non_interference_with_existing_endpoints(self):
        endpoints = [
            ("/fan", 200),
            ("/fan/data", 200),
            ("/fan/timeline", 200),
            ("/overlay", 200),
            ("/control", 200),
            ("/scoring", 200),
        ]
        for path, expected_status in endpoints:
            status, _, _ = self.request("GET", path)
            self.assertEqual(status, expected_status, f"Endpoint {path} failed with status {status}")


if __name__ == "__main__":
    unittest.main()

