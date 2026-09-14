"""Where air quality is about to degrade, and why.

The brief asks for forecasts and nothing in the system predicted anything. Vertex
AI is the obvious tool for it and the free-tier constraint rules it out — there is
no card, and Google Cloud's free tier needs a billing account — so what this does
instead is reason over public data with the model already in use.

That makes the honesty of the label the whole design. This is **not** a trained
predictor. It is Gemini reading an Open-Meteo pollutant forecast, an Open-Meteo
wind forecast and the hotspots this instance has already detected, and saying
what it thinks follows. `AirQualityForecast` carries `basis` so a reader can
check the work and `disclaimer` so nobody mistakes it for an advisory, and hard
constraint 7 requires both to survive every rendering.

The stage runs on the `fast` tier, like every other tool-calling stage. It reads
three payloads of numbers and writes a short structured judgement, which is the
work flash-lite is for; the two primary-tier stages stay the two that read a
photograph and draft a legal document. Constraint 5.
"""

from __future__ import annotations

import asyncio

from strands import Agent

from ..config import settings
from ..models import build_model
from ..schemas import AirQualityForecast, Corridor, CorridorForecast, Hotspot
from ..tools import get_air_quality_forecast, get_wind_forecast
from ..tools.geo import haversine_km
from .prompts import FORECAST

#: Worst-first, so a corridor can be summarised by the segment in trouble.
RISK_ORDER: list[str] = ["low", "elevated", "high", "severe"]


def build_forecast_agent() -> Agent:
    return Agent(
        name="forecast",
        model=build_model(temperature=0.1, tier="fast"),
        system_prompt=FORECAST,
        tools=[get_air_quality_forecast, get_wind_forecast],
        callback_handler=None,
    )


async def forecast_location(
    latitude: float,
    longitude: float,
    location_name: str = "",
    nearby_hotspots: list[Hotspot] | None = None,
    agent: Agent | None = None,
) -> AirQualityForecast:
    """The outlook for one point, given the hotspots that could reach it."""
    agent = agent or build_forecast_agent()
    horizon = settings.vayudoot_forecast_horizon_hours

    prompt = (
        f"Location: {location_name or 'unnamed'} at latitude {latitude}, "
        f"longitude {longitude}.\n"
        f"Horizon: the next {horizon} hours.\n\n"
        f"{_describe_hotspots(latitude, longitude, nearby_hotspots or [])}\n\n"
        "Call both forecast tools for this location, then give the outlook."
    )
    result = await agent.invoke_async(prompt, structured_output_model=AirQualityForecast)

    outlook = result.structured_output
    # The model is asked for its judgement, not for its coordinates or its
    # honesty about what it is. Those are the caller's to set, and leaving them
    # to the model is how a forecast ends up attached to somewhere else.
    #
    # Copied rather than mutated in place. The object came from outside this
    # function and may be shared — two waypoints handed the same instance would
    # otherwise each overwrite the other's location, and the corridor would
    # report one place three times.
    return outlook.model_copy(
        update={
            "latitude": latitude,
            "longitude": longitude,
            "location_name": location_name or outlook.location_name,
            "horizon_hours": horizon,
        }
    )


async def forecast_corridor(
    corridor: Corridor,
    hotspots: list[Hotspot] | None = None,
    agent: Agent | None = None,
) -> CorridorForecast:
    """The outlook along one economic corridor.

    Every waypoint is forecast in parallel — they share no state and each is one
    fast call — and the corridor takes the worst risk any of them carries. A
    corridor is a population strip and a supply line: the segment in trouble is
    what an authority needs to see, and averaging it away would hide exactly the
    thing worth acting on.
    """
    agent = agent or build_forecast_agent()
    pool = hotspots or []

    outlooks = await asyncio.gather(
        *(
            forecast_location(
                latitude=lat,
                longitude=lon,
                location_name=f"{corridor.name} waypoint {index + 1}",
                nearby_hotspots=pool,
                agent=agent,
            )
            for index, (lat, lon) in enumerate(corridor.waypoints)
        ),
        return_exceptions=True,
    )

    # A waypoint that failed is dropped rather than allowed to sink the corridor.
    # One provider error must not turn a corridor's outlook into silence.
    good = [o for o in outlooks if isinstance(o, AirQualityForecast)]
    worst = max((o.risk for o in good), key=RISK_ORDER.index, default="low")

    return CorridorForecast(
        corridor_id=corridor.corridor_id,
        corridor_name=corridor.name,
        risk=worst,  # type: ignore[arg-type]
        summary=_corridor_summary(corridor, good, worst),
        waypoint_forecasts=good,
    )


def upwind_hotspots(
    latitude: float, longitude: float, hotspots: list[Hotspot]
) -> list[Hotspot]:
    """Hotspots close enough to reach a location, nearest first.

    Distance only. Whether the wind is actually bringing one of them is a
    judgement for the model, which has the wind forecast and this list; deciding
    it here would be geometry pretending to be meteorology.
    """
    reach = settings.vayudoot_forecast_upwind_km
    within = [
        (haversine_km(latitude, longitude, h.centre_latitude, h.centre_longitude), h)
        for h in hotspots
    ]
    return [h for km, h in sorted(within, key=lambda pair: pair[0]) if km <= reach]


def _describe_hotspots(latitude: float, longitude: float, hotspots: list[Hotspot]) -> str:
    near = upwind_hotspots(latitude, longitude, hotspots)
    if not near:
        return "Active pollution hotspots within reach of this location: none detected."

    lines = ["Active pollution hotspots within reach of this location:"]
    for spot in near[:10]:
        km = haversine_km(latitude, longitude, spot.centre_latitude, spot.centre_longitude)
        bearing = _compass(latitude, longitude, spot.centre_latitude, spot.centre_longitude)
        corroboration = (
            "independently corroborated"
            if spot.corroborated
            else "citizen reports only, not independently corroborated"
        )
        lines.append(
            f"- {spot.pollution_type.value.replace('_', ' ')}, severity {spot.severity}, "
            f"{km:.0f} km to the {bearing}, confidence {spot.confidence:.2f} "
            f"({corroboration})"
        )
    return "\n".join(lines)


def _corridor_summary(
    corridor: Corridor, outlooks: list[AirQualityForecast], worst: str
) -> str:
    if not outlooks:
        return f"No outlook could be produced for {corridor.name}."

    at_worst = [o for o in outlooks if o.risk == worst]
    where = ", ".join(o.location_name for o in at_worst[:3]) or corridor.name
    return (
        f"{corridor.name}: {worst} risk over the next "
        f"{outlooks[0].horizon_hours} hours, driven by {where}. "
        f"{len(outlooks)} of {len(corridor.waypoints)} waypoints reporting."
    )


def _compass(lat1: float, lon1: float, lat2: float, lon2: float) -> str:
    """Rough compass direction from one point to another, for a readable prompt."""
    import math

    d_lon = math.radians(lon2 - lon1)
    y = math.sin(d_lon) * math.cos(math.radians(lat2))
    x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - math.sin(
        math.radians(lat1)
    ) * math.cos(math.radians(lat2)) * math.cos(d_lon)
    bearing = (math.degrees(math.atan2(y, x)) + 360) % 360
    points = [
        "north", "north-east", "east", "south-east",
        "south", "south-west", "west", "north-west",
    ]
    return points[round(bearing / 45) % 8]
