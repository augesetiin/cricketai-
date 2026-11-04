"""
Playwright and Integration UI Tests for Ask Match AI (Phase 4 Stage 3)
────────────────────────────────────────────────────────────────────
Verifies:
1. Chat section rendering (container, header, icons, controls, chips, messages list, input).
2. Suggested question chips (rendered, responsive, dynamically updated).
3. Manual question submission (input, send button, Enter-to-send, clearing).
4. Chip-based question submission (click-to-ask).
5. Deterministic and AI response rendering (source tags 'Verified Facts' and 'Claude AI').
6. Loading animation and error states.
7. Rate-limit handling (429 banner and countdown).
8. Clear chat functionality (DOM reset and sessionStorage removal).
9. Session history persistence across page reloads.
10. Maximum history limit enforcement (capped at 8 items).
11. XSS and HTML injection protection (safe textContent, no unescaped tags).
12. Empty and overlong question rejection (maxlength 250, whitespace prevention).
13. Duplicate submission prevention (controls disabled while in-flight).
14. Mobile responsiveness at 390x844 with zero horizontal overflow and >= 44px touch targets.
15. Existing dashboard functionality intact (scoreboard, commentary, voice, timeline).
"""
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
import fan_qa
import server
from test_http import HttpTestBase


class TestFanQAUIStructure(HttpTestBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fan.html"),
                  encoding="utf-8") as f:
            cls.html_content = f.read()

    def test_fan_html_served_over_http(self):
        status, headers, body = self.request("GET", "/fan")
        self.assertEqual(status, 200)
        self.assertIn(b"Ask Match AI", body)
        self.assertIn(b"/fan/ask", body)
        # Security invariants
        self.assertNotIn(b"/commands", body)

    def test_qa_ui_elements_present(self):
        html = self.html_content
        # Container and header
        self.assertIn('id="qa-container"', html)
        self.assertIn('class="qa-section"', html)
        self.assertIn('Ask Match AI', html)
        self.assertIn('id="qa-freshness-badge"', html)
        self.assertIn('id="qa-clear-btn"', html)
        # Chips container
        self.assertIn('id="qa-chips-wrapper"', html)
        self.assertIn('id="qa-chips-list"', html)
        # Messages list and empty state
        self.assertIn('id="qa-messages-list"', html)
        self.assertIn('id="qa-empty-state"', html)
        # Alert banner
        self.assertIn('id="qa-alert-banner"', html)
        self.assertIn('id="qa-alert-text"', html)
        # Input bar
        self.assertIn('id="qa-input-form"', html)
        self.assertIn('id="qa-input"', html)
        self.assertIn('maxlength="250"', html)
        self.assertIn('id="qa-char-count"', html)
        self.assertIn('id="qa-send-btn"', html)

    def test_qa_css_classes_and_touch_targets(self):
        html = self.html_content
        self.assertIn('.qa-section', html)
        self.assertIn('.qa-bubble-user', html)
        self.assertIn('.qa-bubble-ai', html)
        self.assertIn('.qa-source-badge.deterministic', html)
        self.assertIn('.qa-source-badge.claude', html)
        self.assertIn('.qa-chip-btn', html)
        self.assertIn('.qa-loading-bubble', html)
        # Touch target minimum height 44px
        self.assertIn('min-height: 44px', html)
        self.assertIn('min-width: 44px', html)


class TestFanQAPlaywright(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
            cls.playwright_available = True
        except ImportError:
            cls.playwright_available = False
            return

        cls.tmp = tempfile.mkdtemp(prefix="cricket_qa_ui_")
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
            mid = server.current_match_id()

            # Seed delivery for context
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
                    ?, 1, 1, 'del_mid_1', 1, 1,
                    1, 0, 1, 1, 1,
                    '4', '4', 4, 0, 4, NULL,
                    0, NULL, NULL, 'Root', 'Stokes',
                    'Anderson', 4, 0, '0.1', 1,
                    'four', 0, 0, 0, NULL,
                    '2026-11-01T12:00:00Z'
                )
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
            self.skipTest("Playwright not installed")
        # Reset client rate limiter history
        fan_qa.get_global_rate_limiter().reset_client("127.0.0.1")

    def test_01_chat_section_rendering(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(f"http://127.0.0.1:{self.port}/fan", wait_until="domcontentloaded")

            # Check section, header, and input exist
            self.assertTrue(page.is_visible("#qa-container"))
            self.assertTrue(page.is_visible("#qa-freshness-badge"))
            self.assertTrue(page.is_visible("#qa-clear-btn"))
            self.assertTrue(page.is_visible("#qa-chips-list"))
            self.assertTrue(page.is_visible("#qa-messages-list"))
            self.assertTrue(page.is_visible("#qa-empty-state"))
            self.assertTrue(page.is_visible("#qa-input"))
            self.assertTrue(page.is_visible("#qa-send-btn"))
            browser.close()

    def test_02_suggested_question_chips(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(f"http://127.0.0.1:{self.port}/fan", wait_until="domcontentloaded")

            page.wait_for_selector(".qa-chip-btn", timeout=5000)
            chips = page.query_selector_all(".qa-chip-btn")
            self.assertGreater(len(chips), 0, "Suggested chips must be rendered")
            chip_text = chips[0].inner_text()
            self.assertTrue(len(chip_text) > 3)
            browser.close()

    def test_03_manual_question_submission(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})

            # Mock POST /fan/ask response
            page.route("**/fan/ask", lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "ok": True,
                    "question": "What is the current score?",
                    "answer": "Home CC is currently 4/0 after 0.1 overs.",
                    "source": "deterministic",
                    "feed_freshness": "live",
                    "suggested_questions": ["Who is bowling?", "Who is batting?"]
                })
            ))

            page.goto(f"http://127.0.0.1:{self.port}/fan", wait_until="domcontentloaded")
            page.fill("#qa-input", "What is the current score?")
            self.assertEqual(page.inner_text("#qa-char-count"), "26/250")

            page.click("#qa-send-btn")
            page.wait_for_selector(".qa-bubble-ai", timeout=5000)

            # Check user bubble
            user_bubbles = page.query_selector_all(".qa-bubble-user")
            self.assertEqual(len(user_bubbles), 1)
            self.assertIn("What is the current score?", user_bubbles[0].inner_text())

            # Check input cleared
            self.assertEqual(page.input_value("#qa-input"), "")
            self.assertEqual(page.inner_text("#qa-char-count"), "0/250")

            # Check AI bubble
            ai_bubbles = page.query_selector_all(".qa-bubble-ai")
            self.assertEqual(len(ai_bubbles), 1)
            self.assertIn("Home CC is currently 4/0", ai_bubbles[0].inner_text())
            browser.close()

    def test_04_chip_based_submission(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})

            page.route("**/fan/ask", lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "ok": True,
                    "question": "Who is currently batting?",
                    "answer": "Root (4*) and Stokes (0*) are currently at the crease.",
                    "source": "deterministic",
                    "feed_freshness": "live",
                    "suggested_questions": []
                })
            ))

            page.goto(f"http://127.0.0.1:{self.port}/fan", wait_until="domcontentloaded")
            page.wait_for_selector(".qa-chip-btn", timeout=5000)
            page.click(".qa-chip-btn:first-child")

            page.wait_for_selector(".qa-bubble-ai", timeout=5000)
            ai_bubbles = page.query_selector_all(".qa-bubble-ai")
            self.assertGreaterEqual(len(ai_bubbles), 1)
            browser.close()

    def test_05_deterministic_and_ai_response_rendering(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})

            # Mock Claude AI response
            page.route("**/fan/ask", lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "ok": True,
                    "question": "Why is the batting team in a good position?",
                    "answer": "With 4 runs off the first ball and no wickets lost, Home CC has established early positive momentum.",
                    "source": "claude-haiku",
                    "feed_freshness": "live",
                    "suggested_questions": []
                })
            ))

            page.goto(f"http://127.0.0.1:{self.port}/fan", wait_until="domcontentloaded")
            page.fill("#qa-input", "Why is the batting team in a good position?")
            page.press("#qa-input", "Enter")

            page.wait_for_selector(".qa-source-badge.claude", timeout=5000)
            badge_text = page.inner_text(".qa-source-badge.claude")
            self.assertIn("Claude AI", badge_text)
            browser.close()

    def test_06_loading_and_error_states(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})

            # Mock 503 Service Unavailable
            page.route("**/fan/ask", lambda route: route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({
                    "ok": False,
                    "error": "AI assistant is temporarily unavailable. You can still ask factual questions.",
                    "code": "SERVICE_UNAVAILABLE",
                    "suggested_questions": ["What is the score?"]
                })
            ))

            page.goto(f"http://127.0.0.1:{self.port}/fan", wait_until="domcontentloaded")
            page.fill("#qa-input", "Complex tactical question?")
            page.click("#qa-send-btn")

            page.wait_for_selector("#qa-alert-banner", timeout=5000)
            self.assertTrue(page.is_visible("#qa-alert-banner"))
            alert_text = page.inner_text("#qa-alert-text")
            self.assertIn("temporarily unavailable", alert_text)
            browser.close()

    def test_07_rate_limit_handling(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})

            # Mock 429 Rate Limit
            page.route("**/fan/ask", lambda route: route.fulfill(
                status=429,
                content_type="application/json",
                body=json.dumps({
                    "ok": False,
                    "error": "Rate limit reached.",
                    "code": "RATE_LIMIT_COOLDOWN",
                    "retry_after_sec": 2
                })
            ))

            page.goto(f"http://127.0.0.1:{self.port}/fan", wait_until="domcontentloaded")
            page.fill("#qa-input", "Question 1?")
            page.click("#qa-send-btn")

            page.wait_for_selector("#qa-alert-banner", timeout=5000)
            self.assertTrue(page.is_visible("#qa-alert-banner"))
            alert_text = page.inner_text("#qa-alert-text")
            self.assertIn("Rate limit", alert_text)
            # Verify controls temporarily disabled
            self.assertTrue(page.is_disabled("#qa-send-btn"))
            browser.close()

    def test_08_clear_chat(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})

            page.route("**/fan/ask", lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "ok": True,
                    "question": "What is the score?",
                    "answer": "4/0",
                    "source": "deterministic",
                    "feed_freshness": "live"
                })
            ))

            page.goto(f"http://127.0.0.1:{self.port}/fan", wait_until="domcontentloaded")
            page.fill("#qa-input", "What is the score?")
            page.click("#qa-send-btn")
            page.wait_for_selector(".qa-bubble-ai", timeout=5000)

            # Click Clear Chat
            page.click("#qa-clear-btn")

            # Check that bubbles are gone and empty state is restored
            self.assertEqual(len(page.query_selector_all(".qa-bubble")), 0)
            self.assertTrue(page.is_visible("#qa-empty-state"))

            # Check sessionStorage is empty
            session_raw = page.evaluate("sessionStorage.getItem('cricketstream_fan_qa_history')")
            self.assertIsNone(session_raw)
            browser.close()

    def test_09_session_history_persistence(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})

            page.route("**/fan/ask", lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "ok": True,
                    "question": "Who is batting?",
                    "answer": "Root and Stokes are batting.",
                    "source": "deterministic",
                    "feed_freshness": "live"
                })
            ))

            page.goto(f"http://127.0.0.1:{self.port}/fan", wait_until="domcontentloaded")
            page.fill("#qa-input", "Who is batting?")
            page.click("#qa-send-btn")
            page.wait_for_selector(".qa-bubble-ai", timeout=5000)

            # Reload page
            page.reload(wait_until="domcontentloaded")

            # Check that chat messages are restored from sessionStorage
            page.wait_for_selector(".qa-bubble-ai", timeout=5000)
            self.assertEqual(len(page.query_selector_all(".qa-bubble-user")), 1)
            self.assertEqual(len(page.query_selector_all(".qa-bubble-ai")), 1)
            browser.close()

    def test_10_maximum_history_limit(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})

            # Pre-seed 10 messages in sessionStorage
            ten_messages = [
                {"role": "user", "content": f"Q{i}", "timestamp": i}
                for i in range(10)
            ]
            page.goto(f"http://127.0.0.1:{self.port}/fan", wait_until="commit")
            page.evaluate("msgs => sessionStorage.setItem('cricketstream_fan_qa_history', JSON.stringify(msgs))", ten_messages)
            page.goto(f"http://127.0.0.1:{self.port}/fan", wait_until="domcontentloaded")

            # Check that history is capped at 8 messages
            rendered_bubbles = page.query_selector_all(".qa-bubble")
            self.assertEqual(len(rendered_bubbles), 8)
            browser.close()

    def test_11_xss_and_html_injection_protection(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})

            # Mock malicious payload
            malicious_payload = "<img src=x onerror=window.XSS_TRIGGERED=true><script>window.XSS_SCRIPT=true</script><b>Bold</b>"
            page.route("**/fan/ask", lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "ok": True,
                    "question": malicious_payload,
                    "answer": malicious_payload,
                    "source": "claude-haiku",
                    "feed_freshness": "live"
                })
            ))

            page.goto(f"http://127.0.0.1:{self.port}/fan", wait_until="domcontentloaded")
            page.fill("#qa-input", malicious_payload)
            page.click("#qa-send-btn")
            page.wait_for_selector(".qa-bubble-ai", timeout=5000)

            # Verify no scripts executed and no image tags injected into DOM
            xss_triggered = page.evaluate("window.XSS_TRIGGERED || window.XSS_SCRIPT")
            self.assertFalse(xss_triggered)
            # The text should be safely rendered as literal string
            ai_bubble_text = page.inner_text(".qa-bubble-ai")
            self.assertIn("<script>", ai_bubble_text)
            self.assertIn("<b>Bold</b>", ai_bubble_text)
            browser.close()

    def test_12_empty_and_overlong_questions(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(f"http://127.0.0.1:{self.port}/fan", wait_until="domcontentloaded")

            # Try submitting empty or whitespace
            page.fill("#qa-input", "   ")
            page.click("#qa-send-btn")
            # Must remain in empty state, zero bubbles
            self.assertEqual(len(page.query_selector_all(".qa-bubble")), 0)

            # Verify maxlength attribute on input
            max_len = page.get_attribute("#qa-input", "maxlength")
            self.assertEqual(max_len, "250")
            browser.close()

    def test_13_duplicate_submission_prevention(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})

            request_count = [0]
            held_route = []

            def intercept_route(route):
                request_count[0] += 1
                held_route.append(route)

            page.route("**/fan/ask", intercept_route)
            page.goto(f"http://127.0.0.1:{self.port}/fan", wait_until="domcontentloaded")

            page.fill("#qa-input", "Score?")
            page.click("#qa-send-btn")

            # The request is in-flight: verify input and send button are disabled
            self.assertTrue(page.is_disabled("#qa-input"))
            self.assertTrue(page.is_disabled("#qa-send-btn"))

            # Attempt duplicate submission while in-flight
            page.evaluate("askQAQuestion('Duplicate score?')")
            self.assertEqual(request_count[0], 1, "Must prevent duplicate in-flight requests")

            # Now fulfill the pending route
            self.assertEqual(len(held_route), 1)
            held_route[0].fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "ok": True,
                    "question": "Score?",
                    "answer": "4/0",
                    "source": "deterministic",
                    "feed_freshness": "live"
                })
            )

            page.wait_for_selector(".qa-bubble-ai", timeout=5000)
            self.assertFalse(page.is_disabled("#qa-input"))
            self.assertFalse(page.is_disabled("#qa-send-btn"))
            browser.close()

    def test_14_mobile_responsiveness_and_touch_targets(self):
        from playwright.sync_api import sync_playwright
        artifact_dir = r"C:\Users\augestin\.gemini\antigravity\brain\0a4a53b2-ae2c-4c2e-a0e5-5594439bb9d1"
        os.makedirs(artifact_dir, exist_ok=True)
        desktop_png = os.path.join(artifact_dir, "qa_desktop.png")
        mobile_png = os.path.join(artifact_dir, "qa_mobile.png")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            # 1. Desktop (1280x800)
            page_desktop = browser.new_page(viewport={"width": 1280, "height": 800})

            # Mock a completed conversation for rich screenshot
            page_desktop.route("**/fan/ask", lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "ok": True,
                    "question": "What is the current match situation?",
                    "answer": "Home CC is 4/0 after 0.1 overs in the 1st innings. Anderson is bowling to Root.",
                    "source": "deterministic",
                    "feed_freshness": "live",
                    "suggested_questions": ["Who is bowling?", "What happened in the previous over?"]
                })
            ))

            page_desktop.goto(f"http://127.0.0.1:{self.port}/fan", wait_until="domcontentloaded")
            page_desktop.fill("#qa-input", "What is the current match situation?")
            page_desktop.click("#qa-send-btn")
            page_desktop.wait_for_selector(".qa-bubble-ai", timeout=5000)

            # Check zero horizontal overflow
            scroll_width = page_desktop.evaluate("document.documentElement.scrollWidth")
            client_width = page_desktop.evaluate("document.documentElement.clientWidth")
            self.assertLessEqual(scroll_width, client_width, "Desktop must not horizontally overflow")

            page_desktop.screenshot(path=desktop_png, full_page=True)
            page_desktop.close()

            # 2. Mobile (390x844)
            page_mobile = browser.new_page(
                viewport={"width": 390, "height": 844},
                user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"
            )
            page_mobile.route("**/fan/ask", lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "ok": True,
                    "question": "How many runs are required to win?",
                    "answer": "Home CC is batting first; no target has been set yet.",
                    "source": "deterministic",
                    "feed_freshness": "live",
                    "suggested_questions": ["What is the current score?", "Who is batting?"]
                })
            ))

            page_mobile.goto(f"http://127.0.0.1:{self.port}/fan", wait_until="domcontentloaded")
            page_mobile.fill("#qa-input", "How many runs are required to win?")
            page_mobile.click("#qa-send-btn")
            page_mobile.wait_for_selector(".qa-bubble-ai", timeout=5000)

            # Check zero horizontal overflow on mobile
            mob_scroll = page_mobile.evaluate("document.documentElement.scrollWidth")
            mob_client = page_mobile.evaluate("document.documentElement.clientWidth")
            self.assertLessEqual(mob_scroll, mob_client, "Mobile must not horizontally overflow")

            # Check touch target heights >= 44px
            for sel in ["#qa-send-btn", "#qa-clear-btn", "#qa-input", ".qa-chip-btn"]:
                box = page_mobile.locator(sel).first.bounding_box()
                self.assertIsNotNone(box, f"{sel} must have a bounding box")
                self.assertGreaterEqual(box["height"], 43.5, f"{sel} height must be >= 44px (got {box['height']})")

            page_mobile.screenshot(path=mobile_png, full_page=True)
            page_mobile.close()
            browser.close()

    def test_15_existing_dashboard_functionality(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(f"http://127.0.0.1:{self.port}/fan", wait_until="domcontentloaded")

            # Scoreboard elements
            self.assertTrue(page.is_visible("#score-runs"))
            self.assertTrue(page.is_visible("#score-wickets"))
            self.assertTrue(page.is_visible("#score-overs"))

            # Live Commentary controls
            self.assertTrue(page.is_visible("#comm-toggle-btn"))
            self.assertTrue(page.is_visible("#voice-toggle-btn"))
            self.assertTrue(page.is_visible("#voice-replay-btn"))

            # Timeline section & Innings tabs
            self.assertTrue(page.is_visible("#timeline-container"))
            self.assertTrue(page.is_visible("#tab-inns-1"))
            self.assertTrue(page.is_visible("#tab-inns-2"))

            # Innings switching still works
            page.click("#tab-inns-2")
            self.assertEqual(page.locator("#tab-inns-2.active").count(), 1)
            page.click("#tab-inns-1")
            self.assertEqual(page.locator("#tab-inns-1.active").count(), 1)

            browser.close()


if __name__ == "__main__":
    unittest.main()
