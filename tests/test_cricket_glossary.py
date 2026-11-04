"""
Unit tests for Cricket Explainer & Glossary Module (Stage 1)
============================================================
Verifies:
 1. At least 25 glossary entries exist.
 2. Every term has a valid English definition.
 3. Hindi and Marathi retrieval for all terms.
 4. Missing translation fallback to English with metadata.
 5. Search by term name (English).
 6. Search in Hindi and Marathi keywords.
 7. Category filtering across all defined categories.
 8. Unknown term handling returns None safely.
 9. Strike-rate calculation in context generator.
10. Economy-rate calculation with partial overs.
11. Current run-rate calculation.
12. Required run-rate calculation.
13. Partnership context.
14. Zero-ball edge cases (protects against ZeroDivisionError).
15. Unsupported DLS target calculations explained honestly.
16. Competition-specific Powerplay explanations.
17. Follow-on threshold accuracy (200, 150, 100, 75).
18. Wide and no-ball descriptions (penalty run + extra ball).
19. No fabricated match examples when data is missing.
20. No modification of existing match state.
"""

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cricket_glossary


class TestCricketGlossary(unittest.TestCase):

    def setUp(self):
        self.sample_match_facts_chase = {
            "match_id": "mid_test_1",
            "innings": 2,
            "status": "live",
            "batting_team": "Rival CC",
            "bowling_team": "Home CC",
            "score": 132,
            "wickets": 4,
            "overs": "16.0",
            "run_rate": 8.25,
            "target": 166,
            "runs_required": 34,
            "balls_remaining": 24,
            "required_run_rate": 8.5,
            "batters": [
                {"name": "Tom Baker", "runs": 45, "balls": 30, "is_striker": True},
                {"name": "Harry Cole", "runs": 18, "balls": 14, "is_striker": False},
            ],
            "bowler": {
                "name": "Ben Walker",
                "overs": 3.2,
                "runs": 24,
                "wickets": 1,
            },
            "partnership": {
                "runs": 42,
                "balls": 28,
                "batter1_name": "Tom Baker",
                "batter2_name": "Harry Cole",
            },
            "is_stale": False,
            "data_age_sec": 4,
        }

    # 1. At least 25 glossary entries exist
    def test_01_minimum_twenty_five_entries(self):
        all_terms = cricket_glossary.get_all_terms("en")
        self.assertGreaterEqual(len(all_terms), 25, "Glossary must contain at least 25 terms")
        self.assertIn("strike_rate", cricket_glossary.GLOSSARY_TERMS)
        self.assertIn("economy_rate", cricket_glossary.GLOSSARY_TERMS)
        self.assertIn("powerplay", cricket_glossary.GLOSSARY_TERMS)
        self.assertIn("required_run_rate", cricket_glossary.GLOSSARY_TERMS)
        self.assertIn("current_run_rate", cricket_glossary.GLOSSARY_TERMS)
        self.assertIn("wide_ball", cricket_glossary.GLOSSARY_TERMS)
        self.assertIn("no_ball", cricket_glossary.GLOSSARY_TERMS)
        self.assertIn("dls_method", cricket_glossary.GLOSSARY_TERMS)
        self.assertIn("partnership", cricket_glossary.GLOSSARY_TERMS)
        self.assertIn("maiden_over", cricket_glossary.GLOSSARY_TERMS)
        self.assertIn("duck", cricket_glossary.GLOSSARY_TERMS)
        self.assertIn("boundary", cricket_glossary.GLOSSARY_TERMS)
        self.assertIn("extras", cricket_glossary.GLOSSARY_TERMS)
        self.assertIn("wicket", cricket_glossary.GLOSSARY_TERMS)
        self.assertIn("over", cricket_glossary.GLOSSARY_TERMS)
        self.assertIn("crease", cricket_glossary.GLOSSARY_TERMS)
        self.assertIn("yorker", cricket_glossary.GLOSSARY_TERMS)
        self.assertIn("bouncer", cricket_glossary.GLOSSARY_TERMS)
        self.assertIn("follow_on", cricket_glossary.GLOSSARY_TERMS)
        self.assertIn("super_over", cricket_glossary.GLOSSARY_TERMS)
        self.assertIn("free_hit", cricket_glossary.GLOSSARY_TERMS)
        self.assertIn("dot_ball", cricket_glossary.GLOSSARY_TERMS)
        self.assertIn("byes_leg_byes", cricket_glossary.GLOSSARY_TERMS)
        self.assertIn("target", cricket_glossary.GLOSSARY_TERMS)
        self.assertIn("drs", cricket_glossary.GLOSSARY_TERMS)

    # 2. Every term has a valid English definition
    def test_02_every_term_has_english_definition(self):
        for term_id in cricket_glossary.GLOSSARY_TERMS:
            t = cricket_glossary.get_term(term_id, lang="en")
            self.assertIsNotNone(t, f"Term {term_id} must resolve in English")
            self.assertTrue(t["name"], f"Term {term_id} must have a name")
            self.assertTrue(t["definition"], f"Term {term_id} must have a definition")
            self.assertFalse(t["is_fallback"])
            self.assertIn(t["category"], cricket_glossary.CATEGORIES)

    # 3. Hindi and Marathi retrieval
    def test_03_hindi_and_marathi_retrieval(self):
        for term_id in cricket_glossary.GLOSSARY_TERMS:
            # Hindi
            t_hi = cricket_glossary.get_term(term_id, lang="hi")
            self.assertIsNotNone(t_hi)
            self.assertTrue(t_hi["definition"], f"Term {term_id} must have Hindi definition")
            self.assertFalse(t_hi["is_fallback"])
            self.assertEqual(t_hi["requested_language"], "hi")

            # Marathi
            t_mr = cricket_glossary.get_term(term_id, lang="mr")
            self.assertIsNotNone(t_mr)
            self.assertTrue(t_mr["definition"], f"Term {term_id} must have Marathi definition")
            self.assertFalse(t_mr["is_fallback"])
            self.assertEqual(t_mr["requested_language"], "mr")

    # 4. Missing translation fallback
    def test_04_missing_translation_fallback(self):
        # Requesting unsupported language code falls back to 'en'
        t = cricket_glossary.get_term("strike_rate", lang="fr")
        self.assertIsNotNone(t)
        self.assertEqual(t["requested_language"], "en")
        self.assertIn("Strike Rate", t["name"])

        # Artificially test an entry missing a specific language
        mock_terms = copy.deepcopy(cricket_glossary.GLOSSARY_TERMS)
        mock_terms["strike_rate"]["definition"]["mr"] = ""
        orig_terms = cricket_glossary.GLOSSARY_TERMS
        try:
            cricket_glossary.GLOSSARY_TERMS = mock_terms
            t_fallback = cricket_glossary.get_term("strike_rate", lang="mr")
            self.assertTrue(t_fallback["is_fallback"])
            self.assertTrue(len(t_fallback["definition"]) > 0)
        finally:
            cricket_glossary.GLOSSARY_TERMS = orig_terms

    # 5. Search by term name (English)
    def test_05_search_by_term_name(self):
        results = cricket_glossary.search_terms("strike rate", lang="en")
        self.assertTrue(len(results) >= 1)
        top_ids = [r["id"] for r in results]
        self.assertIn("strike_rate", top_ids)

    # 6. Search in Hindi and Marathi
    def test_06_search_hindi_and_marathi(self):
        # Search in Hindi: 'यॉर्कर'
        res_hi = cricket_glossary.search_terms("यॉर्कर", lang="hi")
        self.assertTrue(len(res_hi) >= 1)
        self.assertEqual(res_hi[0]["id"], "yorker")

        # Search in Marathi: 'षटक'
        res_mr = cricket_glossary.search_terms("षटक", lang="mr")
        self.assertTrue(len(res_mr) >= 1)
        mr_ids = [r["id"] for r in res_mr]
        self.assertTrue("over" in mr_ids or "maiden_over" in mr_ids)

    # 7. Category filtering
    def test_07_category_filtering(self):
        batting_terms = cricket_glossary.get_terms_by_category("batting", lang="en")
        self.assertTrue(len(batting_terms) >= 3)
        for t in batting_terms:
            self.assertEqual(t["category"], "batting")

        rules_terms = cricket_glossary.get_terms_by_category("rules", lang="en")
        self.assertTrue(len(rules_terms) >= 5)
        for t in rules_terms:
            self.assertEqual(t["category"], "rules")

    # 8. Unknown term handling
    def test_08_unknown_term_handling(self):
        self.assertIsNone(cricket_glossary.get_term("non_existent_term"))
        self.assertIsNone(cricket_glossary.get_term(""))
        self.assertIsNone(cricket_glossary.get_term(None))
        self.assertEqual(cricket_glossary.get_terms_by_category("invalid_cat"), [])
        self.assertEqual(cricket_glossary.search_terms(""), [])

    # 9. Strike-rate calculation
    def test_09_strike_rate_calculation(self):
        ctx = cricket_glossary.build_term_context("strike_rate", self.sample_match_facts_chase, lang="en")
        self.assertIsNotNone(ctx)
        self.assertTrue(ctx["has_context"])
        # Tom Baker: 45 runs off 30 balls = 150.00 SR
        self.assertIn("Tom Baker: 45 runs (30 balls) → Strike Rate: 150.00", ctx["text"])
        # Harry Cole: 18 runs off 14 balls = 128.57 SR
        self.assertIn("Harry Cole: 18 runs (14 balls) → Strike Rate: 128.57", ctx["text"])

    # 10. Economy-rate calculation with partial overs
    def test_10_economy_rate_calculation_partial_overs(self):
        # Ben Walker: 24 runs in 3.2 overs (20 legal balls) -> 24 / 20 * 6 = 7.20 econ
        ctx = cricket_glossary.build_term_context("economy_rate", self.sample_match_facts_chase, lang="en")
        self.assertIsNotNone(ctx)
        self.assertTrue(ctx["has_context"])
        self.assertIn("Ben Walker", ctx["text"])
        self.assertIn("24 runs conceded in 3.2 overs → Economy Rate: 7.20 per over", ctx["text"])

    # 11. Run-rate calculations
    def test_11_run_rate_calculations(self):
        ctx = cricket_glossary.build_term_context("current_run_rate", self.sample_match_facts_chase, lang="en")
        self.assertIsNotNone(ctx)
        self.assertTrue(ctx["has_context"])
        self.assertIn("Rival CC: 132 runs in 16.0 overs → Current Run Rate: 8.25", ctx["text"])

    # 12. Required run-rate calculation
    def test_12_required_run_rate_calculation(self):
        ctx = cricket_glossary.build_term_context("required_run_rate", self.sample_match_facts_chase, lang="en")
        self.assertIsNotNone(ctx)
        self.assertTrue(ctx["has_context"])
        self.assertIn("Target: 166", ctx["text"])
        self.assertIn("Need 34 runs from 24 balls → Required Run Rate: 8.5 per over", ctx["text"])

    # 13. Partnership context
    def test_13_partnership_context(self):
        ctx = cricket_glossary.build_term_context("partnership", self.sample_match_facts_chase, lang="en")
        self.assertIsNotNone(ctx)
        self.assertTrue(ctx["has_context"])
        self.assertIn("Partnership for Tom Baker & Harry Cole: 42 runs (28 balls)", ctx["text"])

    # 14. Zero-ball edge cases
    def test_14_zero_ball_edge_cases(self):
        zero_facts = {
            "innings": 1,
            "status": "live",
            "batters": [
                {"name": "New Batter", "runs": 0, "balls": 0}
            ],
            "bowler": {
                "name": "Opening Bowler",
                "overs": 0.0,
                "runs": 0
            }
        }
        # Strike rate with 0 balls faced should report 0.00 without division by zero
        ctx_sr = cricket_glossary.build_term_context("strike_rate", zero_facts, lang="en")
        self.assertIsNotNone(ctx_sr)
        self.assertIn("0.00", ctx_sr["text"])

        # Economy rate with 0.0 overs bowled should report 0.00 without division by zero
        ctx_econ = cricket_glossary.build_term_context("economy_rate", zero_facts, lang="en")
        self.assertIsNotNone(ctx_econ)
        self.assertIn("0.00", ctx_econ["text"])

    # 15. Unsupported DLS data
    def test_15_unsupported_dls_data(self):
        t = cricket_glossary.get_term("dls_method", lang="en")
        self.assertIn("proprietary ICC statistical resource tables", t["competition_notes"])
        self.assertIn("does not independently compute DLS models", t["competition_notes"])

    # 16. Competition-specific Powerplay explanations
    def test_16_competition_specific_powerplay(self):
        t = cricket_glossary.get_term("powerplay", lang="en")
        self.assertIn("T20I Cl. 28.7", t["rule_reference"])
        self.assertIn("In a full 20-over T20 match, overs 1–6", t["competition_notes"])
        self.assertIn("In 50-over ODIs, there are three stages", t["competition_notes"])
        self.assertIn("rain-reduced matches", t["competition_notes"])

    # 17. Follow-on threshold accuracy
    def test_17_follow_on_threshold_accuracy(self):
        t = cricket_glossary.get_term("follow_on", lang="en")
        self.assertEqual(t["authority_type"], "MCC Law")
        self.assertIn("MCC Law 14", t["rule_reference"])
        # Check all 4 standard duration thresholds
        notes = t["competition_notes"]
        self.assertIn("200 runs in matches of 5 or more days", notes)
        self.assertIn("150 runs in 3- or 4-day matches", notes)
        self.assertIn("100 runs in 2-day matches", notes)
        self.assertIn("75 runs in 1-day two-innings matches", notes)
        self.assertIn("NEVER applies in standard single-innings limited-overs", notes)

    # 18. Wide and no-ball descriptions
    def test_18_wide_and_no_ball_descriptions(self):
        t_wide = cricket_glossary.get_term("wide_ball", lang="en")
        self.assertEqual(t_wide["authority_type"], "MCC Law")
        self.assertIn("MCC Law 22", t_wide["rule_reference"])
        self.assertIn("Awards 1 extra run", t_wide["definition"])
        self.assertIn("does not count as one of the 6 balls", t_wide["definition"])
        self.assertIn("must be bowled again", t_wide["definition"])

        t_nb = cricket_glossary.get_term("no_ball", lang="en")
        self.assertEqual(t_nb["authority_type"], "MCC Law")
        self.assertIn("MCC Law 21", t_nb["rule_reference"])
        self.assertIn("Adds 1 penalty run", t_nb["definition"])
        self.assertIn("does not count as a legal ball", t_nb["definition"])
        self.assertIn("Free Hit", t_nb["competition_notes"])

    # 19. No fabricated match examples
    def test_19_no_fabricated_match_examples(self):
        # In 1st innings, RRR and Target must not hallucinate a chase
        first_inns_facts = {
            "innings": 1,
            "status": "live",
            "score": 45,
            "overs": "6.0",
        }
        ctx_rrr = cricket_glossary.build_term_context("required_run_rate", first_inns_facts, lang="en")
        self.assertFalse(ctx_rrr["has_context"])
        self.assertIn("1st innings", ctx_rrr["text"])
        self.assertIn("only applies in the 2nd innings", ctx_rrr["text"])

        ctx_target = cricket_glossary.build_term_context("target", first_inns_facts, lang="en")
        self.assertFalse(ctx_target["has_context"])
        self.assertIn("1st innings in progress", ctx_target["text"])

    # 20. No modification of existing match state
    def test_20_no_modification_of_match_state(self):
        orig_facts = copy.deepcopy(self.sample_match_facts_chase)
        _ = cricket_glossary.build_term_context("strike_rate", self.sample_match_facts_chase, lang="en")
        _ = cricket_glossary.build_term_context("economy_rate", self.sample_match_facts_chase, lang="hi")
        _ = cricket_glossary.build_term_context("required_run_rate", self.sample_match_facts_chase, lang="mr")
        self.assertEqual(self.sample_match_facts_chase, orig_facts, "build_term_context must never mutate input facts")


if __name__ == "__main__":
    unittest.main()

