"""NASA FIRMS active fire detections.

Satellite thermal anomalies are the strongest independent corroboration for a
citizen report of open burning: they are recorded by an instrument in orbit and
cannot be staged from the ground.
"""

from __future__ import annotations

import csv
import io

import httpx
from strands import tool

from ..config import settings
from .geo import bbox_around, haversine_km

_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
_SOURCE = "VIIRS_SNPP_NRT"


@tool
def find_satellite_fire_detections(
    latitude: float, longitude: float, radius_km: float = 10.0, days: int = 1
) -> dict:
    """Find satellite-detected thermal anomalies near a location.

    Use this to corroborate a report of open waste burning or crop residue burning.
    A detection close to the report location and within the reported time window is
    strong independent evidence.

    Args:
        latitude: Latitude of the report location.
        longitude: Longitude of the report location.
        radius_km: Search radius in kilometres. Defaults to 10.
        days: How many days back to search, 1 to 10. Defaults to 1.

    Returns:
        The number of detections found and details of the closest ones, including
        distance from the report and the satellite's confidence rating.
    """
    if not settings.firms_map_key:
        return {"error": "FIRMS_MAP_KEY is not configured", "detections": []}

    west, south, east, north = bbox_around(latitude, longitude, radius_km)
    url = f"{_BASE}/{settings.firms_map_key}/{_SOURCE}/{west},{south},{east},{north}/{max(1, min(days, 10))}"

    try:
        resp = httpx.get(url, timeout=30)
        resp.raise_for_status()
        rows = list(csv.DictReader(io.StringIO(resp.text)))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"FIRMS request failed: {exc}", "detections": []}

    detections = []
    for row in rows:
        try:
            d_lat, d_lon = float(row["latitude"]), float(row["longitude"])
        except (KeyError, ValueError):
            continue
        dist = haversine_km(latitude, longitude, d_lat, d_lon)
        if dist > radius_km:
            continue
        detections.append(
            {
                "distance_km": round(dist, 2),
                "latitude": d_lat,
                "longitude": d_lon,
                "acquired_date": row.get("acq_date"),
                "acquired_time_utc": row.get("acq_time"),
                "confidence": row.get("confidence"),
                "brightness_kelvin": row.get("bright_ti4"),
                "fire_radiative_power_mw": row.get("frp"),
            }
        )

    detections.sort(key=lambda d: d["distance_km"])
    return {
        "source": _SOURCE,
        "search_radius_km": radius_km,
        "days_searched": days,
        "detection_count": len(detections),
        "detections": detections[:10],
    }
