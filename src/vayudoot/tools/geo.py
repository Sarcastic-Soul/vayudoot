"""Small geodesy helpers shared by the evidence tools."""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088


def bbox_around(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    """Return (west, south, east, north) for a square roughly `radius_km` across."""
    d_lat = radius_km / 110.574
    d_lon = radius_km / (111.320 * max(math.cos(math.radians(lat)), 0.01))
    return (lon - d_lon, lat - d_lat, lon + d_lon, lat + d_lat)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def point_at(lat: float, lon: float, bearing_deg: float, distance_km: float) -> tuple[float, float]:
    """Point `distance_km` away from (lat, lon) along a compass `bearing_deg`."""
    ang = distance_km / EARTH_RADIUS_KM
    br = math.radians(bearing_deg)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(ang) + math.cos(p1) * math.sin(ang) * math.cos(br))
    l2 = l1 + math.atan2(
        math.sin(br) * math.sin(ang) * math.cos(p1),
        math.cos(ang) - math.sin(p1) * math.sin(p2),
    )
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


def upwind_point(
    lat: float, lon: float, wind_from_degrees: float, distance_km: float = 2.0
) -> tuple[float, float]:
    """Back-trace a plume to a plausible source.

    Meteorological wind direction is the direction the wind blows *from*, so the
    source of anything carried to the report location lies along that same
    bearing.
    """
    return point_at(lat, lon, wind_from_degrees, distance_km)
