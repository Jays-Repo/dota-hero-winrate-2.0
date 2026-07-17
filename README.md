# Dota Hero Winrate

A portfolio app that analyzes a Dota 2 player's performance on a chosen hero — win rate, most-built items, and best/worst enemy matchups — powered by the [OpenDota API](https://docs.opendota.com/).

The interesting part isn't the stats themselves; it's the **caching and resilience layer** that makes an expensive, rate-limited public API feel fast and dependable.

## Stack

- **Frontend:** TypeScript, React, Vite
- **Backend:** Python, FastAPI (async), httpx
- **Storage:** SQLite (via `aiosqlite`) as a local cache
- **Data source:** [OpenDota](https://api.opendota.com/api)

## What it does

1. Enter a Dota account ID (Steam32 or Steam64 — the backend normalizes it).
2. Pick a hero.
3. Choose what to view (one panel at a time):
   - **Win rate** — overall record plus a Radiant/Dire breakdown.
   - **Item information** — most-built core items with per-item win rates.
   - **vs Hero information** — best and worst enemy heroes you've faced.

## Why it's built this way

Win rate uses OpenDota's pre-aggregated endpoints, so it's fast and cheap. But **items and matchups require per-match detail** (`GET /matches/{id}`), which is one request per game — hundreds of calls for a well-played hero, and OpenDota's free tier allows only ~60/min and 2,000/day.

To handle that, the backend:

- **Caches every parsed match in SQLite**, so each match's detail is fetched **once, ever**. Items and matchups are then computed with local SQL aggregation.
- **Syncs incrementally** — it diffs OpenDota's match list against what's already stored and only fetches new matches. Analysis is windowed to the most recent `RECENT_MATCH_LIMIT` (25) games to keep it cheap.
- **Throttles outbound requests** with a shared token bucket so a large sync can't starve the fast endpoints into rate-limit errors.
- **Degrades gracefully** — retries transient `429`/`5xx`/network errors with backoff; falls back to cached data (hero list, item constants, player profile, and match stats) when OpenDota is rate-limited or down.

## Project layout

```text
backend/
  main.py            FastAPI app, routes, response models, in-memory cache
  opendota.py        HTTP client: rate limiter, retries, account ID normalization
  db.py              SQLite schema + read/write + aggregation queries
  match_analysis.py  Incremental match sync (list diff + detail fetch)
  items.py           Core-item filtering and stat aggregation
  matchups.py        Enemy-hero matchup aggregation
frontend/
  src/App.tsx        Single-page UI (win rate / items / matchups panels)
```

## Run locally

### 1. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

A `dota_stats.db` file is created automatically on first run (gitignored). Delete it anytime to reset the cache.

### 2. Frontend

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

## API endpoints

| Method & path | Description |
| --- | --- |
| `GET /api/heroes` | Hero list for the dropdown |
| `GET /api/players/{account_id}` | Player profile (name, avatar) — cached |
| `GET /api/winrate?account_id=&hero_id=` | Overall + Radiant/Dire win rate |
| `GET /api/top-items?account_id=&hero_id=` | Most-built core items (recent games) |
| `GET /api/matchups?account_id=&hero_id=` | Best/worst enemy heroes (recent games) |
| `GET /api/status` | Cache summary + remaining OpenDota quota |
| `GET /api/health` | Liveness check |

## Configuration

Set via environment variables (all optional):

- `OPENDOTA_API_KEY` — use an OpenDota API key; raises the request rate limit.
- `OPENDOTA_RATE_LIMIT` — override requests/minute (defaults to a safe free-tier value).

## Finding your Dota account ID

OpenDota uses the **Steam32 account ID**, not your Steam display name.

- Open your [OpenDota profile](https://www.opendota.com/) and copy the number from the URL, **or**
- Paste your **Steam64 ID** — the backend converts it automatically.

```text
https://www.opendota.com/players/86745912
                                 ^^^^^^^^  account ID
```

No API key is required for basic usage.

## Notes & limitations

- Rate limits are per **IP**; a very large first sync can exhaust the daily quota (an API key or waiting for the UTC reset clears it).
- Item/matchup stats reflect the most recent 25 games per hero by default (`RECENT_MATCH_LIMIT` in `backend/items.py`).

## Possible next steps

- Background sync with progress reporting (instead of syncing inside the request)
- "Most-faced enemies" view alongside best/worst win rate
- Swap SQLite for Postgres and deploy (backend on a host, frontend on static hosting)
