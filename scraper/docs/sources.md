# Per-circuit source reference

What's confirmed live, what's left, and exactly where to look. Every URL and
ID below was probed in a dev session — re-verify before scraping if the
season rolls over.

## Adidas 3SSB / Adidas Gold — **JSON API confirmed**

- **Endpoint**: `https://adidas3ssb.com/wp-admin/admin-ajax.php`
- **Method**: GET
- **Plugin**: `adidas-stats-wp` v1.9.8 (custom WP plugin)
- **Auth**: per-session nonce read from the stats page's inline
  `ogpStats = {"ajaxUrl":"…","nonce":"<10-hex>"}` global.
- **Actions**:
  - `ogp_get_player_stats_table`
  - `ogp_get_team_stats_table`
  - `ogp_get_program_stats_table`
- **Filter params**:
  - `season` — **starting** calendar year of the cycle (2025 = "2025-26")
  - `brandNumber` — `10001` for Platinum (3SSB), `10003` for Gold
  - `playLevel` — `Platinum` or `Gold`
  - `division` — `15U|16U|17U`
  - `gender` — `MALE` (boys-only enforced)
  - `minGames`, `sortBy`, `sortOrder`, `page`, `limit`
- **Response**:
  `{success, data: {data: [...], pagination: {total, page, limit, totalPages, hasNext}, filters}}`
- **Verified May 2026** (against `season=2025`, `division=17U`):
  - Platinum / `brand=10001`: 241 players (top tier)
  - Gold     / `brand=10003`: 1,259 players
- **JSON fields used**: `playerNumber`, `firstName`, `lastName`, `teamSlug`,
  `teamName`, `gamesPlayed`, `ppg`, `rpg`, `apg`, `spg`, `bpg`, `tpg`,
  `fgPct`, `threePointPct`, `orpg`, `fpg`, `threePg`, `positions[]`.
- **Status**: implemented as the default path in `circuits/adidas_3ssb.py`;
  Playwright remains as fallback.

## Nike EYBL + Nike EYCL (boys) — **Cerebro Widget tRPC, no config needed**

Both circuits share a single backend that exposes far richer data than the
legacy Pointstreak stats pages: per-game box scores, advanced metrics
(eFG%, TS%, USG%, PPP, AST/TOV, per-40 normalizations), event splits, and
the full calendar.

- **Base**: `https://cerebro-widget.vercel.app/api/trpc/`
- **Transport**: tRPC batched-GET with URL-encoded JSON in `input=`
- **Umbrella id**: `overallId=260104` (env override: `CEREBRO_OVERALL_ID`)
- **Six boys leagues exposed** (`LeaguesList` → name → UUID):
  - `EYBL 15U` / `EYBL 16U` / `EYBL 17U`
  - `EYCL 15U` / `EYCL 16U` / `EYCL 17U`
- **Key procedures**:
  - `RouterCerebroLeagues.LeaguesList` → list all leagues under the umbrella
  - `RouterCerebroTeams.TeamsList` → all teams (filter client-side by `team.league_id`)
  - `RouterCerebroPlayers.PlayersList` → rosters + aggregate stats (paginated)
  - `RouterCerebroPlayer.PlayerXEventsList` → per-session splits
  - `RouterCerebroPlayer.PlayerXGamesList` → per-game box scores
  - `RouterCerebroEvents.EventsList` → calendar (filter `gender != "F"` for boys)
  - `RouterCerebroGames.GamesList` → games for an event + scores + Google
    Drive box-score PDF link
- **Boys filter**: Cerebro hosts girls / NCAA / EuroLeague too. The adapter
  always filters `event.gender != "F"` and `league.name LIKE "EYBL|EYCL …"`.
- **Verified May 2026**:
  - EYBL 17U → 32 teams, sample team Durant has 9 players
  - EYCL 17U → 42 teams, sample Soldiers Camo has 17 players,
    Isaiah Clendinen GP=4 PPG=17.75 FG%=43.9%
  - EventsList → 6 boys EYBL 17U sessions, 2 EYCL 17U sessions; 25 games
    inside Session II (Memphis)
- **Status**: implemented as `circuits/cerebro.py`. `EYBLScraper` and
  `EYCLScraper` are thin subclasses that just set `_LEAGUE_NAME_PREFIX`.
  No env vars required.

### Legacy Pointstreak source (still useful for cross-checks)

- Host: `http://nikeeyb.wtthoops.pointstreak.com` (the older
  `hoopstats.pointstreak.com` host serves stale 2020-era data — don't use).
- leagueid=1366; current EYBL session = seasonid=544.
- Not used by the live pipeline anymore; kept here as a verification
  source if Cerebro ever changes shape.

## UAA / UAA Rise — **bot block confirmed; Playwright required**

- `underarmournext.com/basketball/boys-uaa/` returns HTTP 302 →
  `https://underarmournext.com/blocked/` for plain curl (UA detection).
- **Workaround**: load with `PlaywrightFetcher` — works today. The
  existing UAA adapter already auto-switches to Playwright on
  `EmptyPageError`, so no code change required.
- **No JSON API discovered yet.** The team pages are server-rendered
  HTML (matches the current parser); the data is in `<table>` elements
  with `stid=…` / `spid=…` query params.
- **Follow-up if you want JSON**: load any UAA team page through
  Playwright once with INFO logging — `PlaywrightFetcher` already logs
  every XHR/fetch with `[XHR captured]`. Promote any tidy endpoint to
  `fetch_json` in `circuits/uaa.py`.

## Hoop Group — **no embedded stats; Squarespace marketing site**

- `hoopgroup.com` returns a 301 to a Squarespace marketing host; no API,
  no stats widget, only an Elfsight Instagram embed.
- **Follow-up**: results from Hoop Group events are syndicated through
  `thecircuithoops.com` (Synergy / ScoreBreak feed). Inspect that site
  in DevTools instead of `hoopgroup.com`.

## Made Hoops — **SportNgin platform; needs browser headers**

- `madehoops.com` returns HTTP 403 to plain curl (Cloudflare-style block).
- Underlying platform: `madehoops.sportngin.com` (SportsEngine / SportNgin).
- **How to find the API**:
  - SportsEngine API demo lives at `https://apidemo.sportngin.com/`.
  - GitHub: <https://github.com/sportngin> hosts SportsEngine's OSS clients.
  - Most SportNgin tournaments expose data via the
    `https://api.sportngin.com/` (or `https://api.ngin.com/`) host —
    paths look like `/teams/{id}/roster`, `/games?event_id=X`, etc.
  - Easiest path: load any Made Hoops standings page through
    `PlaywrightFetcher` and inspect captured XHRs in the log.
- **Status**: adapter is scaffolded; raises `NotImplementedError`.

## the-passport.com — **profiles only, no stats JSON**

- Public marketing root; no public stats API surface discoverable.
- Used downstream by 3SSB (`teamSlug` / `playerNumber` map to passport
  player profile pages). Profile pages don't expose stats JSON, but they
  *do* carry bio (height / position / high school / hometown), so Passport
  is wired as an **enricher** (see below), not a stats circuit.

## Enrichment sources (bio + recruiting ranks, not stats circuits)

These don't ingest games/stats — they backfill null player fields
(height, grad_year, high_school, hometown) and recruiting ranks
(`star_rating`, `national_rank`, `state_rank`) after the circuits run. All
match on `lower("first last")` and patch null columns only, so a value set by
one enricher is never clobbered by another. Driven by `enrich_players.py`
(`--source 247|on3|passport`) plus `scripts/enrich_prephoops.py`.

- **247Sports** — two-step. First `extract` writes player profiles to a JSONL
  cache (robots-gated, on-disk cache, rate-limited):

  ```bash
  python -m basketball_scraper.sources.sports247 extract \
      --ranking-url <247-ranking-list-url> --limit 200
  ```

  Then patch the DB from the newest extract: `python enrich_players.py
  --source 247`. The `parse` subcommand reads a saved HTML file offline when a
  URL is robots-disallowed. Code lives under `sources/sports247/`.
- **On3** — live name search; fills bio + industry ranks. Checkpointed +
  rate-limited. `python enrich_players.py --source on3`.
- **PrepHoops** — bulk-paginates the public `prephoops.com/wp-json/wp/v2/players`
  database (~176k profiles, no paywall/bot wall), builds a local name index,
  and joins on it. NULL-only patches, grad-year disambiguation for same-name
  collisions. `python scripts/enrich_prephoops.py [--dry-run] [--max-pages N]`.
- **Passport** — fetches `the-passport.com` profiles for 3SSB players that have
  a `passport_id`. `python enrich_players.py --source passport`.

`enrich_players.py --clean-bad` is a separate maintenance pass that deletes
players with placeholder/single-char names (scraper artifacts).

---

### Quick-test commands

```bash
# Activate the venv first (`python` then works without the python3 macOS quirk).
source .venv/bin/activate

# Live EYBL via Cerebro
python -c "
import asyncio
from basketball_scraper.httpx_fetcher import HttpxFetcher
from basketball_scraper.circuits.eybl import EYBLScraper
class Fake: pass
async def main():
    f = HttpxFetcher()
    s = EYBLScraper(f, Fake(), season=2026, age_division='17U')
    print(len(await s.fetch_teams()), 'EYBL 17U teams')
    await f.close()
asyncio.run(main())"

# Live EYCL via Cerebro — no env vars required
python -c "
import asyncio
from basketball_scraper.httpx_fetcher import HttpxFetcher
from basketball_scraper.circuits.eycl import EYCLScraper
class Fake: pass
async def main():
    f = HttpxFetcher()
    s = EYCLScraper(f, Fake(), season=2026, age_division='17U')
    print(len(await s.fetch_teams()), 'EYCL 17U teams')
    await f.close()
asyncio.run(main())"

# Live Adidas 3SSB JSON API
python -c "
import asyncio
from basketball_scraper.httpx_fetcher import HttpxFetcher
from basketball_scraper.circuits.adidas_3ssb import Adidas3SSBScraper
class Fake: pass
async def main():
    f = HttpxFetcher()
    s = Adidas3SSBScraper(f, Fake(), season=2026, age_division='17U')
    nonce = await s._read_nonce()
    page1 = await s._fetch_json_page(nonce=nonce, brand_number=10001, play_level='Platinum', page=1)
    print('total Platinum players:', page1['pagination']['total'])
    await f.close()
asyncio.run(main())"
```
