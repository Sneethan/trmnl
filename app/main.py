import os
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
import jinja2
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import database as db
from .config import settings
from .ptv_client import PTVClient
from .trmnl_client import TRMNLClient

scheduler = AsyncIOScheduler()

# Jinja2 environment for server-side rendering
_template_dir = os.path.join(os.path.dirname(__file__), "templates")
jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(_template_dir),
    autoescape=False,
)


async def fetch_departure_data(
    stop_id: int,
    platform_numbers: list[int] | None = None,
) -> dict:
    """Fetch PTV departures + stopping pattern — shared by push mode and markup endpoint."""
    ptv = PTVClient(settings.ptv_dev_id, settings.ptv_api_key)

    departures = await ptv.get_departures(
        stop_id=stop_id,
        route_type=0,
        max_results=4,
        platform_numbers=platform_numbers,
    )

    stops = []
    if departures:
        stops = await ptv.get_stopping_pattern(
            run_ref=departures[0]["run_ref"],
            current_stop_id=stop_id,
        )

    per_col = 6
    max_cols = 4
    stop_columns = [
        [{"name": s["name"], "is_current": s["is_current"], "is_express": s["is_express"]}
         for s in stops[i:i + per_col]]
        for i in range(0, min(len(stops), per_col * max_cols), per_col)
    ]

    return {
        "departures": [
            {
                "destination": d["destination"],
                "scheduled_time": d["scheduled_time"],
                "estimated_time": d["estimated_time"],
                "platform": d["platform"],
                "is_express": d["is_express"],
                "train_type": d["train_type"],
            }
            for d in departures
        ],
        "stop_columns": stop_columns,
        "updated_at": datetime.now().strftime("%I:%M %p").lstrip("0").lower(),
    }


def _parse_platforms(raw: str | None) -> list[int] | None:
    if not raw:
        return None
    return [int(p.strip()) for p in raw.split(",") if p.strip()]


# ── Push mode (optional, active when TRMNL_WEBHOOK_URL is set) ──────────────

async def push_departures_to_trmnl():
    """Fetch PTV data and push to TRMNL webhook."""
    platform_numbers = _parse_platforms(settings.platform_numbers)

    data = await fetch_departure_data(
        stop_id=settings.default_stop_id,
        platform_numbers=platform_numbers,
    )
    data["station_name"] = settings.station_name

    trmnl = TRMNLClient(settings.trmnl_webhook_url)
    await trmnl.push_data(data)
    print(f"Pushed {len(data['departures'])} departures to TRMNL")


# ── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Always init database
    db.DATABASE_PATH = settings.database_path
    await db.init_db()

    # Only start scheduler if webhook URL is configured (private/push mode)
    if settings.trmnl_webhook_url:
        await push_departures_to_trmnl()
        scheduler.add_job(
            push_departures_to_trmnl,
            "interval",
            minutes=settings.refresh_minutes,
            id="ptv_refresh",
        )
        scheduler.start()

    yield

    if scheduler.running:
        scheduler.shutdown()


app = FastAPI(lifespan=lifespan)


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/refresh")
async def manual_refresh():
    """Manually trigger a push-mode refresh."""
    if not settings.trmnl_webhook_url:
        return JSONResponse({"error": "Push mode not configured"}, status_code=400)
    await push_departures_to_trmnl()
    return {"status": "refreshed"}


# ── OAuth install flow ───────────────────────────────────────────────────────

@app.get("/install")
async def install(
    code: str = Query(...),
    installation_callback_url: str = Query(...),
):
    """Browser redirect from TRMNL with auth code; exchange for token and redirect back."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://usetrmnl.com/oauth/token",
            json={
                "grant_type": "authorization_code",
                "client_id": settings.trmnl_client_id,
                "client_secret": settings.trmnl_client_secret,
                "code": code,
            },
        )
        resp.raise_for_status()

    return RedirectResponse(url=installation_callback_url, status_code=302)


@app.post("/install/success")
async def install_success(request: Request):
    """Webhook: TRMNL sends user info after successful install."""
    body = await request.json()
    print(f"[install/success] payload: {body}")
    uuid = body.get("uuid")
    access_token = body.get("access_token", "")
    if not uuid:
        return JSONResponse({"error": "Missing uuid"}, status_code=400)

    existing = await db.get_user(uuid)
    if not existing:
        await db.create_user(
            uuid=uuid,
            access_token=access_token,
            plugin_setting_id=body.get("plugin_setting_id"),
            user_name=body.get("user_name"),
            user_email=body.get("user_email"),
            time_zone=body.get("time_zone"),
        )

    return {"status": "ok"}


# ── Uninstall ────────────────────────────────────────────────────────────────

@app.post("/uninstall")
async def uninstall(request: Request):
    """Webhook: TRMNL notifies us a user uninstalled."""
    body = await request.json()
    uuid = body.get("uuid")
    if uuid:
        await db.delete_user(uuid)
    return {"status": "ok"}


# ── Markup endpoint (public plugin) ─────────────────────────────────────────

@app.post("/trmnl/markup")
async def trmnl_markup(request: Request):
    """TRMNL requests markup for a user's display."""
    body = await request.json()
    uuid = body.get("uuid")
    if not uuid:
        return JSONResponse({"error": "Missing uuid"}, status_code=400)

    user = await db.get_user(uuid)
    if not user:
        return JSONResponse({"error": "User not found"}, status_code=404)

    stop_id = user["stop_id"]
    station_name = user["station_name"]
    platform_numbers = _parse_platforms(user.get("platform_numbers"))

    data = await fetch_departure_data(stop_id=stop_id, platform_numbers=platform_numbers)
    data["station_name"] = station_name

    markup = {}
    for layout in ("full", "half_horizontal", "half_vertical", "quadrant"):
        template = jinja_env.get_template(f"{layout}.html")
        markup[layout] = template.render(**data)

    return markup


# ── Settings page ────────────────────────────────────────────────────────────

@app.get("/manage", response_class=HTMLResponse)
async def manage_page(uuid: str = Query(...)):
    user = await db.get_user(uuid)
    if not user:
        # Auto-create user on first manage visit (webhook may not have arrived yet)
        await db.create_user(uuid=uuid, access_token="")
        user = await db.get_user(uuid)

    template = jinja_env.get_template("manage.html")
    return template.render(
        uuid=uuid,
        station_name=user["station_name"],
        stop_id=user["stop_id"],
        platform_numbers=user.get("platform_numbers") or "",
        plugin_setting_id=user.get("plugin_setting_id"),
        message=None,
        message_type=None,
    )


@app.post("/manage/save", response_class=HTMLResponse)
async def manage_save(
    uuid: str = Form(...),
    stop_id: int = Form(...),
    station_name: str = Form(...),
    platform_numbers: str = Form(""),
):
    user = await db.get_user(uuid)
    if not user:
        return HTMLResponse("<h1>User not found</h1>", status_code=404)

    platforms = platform_numbers.strip() or None
    await db.update_user_settings(
        uuid=uuid,
        stop_id=stop_id,
        station_name=station_name,
        platform_numbers=platforms,
    )

    user = await db.get_user(uuid)
    template = jinja_env.get_template("manage.html")
    return template.render(
        uuid=uuid,
        station_name=user["station_name"],
        stop_id=user["stop_id"],
        platform_numbers=user.get("platform_numbers") or "",
        plugin_setting_id=user.get("plugin_setting_id"),
        message="Settings saved",
        message_type="success",
    )


# ── Station search API ──────────────────────────────────────────────────────

@app.get("/api/stations/search")
async def search_stations(q: str = Query(..., min_length=2)):
    ptv = PTVClient(settings.ptv_dev_id, settings.ptv_api_key)
    stops = await ptv.search_stops(q, route_type=0)
    return {"stops": stops}


# ── Dev entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
