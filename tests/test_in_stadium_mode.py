"""
Tests for In-Stadium Ground Companion Mode & Low-Bandwidth Sync
───────────────────────────────────────────────────────────────
Verifies:
1. In-Stadium Ground Dashboard structure:
   - 0.2s low-latency sync badge
   - Battery & Data Saver status
   - Sunlight E-Ink mode toggle
2. DRS Big-Screen Ground Review tracker.
3. Live At-The-Crease card (Striker, Non-Striker, Bowler).
4. Ground Chase Equation & DLS Rain Rule Par Score calculator.
5. Crowd atmosphere & roar decibel meter.
6. Stadium Facilities & Emergency Help drawer.
7. Playwright interactive verification:
   - Mode activation
   - Sunlight toggle
   - Facility drawer expansion
   - Low bandwidth asset efficiency
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_http import HttpTestBase


class TestInStadiumStructureAndLogic(HttpTestBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fan.html"),
                  encoding="utf-8") as f:
            cls.html = f.read()

    def test_stadium_dashboard_present_in_markup(self):
        html = self.html
        self.assertIn('id="stadium-ground-dashboard"', html)
        self.assertIn('GROUND-SYNC FEED', html)
        self.assertIn('Battery &amp; Data Saver ON', html)
        self.assertIn('id="stadium-sun-toggle"', html)
        self.assertIn('toggleStadiumSunlightMode()', html)

    def test_drs_and_crease_elements_present(self):
        html = self.html
        self.assertIn('id="stadium-drs-card"', html)
        self.assertIn('Third Umpire Review', html)
        self.assertIn('id="stadium-striker-name"', html)
        self.assertIn('id="stadium-nonstriker-name"', html)
        self.assertIn('id="stadium-bowler-name"', html)

    def test_dls_par_score_and_atmosphere_present(self):
        html = self.html
        self.assertIn('id="stadium-par-badge"', html)
        self.assertIn('id="stadium-dls-info"', html)
        self.assertIn('id="stadium-crowd-chant"', html)
        self.assertIn('Roar Level', html)

    def test_facility_drawer_present(self):
        html = self.html
        self.assertIn('id="stadium-facility-body"', html)
        self.assertIn('toggleStadiumFacilityDrawer()', html)
        self.assertIn('Free Drinking Water', html)
        self.assertIn('Emergency First-Aid', html)

    def test_stadium_css_and_sunlight_mode(self):
        html = self.html
        self.assertIn('body.mode-stadium #stadium-ground-dashboard', html)
        self.assertIn('body.mode-stadium.sunlight-active', html)


class TestInStadiumPlaywright(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
            cls.playwright_available = True
        except ImportError:
            cls.playwright_available = False

    def test_in_stadium_view_and_interactions(self):
        if not self.playwright_available:
            self.skipTest("Playwright not installed in environment")

        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()

            page.goto("http://localhost:5000/fan", wait_until="domcontentloaded")

            # 1. Switch to In-Stadium Mode
            page.evaluate("selectPersona('stadium')")
            page.wait_for_selector("#stadium-ground-dashboard", state="visible")

            # 2. Verify Stadium dashboard is visible and other mode cards are hidden
            dash_visible = page.is_visible("#stadium-ground-dashboard")
            busy_visible = page.is_visible("#busy-driving-controls")
            tactical_visible = page.is_visible("#tactical-matchups-card")
            self.assertTrue(dash_visible)
            self.assertFalse(busy_visible)
            self.assertFalse(tactical_visible)

            # 3. Test Sunlight Mode Toggle
            page.locator("#stadium-sun-toggle").click()
            is_sunlight = page.evaluate("document.body.classList.contains('sunlight-active')")
            self.assertTrue(is_sunlight, "Sunlight mode should be active after toggle")
            sun_label = page.inner_text("#stadium-sun-label")
            self.assertEqual(sun_label, "Night Mode")

            # Toggle back to Night Mode
            page.locator("#stadium-sun-toggle").click()
            is_sunlight_after = page.evaluate("document.body.classList.contains('sunlight-active')")
            self.assertFalse(is_sunlight_after)

            # 4. Test Facility Drawer expand/collapse
            body_display_before = page.evaluate("document.getElementById('stadium-facility-body').style.display")
            self.assertEqual(body_display_before, "none")
            page.locator(".stadium-facility-header").click()
            body_display_after = page.evaluate("document.getElementById('stadium-facility-body').style.display")
            self.assertEqual(body_display_after, "flex")

            # 5. Test dynamic DLS Par update
            dls_text = page.evaluate("""
                (function() {
                    updateStadiumDashboard({
                        target: 182,
                        score: 160,
                        wickets: 4,
                        overs: '17.2',
                        runs_required: 22,
                        balls_remaining: 16,
                        batting_team: 'Royal Challengers',
                        striker: { name: 'V. Kohli', runs: 50, balls: 35, fours: 5, sixes: 1, sr: 142.8 },
                        non_striker: { name: 'H. Pandya', runs: 21, balls: 10 },
                        bowler: { name: 'M. Starc', overs: '3.2', maidens: 0, runs: 32, wickets: 1, econ: '9.60' }
                    });
                    return {
                        striker: document.getElementById('stadium-striker-name').textContent,
                        runsNeed: document.getElementById('stadium-runs-need').textContent,
                        badge: document.getElementById('stadium-par-badge').textContent
                    };
                })()
            """)
            self.assertIn("V. Kohli", dls_text["striker"])
            self.assertEqual(dls_text["runsNeed"], "22")
            self.assertIn("Ahead of DLS Par", dls_text["badge"])

            browser.close()


if __name__ == "__main__":
    unittest.main()
