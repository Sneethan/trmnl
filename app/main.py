from contextlib import asynccontextmanager
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from .config import settings
from .ptv_client import PTVClient
from .trmnl_client import TRMNLClient

scheduler = AsyncIOScheduler()


async def push_departures_to_trmnl():
    """Fetch PTV data and push to TRMNL webhook."""
    ptv = PTVClient(settings.ptv_dev_id, settings.ptv_api_key)
    trmnl = TRMNLClient(settings.trmnl_webhook_url)

    # Parse platform numbers from config
    platform_numbers = None
    if settings.platform_numbers:
        platform_numbers = [int(p.strip()) for p in settings.platform_numbers.split(",")]

    departures = await ptv.get_departures(
        stop_id=settings.default_stop_id,
        route_type=0,  # Trains
        max_results=3,
        platform_numbers=platform_numbers,
    )

    stops = []
    if departures:
        stops = await ptv.get_stopping_pattern(
            run_ref=departures[0]["run_ref"],
            current_stop_id=settings.default_stop_id,
        )

    # Split stops into columns for the display (max 4 columns × 4 = 16 stops to stay under 2KB)
    per_col = 6
    max_cols = 4
    stop_columns = [
        [{"name": s["name"], "is_current": s["is_current"], "is_express": s["is_express"]}
         for s in stops[i:i + per_col]]
        for i in range(0, min(len(stops), per_col * max_cols), per_col)
    ]

    await trmnl.push_data({
        "station_name": settings.station_name,
        "stop_columns": stop_columns,
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
        "updated_at": datetime.now().strftime("%I:%M %p").lstrip("0").lower(),
    })

    print(f"Pushed {len(departures)} departures to TRMNL")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Push immediately on startup
    await push_departures_to_trmnl()

    # Schedule periodic updates
    scheduler.add_job(
        push_departures_to_trmnl,
        "interval",
        minutes=settings.refresh_minutes,
        id="ptv_refresh",
    )
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/refresh")
async def manual_refresh():
    """Manually trigger a refresh."""
    await push_departures_to_trmnl()
    return {"status": "refreshed"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
