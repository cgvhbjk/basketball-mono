"""
Probe Pointstreak season IDs for leagueid=1366 to find the current EYBL season.
Tries IDs from 545 upward until it finds ones with team data.
Run: py -3.12 debug_find_season.py
"""
import asyncio
import re
from playwright.async_api import async_playwright

BASE = "http://nikeeyb.hoopstats.pointstreak.com"
LEAGUE_ID = 1366
START = 545
END = 700  # reasonable upper bound


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        hits = []
        for sid in range(START, END + 1):
            url = f"{BASE}/teamlist.html?leagueid={LEAGUE_ID}&seasonid={sid}"
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                html = await page.content()
                # Count teamid= links as a signal that teams are present
                team_count = len(re.findall(r"teamid=\d+", html))
                # Also grab the season label from the select if present
                label = await page.eval_on_selector(
                    "#seasonid option[selected]",
                    "el => el.textContent.trim()",
                ) if team_count > 0 else None
                if team_count > 0:
                    print(f"  seasonid={sid}  teams={team_count}  label={label!r}")
                    hits.append(sid)
                else:
                    print(f"  seasonid={sid}  (no data)")
            except Exception as e:
                print(f"  seasonid={sid}  ERROR: {e}")

        await browser.close()

    print(f"\nFound {len(hits)} season(s) with data: {hits}")

asyncio.run(main())
