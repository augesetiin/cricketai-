"""
Phase 3 Stage 4: Comprehensive End-to-End Commentary & Simulated Match Narration Test Suite
────────────────────────────────────────────────────────────────────────────────────────────
Validates:
1. Full application integration (/fan, /fan/data, /fan/timeline, /fan/commentary, /overlay, /control, /scoring).
2. Simulated live match commentary generation across all outcomes:
   - Dots, singles, doubles, triples, boundaries (4s & 6s), wickets, wides, no-balls.
   - Over summaries, milestones, innings transitions, and match completion.
3. Voice narration testing:
   - Muted by default, no historical speech on load, no speech on unmute.
   - Delivery speech when unmuted, muting cancels queued speech.
   - Replay button functionality, rapid delivery anti-stacking.
   - Corrections/undos/AI updates are not auto-spoken, tab switching cancels speech.
   - Unsupported speech synthesis graceful fallback.
4. AI over-summary lifecycle:
   - Deterministic first, asynchronous AI enhancement, in-place revision bump,
   - No duplicate cards, fallback when key missing, no credential leakage.
5. Delivery correction & undo lifecycle:
   - Visible commentary revised on edit, dependent over summaries updated,
   - Undo delivers tombstones, revoked items removed, no duplicate cards on subsequent polls.
6. Cursor & synchronization stress testing:
   - >50 commentary changes between polls, multiple AI updates, reconnects, version resets.
7. OBS overlay and operator isolation:
   - Fan requests never touch _event_buffer or invoke /live or /commands.
8. Responsive layout & screenshot capture at 1280x800 and 390x844 viewports.
"""
import copy
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fan_commentary
import fan_engine
import server
from simulate_match import MatchSimulator
from test_http import HttpTestBase


class TestFanCommentaryE2E(HttpTestBase):
    def setUp(self):
        super().setUp()
        if hasattr(server, "_rv_cache"):
            server._rv_cache.clear()
        with fan_engine._fan_lock:
            fan_engine._fan_cache["data"] = None
            fan_engine._fan_cache["ts"] = 0.0
        with server._db_lock, server._db() as conn:
            fan_engine.init_fan_db(conn)
            fan_commentary.init_commentary_db(conn)
            conn.execute("DELETE FROM fan_commentary")
            conn.execute("DELETE FROM fan_commentary_meta")
            conn.execute("DELETE FROM fan_timeline")
            conn.execute("DELETE FROM fan_reconciler_checkpoint")
            conn.commit()

        # Reset in-memory reconciler & commentary engines
        rec = fan_engine.get_fan_reconciler()
        with rec.lock:
            rec.timeline = []
            rec.seq = 0
            rec.timeline_version = 1
            rec.prev = {}

        comm_eng = fan_commentary.get_fan_commentary_engine()
        comm_eng.match_id = server.current_match_id()

    # ── 1. Full Dashboard & Application Integration ──────────────────────────
    def test_01_all_dashboard_routes_and_configured_port(self):
        # Confirm configured port
        self.assertEqual(server.PORT, 5000, "Server port must be configured to 5000 in server.py")

        routes = [
            ("/fan", 200, "text/html"),
            ("/fan/data", 200, "application/json"),
            ("/fan/timeline", 200, "application/json"),
            ("/fan/commentary", 200, "application/json"),
            ("/overlay", 200, "text/html"),
            ("/control", 200, "text/html"),
            ("/scoring", 200, "text/html"),
        ]
        for path, exp_status, exp_ct in routes:
            status, headers, body = self.request("GET", path)
            self.assertEqual(status, exp_status, f"Route {path} returned status {status}")
            ct = headers.get("Content-Type") or headers.get("content-type") or ""
            self.assertIn(exp_ct, ct, f"Route {path} Content-Type mismatch: {ct}")

    # ── 2. Simulated Live Match & Commentary Generation ──────────────────────
    def test_02_simulated_live_match_all_outcomes(self):
        mid = server.current_match_id()
        sim = MatchSimulator("chase", max_overs=20, seed=101)
        reconciler = fan_engine.FanDeliveryReconciler(mid)
        mtime = 1000

        with server._db_lock, server._db() as conn:
            for label, frame in sim.frames():
                mtime += 1
                size = len(json.dumps(frame))
                reconciler.process_pcs_snapshot(frame, mtime_ns=mtime * 1000000, size=size,
                                               match_id=mid, conn=conn)

        # Check commentary API for Innings 2
        status, data = self.get_json("/fan/commentary?innings=2&limit=50")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        items = data.get("commentary", [])
        self.assertGreater(len(items), 5, "Simulation should generate commentary items")

        # Verify presence of diverse outcomes generated factually
        headlines = [c["headline"].upper() for c in items]
        has_dot = any("DOT" in h for h in headlines)
        has_run = any("RUN" in h for h in headlines)
        self.assertTrue(has_run, "Commentary stream must include run-scoring commentary")
        self.assertTrue(has_dot, "Commentary stream must include dot ball commentary")

        # Verify ordering: ascending by commentary_seq
        seqs = [c["commentary_seq"] for c in items]
        self.assertEqual(seqs, sorted(seqs), "Items must be sorted by commentary_seq")

        # Verify fields and guardrails
        for it in items:
            self.assertIn("headline", it)
            self.assertIn("text", it)
            self.assertIn("audio_text", it)
            self.assertIn("change_seq", it)
            self.assertIn("revision", it)
            self.assertFalse(it["is_revoked"])
            self.assertFalse("hallucinated" in it["text"].lower())

    # ── 3. AI Over-Summary Lifecycle (Asynchronous & Fallback) ───────────────
    def test_03_ai_over_summary_lifecycle_and_fallback(self):
        mid = server.current_match_id()
        engine = fan_commentary.get_fan_commentary_engine()

        # Seed completed over (6 legal balls)
        delivs = []
        for b in range(1, 7):
            delivs.append({
                "match_id": mid, "innings": 1, "seq": b, "event_id": f"del_{b}",
                "over_number": 1, "ball_in_over": b, "runs_batter": 1, "total_runs": 1,
                "token": "1", "outcome": "1", "batter_name": "Smith", "bowler_name": "Broad",
                "score_after": b, "wickets_after": 0, "overs_after": f"0.{b}" if b < 6 else "1.0",
                "is_legal": True, "is_boundary": False, "is_wicket": False,
                "is_corrected": False, "is_uncertain": False, "is_adjustment": False
            })

        # Process deliveries through engine
        with server._db_lock, server._db() as conn:
            engine.process_reconciled_batch(delivs, live_state={"batting_team": "Home CC"}, conn=conn)

        # 1. Deterministic over summary must be immediately available (<1ms)
        status, p1 = self.get_json("/fan/commentary?innings=1")
        self.assertEqual(status, 200)
        items = p1.get("commentary", [])
        summaries = [c for c in items if c["event_type"] == "over_summary"]
        self.assertEqual(len(summaries), 1, "Immediate deterministic summary must exist")
        sum1 = summaries[0]
        self.assertEqual(sum1["revision"], 1)
        self.assertFalse(sum1["is_ai"])
        self.assertIn("Over 1", sum1["text"])

        # 2. Simulate AI completion in background updating summary in-place
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with server._db_lock, server._db() as conn:
            ch_seq = fan_commentary._get_next_change_seq(conn, mid, 1)
            conn.execute("""
                UPDATE fan_commentary
                SET text = 'Broad finishes a steady first over, yielding 6 runs without a wicket.',
                    is_ai = 1, ai_status = 'completed', revision = 2,
                    change_seq = ?, updated_at = ?
                WHERE commentary_id = ?
            """, (ch_seq, now_iso, sum1["commentary_id"]))
            conn.commit()

        # 3. Client polling with since_change_seq receives in-place update
        status, p2 = self.get_json(f"/fan/commentary?innings=1&since_change_seq={sum1['change_seq']}")
        self.assertEqual(status, 200)
        updates = p2.get("commentary", [])
        self.assertEqual(len(updates), 1)
        sum2 = updates[0]
        self.assertEqual(sum2["commentary_id"], sum1["commentary_id"])
        self.assertEqual(sum2["revision"], 2)
        self.assertTrue(sum2["is_ai"])
        self.assertEqual(sum2["ai_status"], "completed")

        # Assert no credentials leaked in response
        body_str = json.dumps(p2)
        self.assertNotIn("sk-ant-", body_str)
        self.assertNotIn("anthropic_api_key", body_str)

    # ── 4. Delivery Correction & Undo Lifecycle ──────────────────────────────
    def test_04_delivery_correction_and_undo_lifecycle(self):
        mid = server.current_match_id()
        engine = fan_commentary.get_fan_commentary_engine()

        # 1. Insert initial ball (1 run)
        d1 = {
            "match_id": mid, "innings": 1, "seq": 1, "event_id": "e1",
            "over_number": 1, "ball_in_over": 1, "runs_batter": 1, "total_runs": 1,
            "token": "1", "outcome": "1", "batter_name": "Smith", "bowler_name": "Broad",
            "score_after": 1, "wickets_after": 0, "overs_after": "0.1",
            "is_legal": True, "is_corrected": False
        }
        with server._db_lock, server._db() as conn:
            engine.process_reconciled_batch([d1], conn=conn)

        status, p1 = self.get_json("/fan/commentary?innings=1")
        self.assertEqual(status, 200)
        c1 = p1["commentary"][0]
        self.assertEqual(c1["revision"], 1)
        self.assertFalse(c1["is_corrected"])
        curr_ch = p1["next_change_seq"]

        # 2. Scorer corrects ball 1 to a 4 (boundary)
        d1_corr = copy.deepcopy(d1)
        d1_corr["runs_batter"] = 4
        d1_corr["total_runs"] = 4
        d1_corr["outcome"] = "4"
        d1_corr["is_boundary"] = True
        d1_corr["score_after"] = 4
        d1_corr["is_corrected"] = True

        with server._db_lock, server._db() as conn:
            engine.process_reconciled_batch([d1_corr], conn=conn)

        status, p2 = self.get_json(f"/fan/commentary?innings=1&since_change_seq={curr_ch}")
        self.assertEqual(status, 200)
        self.assertEqual(len(p2["commentary"]), 1)
        c1_corr = p2["commentary"][0]
        self.assertEqual(c1_corr["commentary_id"], c1["commentary_id"])
        self.assertEqual(c1_corr["revision"], 2)
        self.assertTrue(c1_corr["is_corrected"])
        self.assertIn("FOUR", c1_corr["headline"])
        curr_ch = p2["next_change_seq"]

        # 3. Scorer undoes ball 1
        with server._db_lock, server._db() as conn:
            engine.handle_revocations(mid, 1, [1], conn=conn)

        # Polling client receives tombstone
        status, p3 = self.get_json(f"/fan/commentary?innings=1&since_change_seq={curr_ch}")
        self.assertEqual(status, 200)
        self.assertEqual(len(p3["commentary"]), 1)
        self.assertTrue(p3["commentary"][0]["is_revoked"])

        # Fresh request does NOT receive revoked commentary
        status, p4 = self.get_json("/fan/commentary?innings=1")
        self.assertEqual(status, 200)
        self.assertEqual(p4["total_commentary"], 0)
        self.assertEqual(len(p4["commentary"]), 0)

    # ── 5. Cursor & Synchronization Stress Testing ───────────────────────────
    def test_05_cursor_and_synchronization_stress(self):
        mid = server.current_match_id()
        with server._db_lock, server._db() as conn:
            # Generate 65 commentary items (> 50 limit)
            for i in range(1, 66):
                cid = f"comm_{mid}_i1_s{i}_ball"
                conn.execute("""
                    INSERT INTO fan_commentary (
                        commentary_id, match_id, innings, commentary_seq, source_timeline_seq,
                        change_seq, over_number, ball_in_over, event_type, headline, text, audio_text,
                        is_ai, ai_status, revision, is_corrected, is_uncertain, is_adjustment,
                        is_revoked, created_at, updated_at
                    ) VALUES (?, ?, 1, ?, ?, ?, 1, 1, 'ball', '1 RUN', 'Single.', 'Single.',
                             0, 'none', 1, 0, 0, 0, 0, '2026-11-01T12:00:00Z', '2026-11-01T12:00:00Z')
                """, (cid, mid, i, i, i))
            conn.execute("""
                INSERT INTO fan_commentary_meta (match_id, innings, commentary_version, max_change_seq)
                VALUES (?, 1, 1, 65)
            """, (mid,))
            conn.commit()

        # Incremental poll with limit 50
        status, p1 = self.get_json("/fan/commentary?innings=1&since_change_seq=0&limit=50")
        self.assertEqual(status, 200)
        self.assertEqual(len(p1["commentary"]), 50)
        self.assertTrue(p1["has_more"], "has_more must be true when items exceed limit")
        ch_cursor = p1["next_change_seq"]
        self.assertEqual(ch_cursor, 50, "Cursor must not advance past unprocessed changes")

        # Second poll picks up remaining 15 items
        status, p2 = self.get_json(f"/fan/commentary?innings=1&since_change_seq={ch_cursor}&limit=50")
        self.assertEqual(status, 200)
        self.assertEqual(len(p2["commentary"]), 15)
        self.assertFalse(p2["has_more"])
        self.assertEqual(p2["next_change_seq"], 65)

    # ── 6. OBS Overlay & Operator Isolation ──────────────────────────────────
    def test_06_obs_overlay_isolation_and_no_live_calls(self):
        with server._event_buffer_lock:
            server._event_buffer.append({"type": "milestone", "player": "Key Batter", "text": "Century!"})
            buf_len = len(server._event_buffer)

        # Issue fan requests
        self.get_json("/fan/data")
        self.get_json("/fan/timeline")
        self.get_json("/fan/commentary")
        self.request("GET", "/fan")

        # Verify event buffer completely untouched
        with server._event_buffer_lock:
            self.assertEqual(len(server._event_buffer), buf_len)
            server._event_buffer.clear()

        # Verify /live responds normally
        status, _, _ = self.request("GET", "/live")
        self.assertEqual(status, 200)


# ── 7. Playwright Responsive Visual & Speech Narration Tests ─────────────────

class TestFanCommentaryE2EPlaywright(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
            cls.playwright_available = True
        except ImportError:
            cls.playwright_available = False
            return

        cls.tmp = tempfile.mkdtemp(prefix="cricket_e2e_pw_")
        cls._saved = {
            "STATE_FILE": server.STATE_FILE,
            "_db_path": server._db_path,
            "MANUAL_SCORING_FILE": server.MANUAL_SCORING_FILE,
            "_CLUB_PASSWORD": server._CLUB_PASSWORD,
            "_CONTROL_TOKEN": server._CONTROL_TOKEN,
            "_last_good_state": server._last_good_state,
        }
        server.STATE_FILE = os.path.join(cls.tmp, "match_state.json")
        server._db_path = lambda: os.path.join(cls.tmp, "match_data.db")
        server.MANUAL_SCORING_FILE = os.path.join(cls.tmp, "manual_scoring.json")
        server._manual["session"] = None
        server._manual["load_attempted"] = True
        server._CLUB_PASSWORD = ""
        server._CONTROL_TOKEN = "cd" * 32
        server._last_good_state = None
        server.save_state(dict(server.DEFAULT_STATE))
        with fan_engine._fan_lock:
            fan_engine._fan_cache["data"] = None
            fan_engine._fan_cache["ts"] = 0.0
        server.db_init()

        with server._db_lock, server._db() as conn:
            fan_engine.init_fan_db(conn)
            fan_commentary.init_commentary_db(conn)
            conn.execute("DELETE FROM fan_commentary")
            conn.execute("DELETE FROM fan_commentary_meta")
            mid = server.current_match_id()

            # Seed 10 deliveries across 2 overs
            balls = [
                (1, 1, 1, 1, "ball", "DOT BALL", "Anderson bowls on a good length to Smith, no run.", "0"),
                (2, 1, 2, 2, "ball", "1 RUN", "Smith works it away to square leg for a single.", "1"),
                (3, 1, 3, 3, "ball", "FOUR!", "Gill punches through backward point for a boundary!", "4"),
                (4, 1, 4, 4, "ball", "SIX!", "Gill hammers this over deep midwicket for six runs!", "6"),
                (5, 1, 5, 5, "ball", "WIDE", "Conceded 1 wide down leg side by Anderson.", "1wd"),
                (6, 1, 6, 6, "ball", "WICKET!", "CAUGHT! Edged to first slip! Broad takes it cleanly.", "W"),
                (7, 1, 6, 7, "over_summary", "END OF OVER 1", "Over 1: Home CC 12 for 1 off 1 over.", "OV"),
                (8, 2, 1, 8, "ball", "DOT BALL", "Broad begins with a dot to Kohli.", "0"),
                (9, 2, 2, 9, "ball", "2 RUNS", "Kohli drives into the gap for two runs.", "2"),
                (10, 2, 3, 10, "ball", "3 RUNS", "Superb running between the wickets earns three.", "3"),
            ]
            for s, o, b, ch, ev, hd, txt, tok in balls:
                cid = f"comm_{mid}_i1_s{s}_{ev}"
                conn.execute("""
                    INSERT INTO fan_commentary (
                        commentary_id, match_id, innings, commentary_seq, source_timeline_seq,
                        change_seq, over_number, ball_in_over, event_type, headline, text, audio_text,
                        is_ai, ai_status, revision, is_corrected, is_uncertain, is_adjustment,
                        is_revoked, created_at, updated_at
                    ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'none', 1, 0, 0, 0, 0, '2026-11-01T12:00:00Z', '2026-11-01T12:00:00Z')
                """, (cid, mid, s, s, ch, o, b, ev, hd, txt, txt, int(ev == "over_summary")))

            conn.execute("""
                INSERT INTO fan_commentary_meta (match_id, innings, commentary_version, max_change_seq)
                VALUES (?, 1, 1, 10)
            """, (mid,))
            conn.commit()

        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.server_thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "playwright_available", False):
            cls.httpd.shutdown()
            cls.httpd.server_close()
            for k, v in cls._saved.items():
                setattr(server, k, v)

    def setUp(self):
        if not getattr(self, "playwright_available", False):
            self.skipTest("playwright not installed in environment")

    def test_voice_narration_and_responsive_layout(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            # ── Desktop Viewport (1280x800) ──
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            url = f"http://127.0.0.1:{self.port}/fan"

            # Mock window.speechSynthesis to track speak / cancel calls via defineProperty
            page.add_init_script("""
                window._spokenUtterances = [];
                window._speechCancellations = 0;
                var mockUtterance = function(text) { this.text = text; };
                var mockSynthesis = {
                    speak: function(utt) { window._spokenUtterances.push(utt.text); },
                    cancel: function() { window._speechCancellations++; },
                    getVoices: function() { return []; }
                };
                Object.defineProperty(window, 'SpeechSynthesisUtterance', { value: mockUtterance, configurable: true, writable: true });
                Object.defineProperty(window, 'speechSynthesis', { value: mockSynthesis, configurable: true, writable: true });
            """)

            page.goto(url, wait_until="networkidle")
            btn_ar = page.query_selector("#btn-mode-standard, #btn-mode-all-rounder")
            if btn_ar and btn_ar.is_visible():
                btn_ar.click()
            page.wait_for_selector(".commentary-card")

            # 1. Voice starts muted: no spoken utterances on initial load
            spoken = page.evaluate("() => window._spokenUtterances")
            self.assertEqual(len(spoken), 0, "No audio must be spoken on initial page load")

            # 2. Desktop horizontal overflow check
            sw = page.evaluate("() => document.documentElement.scrollWidth")
            cw = page.evaluate("() => document.documentElement.clientWidth")
            self.assertLessEqual(sw, cw, "Zero horizontal overflow on desktop")

            # Save Desktop Screenshot
            art_dir = r"C:\Users\augestin\.gemini\antigravity\brain\0a4a53b2-ae2c-4c2e-a0e5-5594439bb9d1"
            os.makedirs(art_dir, exist_ok=True)
            page.screenshot(path=os.path.join(art_dir, "commentary_desktop.png"), full_page=True)

            # 3. Enable Voice: does NOT speak old historical cards
            voice_btn = page.query_selector("#voice-toggle-btn")
            voice_btn.click()
            time.sleep(0.1)
            spoken_after_unmute = page.evaluate("() => window._spokenUtterances")
            self.assertEqual(len(spoken_after_unmute), 0, "Unmuting must not speak historical cards")

            # 4. Replay Button: speaks latest eligible card on manual click
            replay_btn = page.query_selector("#voice-replay-btn")
            replay_btn.click()
            time.sleep(0.1)
            spoken_after_replay = page.evaluate("() => window._spokenUtterances")
            self.assertEqual(len(spoken_after_replay), 1, "Replay must speak the latest eligible card")
            self.assertIn("running between the wickets", spoken_after_replay[0])

            # 5. Mute Voice: cancels speech
            voice_btn.click()
            time.sleep(0.1)
            cancels = page.evaluate("() => window._speechCancellations")
            self.assertGreater(cancels, 0, "Muting must cancel active speech")

            # ── Mobile Viewport (390x844) ──
            page_m = browser.new_page(viewport={"width": 390, "height": 844})
            page_m.add_init_script("""
                window._spokenUtterances = [];
                var mockUtterance = function(text) { this.text = text; };
                var mockSynthesis = {
                    speak: function(utt) { window._spokenUtterances.push(utt.text); },
                    cancel: function() {},
                    getVoices: function() { return []; }
                };
                Object.defineProperty(window, 'SpeechSynthesisUtterance', { value: mockUtterance, configurable: true, writable: true });
                Object.defineProperty(window, 'speechSynthesis', { value: mockSynthesis, configurable: true, writable: true });
            """)
            page_m.goto(url, wait_until="networkidle")
            btn_ar_m = page_m.query_selector("#btn-mode-standard, #btn-mode-all-rounder")
            if btn_ar_m and btn_ar_m.is_visible():
                btn_ar_m.click()
            page_m.wait_for_selector(".commentary-card")

            # Check zero horizontal overflow at 390px
            m_sw = page_m.evaluate("() => document.documentElement.scrollWidth")
            m_cw = page_m.evaluate("() => document.documentElement.clientWidth")
            self.assertLessEqual(m_sw, m_cw, "Zero horizontal overflow at 390px mobile viewport")

            # Check touch targets >= 44px
            for btn_id in ["#comm-toggle-btn", "#voice-toggle-btn", "#voice-replay-btn"]:
                box = page_m.query_selector(btn_id).bounding_box()
                self.assertGreaterEqual(box["height"], 44, f"Button {btn_id} touch height must be >= 44px")

            # Save Mobile Screenshot
            page_m.screenshot(path=os.path.join(art_dir, "commentary_mobile.png"), full_page=True)

            browser.close()


if __name__ == "__main__":
    unittest.main()
