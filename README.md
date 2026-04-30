# Transport Victoria for TRMNL

A Python/FastAPI backend that fetches Melbourne train departure data from the PTV Timetable API and renders it on [TRMNL](https://usetrmnl.com) e-ink displays. The display mimics Victoria's Passenger Information Displays (PIDs).

![TRMNL Display](https://cdn.getminted.cc/HFVlN7ta8AIt9yF.jpg)

## Features

- Real-time train departures from any Melbourne metro station
- Stopping pattern display with current stop highlighted
- Express stop indication
- Four layout sizes: full, half horizontal, half vertical, quadrant
- Portrait/landscape orientation support
- Two operating modes: push (single user) or public plugin (multi-user OAuth)
- Per-user configurable station and platform filter

---

## Operating Modes

### Push Mode (Single User)

Set `TRMNL_WEBHOOK_URL` in your environment. On startup the app fetches PTV data and pushes rendered markup to the TRMNL webhook. APScheduler repeats this on your configured interval.

Best for: self-hosted, personal use.

### Public Plugin Mode (Multi-User)

Set `TRMNL_CLIENT_ID` and `TRMNL_CLIENT_SECRET`. TRMNL calls `/trmnl/markup` on demand. Users install via OAuth, configure their station via `/manage`, and departure data is cached per-user in SQLite.

Best for: sharing a plugin with other TRMNL users.

---

## Requirements

- Python 3.11+
- PTV Developer API credentials ([register here](https://www.ptv.vic.gov.au/footer/data-and-reporting/datasets/ptv-timetable-api/))
- A TRMNL device and account

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/Sneethan/trmnl.git
cd trmnl
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

Copy `.env.example` to `.env` (or set environment variables directly):

```env
# Required — PTV API credentials
PTV_DEV_ID=your_developer_id
PTV_API_KEY=your_api_key_guid

# Push mode (single user) — set this OR the OAuth vars below
TRMNL_WEBHOOK_URL=https://usetrmnl.com/api/custom_plugins/YOUR_PLUGIN_ID

# Public plugin mode (multi-user OAuth) — set these OR the webhook URL above
TRMNL_CLIENT_ID=your_trmnl_client_id
TRMNL_CLIENT_SECRET=your_trmnl_client_secret

# Station defaults
DEFAULT_STOP_ID=19843          # Melbourne Central
STATION_NAME=Melbourne Central
PLATFORM_NUMBERS=              # Optional: comma-separated e.g. 1,2

# Refresh interval (push mode)
REFRESH_MINUTES=5

# Public plugin cache guardrails
PUBLIC_CACHE_SECONDS=60
NO_DEPARTURES_CACHE_SECONDS=30
DEPARTURE_CACHE_GRACE_SECONDS=60
RENDER_FRESHNESS_SECONDS=60

# SQLite database location
DATABASE_PATH=./data/trmnl.db
```

### 4. Run

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`.

---

## Docker

```bash
# Build and run
docker-compose up --build

# Run in background
docker-compose up -d
```

The SQLite database is persisted in a named Docker volume (`trmnl-data`).

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/refresh` | Manually trigger push-mode refresh |
| `GET` | `/install` | OAuth code exchange (redirect from TRMNL) |
| `GET` | `/setup` | Station setup page (shown during install) |
| `POST` | `/setup/save` | Save setup settings and redirect to TRMNL |
| `POST` | `/install/success` | TRMNL webhook: user installed |
| `POST` | `/uninstall` | TRMNL webhook: user uninstalled |
| `POST` | `/trmnl/markup` | TRMNL requests rendered HTML for all layout sizes |
| `GET` | `/manage` | Per-user settings page |
| `POST` | `/manage/save` | Save user settings |
| `GET` | `/api/stations/search` | Station autocomplete (`?q=flinders`) |

---

## Display Layouts

Four layout variants are rendered for each request:

| Template | Resolution | TRMNL key |
|----------|-----------|-----------|
| `full.html` | 800×480 | `markup` |
| `half_horizontal.html` | 800×240 | `markup_half_horizontal` |
| `half_vertical.html` | 400×480 | `markup_half_vertical` |
| `quadrant.html` | 400×240 | `markup_quadrant` |

`full.html` contains two layout blocks:
- **Landscape** — multi-column stopping pattern + departure table (default)
- **Portrait** — single-column track-line stops + footer departures, shown on `.screen--portrait`

---

## Common Station IDs

| Station | Stop ID |
|---------|---------|
| Flinders Street | 1071 |
| Melbourne Central | 19843 |
| Southern Cross | 22180 |
| Flagstaff | 19842 |
| Parliament | 19841 |
| Richmond | 1162 |

Use `/api/stations/search?q=<name>` to find any other station's stop ID.

---

## Public Plugin Setup (OAuth)

1. Register your plugin in the [TRMNL developer portal](https://usetrmnl.com/developers) and obtain `TRMNL_CLIENT_ID` and `TRMNL_CLIENT_SECRET`.
2. Set the following URLs in your plugin config:
   - **Install URL**: `https://your-domain/install`
   - **Markup URL**: `https://your-domain/trmnl/markup`
   - **Manage URL**: `https://your-domain/manage`
   - **Uninstall URL**: `https://your-domain/uninstall`
3. Deploy the app publicly (e.g. Railway, Fly.io, VPS).
4. Users install the plugin from TRMNL; they are walked through a setup page to choose their station before completing install.

---

## Architecture

```
PTV API → PTVClient.get_departures() + get_stopping_pattern()
  → fetch_departure_data() builds {departures, stop_columns, station_name, updated_at}
  → Cached in SQLite (public plugin mode)
  → Rendered via Jinja2 templates
  → Pushed to TRMNL webhook or returned as HTML
```

### PTV API Authentication

Every PTV API request is HMAC-SHA1 signed:
- Path includes `?devid=` parameter
- Signature = `HMAC-SHA1(path_with_devid, api_key).hexdigest().upper()`
- Appended as `&signature=` to the URL

### Per-User Caching

In public plugin mode, TRMNL controls plugin refresh and device wake cadence. `_get_fresh_data()` therefore uses only a short API coalescing cache before calling PTV again. Cached data expires at the earliest of `PUBLIC_CACHE_SECONDS`, the first visible departure's estimated UTC time plus `DEPARTURE_CACHE_GRACE_SECONDS`, or `NO_DEPARTURES_CACHE_SECONDS` when no departures are returned. The rendered markup also includes a hidden `refresh_slot` so TRMNL's lazy rendering can detect an intentionally refreshed payload even when the same trains remain visible. Configure the actual plugin refresh rate in TRMNL.

---

## TRMNL Device Compatibility

| Selector | Device |
|----------|--------|
| `.screen--lg` | TRMNL V2/X (1024px+) |
| `.screen--md` | TRMNL OG/OG V2 (800px+) |
| `.screen--sm` | Kindle 2024 (600px+) |
| `.screen--4bit` | 16-shade grayscale (V2/X) |
| `.screen--2bit` | 4-shade grayscale (OG V2) |
| `.screen--1bit` | Monochrome (OG) |
| `.screen--portrait` | Portrait orientation |

Font sizes scale up ~25–30% on `.screen--lg`. Rows 4+ (hidden by default) are revealed on larger screens to show more departures.

---

## License

MIT
