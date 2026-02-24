# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Melbourne PTV Transit Plugin for TRMNL** - a Python/FastAPI backend that fetches Melbourne train departure data from the PTV Timetable API and pushes it to a TRMNL e-ink display via webhooks. The display mimics Victoria's Passenger Information Displays (PIDs).

## Technology Stack

- **Backend**: Python 3.11+ with FastAPI
- **HTTP Client**: httpx (async)
- **Scheduler**: APScheduler for periodic data pushes
- **Templates**: Jinja2 for markup generation
- **Deployment**: Docker, Railway.app, or Fly.io

## Project Structure (Target)

```
ptv-trmnl/
├── app/
│   ├── main.py              # FastAPI app with scheduler
│   ├── ptv_client.py        # PTV API wrapper with HMAC-SHA1 signing
│   ├── trmnl_client.py      # TRMNL webhook client
│   ├── config.py            # Pydantic settings
│   └── templates/           # Jinja2 templates for TRMNL layouts
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run development server
uvicorn app.main:app --reload

# Build Docker image
docker build -t ptv-trmnl .

# Run with Docker Compose
docker-compose up
```

## Environment Variables

```
PTV_DEV_ID=<developer_id>
PTV_API_KEY=<api_key_guid>
TRMNL_WEBHOOK_URL=https://usetrmnl.com/api/custom_plugins/<uuid>
DEFAULT_STOP_ID=19843
STATION_NAME=Melbourne Central
PLATFORM_NUMBERS=1,2  # Optional: comma-separated platform filter
REFRESH_MINUTES=5
```

## Key Architecture Concepts

### PTV API Authentication
Every PTV API request requires HMAC-SHA1 signature calculation:
- Signature = HMAC-SHA1(request_path_with_devid, api_key)
- Signature is case-sensitive and appended as `&signature=` parameter
- Base URL: `https://timetableapi.ptv.vic.gov.au`

### TRMNL Integration
- **Private Plugin**: Push data via webhooks (12 calls/hour limit, 2KB data limit)
- **Public Plugin**: TRMNL pulls markup from your server, requires OAuth
- Webhook payload uses `merge_variables` and `merge_strategy` fields

### Display Constraints
- Resolution: 800×480 pixels (TRMNL OG)
- Colors: Black, white, and 2 grays (2-bit grayscale)
- Four layout variants required for public plugins: full, half_vertical, half_horizontal, quadrant

### Design System (full.md)
- **Color palette**: Grays only (`#555` borders, `#999` express stops, `#f2f2f2` stops background)
- **Countdown**: Shows scheduled departure time (e.g., "9:28 am") not minutes - better for stale data
- **Stopping pattern**: 4-column layout with `.current` (highlighted) and `.express` (grayed) stops
- **Upcoming trains**: Table with columns: Time, Destination, Type, Platform, Departs
- **Title bar**: Fixed bottom bar with logo, "Transit Victoria" title, and update timestamp
- **Font**: Inter family

### Refresh Rate Strategy
- 15+ min refresh: Show scheduled times only, no countdowns
- 5 min refresh: Show countdowns for trains 10+ minutes away
- Trains work better than trams due to longer intervals

## Common Stop IDs

| Station | Stop ID |
|---------|---------|
| Flinders Street | 1071 |
| Melbourne Central | 19843 |
| Southern Cross | 22180 |
| Flagstaff | 19842 |
| Parliament | 19841 |
| Richmond | 1162 |

## Key PTV API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `/v3/departures/route_type/0/stop/{stop_id}` | Train departures |
| `/v3/search/{term}` | Find stops by name |
| `/v3/routes` | List all routes |

Route types: 0=Train, 1=Tram, 2=Bus, 3=V/Line, 4=Night Bus
