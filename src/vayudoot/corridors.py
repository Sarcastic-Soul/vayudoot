"""Major economic corridors, loaded from data.

The brief asks for forecasts "across major economic corridors", so a corridor is
a named object with a real alignment rather than an abstraction over whatever
hotspots happen to line up. It follows the authority table's rule — jurisdiction
data is data — so the corridors themselves live in `data/corridors.json` and
adding one is a JSON edit, never a change to this module. Nothing here names a
state, a city or a route.

Waypoints are sampling points, not a route to drive: a forecast is produced per
waypoint and summarised for the corridor, which is why four to eight sparse
points along the real alignment is the right density. Each waypoint in the data
file also carries the name of the place it sits on, which `Corridor` does not
keep. That is deliberate rather than lossy: nothing downstream needs the label,
but forty bare coordinate pairs are unreviewable, and a name is what lets
somebody check a number against a map before trusting a forecast built on it.
"""

from __future__ import annotations

import itertools
import json
import math
from functools import lru_cache
from pathlib import Path

from .schemas import Corridor
from .tools.geo import haversine_km

_DATA = Path(__file__).resolve().parent / "data" / "corridors.json"


@lru_cache(maxsize=1)
def _corridors() -> tuple[Corridor, ...]:
    """Parse the data file once. The id is the key, so it cannot be duplicated."""
    blob = json.loads(_DATA.read_text())
    return tuple(
        Corridor(
            corridor_id=corridor_id,
            name=entry.get("name", corridor_id),
            states=list(entry.get("states", [])),
            waypoints=[(p["latitude"], p["longitude"]) for p in entry.get("waypoints", [])],
            description=entry.get("description", ""),
        )
        for corridor_id, entry in blob.get("corridors", {}).items()
    )


def all_corridors() -> list[Corridor]:
    """Every corridor in the table, in the order the data file declares them."""
    return list(_corridors())


def get_corridor(corridor_id: str) -> Corridor | None:
    """One corridor by id, or None. An unknown id is a miss, never an exception.

    Corridor ids reach this from URLs and from model output, so a typo must
    produce a 404 rather than a traceback.
    """
    key = corridor_id.strip().lower()
    for corridor in _corridors():
        if corridor.corridor_id == key:
            return corridor
    return None


def corridors_near(latitude: float, longitude: float, within_km: float) -> list[Corridor]:
    """Corridors whose route passes within `within_km` of a point, nearest first.

    Distance is measured to the corridor's *line*, not to its nearest waypoint.
    The waypoints are sparse by design, so nearest-waypoint distance would put a
    town midway between Vadodara and Surat sixty kilometres from a corridor that
    runs straight through it, and the forecast for that corridor would never be
    offered to the place that needs it most.
    """
    scored = [
        (_distance_to_route_km(latitude, longitude, c), c) for c in _corridors() if c.waypoints
    ]
    return [c for distance, c in sorted(scored, key=lambda pair: pair[0]) if distance <= within_km]


def _distance_to_route_km(latitude: float, longitude: float, corridor: Corridor) -> float:
    """Kilometres from a point to the closest segment of a corridor's route."""
    points = corridor.waypoints
    if len(points) == 1:
        return haversine_km(latitude, longitude, points[0][0], points[0][1])
    return min(
        _segment_distance_km(latitude, longitude, a, b) for a, b in itertools.pairwise(points)
    )


def _segment_distance_km(
    latitude: float,
    longitude: float,
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    """Distance from a point to the segment between two waypoints.

    The projection is equirectangular around the query point — the same
    approximation `geo.bbox_around` already makes, and accurate to well under a
    kilometre over the few hundred kilometres a segment spans. Great-circle
    cross-track distance would be more correct and would change no answer this
    system acts on.
    """
    scale = 111.320 * max(math.cos(math.radians(latitude)), 0.01)

    def to_km(point: tuple[float, float]) -> tuple[float, float]:
        return ((point[1] - longitude) * scale, (point[0] - latitude) * 110.574)

    ax, ay = to_km(start)
    bx, by = to_km(end)
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(ax, ay)

    # How far along the segment the perpendicular from the origin falls, clamped
    # so that a point beyond either end measures to the end rather than to the
    # infinite line the segment sits on.
    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / length_sq))
    return math.hypot(ax + t * dx, ay + t * dy)
