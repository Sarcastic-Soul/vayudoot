"""The periodic scan: going and fetching the evidence the map is made of.

`hotspots.py` can already raise a hotspot from a satellite detection or a
station exceedance, with no citizen involved. Nothing, however, was going and
getting those detections, so in practice the map only ever showed what somebody
had photographed — which is the failure mode the v0.3 reframe exists to end, and
which `hotspots.current` says plainly in its own docstring. This module is the
missing half: it calls the same FIRMS and OpenAQ tools the corroboration graph
uses, converts what comes back with the builders already in `hotspots.py`, and
puts the result in the store.

Three decisions are worth stating here, because each of them is a thing somebody
would otherwise reasonably change.

**Nothing here starts a loop.** Importing this module has no effect; something
has to call `run_once`. An unattended process calling two external APIs on a
timer should be switched on by whoever is watching the quota, not by an import,
which is also why `vayudoot_scan_enabled` is off by default and is checked in
`run_once` rather than anywhere deeper — a person asking for a single scan by
hand is not the thing the flag is guarding against.

**No model is involved.** The whole scan is two HTTP calls per point and some
arithmetic. That is deliberate: this is the one part of the system that runs
unattended and repeatedly, and hard constraint 5 says inference is the only
running cost, so the repeating part is the last place to spend it. Reading a
photograph and drafting a complaint still need judgement; fetching a CSV of
thermal anomalies does not.

**A failed source degrades, it does not fail the scan.** Tools return
`{"error": ...}` rather than raising, and a scan that gave up because OpenAQ was
briefly down would throw away the satellite detections it already had.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from . import hotspots, store
from .config import settings
from .schemas import Signal
from .tools import find_satellite_fire_detections, get_nearby_air_quality
from .tools.geo import haversine_km


def scan_point(
    latitude: float,
    longitude: float,
    radius_km: float | None = None,
    days: int | None = None,
) -> list[Signal]:
    """Every signal the independent sources report near one place.

    Both sources are asked, and each is converted by the builder in
    `hotspots.py` that already knows how to read its payload. Writing another
    converter here would be the same judgements made twice and would drift the
    first time FIRMS changed a column name.

    Nothing is stored: this is the piece a diagnostic or a test can call to see
    what one location returns. `scan_points` is what persists.
    """
    signals, _ = _scan_point(latitude, longitude, radius_km, days)
    return signals


def scan_points(points: Iterable[tuple[float, float]]) -> int:
    """Scan several places, store what comes back, and report what was new.

    Everything is collected before a single save, so the deduplication in
    `store.save_signals` sees the whole pass at once. That matters because scan
    points overlap by design — two cases 10 km apart are both scanned at a 50 km
    radius — and the same fire arriving from two directions is one fire.
    """
    new, _, _ = _scan_and_save(points)
    return new


def run_once() -> dict:
    """One full pass over the places this instance has reason to watch.

    Returns a small summary rather than the signals themselves, because the
    caller is a scheduler or an operator and the question either of them has is
    whether the pass did anything and whether anything went wrong.

    `errors` is a list of sentences, not a count. A scan that quietly returned
    zero signals because a key expired looks exactly like a scan of clean air,
    and those are the two states that most need telling apart.
    """
    if not settings.vayudoot_scan_enabled:
        # Reported rather than raised: a scheduler calling a disabled scan is a
        # configuration state, not a fault, and it should be able to say so.
        return {
            "enabled": False,
            "points_scanned": 0,
            "signals_found": 0,
            "signals_new": 0,
            "errors": [],
        }

    points = scan_targets()
    new, found, errors = _scan_and_save(points)
    return {
        "enabled": True,
        "points_scanned": len(points),
        "signals_found": found,
        "signals_new": new,
        "errors": errors,
    }


def scan_targets() -> list[tuple[float, float]]:
    """The places worth spending a scan on.

    Two sources, both of them places this instance already knows somebody cares
    about: the coordinates of every stored case, and the waypoints of every
    configured economic corridor. Corridors are what give the scan reach beyond
    where citizens have reported — they cross states nobody has submitted from,
    which is most of the country.

    Cases of every status are included, withdrawn and rejected ones too. A scan
    point is an area to point public instruments at, not a claim about a report:
    dropping one would only make the map blind at a coordinate somebody once
    thought was worth flagging.
    """
    points: list[tuple[float, float]] = []
    for case in store.all_cases():
        points.append((case.report.latitude, case.report.longitude))
    points.extend(_corridor_waypoints())
    return _thinned(points)


# --------------------------------------------------------------------------- #
# Scanning
# --------------------------------------------------------------------------- #


def _scan_point(
    latitude: float,
    longitude: float,
    radius_km: float | None,
    days: int | None,
) -> tuple[list[Signal], list[str]]:
    """One point's signals, and a sentence for each source that failed.

    The public `scan_point` drops the errors because a caller looking at one
    location can see an empty list for itself; `run_once` keeps them because
    nobody is watching it.
    """
    radius = settings.vayudoot_scan_radius_km if radius_km is None else radius_km
    days_back = settings.vayudoot_scan_days if days is None else days
    fallback = datetime.now(UTC)

    signals: list[Signal] = []
    errors: list[str] = []

    satellite = _call(
        "FIRMS",
        errors,
        lambda: find_satellite_fire_detections(
            latitude=latitude, longitude=longitude, radius_km=radius, days=days_back
        ),
    )
    if satellite is not None:
        signals.extend(hotspots.signals_from_satellite(satellite, observed_fallback=fallback))

    stations = _call(
        "OpenAQ",
        errors,
        lambda: get_nearby_air_quality(latitude=latitude, longitude=longitude, radius_km=radius),
    )
    if stations is not None:
        signals.extend(hotspots.signals_from_stations(stations, observed_fallback=fallback))

    return signals, errors


def _call(source: str, errors: list[str], fetch) -> dict | None:
    """Run one source's tool and return its payload, or None if it failed.

    Tools return `{"error": ...}` and do not raise, which is the project's
    convention and is what makes this a two-line check rather than a handler.
    The exception clause is there anyway because this is the one path that runs
    unattended: a tool that grew a new failure mode must cost this scan one
    source for one pass, not the pass itself.
    """
    try:
        payload = fetch()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{source} raised: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append(f"{source} returned {type(payload).__name__}, not a payload")
        return None
    if payload.get("error"):
        errors.append(f"{source}: {payload['error']}")
        return None
    return payload


def _scan_and_save(
    points: Iterable[tuple[float, float]],
) -> tuple[int, int, list[str]]:
    """Scan every point, save once, and report (new, found, errors)."""
    signals: list[Signal] = []
    errors: list[str] = []
    for latitude, longitude in points:
        found, failures = _scan_point(latitude, longitude, None, None)
        signals.extend(found)
        errors.extend(failures)
    return store.save_signals(signals), len(signals), errors


# --------------------------------------------------------------------------- #
# Choosing where to look
# --------------------------------------------------------------------------- #


def _thinned(points: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    """Drop points close enough to another that they would fetch the same data.

    Each scan covers a radius, so two points half that far apart are largely the
    same square of sky and the same nearest station. Keeping both spends two
    external requests to learn one thing, which on a free tier is the cost that
    limits how often the scan can run at all.
    """
    spacing = settings.vayudoot_scan_radius_km / 2
    kept: list[tuple[float, float]] = []
    for latitude, longitude in points:
        if any(haversine_km(latitude, longitude, lat, lon) < spacing for lat, lon in kept):
            continue
        kept.append((latitude, longitude))
    return kept


def _corridor_waypoints() -> list[tuple[float, float]]:
    """Waypoints of every configured corridor, or nothing if there are none.

    Held together loosely on purpose. Corridors are data loaded from a JSON file
    and the module that loads them is not a dependency this one should fail
    without: a deployment that has not defined any corridors still has a working
    scan over its cases, and that is the more important of the two.
    """
    try:
        from . import corridors
    except ImportError:
        return []

    loader = next(
        (
            getattr(corridors, name)
            for name in ("all_corridors", "load_corridors")
            if hasattr(corridors, name)
        ),
        None,
    )
    if loader is None:
        return []

    try:
        defined = loader()
    except Exception:  # noqa: BLE001
        return []

    points: list[tuple[float, float]] = []
    for corridor in defined:
        for waypoint in getattr(corridor, "waypoints", []):
            try:
                latitude, longitude = float(waypoint[0]), float(waypoint[1])
            except (TypeError, ValueError, IndexError):
                continue
            points.append((latitude, longitude))
    return points
