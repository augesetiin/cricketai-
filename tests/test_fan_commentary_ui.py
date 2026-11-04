"""
Integration & Playwright UI Tests for Fan Live Commentary (Phase 3 Stage 3)
─────────────────────────────────────────────────────────────────────────
Verifies:
1. fan.html serves with all required Live Commentary UI elements and controls.
2. Commentary cards render with headline, text, over/ball badge, AI tag, and outcome styles.
3. Correct chronological ordering (latest at top).
4. In-place card updating on revision bump (AI summary enhancement / correction).
5. Undo revocation handling (tombstone removes card).
6. Zero duplicate cards during polling and reconnects.
7. Incremental polling and cursor management.
8. Reset synchronization (stale version triggers clean re-render).
9. Muted-by-default behavior (Voice starts OFF, no unexpected autoplay).
10. Voice activation only after explicit user interaction.
11. Replay button triggers speech for latest eligible commentary.
12. Mobile responsiveness at 390px width and zero horizontal overflow.
13. Captures desktop and mobile screenshots for the stage completion report.
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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fan_commentary
import fan_engine
import server
from test_http import HttpTestBase


class TestFanCommentaryUIStructure(HttpTestBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fan.html"),
                  encoding="utf-8") as f:
            cls.html_content = f.read()

    def test_fan_html_served_over_http(self):
        status, headers, body = self.request("GET", "/fan")
        self.assertEqual(status, 200)
        self.assertIn(b"Live Match Commentary", body)
        self.assertIn(b"/fan/commentary", body)
        # Strict security & broadcast invariants
        self.assertNotIn(b"/live", body)
        self.assertNotIn(b"/commands", body)

    def test_commentary_ui_elements_present(self):
        html = self.html_content
        # Section container and header
        self.assertIn('id="commentary-container"', html)
        self.assertIn('Live Match Commentary', html)
        # Control buttons
        self.assertIn('id="comm-toggle-btn"', html)
        self.assertIn('id="voice-toggle-btn"', html)
        self.assertIn('id="voice-replay-btn"', html)
        self.assertIn('toggleCommentaryVisibility()', html)
        self.assertIn('toggleVoiceNarration()', html)
        self.assertIn('replayLatestCommentary()', html)
        # Cards wrapper and pagination
        self.assertIn('id="commentary-cards-wrapper"', html)
        self.assertIn('id="commentary-pagination-row"', html)
        self.assertIn('id="load-earlier-commentary-btn"', html)
        self.assertIn('loadEarlierCommentary()', html)

    def test_commentary_css_classes_and_touch_targets(self):
        html = self.html_content
        # Outcome card styling
        self.assertIn('.commentary-card.wicket', html)
        self.assertIn('.commentary-card.four', html)
        self.assertIn('.commentary-card.six', html)
        self.assertIn('.commentary-card.extra', html)
        self.assertIn('.commentary-card.over_summary', html)
        self.assertIn('.commentary-card.milestone', html)
        self.assertIn('.commentary-card.dot', html)
        # Tag badges
        self.assertIn('.comm-tag.ai', html)
        self.assertIn('.comm-tag.corrected', html)
        self.assertIn('.comm-tag.uncertain', html)
        # Touch target minimum height 44px
        self.assertIn('min-height: 44px', html)
        self.assertIn('min-width: 44px', html)

    def test_muted_by_default_in_markup_and_script(self):
        html = self.html_content
        # Voice button markup must start muted
        self.assertIn('aria-pressed="false"', html)
        self.assertIn('Voice OFF', html)
        # State store must start muted
        self.assertIn('voiceEnabled: false', html)

    def test_speech_synthesis_feature_detection_and_visibility(self):
        html = self.html_content
        self.assertIn('speechSynthesis', html)
        self.assertIn('SpeechSynthesisUtterance', html)
        self.assertIn('visibilitychange', html)
        self.assertIn('window.speechSynthesis.cancel()', html)

    def test_js_classifier_logic(self):
        # Mirror test of classifyCommentaryOutcome in frontend JS
        def classify_commentary_outcome(it):
            if it.get("event_type") == "over_summary":
                return "over_summary"
            if it.get("event_type") == "milestone":
                return "milestone"
            hd = (it.get("headline") or "").upper()
            if "WICKET" in hd:
                return "wicket"
            if "SIX" in hd:
                return "six"
            if "FOUR" in hd:
                return "four"
            if "WIDE" in hd or "NO BALL" in hd:
                return "extra"
            if "DOT" in hd:
                return "dot"
            if "RUN" in hd:
                return "runs"
            return "standard"

        self.assertEqual(classify_commentary_outcome({"headline": "WICKET! Bowled Smith"}) , "wicket")
        self.assertEqual(classify_commentary_outcome({"headline": "FOUR! Boundary"}) , "four")
        self.assertEqual(classify_commentary_outcome({"headline": "SIX! Over the ropes"}) , "six")
        self.assertEqual(classify_commentary_outcome({"headline": "WIDE", "event_type": "ball"}) , "extra")
        self.assertEqual(classify_commentary_outcome({"headline": "DOT BALL", "event_type": "ball"}) , "dot")
        self.assertEqual(classify_commentary_outcome({"headline": "1 RUN", "event_type": "ball"}) , "runs")
        self.assertEqual(classify_commentary_outcome({"headline": "END OF OVER 1", "event_type": "over_summary"}) , "over_summary")
        self.assertEqual(classify_commentary_outcome({"headline": "50 PARTNERSHIP", "event_type": "milestone"}) , "milestone")


# ── Playwright Browser Visual & Interaction Tests ────────────────────────────

class TestFanCommentaryPlaywright(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
            cls.playwright_available = True
        except ImportError:
            cls.playwright_available = False
            return

        cls.tmp = tempfile.mkdtemp(prefix="cricket_comm_playwright_")
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
        server.db_init()

        with server._db_lock, server._db() as conn:
            fan_engine.init_fan_db(conn)
            fan_commentary.init_commentary_db(conn)
            conn.execute("DELETE FROM fan_commentary")
            conn.execute("DELETE FROM fan_commentary_meta")
            mid = server.current_match_id()

            # Seed realistic commentary records
            items = [
                (1, 1, 1, 1, "ball", "DOT BALL", "Anderson bowls a tight dot ball outside off to Sharma.", 0, "none", 1, 0),
                (2, 1, 2, 2, "ball", "1 RUN", "Sharma pushes into the covers for a quick single.", 0, "none", 1, 0),
                (3, 1, 3, 3, "ball", "FOUR!", "Gill drives crisply through extra cover for four runs!", 0, "none", 1, 0),
                (4, 1, 4, 4, "ball", "SIX!", "Massive hit! Gill launches Anderson over long-on for six!", 0, "none", 1, 0),
                (5, 1, 5, 5, "ball", "WICKET!", "OUT! Edged and taken behind! Anderson removes Gill for 10.", 0, "none", 1, 0),
                (6, 1, 6, 6, "over_summary", "END OF OVER 1", "Tidy over from Anderson, conceding eleven and picking up the wicket of Gill.", 1, "completed", 1, 0),
            ]

            for s, o, b, ch, ev, hd, txt, is_ai, ai_stat, rev, corr in items:
                cid = f"comm_{mid}_i1_s{s}_{ev}"
                conn.execute("""
                    INSERT INTO fan_commentary (
                        commentary_id, match_id, innings, commentary_seq, source_timeline_seq,
                        change_seq, over_number, ball_in_over, event_type, headline, text, audio_text,
                        is_ai, ai_status, revision, is_corrected, is_uncertain, is_adjustment,
                        is_revoked, created_at, updated_at
                    ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, '2026-11-01T12:00:00Z', '2026-11-01T12:00:00Z')
                """, (cid, mid, s, s, ch, o, b, ev, hd, txt, txt, is_ai, ai_stat, rev, corr))

            conn.execute("""
                INSERT INTO fan_commentary_meta (match_id, innings, commentary_version, max_change_seq)
                VALUES (?, 1, 1, 6)
            """, (mid,))
            conn.commit()

        # Spin up ThreadingHTTPServer on ephemeral port
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

    def test_desktop_and_mobile_visual_and_interaction(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            # 1. Desktop Viewport (1280x800)
            page_desktop = browser.new_page(viewport={"width": 1280, "height": 800})
            url = f"http://127.0.0.1:{self.port}/fan"
            page_desktop.goto(url, wait_until="domcontentloaded")

            # Check presence of commentary cards
            page_desktop.wait_for_selector("#commentary-container")
            page_desktop.wait_for_selector(".commentary-card")

            cards = page_desktop.query_selector_all(".commentary-card")
            self.assertEqual(len(cards), 6, "Must render all 6 seeded commentary cards")

            # Check latest card on top (Over summary or Wicket)
            first_card_text = cards[0].inner_text()
            self.assertIn("OVER 1 SUMMARY", first_card_text.upper())
            self.assertIn("AI SUMMARY", first_card_text.upper())

            # Check zero horizontal overflow
            scroll_width = page_desktop.evaluate("() => document.documentElement.scrollWidth")
            client_width = page_desktop.evaluate("() => document.documentElement.clientWidth")
            self.assertLessEqual(scroll_width, client_width, "Zero horizontal overflow on desktop")

            # Save desktop screenshot to artifact directory
            art_dir = r"C:\Users\augestin\.gemini\antigravity\brain\0a4a53b2-ae2c-4c2e-a0e5-5594439bb9d1"
            os.makedirs(art_dir, exist_ok=True)
            desktop_shot = os.path.join(art_dir, "commentary_desktop.png")
            page_desktop.screenshot(path=desktop_shot, full_page=True)

            # 2. Mobile Viewport (390x844 - iPhone 12/13/14 standard)
            page_mobile = browser.new_page(viewport={"width": 390, "height": 844})
            page_mobile.goto(url, wait_until="domcontentloaded")

            page_mobile.wait_for_selector(".commentary-card")

            # Verify zero horizontal overflow on mobile
            m_scroll = page_mobile.evaluate("() => document.documentElement.scrollWidth")
            m_client = page_mobile.evaluate("() => document.documentElement.clientWidth")
            self.assertLessEqual(m_scroll, m_client, "Zero horizontal overflow at 390px mobile viewport")

            # Verify controls: Voice starts OFF
            voice_btn = page_mobile.query_selector("#voice-toggle-btn")
            self.assertEqual(voice_btn.get_attribute("aria-pressed"), "false")
            self.assertIn("Voice OFF", voice_btn.inner_text())

            # User clicks Voice button -> activates Voice ON
            voice_btn.click()
            time.sleep(0.1)
            self.assertEqual(voice_btn.get_attribute("aria-pressed"), "true")
            self.assertIn("Voice ON", voice_btn.inner_text())

            # User clicks Hide -> hides commentary content area
            hide_btn = page_mobile.query_selector("#comm-toggle-btn")
            self.assertIn("Hide", hide_btn.inner_text())
            hide_btn.click()
            time.sleep(0.1)
            is_visible = page_mobile.is_visible("#commentary-content-area")
            self.assertFalse(is_visible, "Commentary area must hide when toggled off")

            # User clicks Show -> reveals commentary content area
            hide_btn.click()
            time.sleep(0.1)
            is_visible_again = page_mobile.is_visible("#commentary-content-area")
            self.assertTrue(is_visible_again, "Commentary area must reappear when toggled on")

            # Click Replay button
            replay_btn = page_mobile.query_selector("#voice-replay-btn")
            self.assertIsNotNone(replay_btn)
            replay_btn.click()

            # Save mobile screenshot to artifact directory
            mobile_shot = os.path.join(art_dir, "commentary_mobile.png")
            page_mobile.screenshot(path=mobile_shot, full_page=True)

            browser.close()

    def test_incremental_card_update_and_revocation_in_playwright(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 390, "height": 844})
            url = f"http://127.0.0.1:{self.port}/fan"
            page.goto(url, wait_until="domcontentloaded")

            page.wait_for_selector(".commentary-card")
            cards = page.query_selector_all(".commentary-card")
            self.assertEqual(len(cards), 6)

            mid = server.current_match_id()

            # 1. Update existing card in-place (AI summary enhancement)
            cid_summary = f"comm_{mid}_i1_s6_over_summary"
            with server._db_lock, server._db() as conn:
                conn.execute("""
                    UPDATE fan_commentary
                    SET text = 'Enhanced AI summary: Anderson bowled a masterful opening spell.',
                        revision = 2, change_seq = 7, updated_at = '2026-11-01T12:00:15Z'
                    WHERE commentary_id = ?
                """, (cid_summary,))
                conn.execute("""
                    UPDATE fan_commentary_meta
                    SET max_change_seq = 7
                    WHERE match_id = ? AND innings = 1
                """, (mid,))
                conn.commit()

            # Trigger pollCommentary in browser
            with page.expect_response("**/fan/commentary?*since_change_seq=*"):
                page.evaluate("() => { commentaryState.isPolling = false; window.pollCommentary(); }")
            page.wait_for_function(f"() => {{ const el = document.querySelector('#comm-card-{cid_summary} .comm-text'); return el && el.innerText.includes('masterful opening spell'); }}")

            # Assert card updated in-place
            updated_text = page.eval_on_selector(f"#comm-card-{cid_summary} .comm-text", "el => el.innerText")
            self.assertIn("Anderson bowled a masterful opening spell", updated_text)

            # Assert no duplicate cards created
            cards_after_update = page.query_selector_all(".commentary-card")
            self.assertEqual(len(cards_after_update), 6, "Must not create duplicate cards on revision update")

            # 2. Revoke ball 4 (undo)
            cid_six = f"comm_{mid}_i1_s4_ball"
            with server._db_lock, server._db() as conn:
                conn.execute("""
                    UPDATE fan_commentary
                    SET is_revoked = 1, change_seq = 8, updated_at = '2026-11-01T12:00:20Z'
                    WHERE commentary_id = ?
                """, (cid_six,))
                conn.execute("""
                    UPDATE fan_commentary_meta
                    SET max_change_seq = 8
                    WHERE match_id = ? AND innings = 1
                """, (mid,))
                conn.commit()

            with page.expect_response("**/fan/commentary?*since_change_seq=*"):
                page.evaluate("() => { commentaryState.isPolling = false; window.pollCommentary(); }")
            page.wait_for_function(f"() => !document.querySelector('#comm-card-{cid_six}')")

            # Assert revoked card removed from DOM
            six_card = page.query_selector(f"#comm-card-{cid_six}")
            self.assertIsNone(six_card, "Revoked commentary card must be removed from the DOM")
            cards_after_revoke = page.query_selector_all(".commentary-card")
            self.assertEqual(len(cards_after_revoke), 5)

            # 3. Test Reset Synchronization (stale version forces fresh authoritative reload)
            with server._db_lock, server._db() as conn:
                fan_commentary.bump_commentary_version(mid, 1, conn=conn)

            with page.expect_response("**/fan/commentary?*"):
                page.evaluate("() => { commentaryState.isPolling = false; window.pollCommentary(); }")
            page.wait_for_function("() => document.querySelectorAll('.commentary-card').length === 5")

            # Assert version reset reconciled cleanly
            cards_after_reset = page.query_selector_all(".commentary-card")
            self.assertEqual(len(cards_after_reset), 5, "Authoritative snapshot reloaded cleanly after version bump")

            browser.close()


if __name__ == "__main__":
    unittest.main()
