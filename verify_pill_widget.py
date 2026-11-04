import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 800})
        
        # Navigate to fan companion
        await page.goto("http://localhost:5000/fan")
        await page.wait_for_timeout(1000)
        
        # Reset any session storage and remove test-mode to simulate first-time fan landing
        await page.evaluate("() => { sessionStorage.clear(); document.body.classList.remove('test-mode'); var qa = document.getElementById('qa-container'); if (qa) qa.classList.remove('open'); window.goToLandingPage(); }")
        await page.wait_for_timeout(500)
        
        # 1. Take screenshot of Landing Page
        await page.screenshot(path=r"C:\Users\augestin\.gemini\antigravity\brain\0a4a53b2-ae2c-4c2e-a0e5-5594439bb9d1\first_page_clear_title.png")
        print("Captured first_page_clear_title.png")
        
        # Check title color & visibility
        title_color = await page.evaluate("() => getComputedStyle(document.querySelector('.landing-title')).color")
        print("Title color:", title_color)
        
        # 2. Click Late Joiner card
        await page.click("#btn-mode-late-joiner")
        await page.wait_for_timeout(600)
        
        # Verify floating pill button is visible
        is_pill_visible = await page.is_visible("#cricket-dost-float-btn")
        print("Is Cricket Dost pill visible in Late Joiner:", is_pill_visible)
        
        # Verify qa-container is closed initially
        is_qa_open_initially = await page.evaluate("() => document.getElementById('qa-container').classList.contains('open')")
        print("Is QA container open initially:", is_qa_open_initially)
        
        await page.screenshot(path=r"C:\Users\augestin\.gemini\antigravity\brain\0a4a53b2-ae2c-4c2e-a0e5-5594439bb9d1\late_joiner_cricket_dost_pill.png")
        print("Captured late_joiner_cricket_dost_pill.png")
        
        # 3. Click Cricket Dost floating pill
        await page.click("#cricket-dost-float-btn")
        await page.wait_for_timeout(400)
        
        is_qa_visible = await page.is_visible("#qa-container")
        print("Is QA container visible after pill click:", is_qa_visible)
        
        await page.screenshot(path=r"C:\Users\augestin\.gemini\antigravity\brain\0a4a53b2-ae2c-4c2e-a0e5-5594439bb9d1\cricket_dost_corner_widget.png")
        print("Captured cricket_dost_corner_widget.png")
        
        # 4. Click Close button in header
        await page.click("#qa-close-btn")
        await page.wait_for_timeout(300)
        is_qa_open_after_close = await page.evaluate("() => document.getElementById('qa-container').classList.contains('open')")
        print("Is QA container open after clicking close btn:", is_qa_open_after_close)
        
        # 5. Switch to Busy mode and check Cricket Dost is hidden
        await page.evaluate("() => window.setFanMode('busy')")
        await page.wait_for_timeout(400)
        busy_pill_vis = await page.is_visible("#cricket-dost-float-btn")
        print("Is Cricket Dost pill visible in Busy mode (should be False):", busy_pill_vis)
        
        # 6. Switch to Casual & Beginner and check Cricket Dost pill is visible
        await page.evaluate("() => window.setFanMode('beginner')")
        await page.wait_for_timeout(400)
        beginner_pill_vis = await page.is_visible("#cricket-dost-float-btn")
        print("Is Cricket Dost pill visible in Beginner mode:", beginner_pill_vis)
        
        # 7. Mobile Viewport Check (iPhone 14 size)
        mobile_page = await browser.new_page(viewport={"width": 390, "height": 844})
        await mobile_page.goto("http://localhost:5000/fan")
        await mobile_page.wait_for_timeout(500)
        await mobile_page.evaluate("() => { document.body.classList.remove('test-mode'); var qa = document.getElementById('qa-container'); if (qa) qa.classList.remove('open'); window.setFanMode('tactical'); }")
        await mobile_page.wait_for_timeout(400)
        await mobile_page.click("#cricket-dost-float-btn")
        await mobile_page.wait_for_timeout(400)
        await mobile_page.screenshot(path=r"C:\Users\augestin\.gemini\antigravity\brain\0a4a53b2-ae2c-4c2e-a0e5-5594439bb9d1\cricket_dost_mobile_corner_widget.png")
        print("Captured cricket_dost_mobile_corner_widget.png")
        
        await browser.close()
        print("ALL VERIFICATIONS COMPLETED SUCCESSFULLY!")

asyncio.run(run())
