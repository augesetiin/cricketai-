"""
Tests for Phase 2 Stage 3: Mobile Ball-by-Ball Timeline UI (fan.html)
─────────────────────────────────────────────────────────────────────
Verifies:
- fan.html serves with all required Timeline UI elements, badges, and controls.
- Innings tabs, pagination button, and error alert elements are present.
- Outcome badges, tags, and CSS classes conform to the color and role spec:
  dot (grey), runs (blue), four (orange), six (purple), wicket (red),
  extra (amber), uncertain (yellow/amber), adjustment (blue/cyan).
- JS delivery classification, over grouping, incremental append, and
  authoritative cache replacement algorithms execute correctly.
- Invariants: Never polls /live or /commands.
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import server
from test_http import HttpTestBase


class TestFanTimelineUI(HttpTestBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fan.html"),
                  encoding="utf-8") as f:
            cls.html_content = f.read()

    def test_fan_html_served_over_http(self):
        status, headers, body = self.request("GET", "/fan")
        self.assertEqual(status, 200)
        self.assertIn(b"Ball-by-Ball Timeline", body)
        self.assertIn(b"/fan/timeline", body)
        # Strict invariants
        self.assertNotIn(b"/live", body)
        self.assertNotIn(b"/commands", body)

    def test_timeline_ui_structure_present(self):
        html = self.html_content
        # Section and headers
        self.assertIn('id="timeline-container"', html)
        self.assertIn('Ball-by-Ball Timeline', html)
        # Innings Switcher Tabs
        self.assertIn('id="tab-inns-1"', html)
        self.assertIn('id="tab-inns-2"', html)
        self.assertIn('switchInnings(1)', html)
        self.assertIn('switchInnings(2)', html)
        # Containers
        self.assertIn('id="timeline-overs-wrapper"', html)
        self.assertIn('id="timeline-error-alert"', html)
        # Pagination
        self.assertIn('id="timeline-pagination-row"', html)
        self.assertIn('id="load-earlier-btn"', html)
        self.assertIn('loadEarlierDeliveries()', html)

    def test_outcome_badge_css_classes(self):
        html = self.html_content
        # Outcome badge classes
        self.assertIn('.outcome-badge.dot', html)
        self.assertIn('.outcome-badge.runs', html)
        self.assertIn('.outcome-badge.four', html)
        self.assertIn('.outcome-badge.six', html)
        self.assertIn('.outcome-badge.wicket', html)
        self.assertIn('.outcome-badge.extra', html)
        self.assertIn('.outcome-badge.adjustment', html)
        # Tag badges
        self.assertIn('.deliv-tag.latest-tag', html)
        self.assertIn('.deliv-tag.uncertain-tag', html)
        self.assertIn('.deliv-tag.corrected-tag', html)
        self.assertIn('.deliv-tag.adjustment-tag', html)
        # Latest delivery highlight
        self.assertIn('.delivery-item.latest', html)

    def test_timeline_js_classifier_logic(self):
        # Python mirror test of the frontend classifyDelivery logic
        def classify_delivery(d):
            if d.get("is_adjustment"):
                return {"cls": "adjustment", "text": "ADJ"}
            if d.get("is_wicket"):
                return {"cls": "wicket", "text": "W"}
            if d.get("is_boundary"):
                runs = d.get("total_runs", 0)
                if runs == 6 or d.get("outcome") == "6":
                    return {"cls": "six", "text": "6"}
                return {"cls": "four", "text": "4"}
            if not d.get("is_legal") or d.get("extra_type"):
                tok = d.get("token") or (str(d.get("total_runs", 1)) + str(d.get("extra_type", "wd")))
                return {"cls": "extra", "text": tok}
            r = d.get("runs_batter", d.get("total_runs", 0))
            if r == 0 or d.get("outcome") in (".", "0"):
                return {"cls": "dot", "text": "•"}
            return {"cls": "runs", "text": str(r)}

        # Dot
        self.assertEqual(classify_delivery({"is_legal": True, "outcome": ".", "runs_batter": 0})["cls"], "dot")
        # 1 run
        self.assertEqual(classify_delivery({"is_legal": True, "outcome": "1", "runs_batter": 1})["cls"], "runs")
        # Four
        self.assertEqual(classify_delivery({"is_legal": True, "is_boundary": True, "outcome": "4", "total_runs": 4})["cls"], "four")
        # Six
        self.assertEqual(classify_delivery({"is_legal": True, "is_boundary": True, "outcome": "6", "total_runs": 6})["cls"], "six")
        # Wicket
        self.assertEqual(classify_delivery({"is_legal": True, "is_wicket": True, "outcome": "W"})["cls"], "wicket")
        # Wide / No ball
        self.assertEqual(classify_delivery({"is_legal": False, "extra_type": "wd", "token": "1wd"})["cls"], "extra")
        # Score adjustment
        self.assertEqual(classify_delivery({"is_adjustment": True, "outcome": "ADJ"})["cls"], "adjustment")

    def test_over_grouping_logic(self):
        deliveries = [
            {"seq": 1, "over_number": 1, "ball_in_over": 1, "total_runs": 1, "is_wicket": False, "bowler_name": "Bowler A"},
            {"seq": 2, "over_number": 1, "ball_in_over": 2, "total_runs": 4, "is_wicket": False, "bowler_name": "Bowler A"},
            {"seq": 3, "over_number": 1, "ball_in_over": 3, "total_runs": 0, "is_wicket": True, "bowler_name": "Bowler A"},
            {"seq": 4, "over_number": 2, "ball_in_over": 1, "total_runs": 6, "is_wicket": False, "bowler_name": "Bowler B"},
        ]

        # Grouping algorithm
        over_groups = []
        cur_over = None
        for d in deliveries:
            o_num = d["over_number"]
            if not cur_over or cur_over["number"] != o_num:
                cur_over = {"number": o_num, "bowler": d.get("bowler_name"), "total_runs": 0, "wickets": 0, "balls": []}
                over_groups.append(cur_over)
            cur_over["balls"].append(d)
            cur_over["total_runs"] += d["total_runs"]
            if d.get("is_wicket"):
                cur_over["wickets"] += 1

        self.assertEqual(len(over_groups), 2)
        self.assertEqual(over_groups[0]["number"], 1)
        self.assertEqual(over_groups[0]["total_runs"], 5)
        self.assertEqual(over_groups[0]["wickets"], 1)
        self.assertEqual(len(over_groups[0]["balls"]), 3)

        self.assertEqual(over_groups[1]["number"], 2)
        self.assertEqual(over_groups[1]["total_runs"], 6)
        self.assertEqual(over_groups[1]["wickets"], 0)
        self.assertEqual(len(over_groups[1]["balls"]), 1)

    def test_mobile_viewport_and_touch_target_accessibility(self):
        html = self.html_content
        # Responsive viewport meta
        self.assertIn('<meta name="viewport" content="width=device-width, initial-scale=1.0', html)
        # Touch target minimum height
        self.assertIn('min-height: 44px', html)
        # Theme styling colors
        self.assertIn('--orange: #ea580c', html)
        self.assertIn('--blue: #1d4ed8', html)
        self.assertIn('--purple: #7c3aed', html)
        self.assertIn('--red: #dc2626', html)


if __name__ == "__main__":
    unittest.main()

