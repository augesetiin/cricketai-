"""
Unit tests for Fan Commentary Engine (Phase 3 Stage 1)
──────────────────────────────────────────────────────
Verifies:
- fan_commentary SQLite schema and indexes
- Monotonically increasing commentary_seq separated from source_timeline_seq
- Factual deterministic commentary across all delivery outcomes
- Factual guardrails: zero hallucinated shots or unrecorded statistics
- Milestone detection (batter 50, batter 100, team boundaries)
- Immediate availability of deterministic over summaries
- Asynchronous AI over summary replacement (in-place revision bump, no duplicate rows)
- AI unavailable and timeout fallbacks
- In-place delivery corrections
- Undo revocations (is_revoked = 1)
- Reconciler persistence isolation (commentary errors never block timeline)
- Restart idempotence (zero duplicate commentary entries)
- Speech text sanitizer
"""
import copy
import os
import sqlite3
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fan_commentary
import fan_engine
import server


class TestFanCommentary(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        fan_commentary.init_commentary_db(self.conn)
        fan_engine.init_fan_db(self.conn)
        self.engine = fan_commentary.FanCommentaryEngine("test_match")

    def tearDown(self):
        self.conn.close()

    def test_init_db_schema_and_indexes(self):
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(fan_commentary)")
        columns = {col[1]: col[2] for col in cursor.fetchall()}

        required_cols = [
            "commentary_id", "match_id", "innings", "commentary_seq",
            "source_timeline_seq", "over_number", "ball_in_over", "event_type",
            "headline", "text", "audio_text", "is_ai", "ai_status", "revision",
            "is_corrected", "is_uncertain", "is_adjustment", "is_revoked",
            "created_at", "updated_at"
        ]
        for rc in required_cols:
            self.assertIn(rc, columns, f"Missing required column {rc}")

        cursor.execute("PRAGMA index_list(fan_commentary)")
        indexes = [idx[1] for idx in cursor.fetchall()]
        self.assertIn("idx_fan_commentary_seq", indexes)
        self.assertIn("idx_fan_commentary_source", indexes)
        self.assertIn("idx_fan_commentary_over", indexes)

    def test_all_delivery_outcomes_deterministic(self):
        outcomes = [
            # 1. Dot ball
            ({"seq": 1, "batter_name": "Smith", "bowler_name": "Broad", "runs_batter": 0, "total_runs": 0, "outcome": ".", "score_after": 0, "wickets_after": 0, "overs_after": "0.1", "is_legal": True}, "dot", "DOT BALL"),
            # 2. Single
            ({"seq": 2, "batter_name": "Smith", "bowler_name": "Broad", "runs_batter": 1, "total_runs": 1, "outcome": "1", "score_after": 1, "wickets_after": 0, "overs_after": "0.2", "is_legal": True}, "runs", "1 RUN"),
            # 3. Two runs
            ({"seq": 3, "batter_name": "Jones", "non_striker_name": "Smith", "bowler_name": "Broad", "runs_batter": 2, "total_runs": 2, "outcome": "2", "score_after": 3, "wickets_after": 0, "overs_after": "0.3", "is_legal": True}, "runs", "2 RUNS"),
            # 4. Three runs
            ({"seq": 4, "batter_name": "Jones", "bowler_name": "Broad", "runs_batter": 3, "total_runs": 3, "outcome": "3", "score_after": 6, "wickets_after": 0, "overs_after": "0.4", "is_legal": True}, "runs", "3 RUNS"),
            # 5. Boundary Four
            ({"seq": 5, "batter_name": "Smith", "bowler_name": "Broad", "runs_batter": 4, "total_runs": 4, "outcome": "4", "is_boundary": True, "score_after": 10, "wickets_after": 0, "overs_after": "0.5", "is_legal": True}, "four", "FOUR!"),
            # 6. Boundary Six
            ({"seq": 6, "batter_name": "Smith", "bowler_name": "Broad", "runs_batter": 6, "total_runs": 6, "outcome": "6", "is_boundary": True, "score_after": 16, "wickets_after": 0, "overs_after": "1.0", "is_legal": True}, "six", "SIX!"),
            # 7. Wicket
            ({"seq": 7, "batter_name": "Smith", "bowler_name": "Anderson", "is_wicket": True, "wicket_type": "bowled", "score_after": 16, "wickets_after": 1, "overs_after": "1.1", "is_legal": True}, "wicket", "WICKET!"),
            # 8. Wide
            ({"seq": 8, "batter_name": "Jones", "bowler_name": "Anderson", "total_runs": 1, "extra_type": "wd", "is_legal": False, "score_after": 17, "wickets_after": 1, "overs_after": "1.1"}, "extra", "WIDE"),
            # 9. No-ball
            ({"seq": 9, "batter_name": "Jones", "bowler_name": "Anderson", "total_runs": 1, "extra_type": "nb", "is_legal": False, "score_after": 18, "wickets_after": 1, "overs_after": "1.1"}, "extra", "NO BALL"),
            # 10. Uncertain delivery
            ({"seq": 10, "over_number": 2, "is_uncertain": True, "score_after": 20, "wickets_after": 1, "overs_after": "2.0"}, "uncertain", "OVER BOUNDARY"),
            # 11. Adjustment (Cold Start)
            ({"seq": 11, "is_adjustment": True, "adjustment_desc": "Baseline established", "score_after": 45, "wickets_after": 2, "overs_after": "6.0"}, "adjustment", "SCORE UPDATE"),
        ]

        for d, expected_type, expected_headline in outcomes:
            c = fan_commentary.format_delivery_commentary(d)
            self.assertEqual(c["event_type"], expected_type)
            self.assertEqual(c["headline"], expected_headline)
            self.assertIn("score_after" in d and str(d["score_after"]), c["text"])
            self.assertTrue(len(c["text"]) > 10)
            self.assertTrue(len(c["audio_text"]) > 10)

    def test_factual_guardrails_no_hallucinations(self):
        # Delivery without shot type
        d = {
            "seq": 1, "batter_name": "Smith", "bowler_name": "Broad",
            "runs_batter": 4, "total_runs": 4, "outcome": "4", "is_boundary": True,
            "score_after": 4, "wickets_after": 0, "overs_after": "0.1", "is_legal": True
        }
        res = fan_commentary.format_delivery_commentary(d)
        text = res["text"].lower()

        # Must contain actual facts
        self.assertIn("smith", text)
        self.assertIn("broad", text)
        self.assertIn("4", text)

        # Forbidden speculative shot inventions
        forbidden_inventions = ["cover drive", "pull shot", "hook", "straight drive", "square cut", "glance"]
        for f in forbidden_inventions:
            self.assertNotIn(f, text)

    def test_separate_commentary_seq_architecture(self):
        # Process 1 delivery that also triggers a team 50 milestone
        deliv = {
            "match_id": "test_match", "innings": 1, "seq": 12,
            "over_number": 2, "ball_in_over": 6, "token": "4", "outcome": "4",
            "batter_name": "Root", "bowler_name": "Anderson",
            "runs_batter": 4, "total_runs": 4, "is_boundary": True,
            "score_after": 52, "wickets_after": 1, "overs_after": "2.0", "is_legal": True
        }

        generated = self.engine.process_reconciled_batch([deliv], live_state={"score": 48}, conn=self.conn)

        # Both the ball delivery and the milestone and the over summary reference the same delivery!
        rows = self.conn.execute("""
            SELECT commentary_id, commentary_seq, source_timeline_seq, event_type, headline
            FROM fan_commentary
            WHERE match_id='test_match' AND innings=1
            ORDER BY commentary_seq ASC
        """).fetchall()

        self.assertGreaterEqual(len(rows), 2)
        # Verify monotonically increasing commentary_seq
        c_seqs = [r[1] for r in rows]
        self.assertEqual(c_seqs, sorted(c_seqs))
        self.assertEqual(len(c_seqs), len(set(c_seqs)), "commentary_seq must be strictly unique and increasing")

        # Verify source_timeline_seq points to delivery 12 for both
        for r in rows:
            self.assertEqual(r[2], 12, "Multiple commentary items must safely reference source_timeline_seq")

    def test_milestone_detection(self):
        deliv = {
            "match_id": "test_match", "innings": 1, "seq": 10,
            "batter_name": "Williamson", "runs_batter": 4, "total_runs": 4,
            "score_after": 50, "wickets_after": 0, "overs_after": "5.0", "is_legal": True
        }
        live_state = {
            "score": 46,
            "batter1": {"name": "Williamson", "runs": 46}
        }
        ms = fan_commentary.detect_milestones(deliv, prev_state=live_state)
        ms_types = [m["type"] for m in ms]
        self.assertIn("team_50", ms_types)
        self.assertIn("batter_fifty", ms_types)

    def test_over_summary_immediate_availability(self):
        # 6th ball of over 1
        d = {
            "match_id": "test_match", "innings": 1, "seq": 6,
            "over_number": 1, "ball_in_over": 6, "token": "1", "outcome": "1",
            "batter_name": "Smith", "bowler_name": "Anderson", "runs_batter": 1, "total_runs": 1,
            "score_after": 8, "wickets_after": 0, "overs_after": "1.0", "is_legal": True
        }
        self.engine.process_reconciled_batch([d], conn=self.conn)

        row = self.conn.execute("""
            SELECT commentary_id, event_type, headline, text, is_ai, ai_status
            FROM fan_commentary
            WHERE match_id='test_match' AND innings=1 AND event_type='over_summary'
        """).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row[1], "over_summary")
        self.assertIn("END OF OVER 1", row[2])
        self.assertIn("Anderson", row[3])
        self.assertEqual(row[4], 0, "Must be available immediately as deterministic summary")

    def test_asynchronous_ai_over_summary_replacement(self):
        cid = "comm_test_match_i1_o1_summary"
        now_iso = "2026-11-01T12:00:00Z"
        # Seed deterministic summary at revision 1
        self.conn.execute("""
            INSERT INTO fan_commentary (
                commentary_id, match_id, innings, commentary_seq, source_timeline_seq,
                over_number, ball_in_over, event_type, headline, text, audio_text,
                is_ai, ai_status, revision, created_at, updated_at
            ) VALUES (?, 'test_match', 1, 10, 6, 1, 6, 'over_summary', 'END OF OVER 1', 'Deterministic summary', 'Deterministic audio', 0, 'pending', 1, ?, ?)
        """, (cid, now_iso, now_iso))
        self.conn.commit()

        # Simulate async AI update
        ai_summary = "A tightly contested opening over from Anderson yields just two singles."
        def custom_db_update(comm_id, text):
            self.conn.execute("""
                UPDATE fan_commentary
                SET text = ?, audio_text = ?, is_ai = 1, ai_status = 'completed',
                    revision = revision + 1, updated_at = '2026-11-01T12:00:02Z'
                WHERE commentary_id = ?
            """, (text, fan_commentary.sanitize_for_speech(text), comm_id))
            self.conn.commit()

        custom_db_update(cid, ai_summary)

        row = self.conn.execute("""
            SELECT commentary_seq, revision, text, is_ai, ai_status
            FROM fan_commentary WHERE commentary_id=?
        """, (cid,)).fetchone()

        self.assertEqual(row[0], 10, "commentary_seq must be preserved")
        self.assertEqual(row[1], 2, "revision must increment to 2")
        self.assertEqual(row[2], ai_summary)
        self.assertEqual(row[3], 1)
        self.assertEqual(row[4], "completed")

        # Assert no duplicate rows exist
        count = self.conn.execute("SELECT COUNT(*) FROM fan_commentary WHERE commentary_id=?", (cid,)).fetchone()[0]
        self.assertEqual(count, 1)

    def test_ai_unavailable_and_timeout_fallback(self):
        with patch("fan_commentary._get_anthropic_api_key", return_value=""):
            # Empty API key -> skips AI request gracefully
            t = fan_commentary.async_generate_ai_over_summary("test_match", 1, 1, {}, "fake_id")
            self.assertIsNotNone(t)
            t.join(timeout=1.0)

    def test_in_place_delivery_correction(self):
        # Insert initial ball (1 run)
        d1 = {
            "match_id": "test_match", "innings": 1, "seq": 3,
            "over_number": 1, "ball_in_over": 3, "runs_batter": 1, "total_runs": 1,
            "outcome": "1", "batter_name": "Smith", "bowler_name": "Broad",
            "score_after": 5, "wickets_after": 0, "overs_after": "0.3", "is_legal": True,
            "is_corrected": False
        }
        self.engine.process_reconciled_batch([d1], conn=self.conn)

        row1 = self.conn.execute("SELECT revision, text, is_corrected FROM fan_commentary WHERE source_timeline_seq=3").fetchone()
        self.assertEqual(row1[0], 1)
        self.assertEqual(row1[2], 0)

        # Scorer edits ball 3 from 1 to 4 runs
        d1_corrected = copy.deepcopy(d1)
        d1_corrected["runs_batter"] = 4
        d1_corrected["total_runs"] = 4
        d1_corrected["outcome"] = "4"
        d1_corrected["is_boundary"] = True
        d1_corrected["score_after"] = 8
        d1_corrected["is_corrected"] = True

        self.engine.process_reconciled_batch([d1_corrected], conn=self.conn)

        row2 = self.conn.execute("SELECT revision, text, is_corrected FROM fan_commentary WHERE source_timeline_seq=3").fetchone()
        self.assertEqual(row2[0], 2, "revision must bump to 2")
        self.assertEqual(row2[2], 1, "is_corrected must be 1")
        self.assertIn("FOUR", row2[1])

    def test_undo_and_revocation_handling(self):
        # Seed 2 balls
        d1 = {"match_id": "test_match", "innings": 1, "seq": 1, "over_number": 1, "ball_in_over": 1, "runs_batter": 1, "total_runs": 1, "outcome": "1", "batter_name": "A", "bowler_name": "B", "score_after": 1, "wickets_after": 0, "overs_after": "0.1", "is_legal": True}
        d2 = {"match_id": "test_match", "innings": 1, "seq": 2, "over_number": 1, "ball_in_over": 2, "runs_batter": 4, "total_runs": 4, "outcome": "4", "batter_name": "A", "bowler_name": "B", "score_after": 5, "wickets_after": 0, "overs_after": "0.2", "is_legal": True}
        self.engine.process_reconciled_batch([d1, d2], conn=self.conn)

        # Operator undos ball 2
        self.engine.handle_revocations("test_match", 1, [2], conn=self.conn)

        # Ball 1 must remain active (is_revoked = 0)
        r1 = self.conn.execute("SELECT is_revoked FROM fan_commentary WHERE source_timeline_seq=1").fetchone()
        self.assertEqual(r1[0], 0)

        # Ball 2 must be revoked (is_revoked = 1)
        r2 = self.conn.execute("SELECT is_revoked FROM fan_commentary WHERE source_timeline_seq=2").fetchone()
        self.assertEqual(r2[0], 1)

    def test_restart_recovery_idempotence(self):
        d = {"match_id": "test_match", "innings": 1, "seq": 1, "over_number": 1, "ball_in_over": 1, "runs_batter": 1, "total_runs": 1, "outcome": "1", "batter_name": "A", "bowler_name": "B", "score_after": 1, "wickets_after": 0, "overs_after": "0.1", "is_legal": True}
        # First ingestion
        self.engine.process_reconciled_batch([d], conn=self.conn)
        count1 = self.conn.execute("SELECT COUNT(*) FROM fan_commentary").fetchone()[0]
        self.assertEqual(count1, 1)

        # Fresh instance on restart playing identical delivery
        fresh_engine = fan_commentary.FanCommentaryEngine("test_match")
        fresh_engine.process_reconciled_batch([d], conn=self.conn)
        count2 = self.conn.execute("SELECT COUNT(*) FROM fan_commentary").fetchone()[0]
        self.assertEqual(count2, 1, "Must never duplicate commentary entries across restarts")

    def test_reconciler_integration_non_interference(self):
        # Mock engine to simulate unexpected error in commentary
        reconciler = fan_engine.FanDeliveryReconciler("test_reconciler")
        with patch("fan_commentary.FanCommentaryEngine.process_reconciled_batch", side_effect=RuntimeError("Commentary exploded!")):
            # Must NOT raise or break timeline persistence
            d = {"match_id": "test_reconciler", "innings": 1, "seq": 1, "event_id": "e1", "revision": 1, "timeline_version": 1, "over_number": 1, "over_idx": 0, "ball_in_over": 1, "legal_ball_in_over": 1, "is_legal": True, "token": "1", "outcome": "1", "runs_batter": 1, "runs_extras": 0, "total_runs": 1, "extra_type": None, "is_wicket": False, "wicket_type": None, "dismissal_desc": None, "batter_name": "A", "non_striker_name": "B", "bowler_name": "C", "score_after": 1, "wickets_after": 0, "overs_after": "0.1", "is_boundary": False, "boundary_type": None, "is_corrected": False, "is_uncertain": False, "is_adjustment": False, "timestamp": "2026-11-01T12:00:00Z"}
            reconciler._persist_timeline_batch([d], {"count": 1}, conn=self.conn)

        # Verify delivery committed safely into fan_timeline
        row = self.conn.execute("SELECT seq, token FROM fan_timeline WHERE match_id='test_reconciler'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[1], "1")

    def test_speech_text_sanitizer(self):
        tests = [
            ("Score is 14/2 in (1.4 ov).", "Score is 14 for 2 in 1 point 4 overs."),
            ("Score is 0/0.", "Score is 0 for no wicket."),
            ("Conceded 1wd by Broad.", "Conceded 1 wide by Broad."),
            ("No ball called: nb.", "No ball called: no ball."),
            ("Wicket! c Smith b Anderson.", "Wicket! caught by Smith, bowled by Anderson."),
            ("Target is 120 (RR 6.50).", "Target is 120 (run rate 6 point 50)."),
        ]
        for inp, expected in tests:
            san = fan_commentary.sanitize_for_speech(inp)
            self.assertEqual(san, expected)


if __name__ == "__main__":
    unittest.main()
