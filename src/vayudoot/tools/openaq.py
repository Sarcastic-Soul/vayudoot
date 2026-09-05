"""OpenAQ v3 ground station readings.

OpenAQ aggregates national monitoring networks, including the Indian Central
Pollution Control Board stations, so a report can be checked against the
official reading that the authority itself will recognise.
"""

from __future__ import annotations

import httpx
from strands import tool

from ..config import settings
from .geo import haversine_km

_BASE = "https://api.openaq.org/v3"


def _headers() -> dict[str, str]:
    return {"X-API-Key": settings.openaq_api_key}


@tool
def get_nearby_air_quality(latitude: float, longitude: float, radius_km: float = 25.0) -> dict:
    """Get the most recent air quality readings from ground stations near a location.

    Use this to check whether measured pollutant levels support the citizen's report.

    Args:
        latitude: Latitude of the report location.
        longitude: Longitude of the report location.
        radius_km: Search radius in kilometres, maximum 25. Defaults to 25.

    Returns:
        The nearest station, its distance, and its latest pollutant measurements
        with units and timestamps.
    """
    if not settings.openaq_api_key:
        return {"error": "OPENAQ_API_KEY is not configured", "stations": []}

    radius_m = int(min(radius_km, 25.0) * 1000)
    try:
        loc_resp = httpx.get(
            f"{_BASE}/locations",
            params={
                "coordinates": f"{latitude},{longitude}",
                "radius": radius_m,
                "limit": 5,
            },
            headers=_headers(),
            timeout=20,
        )
        loc_resp.raise_for_status()
        locations = loc_resp.json().get("results", [])
    except Exception as exc:  # noqa: BLE001
        return {"error": f"OpenAQ locations request failed: {exc}", "stations": []}

    if not locations:
        return {"stations": [], "note": f"No monitoring station within {radius_km} km"}

    nearest = locations[0]
    coords = nearest.get("coordinates") or {}
    distance = None
    if coords.get("latitude") is not None:
        distance = round(
            haversine_km(latitude, longitude, coords["latitude"], coords["longitude"]), 2
        )

    measurements = []
    try:
        latest_resp = httpx.get(
            f"{_BASE}/locations/{nearest['id']}/latest",
            headers=_headers(),
            timeout=20,
        )
        latest_resp.raise_for_status()
        by_param = {s["id"]: s for s in nearest.get("sensors", [])}
        for row in latest_resp.json().get("results", []):
            sensor = by_param.get(row.get("sensorsId"), {})
            param = sensor.get("parameter") or {}
            measurements.append(
                {
                    "parameter": param.get("name"),
                    "value": row.get("value"),
                    "unit": param.get("units"),
                    "measured_at": (row.get("datetime") or {}).get("utc"),
                }
            )
    except Exception as exc:  # noqa: BLE001
        return {
            "error": f"OpenAQ latest request failed: {exc}",
            "nearest_station": nearest.get("name"),
        }

    return {
        "nearest_station": nearest.get("name"),
        "station_id": nearest.get("id"),
        "distance_km": distance,
        "provider": (nearest.get("provider") or {}).get("name"),
        "measurements": measurements,
        "other_stations_nearby": len(locations) - 1,
    }
