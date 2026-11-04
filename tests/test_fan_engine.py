"""
Unit tests for fan_engine.py (Phase 1 Edge Cases & Match Statuses)
"""
import unittest
import fan_engine


class TestFanEngine(unittest.TestCase):
    def setUp(self):
        with fan_engine._fan_lock:
            fan_engine._fan_cache["ts"] = 0.0
            fan_engine._fan_cache["data"] = None

    def test_pre_match_before_start(self):
        settings = {"home_team": "Exeter CC", "away_team": "Sidmouth CC", "max_overs": 50}
        data = fan_engine.parse_fan_state(None, settings=settings)
        self.assertTrue(data["ok"])
        self.assertEqual(data["status"], "pre_match")
        self.assertEqual(data["status_display"], "PRE-MATCH")
        self.assertIsNone(data["result_text"])
        self.assertEqual(data["batting_team"], "Exeter CC")
        self.assertEqual(data["bowling_team"], "Sidmouth CC")
        self.assertEqual(data["score"], 0)
        self.assertEqual(data["wickets"], 0)
        self.assertEqual(data["overs"], "0.0")
        self.assertEqual(data["max_overs"], 50)
        self.assertEqual(data["run_rate"], "0.00")
        self.assertIsNone(data["target"])
        self.assertIsNone(data["runs_required"])
        self.assertIsNone(data["required_run_rate"])
        self.assertEqual(data["batters"], [])
        self.assertIsNone(data["bowler"])

    def test_pre_match_empty_state_dict(self):
        # When live_state dict is present but match has not yet bowled a ball
        live_state = {
            "battingTeamName": "Home CC",
            "bowlingTeamName": "Opposition CC",
            "innings": 1,
            "score": 0,
            "wickets": 0,
            "overs": "0.0",
            "last_ball": "",
            "match_status": "pre_match",
        }
        data = fan_engine.parse_fan_state(live_state, settings={"max_overs": 40})
        self.assertEqual(data["status"], "pre_match")
        self.assertEqual(data["status_display"], "PRE-MATCH")
        self.assertEqual(data["max_overs"], 40)
        self.assertIsNone(data["result_text"])

    def test_live_first_innings(self):
        live_state = {
            "battingTeamName": "Bridestowe CC",
            "bowlingTeamName": "Belstone CC",
            "innings": 1,
            "score": 115,
            "wickets": 2,
            "overs": 15.3,
            "max_overs": 20,
            "run_rate": 7.42,
            "batter1": {
                "name": "J. Ewen",
                "runs": 58,
                "balls": 38,
                "fours": 7,
                "sixes": 2,
                "onStrike": True,
                "sr": 152.6,
            },
            "batter2": {
                "name": "T. Pengelly",
                "runs": 24,
                "balls": 18,
                "fours": 3,
                "sixes": 0,
                "onStrike": False,
                "sr": 133.3,
            },
            "bowler": {
                "name": "M. Dennis",
                "overs": "3.3",
                "runs": 25,
                "wickets": 1,
                "maidens": 0,
            },
            "partnership_runs": 62,
            "partnership_balls": 44,
            "last_ball": "1 4 . 2 6 1",
            "targetRuns": 0,
            "runsRequired": 0,
        }

        data = fan_engine.parse_fan_state(live_state)
        self.assertEqual(data["status"], "live")
        self.assertEqual(data["status_display"], "LIVE")
        self.assertIsNone(data["result_text"])
        self.assertEqual(data["batting_team"], "Bridestowe CC")
        self.assertEqual(data["bowling_team"], "Belstone CC")
        self.assertEqual(data["score"], 115)
        self.assertEqual(data["wickets"], 2)
        self.assertEqual(data["overs"], "15.3")
        self.assertEqual(data["max_overs"], 20)
        self.assertEqual(data["run_rate"], "7.42")
        self.assertIsNone(data["target"])
        self.assertIsNone(data["runs_required"])
        self.assertIsNone(data["required_run_rate"])

        # Check batters
        self.assertEqual(len(data["batters"]), 2)
        b1, b2 = data["batters"][0], data["batters"][1]
        self.assertEqual(b1["name"], "J. Ewen")
        self.assertEqual(b1["runs"], 58)
        self.assertTrue(b1["strike"])
        self.assertEqual(b2["name"], "T. Pengelly")
        self.assertFalse(b2["strike"])

        # Check bowler
        self.assertIsNotNone(data["bowler"])
        bw = data["bowler"]
        self.assertEqual(bw["name"], "M. Dennis")
        self.assertEqual(bw["overs"], "3.3")
        self.assertEqual(bw["runs"], 25)
        self.assertEqual(bw["wickets"], 1)
        self.assertEqual(bw["economy"], "7.14")

        # Partnership & recent balls
        self.assertEqual(data["partnership"]["runs"], 62)
        self.assertEqual(data["partnership"]["balls"], 44)
        self.assertEqual(data["recent_balls"], ["1", "4", ".", "2", "6", "1"])
        self.assertEqual(data["last_ball_token"], "1")

    def test_innings_one_all_out(self):
        live_state = {
            "battingTeamName": "Bridestowe CC",
            "bowlingTeamName": "Belstone CC",
            "innings": 1,
            "score": 145,
            "wickets": 10,
            "overs": 18.2,
            "max_overs": 20,
        }
        data = fan_engine.parse_fan_state(live_state)
        self.assertEqual(data["status"], "innings_break")
        self.assertEqual(data["status_display"], "INNINGS BREAK")
        self.assertEqual(data["target"], 146)
        self.assertIn("Innings 1 complete: Bridestowe CC set a target of 146", data["result_text"])
        self.assertIsNone(data["required_run_rate"])

    def test_innings_one_overs_limit_reached(self):
        live_state = {
            "battingTeamName": "Bridestowe CC",
            "bowlingTeamName": "Belstone CC",
            "innings": 1,
            "score": 189,
            "wickets": 5,
            "overs": 20.0,
            "max_overs": 20,
        }
        data = fan_engine.parse_fan_state(live_state)
        self.assertEqual(data["status"], "innings_break")
        self.assertEqual(data["status_display"], "INNINGS BREAK")
        self.assertEqual(data["target"], 190)
        self.assertIn("target of 190", data["result_text"])

    def test_live_second_innings_chase(self):
        live_state = {
            "battingTeamName": "Belstone CC",
            "bowlingTeamName": "Bridestowe CC",
            "innings": 2,
            "score": 140,
            "wickets": 4,
            "overs": 18.0,
            "max_overs": 20,
            "run_rate": 7.78,
            "targetRuns": 160,
            "runsRequired": 20,
            "ballsRemaining": 12,
            "batter1": {"name": "A. Player", "runs": 10, "balls": 8, "onStrike": True},
            "batter2": {"name": "B. Player", "runs": 5, "balls": 4, "onStrike": False},
            "bowler": {"name": "C. Bowler", "overs": "3.0", "runs": 18, "wickets": 2},
            "last_ball": "4 1 1 W",
        }

        data = fan_engine.parse_fan_state(live_state)
        self.assertEqual(data["status"], "live")
        self.assertEqual(data["status_display"], "LIVE")
        self.assertIsNone(data["result_text"])
        self.assertEqual(data["target"], 160)
        self.assertEqual(data["runs_required"], 20)
        self.assertEqual(data["balls_remaining"], 12)
        # 20 runs needed in 12 balls = RRR 10.00
        self.assertEqual(data["required_run_rate"], "10.00")
        self.assertEqual(data["recent_balls"], ["4", "1", "1", "W"])
        self.assertEqual(data["last_ball_token"], "W")

    def test_target_successfully_chased(self):
        # 2nd innings chase achieved: 191/5 chasing 190
        live_state = {
            "battingTeamName": "Rival CC",
            "bowlingTeamName": "Home CC",
            "innings": 2,
            "score": 191,
            "wickets": 5,
            "overs": 19.4,
            "max_overs": 20,
            "targetRuns": 190,
            "runsRequired": 0,
            "ballsRemaining": 2,
        }
        data = fan_engine.parse_fan_state(live_state)
        self.assertEqual(data["status"], "match_complete")
        self.assertEqual(data["status_display"], "MATCH COMPLETED")
        self.assertEqual(data["result_text"], "Rival CC won by 5 wickets")
        self.assertEqual(data["runs_required"], 0)
        self.assertIsNone(data["required_run_rate"])

    def test_chase_completed_without_reaching_target(self):
        # The user's exact reported edge case:
        # Score 137/5 chasing 190, 20.0 overs bowled (0 balls remain)
        live_state = {
            "battingTeamName": "Rival CC",
            "bowlingTeamName": "Home CC",
            "innings": 2,
            "score": 137,
            "wickets": 5,
            "overs": "20.0",
            "max_overs": 20,
            "targetRuns": 190,
            "runsRequired": 53,
            "ballsRemaining": 0,
        }
        data = fan_engine.parse_fan_state(live_state)
        self.assertEqual(data["status"], "match_complete")
        self.assertEqual(data["status_display"], "MATCH COMPLETED")
        # 1st innings made 189 (target 190). 2nd innings made 137. Bowling team won by 52 runs!
        self.assertEqual(data["result_text"], "Home CC won by 52 runs")
        self.assertEqual(data["balls_remaining"], 0)
        # Required run rate MUST NOT be "0.00"
        self.assertIsNone(data["required_run_rate"])

    def test_chase_tied(self):
        # 2nd innings finished with scores level: 189/8 chasing 190 off 20.0 overs
        live_state = {
            "battingTeamName": "Rival CC",
            "bowlingTeamName": "Home CC",
            "innings": 2,
            "score": 189,
            "wickets": 8,
            "overs": "20.0",
            "max_overs": 20,
            "targetRuns": 190,
            "runsRequired": 1,
            "ballsRemaining": 0,
        }
        data = fan_engine.parse_fan_state(live_state)
        self.assertEqual(data["status"], "match_complete")
        self.assertEqual(data["status_display"], "MATCH COMPLETED")
        self.assertEqual(data["result_text"], "Match tied")
        self.assertIsNone(data["required_run_rate"])

    def test_chase_all_out_innings(self):
        # 2nd innings batting team all out for 150 chasing 190 in 17.2 overs
        live_state = {
            "battingTeamName": "Rival CC",
            "bowlingTeamName": "Home CC",
            "innings": 2,
            "score": 150,
            "wickets": 10,
            "overs": "17.2",
            "max_overs": 20,
            "targetRuns": 190,
            "runsRequired": 40,
        }
        data = fan_engine.parse_fan_state(live_state)
        self.assertEqual(data["status"], "match_complete")
        self.assertEqual(data["status_display"], "MATCH COMPLETED")
        self.assertEqual(data["result_text"], "Home CC won by 39 runs")
        self.assertIsNone(data["required_run_rate"])

    def test_configured_overs_limit_not_hardcoded_twenty(self):
        # 50-over match: 35.0 overs bowled, 90 balls remaining, max_overs 50
        live_state = {
            "battingTeamName": "Belstone CC",
            "bowlingTeamName": "Bridestowe CC",
            "innings": 2,
            "score": 180,
            "wickets": 4,
            "overs": 35.0,
            "targetRuns": 250,
        }
        settings = {"max_overs": 50}
        data = fan_engine.parse_fan_state(live_state, settings=settings)
        self.assertEqual(data["max_overs"], 50)
        # 50 * 6 = 300 balls; 35.0 overs = 210 balls; 90 balls remaining
        self.assertEqual(data["balls_remaining"], 90)
        self.assertEqual(data["runs_required"], 70)
        # 70 / 90 * 6 = 4.67
        self.assertEqual(data["required_run_rate"], "4.67")
        self.assertEqual(data["status"], "live")

    def test_interrupted_rain_delay(self):
        live_state = {
            "battingTeamName": "Home CC",
            "bowlingTeamName": "Rival CC",
            "innings": 1,
            "score": 85,
            "wickets": 2,
            "overs": 12.3,
            "match_status": "rain_delay",
        }
        data = fan_engine.parse_fan_state(live_state)
        self.assertEqual(data["status"], "interrupted")
        self.assertEqual(data["status_display"], "RAIN DELAY")

    def test_interrupted_by_note(self):
        live_state = {
            "battingTeamName": "Home CC",
            "bowlingTeamName": "Rival CC",
            "innings": 1,
            "score": 60,
            "wickets": 1,
            "overs": 9.1,
            "note": "Rain stopped play - covers on",
        }
        data = fan_engine.parse_fan_state(live_state)
        self.assertEqual(data["status"], "interrupted")
        self.assertEqual(data["status_display"], "RAIN DELAY")
        self.assertEqual(data["result_text"], "Rain stopped play - covers on")

    def test_match_abandoned(self):
        live_state = {
            "battingTeamName": "Home CC",
            "bowlingTeamName": "Rival CC",
            "innings": 1,
            "score": 30,
            "wickets": 1,
            "overs": 5.0,
            "match_status": "abandoned",
        }
        data = fan_engine.parse_fan_state(live_state)
        self.assertEqual(data["status"], "interrupted")
        self.assertEqual(data["status_display"], "MATCH ABANDONED")

    def test_caching_behavior(self):
        call_count = [0]

        def fake_loader():
            call_count[0] += 1
            settings = {"home_team": "Team A", "away_team": "Team B"}
            live_state = {"battingTeamName": "Team A", "score": call_count[0], "overs": 1.0}
            return settings, live_state, "test", True, 0

        current_time = [1000.0]

        def fake_now():
            return current_time[0]

        # Call 1: cold cache -> loader invoked
        d1 = fan_engine.get_fan_data(raw_state_loader=fake_loader, now_fn=fake_now)
        self.assertEqual(call_count[0], 1)
        self.assertEqual(d1["score"], 1)

        # Call 2 at 1000.5s (< TTL) -> cached data returned, loader NOT called
        current_time[0] = 1000.5
        d2 = fan_engine.get_fan_data(raw_state_loader=fake_loader, now_fn=fake_now)
        self.assertEqual(call_count[0], 1)
        self.assertEqual(d2["score"], 1)

        # Call 3 at 1001.2s (> TTL) -> cache expired, loader called again
        current_time[0] = 1001.2
        d3 = fan_engine.get_fan_data(raw_state_loader=fake_loader, now_fn=fake_now)
        self.assertEqual(call_count[0], 2)
        self.assertEqual(d3["score"], 2)


if __name__ == "__main__":
    unittest.main()
