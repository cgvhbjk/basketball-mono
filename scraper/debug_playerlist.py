"""
One-shot debug: fetch letter A player list via Playwright and dump the HTML.
Run from the scraper/ directory:
    py -3.12 debug_playerlist.py
"""
import asyncio
from playwright.async_api import async_playwright

URL = "http://nikeeyb.hoopstats.pointstreak.com/playerlist.html?leagueid=1366&seasonid=544&letter=A"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print(f"Fetching {URL} ...")
        await page.goto(URL, wait_until="networkidle", timeout=30000)
        html = await page.content()
        await browser.close()

    print(f"\n--- HTML length: {len(html)} chars ---\n")
    print(html[:5000])
    print("\n--- (truncated) ---")

    # Also look for any links with playerid or teamid
    import re
    player_links = re.findall(r'playerid=(\d+)', html)
    team_links   = re.findall(r'teamid=(\d+)',   html)
    print(f"\nplayerid= occurrences: {len(player_links)} — samples: {player_links[:5]}")
    print(f"teamid=   occurrences: {len(team_links)}   — samples: {team_links[:5]}")

asyncio.run(main())
