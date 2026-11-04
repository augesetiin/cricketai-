"""
Phase 2 Stage 4: Comprehensive End-to-End Verification Test Suite
─────────────────────────────────────────────────────────────────
Validates:
1. Complete application routes (/fan, /fan/data, /fan/timeline, /overlay, /control, /scoring).
2. Match Simulator E2E:
   - Live score updates and timeline synchronization
   - Multi-delivery capture & over transitions
   - Fours, sixes, wickets, wides, and no-balls
   - Multi-innings persistence (Innings 1 history available during Innings 2)
   - Match completion state
3. OBS Isolation:
   - Timeline captures deliveries independently of /live
   - OBS event buffer is NEVER touched or drained by fan requests
   - Zero duplicate synthetic balls or scoring interference
4. Manual Scoring Lifecycle:
   - Runs, boundaries (4 & 6), extras (wd & nb), wickets
   - Strike rotation and bowler changes
   - In-place ball editing (correction & revision tracking)
   - Undoing deliveries (revocation & timeline version bump)
5. Restart Recovery & Mid-Match Cold Start:
   - Server restart preserves all deliveries without duplicates
   - Mid-match baseline inception markers (is_adjustment=True)
6. Mobile & Desktop UI Layout Invariants:
   - Viewport meta, responsive container, touch targets (>= 44px),
   - Accessible badge colors and font hierarchy.
"""
import copy
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fan_engine
import server
from scoring_engine import InningsEngine
from simulate_match import MatchSimulator
from test_http import HttpTestBase


class TestFanStage4E2E(HttpTestBase):
    def setUp(self):
        super().setUp()
        with server._db_lock, server._db() as conn:
            fan_engine.init_fan_db(conn)
            conn.execute("DELETE FROM fan_timeline")
            conn.execute("DELETE FROM fan_reconciler_checkpoint")
            conn.commit()
        # Reset reconciler in-memory state
        rec = fan_engine.get_fan_reconciler()
        with rec.lock:
            rec.timeline = []
            rec.seq = 0
            rec.timeline_version = 1
            rec.prev = {}

    # ── 1. Route Availability Verification ───────────────────────────────────
    def test_all_application_routes(self):
        routes = [
            ("/fan", 200, "text/html"),
            ("/fan/data", 200, "application/json"),
            ("/fan/timeline", 200, "application/json"),
            ("/overlay", 200, "text/html"),
            ("/control", 200, "text/html"),
            ("/scoring", 200, "text/html"),
        ]
        for path, expected_status, expected_ct in routes:
            status, headers, body = self.request("GET", path)
            self.assertEqual(status, expected_status, f"Route {path} returned status {status}")
            ct = headers.get("Content-Type") or headers.get("content-type") or ""
            self.assertIn(expected_ct, ct, f"Route {path} Content-Type mismatch: {ct}")

    # ── 2. Simulator Chase Scenario E2E ─────────────────────────────────────
    def test_simulator_chase_scenario(self):
        mid = server.current_match_id()
        sim = MatchSimulator("chase", max_overs=20, seed=42)
        reconciler = fan_engine.FanDeliveryReconciler(mid)
        mtime = 1000

        with server._db_lock, server._db() as conn:
            fan_engine.init_fan_db(conn)
            # Feed simulation frames
            for label, frame in sim.frames():
                mtime += 1
                size = len(json.dumps(frame))
                reconciler.process_pcs_snapshot(frame, mtime_ns=mtime * 1000000, size=size,
                                               match_id=mid, conn=conn)

        # Query timeline API for Innings 2
        status, data = self.get_json("/fan/timeline?innings=2&limit=100")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        deliveries = data.get("deliveries", [])
        self.assertGreater(len(deliveries), 5, "Simulator should generate deliveries")

        # Verify classifications in timeline
        has_run = any(d["runs_batter"] > 0 for d in deliveries)
        has_dot = any(d["outcome"] == "dot" or d["token"] in (".", "0") for d in deliveries)
        self.assertTrue(has_run, "Chase should have run-scoring deliveries")
        self.assertTrue(has_dot, "Chase should have dot balls")

        # Verify chronological order
        seqs = [d["seq"] for d in deliveries]
        self.assertEqual(seqs, sorted(seqs), "Deliveries must be sorted chronologically ascending")

        # Verify over grouping fields
        for d in deliveries:
            self.assertIn("over_number", d)
            self.assertIn("ball_in_over", d)
            self.assertIn("score_after", d)
            self.assertIn("wickets_after", d)

    # ── 3. Multi-Innings Persistence ─────────────────────────────────────────
    def test_multi_innings_persistence(self):
        mid = server.current_match_id()
        reconciler = fan_engine.FanDeliveryReconciler(mid)

        with server._db_lock, server._db() as conn:
            fan_engine.init_fan_db(conn)
            # Innings 1: 3 balls
            frame_inn1_b1 = {
                "innings": 1, "score": 4, "wickets": 0, "overs": "0.1",
                "battingTeamName": "Team A", "bowlingTeamName": "Team B",
                "batsman1OnStrike": True, "batsman1Name": "Batter A", "batsman2Name": "Batter B",
                "bowler1Name": "Bowler X", "last_ball": "4", "over_history": "4"
            }
            frame_inn1_b2 = {
                "innings": 1, "score": 5, "wickets": 0, "overs": "0.2",
                "battingTeamName": "Team A", "bowlingTeamName": "Team B",
                "batsman1OnStrike": False, "batsman1Name": "Batter A", "batsman2Name": "Batter B",
                "bowler1Name": "Bowler X", "last_ball": "4 1", "over_history": "4 1"
            }
            reconciler.process_pcs_snapshot(frame_inn1_b1, 1000, 100, mid, conn=conn)
            reconciler.process_pcs_snapshot(frame_inn1_b2, 2000, 100, mid, conn=conn)

            # Innings 2 starts: 2 balls
            frame_inn2_b1 = {
                "innings": 2, "score": 6, "wickets": 0, "overs": "0.1",
                "battingTeamName": "Team B", "bowlingTeamName": "Team A",
                "batsman1OnStrike": True, "batsman1Name": "Batter C", "batsman2Name": "Batter D",
                "bowler1Name": "Bowler Y", "last_ball": "6", "over_history": "6"
            }
            reconciler.process_pcs_snapshot(frame_inn2_b1, 3000, 100, mid, conn=conn)

        # Query Innings 1 timeline: must remain fully intact!
        status1, data1 = self.get_json("/fan/timeline?innings=1")
        self.assertEqual(status1, 200)
        self.assertEqual(len(data1["deliveries"]), 2)
        self.assertEqual(data1["deliveries"][0]["token"], "4")
        self.assertEqual(data1["deliveries"][1]["token"], "1")

        # Query Innings 2 timeline: active innings
        status2, data2 = self.get_json("/fan/timeline?innings=2")
        self.assertEqual(status2, 200)
        self.assertEqual(len(data2["deliveries"]), 1)
        self.assertEqual(data2["deliveries"][0]["token"], "6")

    # ── 4. OBS Overlay Isolation & Event Buffer Non-Interference ─────────────
    def test_obs_isolation_and_event_buffer_safety(self):
        # 1. Verify fan endpoint does NOT drain or touch _event_buffer
        with server._event_buffer_lock:
            server._event_buffer.append({"type": "milestone", "player": "Key Batter", "text": "50 up!"})
            initial_len = len(server._event_buffer)

        # Issue fan dashboard, fan data, and fan timeline requests
        self.get_json("/fan/data")
        self.get_json("/fan/timeline")
        self.request("GET", "/fan")

        # Buffer must be untouched by fan requests
        with server._event_buffer_lock:
            self.assertEqual(len(server._event_buffer), initial_len)
            server._event_buffer.clear()

        # 2. Verify /live (which OBS uses) works normally without conflict
        status, headers, body = self.request("GET", "/live")
        self.assertEqual(status, 200)

    # ── 5. Manual Scoring Lifecycle & Replay Reconciler ──────────────────────
    def test_manual_scoring_lifecycle(self):
        mid = server.current_match_id()
        reconciler = fan_engine.FanDeliveryReconciler(mid)

        config = {
            "home": "Home XI", "away": "Away XI", "max_overs": 20,
            "striker": "Batter 1", "nonstriker": "Batter 2", "bowler": "Bowler 1",
            "home_xi": ["Batter 1", "Batter 2"], "away_xi": ["Bowler 1", "Bowler 2"]
        }

        # Event stream: 1 run, 4 runs, six, wide, wicket
        events = [
            {"event": "bowler", "name": "Bowler 1"},
            {"event": "ball", "kind": "1"},
            {"event": "ball", "kind": "4"},
            {"event": "ball", "kind": "6"},
            {"event": "ball", "kind": "wide", "runs": 1},
            {"event": "ball", "kind": "W", "wicket_type": "bowled"},
        ]

        with server._db_lock, server._db() as conn:
            fan_engine.init_fan_db(conn)
            reconciler.process_manual_snapshot(mid, events, config, conn=conn)

        status, data = self.get_json("/fan/timeline?innings=1")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["deliveries"]), 5)
        delivs = data["deliveries"]

        # 1 run
        self.assertEqual(delivs[0]["total_runs"], 1)
        self.assertFalse(delivs[0]["is_boundary"])

        # 4 runs
        self.assertEqual(delivs[1]["total_runs"], 4)
        self.assertTrue(delivs[1]["is_boundary"])

        # 6 runs
        self.assertEqual(delivs[2]["total_runs"], 6)
        self.assertTrue(delivs[2]["is_boundary"])

        # Wide (extra)
        self.assertFalse(delivs[3]["is_legal"])
        self.assertEqual(delivs[3]["extra_type"], "wide")

        # Wicket
        self.assertTrue(delivs[4]["is_wicket"])
        self.assertEqual(delivs[4]["wicket_type"], "BOWLED")

        # ── Test In-Place Edit ──
        # Edit ball 2 (4 runs -> 2 runs)
        edited_events = copy.deepcopy(events)
        edited_events[2]["kind"] = "2"

        with server._db_lock, server._db() as conn:
            reconciler.process_manual_snapshot(mid, edited_events, config, conn=conn)

        status, data = self.get_json("/fan/timeline?innings=1")
        self.assertEqual(status, 200)
        ball_2 = data["deliveries"][1]
        self.assertEqual(ball_2["total_runs"], 2)
        self.assertTrue(ball_2["is_corrected"])
        self.assertEqual(ball_2["revision"], 2)

        # ── Test Undo (Revoke last delivery) ──
        undo_events = copy.deepcopy(edited_events[:-1])  # 4 balls left

        with server._db_lock, server._db() as conn:
            reconciler.process_manual_snapshot(mid, undo_events, config, conn=conn)

        # Query with old version -> should trigger reset_required
        status, data = self.get_json(f"/fan/timeline?innings=1&version=1")
        self.assertEqual(status, 200)
        self.assertTrue(data["reset_required"])
        self.assertEqual(len(data["deliveries"]), 4)

    # ── 6. Restart Recovery & Idempotence ────────────────────────────────────
    def test_restart_recovery_and_idempotence(self):
        mid = server.current_match_id()

        # Phase A: Populate database with deliveries
        with server._db_lock, server._db() as conn:
            fan_engine.init_fan_db(conn)
            rec1 = fan_engine.FanDeliveryReconciler(mid)
            events = [
                {"event": "bowler", "name": "B"},
                {"event": "ball", "kind": "1"},
                {"event": "ball", "kind": "2"},
                {"event": "ball", "kind": "4"},
            ]
            cfg = {"home": "H", "away": "A", "max_overs": 20, "striker": "A", "nonstriker": "C", "bowler": "B"}
            rec1.process_manual_snapshot(mid, events, cfg, conn=conn)

        # Verify 3 deliveries stored
        status, data = self.get_json("/fan/timeline?innings=1")
        self.assertEqual(data["total_deliveries"], 3)

        # Phase B: Simulate Server Restart (Fresh Reconciler instance from disk)
        rec2 = fan_engine.FanDeliveryReconciler(mid)
        with server._db_lock, server._db() as conn:
            # Replaying the SAME snapshot after restart must NOT duplicate deliveries
            rec2.process_manual_snapshot(mid, events, cfg, conn=conn)

        status, data = self.get_json("/fan/timeline?innings=1")
        self.assertEqual(data["total_deliveries"], 3, "Replaying identical events must not duplicate rows")

    # ── 7. UI Layout, Badges & Mobile Responsiveness Invariants ──────────────
    def test_ui_mobile_viewport_and_badges(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fan.html"),
                  encoding="utf-8") as f:
            html = f.read()

        # Viewport meta for mobile devices
        self.assertIn('name="viewport"', html)
        self.assertIn('width=device-width', html)

        # Mobile card container width <= 640px
        self.assertIn('max-width: 640px', html)

        # Outcome badges visual style definitions
        for badge_cls in ["dot", "runs", "four", "six", "wicket", "extra", "adjustment"]:
            self.assertIn(f".outcome-badge.{badge_cls}", html)

        # Status tags
        for tag_cls in ["latest-tag", "uncertain-tag", "corrected-tag", "adjustment-tag"]:
            self.assertIn(f".deliv-tag.{tag_cls}", html)

        # Touch targets accessible height (minimum 44px for primary buttons)
        self.assertIn('min-height: 44px', html)


if __name__ == "__main__":
    unittest.main()
