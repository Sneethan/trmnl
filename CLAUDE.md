# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Melbourne PTV Transit Plugin for TRMNL** - a Python/FastAPI backend that fetches Melbourne train departure data from the PTV Timetable API and renders it on TRMNL e-ink displays. The display mimics Victoria's Passenger Information Displays (PIDs). Supports two modes: **push mode** (webhook-based, single user) and **public plugin mode** (OAuth, multi-user with per-user settings).

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run development server
uvicorn app.main:app --reload

# Build and run with Docker
docker build -t ptv-trmnl .
docker-compose up
```

No test suite exists currently.

## Environment Variables

```
PTV_DEV_ID=<developer_id>           # Required
PTV_API_KEY=<api_key_guid>          # Required
TRMNL_WEBHOOK_URL=...               # Set for push mode only
TRMNL_CLIENT_ID=...                 # Set for public plugin mode (OAuth)
TRMNL_CLIENT_SECRET=...             # Set for public plugin mode (OAuth)
DEFAULT_STOP_ID=19843               # Melbourne Central
STATION_NAME=Melbourne Central
PLATFORM_NUMBERS=1,2                # Optional: comma-separated platform filter
REFRESH_MINUTES=5
DATABASE_PATH=./data/trmnl.db       # SQLite location
```

## Architecture

### Two Operating Modes

- **Push mode**: When `TRMNL_WEBHOOK_URL` is set, APScheduler periodically fetches PTV data and pushes rendered markup to the TRMNL webhook. Single-user, uses env vars for config.
- **Public plugin mode**: When `TRMNL_CLIENT_ID`/`SECRET` are set, TRMNL calls `/trmnl/markup` on demand. Multi-user with OAuth install flow, per-user settings stored in SQLite, and departure data caching per user.

### Data Flow

```
PTV API → PTVClient.get_departures() + get_stopping_pattern()
  → fetch_departure_data() builds {departures, stop_columns, station_name, updated_at}
  → Cached in SQLite (public plugin mode)
  → Rendered via Jinja2 templates
  → Pushed to TRMNL webhook or returned as HTML
```

### Key Routes (app/main.py)

| Endpoint | Purpose |
|----------|---------|
| `POST /trmnl/markup` | TRMNL calls this to get rendered HTML for all 4 layout sizes |
| `GET /install` | OAuth code exchange, redirects user back to TRMNL |
| `POST /install/success` | TRMNL webhook: user installed, creates DB record |
| `POST /uninstall` | TRMNL webhook: user removed, deletes DB record |
| `GET /manage` | Per-user settings page (station, platforms, refresh interval) |
| `POST /manage/save` | Save user settings to SQLite |
| `GET /api/stations/search` | Station autocomplete for manage page |
| `POST /refresh` | Manual trigger for push-mode refresh |

### PTV API Authentication

Every PTV API request requires HMAC-SHA1 signing (implemented in `ptv_client.py`):
- Path includes `?devid=` parameter
- Signature = `HMAC-SHA1(path_with_devid, api_key).hexdigest().upper()`
- Appended as `&signature=` to the URL

### Database (app/database.py)

SQLite via aiosqlite. Single `users` table stores per-user: access_token, stop_id, station_name, platform_numbers, refresh_minutes, cached departure JSON, and cache timestamp. Migrations run on startup (adds columns idempotently).

### Templates

Four TRMNL layout variants in `app/templates/`: `full.html` (800x480), `half_horizontal.html` (800x240), `half_vertical.html` (400x480), `quadrant.html` (400x240). Plus `manage.html` for the settings page.

Template variables: `departures` (list of dicts with destination, scheduled_time, platform, train_type, is_express), `stop_columns` (4 columns of 6 stops each with name, is_current, is_express), `station_name`, `updated_at`.

### Display Constraints

- Resolution: 800x480 pixels (TRMNL OG)
- Colors: Black, white, and 2 grays only (2-bit grayscale)
- Font: Inter family
- Shows scheduled departure times (e.g., "9:28 am") rather than countdown minutes — better for stale e-ink data
- Stopping pattern uses `.current` (highlighted) and `.express` (grayed) CSS classes

### Per-User Caching

In public plugin mode, `_get_fresh_data()` checks if cached departure data is within the user's refresh window before fetching from PTV. This avoids redundant API calls when TRMNL requests markup more frequently than the user's configured refresh interval.

## Common Stop IDs

| Station | Stop ID |
|---------|---------|
| Flinders Street | 1071 |
| Melbourne Central | 19843 |
| Southern Cross | 22180 |
| Flagstaff | 19842 |
| Parliament | 19841 |
| Richmond | 1162 |

## PTV API Reference

| Endpoint | Purpose |
|----------|---------|
| `/v3/departures/route_type/0/stop/{stop_id}` | Train departures |
| `/v3/pattern/run/{run_ref}/route_type/0` | Stopping pattern for a run |
| `/v3/stops/route/{route_id}/route_type/0` | All stops on a route |
| `/v3/search/{term}` | Find stops by name |

Route types: 0=Train, 1=Tram, 2=Bus, 3=V/Line, 4=Night Bus
