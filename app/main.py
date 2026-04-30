import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

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
MELBOURNE_TZ = ZoneInfo("Australia/Melbourne")

# Pending settings from setup page, keyed by access_token.
# Applied when the /install/success webhook arrives.
_pending_settings: dict[str, dict] = {}

# Jinja2 environment for server-side rendering
_template_dir = os.path.join(os.path.dirname(__file__), "templates")
jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(_template_dir),
    autoescape=False,
)


def _clamped_seconds(value: int | None, default: int) -> int:
    if value is None:
        return default
    return max(0, value)


def _parse_instant(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _cache_expires_at(data: dict, fetched_at: datetime) -> datetime:
    """Return the earliest time cached transit data must be considered stale."""
    candidates = [
        fetched_at + timedelta(seconds=_clamped_seconds(settings.public_cache_seconds, 60)),
    ]

    departures = data.get("departures") or []
    if departures:
        first_departure = departures[0]
        departure_at = _parse_instant(
            first_departure.get("estimated_departure_utc")
            or first_departure.get("scheduled_departure_utc")
        )
        if departure_at is not None:
            grace = _clamped_seconds(settings.departure_cache_grace_seconds, 60)
            candidates.append(departure_at + timedelta(seconds=grace))
    else:
        no_departures_ttl = _clamped_seconds(settings.no_departures_cache_seconds, 30)
        candidates.append(fetched_at + timedelta(seconds=no_departures_ttl))

    return min(candidates)


def _should_force_refresh(request: Request, form=None) -> bool:
    truthy = {"1", "true", "yes", "on"}
    keys = ("force_refresh", "refresh", "force")

    for key in keys:
        raw = request.query_params.get(key)
        if raw is not None and str(raw).strip().lower() in truthy:
            return True

    for key in ("x-trmnl-force-refresh", "x-force-refresh"):
        raw = request.headers.get(key)
        if raw is not None and str(raw).strip().lower() in truthy:
            return True

    if form is not None:
        for key in keys:
            raw = form.get(key)
            if raw is not None and str(raw).strip().lower() in truthy:
                return True

    return False


def _build_render_context(data: dict) -> dict:
    """Attach render metadata without persisting it into the PTV cache."""
    now_utc = datetime.now(timezone.utc)
    freshness_seconds = _clamped_seconds(settings.render_freshness_seconds, 60) or 1
    render_slot = int(now_utc.timestamp() // freshness_seconds)
    rendered_at_utc = datetime.fromtimestamp(render_slot * freshness_seconds, tz=timezone.utc)
    context = dict(data)
    context["rendered_at_utc"] = rendered_at_utc.isoformat()
    context["rendered_at"] = rendered_at_utc.astimezone(MELBOURNE_TZ).strftime("%I:%M %p").lstrip("0").lower()
    context["refresh_slot"] = render_slot
    return context


async def fetch_departure_data(
    stop_id: int,
    platform_numbers: list[int] | None = None,
) -> dict:
    """Fetch PTV departures + stopping pattern — shared by push mode and markup endpoint."""
    ptv = PTVClient(settings.ptv_dev_id, settings.ptv_api_key)

    departures = await ptv.get_departures(
        stop_id=stop_id,
        route_type=0,
        max_results=6,
        platform_numbers=platform_numbers,
    )

    stops = []
    if departures:
        try:
            stops = await ptv.get_stopping_pattern(
                run_ref=departures[0]["run_ref"],
                current_stop_id=stop_id,
            )
        except Exception:
            pass  # Degrade gracefully — departures still shown without pattern

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
                "scheduled_departure_utc": d["scheduled_departure_utc"],
                "estimated_departure_utc": d["estimated_departure_utc"],
                "platform": d["platform"],
                "is_express": d["is_express"],
                "train_type": d["train_type"],
            }
            for d in departures
        ],
        "stop_columns": stop_columns,
        "updated_at": datetime.now(timezone.utc).astimezone(MELBOURNE_TZ).strftime("%I:%M %p").lstrip("0").lower(),
    }


def _parse_platforms(raw: str | None) -> list[int] | None:
    if not raw:
        return None
    return [int(p.strip()) for p in raw.split(",") if p.strip()]


async def _get_fresh_data(user: dict, force_refresh: bool = False) -> dict:
    """Return this user's departure data, using the DB cache only while the
    cached payload is still valid for the visible transit state."""
    cache_updated_at = user.get("cache_updated_at")

    if not force_refresh and cache_updated_at:
        last_fetch = _parse_instant(cache_updated_at)
        cached_json = user.get("cached_departures")
        if last_fetch is not None and cached_json:
            try:
                cached_data = json.loads(cached_json)
            except (TypeError, json.JSONDecodeError):
                cached_data = None
            if cached_data is not None:
                now = datetime.now(timezone.utc)
                if now < _cache_expires_at(cached_data, last_fetch):
                    return cached_data

    # Cache miss or expired — fetch a fresh batch from PTV.
    platform_numbers = _parse_platforms(user.get("platform_numbers"))
    data = await fetch_departure_data(stop_id=user["stop_id"], platform_numbers=platform_numbers)
    data["station_name"] = user["station_name"]
    await db.set_cached_departures(user["uuid"], data)
    return data


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
    """Browser redirect from TRMNL with auth code; exchange for token and redirect to setup."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://trmnl.com/oauth/token",
            json={
                "grant_type": "authorization_code",
                "client_id": settings.trmnl_client_id,
                "client_secret": settings.trmnl_client_secret,
                "code": code,
            },
        )
        resp.raise_for_status()
        token_data = resp.json()

    access_token = token_data.get("access_token", "")
    print(f"[install] OAuth token_data keys: {list(token_data.keys())}, token_prefix={access_token[:12]}...")
    return RedirectResponse(
        url=f"/setup?callback_url={quote(installation_callback_url)}&token={access_token}",
        status_code=302,
    )


# ── Setup flow (shown between OAuth and TRMNL callback) ─────────────────────

@app.get("/setup", response_class=HTMLResponse)
async def setup_page(
    callback_url: str = Query(...),
    token: str = Query(""),
):
    """Show setup page so the user can pick a station before completing install."""
    template = jinja_env.get_template("manage.html")
    return template.render(
        mode="setup",
        callback_url=callback_url,
        token=token,
        uuid="",
        station_name="Melbourne Central",
        stop_id=19843,
        platform_numbers="",
        refresh_minutes=5,
        plugin_setting_id=None,
        message=None,
        message_type=None,
    )


@app.post("/setup/save")
async def setup_save(
    callback_url: str = Form(...),
    token: str = Form(""),
    stop_id: int = Form(...),
    station_name: str = Form(...),
    platform_numbers: str = Form(""),
    refresh_minutes: int = Form(5),
):
    """Store pending settings and redirect to TRMNL callback to complete install."""
    print(f"[setup/save] token_prefix={token[:12] if token else '(empty)'}..., stop_id={stop_id}, station={station_name}")
    if token:
        # Guard against unbounded growth
        if len(_pending_settings) > 1000:
            _pending_settings.clear()
        _pending_settings[token] = {
            "stop_id": stop_id,
            "station_name": station_name,
            "platform_numbers": platform_numbers.strip() or None,
            "refresh_minutes": max(1, refresh_minutes),
        }
    return RedirectResponse(url=callback_url, status_code=302)


@app.post("/install/success")
async def install_success(request: Request):
    """Webhook: TRMNL sends user info after successful install.

    Payload is nested under "user" key:
    {"user": {"uuid": "...", "name": "...", "plugin_setting_id": 123, ...}}
    """
    body = await request.json()
    print(f"[install/success] payload: {body}")

    user_data = body.get("user", {})
    uuid = user_data.get("uuid")
    if not uuid:
        return JSONResponse({"error": "Missing uuid"}, status_code=400)

    access_token = request.headers.get("authorization", "").removeprefix("Bearer ")
    print(f"[install/success] uuid={uuid}, token_prefix={access_token[:12]}...")

    existing = await db.get_user(uuid)
    if existing:
        # User may have been auto-created by /manage — update with real data
        await db.update_user_token(
            uuid=uuid,
            access_token=access_token,
            plugin_setting_id=user_data.get("plugin_setting_id"),
        )
    else:
        await db.create_user(
            uuid=uuid,
            access_token=access_token,
            plugin_setting_id=user_data.get("plugin_setting_id"),
            user_name=user_data.get("name"),
            user_email=user_data.get("email"),
            time_zone=user_data.get("time_zone_iana") or user_data.get("time_zone"),
        )

    # Apply any pending settings from the setup page
    pending = _pending_settings.pop(access_token, None)
    print(f"[install/success] pending settings found: {pending is not None}")
    if pending:
        await db.update_user_settings(
            uuid=uuid,
            stop_id=pending["stop_id"],
            station_name=pending["station_name"],
            platform_numbers=pending["platform_numbers"],
            refresh_minutes=pending["refresh_minutes"],
        )

    return {"status": "ok"}


# ── Uninstall ────────────────────────────────────────────────────────────────

@app.post("/uninstall")
async def uninstall(request: Request):
    """Webhook: TRMNL notifies us a user uninstalled.

    Payload: {"user_uuid": "uuid-of-the-user"}
    """
    body = await request.json()
    uuid = body.get("user_uuid")
    if uuid:
        await db.delete_user(uuid)
    return {"status": "ok"}


# ── Markup endpoint (public plugin) ─────────────────────────────────────────

@app.post("/trmnl/markup")
async def trmnl_markup(request: Request):
    """TRMNL requests markup for a user's display.

    TRMNL sends application/x-www-form-urlencoded with user_uuid field.
    Response must use keys: markup, markup_half_horizontal, markup_half_vertical, markup_quadrant.
    """
    # TRMNL sends form-encoded data, not JSON
    form = await request.form()
    uuid = form.get("user_uuid")

    if not uuid:
        # Fallback: try JSON body in case of testing
        try:
            body = await request.json()
            uuid = body.get("user_uuid") or body.get("uuid")
        except Exception:
            pass

    if not uuid:
        return JSONResponse({"error": "Missing user_uuid"}, status_code=400)

    user = await db.get_user(uuid)
    if not user:
        return JSONResponse({"error": "User not found"}, status_code=404)

    data = _build_render_context(
        await _get_fresh_data(user, force_refresh=_should_force_refresh(request, form))
    )

    # TRMNL expects these exact keys
    layout_map = {
        "markup": "full",
        "markup_half_horizontal": "half_horizontal",
        "markup_half_vertical": "half_vertical",
        "markup_quadrant": "quadrant",
    }

    result = {}
    for response_key, template_name in layout_map.items():
        template = jinja_env.get_template(f"{template_name}.html")
        result[response_key] = template.render(**data)

    return JSONResponse(
        result,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


# ── Settings page ────────────────────────────────────────────────────────────

@app.get("/manage", response_class=HTMLResponse)
async def manage_page(uuid: str = Query(...)):
    print(f"[manage] uuid={uuid}")
    user = await db.get_user(uuid)
    if not user:
        # Auto-create user on first manage visit (webhook may not have arrived yet)
        await db.create_user(uuid=uuid, access_token="")
        user = await db.get_user(uuid)

    template = jinja_env.get_template("manage.html")
    return template.render(
        mode="manage",
        callback_url="",
        token="",
        uuid=uuid,
        station_name=user["station_name"],
        stop_id=user["stop_id"],
        platform_numbers=user.get("platform_numbers") or "",
        refresh_minutes=user.get("refresh_minutes") or 5,
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
    refresh_minutes: int = Form(5),
):
    print(f"[manage/save] uuid={uuid}, stop_id={stop_id}, station={station_name}")
    user = await db.get_user(uuid)
    if not user:
        return HTMLResponse("<h1>User not found</h1>", status_code=404)

    platforms = platform_numbers.strip() or None
    await db.update_user_settings(
        uuid=uuid,
        stop_id=stop_id,
        station_name=station_name,
        platform_numbers=platforms,
        refresh_minutes=max(1, refresh_minutes),
    )
    await db.flush_cached_departures(uuid)

    user = await db.get_user(uuid)
    template = jinja_env.get_template("manage.html")
    return template.render(
        mode="manage",
        callback_url="",
        token="",
        uuid=uuid,
        station_name=user["station_name"],
        stop_id=user["stop_id"],
        platform_numbers=user.get("platform_numbers") or "",
        refresh_minutes=user.get("refresh_minutes") or 5,
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
