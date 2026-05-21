"""
Debug: print the headers and first data row from the stats table on a player page.
Run: py -3.12 debug_player_stats.py
"""
import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

URL = "http://nikeeyb.hoopstats.pointstreak.com/player.html?playerid=83381&seasonid=544"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(URL, wait_until="domcontentloaded", timeout=45000)
        html = await page.content()
        await browser.close()

    soup = BeautifulSoup(html, "html.parser")

    for i, table in enumerate(soup.find_all("table")):
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        if not headers:
            continue
        print(f"\n=== Table {i} headers ===")
        print(headers)
        # Print first data row
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if cells:
                print("First data row:", [c.get_text(strip=True) for c in cells])
                break

asyncio.run(main())
