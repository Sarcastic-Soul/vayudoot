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


_AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"


@tool
def get_air_quality_forecast(latitude: float, longitude: float, hours: int = 72) -> dict:
    """Get the hourly air quality and wind outlook for a location.

    Use this to judge whether air quality is about to degrade, and why. The
    pollutant values are a modelled forecast, not a measurement, and must be
    described that way in anything a person reads.

    Args:
        latitude: Latitude of the location.
        longitude: Longitude of the location.
        hours: How far ahead to look, 1 to 120. Defaults to 72.

    Returns:
        The peak forecast PM2.5 and PM10 with the hours they occur, the hours
        spent above the Indian 24-hour standard, and the wind direction the air
        is expected to arrive from.
    """
    span = max(1, min(hours, 120))
    try:
        resp = httpx.get(
            _AIR_QUALITY_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "hourly": "pm2_5,pm10",
                # From the current hour, not from midnight. `forecast_days`
                # starts the series at 00:00 UTC today, so a call made in the
                # evening spent most of a day of its "next 72 hours" on hours
                # that had already happened, and a peak found there was
                # reported as a forecast.
                "forecast_hours": span,
            },
            timeout=20,
        )
        resp.raise_for_status()
        hourly = resp.json().get("hourly", {})
    except Exception as exc:  # noqa: BLE001 - tool errors are reported to the agent
        return {"error": f"Open-Meteo air quality request failed: {exc}"}

    times = (hourly.get("time") or [])[:span]
    if not times:
        return {"error": "Open-Meteo returned no hourly air quality data"}

    out: dict = {
        "source": "Open-Meteo air quality model",
        "is_forecast": True,
        "hours_ahead": len(times),
        "window_start": times[0],
        "window_end": times[-1],
    }

    # Indian NAAQS 24-hour standards. The same numbers `config.py` carries, and
    # for the same reason: a forecast is raised so an Indian authority acts on
    # it, so it is measured against the standard that authority is bound by.
    standards = {"pm2_5": 60.0, "pm10": 100.0}
    for parameter, standard in standards.items():
        series = [v for v in (hourly.get(parameter) or [])[:span] if v is not None]
        if not series:
            continue
        peak = max(series)
        out[f"{parameter}_peak"] = peak
        out[f"{parameter}_peak_at"] = times[series.index(peak)]
        out[f"{parameter}_hours_above_standard"] = sum(1 for v in series if v >= standard)
        out[f"{parameter}_standard"] = standard

    return out


@tool
def get_wind_forecast(latitude: float, longitude: float, hours: int = 72) -> dict:
    """Get the hourly wind outlook for a location.

    Use this to work out where the air arriving at a location will have come
    from, which is what decides whether an upwind fire reaches it.

    Args:
        latitude: Latitude of the location.
        longitude: Longitude of the location.
        hours: How far ahead to look, 1 to 120. Defaults to 72.

    Returns:
        The dominant direction the wind is forecast to blow from, its average and
        peak speed, and whether conditions are stagnant enough to trap pollution.
    """
    span = max(1, min(hours, 120))
    try:
        resp = httpx.get(
            _URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "hourly": "wind_speed_10m,wind_direction_10m",
                "wind_speed_unit": "ms",
                "forecast_hours": span,
            },
            timeout=20,
        )
        resp.raise_for_status()
        hourly = resp.json().get("hourly", {})
    except Exception as exc:  # noqa: BLE001 - tool errors are reported to the agent
        return {"error": f"Open-Meteo wind forecast request failed: {exc}"}

    speeds = [v for v in (hourly.get("wind_speed_10m") or [])[:span] if v is not None]
    if not speeds:
        return {"error": "Open-Meteo returned no hourly wind data"}

    out: dict = {
        "source": "Open-Meteo",
        "is_forecast": True,
        "hours_ahead": len(speeds),
        "mean_wind_speed_ms": round(sum(speeds) / len(speeds), 2),
        "peak_wind_speed_ms": round(max(speeds), 2),
        # Still air is what turns a local fire into a smog episode: without wind
        # nothing disperses, so a low mean is as much a warning as a high one.
        "stagnant_hours": sum(1 for v in speeds if v < 1.5),
    }
    # Paired from the raw series, hour by hour: the filtered lists above can
    # drop different hours and would pair one hour's speed with another's
    # direction.
    dominant = dominant_bearing(
        (hourly.get("wind_speed_10m") or [])[:span],
        (hourly.get("wind_direction_10m") or [])[:span],
    )
    if dominant is not None:
        out["dominant_wind_from_degrees"] = round(dominant, 1)
        source_lat, source_lon = upwind_point(latitude, longitude, dominant, 50.0)
        out["air_arrives_from_latitude"] = round(source_lat, 5)
        out["air_arrives_from_longitude"] = round(source_lon, 5)
    return out


def dominant_bearing(speeds: list, bearings: list) -> float | None:
    """The direction the wind mostly blows from, as a speed-weighted vector mean.

    Compass bearings wrap at 360, so their arithmetic mean is wrong exactly when
    the wind is northerly: 350 and 10 average to 180, a southerly. Checked live
    on 28 September 2026 over a 72-hour Mumbai forecast whose hours ran from 9 to
    356 degrees: the arithmetic mean said 151 (south-south-east) and the vector
    mean 359 (north). The model was being told air came from the opposite side,
    which inverts the one judgement the forecast turns on — whether a fire is
    upwind. Each hour is weighted by its speed because an hour of calm carries
    no air from anywhere.

    Returns None when there is nothing to average or the hours cancel out.
    """
    import math

    pairs = [
        (s, b) for s, b in zip(speeds, bearings, strict=False) if s is not None and b is not None
    ]
    if not pairs:
        return None
    east = sum(s * math.sin(math.radians(b)) for s, b in pairs)
    north = sum(s * math.cos(math.radians(b)) for s, b in pairs)
    if math.hypot(east, north) < 1e-9:
        return None
    return (math.degrees(math.atan2(east, north)) + 360) % 360
