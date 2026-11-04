"""
CricketStream Fan Companion — Commentary Engine (Phase 3 Stage 1)
─────────────────────────────────────────────────────────────────
Provides factual, event-driven live cricket commentary and narration.
- Layer 1: Instant deterministic commentary for all delivery outcomes (<1ms).
- Layer 2: Selective asynchronous AI over summaries with automatic fallback.
- Separate monotonic `commentary_seq` and `source_timeline_seq`.
- In-place revisions on edits and clean invalidation on undos.
- Phonetically sanitized `audio_text` for browser SpeechSynthesis.

Never calls /live or /commands, never modifies scoring_engine.py,
never touches the balls table, and never holds DB locks during AI calls.
"""
import copy
import datetime
import json
import os
import re
import sqlite3
import threading
import time

# ── Database Initialization & Schema ─────────────────────────────────────────

def init_commentary_db(conn=None):
    """
    Initializes the dedicated fan_commentary table, meta table, and indexes.
    Completely isolated from the broadcast's original balls table.
    """
    close_after = False
    if conn is None:
        import server
        conn = server._db()
        close_after = True

    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS fan_commentary (
            commentary_id TEXT PRIMARY KEY,
            match_id TEXT NOT NULL,
            innings INTEGER NOT NULL,
            commentary_seq INTEGER NOT NULL,
            source_timeline_seq INTEGER,
            change_seq INTEGER NOT NULL DEFAULT 0,
            over_number INTEGER NOT NULL,
            ball_in_over INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            headline TEXT NOT NULL,
            text TEXT NOT NULL,
            audio_text TEXT NOT NULL,
            is_ai INTEGER NOT NULL DEFAULT 0,
            ai_status TEXT NOT NULL DEFAULT 'none',
            revision INTEGER NOT NULL DEFAULT 1,
            is_corrected INTEGER NOT NULL DEFAULT 0,
            is_uncertain INTEGER NOT NULL DEFAULT 0,
            is_adjustment INTEGER NOT NULL DEFAULT 0,
            is_revoked INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_fan_commentary_seq 
        ON fan_commentary(match_id, innings, commentary_seq);

        CREATE INDEX IF NOT EXISTS idx_fan_commentary_source 
        ON fan_commentary(match_id, innings, source_timeline_seq);

        CREATE INDEX IF NOT EXISTS idx_fan_commentary_over 
        ON fan_commentary(match_id, innings, over_number);

        CREATE TABLE IF NOT EXISTS fan_commentary_meta (
            match_id TEXT NOT NULL,
            innings INTEGER NOT NULL,
            commentary_version INTEGER NOT NULL DEFAULT 1,
            max_change_seq INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (match_id, innings)
        );
        """)

        # Migration: ensure change_seq column exists if table was created earlier without it
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(fan_commentary)")
        cols = [c[1] for c in cursor.fetchall()]
        if "change_seq" not in cols:
            cursor.execute("ALTER TABLE fan_commentary ADD COLUMN change_seq INTEGER NOT NULL DEFAULT 0")

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_fan_commentary_change 
            ON fan_commentary(match_id, innings, change_seq)
        """)

        conn.commit()
    finally:
        if close_after:
            conn.close()


def _get_next_commentary_seq(conn, match_id, innings):
    """Returns the next monotonically increasing sequence number for commentary display."""
    row = conn.execute(
        "SELECT COALESCE(MAX(commentary_seq), 0) FROM fan_commentary WHERE match_id=? AND innings=?",
        (match_id, innings),
    ).fetchone()
    return int(row[0]) + 1 if row and row[0] is not None else 1


def _get_next_change_seq(conn, match_id, innings):
    """
    Returns the next monotonically increasing change sequence number for commentary.
    Every insertion, update/revision, AI replacement, and revocation increments this counter.
    """
    row = conn.execute(
        "SELECT max_change_seq FROM fan_commentary_meta WHERE match_id=? AND innings=?",
        (match_id, innings)
    ).fetchone()
    
    if row is None:
        try:
            m_row = conn.execute(
                "SELECT COALESCE(MAX(change_seq), 0) FROM fan_commentary WHERE match_id=? AND innings=?",
                (match_id, innings)
            ).fetchone()
            cur = int(m_row[0]) if m_row and m_row[0] is not None else 0
        except Exception:
            cur = 0
        nxt = cur + 1
        conn.execute("""
            INSERT INTO fan_commentary_meta (match_id, innings, commentary_version, max_change_seq)
            VALUES (?, ?, 1, ?)
        """, (match_id, innings, nxt))
        return nxt
    else:
        nxt = int(row[0]) + 1
        conn.execute("""
            UPDATE fan_commentary_meta
            SET max_change_seq = ?
            WHERE match_id=? AND innings=?
        """, (nxt, match_id, innings))
        return nxt


def _get_current_change_seq(conn, match_id, innings):
    """Returns the current highest change sequence number for commentary in this innings."""
    row = conn.execute(
        "SELECT max_change_seq FROM fan_commentary_meta WHERE match_id=? AND innings=?",
        (match_id, innings)
    ).fetchone()
    if row and row[0] is not None:
        return int(row[0])
    try:
        row2 = conn.execute(
            "SELECT COALESCE(MAX(change_seq), 0) FROM fan_commentary WHERE match_id=? AND innings=?",
            (match_id, innings)
        ).fetchone()
        return int(row2[0]) if row2 and row2[0] is not None else 0
    except Exception:
        return 0


def _get_commentary_version(conn, match_id, innings):
    """Returns the authoritative commentary version."""
    ver = 1
    try:
        row = conn.execute(
            "SELECT commentary_version FROM fan_commentary_meta WHERE match_id=? AND innings=?",
            (match_id, innings)
        ).fetchone()
        if row and row[0] is not None:
            ver = max(ver, int(row[0]))
    except Exception:
        pass

    try:
        import fan_engine
        rec = fan_engine.get_fan_reconciler()
        if rec and getattr(rec, "mid", None) == match_id:
            ver = max(ver, int(rec.timeline_version))
    except Exception:
        pass

    try:
        row_cp = conn.execute(
            "SELECT timeline_version FROM fan_reconciler_checkpoint WHERE match_id=?", (match_id,)
        ).fetchone()
        if row_cp and row_cp[0] is not None:
            ver = max(ver, int(row_cp[0]))
    except Exception:
        pass

    return ver


def bump_commentary_version(match_id, innings, conn=None):
    """Bumps commentary version on match reset or major timeline rewind."""
    close_after = False
    if conn is None:
        import server
        conn = server._db()
        close_after = True

    try:
        cur = _get_commentary_version(conn, match_id, innings)
        new_ver = cur + 1
        row = conn.execute(
            "SELECT commentary_version FROM fan_commentary_meta WHERE match_id=? AND innings=?",
            (match_id, innings)
        ).fetchone()
        if row:
            conn.execute("""
                UPDATE fan_commentary_meta
                SET commentary_version = ?
                WHERE match_id=? AND innings=?
            """, (new_ver, match_id, innings))
        else:
            conn.execute("""
                INSERT INTO fan_commentary_meta (match_id, innings, commentary_version, max_change_seq)
                VALUES (?, ?, ?, 0)
            """, (match_id, innings, new_ver))
        conn.commit()
        return new_ver
    finally:
        if close_after:
            conn.close()


# ── Speech Synthesis Text Sanitizer ──────────────────────────────────────────

def sanitize_for_speech(text):
    """
    Converts cricket notation and abbreviations into natural speech phrases
    optimized for browser SpeechSynthesis engines.
    """
    if not text:
        return ""

    s = str(text).strip()
    # Replace score formats like 14/2 -> 14 for 2
    s = re.sub(r"\b(\d+)/0\b", r"\1 for no wicket", s)
    s = re.sub(r"\b(\d+)/(\d+)\b", r"\1 for \2", s)

    # Replace overs like (1.4 ov) -> (1 point 4 overs)
    s = re.sub(r"\((\d+)\.(\d+)\s*ov\)", r"\1 point \2 overs", s)
    s = re.sub(r"\b(\d+)\.(\d+)\s*ov\b", r"\1 point \2 overs", s)

    # Cricket terminology
    s = re.sub(r"\b1wd\b", "1 wide", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(\d+)wd\b", r"\1 wides", s, flags=re.IGNORECASE)
    s = re.sub(r"\bnb\b", "no ball", s, flags=re.IGNORECASE)
    s = re.sub(r"\blb\b", "leg bye", s, flags=re.IGNORECASE)
    s = re.sub(r"\bc\s+([A-Z][a-zA-Z]+)\s+b\s+([A-Z][a-zA-Z]+)", r"caught by \1, bowled by \2", s)
    s = re.sub(r"\bb\s+([A-Z][a-zA-Z]+)", r"bowled by \1", s)
    s = re.sub(r"\bRRR\s*(\d+)\.(\d+)\b", r"required run rate \1 point \2", s)
    s = re.sub(r"\bRR\s*(\d+)\.(\d+)\b", r"run rate \1 point \2", s)
    s = re.sub(r"\brequired rate is (\d+)\.(\d+)\b", r"required run rate \1 point \2", s)
    s = re.sub(r"\b(\d+)\.(\d+)\s*per over\b", r"\1 point \2 per over", s)
    s = re.sub(r"\b(\d+)\s*b\b", r"\1 balls", s)
    s = re.sub(r"\b1 balls\b", "1 ball", s)

    # Clean punctuation for natural speech pauses
    s = s.replace("—", ", ").replace("–", ", ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ── Commentary Personalities & Factual Chase Context ─────────────────────────

PERSONALITY_RADIO = "radio_presenter"
PERSONALITY_ANALYST = "match_analyst"
PERSONALITY_SIMPLE = "simple_cricket"


def format_chase_context(score, wickets, live_state=None, delivery=None):
    """
    Computes a factual chase equation string if 2nd innings or target is present.
    Example: 'They need 26 runs from 16 balls to win. The required rate is 9.75 per over.'
    Never invents statistics.
    """
    st = live_state if (live_state and isinstance(live_state, dict)) else (delivery if (delivery and isinstance(delivery, dict)) else {})
    if not st:
        return ""

    target = st.get("target") or st.get("targetRuns")
    if not target:
        return ""
    try:
        target = int(target)
    except (ValueError, TypeError):
        return ""

    if target <= 0:
        return ""

    runs_req = st.get("runs_required")
    if runs_req is None or str(runs_req) in ("N/A", "None", ""):
        runs_req = max(0, target - score)
    else:
        try:
            runs_req = int(runs_req)
        except (ValueError, TypeError):
            runs_req = max(0, target - score)

    balls_rem = st.get("balls_remaining")
    if balls_rem is not None and str(balls_rem) not in ("N/A", "None", ""):
        try:
            balls_rem = int(balls_rem)
        except (ValueError, TypeError):
            balls_rem = None

    rrr = st.get("required_run_rate")
    bat_team = str(st.get("batting_team") or "").strip()

    if balls_rem is not None and balls_rem > 0:
        if runs_req <= 0:
            prefix = f"{bat_team} have " if bat_team else "They have "
            return f"{prefix}reached the target!"

        team_str = f"{bat_team} need " if bat_team else "They need "
        ball_word = "ball" if balls_rem == 1 else "balls"
        run_word = "run" if runs_req == 1 else "runs"

        chase_str = f"{team_str}{runs_req} {run_word} from {balls_rem} {ball_word} to win."
        if rrr and str(rrr).strip() not in ("N/A", "None", ""):
            chase_str += f" The required rate is {rrr} per over."
        return chase_str
    elif runs_req is not None and runs_req > 0:
        team_str = f"{bat_team} need " if bat_team else "They need "
        run_word = "run" if runs_req == 1 else "runs"
        return f"{team_str}{runs_req} {run_word} to win."

    return ""


# ── Deterministic Commentary Templates (Factual & Zero-Hallucination) ────────

_DOT_TEMPLATES = [
    "{bowler} to {batter}, no run. Score is {score}/{wickets} ({overs} ov).",
    "Dot ball. {bowler} bowls a tidy delivery to {batter}. {score}/{wickets}.",
    "{batter} defends {bowler}, no run taken. {score}/{wickets} ({overs} ov).",
]

_SINGLE_TEMPLATES = [
    "{batter} works {bowler} away for a single. {score}/{wickets} ({overs} ov).",
    "1 run. {batter} turns {bowler} into the gap for a single. {score}/{wickets}.",
    "Single taken by {batter} off {bowler}. Score moves to {score}/{wickets}.",
]

_TWO_TEMPLATES = [
    "2 runs. {batter} pushes {bowler} into space and they complete two. {score}/{wickets}.",
    "{batter} and {non_striker} run well between the wickets for a brace. {score}/{wickets}.",
]

_THREE_TEMPLATES = [
    "3 runs. {batter} places {bowler} into the outfield and they run three. {score}/{wickets}.",
]

_FOUR_TEMPLATES = [
    "FOUR! {batter} finds the fence off {bowler}. {team_move} ({overs} ov).{chase}",
    "Boundary! 4 runs to {batter} off {bowler}. {team_move}.{chase}",
    "FOUR runs! {batter} beats the field off {bowler}. {team_reach} ({overs} ov).{chase}",
]

_SIX_TEMPLATES = [
    "SIX! {batter} launches {bowler} over the boundary! {team_move} ({overs} ov).{chase}",
    "MAXIMUM! A clean six from {batter} off {bowler}. {team_reach} ({overs} ov).{chase}",
    "SIX runs! Cleared the ropes in style! {batter} sends {bowler} into the stands. {team_move}.{chase}",
]


def format_delivery_commentary(delivery, live_state=None, personality=PERSONALITY_RADIO):
    """
    Factual transformation of a fan_timeline delivery object into broadcast text,
    headline, and natural speech-friendly audio text.
    Supports Radio Presenter, Match Analyst, and Simple Cricket personalities.
    Never invents fictitious shots, unrecorded fielders, or unverified stats.
    """
    bat = delivery.get("batter_name") or "Batter"
    non_bat = delivery.get("non_striker_name") or "Non-striker"
    bowl = delivery.get("bowler_name") or "Bowler"
    score = delivery.get("score_after", 0)
    wkts = delivery.get("wickets_after", 0)
    ovs = delivery.get("overs_after") or f"{delivery.get('over_number', 1) - 1}.{delivery.get('ball_in_over', 1)}"
    seq = delivery.get("seq", 1)
    tot_runs = delivery.get("total_runs", 0)
    bat_runs = delivery.get("runs_batter", 0)
    extra_type = delivery.get("extra_type")

    # Team names and chase equation
    bat_team = str((live_state.get("batting_team") if live_state else None) or delivery.get("batting_team") or "").strip()
    team_move = f"{bat_team} move to {score}/{wkts}" if bat_team else f"Score moves to {score}/{wkts}"
    team_reach = f"{bat_team} reach {score}/{wkts}" if bat_team else f"Score is {score}/{wkts}"

    chase_eq = format_chase_context(score, wkts, live_state, delivery)
    chase_suffix = f" {chase_eq}" if chase_eq else ""

    # 1. Score Inception / Baseline Adjustment
    if delivery.get("is_adjustment"):
        desc = delivery.get("adjustment_desc") or "Baseline score established"
        text = f"Match feed synchronized: {desc} at {score}/{wkts} ({ovs} ov)."
        headline = "SCORE UPDATE"
        return {"event_type": "adjustment", "headline": headline, "text": text, "audio_text": sanitize_for_speech(text)}

    # 2. Uncertain / Reconstructed Delivery
    if delivery.get("is_uncertain"):
        o_num = delivery.get("over_number", 1)
        text = f"Reconstructed over-boundary delivery for Over {o_num}. Score moves to {score}/{wkts} ({ovs} ov)."
        headline = "OVER BOUNDARY"
        return {"event_type": "uncertain", "headline": headline, "text": text, "audio_text": sanitize_for_speech(text)}

    # 3. Dismissal / Wicket
    if delivery.get("is_wicket"):
        w_type = delivery.get("wicket_type") or "wicket"
        d_desc = delivery.get("dismissal_desc")
        dismiss_phrase = f"OUT ({d_desc})" if d_desc else f"OUT ({w_type})"

        if personality == PERSONALITY_ANALYST:
            text = f"Tactical Insight: Crucial wicket! {bat} is {dismiss_phrase} off {bowl}. {team_move} ({ovs} ov).{chase_suffix}"
        elif personality == PERSONALITY_SIMPLE:
            text = f"Player out! {bat} is {dismiss_phrase} bowled by {bowl}. The fielding team celebrate! {team_reach} ({ovs} ov).{chase_suffix}"
        else: # Radio Presenter
            text = f"WICKET! {bat} is {dismiss_phrase} off {bowl}. {team_move} ({ovs} ov).{chase_suffix}"

        headline = "WICKET!"
        return {"event_type": "wicket", "headline": headline, "text": text, "audio_text": sanitize_for_speech(text)}

    # 4. Boundary Six
    if delivery.get("is_boundary") and (tot_runs == 6 or delivery.get("outcome") == "6" or bat_runs == 6):
        tmpl = _SIX_TEMPLATES[seq % len(_SIX_TEMPLATES)]
        raw_text = tmpl.format(batter=bat, bowler=bowl, score=score, wickets=wkts, overs=ovs,
                               team_move=team_move, team_reach=team_reach, chase=chase_suffix)

        if personality == PERSONALITY_ANALYST:
            text = f"Tactical Insight: Clean maximum! {bat} accelerates off {bowl}. {team_reach} ({ovs} ov).{chase_suffix}"
        elif personality == PERSONALITY_SIMPLE:
            text = f"Massive six! {bat} hits {bowl} right over the boundary! {team_reach} ({ovs} ov).{chase_suffix}"
        else:
            text = raw_text

        headline = "SIX!"
        return {"event_type": "six", "headline": headline, "text": text, "audio_text": sanitize_for_speech(text)}

    # 5. Boundary Four
    if delivery.get("is_boundary") and (tot_runs == 4 or delivery.get("outcome") == "4" or bat_runs == 4):
        tmpl = _FOUR_TEMPLATES[seq % len(_FOUR_TEMPLATES)]
        raw_text = tmpl.format(batter=bat, bowler=bowl, score=score, wickets=wkts, overs=ovs,
                               team_move=team_move, team_reach=team_reach, chase=chase_suffix)

        if personality == PERSONALITY_ANALYST:
            text = f"Tactical Insight: Boundary found by {bat} off {bowl}. That eases the pressure. {team_reach} ({ovs} ov).{chase_suffix}"
        elif personality == PERSONALITY_SIMPLE:
            text = f"Great shot! {bat} finds the boundary for four off {bowl}. {team_reach} ({ovs} ov).{chase_suffix}"
        else:
            text = raw_text

        headline = "FOUR!"
        return {"event_type": "four", "headline": headline, "text": text, "audio_text": sanitize_for_speech(text)}

    # 6. Extras (Wide, No-ball, Bye, Leg-bye)
    if not delivery.get("is_legal") or extra_type:
        if extra_type == "wd" or delivery.get("outcome") == "wide":
            if tot_runs <= 1:
                text = f"Wide ball called against {bowl}. 1 extra. {score}/{wkts} ({ovs} ov)."
            else:
                text = f"{tot_runs} wides conceded by {bowl}. {score}/{wkts} ({ovs} ov)."
            headline = "WIDE"
        elif extra_type == "nb" or delivery.get("outcome") == "noball":
            text = f"No-ball called against {bowl}. {tot_runs} runs added. {score}/{wkts} ({ovs} ov)."
            headline = "NO BALL"
        else:
            et_label = "leg-byes" if extra_type == "lb" else "byes"
            text = f"{tot_runs} {et_label} to the batting side off {bowl}. {score}/{wkts} ({ovs} ov)."
            headline = "EXTRAS"
        return {"event_type": "extra", "headline": headline, "text": text, "audio_text": sanitize_for_speech(text)}

    # 7. Standard Runs off Bat
    if bat_runs == 0 or delivery.get("outcome") in (".", "0"):
        tmpl = _DOT_TEMPLATES[seq % len(_DOT_TEMPLATES)]
        text = tmpl.format(batter=bat, bowler=bowl, score=score, wickets=wkts, overs=ovs)
        headline = "DOT BALL"
        # Audio text: concise radio phrasing without droning full score on every dot
        if (seq % 3 == 0) or (delivery.get("ball_in_over", 1) == 6):
            audio_text = sanitize_for_speech(text)
        else:
            dot_radios = [
                f"{bowl} to {bat}, defended, no run.",
                f"Dot ball. Tidy delivery from {bowl} to {bat}.",
                f"{bat} defends {bowl}, no run taken."
            ]
            audio_text = dot_radios[seq % len(dot_radios)]
        return {"event_type": "dot", "headline": headline, "text": text, "audio_text": audio_text}
    elif bat_runs == 1:
        tmpl = _SINGLE_TEMPLATES[seq % len(_SINGLE_TEMPLATES)]
        text = tmpl.format(batter=bat, bowler=bowl, score=score, wickets=wkts, overs=ovs)
        headline = "1 RUN"
        return {"event_type": "runs", "headline": headline, "text": text, "audio_text": sanitize_for_speech(text)}
    elif bat_runs == 2:
        tmpl = _TWO_TEMPLATES[seq % len(_TWO_TEMPLATES)]
        text = tmpl.format(batter=bat, non_striker=non_bat, bowler=bowl, score=score, wickets=wkts, overs=ovs)
        headline = "2 RUNS"
        return {"event_type": "runs", "headline": headline, "text": text, "audio_text": sanitize_for_speech(text)}
    elif bat_runs == 3:
        tmpl = _THREE_TEMPLATES[seq % len(_THREE_TEMPLATES)]
        text = tmpl.format(batter=bat, bowler=bowl, score=score, wickets=wkts, overs=ovs)
        headline = "3 RUNS"
        return {"event_type": "runs", "headline": headline, "text": text, "audio_text": sanitize_for_speech(text)}
    else:
        text = f"{bat_runs} runs to {bat} off {bowl}. {score}/{wkts} ({ovs} ov)."
        headline = f"{bat_runs} RUNS"
        return {"event_type": "runs", "headline": headline, "text": text, "audio_text": sanitize_for_speech(text)}


# ── Factual Milestone Detection ──────────────────────────────────────────────

def detect_milestones(delivery, prev_state=None):
    """
    Detects factual match and player milestones supported by verified timeline facts.
    Returns list of milestone dicts, or empty list.
    """
    milestones = []
    bat = delivery.get("batter_name") or "Batter"
    score = delivery.get("score_after", 0)
    wkts = delivery.get("wickets_after", 0)
    ovs = delivery.get("overs_after") or "0.0"
    runs_added = delivery.get("total_runs", 0)
    prev_score = score - runs_added if prev_state is None else prev_state.get("score", score - runs_added)

    # Team Milestones (50, 100, 150, 200, 250, 300)
    for boundary in (50, 100, 150, 200, 250, 300):
        if prev_score < boundary <= score:
            text = f"Team milestone: {boundary} up! Total reaches {score}/{wkts} off {ovs} overs."
            milestones.append({
                "type": f"team_{boundary}",
                "headline": f"{boundary} UP!",
                "text": text,
                "audio_text": sanitize_for_speech(text),
            })

    # Individual Batter Milestones (50 and 100)
    # Check if delivery has cumulative batter runs recorded
    bat_runs = delivery.get("runs_batter", 0)
    # If the delivery carries batter's total or if it can be verified
    # When available in live state:
    if prev_state and isinstance(prev_state, dict):
        b1 = prev_state.get("batter1") or {}
        b2 = prev_state.get("batter2") or {}
        p_bat = b1 if b1.get("name") == bat else (b2 if b2.get("name") == bat else None)
        if p_bat:
            old_r = int(p_bat.get("runs", 0) or 0)
            new_r = old_r + bat_runs
            if old_r < 50 <= new_r:
                text = f"FIFTY for {bat}! Reaches a brilliant half-century ({new_r} runs)."
                milestones.append({
                    "type": "batter_fifty",
                    "headline": "FIFTY!",
                    "text": text,
                    "audio_text": sanitize_for_speech(text),
                })
            elif old_r < 100 <= new_r:
                text = f"CENTURY for {bat}! A magnificent hundred reached ({new_r} runs)."
                milestones.append({
                    "type": "batter_century",
                    "headline": "CENTURY!",
                    "text": text,
                    "audio_text": sanitize_for_speech(text),
                })

    return milestones


# ── Over Summary Generator (Immediate Deterministic + Async AI) ──────────────

def format_deterministic_over_summary(over_number, bowler, over_runs, wickets, score, total_wickets, batting_team="", chase_equation=""):
    """
    Creates an immediate, 100% deterministic over summary.
    Available instantly with 0 latency and 0 external API calls.
    """
    w_text = f" and {wickets} wicket" + ("s" if wickets > 1 else "") if wickets > 1 else (" and 1 wicket" if wickets == 1 else " (no wickets)")
    team_str = f" {batting_team}" if batting_team else ""
    run_str = f"{over_runs} run" if over_runs == 1 else f"{over_runs} runs"
    text = (
        f"End of Over {over_number}: {run_str}{w_text} "
        f"from {bowler}'s over.{team_str} {score}/{total_wickets}."
    )
    if chase_equation:
        text += f" {chase_equation}"
    headline = f"END OF OVER {over_number}"
    return {
        "event_type": "over_summary",
        "headline": headline,
        "text": text,
        "audio_text": sanitize_for_speech(text),
    }


def _get_anthropic_api_key():
    import server
    try:
        cfg = server.load_state()
        return cfg.get("anthropic_api_key", "").strip() or os.environ.get("ANTHROPIC_API_KEY", "")
    except Exception:
        return os.environ.get("ANTHROPIC_API_KEY", "")


def async_generate_ai_over_summary(match_id, innings, over_number, prompt_data, commentary_id,
                                    db_updater=None, timeout_sec=6.0):
    """
    Runs Anthropic AI request on a daemon thread.
    NEVER holds database locks while making network calls.
    Updates the existing commentary row with revision = revision + 1 and is_ai = 1.
    """
    def _worker():
        api_key = _get_anthropic_api_key()
        if not api_key:
            return

        try:
            import anthropic
        except ImportError:
            return

        bowler = prompt_data.get("bowler", "Bowler")
        over_runs = prompt_data.get("over_runs", 0)
        wickets = prompt_data.get("wickets", 0)
        score = prompt_data.get("score", 0)
        tot_wkts = prompt_data.get("total_wickets", 0)
        batting_team = prompt_data.get("batting_team", "Batting team")
        balls_str = prompt_data.get("balls_str", "")

        wkt_str = f"{wickets} wicket{'s' if wickets != 1 else ''}" if wickets > 0 else "no wickets"
        prompt = (
            "You are a cricket broadcast radio commentator. "
            "Write ONE crisp sentence (max 20 words) summarising this completed over. "
            "Direct and factual. Use only the names and figures given below. "
            "Never invent fictional shots or unrecorded fielders.\n\n"
            f"Over {over_number}: {over_runs} runs conceded ({wkt_str}). "
            f"Bowler: {bowler}. "
            f"Score: {batting_team} {score}/{tot_wkts} off {over_number} overs. "
            f"Deliveries: {balls_str}.\n"
            "Commentary:"
        )

        try:
            client = anthropic.Anthropic(api_key=api_key)
            msg = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=60,
                messages=[{"role": "user", "content": prompt}],
                timeout=timeout_sec
            )
            ai_text = msg.content[0].text.strip().strip('"').strip("'")
            if "." in ai_text:
                ai_text = ai_text.split(".")[0].strip() + "."

            # Persist update without holding previous lock
            if db_updater:
                db_updater(commentary_id, ai_text)
            else:
                import server
                with server._db_lock, server._db() as conn:
                    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
                    ch_seq = _get_next_change_seq(conn, match_id, innings)
                    conn.execute("""
                        UPDATE fan_commentary
                        SET text = ?, audio_text = ?, is_ai = 1, ai_status = 'completed',
                            revision = revision + 1, change_seq = ?, updated_at = ?
                        WHERE commentary_id = ?
                    """, (ai_text, sanitize_for_speech(ai_text), ch_seq, now_iso, commentary_id))
                    conn.commit()

        except Exception:
            # AI failure is non-fatal: mark status as fallback
            try:
                import server
                with server._db_lock, server._db() as conn:
                    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
                    ch_seq = _get_next_change_seq(conn, match_id, innings)
                    conn.execute("""
                        UPDATE fan_commentary
                        SET ai_status = 'fallback', change_seq = ?, updated_at = ?
                        WHERE commentary_id = ?
                    """, (ch_seq, now_iso, commentary_id))
                    conn.commit()
            except Exception:
                pass

    t = threading.Thread(target=_worker, name=f"AIOverSummary_{over_number}", daemon=True)
    t.start()
    return t


# ── Core Commentary Engine (Reconciler Integration) ──────────────────────────

class FanCommentaryEngine:
    """
    Autonomous live commentary engine.
    Maintains monotonicity of commentary_seq, handles deduplication,
    in-place edits, and undo revocations.
    """

    def __init__(self, match_id="match_1"):
        self.match_id = match_id
        self.lock = threading.Lock()

    def process_reconciled_batch(self, deliveries, live_state=None, conn=None):
        """
        Processes newly committed fan_timeline deliveries.
        Inserts delivery commentary, milestones, and over summaries.
        Executes purely on factual delivery attributes.
        """
        if not deliveries:
            return []

        close_after = False
        if conn is None:
            import server
            conn = server._db()
            close_after = True

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        generated_entries = []

        try:
            with self.lock:
                init_commentary_db(conn)

                for deliv in deliveries:
                    mid = deliv.get("match_id", self.match_id)
                    innings = deliv.get("innings", 1)
                    seq = deliv.get("seq", 1)
                    o_num = deliv.get("over_number", 1)
                    b_num = deliv.get("ball_in_over", 1)
                    is_corr = int(bool(deliv.get("is_corrected", False)))
                    is_unc = int(bool(deliv.get("is_uncertain", False)))
                    is_adj = int(bool(deliv.get("is_adjustment", False)))

                    # 1. Primary Delivery Commentary
                    cid_ball = f"comm_{mid}_i{innings}_s{seq}_ball"
                    formatted = format_delivery_commentary(deliv, live_state=live_state, personality=PERSONALITY_RADIO)

                    # Check for existing commentary row (replay or correction)
                    existing = conn.execute(
                        "SELECT commentary_seq, revision, text FROM fan_commentary WHERE commentary_id=?",
                        (cid_ball,),
                    ).fetchone()

                    if existing:
                        c_seq, rev, old_txt = existing[0], existing[1], existing[2]
                        if old_txt != formatted["text"] or is_corr:
                            ch_seq = _get_next_change_seq(conn, mid, innings)
                            conn.execute("""
                                UPDATE fan_commentary
                                SET text = ?, audio_text = ?, headline = ?, event_type = ?,
                                    is_corrected = 1, revision = revision + 1,
                                    change_seq = ?, updated_at = ?
                                WHERE commentary_id = ?
                            """, (formatted["text"], formatted["audio_text"], formatted["headline"],
                                  formatted["event_type"], ch_seq, now_iso, cid_ball))
                    else:
                        c_seq = _get_next_commentary_seq(conn, mid, innings)
                        ch_seq = _get_next_change_seq(conn, mid, innings)
                        conn.execute("""
                            INSERT INTO fan_commentary (
                                commentary_id, match_id, innings, commentary_seq, source_timeline_seq,
                                change_seq, over_number, ball_in_over, event_type, headline, text, audio_text,
                                is_ai, ai_status, revision, is_corrected, is_uncertain, is_adjustment,
                                is_revoked, created_at, updated_at
                            ) VALUES (
                                ?, ?, ?, ?, ?,
                                ?, ?, ?, ?, ?, ?, ?,
                                0, 'none', 1, ?, ?, ?,
                                0, ?, ?
                            )
                        """, (
                            cid_ball, mid, innings, c_seq, seq,
                            ch_seq, o_num, b_num, formatted["event_type"], formatted["headline"],
                            formatted["text"], formatted["audio_text"],
                            is_corr, is_unc, is_adj, now_iso, now_iso
                        ))

                    generated_entries.append(cid_ball)

                    # 2. Milestone Detection (if any triggered on this ball)
                    milestones = detect_milestones(deliv, live_state)
                    for ms in milestones:
                        cid_ms = f"comm_{mid}_i{innings}_s{seq}_milestone_{ms['type']}"
                        existing_ms = conn.execute(
                            "SELECT commentary_seq FROM fan_commentary WHERE commentary_id=?", (cid_ms,)
                        ).fetchone()
                        if not existing_ms:
                            ms_seq = _get_next_commentary_seq(conn, mid, innings)
                            ch_seq = _get_next_change_seq(conn, mid, innings)
                            conn.execute("""
                                INSERT INTO fan_commentary (
                                    commentary_id, match_id, innings, commentary_seq, source_timeline_seq,
                                    change_seq, over_number, ball_in_over, event_type, headline, text, audio_text,
                                    is_ai, ai_status, revision, is_corrected, is_uncertain, is_adjustment,
                                    is_revoked, created_at, updated_at
                                ) VALUES (
                                    ?, ?, ?, ?, ?,
                                    ?, ?, ?, 'milestone', ?, ?, ?,
                                    0, 'none', 1, 0, 0, 0,
                                    0, ?, ?
                                )
                            """, (
                                cid_ms, mid, innings, ms_seq, seq,
                                ch_seq, o_num, b_num, ms["headline"], ms["text"], ms["audio_text"],
                                now_iso, now_iso
                            ))
                            generated_entries.append(cid_ms)

                    # 3. End-of-Over Summary Detection
                    # Triggered when legal balls in over reach 6 or over completes
                    is_over_end = (b_num >= 6 and deliv.get("is_legal")) or (deliv.get("overs_after", "").endswith(".0") and b_num >= 6)
                    if is_over_end and not is_adj:
                        cid_ov = f"comm_{mid}_i{innings}_o{o_num}_summary"
                        existing_ov = conn.execute(
                            "SELECT commentary_seq FROM fan_commentary WHERE commentary_id=?", (cid_ov,)
                        ).fetchone()

                        # Collect deliveries in this completed over
                        rows = conn.execute("""
                            SELECT total_runs, is_wicket, token FROM fan_timeline
                            WHERE match_id=? AND innings=? AND over_number=?
                            ORDER BY seq ASC
                        """, (mid, innings, o_num)).fetchall()

                        ov_runs = sum(r[0] for r in rows) if rows else deliv.get("runs_batter", 0)
                        ov_wkts = sum(1 for r in rows if r[1]) if rows else (1 if deliv.get("is_wicket") else 0)
                        balls_str = " ".join(r[2] for r in rows) if rows else str(deliv.get("token", ""))

                        bowler = deliv.get("bowler_name") or "Bowler"
                        score = deliv.get("score_after", 0)
                        tot_wkts = deliv.get("wickets_after", 0)
                        bat_team = (live_state.get("batting_team") if live_state else None) or ""

                        chase_eq = format_chase_context(score, tot_wkts, live_state, deliv)
                        det_ov = format_deterministic_over_summary(
                            o_num, bowler, ov_runs, ov_wkts, score, tot_wkts, bat_team, chase_equation=chase_eq
                        )

                        if existing_ov:
                            ch_seq = _get_next_change_seq(conn, mid, innings)
                            conn.execute("""
                                UPDATE fan_commentary
                                SET text = ?, audio_text = ?, revision = revision + 1,
                                    change_seq = ?, updated_at = ?
                                WHERE commentary_id = ?
                            """, (det_ov["text"], det_ov["audio_text"], ch_seq, now_iso, cid_ov))
                        else:
                            ov_seq = _get_next_commentary_seq(conn, mid, innings)
                            ch_seq = _get_next_change_seq(conn, mid, innings)
                            conn.execute("""
                                INSERT INTO fan_commentary (
                                    commentary_id, match_id, innings, commentary_seq, source_timeline_seq,
                                    change_seq, over_number, ball_in_over, event_type, headline, text, audio_text,
                                    is_ai, ai_status, revision, is_corrected, is_uncertain, is_adjustment,
                                    is_revoked, created_at, updated_at
                                ) VALUES (
                                    ?, ?, ?, ?, ?,
                                    ?, ?, 6, 'over_summary', ?, ?, ?,
                                    0, 'pending', 1, 0, ?, 0,
                                    0, ?, ?
                                )
                            """, (
                                cid_ov, mid, innings, ov_seq, seq,
                                ch_seq, o_num, det_ov["headline"], det_ov["text"], det_ov["audio_text"],
                                is_unc, now_iso, now_iso
                            ))
                            generated_entries.append(cid_ov)

                            # Asynchronous selective AI over summary enhancement
                            # Guard: skip AI request if over has uncertain balls or no API key
                            if not is_unc and _get_anthropic_api_key():
                                prompt_info = {
                                    "bowler": bowler, "over_runs": ov_runs, "wickets": ov_wkts,
                                    "score": score, "total_wickets": tot_wkts, "batting_team": bat_team,
                                    "balls_str": balls_str
                                }
                                async_generate_ai_over_summary(mid, innings, o_num, prompt_info, cid_ov)

                # 4. Match Completion Announcement
                if live_state and isinstance(live_state, dict) and (live_state.get("status") == "match_complete" or live_state.get("result_text")):
                    last_deliv = deliveries[-1]
                    s_seq = last_deliv.get("seq", 1)
                    o_last = last_deliv.get("over_number", 1)
                    cid_mc = f"comm_{mid}_i{innings}_match_complete"
                    existing_mc = conn.execute(
                        "SELECT commentary_seq FROM fan_commentary WHERE commentary_id=?", (cid_mc,)
                    ).fetchone()
                    if not existing_mc:
                        res_text = live_state.get("result_text") or "Match completed"
                        mc_text = f"That is the match! {res_text}! A thrilling conclusion to a fantastic contest!"
                        mc_seq = _get_next_commentary_seq(conn, mid, innings)
                        ch_seq = _get_next_change_seq(conn, mid, innings)
                        conn.execute("""
                            INSERT INTO fan_commentary (
                                commentary_id, match_id, innings, commentary_seq, source_timeline_seq,
                                change_seq, over_number, ball_in_over, event_type, headline, text, audio_text,
                                is_ai, ai_status, revision, is_corrected, is_uncertain, is_adjustment,
                                is_revoked, created_at, updated_at
                            ) VALUES (
                                ?, ?, ?, ?, ?,
                                ?, ?, 6, 'match_complete', 'MATCH COMPLETE', ?, ?,
                                0, 'none', 1, 0, 0, 0,
                                0, ?, ?
                            )
                        """, (
                            cid_mc, mid, innings, mc_seq, s_seq,
                            ch_seq, o_last, mc_text, sanitize_for_speech(mc_text),
                            now_iso, now_iso
                        ))
                        generated_entries.append(cid_mc)

                conn.commit()
                return generated_entries

        finally:
            if close_after:
                conn.close()

    def handle_revocations(self, match_id, innings, revoked_seqs, conn=None):
        """
        Invalidates commentary entries whose underlying timeline events were undone.
        Sets is_revoked = 1 and issues a new change_seq so polling clients receive the tombstone.
        """
        if not revoked_seqs:
            return

        close_after = False
        if conn is None:
            import server
            conn = server._db()
            close_after = True

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        try:
            with self.lock:
                init_commentary_db(conn)
                for seq in revoked_seqs:
                    rows = conn.execute("""
                        SELECT commentary_id FROM fan_commentary
                        WHERE match_id = ? AND innings = ? AND source_timeline_seq = ? AND is_revoked = 0
                    """, (match_id, innings, seq)).fetchall()
                    for r in rows:
                        ch_seq = _get_next_change_seq(conn, match_id, innings)
                        conn.execute("""
                            UPDATE fan_commentary
                            SET is_revoked = 1, change_seq = ?, updated_at = ?
                            WHERE commentary_id = ?
                        """, (ch_seq, now_iso, r[0]))
                conn.commit()
        finally:
            if close_after:
                conn.close()


# ── Row Serializer & HTTP API (Phase 3 Stage 2) ──────────────────────────────

def _row_to_commentary(row):
    """Formats an SQLite row from fan_commentary into a client-safe dictionary."""
    col_keys = row.keys() if hasattr(row, "keys") else []
    return {
        "commentary_id": str(row["commentary_id"]),
        "match_id": str(row["match_id"]),
        "innings": int(row["innings"]),
        "commentary_seq": int(row["commentary_seq"]),
        "source_timeline_seq": int(row["source_timeline_seq"]) if row["source_timeline_seq"] is not None else None,
        "change_seq": int(row["change_seq"]) if "change_seq" in col_keys and row["change_seq"] is not None else 0,
        "over_number": int(row["over_number"]),
        "ball_in_over": int(row["ball_in_over"]),
        "event_type": str(row["event_type"]),
        "headline": str(row["headline"]),
        "text": str(row["text"]),
        "audio_text": str(row["audio_text"]),
        "is_ai": bool(row["is_ai"]),
        "ai_status": str(row["ai_status"]),
        "revision": int(row["revision"]),
        "is_corrected": bool(row["is_corrected"]),
        "is_uncertain": bool(row["is_uncertain"]),
        "is_adjustment": bool(row["is_adjustment"]),
        "is_revoked": bool(row["is_revoked"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def get_fan_commentary(qs=None, conn=None):
    """
    HTTP commentary retrieval, polling, and pagination API (Phase 3 Stage 2).
    Retrieves commentary records from fan_commentary in match_data.db.
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
    # Incompatible combinations:
    # - since_seq and before_seq
    # - since_change_seq and before_seq
    # - since_seq and since_change_seq
    if "since_seq" in raw_params and "before_seq" in raw_params:
        return {
            "ok": False,
            "error": "Conflicting cursors: cannot provide both 'since_seq' and 'before_seq' simultaneously"
        }
    if "since_change_seq" in raw_params and "before_seq" in raw_params:
        return {
            "ok": False,
            "error": "Conflicting cursors: cannot provide both 'since_change_seq' and 'before_seq' simultaneously"
        }
    if "since_seq" in raw_params and "since_change_seq" in raw_params:
        return {
            "ok": False,
            "error": "Conflicting cursors: cannot provide both 'since_seq' and 'since_change_seq' simultaneously"
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
        try:
            import fan_engine
            fan_state = fan_engine.get_fan_data()
            if fan_state and isinstance(fan_state, dict) and fan_state.get("ok"):
                innings = fan_state.get("innings", 1)
        except Exception:
            innings = 1
        if not innings or innings not in (1, 2):
            innings = 1

    # 4. Limit validation (default 20, max 50, min 1)
    limit = 20
    if "limit" in raw_params and raw_params["limit"] != "":
        lim_str = str(raw_params["limit"]).strip()
        try:
            lim_int = int(lim_str)
        except (ValueError, TypeError):
            return {"ok": False, "error": f"Invalid limit parameter '{lim_str}': must be an integer"}
        if lim_int < 1:
            return {"ok": False, "error": "Invalid limit parameter: limit must be at least 1"}
        limit = min(lim_int, 50)

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

    # 7. since_change_seq validation
    since_change_seq = None
    if "since_change_seq" in raw_params and raw_params["since_change_seq"] != "":
        sc_str = str(raw_params["since_change_seq"]).strip()
        try:
            sc_int = int(sc_str)
        except (ValueError, TypeError):
            return {"ok": False, "error": f"Invalid since_change_seq parameter '{sc_str}': must be an integer"}
        if sc_int < 0:
            return {"ok": False, "error": "Sequence numbers cannot be negative"}
        since_change_seq = sc_int

    # 8. version validation
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

    # 9. Current match ID
    mid = raw_params.get("match_id")
    if not mid:
        try:
            mid = server.current_match_id()
        except Exception:
            mid = "match_1"

    # 9b. Spoiler delay filter (Stage 8)
    delay_sec = 0
    if "delay" in raw_params and raw_params["delay"] != "":
        try:
            delay_sec = max(0, int(raw_params["delay"]))
        except (ValueError, TypeError):
            delay_sec = 0
    cutoff_iso = None
    if delay_sec > 0:
        cutoff_iso = datetime.datetime.fromtimestamp(time.time() - delay_sec, tz=datetime.timezone.utc).isoformat()

    # 10. Query execution helper
    def _execute(db_c):
        init_commentary_db(db_c)
        db_c.row_factory = sqlite3.Row

        cur_ver = _get_commentary_version(db_c, mid, innings)
        cur_change_seq = _get_current_change_seq(db_c, mid, innings)

        # Stale client version detection
        reset_req = False
        eff_since = since_seq
        eff_before = before_seq
        eff_since_change = since_change_seq

        if client_version is not None and client_version != cur_ver:
            reset_req = True
            # Invalidate client cursors to force latest authoritative page
            eff_since = None
            eff_before = None
            eff_since_change = None

        # Total non-revoked commentary count
        if cutoff_iso:
            row_cnt = db_c.execute(
                "SELECT COUNT(*) AS c FROM fan_commentary WHERE match_id=? AND innings=? AND is_revoked=0 AND created_at <= ?",
                (mid, innings, cutoff_iso),
            ).fetchone()
        else:
            row_cnt = db_c.execute(
                "SELECT COUNT(*) AS c FROM fan_commentary WHERE match_id=? AND innings=? AND is_revoked=0",
                (mid, innings),
            ).fetchone()
        total_commentary = int(row_cnt["c"]) if row_cnt else 0

        # Query commentary
        if eff_since_change is not None:
            # Incremental updates using change cursor: includes new, revised, and revoked tombstones
            if cutoff_iso:
                q = (
                    "SELECT * FROM fan_commentary WHERE match_id=? AND innings=? AND change_seq > ? AND created_at <= ? "
                    "ORDER BY change_seq ASC LIMIT ?"
                )
                rows = db_c.execute(q, (mid, innings, eff_since_change, cutoff_iso, limit + 1)).fetchall()
            else:
                q = (
                    "SELECT * FROM fan_commentary WHERE match_id=? AND innings=? AND change_seq > ? "
                    "ORDER BY change_seq ASC LIMIT ?"
                )
                rows = db_c.execute(q, (mid, innings, eff_since_change, limit + 1)).fetchall()
            has_more = len(rows) > limit
            res_rows = rows[:limit] if has_more else rows
            commentary = [_row_to_commentary(r) for r in res_rows]

            if commentary:
                next_change_seq = commentary[-1]["change_seq"]
                active_seqs = [c["commentary_seq"] for c in commentary if not c["is_revoked"]]
                next_since_seq = max(active_seqs) if active_seqs else None
                next_before_seq = min(active_seqs) if active_seqs else None
            else:
                next_change_seq = eff_since_change
                next_since_seq = None
                next_before_seq = None

        elif eff_before is not None:
            # Older history page: only active records, ordered chronologically
            if cutoff_iso:
                q = (
                    "SELECT * FROM fan_commentary WHERE match_id=? AND innings=? AND is_revoked=0 AND commentary_seq < ? AND created_at <= ? "
                    "ORDER BY commentary_seq DESC LIMIT ?"
                )
                rows = db_c.execute(q, (mid, innings, eff_before, cutoff_iso, limit + 1)).fetchall()
            else:
                q = (
                    "SELECT * FROM fan_commentary WHERE match_id=? AND innings=? AND is_revoked=0 AND commentary_seq < ? "
                    "ORDER BY commentary_seq DESC LIMIT ?"
                )
                rows = db_c.execute(q, (mid, innings, eff_before, limit + 1)).fetchall()
            has_more = len(rows) > limit
            res_rows = rows[:limit] if has_more else rows
            commentary = [_row_to_commentary(r) for r in reversed(res_rows)]

            if commentary:
                next_since_seq = commentary[-1]["commentary_seq"]
                next_before_seq = commentary[0]["commentary_seq"] if has_more else None
            else:
                next_since_seq = None
                next_before_seq = None
            next_change_seq = cur_change_seq

        elif eff_since is not None:
            # Newer records by commentary_seq: only active records
            if cutoff_iso:
                q = (
                    "SELECT * FROM fan_commentary WHERE match_id=? AND innings=? AND is_revoked=0 AND commentary_seq > ? AND created_at <= ? "
                    "ORDER BY commentary_seq ASC LIMIT ?"
                )
                rows = db_c.execute(q, (mid, innings, eff_since, cutoff_iso, limit + 1)).fetchall()
            else:
                q = (
                    "SELECT * FROM fan_commentary WHERE match_id=? AND innings=? AND is_revoked=0 AND commentary_seq > ? "
                    "ORDER BY commentary_seq ASC LIMIT ?"
                )
                rows = db_c.execute(q, (mid, innings, eff_since, limit + 1)).fetchall()
            has_more = len(rows) > limit
            res_rows = rows[:limit] if has_more else rows
            commentary = [_row_to_commentary(r) for r in res_rows]

            if commentary:
                next_since_seq = commentary[-1]["commentary_seq"]
                next_before_seq = commentary[0]["commentary_seq"]
            else:
                next_since_seq = eff_since
                next_before_seq = None
            next_change_seq = cur_change_seq

        else:
            # Initial latest-commentary or version reset snapshot: only active records
            if cutoff_iso:
                q = (
                    "SELECT * FROM fan_commentary WHERE match_id=? AND innings=? AND is_revoked=0 AND created_at <= ? "
                    "ORDER BY commentary_seq DESC LIMIT ?"
                )
                rows = db_c.execute(q, (mid, innings, cutoff_iso, limit + 1)).fetchall()
            else:
                q = (
                    "SELECT * FROM fan_commentary WHERE match_id=? AND innings=? AND is_revoked=0 "
                    "ORDER BY commentary_seq DESC LIMIT ?"
                )
                rows = db_c.execute(q, (mid, innings, limit + 1)).fetchall()
            has_more = len(rows) > limit
            res_rows = rows[:limit] if has_more else rows
            commentary = [_row_to_commentary(r) for r in reversed(res_rows)]

            if commentary:
                next_since_seq = commentary[-1]["commentary_seq"]
                next_before_seq = commentary[0]["commentary_seq"] if has_more else None
            else:
                next_since_seq = None
                next_before_seq = None
            next_change_seq = cur_change_seq

        return {
            "ok": True,
            "match_id": mid,
            "innings": innings,
            "commentary_version": cur_ver,
            "total_commentary": total_commentary,
            "reset_required": reset_req,
            "has_more": has_more,
            "next_since_seq": next_since_seq,
            "next_before_seq": next_before_seq,
            "next_change_seq": next_change_seq,
            "commentary": commentary,
        }

    if conn is not None:
        return _execute(conn)
    else:
        with server._db_lock, server._db() as db_c:
            return _execute(db_c)


# ── Global Engine Instance ───────────────────────────────────────────────────

_global_commentary_engine = FanCommentaryEngine()

def get_fan_commentary_engine():
    return _global_commentary_engine
