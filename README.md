# basketball-mono

AAU basketball stats scraper + dashboard. Scrapes player/team stats from EYBL, EYCL, Adidas 3SSB, Adidas Gold, UAA, UAA Rise, and PUMA, stores them in Supabase, and displays them in a Next.js dashboard.

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

CIRCUIT=eybl          # eybl | eycl | 3ssb | adidas_gold | uaa | uaa_rise | puma
SEASON=2026
AGE_DIVISION=17U      # 15U | 16U | 17U
USE_PLAYWRIGHT=false
```

Run a single circuit:

```bash
python -m basketball_scraper.main
```

Run all circuits (loops through every circuit × division combination):

```bash
python run_all.py
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

Key tables: `circuits`, `teams`, `players`, `player_season_stats`
