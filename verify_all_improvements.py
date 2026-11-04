import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 840})
        
        # 1. First Page / Landing
        await page.goto("http://localhost:5000/fan")
        await page.wait_for_timeout(800)
        await page.evaluate("() => { sessionStorage.clear(); document.body.classList.remove('test-mode'); var qa = document.getElementById('qa-container'); if (qa) qa.classList.remove('open'); window.goToLandingPage(); }")
        await page.wait_for_timeout(500)
        
        await page.screenshot(path=r"C:\Users\augestin\.gemini\antigravity\brain\0a4a53b2-ae2c-4c2e-a0e5-5594439bb9d1\landing_page_verified.png")
        print("1. Landing page screenshot captured.")
        
        # 2. Check Live Win Probability Bar across ALL modes
        modes = ['late-joiner', 'beginner', 'tactical', 'busy', 'stadium', 'standard']
        for m in modes:
            await page.evaluate(f"() => window.setFanMode('{m}')")
            await page.wait_for_timeout(300)
            is_win_bar_visible = await page.is_visible("#ai-win-bar")
            print(f"Mode '{m}': Win Probability Bar Visible = {is_win_bar_visible}")
            assert is_win_bar_visible, f"#ai-win-bar must be visible in {m} mode"
            
        # 3. Verify Busy / Driving Mode Features
        await page.evaluate("() => window.setFanMode('busy')")
        await page.wait_for_timeout(400)
        
        busy_lang_count = await page.locator(".busy-lang-chip").count()
        print(f"Busy mode language chips count: {busy_lang_count} (expected 10)")
        assert busy_lang_count == 10, "Must have 10 IPL language chips in busy mode"
        
        station_text = await page.inner_text("#busy-radio-station-name")
        print("Busy radio station name:", station_text.encode('ascii', 'ignore').decode())
        
        ticker_text = await page.inner_text("#busy-flash-ticker-text")
        print("Busy Hindi flash ticker:", ticker_text.encode('ascii', 'ignore').decode())
        
        soundwave_vis = await page.is_visible("#busy-soundwave")
        print("Busy soundwave visible:", soundwave_vis)
        
        await page.screenshot(path=r"C:\Users\augestin\.gemini\antigravity\brain\0a4a53b2-ae2c-4c2e-a0e5-5594439bb9d1\busy_driving_hindi_mode.png")
        print("3. Busy mode screenshot captured.")
        
        # 4. Verify Cricket Dost Chatbot Clean UI & Top 10 Languages
        await page.evaluate("() => window.setFanMode('tactical')")
        await page.wait_for_timeout(400)
        
        # Open Cricket Dost
        await page.click("#cricket-dost-float-btn")
        await page.wait_for_timeout(400)
        
        qa_lang_count = await page.locator(".qa-lang-pill").count()
        print(f"Cricket Dost language pills count: {qa_lang_count} (expected 10)")
        assert qa_lang_count == 10, "Must have 10 IPL language pills in Cricket Dost"
        
        # Verify 6 options are hidden for human users
        pov_bar_disp = await page.evaluate("() => getComputedStyle(document.querySelector('.qa-pov-bar')).display")
        chips_disp = await page.evaluate("() => getComputedStyle(document.getElementById('qa-chips-wrapper')).display")
        print(f"User mode: .qa-pov-bar display={pov_bar_disp}, #qa-chips-wrapper display={chips_disp}")
        assert pov_bar_disp == "none", ".qa-pov-bar must be hidden"
        assert chips_disp == "none", "#qa-chips-wrapper must be hidden"
        
        await page.screenshot(path=r"C:\Users\augestin\.gemini\antigravity\brain\0a4a53b2-ae2c-4c2e-a0e5-5594439bb9d1\cricket_dost_clean_multilingual.png")
        print("4. Cricket Dost multilingual screenshot captured.")
        
        # 5. Mobile Viewport Check (390x844)
        await page.set_viewport_size({"width": 390, "height": 844})
        await page.wait_for_timeout(400)
        await page.screenshot(path=r"C:\Users\augestin\.gemini\antigravity\brain\0a4a53b2-ae2c-4c2e-a0e5-5594439bb9d1\cricket_dost_mobile_clean.png")
        print("5. Mobile clean screenshot captured.")
        
        # Switch mobile to busy mode
        await page.evaluate("() => window.setFanMode('busy')")
        await page.wait_for_timeout(400)
        await page.screenshot(path=r"C:\Users\augestin\.gemini\antigravity\brain\0a4a53b2-ae2c-4c2e-a0e5-5594439bb9d1\busy_driving_mobile_hindi.png")
        print("6. Mobile busy Hindi screenshot captured.")
        
        await browser.close()
        print("ALL VERIFICATIONS COMPLETED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(run())
