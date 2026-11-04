import unittest
import fan_commentary

class TestRadioCommentary(unittest.TestCase):
    def setUp(self):
        self.live_state_chase = {
            "batting_team": "Royal Challengers",
            "bowling_team": "Super Kings",
            "target": 182,
            "runs_required": 26,
            "balls_remaining": 16,
            "required_run_rate": "9.75",
            "status": "live",
            "run_rate": "9.00"
        }

    def test_01_boundary_four_with_chase_equation(self):
        deliv = {
            "seq": 1,
            "batter_name": "Virat Kohli",
            "bowler_name": "Mitchell Starc",
            "runs_batter": 4,
            "total_runs": 4,
            "is_boundary": True,
            "outcome": "4",
            "score_after": 156,
            "wickets_after": 4,
            "overs_after": "17.2",
            "is_legal": True
        }
        res = fan_commentary.format_delivery_commentary(deliv, live_state=self.live_state_chase, personality="radio_presenter")
        
        self.assertEqual(res["event_type"], "four")
        self.assertEqual(res["headline"], "FOUR!")
        self.assertIn("Virat Kohli", res["text"])
        self.assertIn("Mitchell Starc", res["text"])
        self.assertIn("156", res["text"])
        # Chase equation asserted
        self.assertIn("26 runs", res["text"])
        self.assertIn("16 balls", res["text"])
        self.assertIn("9.75", res["text"])
        
        # Audio text check
        audio = res["audio_text"]
        self.assertIn("Virat Kohli", audio)
        self.assertIn("Mitchell Starc", audio)
        self.assertIn("156 for 4", audio)
        self.assertIn("26 runs from 16 balls to win", audio)
        self.assertIn("required run rate 9 point 75", audio)

    def test_02_boundary_six_announcement(self):
        deliv = {
            "seq": 2,
            "batter_name": "Hardik Pandya",
            "bowler_name": "Pat Cummins",
            "runs_batter": 6,
            "total_runs": 6,
            "is_boundary": True,
            "outcome": "6",
            "score_after": 162,
            "wickets_after": 4,
            "overs_after": "17.3",
            "is_legal": True
        }
        res = fan_commentary.format_delivery_commentary(deliv, live_state=self.live_state_chase, personality="radio_presenter")
        self.assertEqual(res["event_type"], "six")
        self.assertEqual(res["headline"], "SIX!")
        self.assertIn("Hardik Pandya", res["text"])
        self.assertIn("Pat Cummins", res["text"])
        self.assertIn("162", res["text"])

    def test_03_wicket_with_dismissal_details_and_chase(self):
        deliv = {
            "seq": 3,
            "batter_name": "Rohit Sharma",
            "bowler_name": "Pat Cummins",
            "is_wicket": True,
            "wicket_type": "caught",
            "dismissal_desc": "c Warner b Cummins",
            "score_after": 110,
            "wickets_after": 3,
            "overs_after": "12.4",
            "is_legal": True
        }
        chase_st = dict(self.live_state_chase)
        chase_st["runs_required"] = 45
        chase_st["balls_remaining"] = 28
        chase_st["required_run_rate"] = "9.64"
        
        res = fan_commentary.format_delivery_commentary(deliv, live_state=chase_st, personality="radio_presenter")
        self.assertEqual(res["event_type"], "wicket")
        self.assertEqual(res["headline"], "WICKET!")
        self.assertIn("Rohit Sharma", res["text"])
        self.assertIn("Pat Cummins", res["text"])
        self.assertIn("c Warner b Cummins", res["text"])
        self.assertIn("45 runs", res["text"])
        self.assertIn("28 balls", res["text"])
        
        # Audio text
        audio = res["audio_text"]
        self.assertIn("caught by Warner, bowled by Cummins", audio)
        self.assertIn("110 for 3", audio)

    def test_04_missing_player_details_fallback(self):
        deliv = {
            "seq": 4,
            "batter_name": None,
            "bowler_name": None,
            "runs_batter": 4,
            "total_runs": 4,
            "is_boundary": True,
            "outcome": "4",
            "score_after": 20,
            "wickets_after": 0,
            "overs_after": "2.1",
            "is_legal": True
        }
        res = fan_commentary.format_delivery_commentary(deliv, live_state=None, personality="radio_presenter")
        self.assertEqual(res["event_type"], "four")
        # Graceful fallback without crashing
        self.assertIn("Batter", res["text"])
        self.assertIn("Bowler", res["text"])
        self.assertIn("20", res["text"])

    def test_05_over_summary_with_chase_equation(self):
        chase_eq = fan_commentary.format_chase_context(156, 4, live_state=self.live_state_chase)
        res = fan_commentary.format_deterministic_over_summary(
            over_number=17,
            bowler="Mitchell Starc",
            over_runs=12,
            wickets=1,
            score=156,
            total_wickets=4,
            batting_team="Royal Challengers",
            chase_equation=chase_eq
        )
        self.assertEqual(res["event_type"], "over_summary")
        self.assertEqual(res["headline"], "END OF OVER 17")
        self.assertIn("Mitchell Starc", res["text"])
        self.assertIn("12 runs", res["text"])
        self.assertIn("1 wicket", res["text"])
        self.assertIn("26 runs", res["text"])
        self.assertIn("16 balls", res["text"])

    def test_06_match_analyst_and_simple_cricket_personalities(self):
        deliv = {
            "seq": 5,
            "batter_name": "Kohli",
            "bowler_name": "Starc",
            "runs_batter": 4,
            "total_runs": 4,
            "is_boundary": True,
            "outcome": "4",
            "score_after": 156,
            "wickets_after": 4,
            "overs_after": "17.2",
            "is_legal": True
        }
        res_analyst = fan_commentary.format_delivery_commentary(deliv, live_state=self.live_state_chase, personality="match_analyst")
        self.assertIn("Tactical Insight", res_analyst["text"])
        self.assertIn("Kohli", res_analyst["text"])

        res_simple = fan_commentary.format_delivery_commentary(deliv, live_state=self.live_state_chase, personality="simple_cricket")
        self.assertIn("Great shot", res_simple["text"])
        self.assertIn("Kohli", res_simple["text"])

    def test_07_milestones_and_match_completion(self):
        deliv = {
            "seq": 6,
            "batter_name": "Kohli",
            "runs_batter": 4,
            "total_runs": 4,
            "score_after": 150,
            "wickets_after": 4,
            "overs_after": "16.4",
            "is_legal": True
        }
        ms = fan_commentary.detect_milestones(deliv, prev_state={"score": 146})
        self.assertTrue(any(m["type"] == "team_150" for m in ms))

    def test_08_no_repetitive_score_reading_on_routine_dots(self):
        # Sequential dots should vary and avoid repeating the entire score on every ball
        d1 = {"seq": 1, "batter_name": "Kohli", "bowler_name": "Starc", "runs_batter": 0, "outcome": ".", "score_after": 50, "wickets_after": 2, "overs_after": "8.1", "ball_in_over": 1}
        d2 = {"seq": 2, "batter_name": "Kohli", "bowler_name": "Starc", "runs_batter": 0, "outcome": ".", "score_after": 50, "wickets_after": 2, "overs_after": "8.2", "ball_in_over": 2}
        
        r1 = fan_commentary.format_delivery_commentary(d1, personality="radio_presenter")
        r2 = fan_commentary.format_delivery_commentary(d2, personality="radio_presenter")
        
        # Audio texts should be concise and not identical
        self.assertNotEqual(r1["audio_text"], r2["audio_text"])
        self.assertTrue(len(r1["audio_text"]) > 5)
        self.assertTrue(len(r2["audio_text"]) > 5)

if __name__ == "__main__":
    unittest.main()

