"""
Tests for Stage 6 & 7: Smart Timeline Filters & Personalised Notifications UI
─────────────────────────────────────────────────────────────────────────────
Verifies:
1. fan.html contains smart timeline filter pills: All, Boundaries, Wickets, Milestones, Over Ends.
2. fan.html contains dynamic player filter dropdown <select id="timeline-player-filter">.
3. fan.html contains score-at-event badges on delivery items.
4. fan.html contains in-app toast banner <div id="notification-toast">.
5. fan.html contains personalised alerts settings modal <div id="alerts-modal"> with event toggles.
6. fan.html contains Low-Data toggle button and Score privacy mask toggle button.
"""
import os
import unittest


class TestSmartTimelineAndNotificationsUI(unittest.TestCase):
    def setUp(self):
        html_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fan.html")
        with open(html_path, "r", encoding="utf-8") as f:
            self.html = f.read()

    def test_01_timeline_filter_pills_present(self):
        self.assertIn('class="timeline-filters-bar"', self.html)
        self.assertIn('id="tl-btn-all"', self.html)
        self.assertIn('id="tl-btn-boundaries"', self.html)
        self.assertIn('id="tl-btn-wickets"', self.html)
        self.assertIn('id="tl-btn-milestones"', self.html)
        self.assertIn('id="tl-btn-overs"', self.html)

    def test_02_timeline_player_filter_present(self):
        self.assertIn('id="timeline-player-filter"', self.html)
        self.assertIn('setTimelinePlayerFilter', self.html)

    def test_03_score_at_event_badge_logic_present(self):
        self.assertIn('score-at-event-badge', self.html)
        self.assertIn('d.score_after', self.html)
        self.assertIn('d.wickets_after', self.html)

    def test_04_notification_toast_banner_present(self):
        self.assertIn('id="notification-toast"', self.html)
        self.assertIn('id="toast-icon"', self.html)
        self.assertIn('id="toast-title"', self.html)
        self.assertIn('id="toast-msg"', self.html)
        self.assertIn('showToast', self.html)
        self.assertIn('dismissToast', self.html)

    def test_05_personalised_alerts_modal_present(self):
        self.assertIn('id="alerts-modal"', self.html)
        self.assertIn('id="alert-opt-wickets"', self.html)
        self.assertIn('id="alert-opt-boundaries"', self.html)
        self.assertIn('id="alert-opt-milestones"', self.html)
        self.assertIn('id="alert-opt-result"', self.html)
        self.assertIn('id="alert-opt-fav-only"', self.html)
        self.assertIn('id="alert-fav-players-input"', self.html)
        self.assertIn('saveAlertSettings', self.html)
        self.assertIn('toggleAlertsModal', self.html)

    def test_06_low_data_and_score_mask_toggles_present(self):
        self.assertIn('id="low-data-toggle-btn"', self.html)
        self.assertIn('toggleLowDataMode', self.html)
        self.assertIn('id="hide-score-toggle-btn"', self.html)
        self.assertIn('toggleHideScore', self.html)
        self.assertIn('id="spoiler-delay-select"', self.html)
        self.assertIn('setSpoilerDelay', self.html)


if __name__ == "__main__":
    unittest.main()

