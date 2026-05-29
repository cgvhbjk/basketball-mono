# basketball-mono

Boys grassroots basketball stats scraper + dashboard. Scrapes player/team stats from Nike EYBL, Nike EYCL (boys), Adidas 3SSB, Adidas Gold, UAA, and UAA Rise. Hoop Group and Made Hoops adapters are scaffolded but not implemented. Stores everything in Supabase and displays it in a Next.js dashboard.

> **Boys-only.** The men's pipeline does not ingest girls circuits. See `scraper/basketball_scraper/circuits/eycl.py` for why the EYCL adapter is configuration-gated.

## Repo structure

```
basketball-mono/
├── scraper/                  # Python scraper
│   ├── basketball_scraper/
│   │   ├── circuits/         # One file per circuit (eybl.py, uaa.py, …)
│   │   ├── main.py           # Entry point
│   │   ├── models.py         # Pydantic models
│   │   ├── upsert.py         # Supabase write helpers
│   │   └── config.py         # Settings (reads .env)
│   ├── enrich_players.py     # Backfill 247/On3/Passport rankings
│   └── requirements.txt
├── basketball-dashboard/     # Next.js 16 dashboard (deployed to Vercel)
│   └── src/
│       ├── app/page.tsx
│       ├── components/players-table/
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

Backfill rankings from 247Sports / On3 / Passport:

```bash
python enrich_players.py
```

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

**Dashboard → Vercel**

1. Import the repo in Vercel, set root directory to `basketball-dashboard`
2. Add environment variables: `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY`

**Scraper → GitHub Actions**

The workflow at `.github/workflows/scraper.yml` runs every Monday at 6am UTC. Add these secrets to your GitHub repo (Settings → Secrets → Actions):

- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`

You can also trigger it manually from the Actions tab with a specific circuit/season/division.

## Database

Migrations live in `basketball-db/supabase/migrations/`. Apply them in order via the Supabase dashboard SQL editor or `supabase db push`.

Key tables: `circuits`, `teams`, `players`, `player_season_stats`, `events`, `games`, `box_scores`, `source_snapshots`, `source_aliases`.

## Adding a new circuit

See [`scraper/docs/adapters.md`](scraper/docs/adapters.md). TL;DR: drop a single file under `scraper/basketball_scraper/circuits/<name>.py` that subclasses `BaseCircuit`, implements `fetch_teams` / `fetch_roster` / `fetch_stats`, and register it in `main.REGISTRY` + `config.CIRCUIT_KEYS`. Prefer JSON endpoints over HTML and run the page through `PlaywrightFetcher` once to log XHR traffic if you're hunting for a hidden API.
