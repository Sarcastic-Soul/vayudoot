"""Hotspot detection: turning independent observations into places on a map.

The unit of work of the system from v0.3 on. `docs/SCOPE.md` records why it
replaced the case; this module is where that decision is actually enforced, so
the two rules that matter are stated here next to the code that implements them.

**A hotspot does not need a citizen report to exist.** `clustering.py` groups
cases, so a cluster can only appear where somebody has already photographed
something. That is the failure mode of every crowdsourced platform: the map is
empty in every district nobody has reported from, which is most of India, and an
empty map is indistinguishable from clean air. Satellite detections and station
readings are converted to `Signal`s and seed hotspots on their own, so the map
has content nationally before a single citizen has opened the app. A citizen
photograph then does what only it can: it *upgrades* a hotspot, naming what is
actually burning and turning a thermal anomaly into a describable event that a
complaint can be written about.

**Corroboration gates publication, it does not merely annotate it.** A hotspot
supported only by public submissions has its confidence capped, however many
submissions there are. Fifteen coordinated false reports would otherwise
manufacture a hotspot, and a map that can be aimed at an address is a weapon
rather than a public good. Hard constraint 7 in `CLAUDE.md`.

Detection is derived on demand from stored signals, not stored itself, for the
same reason clusters are: membership changes whenever a signal arrives.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta

from . import grouping
from .config import settings
from .schemas import (
    Case,
    CaseStatus,
    Hotspot,
    PollutionType,
    Signal,
    SignalSource,
)

#: Cases that must not contribute a signal.
#:
#: `rejected` fell below the evidence stage's confidence floor, so the
#: photograph never supported anything. `withdrawn` was taken back by the
#: citizen and must not go on holding a place on a public map. `failed` died
#: mid-run and may carry no evidence at all.
#:
#: `resolved` and `acknowledged` stay in, matching `clustering.EXCLUDED_STATUSES`
#: and for the same reason: a problem that was fixed and came back is the
#: strongest pattern there is.
EXCLUDED_STATUSES: frozenset[CaseStatus] = frozenset(
    {CaseStatus.REJECTED, CaseStatus.WITHDRAWN, CaseStatus.FAILED}
)


#: The evidence stage's severity bands as magnitudes. Its vocabulary is the one
#: a person used to describe what they saw, so it is the right scale to keep;
#: this only puts it on the 0-1 axis the other sources report on.
SEVERITY_BANDS: dict[str, float] = {
    "low": 0.25,
    "moderate": 0.5,
    "high": 0.75,
    "severe": 1.0,
}

#: How much a ground station reading is believed. High and fixed: a
#: reference-grade instrument reporting a number is not in doubt, and whatever
#: uncertainty it has is not something this system can estimate. How *bad* the
#: reading is, which does vary, is the signal's magnitude instead.
STATION_RELIABILITY: float = 0.9

#: Fire radiative power, in megawatts, at which a detection counts as a fully
#: severe event. Agricultural residue fires commonly sit in the tens of MW and
#: large industrial or landfill fires run into the hundreds, so 100 MW is the
#: point past which more power does not change what an authority should do.
SATELLITE_FULL_POWER_MW: float = 100.0


def detect(signals: Iterable[Signal]) -> list[Hotspot]:
    """Every hotspot the signals support, strongest first.

    Ranked by confidence and then recency, because an operations view is read
    top-down and the question it answers is "what should I look at now".
    """
    found = [
        _summarise(members)
        for members in _groups(signals)
        if len(members) >= settings.vayudoot_hotspot_min_signals
    ]
    return sorted(found, key=lambda h: (h.confidence, h.last_seen_at), reverse=True)


def current() -> list[Hotspot]:
    """Every hotspot the instance can presently see.

    Reads both halves of the evidence: signals derived from the cases citizens
    submitted, and signals `scan.py` fetched from FIRMS and OpenAQ. The second
    half is what lets a hotspot appear in a district nobody has reported from,
    which was the whole point of the v0.3 reframe.

    Scanned signals are filtered by retention before they get here —
    `store.live_signals()` — so a fire from two months ago is history rather than
    a live hotspot. Case-derived signals are not filtered the same way: the
    hotspot window already decides what still groups, and a case is a durable
    record of a complaint rather than a transient observation.
    """
    from . import store

    return detect(_deduplicate([*_signals_from_cases(), *store.live_signals()]))


def _signals_from_cases() -> list[Signal]:
    from . import store

    built = (signal_from_case(case) for case in store.all_cases())
    return [signal for signal in built if signal is not None]


def _deduplicate(signals: Iterable[Signal]) -> list[Signal]:
    """One observation, counted once.

    The two sources can legitimately overlap — a scan stores a station signal,
    and a later scan of a nearby point returns the same station — and
    `store.save_signals` already dedupes on the way in. This guards the join
    rather than the store: a duplicate here would inflate a hotspot's signal
    count, and signal count drives both severity and the agreement term in
    confidence. Two copies of one reading must never read as two instruments
    agreeing.
    """
    seen: dict[str, Signal] = {}
    for signal in signals:
        seen.setdefault(signal.signal_id, signal)
    return list(seen.values())


# --------------------------------------------------------------------------- #
# Building signals from the sources
# --------------------------------------------------------------------------- #


def signal_from_case(case: Case) -> Signal | None:
    """A citizen's classified photograph as a signal, or None if it is not one.

    The evidence stage produces both numbers this needs and they must not be
    confused. Its `confidence` is how sure it is of what it saw, and becomes
    `strength`. Its `severity` is how bad what it saw is, and becomes
    `magnitude`. Feeding confidence into severity made one certain photograph of
    a small fire report as `severe`, which is the overclaim hard constraint 7
    exists to prevent.
    """
    if case.status in EXCLUDED_STATUSES or case.evidence is None:
        return None
    if case.evidence.pollution_type is PollutionType.UNCLEAR:
        return None

    return Signal(
        source=SignalSource.CITIZEN_REPORT,
        signal_id=case.case_id,
        latitude=case.report.latitude,
        longitude=case.report.longitude,
        observed_at=_aware(case.report.observed_at),
        pollution_type=case.evidence.pollution_type,
        strength=case.evidence.confidence,
        magnitude=SEVERITY_BANDS.get(case.evidence.severity, 0.5),
        summary=f"Citizen report: {case.evidence.pollution_type.value.replace('_', ' ')}",
    )


def signals_from_satellite(
    payload: dict, observed_fallback: datetime | None = None
) -> list[Signal]:
    """Thermal anomalies from a `find_satellite_fire_detections` payload.

    A detection is classified `unclear` on purpose. VIIRS sees heat, not fuel:
    calling a thermal anomaly crop residue burning because it is over farmland
    would be the system inventing the one fact a complaint turns on. A citizen
    photograph is what resolves it, which is precisely the division of labour
    this module exists to express.

    Strength comes from the satellite's own confidence rating, which VIIRS
    publishes as low/nominal/high or as a percentage depending on the product.
    """
    out: list[Signal] = []
    for detection in payload.get("detections", []):
        lat, lon = detection.get("latitude"), detection.get("longitude")
        if lat is None or lon is None:
            continue
        observed = _detection_time(detection) or observed_fallback or datetime.now(UTC)
        out.append(
            Signal(
                source=SignalSource.SATELLITE,
                signal_id=f"viirs:{lat:.5f}:{lon:.5f}:{observed.isoformat()}",
                latitude=float(lat),
                longitude=float(lon),
                observed_at=observed,
                pollution_type=PollutionType.UNCLEAR,
                strength=_satellite_strength(detection.get("confidence")),
                magnitude=_satellite_magnitude(detection.get("fire_radiative_power_mw")),
                summary=_satellite_summary(detection),
            )
        )
    return out


def signals_from_stations(payload: dict, observed_fallback: datetime | None = None) -> list[Signal]:
    """Readings above their standard, from a `get_nearby_air_quality` payload.

    Only readings that *exceed* a standard become signals. A station reporting
    clean air is evidence of nothing happening and must not put a dot on a map.
    That is not the same as the reading being useless: the corroboration stage
    reads a normal value too, because there it argues *against* a citizen's
    report, which is a different job from raising a hotspot.

    The signal is placed at the station, never at the coordinates that were
    searched from — `openaq.py` returns the instrument's own position for this
    reason. One station therefore contributes one signal per exceeding
    pollutant, which is correct: PM10 and NO2 over standard at one site are two
    observations of the same air.

    Thresholds are the Indian NAAQS 24-hour standards, in `config.py` with the
    notification cited. A reading at the standard is strength 0 and one at three
    times it is strength 1.
    """
    lat, lon = payload.get("latitude"), payload.get("longitude")
    if lat is None or lon is None:
        return []

    station_id = payload.get("station_id") or f"{float(lat):.4f},{float(lon):.4f}"
    station_name = payload.get("nearest_station") or "Ground station"

    out: list[Signal] = []
    for measurement in payload.get("measurements", []):
        parameter = measurement.get("parameter")
        strength = _exceedance(
            parameter, measurement.get("value"), measurement.get("unit")
        )
        if strength is None:
            continue
        observed = _parse_time(measurement.get("measured_at")) or (
            observed_fallback or datetime.now(UTC)
        )
        out.append(
            Signal(
                source=SignalSource.GROUND_STATION,
                signal_id=f"station:{station_id}:{parameter}",
                latitude=float(lat),
                longitude=float(lon),
                observed_at=observed,
                pollution_type=PollutionType.UNCLEAR,
                strength=STATION_RELIABILITY,
                magnitude=strength,
                summary=(
                    f"{station_name}: {parameter} {measurement.get('value')} "
                    f"{measurement.get('unit', '')}".strip()
                ),
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Grouping
# --------------------------------------------------------------------------- #


def _coords(signal: Signal) -> tuple[float, float]:
    return (signal.latitude, signal.longitude)


def _observed(signal: Signal) -> datetime:
    return _aware(signal.observed_at)


def _groups(signals: Iterable[Signal]) -> list[list[Signal]]:
    """Partition signals into same-event groups.

    Classified signals group only with their own pollution type, exactly as
    clusters do: a waste fire and a construction site at identical coordinates
    are two problems, and merging them would produce a complaint citing the wrong
    statute.

    Unclassified signals — every satellite and station one — are grouped
    separately and then offered to the classified groups they overlap. That is
    what makes a citizen photograph *upgrade* a satellite detection rather than
    sit beside it as a second dot.
    """
    radius = settings.vayudoot_hotspot_radius_km
    max_gap = timedelta(days=settings.vayudoot_hotspot_window_days)

    classified: dict[PollutionType, list[Signal]] = {}
    unclassified: list[Signal] = []
    for signal in signals:
        if signal.pollution_type is PollutionType.UNCLEAR:
            unclassified.append(signal)
        else:
            classified.setdefault(signal.pollution_type, []).append(signal)

    groups: list[list[Signal]] = []
    for same_type in classified.values():
        groups.extend(
            grouping.link(
                same_type,
                position=_coords,
                timestamp=_observed,
                radius_km=radius,
                max_gap=max_gap,
            )
        )

    leftover: list[Signal] = []
    for signal in unclassified:
        host = _nearest_group(signal, groups, radius, max_gap)
        if host is None:
            leftover.append(signal)
        else:
            host.append(signal)

    groups.extend(
        grouping.link(
            leftover,
            position=_coords,
            timestamp=_observed,
            radius_km=radius,
            max_gap=max_gap,
        )
    )
    return groups


def _nearest_group(
    signal: Signal, groups: Sequence[list[Signal]], radius_km: float, max_gap: timedelta
) -> list[Signal] | None:
    """The classified group this unclassified signal belongs to, if any."""
    from .tools.geo import haversine_km

    best: list[Signal] | None = None
    best_km = radius_km
    for group in groups:
        if abs(_observed(signal) - max(_observed(s) for s in group)) > max_gap:
            continue
        centre_lat, centre_lon = grouping.centroid(group, _coords)
        km = haversine_km(signal.latitude, signal.longitude, centre_lat, centre_lon)
        if km <= best_km:
            best, best_km = group, km
    return best


# --------------------------------------------------------------------------- #
# Summarising
# --------------------------------------------------------------------------- #


def hotspot_id(pollution_type: PollutionType, seed_signal_id: str) -> str:
    """A stable identity, so a hotspot can be linked to and cited as it grows.

    Derived from the pollution type and the earliest signal, both fixed for the
    life of the group: later signals join it, they never displace its seed. Same
    property and same reasoning as `clustering.cluster_id`.
    """
    digest = hashlib.sha256(f"{pollution_type.value}:{seed_signal_id}".encode()).hexdigest()
    return f"VDH-{digest[:8].upper()}"


def _summarise(members: Sequence[Signal]) -> Hotspot:
    ordered = sorted(members, key=_observed)
    seed = ordered[0]
    centre_lat, centre_lon = grouping.centroid(ordered, _coords)

    pollution_type = next(
        (s.pollution_type for s in ordered if s.pollution_type is not PollutionType.UNCLEAR),
        PollutionType.UNCLEAR,
    )

    source_counts: dict[SignalSource, int] = {}
    for signal in ordered:
        source_counts[signal.source] = source_counts.get(signal.source, 0) + 1

    corroborated = any(s.is_independent for s in ordered)
    first, last = _observed(ordered[0]), _observed(ordered[-1])

    return Hotspot(
        hotspot_id=hotspot_id(pollution_type, seed.signal_id),
        pollution_type=pollution_type,
        centre_latitude=centre_lat,
        centre_longitude=centre_lon,
        radius_km=_radius(ordered, centre_lat, centre_lon),
        confidence=_confidence(ordered, corroborated),
        severity=_severity(ordered),
        corroborated=corroborated,
        signal_count=len(ordered),
        source_counts=source_counts,
        first_seen_at=first,
        last_seen_at=last,
        span_days=max((last - first).days, 0),
        case_ids=[s.signal_id for s in ordered if s.source is SignalSource.CITIZEN_REPORT],
        signals=list(ordered),
    )


def _radius(members: Sequence[Signal], centre_lat: float, centre_lon: float) -> float:
    """How far the signals actually spread, floored at the configured minimum.

    The floor is not cosmetic. A hotspot drawn tightly around one building is a
    public accusation against whoever occupies it, whether or not a name appears
    anywhere on the page. Hard constraint 7.
    """
    from .tools.geo import haversine_km

    spread = max(haversine_km(s.latitude, s.longitude, centre_lat, centre_lon) for s in members)
    return round(max(spread, settings.vayudoot_hotspot_min_radius_km), 3)


def _confidence(members: Sequence[Signal], corroborated: bool) -> float:
    """How much the system believes a hotspot is real.

    Built from the strongest signal, lifted by agreement between *distinct
    sources* rather than by volume. Ten photographs of one fire are one fire
    seen ten times; a photograph plus a satellite detection plus a station
    exceedance is three instruments that cannot all be wrong the same way.

    Uncorroborated hotspots are then capped outright. This is the line hard
    constraint 7 draws, and it is a cap rather than a penalty on purpose: no
    quantity of public submissions can climb past it, because quantity is
    exactly what a coordinated campaign can manufacture.
    """
    strongest = max(s.strength for s in members)
    distinct_sources = len({s.source for s in members})
    agreement = min(0.15 * (distinct_sources - 1), 0.3)
    confidence = min(strongest + agreement, 1.0)

    if not corroborated:
        confidence = min(confidence, settings.vayudoot_hotspot_uncorroborated_cap)
    return round(confidence, 3)


def _severity(members: Sequence[Signal]) -> str:
    """How bad it looks, from the strongest signal and how persistent it is.

    Reads `magnitude`, never `strength`. The two are routinely far apart — a
    single clear photograph of a small fire is high confidence and low severity,
    and a month of marginal station exceedances is the reverse — and an earlier
    version of this function read `strength`, which made every confident report
    `severe` regardless of what it showed.
    """
    largest = max(s.magnitude for s in members)
    persistence = min(len(members) / 10, 0.2)
    # Rounded before banding, not for tidiness: 0.7 + 0.2 is 0.8999999999999999
    # in binary floating point, so an unrounded comparison drops a hotspot a
    # whole band on a representation artefact.
    score = round(largest + persistence, 6)

    if score >= 0.9:
        return "severe"
    if score >= 0.7:
        return "high"
    if score >= 0.45:
        return "moderate"
    return "low"


# --------------------------------------------------------------------------- #
# Source payload parsing
# --------------------------------------------------------------------------- #


def _satellite_strength(confidence: object) -> float:
    """VIIRS confidence to a 0-1 strength.

    The product publishes either a nominal band or a percentage depending on the
    source, so both are handled rather than assuming one.
    """
    if confidence is None:
        return 0.5
    text = str(confidence).strip().lower()
    named = {"l": 0.3, "low": 0.3, "n": 0.6, "nominal": 0.6, "h": 0.85, "high": 0.85}
    if text in named:
        return named[text]
    try:
        return max(0.0, min(float(text) / 100, 1.0))
    except ValueError:
        return 0.5


def _satellite_magnitude(power: object) -> float:
    """Fire radiative power to a 0-1 magnitude.

    FRP is the one genuinely physical magnitude any source here reports: it is
    how much energy the fire is radiating, which is as close to "how big is it"
    as an instrument gets. A detection with no FRP published falls back to the
    middle rather than to zero, because absent is not small.
    """
    if power is None:
        return 0.5
    try:
        watts = float(power)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.5
    return round(max(0.0, min(watts / SATELLITE_FULL_POWER_MW, 1.0)), 3)


def _satellite_summary(detection: dict) -> str:
    power = detection.get("fire_radiative_power_mw")
    if power:
        return f"Satellite thermal detection, {power} MW radiative power"
    return "Satellite thermal detection"


def _detection_time(detection: dict) -> datetime | None:
    """FIRMS publishes the date and the UTC time of acquisition separately."""
    date = detection.get("acquired_date")
    if not date:
        return None
    raw = str(detection.get("acquired_time_utc") or "0").zfill(4)
    try:
        return datetime.fromisoformat(str(date)).replace(
            hour=int(raw[:2]), minute=int(raw[2:4]), tzinfo=UTC
        )
    except ValueError:
        return None


def exceedance_strength(
    parameter: object, value: object, unit: object = None
) -> float | None:
    """Public name for `_exceedance`.

    A citizen sensor reading arrives through the API rather than through a
    payload from a tool, but the question asked of it is identical: how far past
    its standard is this, and is it past it at all. Two implementations of that
    would be two places for the standards to disagree.
    """
    return _exceedance(parameter, value, unit)


def _exceedance(parameter: object, value: object, unit: object = None) -> float | None:
    """How far past its standard a reading is, or None if it is not past it.

    Returns 0.0 at the standard and 1.0 at three times it. A reading below the
    standard returns None rather than 0, because a clean reading is not a weak
    signal — it is not a signal at all.

    The reading is converted to µg/m³ first. This is not defensive tidiness: the
    standards table once held CO's 2 mg/m³ verbatim while OpenAQ reported CO in
    µg/m³, and a real reading of 1680 µg/m³ — comfortably below the standard —
    scored as a maximum-severity exceedance. A thousand-fold unit error is
    invisible in a number and glaring on a map.
    """
    if parameter is None or value is None:
        return None
    standard = settings.naaqs_standards.get(str(parameter).lower())
    if not standard:
        return None
    try:
        reading = _micrograms(float(value), unit)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if reading is None or reading < standard:
        return None
    return round(min((reading - standard) / (2 * standard), 1.0), 3)


def _micrograms(value: float, unit: object) -> float | None:
    """A reading in µg/m³, whatever unit it arrived in.

    An unrecognised unit returns None rather than being assumed. Guessing wrong
    is how a thousand-fold error reaches the map; refusing to guess costs one
    signal.
    """
    if unit is None:
        # Most sources, including OpenAQ, report µg/m³ and many omit the unit
        # entirely. Assuming the common case is reasonable; assuming a *named*
        # unit means something other than what it says is not.
        return value

    text = str(unit).strip().lower().replace("μ", "µ")
    if text in {"µg/m³", "ug/m3", "µg/m3", "ugm3", "ug/m^3", "µg/m^3", ""}:
        return value
    if text in {"mg/m³", "mg/m3", "mgm3", "mg/m^3"}:
        return value * 1000
    return None


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return _aware(datetime.fromisoformat(str(value)))
    except ValueError:
        return None


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
