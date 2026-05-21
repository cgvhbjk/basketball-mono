"""
Probe thecircuithoops.com EYBL pages to understand HTML structure.
Run: py -3.12 debug_circuithoops.py
"""
import asyncio
import re
from playwright.async_api import async_playwright

SUBSEASON = "942853"

PAGES = {
    "standings": f"https://www.thecircuithoops.com/standings/show/8957138?mirror_id=7009352&subseason={SUBSEASON}",
    "roster":    f"https://www.thecircuithoops.com/roster/show/8957149?subseason={SUBSEASON}",
    "stats":     f"https://www.thecircuithoops.com/stats/team_instance/10131657?subseason={SUBSEASON}&tab=team_instance_player_stats&tool=5706191",
}


async def fetch(page, url: str) -> str:
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(2000)
    return await page.content()


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = await ctx.new_page()

        # ── Standings ──────────────────────────────────────────────
        print("=" * 60)
        print("STANDINGS PAGE")
        print("=" * 60)
        html = await fetch(page, PAGES["standings"])
        # Print first 4000 chars and all team/roster links
        print(html[:4000])
        print("\n--- team/roster links ---")
        for m in re.findall(r'href="([^"]*(?:roster|team)[^"]*)"', html):
            print(" ", m)

        # ── Roster ─────────────────────────────────────────────────
        print("\n" + "=" * 60)
        print("ROSTER PAGE (PSA Cardinals)")
        print("=" * 60)
        html = await fetch(page, PAGES["roster"])
        print(html[:4000])
        print("\n--- player links ---")
        for m in re.findall(r'href="([^"]*roster_player[^"]*)"', html):
            print(" ", m)

        # ── Stats ──────────────────────────────────────────────────
        print("\n" + "=" * 60)
        print("STATS PAGE (MOKAN Elite)")
        print("=" * 60)
        html = await fetch(page, PAGES["stats"])
        # Find table headers
        headers = re.findall(r'<th[^>]*>(.*?)</th>', html, re.DOTALL)
        print("Table headers:", [re.sub(r'<[^>]+>', '', h).strip() for h in headers[:30]])
        # Print first 3000 chars around any table
        m = re.search(r'<table', html)
        if m:
            print(html[max(0, m.start()-200):m.start()+3000])
        else:
            print(html[:3000])

        await browser.close()


asyncio.run(main())
