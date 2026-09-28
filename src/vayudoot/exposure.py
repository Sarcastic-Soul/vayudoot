"""How many people live close enough to a hotspot to be breathing it.

The brief frames these events as a threat to public health, and a circle on a map
does not say how much of one. Two fires of the same severity are not the same
priority when one is in open farmland and the other is upwind of a million
people, and the number that separates them is a count of people. That is all this
module adds: a population figure, and the largest towns it came from.

**What is counted, exactly.** The populations of places in the GeoNames
`cities15000` gazetteer (CC BY 4.0) whose *centre* lies within a radius of the
hotspot's centre. `data/settlements.csv` is that gazetteer filtered to India, the
neighbouring countries whose smoke reaches it, and South Africa and Brazil, the
two other countries this repository carries authority tables for;
`scripts/build_settlements.py` rebuilds it, so the provenance is checkable rather
than asserted.

It is therefore a lower bound in the countryside and a coarse figure in a city,
and the `basis` string says both. Villages under 15,000 people are not in the
gazetteer at all, which is most of rural Punjab — the very place stubble burns —
so a farmland hotspot reads low. A city counts whole when its centre is in reach
and not at all when it is not, so Delhi's eleven million arrive or vanish at a
kilometre's difference. Neither is a reason to leave the number out; both are
reasons to say what it is. An overstated exposure figure would be a public claim
the data does not support, which is hard constraint 7's concern in a new form.

**Places, never facilities.** `towns` names settlements, which are public and
large by construction — the gazetteer's floor is 15,000 people. Nothing here can
name an operator. Hard constraint 7.

**It does not touch confidence or ranking.** Exposure answers "how much does it
matter if this is real", which is a different question from "is this real". A
hotspot next to a city is not more likely to exist, and letting population lift
confidence would put the best-corroborated fire in empty country below a weak
report from a suburb. It is carried on the hotspot for a reader to weigh.
"""

from __future__ import annotations

import bisect
import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .schemas import Exposure
from .tools.geo import bbox_around, haversine_km

_DATA = Path(__file__).resolve().parent / "data" / "settlements.csv"

#: Largest settlements named on an exposure. Three is what fits on a map popup
#: and is enough to let a reader place the circle without a basemap.
TOWNS_NAMED = 3


@dataclass(frozen=True, slots=True)
class Settlement:
    name: str
    country: str
    latitude: float
    longitude: float
    population: int


@dataclass(frozen=True, slots=True)
class _Table:
    """Settlements sorted by latitude, with the latitudes alongside for bisecting.

    Sorting once means a lookup touches only the band of rows within the radius
    north and south, a few dozen out of four thousand, before any haversine is
    computed. `/hotspots` runs this for every hotspot on every call, so the
    difference is worth the ten lines.
    """

    settlements: tuple[Settlement, ...]
    latitudes: tuple[float, ...]


@lru_cache(maxsize=4)
def _load(path: Path) -> _Table:
    """Read the table once per path. Keyed by path so a test can point elsewhere."""
    if not path.exists():
        return _Table((), ())
    with path.open(encoding="utf-8") as handle:
        lines = (line for line in handle if not line.startswith("#"))
        parsed = [
            Settlement(
                name=row["name"],
                country=row["country"],
                latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),
                population=int(row["population"]),
            )
            for row in csv.DictReader(lines)
        ]
    parsed.sort(key=lambda s: s.latitude)
    return _Table(tuple(parsed), tuple(s.latitude for s in parsed))


def settlements_within(latitude: float, longitude: float, radius_km: float) -> list[Settlement]:
    """Every settlement whose centre is within `radius_km`, largest first."""
    table = _load(_DATA)
    if not table.settlements or radius_km <= 0:
        return []

    west, south, east, north = bbox_around(latitude, longitude, radius_km)
    lo = bisect.bisect_left(table.latitudes, south)
    hi = bisect.bisect_right(table.latitudes, north)
    found = [
        s
        for s in table.settlements[lo:hi]
        if west <= s.longitude <= east
        and haversine_km(latitude, longitude, s.latitude, s.longitude) <= radius_km
    ]
    return sorted(found, key=lambda s: s.population, reverse=True)


def exposure_for(latitude: float, longitude: float, radius_km: float) -> Exposure | None:
    """The population in reach of a point, or None if the gazetteer has nobody there.

    None rather than zero on purpose. Zero would read as "nobody lives here",
    which the data cannot say: it only knows about places over 15,000 people, and
    an empty result means none of *those* are in reach.
    """
    found = settlements_within(latitude, longitude, radius_km)
    if not found:
        return None

    radius = round(radius_km, 3)
    count = len(found)
    return Exposure(
        population=sum(s.population for s in found),
        radius_km=radius,
        towns=[s.name for s in found[:TOWNS_NAMED]],
        settlement_count=count,
        basis=(
            f"Sum of the populations of {count} place{'s' if count != 1 else ''} whose "
            f"centre lies within {radius:g} km of the hotspot's centre, from the GeoNames "
            "gazetteer of places over 15,000 people (CC BY 4.0, geonames.org). A coarse "
            "figure, not a headcount: it reads low in the countryside, since villages "
            "under 15,000 people are not counted, and a city is counted whole when its "
            "centre is in reach."
        ),
    )
