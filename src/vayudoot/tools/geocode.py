"""Reverse geocoding via OpenStreetMap Nominatim.

Turns the report's coordinates into an administrative address, which is what the
jurisdiction lookup keys on. Nominatim asks callers to identify themselves and
to stay under one request per second, both of which this respects.
"""

from __future__ import annotations

import httpx
from strands import tool

_URL = "https://nominatim.openstreetmap.org/reverse"
_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
_UA = "vayudoot/0.1 (pollution complaint agent; https://github.com/Sarcastic-Soul)"


@tool
def reverse_geocode(latitude: float, longitude: float) -> dict:
    """Resolve coordinates to an administrative address.

    Use this to find the ward, city, district, and state that a report falls in,
    which determines which authority has jurisdiction.

    Args:
        latitude: Latitude of the report location.
        longitude: Longitude of the report location.

    Returns:
        The display address and its administrative components.
    """
    try:
        resp = httpx.get(
            _URL,
            params={
                "lat": latitude,
                "lon": longitude,
                "format": "jsonv2",
                "zoom": 16,
                "addressdetails": 1,
            },
            headers={"User-Agent": _UA},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Nominatim request failed: {exc}"}

    addr = data.get("address", {})
    return {
        "display_name": data.get("display_name", ""),
        "suburb": addr.get("suburb") or addr.get("neighbourhood", ""),
        "city": addr.get("city") or addr.get("town") or addr.get("village", ""),
        "district": addr.get("state_district", ""),
        "state": addr.get("state", ""),
        "postcode": addr.get("postcode", ""),
        "country": addr.get("country", ""),
        "country_code": addr.get("country_code", ""),
    }


def search_places(query: str, limit: int = 5) -> list[dict]:
    """Find coordinates for a place name.

    Not a tool: the interface uses this so a citizen can name where the pollution
    is instead of typing coordinates. Nobody knows their own latitude.
    """
    if not query.strip():
        return []

    try:
        resp = httpx.get(
            _SEARCH_URL,
            params={
                "q": query,
                "format": "jsonv2",
                "addressdetails": 1,
                "limit": max(1, min(limit, 10)),
                "countrycodes": "in",
            },
            headers={"User-Agent": _UA},
            timeout=20,
        )
        resp.raise_for_status()
        results = resp.json()
    except Exception as exc:  # noqa: BLE001
        return [{"error": f"Nominatim search failed: {exc}"}]

    return [
        {
            "display_name": item.get("display_name", ""),
            "latitude": float(item["lat"]),
            "longitude": float(item["lon"]),
        }
        for item in results
        if item.get("lat") and item.get("lon")
    ]
