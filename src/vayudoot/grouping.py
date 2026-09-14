"""Centroid-linkage grouping of observations in space and time.

Extracted from `clustering.py`, which grouped citizen cases and was the only
caller until hotspot detection needed the same rule for satellite detections and
station readings. Two copies of this would have drifted, and the drift would be
invisible: both would still produce groups, just not the same ones, and the map
would disagree with the complaint drafted from it.

The rule itself is `clustering.py`'s and the reasoning is unchanged:

Proximity is measured to the group's **centroid**, not to any member. Linking to
the nearest member chains — a line of observations 400 m apart would walk across
a city and report one absurd group. Centroid linkage bounds a group's diameter to
roughly twice the radius, which is the behaviour a complaint can defend.

The window is a maximum **gap**, not a maximum age. A site that burns every
fortnight for six months is one ongoing pattern; a fire in January and another in
November are two episodes that happen to share a postcode.

Items are consumed in timestamp order, which is what makes the output
deterministic: the same store always yields the same groups, which is in turn
what lets a group's identity be stable enough to cite.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timedelta
from typing import TypeVar

from .tools.geo import haversine_km

T = TypeVar("T")

#: Where an item is, as (latitude, longitude).
Position = Callable[[T], "tuple[float, float]"]
#: When an item was observed. Must be timezone-aware; see `clustering._observed`
#: and `hotspots._observed` for the normalisation each caller applies first.
Timestamp = Callable[[T], datetime]


def centroid(items: Sequence[T], position: Position) -> tuple[float, float]:
    """Arithmetic mean of the items' coordinates.

    A flat mean is wrong on a globe and irrelevant at this scale: every group
    spans well under a kilometre, where the error is centimetres.
    """
    points = [position(item) for item in items]
    return (
        sum(lat for lat, _ in points) / len(points),
        sum(lon for _, lon in points) / len(points),
    )


def link(
    items: Iterable[T],
    *,
    position: Position,
    timestamp: Timestamp,
    radius_km: float,
    max_gap: timedelta,
) -> list[list[T]]:
    """Partition observations into groups by centroid linkage in time order.

    Callers are responsible for having already split `items` by anything that
    must match exactly — pollution type, in both current callers. This function
    only knows about distance and time.
    """
    ordered = sorted(items, key=timestamp)

    groups: list[list[T]] = []
    for item in ordered:
        lat, lon = position(item)
        best: list[T] | None = None
        best_km = math.inf
        for group in groups:
            if timestamp(item) - timestamp(group[-1]) > max_gap:
                continue
            centre_lat, centre_lon = centroid(group, position)
            km = haversine_km(lat, lon, centre_lat, centre_lon)
            if km <= radius_km and km < best_km:
                best, best_km = group, km
        if best is None:
            groups.append([item])
        else:
            best.append(item)
    return groups
