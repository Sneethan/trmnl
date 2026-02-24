# Building a Melbourne PTV Transit Plugin for TRMNL

A complete guide to creating your first TRMNL plugin that displays train departures in the style of Victoria's Passenger Information Displays (PIDs).

---

## Table of Contents

1. [Understanding TRMNL Plugin Architecture](#1-understanding-trmnl-plugin-architecture)
2. [Choosing Your Plugin Type](#2-choosing-your-plugin-type)
3. [Getting Your PTV API Credentials](#3-getting-your-ptv-api-credentials)
4. [Setting Up Your Development Environment](#4-setting-up-your-development-environment)
5. [Building the Backend](#5-building-the-backend)
6. [Designing for E-Ink: The PID Layout](#6-designing-for-e-ink-the-pid-layout)
7. [Handling Different Refresh Rates](#7-handling-different-refresh-rates)
8. [Layout Variants for Different Display Sizes](#8-layout-variants-for-different-display-sizes)
9. [Deployment Options](#9-deployment-options)
10. [Going Public](#10-going-public)

---

## 1. Understanding TRMNL Plugin Architecture

TRMNL offers three approaches to custom content:

### Option A: Private Plugin (Recommended to Start)
- **Best for**: Personal use, prototyping, learning
- **How it works**: You push data to TRMNL via webhooks, and design your markup in their browser-based editor
- **Pros**: No server needed for rendering; TRMNL handles image generation
- **Cons**: Limited to 12 webhook calls/hour (30 for TRMNL+); data size limits (2KB, 5KB for TRMNL+)

### Option B: Public Plugin (Marketplace)
- **Best for**: Sharing with the community
- **How it works**: TRMNL pulls markup from your server when screens need rendering
- **Pros**: Full control; can serve many users
- **Cons**: Requires OAuth flow implementation; your server must be publicly accessible

### Option C: Recipe (Forkable Template)
- **Best for**: Sharing configurations that others can customize
- **How it works**: Users fork your template and input their own credentials

**For your PTV project**: Start with a **Private Plugin** to nail the design and data flow. Once it's working, you can graduate to a Public Plugin if you want to share it.

---

## 2. Choosing Your Plugin Type

Given your goals and experience level, here's the recommended path:

### Phase 1: Private Plugin (MVP)
```
[Your Backend Server] --webhook--> [TRMNL API] --renders--> [Your Device]
```

You'll need:
- A simple backend that fetches PTV data
- A scheduled job (cron) to push data to TRMNL
- Markup templates in TRMNL's editor

### Phase 2: Public Plugin (If you want to share)
```
[TRMNL Server] --POST request--> [Your Backend] --returns markup--> [TRMNL Server] --renders--> [User's Device]
```

Additional requirements:
- OAuth flow for user authentication
- Webhook endpoints for install/uninstall
- Markup generation on your server

---

## 3. Getting Your PTV API Credentials

The PTV Timetable API is free but requires registration:

1. **Email**: `APIKeyRequest@ptv.vic.gov.au`
2. **Subject line**: `PTV Timetable API - request for key`
3. **Include**: Your name and a brief description of your project

You'll receive:
- A **Developer ID** (devid)
- An **API Key** (128-bit GUID)

### API Authentication
Every PTV API request requires a signature. The URL must include:
```
?devid=YOUR_DEVID&signature=CALCULATED_SIGNATURE
```

The signature is an HMAC-SHA1 hash of the full request path (including devid) using your API key.

### Key Endpoints You'll Use

| Endpoint                                     | Purpose                      |
| -------------------------------------------- | ---------------------------- |
| `/v3/departures/route_type/0/stop/{stop_id}` | Train departures from a stop |
| `/v3/stops/route/{route_id}/route_type/0`    | Stops on a train line        |
| `/v3/search/{term}`                          | Find stops by name           |
| `/v3/routes`                                 | List all routes              |
| `/v3/directions/route/{route_id}`            | Get direction IDs            |

**Route Types**: 0 = Train, 1 = Tram, 2 = Bus, 3 = V/Line, 4 = Night Bus

---

## 4. Setting Up Your Development Environment

Since you're comfortable with FastAPI, let's use that. Python has excellent PTV API wrappers too.

### Project Structure
```
ptv-trmnl/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app
│   ├── ptv_client.py        # PTV API wrapper
│   ├── trmnl_client.py      # TRMNL webhook client
│   ├── templates/           # Jinja2 templates for markup
│   │   ├── full.html
│   │   ├── half_vertical.html
│   │   ├── half_horizontal.html
│   │   └── quadrant.html
│   └── config.py            # Environment variables
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

### requirements.txt
```
fastapi>=0.100.0
uvicorn>=0.22.0
httpx>=0.24.0
python-dotenv>=1.0.0
apscheduler>=3.10.0
jinja2>=3.1.0
pydantic>=2.0.0
```

### Basic FastAPI Setup (app/main.py)
```python
from fastapi import FastAPI, HTTPException
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from contextlib import asynccontextmanager
from .ptv_client import PTVClient
from .trmnl_client import TRMNLClient
from .config import settings

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the scheduler
    scheduler.add_job(
        push_departures_to_trmnl,
        'interval',
        minutes=5,  # Adjust based on your refresh rate
        id='ptv_refresh'
    )
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)

async def push_departures_to_trmnl():
    """Fetch PTV data and push to TRMNL webhook"""
    ptv = PTVClient(settings.PTV_DEV_ID, settings.PTV_API_KEY)
    trmnl = TRMNLClient(settings.TRMNL_WEBHOOK_URL)
    
    departures = await ptv.get_departures(
        stop_id=settings.DEFAULT_STOP_ID,
        route_type=0,  # Trains
        max_results=6
    )
    
    await trmnl.push_data({
        "departures": departures,
        "station_name": settings.STATION_NAME,
        "updated_at": datetime.now().isoformat()
    })

@app.get("/health")
async def health():
    return {"status": "ok"}
```

### PTV Client (app/ptv_client.py)
```python
import hashlib
import hmac
from datetime import datetime
from urllib.parse import urlencode
import httpx

class PTVClient:
    BASE_URL = "https://timetableapi.ptv.vic.gov.au"
    
    def __init__(self, dev_id: str, api_key: str):
        self.dev_id = dev_id
        self.api_key = api_key
    
    def _sign_url(self, path: str) -> str:
        """Generate signed URL for PTV API"""
        # Add devid to path
        separator = '&' if '?' in path else '?'
        path_with_devid = f"{path}{separator}devid={self.dev_id}"
        
        # Calculate signature
        signature = hmac.new(
            self.api_key.encode('utf-8'),
            path_with_devid.encode('utf-8'),
            hashlib.sha1
        ).hexdigest().upper()
        
        return f"{self.BASE_URL}{path_with_devid}&signature={signature}"
    
    async def get_departures(
        self, 
        stop_id: int, 
        route_type: int = 0,
        max_results: int = 5,
        expand: list = None
    ) -> list:
        """Get upcoming departures from a stop"""
        expand = expand or ["stop", "route", "run", "direction"]
        
        path = f"/v3/departures/route_type/{route_type}/stop/{stop_id}"
        params = {
            "max_results": max_results,
            "expand": expand
        }
        
        # Build query string
        query = urlencode(params, doseq=True)
        full_path = f"{path}?{query}"
        
        url = self._sign_url(full_path)
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
        
        return self._process_departures(data)
    
    def _process_departures(self, data: dict) -> list:
        """Transform PTV response into display-ready format"""
        departures = []
        
        for dep in data.get('departures', []):
            # Get related data from expanded objects
            route = data['routes'].get(str(dep['route_id']), {})
            run = data['runs'].get(str(dep['run_id']), {})
            direction = data['directions'].get(str(dep['direction_id']), {})
            
            # Calculate minutes until departure
            scheduled = datetime.fromisoformat(
                dep['scheduled_departure_utc'].replace('Z', '+00:00')
            )
            estimated = dep.get('estimated_departure_utc')
            if estimated:
                departure_time = datetime.fromisoformat(
                    estimated.replace('Z', '+00:00')
                )
            else:
                departure_time = scheduled
            
            now = datetime.now(departure_time.tzinfo)
            minutes_until = int((departure_time - now).total_seconds() / 60)
            
            departures.append({
                'destination': run.get('destination_name', direction.get('direction_name', 'Unknown')),
                'scheduled_time': scheduled.strftime('%H:%M'),
                'estimated_time': departure_time.strftime('%H:%M'),
                'minutes_until': max(0, minutes_until),
                'platform': dep.get('platform_number', ''),
                'route_name': route.get('route_name', ''),
                'is_express': 'express' in run.get('express_stop_count', 0) > 0,
                'stops': self._get_stopping_pattern(run)
            })
        
        return departures
    
    def _get_stopping_pattern(self, run: dict) -> list:
        """Extract stopping pattern from run data"""
        # This would require an additional API call to /v3/pattern/run/{run_id}
        # For simplicity, returning empty list - implement if needed
        return []
```

### TRMNL Client (app/trmnl_client.py)
```python
import httpx

class TRMNLClient:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
    
    async def push_data(self, data: dict, strategy: str = "replace"):
        """Push data to TRMNL webhook"""
        payload = {
            "merge_variables": data,
            "merge_strategy": strategy
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
        
        return response.json()
```

---

## 5. Building the Backend

### Configuration (app/config.py)
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PTV_DEV_ID: str
    PTV_API_KEY: str
    TRMNL_WEBHOOK_URL: str
    DEFAULT_STOP_ID: int = 19843  # Melbourne Central
    STATION_NAME: str = "Melbourne Central"
    
    class Config:
        env_file = ".env"

settings = Settings()
```

### Environment File (.env)
```bash
PTV_DEV_ID=your_developer_id
PTV_API_KEY=your_api_key_guid
TRMNL_WEBHOOK_URL=https://usetrmnl.com/api/custom_plugins/your_uuid_here
DEFAULT_STOP_ID=19843
STATION_NAME=Melbourne Central
```

### Finding Stop IDs
Use the PTV search endpoint or these common stations:

| Station | Stop ID |
|---------|---------|
| Flinders Street | 1071 |
| Melbourne Central | 19843 |
| Southern Cross | 22180 |
| Flagstaff | 19842 |
| Parliament | 19841 |
| Richmond | 1162 |

---

## 6. Designing for E-Ink: The PID Layout

### TRMNL Display Constraints
- **Resolution**: 800×480 pixels (TRMNL OG)
- **Colors**: Black, white, and 2 grays (2-bit grayscale)
- **No animations**: Static images only

### Layout Dimensions

| Layout | Dimensions | Use Case |
|--------|------------|----------|
| `view--full` | 800×480 | Full departure board |
| `view--half_vertical` | 400×480 | Left/right mashup |
| `view--half_horizontal` | 800×240 | Top/bottom mashup |
| `view--quadrant` | 400×240 | Quarter screen |

### Adapting the PID Design

Looking at your reference image, the key elements are:

1. **Header**: Next departure time, destination, countdown badge
2. **Service type**: Express/Stopping indicator
3. **Stopping pattern**: Multi-column list of stops with visual track line
4. **Upcoming services**: 2-3 additional departures in compact format
5. **Current time**: Clock in corner

### Full Layout Markup Template

Create this in TRMNL's Private Plugin markup editor:

```html
<style>
  .pid-container {
    background: #e8e8e8;
    height: 100%;
    padding: 16px;
    font-family: 'Inter', sans-serif;
  }
  
  .pid-header {
    border-top: 6px solid #009FE3; /* Metro cyan */
    padding-top: 16px;
    margin-bottom: 12px;
  }
  
  .next-train {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
  }
  
  .departure-info {
    display: flex;
    gap: 16px;
    align-items: baseline;
  }
  
  .departure-time {
    font-size: 42px;
    font-weight: 300;
  }
  
  .destination {
    font-size: 54px;
    font-weight: 500;
  }
  
  .countdown {
    background: black;
    color: white;
    padding: 8px 20px;
    font-size: 36px;
    font-weight: 500;
  }
  
  .service-type {
    font-size: 28px;
    color: #333;
    margin-bottom: 16px;
  }
  
  .stopping-pattern {
    display: flex;
    gap: 8px;
    padding: 16px 0;
    border-top: 1px solid #ccc;
    border-bottom: 1px solid #ccc;
    margin-bottom: 16px;
  }
  
  .stop-column {
    flex: 1;
    border-left: 3px solid #009FE3;
    padding-left: 12px;
  }
  
  .stop-name {
    font-size: 18px;
    line-height: 1.5;
    color: #333;
  }
  
  .stop-name.express {
    color: #999;
  }
  
  .stop-name.current {
    background: #009FE3;
    color: white;
    padding: 2px 8px;
    margin-left: -12px;
    padding-left: 12px;
  }
  
  .upcoming-trains {
    border-top: 1px solid #ccc;
    padding-top: 12px;
  }
  
  .upcoming-row {
    display: flex;
    align-items: center;
    padding: 8px 0;
    border-left: 4px solid #009FE3;
    padding-left: 12px;
    margin-bottom: 8px;
  }
  
  .upcoming-time {
    width: 80px;
    font-size: 22px;
    font-weight: 400;
  }
  
  .upcoming-dest {
    flex: 1;
    font-size: 22px;
    font-weight: 500;
  }
  
  .upcoming-type {
    font-size: 18px;
    color: #666;
    width: 100px;
  }
  
  .upcoming-countdown {
    background: black;
    color: white;
    padding: 4px 12px;
    font-size: 18px;
  }
  
  .clock {
    position: absolute;
    bottom: 16px;
    right: 16px;
    font-size: 24px;
    border: 1px solid #ccc;
    padding: 8px 12px;
  }
</style>

<div class="pid-container">
  <div class="pid-header">
    {% if departures.size > 0 %}
      {% assign next = departures[0] %}
      <div class="next-train">
        <div>
          <div class="departure-info">
            <span class="departure-time">{{ next.scheduled_time }}</span>
            <span class="destination">{{ next.destination }}</span>
          </div>
          <div class="service-type">
            {% if next.is_express %}Express{% else %}Stopping All Stations{% endif %}
          </div>
        </div>
        <div class="countdown">{{ next.minutes_until }} min</div>
      </div>
      
      <div class="stopping-pattern">
        {% for stop in next.stops %}
          {% assign col_index = forloop.index0 | modulo: 4 %}
          {% if col_index == 0 %}
            <div class="stop-column">
          {% endif %}
          
          <div class="stop-name {% if stop.is_current %}current{% endif %} {% if stop.is_express %}express{% endif %}">
            {{ stop.name }}
          </div>
          
          {% if col_index == 3 or forloop.last %}
            </div>
          {% endif %}
        {% endfor %}
      </div>
    {% endif %}
  </div>
  
  <div class="upcoming-trains">
    {% for departure in departures offset:1 limit:2 %}
      <div class="upcoming-row">
        <span class="upcoming-time">{{ departure.scheduled_time }}</span>
        <span class="upcoming-dest">{{ departure.destination }}</span>
        <span class="upcoming-type">{% if departure.is_express %}Express{% endif %}</span>
        <span class="upcoming-countdown">{{ departure.minutes_until }} min</span>
      </div>
    {% endfor %}
  </div>
  
  <div class="clock">{{ updated_at | date: "%H:%M:%S" }}</div>
</div>
```

---

## 7. Handling Different Refresh Rates

### The Staleness Problem

| User Type | Refresh Rate | Data Freshness Challenge |
|-----------|--------------|--------------------------|
| Base TRMNL | 15-60 min | Data very stale; show scheduled times only |
| TRMNL+ | 5 min | Usable for trains; risky for trams |
| Self-hosted | 1-5 min | Best experience |

### Strategy: Adaptive Display

Instead of showing "4 min" countdowns (which become lies), adapt your display:

**For 15+ minute refreshes**:
- Show scheduled departure times only (e.g., "7:27am")
- No countdown badges
- Add disclaimer: "Scheduled times - check app for live updates"
- Focus on the stopping pattern and route information

**For 5-minute refreshes**:
- Show countdowns for trains 10+ minutes away
- Use "Due" or "Now" for imminent departures
- Update countdown text to show ranges ("10-15 min")

### Detecting Refresh Rate

TRMNL sends device metadata in the webhook, but for private plugins, you'll need to configure this yourself in your backend.

```python
# In your config
REFRESH_MODE = "long"  # "short" (5 min), "long" (15+ min)

# In your data processing
def format_departure(departure: dict, refresh_mode: str) -> dict:
    if refresh_mode == "long":
        return {
            **departure,
            "display_time": departure["scheduled_time"],
            "show_countdown": False
        }
    else:
        return {
            **departure,
            "display_time": f"{departure['minutes_until']} min" if departure['minutes_until'] > 1 else "Due",
            "show_countdown": True
        }
```

---

## 8. Layout Variants for Different Display Sizes

You'll need to provide markup for all four layouts to publish publicly:

### Full (800×480) - Primary View
Full PID board with stopping pattern, countdown, upcoming trains.

### Half Vertical (400×480) - Sidebar
Simplified list view:
- Station name at top
- 4-5 departures as rows
- Time + destination only
- No stopping pattern

```html
<div class="view view--half_vertical">
  <div class="pid-compact">
    <div class="station-header">{{ station_name }}</div>
    {% for dep in departures limit:5 %}
      <div class="compact-row">
        <span class="time">{{ dep.scheduled_time }}</span>
        <span class="dest">{{ dep.destination | truncate: 15 }}</span>
      </div>
    {% endfor %}
  </div>
</div>
```

### Half Horizontal (800×240) - Banner
Wide but short:
- Next departure prominently
- 2 upcoming as smaller text
- Clock

### Quadrant (400×240) - Minimal
Ultra-compact:
- Next 2-3 departures only
- Time + abbreviated destination
- No extras

---

## 9. Deployment Options

### Option 1: Railway.app (Easiest)
```bash
# Install Railway CLI
npm install -g @railway/cli

# Login and deploy
railway login
railway init
railway up
```

Add environment variables in Railway dashboard.

### Option 2: Fly.io
```bash
# Install flyctl
brew install flyctl

# Deploy
fly launch
fly secrets set PTV_DEV_ID=xxx PTV_API_KEY=xxx TRMNL_WEBHOOK_URL=xxx
fly deploy
```

### Option 3: Self-hosted (Docker)

**Dockerfile**:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**docker-compose.yml**:
```yaml
version: '3.8'
services:
  ptv-trmnl:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    restart: unless-stopped
```

---

## 10. Going Public

Once your private plugin is working well:

### Requirements for Public Marketplace
1. Provide markup for ALL layouts (full, half_vertical, half_horizontal, quadrant)
2. Implement OAuth flow for user installation
3. Handle webhook events (install, uninstall)
4. Store user configurations (which station they want)

### Simplified Public Plugin Flow

For a public plugin, TRMNL will POST to your server requesting markup:

```python
@app.post("/trmnl/markup")
async def generate_markup(
    user_uuid: str = Form(...),
    trmnl: str = Form(...)  # JSON metadata
):
    # Look up user's configured station from your database
    user_config = await get_user_config(user_uuid)
    
    # Fetch departures for their station
    departures = await ptv.get_departures(user_config.stop_id)
    
    # Generate markup for all layouts
    return {
        "markup": render_template("full.html", departures=departures),
        "markup_half_vertical": render_template("half_vertical.html", departures=departures),
        "markup_half_horizontal": render_template("half_horizontal.html", departures=departures),
        "markup_quadrant": render_template("quadrant.html", departures=departures)
    }
```

---

## Quick Start Checklist

1. [x] Email PTV for API credentials
2. [ ] Create TRMNL account and set up a Private Plugin
3. [ ] Copy your webhook URL from the Private Plugin settings
4. [ ] Set up FastAPI project locally
5. [ ] Test PTV API calls work with your credentials
6. [ ] Push sample data to TRMNL webhook
7. [ ] Design your markup in TRMNL's editor
8. [ ] Set up a scheduled job to push updates
9. [ ] Deploy to Railway/Fly/Docker
10. [ ] Enjoy your Melbourne metro PID on e-ink!

---

## Resources

- **TRMNL Framework Docs**: https://usetrmnl.com/framework
- **TRMNL Plugin Demo**: https://usetrmnl.com/plugins/demo
- **PTV API Swagger**: https://timetableapi.ptv.vic.gov.au/swagger/ui/index
- **TransportVic PID Mockups**: https://github.com/TransportVic/vic-pid
- **Python PTV Wrapper**: https://pypi.org/project/ptv-python-wrapper/

---

## Notes on Your Design Goals

### Mimicking the Metro LCD PIDs
The image you shared shows the escalator/concourse LCD style with:
- Gray background (#e8e8e8)
- Cyan Metro branding (#009FE3)
- Multi-column stopping pattern with visual "track line"
- Black countdown badges
- Clean typography

This works beautifully on TRMNL's grayscale display! The cyan will render as a medium gray, which still provides good contrast.

### TRMNL X (Larger Display)
When TRMNL X releases with larger displays, you'll get more pixels to work with. The full PID layout will look even more authentic. Consider:
- Larger font sizes
- More stops visible in pattern
- More upcoming departures

### Why Trains Work Better Than Trams
You're right that trains are ideal for e-ink:
- Longer intervals between services (5-20 min)
- More predictable scheduling
- Longer dwell times allow for "comfortable" staleness

Trams and buses, with 3-5 minute frequencies, would show perpetually stale data on anything slower than real-time displays.
