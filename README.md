# basketball-mono

**Live dashboard:** https://basketball-mono.vercel.app

Boys grassroots basketball stats scraper + dashboard. Scrapes player/team stats from Nike EYBL, Nike EYCL (boys), Adidas 3SSB, Adidas Gold, UAA, and UAA Rise. Hoop Group and Made Hoops adapters are scaffolded but not implemented. Stores everything in Supabase and displays it in a Next.js dashboard.

> **Boys-only.** The men's pipeline does not ingest girls circuits. See `scraper/basketball_scraper/circuits/eycl.py` for why the EYCL adapter is configuration-gated.

## Repo structure

```
basketball-mono/
├── scraper/                  # Python scraper
│   ├── basketball_scraper/
│   │   ├── circuits/         # One file per circuit (cerebro.py, eybl.py, uaa.py, …)
│   │   ├── sources/sports247/# 247Sports extractor (separate CLI)
│   │   ├── cli.py            # `python -m basketball_scraper ingest …`
│   │   ├── main.py           # Orchestrator (teams→rosters→stats→events→box scores)
│   │   ├── models.py         # Pydantic models
│   │   ├── upsert.py         # Supabase write helpers
│   │   └── config.py         # Settings (reads .env)
│   ├── enrich_players.py     # Backfill 247/On3/Passport bio + ranks
│   ├── scripts/             # enrich_prephoops.py + DB maintenance scripts
│   └── requirements.txt
├── basketball-dashboard/     # Next.js 16 dashboard (deployed to Vercel)
│   └── src/
│       ├── app/page.tsx
│       ├── components/players-table/  # sortable/filterable players grid
│       ├── components/watchlist/      # shared (global_watchlist) scouting list
│       └── lib/
├── basketball-db/
│   └── supabase/migrations/  # SQL migrations
└── .github/workflows/
    └── scraper.yml           # Weekly GitHub Actions cron
```

## Prerequisites

- Python 3.12+ (Homebrew recommended on macOS — system Python uses LibreSSL which breaks HTTPS)
- Node 18+
- A [Supabase](https://supabase.com) project with migrations applied (see `basketball-db/supabase/migrations/`)

## Scraper setup

```bash
cd scraper
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Create `scraper/.env`:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-role-key

CIRCUIT=eybl          # eybl | eycl | 3ssb | adidas_gold | uaa | uaa_rise | hoop_group | made_hoops
SEASON=2026
AGE_DIVISION=17U      # 15U | 16U | 17U
USE_PLAYWRIGHT=false
ENABLE_SNAPSHOTS=true # write raw HTML/JSON to ./snapshots/
```

No circuit-specific env vars are required. EYBL/EYCL use the Cerebro tRPC API
(no auth, no IDs); 3SSB and Adidas Gold use the public OGP stats API; UAA/UAA
Rise are server-rendered HTML behind a Playwright-only block. See
[`scraper/docs/sources.md`](scraper/docs/sources.md) for per-circuit endpoint
details.

Run via the CLI:

```bash
python -m basketball_scraper list-circuits
python -m basketball_scraper ingest --circuit eybl --season 2026 --division 17U
python -m basketball_scraper ingest-all --circuits eybl uaa 3ssb
```

The legacy entry point still works:

```bash
python -m basketball_scraper.main   # reads CIRCUIT/SEASON/AGE_DIVISION from .env
```

Backfill bio + recruiting ranks (height, grad year, high school, hometown,
`star_rating`, `national_rank`, `state_rank`). Each source patches null columns
only, so they compose without clobbering each other:

```bash
# On3 (live name search) and Passport (3SSB players with a passport_id)
python enrich_players.py --source on3
python enrich_players.py --source passport

# 247Sports is two-step: extract profiles to a JSONL cache, then patch the DB
python -m basketball_scraper.sources.sports247 extract --ranking-url <url> --limit 200
python enrich_players.py --source 247

# PrepHoops bulk-joins the public player DB
python scripts/enrich_prephoops.py

# Maintenance: drop placeholder/single-char player names left by scrapers
python enrich_players.py --clean-bad
```

See [`scraper/docs/sources.md`](scraper/docs/sources.md) for what each source
provides.

## Dashboard setup

```bash
cd basketball-dashboard
npm install
```

Create `basketball-dashboard/.env.local`:

```env
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
```

```bash
npm run dev   # http://localhost:3000
```

## Deployment

**Dashboard → Vercel** — live at https://basketball-mono.vercel.app

1. Import the repo in Vercel, set root directory to `basketball-dashboard`
2. Add environment variables: `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY`

**Scraper → GitHub Actions**

The workflow at `.github/workflows/scraper.yml` runs every Monday at 6am UTC and scrapes a **single** circuit per run (the scheduled run defaults to `uaa`). The job opts into the **Production** environment, so add these secrets there (Settings → Environments → Production → Environment secrets), not as repo-level Actions secrets — repo-level secrets resolve to `""` and the run silently writes nothing:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`

You can also trigger it manually from the Actions tab with a specific circuit/season/division. Enrichment (`enrich_players.py`, `enrich_prephoops.py`) is not part of this workflow — run it separately.

## Database

Migrations live in `basketball-db/supabase/migrations/`. Apply them in order via the Supabase dashboard SQL editor or `supabase db push`.

Key tables: `circuits`, `teams`, `players`, `team_rosters`, `player_season_stats`, `events`, `games`, `box_scores`, `source_aliases`, `source_snapshots`, `global_watchlist` (+ `global_watchlist_status_options`).

## Adding a new circuit

See [`scraper/docs/adapters.md`](scraper/docs/adapters.md). TL;DR: drop a single file under `scraper/basketball_scraper/circuits/<name>.py` that subclasses `BaseCircuit`, implements `fetch_teams` / `fetch_roster` / `fetch_stats`, and register it in `main.REGISTRY` + `config.CIRCUIT_KEYS`. Prefer JSON endpoints over HTML and run the page through `PlaywrightFetcher` once to log XHR traffic if you're hunting for a hidden API.
