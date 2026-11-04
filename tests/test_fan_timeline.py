"""
Comprehensive unit tests for FanDeliveryReconciler and Timeline Engine (Phase 2 Stage 1)
"""
import os
import sqlite3
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fan_engine
import server


class TestFanTimelineEngine(unittest.TestCase):
    def setUp(self):
        # Use an in-memory SQLite database for test isolation
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        fan_engine.init_fan_db(self.conn)
        self.reconciler = fan_engine.FanDeliveryReconciler("test_match_1")

    def tearDown(self):
        self.conn.close()

    def test_manual_scoring_legal_deliveries(self):
        cfg = {"home": "Team A", "away": "Team B", "max_overs": 20}
        events = [
            {"event": "bowler", "name": "Bowler 1"},
            {"event": "ball", "kind": "4"},
            {"event": "ball", "kind": "1"},
        ]
        self.reconciler.process_manual_snapshot("test_match_1", events, cfg, conn=self.conn)
        timeline = self.reconciler.timeline

        self.assertEqual(len(timeline), 2)
        # Ball 1: 4 runs off bat
        b1 = timeline[0]
        self.assertEqual(b1["seq"], 1)
        self.assertEqual(b1["over_number"], 1)
        self.assertEqual(b1["ball_in_over"], 1)
        self.assertEqual(b1["legal_ball_in_over"], 1)
        self.assertTrue(b1["is_legal"])
        self.assertEqual(b1["token"], "4")
        self.assertEqual(b1["runs_batter"], 4)
        self.assertEqual(b1["runs_extras"], 0)
        self.assertEqual(b1["total_runs"], 4)
        self.assertEqual(b1["score_after"], 4)
        self.assertEqual(b1["wickets_after"], 0)
        self.assertEqual(b1["batter_name"], "Team A 1")
        self.assertEqual(b1["bowler_name"], "Bowler 1")
        self.assertTrue(b1["is_boundary"])
        self.assertEqual(b1["boundary_type"], "four")

        # Ball 2: 1 run off bat -> strike rotated
        b2 = timeline[1]
        self.assertEqual(b2["seq"], 2)
        self.assertEqual(b2["total_runs"], 1)
        self.assertEqual(b2["score_after"], 5)
        self.assertEqual(b2["batter_name"], "Team A 1")

    def test_wides_and_noballs_semantics(self):
        cfg = {"home": "Team A", "away": "Team B", "max_overs": 20}
        events = [
            {"event": "bowler", "name": "Bowler 1"},
            {"event": "ball", "kind": "wide", "runs": 1},  # Wide + 1 run = 2 extras
            {"event": "ball", "kind": "noball", "runs": 4}, # No-ball + 4 bat runs = 5 total
        ]
        self.reconciler.process_manual_snapshot("test_match_1", events, cfg, conn=self.conn)
        timeline = self.reconciler.timeline

        self.assertEqual(len(timeline), 2)
        # Wide
        w = timeline[0]
        self.assertFalse(w["is_legal"])
        self.assertEqual(w["extra_type"], "wide")
        self.assertEqual(w["runs_batter"], 0)
        self.assertEqual(w["runs_extras"], 2)
        self.assertEqual(w["total_runs"], 2)
        self.assertEqual(w["score_after"], 2)

        # No-ball with boundary
        nb = timeline[1]
        self.assertFalse(nb["is_legal"])
        self.assertEqual(nb["extra_type"], "noball")
        self.assertEqual(nb["runs_batter"], 4)
        self.assertEqual(nb["runs_extras"], 1)
        self.assertEqual(nb["total_runs"], 5)
        self.assertEqual(nb["score_after"], 7)
        self.assertTrue(nb["is_boundary"])

    def test_wickets_and_dismissal_details(self):
        cfg = {"home": "Team A", "away": "Team B", "max_overs": 20}
        events = [
            {"event": "bowler", "name": "Bowler 1"},
            {"event": "ball", "kind": "W", "wicket_type": "caught", "fielder": "Fielder 1"},
        ]
        self.reconciler.process_manual_snapshot("test_match_1", events, cfg, conn=self.conn)
        timeline = self.reconciler.timeline

        self.assertEqual(len(timeline), 1)
        wkt = timeline[0]
        self.assertTrue(wkt["is_wicket"])
        self.assertEqual(wkt["wicket_type"], "CAUGHT")
        self.assertIn("Fielder 1", wkt["dismissal_desc"])
        self.assertEqual(wkt["wickets_after"], 1)
        self.assertEqual(wkt["score_after"], 0)

    def test_strike_rotation_and_bowler_changes(self):
        cfg = {"home": "Team A", "away": "Team B", "max_overs": 20}
        events = [
            {"event": "bowler", "name": "Bowler 1"},
            {"event": "ball", "kind": "1"},  # Striker Team A 1 scores 1, so Team A 2 is on strike
            {"event": "ball", "kind": "dot"},  # Faced by Team A 2
        ]
        self.reconciler.process_manual_snapshot("test_match_1", events, cfg, conn=self.conn)
        timeline = self.reconciler.timeline

        self.assertEqual(timeline[0]["batter_name"], "Team A 1")
        self.assertEqual(timeline[1]["batter_name"], "Team A 2")

    def test_manual_undo_and_historical_edits(self):
        cfg = {"home": "Team A", "away": "Team B", "max_overs": 20}
        events = [
            {"event": "bowler", "name": "Bowler 1"},
            {"event": "ball", "kind": "4"},
            {"event": "ball", "kind": "6"},
        ]
        self.reconciler.process_manual_snapshot("test_match_1", events, cfg, conn=self.conn)
        self.assertEqual(len(self.reconciler.timeline), 2)
        v1 = self.reconciler.timeline_version

        # 1. Test Undo: operator removes last ball
        events_after_undo = events[:-1]
        self.reconciler.process_manual_snapshot("test_match_1", events_after_undo, cfg, conn=self.conn)
        self.assertEqual(len(self.reconciler.timeline), 1)
        self.assertEqual(self.reconciler.timeline[0]["token"], "4")
        # Timeline version bumped to trigger client reset
        self.assertGreater(self.reconciler.timeline_version, v1)
        v2 = self.reconciler.timeline_version

        # 2. Test Historical Edit: edit ball 0 from 4 to 1
        events_after_edit = [
            {"event": "bowler", "name": "Bowler 1"},
            {"event": "ball", "kind": "1"},
        ]
        self.reconciler.process_manual_snapshot("test_match_1", events_after_edit, cfg, conn=self.conn)
        self.assertEqual(len(self.reconciler.timeline), 1)
        self.assertEqual(self.reconciler.timeline[0]["token"], "1")
        self.assertTrue(self.reconciler.timeline[0]["is_corrected"])
        self.assertEqual(self.reconciler.timeline[0]["revision"], 2)
        self.assertGreater(self.reconciler.timeline_version, v2)

    def test_timestamp_preservation_across_replays(self):
        cfg = {"home": "Team A", "away": "Team B", "max_overs": 20}
        events = [
            {"event": "bowler", "name": "Bowler 1"},
            {"event": "ball", "kind": "1", "ts": "2026-11-01T10:00:00Z"},
            {"event": "ball", "kind": "2"},  # Generated on first replay
        ]
        self.reconciler.process_manual_snapshot("test_match_1", events, cfg, conn=self.conn)
        ts1 = self.reconciler.timeline[0]["timestamp"]
        ts2 = self.reconciler.timeline[1]["timestamp"]
        self.assertEqual(ts1, "2026-11-01T10:00:00Z")

        # Second replay 1 second later must preserve exact timestamps
        time.sleep(0.01)
        self.reconciler.process_manual_snapshot("test_match_1", events, cfg, conn=self.conn)
        self.assertEqual(self.reconciler.timeline[0]["timestamp"], ts1)
        self.assertEqual(self.reconciler.timeline[1]["timestamp"], ts2)

    def test_pcs_snapshot_duplicate_and_additions(self):
        state1 = {
            "battingTeamName": "Rival CC",
            "bowlingTeamName": "Home CC",
            "innings": 1,
            "score": 5,
            "wickets": 0,
            "overs": "0.2",
            "last_ball": "4 1",
            "batter1": {"name": "Player 1", "onStrike": True},
            "bowler": {"name": "Bowler A"},
        }
        self.reconciler.process_pcs_snapshot(state1, mtime_ns=1000, size=500, match_id="test_pcs_1", conn=self.conn)
        self.assertEqual(len(self.reconciler.timeline), 2)
        self.assertEqual(self.reconciler.timeline[0]["token"], "4")
        self.assertEqual(self.reconciler.timeline[1]["token"], "1")

        # Duplicate snapshot with identical balls
        self.reconciler.process_pcs_snapshot(state1, mtime_ns=1000, size=500, match_id="test_pcs_1", conn=self.conn)
        self.assertEqual(len(self.reconciler.timeline), 2)

        # New delivery added: ". 4 1 W" (next ball is W)
        state2 = dict(state1)
        state2["score"] = 5
        state2["wickets"] = 1
        state2["overs"] = "0.3"
        state2["last_ball"] = "4 1 W"
        self.reconciler.process_pcs_snapshot(state2, mtime_ns=2000, size=510, match_id="test_pcs_1", conn=self.conn)
        self.assertEqual(len(self.reconciler.timeline), 3)
        self.assertEqual(self.reconciler.timeline[2]["token"], "W")
        self.assertTrue(self.reconciler.timeline[2]["is_wicket"])

    def test_pcs_current_over_correction(self):
        # Scorer changes ball 2 from 1 to 4
        state1 = {
            "battingTeamName": "Rival CC", "bowlingTeamName": "Home CC",
            "innings": 1, "score": 5, "wickets": 0, "overs": "0.2",
            "last_ball": "4 1", "batter1": {"name": "P1", "onStrike": True},
            "bowler": {"name": "B1"},
        }
        self.reconciler.process_pcs_snapshot(state1, 1000, 500, match_id="test_pcs_2", conn=self.conn)
        self.assertEqual(self.reconciler.timeline[1]["token"], "1")

        state2 = dict(state1)
        state2["score"] = 8  # 4 + 4
        state2["last_ball"] = "4 4"
        self.reconciler.process_pcs_snapshot(state2, 2000, 500, match_id="test_pcs_2", conn=self.conn)
        self.assertEqual(len(self.reconciler.timeline), 2)
        self.assertEqual(self.reconciler.timeline[1]["token"], "4")
        self.assertTrue(self.reconciler.timeline[1]["is_corrected"])
        self.assertEqual(self.reconciler.timeline[1]["revision"], 2)

    def test_over_boundary_recovery_and_uncertain_marking(self):
        # Over 15.5: 5 balls logged
        state1 = {
            "battingTeamName": "Rival CC", "bowlingTeamName": "Home CC",
            "innings": 1, "score": 100, "wickets": 2, "overs": "15.5",
            "last_ball": "1 4 . 2 1", "batter1": {"name": "Striker A", "onStrike": True},
            "bowler": {"name": "Bowler X"},
        }
        self.reconciler.process_pcs_snapshot(state1, 1000, 500, match_id="test_pcs_3", conn=self.conn)
        # 1 baseline entry for completed overs 1-15 + 5 active balls in over 16
        self.assertEqual(len(self.reconciler.timeline), 6)

        # Over boundary crossed: 16.1, score increased by 5 (4 runs on final ball + 1 on new ball)
        # Ticker shows '1' for the new over
        state2 = {
            "battingTeamName": "Rival CC", "bowlingTeamName": "Home CC",
            "innings": 1, "score": 105, "wickets": 2, "overs": "16.1",
            "last_ball": "1", "batter1": {"name": "Striker B", "onStrike": True},
            "bowler": {"name": "Bowler Y"},
        }
        self.reconciler.process_pcs_snapshot(state2, 2000, 500, match_id="test_pcs_3", conn=self.conn)

        # Timeline contains: 1 baseline + 5 initial + 1 recovered final ball + 1 new over ball = 8 entries
        self.assertEqual(len(self.reconciler.timeline), 8)
        recovered_ball = self.reconciler.timeline[6]
        self.assertEqual(recovered_ball["over_number"], 16)
        self.assertEqual(recovered_ball["total_runs"], 4)
        # CRITICAL: Reconstructed delivery is honestly marked as uncertain
        self.assertTrue(recovered_ball["is_uncertain"])
        self.assertIn("score delta", recovered_ball["adjustment_desc"].lower())

    def test_restart_and_checkpoint_recovery(self):
        # Populate timeline in DB
        state = {
            "battingTeamName": "Rival CC", "bowlingTeamName": "Home CC",
            "innings": 1, "score": 6, "wickets": 0, "overs": "0.2",
            "last_ball": "2 4", "batter1": {"name": "P1", "onStrike": True},
            "bowler": {"name": "B1"},
        }
        self.reconciler.process_pcs_snapshot(state, 1000, 500, match_id="test_restart_1", conn=self.conn)
        self.assertEqual(len(self.reconciler.timeline), 2)

        # Create a fresh reconciler instance (simulating server reboot)
        fresh_reconciler = fan_engine.FanDeliveryReconciler()
        fresh_reconciler.restore_from_db(match_id="test_restart_1", conn=self.conn)

        self.assertEqual(len(fresh_reconciler.timeline), 2)
        self.assertEqual(fresh_reconciler.timeline[0]["token"], "2")
        self.assertEqual(fresh_reconciler.timeline[1]["token"], "4")
        self.assertEqual(fresh_reconciler.prev["score"], 6)

    def test_cold_start_halfway_through_match(self):
        # Match starts at over 14.2 with score 95/3
        state = {
            "battingTeamName": "Rival CC", "bowlingTeamName": "Home CC",
            "innings": 1, "score": 95, "wickets": 3, "overs": "14.2",
            "last_ball": "1 .", "batter1": {"name": "P1", "onStrike": True},
            "bowler": {"name": "B1"},
        }
        self.reconciler.process_pcs_snapshot(state, 1000, 500, match_id="test_cold_1", conn=self.conn)
        # Must write a baseline entry for completed overs rather than inventing overs 1..14
        self.assertEqual(len(self.reconciler.timeline), 3)
        base = self.reconciler.timeline[0]
        self.assertTrue(base["is_adjustment"])
        self.assertFalse(base["is_uncertain"])
        self.assertIn("connected at 14.2", base["adjustment_desc"].lower())
        # The 2 balls of the active over are logged
        self.assertEqual(self.reconciler.timeline[1]["token"], "1")
        self.assertEqual(self.reconciler.timeline[2]["token"], ".")

    def test_worker_single_instance_and_lifecycle(self):
        # Test worker thread start and idempotent start
        fan_engine.start_fan_timeline_worker()
        self.assertTrue(fan_engine._worker_started)
        t1 = fan_engine._worker_thread

        # Second call does not spawn a second thread
        fan_engine.start_fan_timeline_worker()
        self.assertEqual(fan_engine._worker_thread, t1)

        # Stop worker
        fan_engine.stop_fan_timeline_worker(timeout=1.0)
        self.assertFalse(fan_engine._worker_started)
        self.assertIsNone(fan_engine._worker_thread)

    def test_concurrent_scoring_operations_thread_safety(self):
        cfg = {"home": "Team A", "away": "Team B", "max_overs": 20}
        events = [{"event": "bowler", "name": "B1"}]
        for i in range(20):
            events.append({"event": "ball", "kind": "1"})

        errors = []

        def reader():
            try:
                for _ in range(50):
                    self.reconciler.process_manual_snapshot("test_conc", events, cfg, conn=self.conn)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertEqual(len(self.reconciler.timeline), 20)


if __name__ == "__main__":
    unittest.main()
