"""
Fetch all season options from the EYBL Pointstreak dropdown.
Run: py -3.12 debug_seasons.py
"""
import asyncio
from playwright.async_api import async_playwright

URL = "http://nikeeyb.hoopstats.pointstreak.com/teamlist.html?leagueid=1366&seasonid=544"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(URL, wait_until="domcontentloaded", timeout=45000)

        # Dump raw HTML of every select element on the page
        selects = await page.eval_on_selector_all(
            "select",
            "els => els.map(s => s.outerHTML)"
        )
        await browser.close()

    print(f"Found {len(selects)} select element(s):\n")
    for i, html in enumerate(selects):
        print(f"=== Select {i} ===")
        print(html[:2000])
        print()

asyncio.run(main())
