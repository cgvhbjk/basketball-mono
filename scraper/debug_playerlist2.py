"""
Debug: show the HTML surrounding the first few playerid links.
Run: py -3.12 debug_playerlist2.py
"""
import asyncio
import re
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

URL = "http://nikeeyb.hoopstats.pointstreak.com/playerlist.html?leagueid=1366&seasonid=544&letter=A"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(URL, wait_until="networkidle", timeout=30000)
        html = await page.content()
        await browser.close()

    soup = BeautifulSoup(html, "html.parser")

    # Find first 3 links with playerid and print their parent chain
    links = soup.find_all("a", href=re.compile(r"playerid="))[:3]
    for link in links:
        print("=== PLAYER LINK ===")
        print(f"  href: {link['href']}")
        print(f"  text: {link.get_text(strip=True)!r}")
        parent = link.parent
        for _ in range(4):
            print(f"  parent <{parent.name}> classes={parent.get('class','')}")
            # print first 300 chars of parent's HTML
            print(f"    {str(parent)[:300]}")
            if parent.name in ("body", None):
                break
            parent = parent.parent
        print()

asyncio.run(main())
