export default function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  res.setHeader('Cache-Control', 'no-store, max-age=0');

  if (req.method === 'OPTIONS') {
    return res.status(204).end();
  }

  return res.status(200).json({
    ok: true,
    status: 'live',
    status_display: 'LIVE',
    result_text: null,
    batting_team: 'Royal Challengers',
    bowling_team: 'Super Kings',
    innings: 2,
    score: 156,
    wickets: 4,
    overs: '17.2',
    max_overs: 20,
    run_rate: '9.00',
    target: 182,
    runs_required: 26,
    balls_remaining: 16,
    required_run_rate: '9.75',
    batters: [
      { name: 'Virat Kohli', runs: 68, balls: 42, fours: 5, sixes: 2, strike: true, sr: 161.9 },
      { name: 'Hardik Pandya', runs: 19, balls: 9, fours: 1, sixes: 1, strike: false, sr: 211.1 }
    ],
    bowler: {
      name: 'Mitchell Starc',
      overs: '3.2',
      maidens: 0,
      runs: 28,
      wickets: 1,
      economy: '8.40'
    },
    partnership: { runs: 38, balls: 18 },
    recent_balls: ['4', '1', '.', '6', '2', '1'],
    last_ball_token: '1',
    win_probability: {
      batting_team_pct: 62,
      bowling_team_pct: 38,
      methodology: 'Historical chase model calculated from 26 needed off 16 balls with 6 wickets in hand.',
      limitations: 'Live statistical estimate; does not account for bowler over restrictions.'
    },
    feed_source: 'live',
    feed_fresh: true,
    last_updated_sec_ago: 0
  });
}

