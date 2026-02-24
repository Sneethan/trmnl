"""
Simple test script to verify PTV API connection.
Run with: python test_ptv.py
"""

import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

# Import after loading env
from app.ptv_client import PTVClient


async def main():
    dev_id = os.getenv("PTV_DEV_ID")
    api_key = os.getenv("PTV_API_KEY")
    stop_id = int(os.getenv("DEFAULT_STOP_ID", "19843"))
    platform_str = os.getenv("PLATFORM_NUMBERS")

    if not dev_id or not api_key:
        print("Error: Missing PTV_DEV_ID or PTV_API_KEY in .env file")
        return

    platform_numbers = None
    if platform_str:
        platform_numbers = [int(p.strip()) for p in platform_str.split(",")]
        print(f"Testing PTV API for stop ID: {stop_id}, platforms: {platform_numbers}")
    else:
        print(f"Testing PTV API for stop ID: {stop_id} (all platforms)")
    print("-" * 40)

    client = PTVClient(dev_id, api_key)

    try:
        departures = await client.get_departures(stop_id, max_results=5, platform_numbers=platform_numbers)

        if not departures:
            print("No departures found.")
            return

        print(f"Found {len(departures)} departures:\n")

        for i, dep in enumerate(departures, 1):
            print(f"{i}. {dep['destination']}")
            print(f"   Scheduled: {dep['scheduled_time']}")
            print(f"   Platform: {dep['platform'] or 'TBA'}")
            print(f"   Express: {'Yes' if dep['is_express'] else 'No'}")
            print(f"   In: {dep['minutes_until']} min")
            print()

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
