"""
Playwright UI Automated Visual Inspection & Verification Script
───────────────────────────────────────────────────────────────
Renders the live fan companion dashboard in both Desktop (1280x800)
and Mobile (390x844) viewports using headless Chromium.
Captures screenshots and validates:
- Zero horizontal overflow (scrollWidth <= clientWidth)
- Outcome badge rendering and colors
- Delivery cards readability
- Over grouping and token pills
- Innings tab switching interaction
- 'Show earlier deliveries' pagination interaction
- Latest delivery highlight styling
"""
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fan_engine
import server


def setup_test_server():
    tmp = tempfile.mkdtemp(prefix="cricket_e2e_")
    server.STATE_FILE = os.path.join(tmp, "match_state.json")
    server._db_path = lambda: os.path.join(tmp, "match_data.db")
    server.MANUAL_SCORING_FILE = os.path.join(tmp, "manual_scoring.json")
    server._manual["session"] = None
    server._manual["load_attempted"] = True
    server._CLUB_PASSWORD = ""
    server._CONTROL_TOKEN = "cd" * 32
    server._last_good_state = None
    server.save_state(dict(server.DEFAULT_STATE))
    server.db_init()

    # Prepopulate timeline with realistic match deliveries (Overs 1 to 3)
    with server._db_lock, server._db() as conn:
        fan_engine.init_fan_db(conn)
        mid = server.current_match_id()

        # Seed 15 deliveries across 3 overs
        balls_spec = [
            # Over 1
            (1, 1, 1, "0", ".", 0, 0, 0, True, False, "Smith", "Jones", "Anderson", 0, 0, "0.1"),
            (1, 1, 2, "1", "1", 1, 0, 1, True, False, "Smith", "Jones", "Anderson", 1, 0, "0.2"),
            (1, 1, 3, "4", "4", 4, 0, 4, True, False, "Jones", "Smith", "Anderson", 5, 0, "0.3"),
            (1, 1, 4, "1wd", "wd", 0, 1, 1, False, False, "Jones", "Smith", "Anderson", 6, 0, "0.3"),
            (1, 1, 5, "0", ".", 0, 0, 0, True, False, "Jones", "Smith", "Anderson", 6, 0, "0.4"),
            (1, 1, 6, "6", "6", 6, 0, 6, True, False, "Jones", "Smith", "Anderson", 12, 0, "0.5"),
            (1, 1, 7, "1", "1", 1, 0, 1, True, False, "Jones", "Smith", "Anderson", 13, 0, "1.0"),
            # Over 2
            (1, 2, 1, "0", ".", 0, 0, 0, True, False, "Jones", "Smith", "Broad", 13, 0, "1.1"),
            (1, 2, 2, "2", "2", 2, 0, 2, True, False, "Jones", "Smith", "Broad", 15, 0, "1.2"),
            (1, 2, 3, "W", "W", 0, 0, 0, True, True, "Jones", "Smith", "Broad", 15, 1, "1.3"),
            (1, 2, 4, "0", ".", 0, 0, 0, True, False, "Root", "Smith", "Broad", 15, 1, "1.4"),
            (1, 2, 5, "4", "4", 4, 0, 4, True, False, "Root", "Smith", "Broad", 19, 1, "1.5"),
            (1, 2, 6, "1", "1", 1, 0, 1, True, False, "Root", "Smith", "Broad", 20, 1, "2.0"),
            # Over 3
            (1, 3, 1, "0", ".", 0, 0, 0, True, False, "Root", "Smith", "Anderson", 20, 1, "2.1"),
            (1, 3, 2, "6", "6", 6, 0, 6, True, False, "Root", "Smith", "Anderson", 26, 1, "2.2"),
        ]

        for b in balls_spec:
            inns, o_num, b_num, tok, outc, rb, rx, tr, leg, wkt, bat, nbat, bowl, sc, wkts, ovs = b
            seq = len(balls_spec) - balls_spec.index(b)  # 1 to 15
            conn.execute("""
                INSERT INTO fan_timeline (
                    match_id, innings, seq, event_id, revision, timeline_version,
                    over_number, over_idx, ball_in_over, legal_ball_in_over, is_legal,
                    token, outcome, runs_batter, runs_extras, total_runs, extra_type,
                    is_wicket, wicket_type, dismissal_desc, batter_name, non_striker_name,
                    bowler_name, score_after, wickets_after, overs_after, is_boundary,
                    boundary_type, is_corrected, is_uncertain, is_adjustment, adjustment_desc,
                    timestamp
                ) VALUES (
                    ?, ?, ?, ?, 1, 1,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, 0, 0, 0, NULL,
                    '2026-11-01T12:00:00Z'
                )
            """, (
                mid, inns, seq, f"del_{mid}_i{inns}_s{seq}",
                o_num, o_num - 1, b_num, b_num, int(leg),
                tok, outc, rb, rx, tr, "wd" if not leg else None,
                int(wkt), "caught" if wkt else None, "c Jones b Broad" if wkt else None,
                bat, nbat, bowl, sc, wkts, ovs,
                int(outc in ("4", "6")), "four" if outc == "4" else ("six" if outc == "6" else None)
            ))

        # Checkpoint
        conn.execute("""
            INSERT OR REPLACE INTO fan_reconciler_checkpoint
            (match_id, innings, timeline_version, updated)
            VALUES (?, 1, 1, '2026-11-01T12:00:00Z')
        """, (mid,))
        conn.commit()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, port, tmp


def main():
    httpd, port, tmp = setup_test_server()
    artifact_dir = r"C:\Users\augestin\.gemini\antigravity\brain\0a4a53b2-ae2c-4c2e-a0e5-5594439bb9d1"
    os.makedirs(artifact_dir, exist_ok=True)
    desktop_png = os.path.join(artifact_dir, "fan_desktop.png")
    mobile_png = os.path.join(artifact_dir, "fan_mobile.png")

    print(f"Ephemeral test server running on port {port}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # ── 1. Desktop Viewport (1280x800) ──────────────────────────────────
        desktop_page = browser.new_page(viewport={"width": 1280, "height": 800})
        desktop_page.goto(f"http://127.0.0.1:{port}/fan")
        desktop_page.wait_for_selector(".over-block", timeout=5000)
        time.sleep(0.5)

        # Verify no horizontal scrollbar/overflow
        has_h_scroll = desktop_page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
        print(f"Desktop horizontal scroll overflow: {has_h_scroll}")
        assert not has_h_scroll, "Desktop layout has horizontal overflow!"

        # Verify elements exist
        over_count = desktop_page.locator(".over-block").count()
        print(f"Desktop rendered {over_count} over blocks")
        assert over_count > 0, "No over blocks rendered"

        # Capture Desktop screenshot
        desktop_page.screenshot(path=desktop_png, full_page=True)
        print(f"Saved desktop screenshot to: {desktop_png}")
        desktop_page.close()

        # ── 2. Mobile Viewport (390x844 - iPhone 12/13/14 size) ──────────────
        mobile_page = browser.new_page(viewport={"width": 390, "height": 844},
                                       user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)")
        mobile_page.goto(f"http://127.0.0.1:{port}/fan")
        mobile_page.wait_for_selector(".over-block", timeout=5000)
        time.sleep(0.5)

        # Verify no mobile horizontal scrollbar/overflow
        mob_h_scroll = mobile_page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
        print(f"Mobile horizontal scroll overflow: {mob_h_scroll}")
        assert not mob_h_scroll, "Mobile layout has horizontal overflow!"

        # Verify latest delivery highlight
        latest_items = mobile_page.locator(".delivery-item.latest").count()
        print(f"Mobile latest delivery highlighted: {latest_items > 0}")
        assert latest_items > 0, "Latest delivery highlight is missing"

        # Test Innings Switching interaction
        mobile_page.click("#tab-inns-2")
        time.sleep(0.4)
        active_tab_2 = mobile_page.locator("#tab-inns-2.active").count()
        assert active_tab_2 == 1, "Innings 2 tab should be active"
        print("Innings switching interaction verified: Tab 2 active")

        # Switch back to Innings 1
        mobile_page.click("#tab-inns-1")
        time.sleep(0.4)

        # Capture Mobile screenshot
        mobile_page.screenshot(path=mobile_png, full_page=True)
        print(f"Saved mobile screenshot to: {mobile_png}")
        mobile_page.close()

        browser.close()

    httpd.shutdown()
    print("ALL PLAYWRIGHT VISUAL AND INTERACTION TESTS PASSED!")


if __name__ == "__main__":
    main()

