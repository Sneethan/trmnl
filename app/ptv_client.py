import hashlib
import re
import hmac
from datetime import datetime, timezone
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

import httpx

MELBOURNE_TZ = ZoneInfo("Australia/Melbourne")


def _clean_stop_name(name: str) -> str:
    return re.sub(r"\s*\bStation\b\s*$", "", name, flags=re.IGNORECASE).strip()


class PTVClient:
    BASE_URL = "https://timetableapi.ptv.vic.gov.au"

    def __init__(self, dev_id: str, api_key: str):
        self.dev_id = dev_id
        self.api_key = api_key

    def _sign_url(self, path: str) -> str:
        """Generate signed URL for PTV API."""
        separator = "&" if "?" in path else "?"
        path_with_devid = f"{path}{separator}devid={self.dev_id}"

        signature = hmac.new(
            self.api_key.encode("utf-8"),
            path_with_devid.encode("utf-8"),
            hashlib.sha1,
        ).hexdigest().upper()

        return f"{self.BASE_URL}{path_with_devid}&signature={signature}"

    async def get_departures(
        self,
        stop_id: int,
        route_type: int = 0,
        max_results: int = 6,
        platform_numbers: list[int] | None = None,
    ) -> list[dict]:
        """Get upcoming departures from a stop."""
        path = f"/v3/departures/route_type/{route_type}/stop/{stop_id}"
        params: dict = {}
        if platform_numbers:
            params["platform_numbers"] = platform_numbers
        params["max_results"] = max_results
        params["expand"] = ["run", "direction"]
        query = urlencode(params, doseq=True)
        full_path = f"{path}?{query}"

        url = self._sign_url(full_path)

        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        return self._process_departures(data)[:max_results]

    def _process_departures(self, data: dict) -> list[dict]:
        """Transform PTV response into display-ready format."""
        departures = []

        for dep in data.get("departures", []):
            route = data.get("routes", {}).get(str(dep["route_id"]), {})
            run = data.get("runs", {}).get(str(dep["run_id"]), {})
            direction = data.get("directions", {}).get(str(dep["direction_id"]), {})

            scheduled = datetime.fromisoformat(
                dep["scheduled_departure_utc"].replace("Z", "+00:00")
            )
            estimated = dep.get("estimated_departure_utc")
            if estimated:
                departure_time = datetime.fromisoformat(
                    estimated.replace("Z", "+00:00")
                )
            else:
                departure_time = scheduled

            now = datetime.now(timezone.utc)
            minutes_until = int((departure_time - now).total_seconds() / 60)

            departures.append({
                "destination": run.get("destination_name", direction.get("direction_name", "Unknown")),
                "scheduled_time": scheduled.astimezone(MELBOURNE_TZ).strftime("%I:%M %p").lstrip("0").lower(),
                "estimated_time": departure_time.astimezone(MELBOURNE_TZ).strftime("%I:%M %p").lstrip("0").lower(),
                "minutes_until": max(0, minutes_until),
                "platform": dep.get("platform_number", ""),
                "is_express": run.get("express_stop_count", 0) > 0,
                "train_type": "Ltd Express" if run.get("express_stop_count", 0) > 0 else "Stops All",
                "run_ref": dep.get("run_ref", ""),
                "route_id": dep["route_id"],
                "direction_id": dep["direction_id"],
            })

        return departures

    async def get_route_stops(
        self,
        route_id: int,
        direction_id: int,
        current_stop_id: int,
        route_type: int = 0,
    ) -> list[dict]:
        """Get stops on a route from the current station onward."""
        path = f"/v3/stops/route/{route_id}/route_type/{route_type}"
        params = {"direction_id": direction_id}
        full_path = f"{path}?{urlencode(params)}"

        url = self._sign_url(full_path)

        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        stops = sorted(data.get("stops", []), key=lambda s: s["stop_sequence"])

        current_seq = next(
            (s["stop_sequence"] for s in stops if s["stop_id"] == current_stop_id),
            0,
        )

        return [
            {
                "name": _clean_stop_name(s["stop_name"]),
                "stop_id": s["stop_id"],
                "is_current": s["stop_id"] == current_stop_id,
                "is_express": False,
            }
            for s in stops
            if s["stop_sequence"] >= current_seq
        ]

    async def search_stops(self, term: str, route_type: int = 0) -> list[dict]:
        """Search for stops by name, filtered to a route type."""
        path = f"/v3/search/{quote(term)}"
        params = {"route_types": route_type}
        full_path = f"{path}?{urlencode(params, doseq=True)}"

        url = self._sign_url(full_path)

        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        return [
            {"stop_id": s["stop_id"], "stop_name": _clean_stop_name(s["stop_name"])}
            for s in data.get("stops", [])
        ]

    async def get_stopping_pattern(self, run_ref: str, current_stop_id: int, route_type: int = 0) -> list[dict]:
        """Get stopping pattern for a specific run.

        Makes two requests to the pattern endpoint:
        1. Without include_skipped_stops — gives us the stops the train calls at.
        2. With include_skipped_stops — gives us ALL stops on the train's actual
           path (including express-skipped ones).

        By diffing the two we know exactly which stops are express, without
        needing the route-stops endpoint (which returns city-loop stops that
        may not be on this run's path at all).
        """
        base_path = f"/v3/pattern/run/{run_ref}/route_type/{route_type}"

        # Request 1: calling stops only
        params = {"expand": ["stop"]}
        url = self._sign_url(f"{base_path}?{urlencode(params, doseq=True)}")
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data_calling = resp.json()

        # Request 2: all stops on the run's path (including skipped)
        params_full = {"expand": ["stop"], "include_skipped_stops": "true"}
        url_full = self._sign_url(f"{base_path}?{urlencode(params_full, doseq=True)}")
        async with httpx.AsyncClient() as client:
            resp_full = await client.get(url_full)
            resp_full.raise_for_status()
            data_full = resp_full.json()

        stops_lookup = {**data_calling.get("stops", {}), **data_full.get("stops", {})}

        def stop_name(stop_id):
            info = stops_lookup.get(str(stop_id), {})
            return _clean_stop_name(info.get("stop_name", "Unknown"))

        # Build set of stop_ids the train actually calls at (from current stop onward)
        calling_ids: set[int] = set()
        found_current = False
        for dep in data_calling.get("departures", []):
            sid = dep.get("stop_id")
            if sid == current_stop_id:
                found_current = True
            if found_current:
                calling_ids.add(sid)

        # Build ordered list of ALL stops on the run's path (from current stop onward)
        found_current = False
        result = []
        for dep in data_full.get("departures", []):
            sid = dep.get("stop_id")
            if sid == current_stop_id:
                found_current = True
            if not found_current:
                continue
            result.append({
                "name": stop_name(sid),
                "stop_id": sid,
                "is_current": sid == current_stop_id,
                "is_express": sid not in calling_ids,
            })

        return result
