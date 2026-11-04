"""
CricketStream Fan Companion — Fan Engine (Phase 1 & Phase 2 Backend)
───────────────────────────────────────────────────────────────────
Provides safe, read-only extraction, caching, and autonomous ball-by-ball
timeline reconciliation for fan clients.

Never calls /live or /commands, never modifies scoring_engine.py, never
touches _ball_log_prev or _event_buffer, and mutates no broadcast state.
"""
import datetime
import json
import os
import sqlite3
import threading
import time

# ── Phase 1 Cache & State ──────────────────────────────────────────────────
_fan_cache = {"ts": 0.0, "data": None}
_fan_lock = threading.Lock()
CACHE_TTL_SEC = 1.0


def _format_overs(val):
    try:
        f = float(val or 0.0)
        return f"{f:.1f}"
    except (ValueError, TypeError):
        return "0.0"


def _format_run_rate(val):
    try:
        f = float(val or 0.0)
        return f"{f:.2f}"
    except (ValueError, TypeError):
        return "0.00"


def _overs_to_balls(val):
    """
    Converts overs float, int, or string ('16.4', 20.0, '20') to total legal deliveries.
    """
    try:
        s = str(val or "0").strip()
        if "." in s:
            w, _, b = s.partition(".")
            return int(w or 0) * 6 + int(b or 0)
        elif s.isdigit():
            return int(s) * 6
        f = float(s)
        whole = int(f)
        part = round((f - whole) * 10)
        return whole * 6 + part
    except Exception:
        return 0


def _calc_economy(runs, overs_str):
    try:
        r = int(runs or 0)
        balls = _overs_to_balls(overs_str)
        if balls <= 0:
            return "0.00"
        return f"{(r / balls * 6):.2f}"
    except Exception:
        return "0.00"


def _resolve_max_overs(live_state, settings=None):
    """
    Determines configured innings overs limit dynamically. Never hardcodes 20.
    1. live_state.get('max_overs')
    2. Derived from ballsRemaining + overs bowled in 2nd innings
    3. settings.get('max_overs')
    """
    if live_state and isinstance(live_state, dict):
        mo = live_state.get("max_overs")
        if mo is not None:
            try:
                val = int(float(str(mo)))
                if val > 0:
                    return val
            except (ValueError, TypeError):
                pass

        # If ballsRemaining is present in 2nd innings chase, deduce limit
        balls_rem = live_state.get("ballsRemaining")
        if balls_rem is not None:
            try:
                rem = int(balls_rem)
                if rem > 0:
                    bowled = _overs_to_balls(live_state.get("overs"))
                    total = bowled + rem
                    if total > 0 and total % 6 == 0:
                        return total // 6
            except (ValueError, TypeError):
                pass

    if settings and isinstance(settings, dict):
        mo = settings.get("max_overs")
        if mo is not None:
            try:
                val = int(float(str(mo)))
                if val > 0:
                    return val
            except (ValueError, TypeError):
                pass

    return None


def parse_fan_state(live_state, settings=None, now=None):
    """
    Pure transformation of raw PCS/manual live state dict and settings into the
    fan dashboard contract. Never mutates input or external state.
    """
    now = time.time() if now is None else now
    s = settings or {}

    home_default = s.get("home_team", "Home CC")
    away_default = s.get("away_team", "Opposition CC")

    if not live_state or not isinstance(live_state, dict):
        return {
            "ok": True,
            "status": "pre_match",
            "status_display": "PRE-MATCH",
            "result_text": None,
            "feed_source": "none",
            "feed_fresh": False,
            "last_updated_sec_ago": None,
            "batting_team": home_default,
            "bowling_team": away_default,
            "innings": 1,
            "score": 0,
            "wickets": 0,
            "overs": "0.0",
            "max_overs": _resolve_max_overs(None, s),
            "run_rate": "0.00",
            "target": None,
            "runs_required": None,
            "balls_remaining": None,
            "required_run_rate": None,
            "batters": [],
            "bowler": None,
            "partnership": {"runs": 0, "balls": 0},
            "recent_balls": [],
            "last_ball_token": None,
            "win_probability": None,
        }

    score = int(live_state.get("score", 0) or 0)
    wickets = int(live_state.get("wickets", 0) or 0)
    overs_val = live_state.get("overs", 0.0)
    overs_str = _format_overs(overs_val)
    bowled_balls = _overs_to_balls(overs_val)
    rr_str = _format_run_rate(live_state.get("run_rate", 0.0))
    innings = int(live_state.get("innings", 1) or 1)

    batting_team = str(live_state.get("battingTeamName") or home_default).strip() or home_default
    bowling_team = str(live_state.get("bowlingTeamName") or away_default).strip() or away_default

    max_overs = _resolve_max_overs(live_state, s)
    total_quota_balls = (max_overs * 6) if max_overs else None

    # Recent balls (last_ball ticker from this over)
    raw_ticker = str(live_state.get("last_ball", "") or "").strip()
    recent_balls = [t for t in raw_ticker.split() if t]
    last_ball_token = recent_balls[-1] if recent_balls else None

    # Current batters
    batters = []
    for bk in ("batter1", "batter2"):
        b = live_state.get(bk) or {}
        nm = str(b.get("name") or "").strip()
        if nm and nm not in ("—", "-"):
            b_runs = int(b.get("runs", 0) or 0)
            b_balls = int(b.get("balls", 0) or 0)
            sr = float(b.get("sr", 0) or (round(b_runs / b_balls * 100, 1) if b_balls > 0 else 0.0))
            batters.append({
                "name": nm,
                "runs": b_runs,
                "balls": b_balls,
                "fours": int(b.get("fours", 0) or 0),
                "sixes": int(b.get("sixes", 0) or 0),
                "strike": bool(b.get("onStrike")),
                "sr": sr,
            })

    # Current bowler
    bw = live_state.get("bowler") or {}
    bw_name = str(bw.get("name") or "").strip()
    if bw_name and bw_name not in ("—", "-"):
        bw_runs = int(bw.get("runs", 0) or 0)
        bw_overs = str(bw.get("overs", "0") or "0")
        bowler = {
            "name": bw_name,
            "overs": bw_overs,
            "maidens": int(bw.get("maidens", 0) or 0),
            "runs": bw_runs,
            "wickets": int(bw.get("wickets", 0) or 0),
            "economy": _calc_economy(bw_runs, bw_overs),
        }
    else:
        bowler = None

    # Partnership
    p_runs = int(live_state.get("partnership_runs", 0) or 0)
    p_balls = int(live_state.get("partnership_balls", 0) or 0)
    partnership = {"runs": p_runs, "balls": p_balls}

    # Match state detection
    raw_match_status = str(live_state.get("match_status") or live_state.get("status") or "").strip().lower()
    note_text = str(live_state.get("note") or live_state.get("result") or "").strip()
    note_lower = note_text.lower()

    # 1. Interrupted / rain / bad light / abandoned
    is_interrupted = False
    interrupted_label = "MATCH PAUSED"
    if raw_match_status in ("rain", "rain_delay", "interrupted", "delayed", "bad_light", "stumps"):
        is_interrupted = True
        if "rain" in raw_match_status:
            interrupted_label = "RAIN DELAY"
        elif "light" in raw_match_status:
            interrupted_label = "BAD LIGHT"
        elif "stump" in raw_match_status:
            interrupted_label = "STUMPS"
        else:
            interrupted_label = "MATCH PAUSED"
    elif "rain" in note_lower or "weather" in note_lower or "covers" in note_lower:
        is_interrupted = True
        interrupted_label = "RAIN DELAY"
    elif "bad light" in note_lower:
        is_interrupted = True
        interrupted_label = "BAD LIGHT"
    elif raw_match_status == "abandoned" or "abandoned" in note_lower or "no result" in note_lower:
        is_interrupted = True
        interrupted_label = "MATCH ABANDONED"

    # 2. Pre-match check
    has_play = (score > 0 or wickets > 0 or bowled_balls > 0 or bool(recent_balls) or bool(batters))
    if not has_play and raw_match_status in ("", "pre_match", "scheduled", "upcoming"):
        return {
            "ok": True,
            "status": "pre_match",
            "status_display": "PRE-MATCH",
            "result_text": None,
            "batting_team": batting_team,
            "bowling_team": bowling_team,
            "innings": 1,
            "score": 0,
            "wickets": 0,
            "overs": "0.0",
            "max_overs": max_overs,
            "run_rate": "0.00",
            "target": None,
            "runs_required": None,
            "balls_remaining": None,
            "required_run_rate": None,
            "batters": batters,
            "bowler": bowler,
            "partnership": partnership,
            "recent_balls": recent_balls,
            "last_ball_token": last_ball_token,
            "win_probability": None,
        }

    # 3. Innings 1 vs Innings 2 resolution
    raw_target = int(live_state.get("targetRuns", 0) or live_state.get("target", 0) or 0)
    target = raw_target if raw_target > 0 else None

    # Calculate balls remaining and chase stats
    if innings >= 2 or target is not None:
        if not target and int(live_state.get("runsRequired", 0) or 0) > 0:
            target = score + int(live_state["runsRequired"])

        if total_quota_balls is not None:
            balls_rem = max(0, total_quota_balls - bowled_balls)
        elif live_state.get("ballsRemaining") is not None:
            balls_rem = max(0, int(live_state.get("ballsRemaining", 0) or 0))
        else:
            balls_rem = None

        if target is not None:
            runs_req = max(0, target - score)
        else:
            runs_req = None

        if target is not None and score >= target:
            status = "match_complete"
            status_display = "MATCH COMPLETED"
            wkts_left = max(0, 10 - wickets)
            w_word = "wicket" if wkts_left == 1 else "wickets"
            result_text = f"{batting_team} won by {wkts_left} {w_word}"
            rrr_str = None
            runs_req = 0
        elif (target is not None and score < target and
              (balls_rem == 0 or wickets >= 10 or raw_match_status in ("complete", "finished", "match_complete"))):
            status = "match_complete"
            status_display = "MATCH COMPLETED"
            rrr_str = None
            if score == target - 1:
                result_text = "Match tied"
            else:
                margin = (target - 1) - score
                r_word = "run" if margin == 1 else "runs"
                result_text = f"{bowling_team} won by {margin} {r_word}"
        elif is_interrupted:
            status = "interrupted"
            status_display = interrupted_label
            result_text = note_text or f"Match paused ({interrupted_label.title()})"
            rrr_str = None
        else:
            status = "live"
            status_display = "LIVE"
            result_text = None
            if balls_rem and balls_rem > 0 and runs_req is not None:
                rrr_str = f"{(runs_req / balls_rem * 6):.2f}"
            else:
                rrr_str = None

    else:
        target = None
        runs_req = None
        balls_rem = None
        rrr_str = None

        inn1_overs_done = (total_quota_balls is not None and bowled_balls >= total_quota_balls)
        inn1_all_out = (wickets >= 10)
        inn1_ended = (inn1_overs_done or inn1_all_out or
                      raw_match_status in ("innings_break", "break", "innings_complete"))

        if inn1_ended:
            status = "innings_break"
            status_display = "INNINGS BREAK"
            next_target = score + 1
            result_text = f"Innings 1 complete: {batting_team} set a target of {next_target}"
            target = next_target
        elif is_interrupted:
            status = "interrupted"
            status_display = interrupted_label
            result_text = note_text or f"Match paused ({interrupted_label.title()})"
        else:
            status = "live"
            status_display = "LIVE"
            result_text = None

    win_prob = None
    try:
        import win_predictor
        limit = max_overs or 20
        model = win_predictor.league_model([])
        pred = win_predictor.predict(innings, score, wickets, overs_val, limit, model, target=target or 0)
        if pred:
            win_prob = {
                "batting_team_pct": pred["batting"],
                "bowling_team_pct": pred["bowling"],
                "methodology": "Duckworth-Lewis historical resource decay model based on balls left and wickets in hand.",
                "limitations": "Estimates match probability from remaining resource percentages; does not account for pitch degradation or bowler quota restrictions.",
            }
    except Exception:
        win_prob = None

    return {
        "ok": True,
        "status": status,
        "status_display": status_display,
        "result_text": result_text,
        "batting_team": batting_team,
        "bowling_team": bowling_team,
        "innings": innings,
        "score": score,
        "wickets": wickets,
        "overs": overs_str,
        "max_overs": max_overs,
        "run_rate": rr_str,
        "target": target,
        "runs_required": runs_req,
        "balls_remaining": balls_rem,
        "required_run_rate": rrr_str,
        "batters": batters,
        "bowler": bowler,
        "partnership": partnership,
        "recent_balls": recent_balls,
        "last_ball_token": last_ball_token,
        "win_probability": win_prob,
    }


def _get_delayed_fan_data(delay_sec, now=None):
    """
    Reconstructs historical fan match state from verified fan_timeline up to (now - delay_sec).
    Guarantees viewers on TV/streaming broadcast delays do not suffer spoilers.
    """
    if now is None:
        now = time.time()
    cutoff_ts = now - delay_sec
    cutoff_iso = datetime.datetime.fromtimestamp(cutoff_ts, tz=datetime.timezone.utc).isoformat()

    import server
    conn = server._db()
    try:
        init_fan_db(conn)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        try:
            mid = server.current_match_id()
        except Exception:
            mid = "match_1"

        row = cur.execute(
            "SELECT * FROM fan_timeline WHERE match_id=? AND timestamp <= ? ORDER BY innings DESC, seq DESC LIMIT 1",
            (mid, cutoff_iso)
        ).fetchone()

        live_st = get_fan_data(delay_sec=0)

        if not row:
            return {
                "ok": True,
                "status": "pre_match",
                "status_display": "PRE-MATCH",
                "result_text": None,
                "batting_team": live_st.get("batting_team", "Home CC"),
                "bowling_team": live_st.get("bowling_team", "Opposition CC"),
                "innings": 1,
                "score": 0,
                "wickets": 0,
                "overs": "0.0",
                "max_overs": live_st.get("max_overs", 20),
                "run_rate": "0.00",
                "target": None,
                "runs_required": None,
                "balls_remaining": None,
                "required_run_rate": None,
                "batters": [],
                "bowler": None,
                "partnership": {"runs": 0, "balls": 0},
                "recent_balls": [],
                "last_ball_token": "",
                "win_probability": None,
                "feed_source": "delayed_reconciled",
                "feed_fresh": True,
                "last_updated_sec_ago": delay_sec,
                "spoiler_delay_sec": delay_sec,
            }

        innings = int(row["innings"])
        score = int(row["score_after"])
        wickets = int(row["wickets_after"])
        overs_str = str(row["overs_after"])

        recent_rows = cur.execute(
            "SELECT token FROM fan_timeline WHERE match_id=? AND innings=? AND timestamp <= ? ORDER BY seq DESC LIMIT 6",
            (mid, innings, cutoff_iso)
        ).fetchall()
        recent_balls = [r["token"] for r in reversed(recent_rows)]

        batters = []
        if row["batter_name"]:
            batters.append({"name": row["batter_name"], "runs": int(row["runs_batter"]), "balls": 0, "fours": 0, "sixes": 0, "is_striker": True})
        if row["non_striker_name"]:
            batters.append({"name": row["non_striker_name"], "runs": 0, "balls": 0, "fours": 0, "sixes": 0, "is_striker": False})

        bowler = None
        if row["bowler_name"]:
            bowler = {"name": row["bowler_name"], "overs": "0", "maidens": 0, "runs": 0, "wickets": 0}

        target = None
        runs_req = None
        balls_rem = None
        rrr_str = None
        max_overs = live_st.get("max_overs", 20)

        if innings >= 2:
            target_row = cur.execute(
                "SELECT MAX(score_after) FROM fan_timeline WHERE match_id=? AND innings=1 AND timestamp <= ?",
                (mid, cutoff_iso)
            ).fetchone()
            if target_row and target_row[0] is not None:
                target = int(target_row[0]) + 1
            else:
                target = live_st.get("target")
            if target:
                runs_req = max(0, target - score)
            bowled_balls = _overs_to_balls(overs_str)
            total_quota = max_overs * 6 if max_overs else 120
            balls_rem = max(0, total_quota - bowled_balls)
            if balls_rem > 0 and runs_req is not None:
                rrr_str = f"{(runs_req / balls_rem * 6):.2f}"

        rr_str = _format_run_rate(score / max(1, _overs_to_balls(overs_str) / 6))

        win_prob = None
        try:
            import win_predictor
            limit = max_overs or 20
            model = win_predictor.league_model([])
            pred = win_predictor.predict(innings, score, wickets, float(overs_str), limit, model, target=target or 0)
            if pred:
                win_prob = {
                    "batting_team_pct": pred["batting"],
                    "bowling_team_pct": pred["bowling"],
                    "methodology": "Duckworth-Lewis historical resource decay model based on balls left and wickets in hand.",
                    "limitations": "Estimates match probability from remaining resource percentages; does not account for pitch degradation or bowler quota restrictions.",
                }
        except Exception:
            win_prob = None

        return {
            "ok": True,
            "status": "live",
            "status_display": "LIVE (DELAYED)",
            "result_text": None,
            "batting_team": live_st.get("batting_team", "Home CC"),
            "bowling_team": live_st.get("bowling_team", "Opposition CC"),
            "innings": innings,
            "score": score,
            "wickets": wickets,
            "overs": overs_str,
            "max_overs": max_overs,
            "run_rate": rr_str,
            "target": target,
            "runs_required": runs_req,
            "balls_remaining": balls_rem,
            "required_run_rate": rrr_str,
            "batters": batters,
            "bowler": bowler,
            "partnership": {"runs": 0, "balls": 0},
            "recent_balls": recent_balls,
            "last_ball_token": row["token"],
            "win_probability": win_prob,
            "feed_source": "delayed_reconciled",
            "feed_fresh": True,
            "last_updated_sec_ago": delay_sec,
            "spoiler_delay_sec": delay_sec,
        }
    except Exception:
        st = dict(live_st)
        st["spoiler_delay_sec"] = delay_sec
        return st
    finally:
        conn.close()


def get_fan_data(raw_state_loader=None, now_fn=None, delay_sec=0):
    """
    Returns thread-safe, 1s-cached fan match state.
    Calls safe read-only loaders: manual_live_state() or read_score_source(s).
    Never mutates internal match state or databases.
    If delay_sec > 0, returns the delayed state up to cutoff (Stage 8 Spoiler Protection).
    """
    global _fan_cache

    now = time.time() if now_fn is None else now_fn()
    if delay_sec and delay_sec > 0:
        return _get_delayed_fan_data(delay_sec, now=now)
    with _fan_lock:
        if _fan_cache["data"] is not None and 0 <= (now - _fan_cache["ts"]) < CACHE_TTL_SEC:
            return dict(_fan_cache["data"])

    # Fetch live state using the server's safe read interfaces
    if raw_state_loader is not None:
        settings, live_state, feed_source, is_fresh, age_sec = raw_state_loader()
    else:
        import server
        settings = server.load_state()
        manual_state = server.manual_live_state()
        # IMPORTANT: read_score_source() requires settings dict argument
        live_state = manual_state or server.read_score_source(settings)

        if manual_state or server.manual_session_active():
            feed_source = "manual"
            is_fresh = True
            age_sec = 0
        else:
            feed_source = settings.get("pcs_source", "local")
            pcs_dir = server.effective_pcs_folder(settings)
            pcs_path = server.find_pcs_output_file(pcs_dir) if pcs_dir else None
            if pcs_path and os.path.exists(pcs_path):
                try:
                    mtime = os.path.getmtime(pcs_path)
                    age_sec = max(0, int(now - mtime))
                    is_fresh = (age_sec < 120)
                except OSError:
                    age_sec = None
                    is_fresh = False
            else:
                age_sec = None
                is_fresh = False

    if live_state is None and raw_state_loader is None:
        try:
            tl_st = _get_delayed_fan_data(0, now=now)
            if tl_st.get("status") != "pre_match":
                tl_st["feed_source"] = "timeline_reconciled"
                tl_st["feed_fresh"] = True
                tl_st["last_updated_sec_ago"] = 0
                with _fan_lock:
                    _fan_cache["ts"] = now
                    _fan_cache["data"] = tl_st
                return dict(tl_st)
        except Exception:
            pass

    data = parse_fan_state(live_state, settings=settings, now=now)
    data["feed_source"] = feed_source
    data["feed_fresh"] = is_fresh
    data["last_updated_sec_ago"] = age_sec

    with _fan_lock:
        _fan_cache["ts"] = now
        _fan_cache["data"] = data

    return dict(data)


# ── Phase 2 Backend: Dedicated SQLite Tables & Reconciler ──────────────────

def init_fan_db(conn=None):
    """
    Ensures dedicated fan_timeline and fan_reconciler_checkpoint tables exist.
    Never alters, drops, or mutates the broadcast's original balls table.
    """
    close_after = False
    if conn is None:
        import server
        conn = server._db()
        close_after = True

    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS fan_timeline (
            match_id TEXT NOT NULL,
            innings INTEGER NOT NULL,
            seq INTEGER NOT NULL,
            event_id TEXT NOT NULL UNIQUE,
            revision INTEGER NOT NULL DEFAULT 1,
            timeline_version INTEGER NOT NULL DEFAULT 1,
            over_number INTEGER NOT NULL,
            over_idx INTEGER NOT NULL,
            ball_in_over INTEGER NOT NULL,
            legal_ball_in_over INTEGER NOT NULL,
            is_legal INTEGER NOT NULL,
            token TEXT NOT NULL,
            outcome TEXT NOT NULL,
            runs_batter INTEGER NOT NULL DEFAULT 0,
            runs_extras INTEGER NOT NULL DEFAULT 0,
            total_runs INTEGER NOT NULL DEFAULT 0,
            extra_type TEXT,
            is_wicket INTEGER NOT NULL DEFAULT 0,
            wicket_type TEXT,
            dismissal_desc TEXT,
            batter_name TEXT,
            non_striker_name TEXT,
            bowler_name TEXT,
            score_after INTEGER NOT NULL,
            wickets_after INTEGER NOT NULL,
            overs_after TEXT NOT NULL,
            is_boundary INTEGER NOT NULL DEFAULT 0,
            boundary_type TEXT,
            is_corrected INTEGER NOT NULL DEFAULT 0,
            is_uncertain INTEGER NOT NULL DEFAULT 0,
            is_adjustment INTEGER NOT NULL DEFAULT 0,
            adjustment_desc TEXT,
            timestamp TEXT NOT NULL,
            PRIMARY KEY (match_id, innings, seq)
        );

        CREATE INDEX IF NOT EXISTS idx_fan_timeline_cursor 
        ON fan_timeline(match_id, innings, seq);

        CREATE TABLE IF NOT EXISTS fan_reconciler_checkpoint (
            match_id TEXT PRIMARY KEY,
            innings INTEGER NOT NULL,
            last_over_idx INTEGER,
            last_count INTEGER,
            last_score INTEGER,
            last_wickets INTEGER,
            last_sig TEXT,
            last_striker TEXT,
            last_nonstriker TEXT,
            last_bowler TEXT,
            last_mtime_ns INTEGER,
            last_file_size INTEGER,
            timeline_version INTEGER NOT NULL DEFAULT 1,
            updated TEXT NOT NULL
        );
        """)
        conn.commit()
    finally:
        if close_after:
            conn.close()


class FanDeliveryReconciler:
    """
    Isolated, thread-safe delivery reconciler.
    Maintains its own private state, lock, and timeline buffer.
    Never reads or writes _ball_log_prev and never touches _event_buffer.
    """
    _init_db = staticmethod(init_fan_db)

    def __init__(self, match_id="default_match"):
        self.lock = threading.Lock()
        self.match_id = match_id
        self.innings = 1
        self.timeline_version = 1
        self.timeline = []  # In-memory list of deliveries for fast reads
        self.seq = 0
        self.prev = {
            "mid": match_id,
            "innings": 1,
            "over": None,
            "score": 0,
            "wickets": 0,
            "count": 0,
            "striker": "",
            "nonstriker": "",
            "bowler": "",
            "sig": (),
            "done": None,
            "mtime_ns": 0,
            "size": 0,
        }
        self._known_timestamps = {}  # event_id -> preserved ISO timestamp

    def restore_from_db(self, match_id=None, conn=None):
        """
        Restores timeline and checkpoint from SQLite across server restarts.
        """
        mid = match_id or self.match_id
        close_after = False
        if conn is None:
            import server
            conn = server._db()
            close_after = True

        with self.lock:
            try:
                init_fan_db(conn)
                c = conn.cursor()
                # 1. Restore Checkpoint
                cp = c.execute(
                    "SELECT innings, last_over_idx, last_count, last_score, last_wickets, "
                    "last_sig, last_striker, last_nonstriker, last_bowler, last_mtime_ns, "
                    "last_file_size, timeline_version FROM fan_reconciler_checkpoint WHERE match_id=?",
                    (mid,)
                ).fetchone()

                if cp:
                    self.match_id = mid
                    self.innings = cp[0]
                    self.prev["mid"] = mid
                    self.prev["innings"] = cp[0]
                    self.prev["over"] = cp[1]
                    self.prev["count"] = cp[2]
                    self.prev["score"] = cp[3]
                    self.prev["wickets"] = cp[4]
                    sig_str = cp[5] or ""
                    self.prev["sig"] = tuple(sig_str.split()) if sig_str else ()
                    self.prev["striker"] = cp[6] or ""
                    self.prev["nonstriker"] = cp[7] or ""
                    self.prev["bowler"] = cp[8] or ""
                    self.prev["mtime_ns"] = cp[9] or 0
                    self.prev["size"] = cp[10] or 0
                    self.timeline_version = cp[11] or 1

                # 2. Restore Timeline
                rows = c.execute(
                    "SELECT match_id, innings, seq, event_id, revision, timeline_version, "
                    "over_number, over_idx, ball_in_over, legal_ball_in_over, is_legal, "
                    "token, outcome, runs_batter, runs_extras, total_runs, extra_type, "
                    "is_wicket, wicket_type, dismissal_desc, batter_name, non_striker_name, "
                    "bowler_name, score_after, wickets_after, overs_after, is_boundary, "
                    "boundary_type, is_corrected, is_uncertain, is_adjustment, adjustment_desc, "
                    "timestamp FROM fan_timeline WHERE match_id=? ORDER BY innings ASC, seq ASC",
                    (mid,)
                ).fetchall()

                self.timeline = []
                max_seq = 0
                for r in rows:
                    deliv = {
                        "match_id": r[0], "innings": r[1], "seq": r[2], "event_id": r[3],
                        "revision": r[4], "timeline_version": r[5], "over_number": r[6],
                        "over_idx": r[7], "ball_in_over": r[8], "legal_ball_in_over": r[9],
                        "is_legal": bool(r[10]), "token": r[11], "outcome": r[12],
                        "runs_batter": r[13], "runs_extras": r[14], "total_runs": r[15],
                        "extra_type": r[16], "is_wicket": bool(r[17]), "wicket_type": r[18],
                        "dismissal_desc": r[19], "batter_name": r[20], "non_striker_name": r[21],
                        "bowler_name": r[22], "score_after": r[23], "wickets_after": r[24],
                        "overs_after": r[25], "is_boundary": bool(r[26]), "boundary_type": r[27],
                        "is_corrected": bool(r[28]), "is_uncertain": bool(r[29]),
                        "is_adjustment": bool(r[30]), "adjustment_desc": r[31], "timestamp": r[32]
                    }
                    self.timeline.append(deliv)
                    self._known_timestamps[r[3]] = r[32]
                    if r[2] > max_seq:
                        max_seq = r[2]

                self.seq = max_seq
            finally:
                if close_after:
                    conn.close()

    def _persist_timeline_batch(self, new_or_updated_deliveries, checkpoint_data, deleted_seqs=None, conn=None):
        """
        Saves timeline additions/updates and checkpoint in a single SQLite transaction.
        """
        close_after = False
        if conn is None:
            import server
            conn = server._db()
            close_after = True

        try:
            with conn:  # Enforces a single atomic transaction
                init_fan_db(conn)
                c = conn.cursor()

                # 1. Handle any deleted deliveries (from undos)
                if deleted_seqs:
                    for s in deleted_seqs:
                        c.execute("DELETE FROM fan_timeline WHERE match_id=? AND innings=? AND seq=?",
                                  (self.match_id, self.innings, s))

                # 2. Insert or update deliveries
                for d in new_or_updated_deliveries:
                    c.execute("""
                    INSERT OR REPLACE INTO fan_timeline(
                        match_id, innings, seq, event_id, revision, timeline_version,
                        over_number, over_idx, ball_in_over, legal_ball_in_over, is_legal,
                        token, outcome, runs_batter, runs_extras, total_runs, extra_type,
                        is_wicket, wicket_type, dismissal_desc, batter_name, non_striker_name,
                        bowler_name, score_after, wickets_after, overs_after, is_boundary,
                        boundary_type, is_corrected, is_uncertain, is_adjustment,
                        adjustment_desc, timestamp
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        d["match_id"], d["innings"], d["seq"], d["event_id"], d["revision"],
                        d["timeline_version"], d["over_number"], d["over_idx"], d["ball_in_over"],
                        d["legal_ball_in_over"], int(d["is_legal"]), d["token"], d["outcome"],
                        d["runs_batter"], d["runs_extras"], d["total_runs"], d["extra_type"],
                        int(d["is_wicket"]), d["wicket_type"], d["dismissal_desc"], d["batter_name"],
                        d["non_striker_name"], d["bowler_name"], d["score_after"], d["wickets_after"],
                        d["overs_after"], int(d["is_boundary"]), d["boundary_type"],
                        int(d["is_corrected"]), int(d["is_uncertain"]), int(d["is_adjustment"]),
                        d.get("adjustment_desc"), d["timestamp"]
                    ))

                # 3. Update Checkpoint
                cp = checkpoint_data
                now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
                c.execute("""
                INSERT OR REPLACE INTO fan_reconciler_checkpoint(
                    match_id, innings, last_over_idx, last_count, last_score, last_wickets,
                    last_sig, last_striker, last_nonstriker, last_bowler, last_mtime_ns,
                    last_file_size, timeline_version, updated
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    self.match_id, self.innings, cp.get("over"), cp.get("count", 0),
                    cp.get("score", 0), cp.get("wickets", 0), " ".join(cp.get("sig", ())),
                    cp.get("striker", ""), cp.get("nonstriker", ""), cp.get("bowler", ""),
                    cp.get("mtime_ns", 0), cp.get("size", 0), self.timeline_version, now_str
                ))

            # Phase 3 Stage 1: Generate and synchronize commentary after timeline persistence commits
            try:
                import fan_commentary
                comm_engine = fan_commentary.get_fan_commentary_engine()
                if deleted_seqs:
                    comm_engine.handle_revocations(self.match_id, self.innings, deleted_seqs, conn=conn)
                if new_or_updated_deliveries:
                    comm_engine.process_reconciled_batch(new_or_updated_deliveries, checkpoint_data, conn=conn)
            except Exception:
                # Commentary generation exceptions must never interrupt timeline ingestion
                pass
        finally:
            if close_after:
                conn.close()

    def process_manual_snapshot(self, match_id, events_copy, sess_config, conn=None):
        """
        Replays manual scoring events using an isolated ManualScoringSession.
        Executes completely outside _manual_lock. Never modifies active session.
        """
        import server
        temp = server.ManualScoringSession(dict(sess_config))
        reconstructed = []
        seq = 0

        with self.lock:
            self.match_id = match_id
            for ev in events_copy:
                kind = ev.get("event")
                inn = temp.current
                inn_no = temp.innings_no

                if kind == "ball":
                    seq += 1
                    # CRITICAL: Capture state BEFORE applying delivery
                    striker = inn.striker.name
                    non_striker = inn.non_striker.name
                    bowler = inn.bowler_for_over(inn.current_over_no).name
                    over_idx = inn.current_over_no
                    over_num = over_idx + 1
                    ball_in_over = len(inn.over_tokens) + 1
                    is_legal = ev.get("kind") not in ("wide", "noball")
                    legal_ball_in_over = (inn.legal_balls % 6) + (0 if not is_legal else 1)

                    # Advance isolated engine
                    temp._apply(ev, lenient=True)
                    post_inn = temp.innings[inn_no - 1]
                    token = (post_inn.over_tokens[-1] if post_inn.over_tokens
                             else (post_inn.token_history[-1][0][-1] if post_inn.token_history else "?"))

                    score_after = post_inn.total
                    wickets_after = post_inn.wkts
                    overs_after = post_inn.overs_str()

                    classified = server._classify_ball(token)
                    is_wkt = bool(classified.get("wicket"))
                    wkt_detail = post_inn.last_wicket if is_wkt else None

                    # Exact runs semantics
                    runs_val = int(ev.get("runs", 0) or 0)
                    if ev.get("kind") == "wide":
                        runs_bat = 0
                        runs_ext = 1 + runs_val
                        tot_runs = 1 + runs_val
                    elif ev.get("kind") == "noball":
                        runs_bat = runs_val
                        runs_ext = 1
                        tot_runs = 1 + runs_val
                    elif ev.get("kind") in ("bye", "legbye"):
                        runs_bat = 0
                        runs_ext = runs_val or 1
                        tot_runs = runs_val or 1
                    elif ev.get("kind") in ("dot", "W"):
                        runs_bat = 0
                        runs_ext = 0
                        tot_runs = 0
                    else:
                        runs_bat = int(ev.get("kind", 0) or 0)
                        runs_ext = 0
                        tot_runs = runs_bat

                    # Boundary detection off bat (including no-balls with bat runs)
                    is_bnd = (classified["outcome"] in ("4", "6")) or (runs_bat in (4, 6))
                    bnd_type = "four" if (classified["outcome"] == "4" or runs_bat == 4) else ("six" if (classified["outcome"] == "6" or runs_bat == 6) else None)

                    # Human-readable dismissal description
                    dismissal_text = None
                    if is_wkt and wkt_detail:
                        w_type = (wkt_detail.get("type") or "WICKET").upper()
                        f_name = wkt_detail.get("fielder")
                        b_name = wkt_detail.get("bowler") or bowler
                        if w_type == "CAUGHT" and f_name:
                            dismissal_text = f"c {f_name} b {b_name}"
                        elif w_type == "BOWLED":
                            dismissal_text = f"b {b_name}"
                        elif w_type == "LBW":
                            dismissal_text = f"lbw b {b_name}"
                        elif w_type == "RUN OUT":
                            dismissal_text = f"run out ({f_name or b_name})"
                        elif w_type == "STUMPED" and f_name:
                            dismissal_text = f"st {f_name} b {b_name}"
                        else:
                            dismissal_text = wkt_detail.get("howout") or f"{w_type} b {b_name}"

                    event_id = f"del_{match_id}_i{inn_no}_o{over_num}_b{ball_in_over}_s{seq}"

                    # Timestamp preservation: never re-stamp on re-replays
                    ts = ev.get("ts") or self._known_timestamps.get(event_id)
                    if not ts:
                        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
                        self._known_timestamps[event_id] = ts

                    reconstructed.append({
                        "match_id": match_id,
                        "innings": inn_no,
                        "seq": seq,
                        "event_id": event_id,
                        "revision": 1,
                        "timeline_version": self.timeline_version,
                        "over_number": over_num,
                        "over_idx": over_idx,
                        "ball_in_over": ball_in_over,
                        "legal_ball_in_over": legal_ball_in_over,
                        "is_legal": is_legal,
                        "token": token,
                        "outcome": classified["outcome"],
                        "runs_batter": runs_bat,
                        "runs_extras": runs_ext,
                        "total_runs": tot_runs,
                        "extra_type": classified.get("extra"),
                        "is_wicket": is_wkt,
                        "wicket_type": wkt_detail["type"] if wkt_detail else None,
                        "dismissal_desc": dismissal_text,
                        "batter_name": striker,
                        "non_striker_name": non_striker,
                        "bowler_name": bowler,
                        "score_after": score_after,
                        "wickets_after": wickets_after,
                        "overs_after": overs_after,
                        "is_boundary": is_bnd,
                        "boundary_type": bnd_type,
                        "is_corrected": False,
                        "is_uncertain": False,
                        "is_adjustment": False,
                        "adjustment_desc": None,
                        "timestamp": ts,
                    })
                else:
                    temp._apply(ev, lenient=True)

            # Compare against current timeline to detect Undos or Edits
            deleted_seqs = []
            if len(reconstructed) < len(self.timeline):
                # Undo detected: bump timeline_version
                self.timeline_version += 1
                deleted_seqs = [d["seq"] for d in self.timeline[len(reconstructed):]]
                for r in reconstructed:
                    r["timeline_version"] = self.timeline_version
            elif len(reconstructed) == len(self.timeline):
                # Check for edited balls
                has_edit = False
                for idx, (old, new) in enumerate(zip(self.timeline, reconstructed)):
                    if old["token"] != new["token"] or old["total_runs"] != new["total_runs"]:
                        new["revision"] = old["revision"] + 1
                        new["is_corrected"] = True
                        has_edit = True
                if has_edit:
                    self.timeline_version += 1
                    for r in reconstructed:
                        r["timeline_version"] = self.timeline_version

            self.timeline = reconstructed
            self.seq = seq
            self.innings = temp.innings_no
            self.prev["over"] = temp.current.current_over_no
            self.prev["score"] = temp.current.total
            self.prev["wickets"] = temp.current.wkts

            # Persist to SQLite
            self._persist_timeline_batch(
                self.timeline,
                {"over": self.prev["over"], "score": self.prev["score"], "wickets": self.prev["wickets"]},
                deleted_seqs=deleted_seqs,
                conn=conn
            )

    def process_pcs_snapshot(self, live_state, mtime_ns, size, match_id=None, conn=None):
        """
        Reconciles PCS / NV Play scoreboard state without calling /live or using _ball_log_prev.
        Reconstructs deliveries, handles over-boundary recovery, and marks uncertain details honestly.
        """
        import server
        mid = match_id or self.match_id

        with self.lock:
            self.match_id = mid
            balls = server._parse_ticker(live_state.get("last_ball", ""))
            innings = int(live_state.get("innings", 1) or 1)
            over_idx = int(float(live_state.get("overs", 0) or 0))
            score = int(live_state.get("score", 0) or 0)
            wkts = int(live_state.get("wickets", 0) or 0)
            bteam = live_state.get("battingTeamName", "")
            b1 = live_state.get("batter1", {}) or {}
            b2 = live_state.get("batter2", {}) or {}
            striker = b1.get("name", "") if b1.get("onStrike") else b2.get("name", "")
            nonstriker = b2.get("name", "") if b1.get("onStrike") else b1.get("name", "")
            bowler = (live_state.get("bowler", {}) or {}).get("name", "")
            prev = self.prev

            # Inception baseline for mid-match cold start (overs already completed before connecting)
            if not self.timeline and over_idx >= 1 and prev["over"] is None:
                self.seq += 1
                base_score = max(0, score - sum(b["runs"] for b in balls))
                baseline = {
                    "match_id": mid, "innings": innings, "seq": self.seq,
                    "event_id": f"del_{mid}_i{innings}_baseline_s{self.seq}",
                    "revision": 1, "timeline_version": self.timeline_version,
                    "over_number": over_idx, "over_idx": max(0, over_idx - 1),
                    "ball_in_over": 0, "legal_ball_in_over": 0, "is_legal": True,
                    "token": "START", "outcome": "start", "runs_batter": 0,
                    "runs_extras": 0, "total_runs": 0, "extra_type": None,
                    "is_wicket": False, "wicket_type": None, "dismissal_desc": None,
                    "batter_name": striker, "non_striker_name": nonstriker,
                    "bowler_name": bowler, "score_after": base_score, "wickets_after": wkts,
                    "overs_after": f"{over_idx}.0",
                    "is_boundary": False, "boundary_type": None, "is_corrected": False,
                    "is_uncertain": False, "is_adjustment": True,
                    "adjustment_desc": f"Timeline connected at {live_state.get('overs', '0.0')} ov ({score}/{wkts})",
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                }
                self.timeline.append(baseline)
                prev.update({"mid": mid, "innings": innings, "over": over_idx,
                             "score": base_score, "wickets": wkts, "mtime_ns": mtime_ns, "size": size})
                self._persist_timeline_batch([baseline], prev, conn=conn)

            sig = tuple(b["outcome"] for b in balls)
            tail = []
            rolled = (prev["mid"] == mid and prev["innings"] == innings
                      and prev["over"] is not None and over_idx > prev["over"])
            ref = prev.get("sig") if rolled else (
                prev["done"][3] if prev.get("done") and prev["done"][:3] == (mid, innings, over_idx - 1)
                else None)

            # Filter stale NV Play over-boundary tickers
            if (balls and ref and _overs_to_balls(live_state.get("overs", 0) or 0) % 6 == 0
                    and len(sig) >= len(ref) and sig[:len(ref)] == ref):
                tail = balls[len(ref):] if rolled else []
                balls = []

            new_deliveries = []

            # Over-boundary recovery for omitted deliveries
            if rolled:
                now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
                if tail:
                    run, wk = prev["score"], prev["wickets"]
                    for b in tail:
                        self.seq += 1
                        run += b["runs"]
                        wk += 1 if b["wicket"] else 0
                        deliv = {
                            "match_id": mid, "innings": innings, "seq": self.seq,
                            "event_id": f"del_{mid}_i{innings}_o{prev['over']+1}_b{self.seq}_s{self.seq}",
                            "revision": 1, "timeline_version": self.timeline_version,
                            "over_number": prev["over"] + 1, "over_idx": prev["over"],
                            "ball_in_over": prev["count"] + 1, "legal_ball_in_over": 6,
                            "is_legal": bool(b["legal"]), "token": b["outcome"],
                            "outcome": b["outcome"], "runs_batter": b["runs"] if b["legal"] else 0,
                            "runs_extras": b["runs"] if not b["legal"] else 0, "total_runs": b["runs"],
                            "extra_type": b["extra"], "is_wicket": bool(b["wicket"]),
                            "wicket_type": "wicket" if b["wicket"] else None, "dismissal_desc": None,
                            "batter_name": prev["striker"] or striker,
                            "non_striker_name": prev["nonstriker"] or nonstriker,
                            "bowler_name": prev["bowler"] or bowler, "score_after": run,
                            "wickets_after": wk, "overs_after": f"{prev['over']+1}.0",
                            "is_boundary": b["outcome"] in ("4", "6"),
                            "boundary_type": "four" if b["outcome"] == "4" else ("six" if b["outcome"] == "6" else None),
                            "is_corrected": False, "is_uncertain": False, "is_adjustment": False,
                            "adjustment_desc": None, "timestamp": now_iso
                        }
                        new_deliveries.append(deliv)
                        self.timeline.append(deliv)
                        prev["count"] += 1
                    prev.update({"score": run, "wickets": wk})

                # Check for omitted 6th delivery delta
                miss_runs = score - prev["score"] - sum(b["runs"] for b in balls)
                miss_wkts = wkts - prev["wickets"] - sum(1 for b in balls if b["wicket"])
                if miss_runs >= 0 and (miss_runs > 0 or miss_wkts > 0 or (prev["count"] > 0 and not tail)):
                    self.seq += 1
                    synth_tok = "W" if miss_wkts > 0 else (str(miss_runs) if miss_runs else ".")
                    classified = server._classify_ball(synth_tok)
                    deliv = {
                        "match_id": mid, "innings": innings, "seq": self.seq,
                        "event_id": f"del_{mid}_i{innings}_o{prev['over']+1}_b{prev['count']+1}_s{self.seq}",
                        "revision": 1, "timeline_version": self.timeline_version,
                        "over_number": prev["over"] + 1, "over_idx": prev["over"],
                        "ball_in_over": prev["count"] + 1, "legal_ball_in_over": 6,
                        "is_legal": True, "token": synth_tok, "outcome": classified["outcome"],
                        "runs_batter": miss_runs, "runs_extras": 0, "total_runs": miss_runs,
                        "extra_type": None, "is_wicket": miss_wkts > 0,
                        "wicket_type": "wicket" if miss_wkts > 0 else None,
                        "dismissal_desc": "Dismissal deduced from scoreboard delta" if miss_wkts > 0 else None,
                        "batter_name": prev["striker"] or striker,
                        "non_striker_name": prev["nonstriker"] or nonstriker,
                        "bowler_name": prev["bowler"] or bowler,
                        "score_after": prev["score"] + miss_runs,
                        "wickets_after": prev["wickets"] + miss_wkts,
                        "overs_after": f"{prev['over']+1}.0",
                        "is_boundary": synth_tok in ("4", "6"),
                        "boundary_type": "four" if synth_tok == "4" else ("six" if synth_tok == "6" else None),
                        "is_corrected": False,
                        # CRITICAL: Reconstructed deliveries from delta are honestly marked uncertain
                        "is_uncertain": True,
                        "is_adjustment": False,
                        "adjustment_desc": "Over-boundary delivery recovered from scoreboard score delta",
                        "timestamp": now_iso
                    }
                    new_deliveries.append(deliv)
                    self.timeline.append(deliv)

                prev.update({"over": None, "count": 0, "score": score, "wickets": wkts,
                             "done": (mid, innings, prev["over"], prev.get("sig"))})

            # Process deliveries in current over
            if balls:
                over_runs = sum(b["runs"] for b in balls)
                over_start = score - over_runs
                now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
                run = over_start

                # Match against existing deliveries in this over to identify new ones or edits
                existing_in_over = [d for d in self.timeline if d["over_idx"] == over_idx and d["innings"] == innings and not d["is_adjustment"]]
                
                # Check for current-over edits or undos
                if len(balls) < len(existing_in_over):
                    # Current-over undo detected: revoke removed deliveries
                    self.timeline_version += 1
                    revoked_count = len(existing_in_over) - len(balls)
                    for _ in range(revoked_count):
                        popped = self.timeline.pop()
                        conn_del = conn or (server._db() if 'server' in globals() else None)
                        if conn_del:
                            with conn_del:
                                conn_del.execute("DELETE FROM fan_timeline WHERE match_id=? AND innings=? AND seq=?",
                                                 (mid, innings, popped["seq"]))
                    existing_in_over = existing_in_over[:len(balls)]

                raw_tokens = str(live_state.get("last_ball", "") or "").split()
                for i, b in enumerate(balls, start=1):
                    run += b["runs"]
                    raw_tok = raw_tokens[i - 1] if i <= len(raw_tokens) else b["outcome"]
                    if i <= len(existing_in_over):
                        # Existing ball: check for in-place edit
                        old_d = existing_in_over[i - 1]
                        if old_d["token"] != raw_tok or old_d["total_runs"] != b["runs"]:
                            old_d["token"] = raw_tok
                            old_d["outcome"] = b["outcome"]
                            old_d["total_runs"] = b["runs"]
                            old_d["runs_batter"] = b["runs"] if b["legal"] else 0
                            old_d["runs_extras"] = b["runs"] if not b["legal"] else 0
                            old_d["score_after"] = run
                            old_d["revision"] += 1
                            old_d["is_corrected"] = True
                            self.timeline_version += 1
                            new_deliveries.append(old_d)
                    else:
                        # New delivery in active over
                        self.seq += 1
                        is_leg = bool(b["legal"])
                        ball_obj = {
                            "match_id": mid, "innings": innings, "seq": self.seq,
                            "event_id": f"del_{mid}_i{innings}_o{over_idx+1}_b{i}_s{self.seq}",
                            "revision": 1, "timeline_version": self.timeline_version,
                            "over_number": over_idx + 1, "over_idx": over_idx,
                            "ball_in_over": i, "legal_ball_in_over": i,  # Approximate within over
                            "is_legal": is_leg, "token": raw_tok, "outcome": b["outcome"],
                            "runs_batter": b["runs"] if is_leg else 0,
                            "runs_extras": b["runs"] if not is_leg else 0,
                            "total_runs": b["runs"], "extra_type": b["extra"],
                            "is_wicket": bool(b["wicket"]),
                            "wicket_type": "wicket" if b["wicket"] else None,
                            "dismissal_desc": None,
                            "batter_name": striker, "non_striker_name": nonstriker,
                            "bowler_name": bowler, "score_after": run,
                            "wickets_after": wkts, "overs_after": _format_overs(live_state.get("overs", 0)),
                            "is_boundary": b["outcome"] in ("4", "6"),
                            "boundary_type": "four" if b["outcome"] == "4" else ("six" if b["outcome"] == "6" else None),
                            "is_corrected": False, "is_uncertain": False, "is_adjustment": False,
                            "adjustment_desc": None, "timestamp": now_iso
                        }
                        new_deliveries.append(ball_obj)
                        self.timeline.append(ball_obj)

            prev.update({"mid": mid, "innings": innings, "over": over_idx,
                         "score": score, "wickets": wkts, "count": len(balls),
                         "striker": striker, "nonstriker": nonstriker, "bowler": bowler,
                         "sig": tuple(b["outcome"] for b in balls),
                         "mtime_ns": mtime_ns, "size": size})

            if new_deliveries:
                self._persist_timeline_batch(new_deliveries, prev, conn=conn)


# ── Global Reconciler & Worker Lifecycle ───────────────────────────────────

_global_reconciler = FanDeliveryReconciler()
_worker_started = False
_worker_lock = threading.Lock()
_stop_event = threading.Event()
_worker_thread = None


def get_fan_reconciler():
    return _global_reconciler


def _fan_worker_loop():
    """
    Background worker loop. Samples the score source every 500ms.
    Completely isolated from /live and OBS.
    """
    import server

    while not _stop_event.is_set():
        try:
            if server.manual_session_active():
                # Safe read under _manual_lock: snapshot only!
                with server._manual_lock:
                    sess = server._manual_session_locked()
                    if sess:
                        events_copy = [dict(ev) for ev in sess.events]
                        cfg_copy = dict(sess.config)
                        mid = server.current_match_id()
                    else:
                        events_copy, cfg_copy, mid = None, None, None

                # Replay executes OUTSIDE _manual_lock!
                if events_copy is not None:
                    _global_reconciler.process_manual_snapshot(mid, events_copy, cfg_copy)

            else:
                settings = server.load_state()
                pcs_dir = server.effective_pcs_folder(settings)
                pcs_path = server.find_pcs_output_file(pcs_dir) if pcs_dir else None
                if pcs_path and os.path.exists(pcs_path):
                    try:
                        stat = os.stat(pcs_path)
                        mtime_ns = getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9))
                        size = stat.st_size
                    except OSError:
                        mtime_ns, size = 0, 0

                    if mtime_ns != _global_reconciler.prev.get("mtime_ns") or size != _global_reconciler.prev.get("size"):
                        live_state = server.read_score_source(settings)
                        if live_state:
                            mid = server.current_match_id()
                            _global_reconciler.process_pcs_snapshot(live_state, mtime_ns, size, match_id=mid)

        except Exception:
            pass  # Background worker must never crash server process

        _stop_event.wait(0.5)


def start_fan_timeline_worker():
    """
    Explicit, single-instance startup of the timeline background daemon thread.
    Never started on module import. Safe to call multiple times.
    """
    global _worker_started, _worker_thread
    with _worker_lock:
        if _worker_started:
            return
        _stop_event.clear()
        _worker_started = True
        _worker_thread = threading.Thread(target=_fan_worker_loop, name="FanTimelineWorker", daemon=True)
        _worker_thread.start()


def stop_fan_timeline_worker(timeout=2.0):
    """
    Gracefully stops the timeline background worker.
    """
    global _worker_started, _worker_thread
    with _worker_lock:
        if not _worker_started:
            return
        _stop_event.set()
        if _worker_thread and _worker_thread.is_alive():
            _worker_thread.join(timeout=timeout)
        _worker_started = False
        _worker_thread = None


# ── HTTP Timeline API & Pagination (Phase 2 Stage 2) ─────────────────────────

def _row_to_timeline_delivery(row):
    return {
        "match_id": str(row["match_id"]),
        "innings": int(row["innings"]),
        "seq": int(row["seq"]),
        "event_id": str(row["event_id"]),
        "revision": int(row["revision"]),
        "timeline_version": int(row["timeline_version"]),
        "over_number": int(row["over_number"]),
        "over_idx": int(row["over_idx"]),
        "ball_in_over": int(row["ball_in_over"]),
        "legal_ball_in_over": int(row["legal_ball_in_over"]),
        "is_legal": bool(row["is_legal"]),
        "token": str(row["token"]),
        "outcome": str(row["outcome"]),
        "runs_batter": int(row["runs_batter"]),
        "runs_extras": int(row["runs_extras"]),
        "total_runs": int(row["total_runs"]),
        "extra_type": row["extra_type"],
        "is_wicket": bool(row["is_wicket"]),
        "wicket_type": row["wicket_type"],
        "dismissal_desc": row["dismissal_desc"],
        "batter_name": row["batter_name"],
        "non_striker_name": row["non_striker_name"],
        "bowler_name": row["bowler_name"],
        "score_after": int(row["score_after"]),
        "wickets_after": int(row["wickets_after"]),
        "overs_after": str(row["overs_after"]),
        "is_boundary": bool(row["is_boundary"]),
        "boundary_type": row["boundary_type"],
        "is_corrected": bool(row["is_corrected"]),
        "is_uncertain": bool(row["is_uncertain"]),
        "is_adjustment": bool(row["is_adjustment"]),
        "adjustment_desc": row["adjustment_desc"],
        "timestamp": str(row["timestamp"]),
    }


def get_fan_timeline(qs=None, conn=None):
    """
    HTTP timeline retrieval and pagination API (Phase 2 Stage 2).
    Retrieves delivery records from fan_timeline in match_data.db.
    Safe, read-only, never invokes /live or /commands.
    """
    from urllib.parse import parse_qs
    import server

    # 1. Parse parameters and reject ambiguous duplicate keys
    raw_params = {}
    if isinstance(qs, str):
        parsed = parse_qs(qs, keep_blank_values=True)
        for k, v in parsed.items():
            if len(v) > 1:
                return {"ok": False, "error": f"Ambiguous parameter: duplicate values provided for '{k}'"}
            raw_params[k] = v[0]
    elif isinstance(qs, dict):
        for k, v in qs.items():
            if isinstance(v, (list, tuple)):
                if len(v) > 1:
                    return {"ok": False, "error": f"Ambiguous parameter: duplicate values provided for '{k}'"}
                raw_params[k] = v[0] if v else ""
            else:
                raw_params[k] = v
    elif qs is None:
        raw_params = {}

    # 2. Reject conflicting cursors
    if "since_seq" in raw_params and "before_seq" in raw_params:
        return {
            "ok": False,
            "error": "Conflicting cursors: cannot provide both 'since_seq' and 'before_seq' simultaneously"
        }

    # 3. Innings validation
    innings = None
    if "innings" in raw_params and raw_params["innings"] != "":
        val_str = str(raw_params["innings"]).strip()
        try:
            val_int = int(val_str)
        except (ValueError, TypeError):
            return {"ok": False, "error": f"Invalid innings parameter '{val_str}': must be an integer (1 or 2)"}
        if val_int not in (1, 2):
            return {"ok": False, "error": f"Invalid innings parameter '{val_int}': must be 1 or 2"}
        innings = val_int
    else:
        # Active innings detection when omitted
        try:
            fan_state = get_fan_data()
            if fan_state and isinstance(fan_state, dict) and fan_state.get("ok"):
                innings = fan_state.get("innings", 1)
        except Exception:
            innings = 1
        if not innings or innings not in (1, 2):
            innings = 1

    # 4. Limit validation
    limit = 30
    if "limit" in raw_params and raw_params["limit"] != "":
        lim_str = str(raw_params["limit"]).strip()
        try:
            lim_int = int(lim_str)
        except (ValueError, TypeError):
            return {"ok": False, "error": f"Invalid limit parameter '{lim_str}': must be an integer"}
        if lim_int < 1:
            return {"ok": False, "error": "Invalid limit parameter: limit must be at least 1"}
        limit = min(lim_int, 100)

    # 5. since_seq validation
    since_seq = None
    if "since_seq" in raw_params and raw_params["since_seq"] != "":
        s_str = str(raw_params["since_seq"]).strip()
        try:
            s_int = int(s_str)
        except (ValueError, TypeError):
            return {"ok": False, "error": f"Invalid since_seq parameter '{s_str}': must be an integer"}
        if s_int < 0:
            return {"ok": False, "error": "Sequence numbers cannot be negative"}
        since_seq = s_int

    # 6. before_seq validation
    before_seq = None
    if "before_seq" in raw_params and raw_params["before_seq"] != "":
        b_str = str(raw_params["before_seq"]).strip()
        try:
            b_int = int(b_str)
        except (ValueError, TypeError):
            return {"ok": False, "error": f"Invalid before_seq parameter '{b_str}': must be an integer"}
        if b_int < 0:
            return {"ok": False, "error": "Sequence numbers cannot be negative"}
        before_seq = b_int

    # 7. version validation
    client_version = None
    if "version" in raw_params and raw_params["version"] != "":
        v_str = str(raw_params["version"]).strip()
        try:
            v_int = int(v_str)
        except (ValueError, TypeError):
            return {"ok": False, "error": f"Invalid version parameter '{v_str}': must be an integer"}
        if v_int < 0:
            return {"ok": False, "error": "Version cannot be negative"}
        client_version = v_int

    # 8. Current match ID
    mid = raw_params.get("match_id")
    if not mid:
        try:
            mid = server.current_match_id()
        except Exception:
            mid = "match_1"

    # 8b. Spoiler delay filter (Stage 8)
    delay_sec = 0
    if "delay" in raw_params and raw_params["delay"] != "":
        try:
            delay_sec = max(0, int(raw_params["delay"]))
        except (ValueError, TypeError):
            delay_sec = 0
    cutoff_iso = None
    if delay_sec > 0:
        cutoff_iso = datetime.datetime.fromtimestamp(time.time() - delay_sec, tz=datetime.timezone.utc).isoformat()

    # 9. Query execution helper
    def _execute(db_c):
        init_fan_db(db_c)
        db_c.row_factory = sqlite3.Row

        # Current timeline version
        cur_ver = 1
        row_cp = db_c.execute(
            "SELECT timeline_version FROM fan_reconciler_checkpoint WHERE match_id=?", (mid,)
        ).fetchone()
        if row_cp and row_cp["timeline_version"] is not None:
            cur_ver = max(cur_ver, int(row_cp["timeline_version"]))

        row_tl = db_c.execute(
            "SELECT MAX(timeline_version) AS mv FROM fan_timeline WHERE match_id=? AND innings=?",
            (mid, innings),
        ).fetchone()
        if row_tl and row_tl["mv"] is not None:
            cur_ver = max(cur_ver, int(row_tl["mv"]))

        rec = get_fan_reconciler()
        if rec and getattr(rec, "mid", None) == mid:
            cur_ver = max(cur_ver, int(rec.timeline_version))

        # Version mismatch check
        reset_req = False
        eff_since = since_seq
        eff_before = before_seq
        if client_version is not None and client_version != cur_ver:
            reset_req = True
            # Invalidate client cursors to force latest authoritative page
            eff_since = None
            eff_before = None

        # Total deliveries count
        if cutoff_iso:
            row_cnt = db_c.execute(
                "SELECT COUNT(*) AS c FROM fan_timeline WHERE match_id=? AND innings=? AND timestamp <= ?",
                (mid, innings, cutoff_iso),
            ).fetchone()
        else:
            row_cnt = db_c.execute(
                "SELECT COUNT(*) AS c FROM fan_timeline WHERE match_id=? AND innings=?",
                (mid, innings),
            ).fetchone()
        total_deliveries = int(row_cnt["c"]) if row_cnt else 0

        # Query deliveries
        if eff_since is not None:
            # Incremental updates
            if cutoff_iso:
                q = (
                    "SELECT * FROM fan_timeline WHERE match_id=? AND innings=? AND seq > ? AND timestamp <= ? "
                    "ORDER BY seq ASC LIMIT ?"
                )
                rows = db_c.execute(q, (mid, innings, eff_since, cutoff_iso, limit + 1)).fetchall()
            else:
                q = (
                    "SELECT * FROM fan_timeline WHERE match_id=? AND innings=? AND seq > ? "
                    "ORDER BY seq ASC LIMIT ?"
                )
                rows = db_c.execute(q, (mid, innings, eff_since, limit + 1)).fetchall()
            has_more = len(rows) > limit
            res_rows = rows[:limit] if has_more else rows
            deliveries = [_row_to_timeline_delivery(r) for r in res_rows]
        elif eff_before is not None:
            # Older page retrieval
            if cutoff_iso:
                q = (
                    "SELECT * FROM fan_timeline WHERE match_id=? AND innings=? AND seq < ? AND timestamp <= ? "
                    "ORDER BY seq DESC LIMIT ?"
                )
                rows = db_c.execute(q, (mid, innings, eff_before, cutoff_iso, limit + 1)).fetchall()
            else:
                q = (
                    "SELECT * FROM fan_timeline WHERE match_id=? AND innings=? AND seq < ? "
                    "ORDER BY seq DESC LIMIT ?"
                )
                rows = db_c.execute(q, (mid, innings, eff_before, limit + 1)).fetchall()
            has_more = len(rows) > limit
            res_rows = rows[:limit] if has_more else rows
            deliveries = [_row_to_timeline_delivery(r) for r in reversed(res_rows)]
        else:
            # Initial latest-deliveries or version reset snapshot
            if cutoff_iso:
                q = (
                    "SELECT * FROM fan_timeline WHERE match_id=? AND innings=? AND timestamp <= ? "
                    "ORDER BY seq DESC LIMIT ?"
                )
                rows = db_c.execute(q, (mid, innings, cutoff_iso, limit + 1)).fetchall()
            else:
                q = (
                    "SELECT * FROM fan_timeline WHERE match_id=? AND innings=? "
                    "ORDER BY seq DESC LIMIT ?"
                )
                rows = db_c.execute(q, (mid, innings, limit + 1)).fetchall()
            has_more = len(rows) > limit
            res_rows = rows[:limit] if has_more else rows
            deliveries = [_row_to_timeline_delivery(r) for r in reversed(res_rows)]

        # Cursor pointers
        if deliveries:
            next_since_seq = deliveries[-1]["seq"]
            if eff_before is not None:
                next_before_seq = deliveries[0]["seq"] if has_more else None
            elif eff_since is not None:
                next_before_seq = deliveries[0]["seq"]
            else:
                next_before_seq = deliveries[0]["seq"] if has_more else None
        else:
            has_more = False
            next_since_seq = eff_since if eff_since is not None else None
            next_before_seq = None

        return {
            "ok": True,
            "match_id": mid,
            "innings": innings,
            "timeline_version": cur_ver,
            "total_deliveries": total_deliveries,
            "reset_required": reset_req,
            "has_more": has_more,
            "next_since_seq": next_since_seq,
            "next_before_seq": next_before_seq,
            "deliveries": deliveries,
        }

    if conn is not None:
        return _execute(conn)
    else:
        with server._db_lock, server._db() as db_c:
            return _execute(db_c)


def get_fan_commentary(qs=None, conn=None):
    """
    HTTP live commentary retrieval and pagination API (Phase 3 Stage 2).
    Delegates cleanly to fan_commentary.get_fan_commentary.
    """
    import fan_commentary
    return fan_commentary.get_fan_commentary(qs, conn=conn)


