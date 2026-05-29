# Writing a circuit adapter

This is the scraper's "add one file, get a new circuit" contract. The men's
pipeline is **boys-only**; do not add girls-specific code paths.

## The contract

Every adapter subclasses `basketball_scraper.circuits.base_circuit.BaseCircuit`
and lives in `basketball_scraper/circuits/<name>.py`. The required surface is:

```python
class MyCircuitScraper(BaseCircuit):
    circuit_name = "MyCircuit"     # matches circuits.name in the DB
    circuit_org  = "MyOrg"         # logo/parent organization
    source_strategy = "json"       # one of: json, html, playwright, hybrid

    async def fetch_teams(self) -> list[Team]: ...
    async def fetch_roster(self, team: Team) -> list[tuple[Player, RosterEntry]]: ...
    async def fetch_stats(self, team: Team) -> list[SeasonStats]: ...
```

Optional (override only when the source has the data):

```python
    async def list_events(self) -> list[Event]: ...
    async def get_event(self, event_source_id: str) -> Event | None: ...
    async def list_games(self, event_source_id: str) -> list[Game]: ...
    async def get_game(self, game_source_id: str) -> Game | None: ...
    async def get_box_score(self, game_source_id: str) -> list[BoxScore]: ...
```

Then register it in two places:

1. `basketball_scraper/main.py` → `REGISTRY` dict
2. `basketball_scraper/config.py` → `CIRCUIT_KEYS` tuple and the `Settings.circuit` Literal

## Source-strategy ladder

When picking the source, prefer in this order. Falling back is fine —
declare `source_strategy = "hybrid"` and tag each layer clearly in your code.

1. **JSON endpoint or GraphQL.** Stable, machine-readable, future-proof. Use
   `await self.fetcher.fetch_json(url)`.
2. **Server-rendered HTML.** Parse with BeautifulSoup. Use
   `await self.fetcher.fetch_html(url)` and keep parsing functions
   pure (input HTML → output models) so they can be unit-tested.
3. **Playwright.** Only when the data is injected client-side and there's no
   JSON endpoint to discover. Bonus: `PlaywrightFetcher` logs every XHR at
   INFO so you can spot the real API and promote it to step 1.

## Discovering hidden JSON

Run the page through `PlaywrightFetcher` once. Each XHR/fetch will be logged
like `[XHR captured] GET https://api.example.com/...`. Pick the one that
matches the data you want, then replicate the request with `fetch_json` in
your adapter.

## Reliability built-in

Both fetchers wrap their calls in `with_retries` (exponential backoff +
jitter) and `DomainRateLimiter` (per-host minimum interval). You don't need
to add your own; just keep your adapter's `await asyncio.sleep(...)` calls
to a minimum since the limiter already covers it.

## Snapshots

Every fetcher call records the raw body to `./snapshots/<adapter>/<YYYY>/...`
keyed by sha256. Disable with `ENABLE_SNAPSHOTS=false` in `.env`. Snapshots
are content-addressed, so re-running an unchanged endpoint is a no-op write.

To replay a parser against a historical snapshot, just read it from disk:

```python
from pathlib import Path
from basketball_scraper.circuits.adidas_3ssb import parse_stats_page

html = Path("snapshots/3SSB/2026/05/01/abc123__stats.html").read_text()
rows = parse_stats_page(html, season=2026, age_division="17U")
```

## Error contract

- `EmptyPageError` — the page loaded but rendered an empty shell. The
  orchestrator will swap to Playwright automatically.
- `BlockedError` — Incapsula / Cloudflare blocked the IP. The orchestrator
  will abort the circuit (these blocks don't resolve by retrying).
- Anything else — the orchestrator catches it per-team and continues with
  the next team. The failing team won't be added to the checkpoint, so the
  next run picks it up.

## Configuration-gated circuits

For circuits whose source IDs aren't safe to hardcode (because the wrong
ID would silently scrape the wrong event), require them via env vars and
raise `RuntimeError` until set. The EYBL and EYCL adapters follow this
pattern — see `circuits/eybl.py` and `circuits/eycl.py`.

## Tests

Add a fixture under `tests/fixtures/` and a parser test under `tests/`. See
`tests/test_parsers_adidas_3ssb.py` for the shape. The parser tests run
without network access — they only feed saved HTML/JSON to your parser
functions.

## What NOT to do

- Don't add girls-specific filters, flags, or fields. The pipeline is boys-only.
- Don't store cross-adapter logic outside the adapter. The orchestrator
  in `main.py` should only see normalized Pydantic models.
- Don't add per-circuit Supabase writes. The orchestrator handles upserts;
  your adapter returns models and that's it.
- Don't depend on regex'd headers ("any table with PPG…") when a stable
  selector or JSON field exists. Pin to the most specific thing the source
  provides; flaky parsers create silent data corruption.
