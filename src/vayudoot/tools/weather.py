"""Open-Meteo wind and weather. No API key required."""

from __future__ import annotations

import httpx
from strands import tool

from .geo import upwind_point

_URL = "https://api.open-meteo.com/v1/forecast"


@tool
def get_wind_conditions(latitude: float, longitude: float) -> dict:
    """Get current wind and weather at a location, and back-trace the plume upwind.

    Use this to work out where airborne pollution observed at the report location
    is most likely to have originated.

    Args:
        latitude: Latitude of the report location.
        longitude: Longitude of the report location.

    Returns:
        Wind speed in m/s, the compass bearing the wind is blowing from, temperature,
        humidity, and the coordinates of a plausible upwind source two kilometres away.
    """
    try:
        resp = httpx.get(
            _URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": "wind_speed_10m,wind_direction_10m,temperature_2m,relative_humidity_2m",
                "wind_speed_unit": "ms",
            },
            timeout=15,
        )
        resp.raise_for_status()
        current = resp.json().get("current", {})
    except Exception as exc:  # noqa: BLE001 - tool errors are reported to the agent
        return {"error": f"Open-Meteo request failed: {exc}"}

    wind_from = current.get("wind_direction_10m")
    result = {
        "wind_speed_ms": current.get("wind_speed_10m"),
        "wind_from_degrees": wind_from,
        "temperature_c": current.get("temperature_2m"),
        "relative_humidity_pct": current.get("relative_humidity_2m"),
        "observed_at": current.get("time"),
    }
    if wind_from is not None:
        src_lat, src_lon = upwind_point(latitude, longitude, float(wind_from))
        result["upwind_source_latitude"] = round(src_lat, 5)
        result["upwind_source_longitude"] = round(src_lon, 5)
    return result
