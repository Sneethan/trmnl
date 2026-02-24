"""
Test suite for TRMNL webhook integration.
Run with: python test_push.py

Tests:
  1. Connectivity   - push minimal payload from config (no PTV needed)
  2. Fetch stored   - GET current merge_variables back from TRMNL
  3. Live push      - fetch real PTV data and push end-to-end
"""

import asyncio
import os
from datetime import datetime

import httpx
from dotenv import load_dotenv

load_dotenv()

from app.ptv_client import PTVClient
from app.trmnl_client import TRMNLClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sep(title: str) -> None:
    print(f"\n{'─' * 52}")
    print(f"  {title}")
    print(f"{'─' * 52}")


def ok(msg: str) -> None:
    print(f"  PASS  {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL  {msg}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_connectivity(trmnl: TRMNLClient, station_name: str) -> bool:
    """Push a minimal well-formed payload to verify the endpoint is reachable."""
    sep("Test 1: Webhook connectivity")
    payload = {
        "station_name": station_name,
        "departures": [],
        "stops": [],
        "updated_at": datetime.now().strftime("%I:%M %p").lstrip("0").lower(),
    }
    print(f"  Station: {station_name}")
    print(f"  Departures: []  (connectivity check only)")
    try:
        result = await trmnl.push_data(payload)
        ok(f"Endpoint reachable. Response: {result}")
        return True
    except httpx.HTTPStatusError as e:
        fail(f"HTTP {e.response.status_code}: {e.response.text}")
        return False
    except Exception as e:
        fail(str(e))
        return False


async def test_fetch_stored(webhook_url: str) -> bool:
    """GET the currently stored merge_variables back from TRMNL."""
    sep("Test 2: Fetch stored variables (GET)")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(webhook_url)
            response.raise_for_status()
        data = response.json()
        keys = list(data.get("merge_variables", {}).keys())
        ok(f"Fetched OK. Top-level keys: {keys}")
        departures = data.get("merge_variables", {}).get("departures", [])
        if departures:
            print(f"  Stored departures ({len(departures)}):")
            for dep in departures:
                print(f"    {dep.get('estimated_time', '?'):>8}  "
                      f"{dep.get('destination', '?'):<30}  "
                      f"Platform {dep.get('platform', '?')}  "
                      f"{'Express' if dep.get('is_express') else 'All stops'}")
        return True
    except httpx.HTTPStatusError as e:
        fail(f"HTTP {e.response.status_code}: {e.response.text}")
        return False
    except Exception as e:
        fail(str(e))
        return False


async def test_live_push(
    ptv: PTVClient,
    trmnl: TRMNLClient,
    stop_id: int,
    station_name: str,
    platform_numbers: list[int] | None = None,
) -> bool:
    """Fetch live PTV data and push it to TRMNL end-to-end."""
    sep("Test 3: Live PTV → TRMNL push")
    try:
        plat_str = f", platforms {platform_numbers}" if platform_numbers else ""
        print(f"  Fetching departures for stop {stop_id} ({station_name}{plat_str})...")
        departures = await ptv.get_departures(stop_id, max_results=3, platform_numbers=platform_numbers)
        print(f"  Got {len(departures)} departure(s):")
        for dep in departures:
            print(f"    {dep['estimated_time']:>8}  "
                  f"{dep['destination']:<30}  "
                  f"Platform {dep['platform']}  "
                  f"{'Express' if dep['is_express'] else 'All stops'}")

        payload = {
            "station_name": station_name,
            "departures": [
                {
                    "destination": d["destination"],
                    "scheduled_time": d["scheduled_time"],
                    "estimated_time": d["estimated_time"],
                    "platform": d["platform"],
                    "is_express": d["is_express"],
                }
                for d in departures
            ],
            "updated_at": datetime.now().strftime("%I:%M %p").lstrip("0").lower(),
        }

        print()
        print("  Pushing to TRMNL...")
        result = await trmnl.push_data(payload)
        ok(f"Live push succeeded. Response: {result}")
        return True
    except httpx.HTTPStatusError as e:
        fail(f"HTTP {e.response.status_code}: {e.response.text}")
        return False
    except Exception as e:
        fail(str(e))
        import traceback
        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def main() -> None:
    webhook_url = os.getenv("TRMNL_WEBHOOK_URL")
    dev_id = os.getenv("PTV_DEV_ID")
    api_key = os.getenv("PTV_API_KEY")
    stop_id = int(os.getenv("DEFAULT_STOP_ID", "19843"))
    station_name = os.getenv("STATION_NAME", "Melbourne Central")
    platform_numbers = None
    if platform_str := os.getenv("PLATFORM_NUMBERS"):
        platform_numbers = [int(p.strip()) for p in platform_str.split(",")]

    if not webhook_url:
        print("ERROR: TRMNL_WEBHOOK_URL not set in .env")
        return

    trmnl = TRMNLClient(webhook_url)
    results: dict[str, bool | None] = {}

    results["connectivity"] = await test_connectivity(trmnl, station_name)
    results["fetch_stored"] = await test_fetch_stored(webhook_url)

    if dev_id and api_key:
        ptv = PTVClient(dev_id, api_key)
        results["live_push"] = await test_live_push(ptv, trmnl, stop_id, station_name, platform_numbers)
    else:
        sep("Test 3: Live PTV → TRMNL push")
        print("  SKIP  PTV_DEV_ID or PTV_API_KEY not set in .env")
        results["live_push"] = None

    sep("Summary")
    passed  = sum(1 for v in results.values() if v is True)
    failed  = sum(1 for v in results.values() if v is False)
    skipped = sum(1 for v in results.values() if v is None)
    for name, result in results.items():
        label = "PASS" if result is True else ("SKIP" if result is None else "FAIL")
        print(f"  {label}  {name}")
    print()
    print(f"  {passed} passed  {failed} failed  {skipped} skipped")
    print()


if __name__ == "__main__":
    asyncio.run(main())
