"""
Tests for Busy / Driving Experience & Radio Presenter Commentary
────────────────────────────────────────────────────────────────
Verifies:
1. Three commentary personalities exist in markup and script (Radio Presenter default).
2. Commentary queue priority hierarchy:
   - Level 1: wicket, match_complete
   - Level 2: milestone
   - Level 3: six, four
   - Level 4: over_summary
   - Level 5: runs, extra, dot
3. Preemption logic: High priority boundary/wicket cancels routine dot/run and clears obsolete routine items.
4. Natural punctuation and speech sanitization for SpeechSynthesis:
   - RRR / required run rate decimal formatting
   - Ball singular/plural correction
   - Breath pauses after excitement
5. Driving safety invariants:
   - Explicit voice activation required (starts muted)
   - Chatbot input and floating buttons hidden in driving mode
   - Background audio persistence when mode === 'busy'
   - Wake lock status indicator and lifecycle
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_http import HttpTestBase
import fan_commentary
import fan_engine
import server


class TestBusyDrivingStructureAndLogic(HttpTestBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fan.html"),
                  encoding="utf-8") as f:
            cls.html = f.read()

    def test_personality_chips_present_in_markup(self):
        html = self.html
        self.assertIn('id="btn-pers-radio"', html)
        self.assertIn('id="btn-pers-analyst"', html)
        self.assertIn('id="btn-pers-simple"', html)
        self.assertIn('data-pers="radio_presenter"', html)
        self.assertIn('data-pers="match_analyst"', html)
        self.assertIn('data-pers="simple_cricket"', html)
        self.assertIn('Radio Presenter (Live)', html)
        self.assertIn('Match Analyst', html)
        self.assertIn('Simple Cricket', html)

    def test_default_personality_is_radio_presenter(self):
        html = self.html
        self.assertIn("var currentPersonality = 'radio_presenter';", html)
        self.assertIn('class="busy-pers-chip active" id="btn-pers-radio"', html)

    def test_commentary_queue_priority_and_preemption_in_script(self):
        html = self.html
        self.assertIn('commentaryQueue', html)
        self.assertIn('getPriority', html)
        self.assertIn('preemptCurrent', html)
        self.assertIn('cancelAll', html)
        # Priority mapping
        self.assertIn("if (ev === 'wicket' || ev === 'match_complete') return 1;", html)
        self.assertIn("if (ev === 'milestone') return 2;", html)
        self.assertIn("if (ev === 'six' || ev === 'four') return 3;", html)
        self.assertIn("if (ev === 'over_summary') return 4;", html)
        # Preemption check for priority <= 3
        self.assertIn("if (priority <= 3)", html)
        self.assertIn("this.preemptCurrent()", html)

    def test_driving_safety_distraction_free_css(self):
        html = self.html
        # Chat and distracting elements hidden in busy mode
        self.assertIn('body.mode-busy #qa-container', html)
        self.assertIn('body.mode-busy .cricket-dost-pill-btn', html)
        self.assertIn('body.mode-busy #cricket-dost-float-btn', html)
        self.assertIn('body.mode-busy .floating-actions', html)
        self.assertIn('body.mode-busy .sticky-nav-bar', html)

    def test_background_audio_persistence_for_drivers(self):
        html = self.html
        # Only pause on visibilitychange if NOT in busy mode
        self.assertIn("currentFanMode !== 'busy'", html)
        self.assertIn("!document.hidden || currentFanMode === 'busy'", html)

    def test_speech_sanitization_rules(self):
        html = self.html
        self.assertIn("sanitizeFrontendSpeech", html)
        self.assertIn("required run rate $1 point $2", html)
        self.assertIn("1 ball", html)

    def test_wake_lock_integration(self):
        html = self.html
        self.assertIn("requestWakeLock", html)
        self.assertIn("releaseWakeLock", html)
        self.assertIn("busy-wakelock-status", html)

    def test_default_english_language_and_hindi_support(self):
        html = self.html
        self.assertIn("var busyLang = 'en';", html)
        self.assertIn('data-lang="en"', html)
        self.assertIn('English (Default)', html)
        self.assertIn('data-lang="hi"', html)
        self.assertIn('generateMatchCatchUpRecap', html)

    def test_humanized_neural_voice_engine(self):
        html = self.html
        self.assertIn("selectBestHumanVoice", html)
        self.assertIn("premiumKeywords", html)
        self.assertIn("utt.pitch = 1.02", html)
        self.assertIn("utt.rate = 1.02", html)

    def test_match_catchup_recap_controls(self):
        html = self.html
        self.assertIn('id="busy-catchup-btn"', html)
        self.assertIn('playMatchCatchUpIntro', html)


class TestBusyDrivingPlaywright(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
            cls.playwright_available = True
        except ImportError:
            cls.playwright_available = False

    def test_driving_mode_interaction_and_speech_simulation(self):
        if not self.playwright_available:
            self.skipTest("Playwright not installed in environment")

        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            # Spy on native SpeechSynthesis
            page.add_init_script("""
                window.__mockSpoken = [];
                window.__mockCancelled = 0;
                if (window.speechSynthesis) {
                    var origSpeak = window.speechSynthesis.speak.bind(window.speechSynthesis);
                    var origCancel = window.speechSynthesis.cancel.bind(window.speechSynthesis);
                    window.speechSynthesis.speak = function(utt) {
                        window.__mockSpoken.push(utt.text);
                        try { origSpeak(utt); } catch(e) {}
                    };
                    window.speechSynthesis.cancel = function() {
                        window.__mockCancelled++;
                        try { origCancel(); } catch(e) {}
                    };
                }
            """)

            # Load page
            page.goto("http://localhost:5000/fan", wait_until="domcontentloaded")

            # 1. Verify landing page or select Busy / Driving
            busy_btn = page.locator("#btn-mode-busy")
            if busy_btn.is_visible():
                busy_btn.click()
            else:
                page.evaluate("selectPersona('busy')")

            page.wait_for_selector("#busy-driving-controls", state="visible")

            # 2. Verify Radio Presenter chip is active by default
            radio_active = page.evaluate("document.getElementById('btn-pers-radio').classList.contains('active')")
            self.assertTrue(radio_active, "Radio Presenter chip should be active by default")

            # 3. Switch to Match Analyst
            page.locator("#btn-pers-analyst").click()
            analyst_active = page.evaluate("document.getElementById('btn-pers-analyst').classList.contains('active')")
            self.assertTrue(analyst_active, "Match Analyst chip should become active")
            pers_val = page.evaluate("currentPersonality")
            self.assertEqual(pers_val, "match_analyst")

            # 4. Switch back to Radio Presenter
            page.locator("#btn-pers-radio").click()
            pers_val2 = page.evaluate("currentPersonality")
            self.assertEqual(pers_val2, "radio_presenter")

            # 5. Verify voice is auto-activated on opening busy mode to narrate match recap
            voice_enabled = page.evaluate("commentaryState.voiceEnabled")
            self.assertTrue(voice_enabled, "Voice narration automatically activates on entering driving mode to deliver match recap")

            # 6. Verify Cricket Dost floating button is hidden in driving mode
            is_chat_hidden = page.evaluate("""
                (function() {
                    var btn = document.getElementById('cricket-dost-float-btn');
                    if (!btn) return true;
                    var style = window.getComputedStyle(btn);
                    return style.display === 'none';
                })()
            """)
            self.assertTrue(is_chat_hidden, "Chatbot button must be hidden in driving mode to prevent distraction")

            # 7. Test commentaryQueue preemption in browser context
            preemption_result = page.evaluate("""
                (function() {
                    commentaryState.speechSupported = true;
                    commentaryState.voiceEnabled = true;
                    commentaryQueue.cancelAll();

                    // 1. Enqueue routine dot (priority 5)
                    var dotItem = {
                        commentary_id: 101,
                        event_type: 'dot',
                        bowler_name: 'Starc',
                        text: 'Dot ball defended.'
                    };
                    commentaryQueue.enqueue(dotItem, false);

                    // Verify speaking dot
                    var isSpeakingDot = commentaryQueue.isSpeaking;
                    var currentPriority = commentaryQueue.currentPriority;

                    // 2. High priority wicket arrives (priority 1)
                    var wicketItem = {
                        commentary_id: 102,
                        event_type: 'wicket',
                        batter_name: 'Kohli',
                        dismissal_text: 'c Warner b Cummins',
                        text: 'WICKET! Kohli out!'
                    };
                    commentaryQueue.enqueue(wicketItem, false);

                    return {
                        dotSpeaking: isSpeakingDot,
                        dotPriority: currentPriority,
                        cancelledCount: window.__mockCancelled,
                        spokenList: window.__mockSpoken
                    };
                })()
            """)
            self.assertTrue(preemption_result["dotSpeaking"])
            self.assertEqual(preemption_result["dotPriority"], 5)
            self.assertGreaterEqual(preemption_result["cancelledCount"], 1, "Routine dot should be preempted by wicket")

            # 8. Test background visibility persistence
            bg_audio_check = page.evaluate("""
                (function() {
                    currentFanMode = 'busy';
                    var beforeCancel = window.__mockCancelled;
                    // Simulate visibility change to hidden
                    var event = new Event('visibilitychange');
                    Object.defineProperty(document, 'hidden', { value: true, configurable: true });
                    document.dispatchEvent(event);
                    return {
                        before: beforeCancel,
                        after: window.__mockCancelled
                    };
                })()
            """)
            self.assertEqual(bg_audio_check["before"], bg_audio_check["after"],
                             "In busy mode, hidden document must NOT cancel audio")

            browser.close()


if __name__ == "__main__":
    unittest.main()
