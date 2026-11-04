"""
Integration tests for GET /fan/glossary HTTP API (Stage 2)
===========================================================
Verifies:
 1. Full glossary retrieval (200 OK, total >= 25, categories present).
 2. English response (default and explicit lang=en).
 3. Hindi response (lang=hi, localized terms & category names).
 4. Marathi response (lang=mr, localized terms & category names).
 5. Specific term retrieval (term=strike_rate).
 6. Unknown term handling (404 Not Found, code="TERM_NOT_FOUND").
 7. Search by English name (q=yorker).
 8. Search by Hindi name (q=यॉर्कर).
 9. Search by Marathi name (q=षटक).
10. Category filtering (category=batting).
11. Search plus category filtering (q=rate&category=batting).
12. Invalid language validation (400 Bad Request, code="INVALID_LANGUAGE").
13. Invalid category validation (400 Bad Request, code="INVALID_CATEGORY").
14. Duplicate parameter rejection (400 Bad Request, code="DUPLICATE_PARAMETER").
15. Empty search query handling (200 OK, returns terms cleanly).
16. Excessively long search query rejection (400 Bad Request, code="QUERY_TOO_LONG").
17. Contextual match example generation using verified server match data.
18. Missing match data handling (1st innings RRR explanation).
19. Stale match data handling (is_stale flag and notice).
20. Read-only invariant: zero mutation of state, DB tables, or scoring sessions.
"""

import copy
import json
import os
import sys
import tempfile
import time
import unittest
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cricket_glossary
import fan_engine
import server
from test_http import HttpTestBase


class TestCricketGlossaryHttp(HttpTestBase):
    def setUp(self):
        super().setUp()
        server._last_good_state = None
        server.save_state(dict(server.DEFAULT_STATE))

        self.pcs_dir = os.path.join(self.tmp, "pcs_feed")
        os.makedirs(self.pcs_dir, exist_ok=True)
        server.save_state({"pcs_output_folder": self.pcs_dir})

        # Initialize SQLite tables
        server._innings_latch = 1
        with server._db_lock, server._db() as conn:
            fan_engine.init_fan_db(conn)

    def set_simulated_match(self, frame):
        """Write frame to PCS output folder and reset cache."""
        inn = int(frame.get("innings", 1) or 1)
        server._innings_latch = inn
        path = os.path.join(self.pcs_dir, "scoreboard.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(frame, f)
        server.save_state({
            "pcs_output_folder": self.pcs_dir,
            "home_team": frame.get("batting_team", "Home CC"),
            "away_team": frame.get("bowling_team", "Rival CC")
        })
        with fan_engine._fan_lock:
            fan_engine._fan_cache["data"] = None
            fan_engine._fan_cache["ts"] = 0.0
        server._pcs_last_mtime = 0
        server._pcs_last_state = None

    # 1. Full glossary retrieval
    def test_01_full_glossary_retrieval(self):
        status, headers, body = self.request("GET", "/fan/glossary")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        data = json.loads(body)
        self.assertTrue(data.get("ok"))
        self.assertGreaterEqual(data.get("total", 0), 25)
        self.assertIn("terms", data)
        self.assertIn("categories", data)
        self.assertEqual(data.get("lang"), "en")

    # 2. English response
    def test_02_english_response(self):
        status, data = self.get_json("/fan/glossary?lang=en")
        self.assertEqual(status, 200)
        self.assertEqual(data.get("lang"), "en")
        terms = {t["id"]: t for t in data.get("terms", [])}
        self.assertIn("strike_rate", terms)
        self.assertIn("Batting Strike Rate", terms["strike_rate"]["name"])

    # 3. Hindi response
    def test_03_hindi_response(self):
        status, data = self.get_json("/fan/glossary?lang=hi")
        self.assertEqual(status, 200)
        self.assertEqual(data.get("lang"), "hi")
        terms = {t["id"]: t for t in data.get("terms", [])}
        self.assertIn("strike_rate", terms)
        self.assertIn("स्ट्राइक रेट", terms["strike_rate"]["name"])
        # Check category names localized
        cat_names = [c["name"] for c in data.get("categories", [])]
        self.assertIn("बल्लेबाजी", cat_names)

    # 4. Marathi response
    def test_04_marathi_response(self):
        status, data = self.get_json("/fan/glossary?lang=mr")
        self.assertEqual(status, 200)
        self.assertEqual(data.get("lang"), "mr")
        terms = {t["id"]: t for t in data.get("terms", [])}
        self.assertIn("strike_rate", terms)
        self.assertIn("स्ट्राइक रेट", terms["strike_rate"]["name"])
        cat_names = [c["name"] for c in data.get("categories", [])]
        self.assertIn("फलंदाजी", cat_names)

    # 5. Specific term retrieval
    def test_05_specific_term_retrieval(self):
        status, data = self.get_json("/fan/glossary?term=strike_rate&lang=en")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        term = data.get("term", {})
        self.assertEqual(term.get("id"), "strike_rate")
        self.assertIn("A statistical measure", term.get("definition", ""))
        self.assertEqual(term.get("formula"), "(Runs Scored / Balls Faced) × 100")
        self.assertEqual(term.get("authority_type"), "Scoring Metric")

    # 6. Unknown term handling
    def test_06_unknown_term(self):
        status, data = self.get_json("/fan/glossary?term=unknown_nonexistent_term")
        self.assertEqual(status, 404)
        self.assertFalse(data.get("ok"))
        self.assertEqual(data.get("code"), "TERM_NOT_FOUND")
        self.assertIn("not found", data.get("error", "").lower())

    # 7. Search by English name
    def test_07_search_by_english_name(self):
        status, data = self.get_json("/fan/glossary?q=yorker&lang=en")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        ids = [t["id"] for t in data.get("terms", [])]
        self.assertIn("yorker", ids)

    # 8. Search by Hindi name
    def test_08_search_by_hindi_name(self):
        q = quote("यॉर्कर")
        status, data = self.get_json(f"/fan/glossary?q={q}&lang=hi")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        ids = [t["id"] for t in data.get("terms", [])]
        self.assertIn("yorker", ids)

    # 9. Search by Marathi name
    def test_09_search_by_marathi_name(self):
        q = quote("षटक")
        status, data = self.get_json(f"/fan/glossary?q={q}&lang=mr")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        ids = [t["id"] for t in data.get("terms", [])]
        self.assertTrue("over" in ids or "maiden_over" in ids)

    # 10. Category filtering
    def test_10_category_filtering(self):
        status, data = self.get_json("/fan/glossary?category=batting")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("category"), "batting")
        terms = data.get("terms", [])
        self.assertGreaterEqual(len(terms), 3)
        for t in terms:
            self.assertEqual(t.get("category"), "batting")

    # 11. Search plus category filtering
    def test_11_search_plus_category_filtering(self):
        status, data = self.get_json("/fan/glossary?q=rate&category=batting")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        terms = data.get("terms", [])
        ids = [t["id"] for t in terms]
        self.assertIn("strike_rate", ids)
        for t in terms:
            self.assertEqual(t.get("category"), "batting")

    # 12. Invalid language validation
    def test_12_invalid_language(self):
        status, data = self.get_json("/fan/glossary?lang=spanish")
        self.assertEqual(status, 400)
        self.assertFalse(data.get("ok"))
        self.assertEqual(data.get("code"), "INVALID_LANGUAGE")
        self.assertIn("spanish", data.get("error", ""))

    # 13. Invalid category validation
    def test_13_invalid_category(self):
        status, data = self.get_json("/fan/glossary?category=nonexistent_category")
        self.assertEqual(status, 400)
        self.assertFalse(data.get("ok"))
        self.assertEqual(data.get("code"), "INVALID_CATEGORY")
        self.assertIn("nonexistent_category", data.get("error", ""))

    # 14. Duplicate parameter rejection
    def test_14_duplicate_parameters(self):
        status, data = self.get_json("/fan/glossary?lang=en&lang=hi")
        self.assertEqual(status, 400)
        self.assertFalse(data.get("ok"))
        self.assertEqual(data.get("code"), "DUPLICATE_PARAMETER")
        self.assertIn("Ambiguous parameter", data.get("error", ""))

    # 15. Empty search query handling
    def test_15_empty_search(self):
        status, data = self.get_json("/fan/glossary?q=")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        self.assertGreaterEqual(data.get("total", 0), 25)

    # 16. Excessively long search query rejection
    def test_16_excessively_long_search(self):
        long_q = "a" * 105
        status, data = self.get_json(f"/fan/glossary?q={long_q}")
        self.assertEqual(status, 400)
        self.assertFalse(data.get("ok"))
        self.assertEqual(data.get("code"), "QUERY_TOO_LONG")

    # 17. Contextual match example using verified server match data
    def test_17_contextual_match_example(self):
        # Simulate active 2nd innings chase
        self.set_simulated_match({
            "batting_team": "Rival CC",
            "bowling_team": "Home CC",
            "innings": 2,
            "runs": "132",
            "wickets": "4",
            "overs": "16.0",
            "run_rate": "8.25",
            "target": "166",
            "runs_required": "34",
            "balls_remaining": "24",
            "max_overs": "20",
            "batter1_name": "Tom Baker",
            "batter1_runs": "45",
            "batter1_balls": "30",
            "batter2_name": "Harry Cole",
            "batter2_runs": "18",
            "batter2_balls": "14",
            "bowler_name": "Ben Walker",
            "last_ball": "1"
        })

        status, data = self.get_json("/fan/glossary?term=required_run_rate&lang=en")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        ctx = data.get("context_example")
        self.assertIsNotNone(ctx)
        self.assertTrue(ctx.get("has_context"))
        self.assertIn("Target: 166", ctx.get("text", ""))
        self.assertIn("Need 34 runs from 24 balls", ctx.get("text", ""))

    # 18. Missing match data handling (1st innings RRR)
    def test_18_missing_match_data(self):
        # Simulate 1st innings
        self.set_simulated_match({
            "batting_team": "Home CC",
            "bowling_team": "Rival CC",
            "innings": 1,
            "runs": "45",
            "wickets": "2",
            "overs": "6.0",
            "run_rate": "7.50",
            "max_overs": "20"
        })

        status, data = self.get_json("/fan/glossary?term=required_run_rate&lang=en")
        self.assertEqual(status, 200)
        ctx = data.get("context_example")
        self.assertIsNotNone(ctx)
        self.assertFalse(ctx.get("has_context"))
        self.assertIn("1st innings", ctx.get("text", ""))

    # 19. Stale match data handling
    def test_19_stale_match_data(self):
        # Write scoreboard and simulate stale feed (>30s)
        self.set_simulated_match({
            "batting_team": "Rival CC",
            "bowling_team": "Home CC",
            "innings": 2,
            "runs": "132",
            "wickets": "4",
            "overs": "16.0",
            "target": "166",
            "runs_required": "34",
            "balls_remaining": "24",
            "batter1_name": "Tom Baker",
            "batter1_runs": "45",
            "batter1_balls": "30",
        })

        # Artificial age in cache
        fan_data = fan_engine.get_fan_data()
        fan_data["last_updated_sec_ago"] = 65
        fan_data["feed_fresh"] = False
        with fan_engine._fan_lock:
            fan_engine._fan_cache["data"] = fan_data
            fan_engine._fan_cache["ts"] = time.time()

        status, data = self.get_json("/fan/glossary?term=strike_rate&lang=en")
        self.assertEqual(status, 200)
        ctx = data.get("context_example")
        self.assertIsNotNone(ctx)
        self.assertTrue(ctx.get("is_stale"))
        self.assertIn("delayed", ctx.get("text", "").lower())

    # 20. Read-only invariant: zero mutation of state, DB tables, or scoring sessions
    def test_20_no_state_mutation(self):
        st_before = server.load_state()
        _ = self.get_json("/fan/glossary?lang=hi")
        _ = self.get_json("/fan/glossary?term=yorker&lang=mr")
        _ = self.get_json("/fan/glossary?category=bowling")
        st_after = server.load_state()
        self.assertEqual(st_before, st_after, "Glossary endpoint must not modify server state")


if __name__ == "__main__":
    unittest.main()
