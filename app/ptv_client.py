import hashlib
import re
import hmac
from datetime import datetime, timezone
from urllib.parse import quote, urlencode

import httpx


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
                "scheduled_time": scheduled.astimezone().strftime("%I:%M %p").lstrip("0").lower(),
                "estimated_time": departure_time.astimezone().strftime("%I:%M %p").lstrip("0").lower(),
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
        """Get stopping pattern for a specific run, including skipped (express) stops."""
        path = f"/v3/pattern/run/{run_ref}/route_type/{route_type}"
        params = {"expand": ["stop"], "include_skipped_stops": "true"}
        query = urlencode(params, doseq=True)
        full_path = f"{path}?{query}"

        url = self._sign_url(full_path)

        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        stops_lookup = data.get("stops", {})

        def stop_name(stop_id):
            info = stops_lookup.get(str(stop_id), {})
            return _clean_stop_name(info.get("stop_name", "Unknown"))

        result = []
        found_current = False

        for dep in data.get("departures", []):
            sid = dep.get("stop_id")
            is_current = sid == current_stop_id
            if is_current:
                found_current = True

            if not found_current:
                continue

            result.append({
                "name": stop_name(sid),
                "stop_id": sid,
                "is_current": is_current,
                "is_express": False,
            })

            # Interleave any stops skipped after this scheduled stop
            for skipped in dep.get("skipped_stops", []):
                skipped_id = skipped.get("stop_id")
                skipped_name = _clean_stop_name(
                    stops_lookup.get(str(skipped_id), {}).get("stop_name")
                    or skipped.get("stop_name", "Unknown")
                )
                result.append({
                    "name": skipped_name,
                    "stop_id": skipped_id,
                    "is_current": False,
                    "is_express": True,
                })

        return result
