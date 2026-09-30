"""CPCB's own live station feed: every continuous monitoring station in India.

The Central Pollution Control Board publishes the current hour's AQI for all of
its continuous stations — about five hundred, run by CPCB and the state boards —
as one XML document at a public URL that needs no key. data.gov.in republishes
the same numbers behind an API key, and its API host refused connections when
this was written; the board's own feed is the source both come from.

Three things about it decide how it is used.

**One request covers the country.** The feed is not queried by location, so it
is fetched once and cached for `_TTL`, and every scan point in a pass filters
the same parsed copy. A scan over forty corridor waypoints costs one request,
not forty.

**The numbers are AQI sub-indices, not concentrations.** Each pollutant carries
`Min`, `Max` and `Avg` on the National AQI's 0–500 scale; the station's AQI is
the largest `Avg`. That is not something to convert back to µg/m³ — the
breakpoints are piecewise and the feed does not say which averaging window it
used — and it does not need converting: the National AQI is built so that a
sub-index of 100 is the national ambient standard. `hotspots.signals_from_cpcb`
reads the index directly for that reason rather than going through the unit
conversion the OpenAQ builder needs.

**India only.** A point with no CPCB station in range gets an empty list, and
the scan asks OpenAQ instead. See `scan._scan_point` for why it is one or the
other and never both.
"""

from __future__ import annotations

import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import httpx

from .geo import haversine_km

_FEED = "https://airquality.cpcb.gov.in/caaqms/rss_feed"

#: Stations report hourly, so a cache shorter than that only re-reads the same
#: hour. Fifteen minutes keeps a fresh hour from waiting long to appear.
_TTL = 15 * 60

#: `lastupdate` is Indian Standard Time and carries no offset.
_IST = timezone(timedelta(hours=5, minutes=30))

_lock = threading.Lock()
_cache: tuple[float, list[dict]] | None = None


def get_cpcb_stations(latitude: float, longitude: float, radius_km: float = 25.0) -> dict:
    """Get the current AQI from official CPCB monitoring stations near a location in India.

    Values are National AQI sub-indices (0 to 500) per pollutant, where 100 is
    the national ambient standard. Outside India this returns no stations.

    Args:
        latitude: Latitude of the location.
        longitude: Longitude of the location.
        radius_km: Search radius in kilometres. Defaults to 25.

    Returns:
        The stations within the radius, nearest first, each with its position,
        distance, observation time, AQI, predominant pollutant and sub-indices.
    """
    try:
        stations = _stations()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"CPCB feed request failed: {exc}", "stations": []}

    near = []
    for station in stations:
        distance = haversine_km(latitude, longitude, station["latitude"], station["longitude"])
        if distance <= radius_km:
            near.append({**station, "distance_km": round(distance, 2)})
    near.sort(key=lambda s: s["distance_km"])
    return {"source": "CPCB", "stations": near}


def _stations() -> list[dict]:
    """The parsed feed, fetched at most once per `_TTL` however many callers ask."""
    global _cache
    with _lock:
        if _cache is not None and time.monotonic() - _cache[0] < _TTL:
            return _cache[1]
        response = httpx.get(_FEED, timeout=30, follow_redirects=True)
        response.raise_for_status()
        stations = parse(response.content)
        _cache = (time.monotonic(), stations)
        return stations


def parse(document: bytes | str) -> list[dict]:
    """Every station in a feed document that has a position and an AQI.

    A station missing either is skipped rather than guessed at: without a
    position it cannot be placed, and without an AQI it has not reported this
    hour. A pollutant whose average is absent or `NA` is left out of that
    station's sub-indices for the same reason.
    """
    root = ET.fromstring(document)
    out: list[dict] = []
    for station in root.iter("Station"):
        try:
            latitude = float(station.get("latitude", ""))
            longitude = float(station.get("longitude", ""))
        except ValueError:
            continue
        aqi = station.find("Air_Quality_Index")
        if aqi is None or not _number(aqi.get("Value")):
            continue

        sub_indices = {}
        for pollutant in station.iter("Pollutant_Index"):
            value = _number(pollutant.get("Avg"))
            if value is not None and pollutant.get("id"):
                sub_indices[pollutant.get("id")] = value

        out.append(
            {
                "name": station.get("id") or f"{latitude:.4f},{longitude:.4f}",
                "latitude": latitude,
                "longitude": longitude,
                "observed_at": _observed(station.get("lastupdate")),
                "aqi": _number(aqi.get("Value")),
                "predominant": aqi.get("Predominant_Parameter"),
                "sub_indices": sub_indices,
            }
        )
    return out


def _number(text: str | None) -> float | None:
    try:
        return float(text) if text is not None else None
    except ValueError:
        return None


def _observed(text: str | None) -> str | None:
    """`30-09-2026 19:00:00` in IST, as an ISO 8601 timestamp with its offset."""
    if not text:
        return None
    try:
        return datetime.strptime(text, "%d-%m-%Y %H:%M:%S").replace(tzinfo=_IST).isoformat()
    except ValueError:
        return None
