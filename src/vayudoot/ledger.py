"""The forecast ledger: every forecast this node makes, checked against what happened.

The forecast is Gemini reasoning over public data, and until this module its
accuracy had never been measured. A forecast nobody scores is a claim nobody can
check, and hard constraint 7 exists because people act on these. So every
forecast served — a point, or each waypoint of a corridor — is written down when
it is made, and scored once its window has passed.

**Prospective, so nothing leaks.** The record is written at the moment the
forecast is served, with the risk band, the window, and the no-model baseline
fetched at the same moment. Scoring only ever adds an outcome beside it; it
cannot change what was predicted. A backtest can fool itself with data that did
not exist yet; a ledger written in advance cannot. `scripts/forecast_backtest.py`
is the retrospective check, and `docs/forecast-evaluation.md` says how far it can
be trusted.

**Scoring spends no model call.** It reads OpenAQ reference stations near the
location over the window and maps the worst 24-hour mean to the same four bands
the forecast uses. It runs from the scan timer or when somebody reads the ledger,
at most once per `vayudoot_forecast_scoring_interval_minutes`, never once per
request.

**Unscorable is an answer, not a failure.** Where no reference station is close
enough, or the stations reported too few hours, the forecast is marked
unscorable and is never counted as right or wrong. Counting it either way would
make the score say something about the station network instead of the forecaster.

**Always beside two baselines.** A hit rate on its own means nothing in Delhi in
November, where "high" is right most days. Each outcome also records what
persistence (yesterday's observed band, carried forward) and the raw Open-Meteo
CAMS number (mapped to a band with no model) would have said, and the skill
summary compares the forecaster against each on exactly the same forecasts.
"""

from __future__ import annotations

import logging
import math
import statistics
import threading
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx

from . import store
from .agents.forecast import FORECASTER_VERSION, RISK_ORDER, prompt_sha256
from .config import settings
from .schemas import (
    AirQualityForecast,
    BandScores,
    BaselineComparison,
    ForecastOutcome,
    ForecastRecord,
    ForecastSkill,
)

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# The band mapping. The only place observed numbers become risk bands.
# --------------------------------------------------------------------------- #

#: Upper limits of the low, elevated and high bands, as a 24-hour mean in µg/m³.
#: Anything above the last is severe.
#:
#: The forecast prompt does not define its bands with numbers. It says only that
#: severe is for "the forecast far past the standard", and the tool the model
#: reads prints that standard beside every number it returns: the Indian 24-hour
#: NAAQS, 60 µg/m³ for PM2.5 and 100 for PM10. The mapping is built outward from
#: that one anchor:
#:
#: * low      — within the standard the model was shown (AQI Good and
#:              Satisfactory).
#: * elevated — over it, up to the AQI's Poor category (PM2.5 up to 120, which
#:              is twice the standard).
#: * high     — the AQI's Very Poor category.
#: * severe   — the AQI's Severe category, PM2.5 above 250: four times the
#:              standard, which is what "far past" has to mean if it means
#:              anything.
#:
#: Every boundary is a breakpoint of the CPCB National Air Quality Index (2014),
#: so a reader can check a band against a published AQI bulletin. The bands are
#: still this system's own and are never presented as the AQI's categories.
#:
#: The 24-hour mean is the averaging period the standard and the AQI breakpoints
#: are both defined over. Hourly peaks run far higher and would put every Delhi
#: evening in "severe".
BAND_LIMITS: dict[str, tuple[float, float, float]] = {
    "pm25": (60.0, 120.0, 250.0),
    "pm10": (100.0, 350.0, 430.0),
}

BAND_BASIS = (
    "Worst 24-hour mean over the forecast window, from reference stations within "
    "25 km. PM2.5: low up to 60 µg/m³ (the Indian 24-hour standard), elevated up to "
    "120, high up to 250, severe above 250. PM10 where no PM2.5 is reported: 100, "
    "350, 430. Boundaries are CPCB National AQI breakpoints; the bands are this "
    "system's, not the AQI's."
)


def band_for(pollutant: str, value: float) -> str:
    """The risk band a 24-hour mean falls in. Boundaries belong to the lower band."""
    for band, limit in zip(RISK_ORDER, BAND_LIMITS[pollutant], strict=False):
        if value <= limit:
            return band
    return RISK_ORDER[-1]


def band_definitions() -> list[dict]:
    """The bands as data, for the forecaster spec a node publishes."""
    out = []
    lower = {"pm25": 0.0, "pm10": 0.0}
    for index, band in enumerate(RISK_ORDER):
        row: dict = {"risk": band}
        for pollutant, limits in BAND_LIMITS.items():
            upper = limits[index] if index < len(limits) else None
            row[f"{pollutant}_from"] = lower[pollutant]
            row[f"{pollutant}_to"] = upper
            if upper is not None:
                lower[pollutant] = upper
        out.append(row)
    return out


# --------------------------------------------------------------------------- #
# What counts as an observation
# --------------------------------------------------------------------------- #

#: How close a reference station must be to score a forecast. The forecast's own
#: inputs cannot resolve anything finer: the CAMS global model behind the
#: Open-Meteo pollutant forecast works on a grid of roughly 40 km. 25 km is also
#: the cap the project's OpenAQ tool already uses. Past it, the station is
#: describing somewhere else.
SCORING_RADIUS_KM = 25.0

#: Hours of data a 24-hour mean needs. CPCB's own AQI requires at least 16 of 24
#: before it will publish a daily figure; using the same rule means a day this
#: ledger scores is a day the authority would have scored too.
MIN_HOURS_PER_DAY = 16

#: How many stations to average, nearest first. One station is a street corner;
#: the median of three is a neighbourhood, and resists one instrument reporting
#: nonsense. More costs OpenAQ requests without changing the answer.
MAX_STATIONS = 3

#: An hourly value outside this range is an instrument fault, not air. CPCB
#: stations report 999 and above as an error or saturation code, and zero or
#: below as a fault.
PLAUSIBLE_RANGE = (0.0, 999.0)

#: How long after a window closes before it is scored. OpenAQ ingests CPCB data
#: within an hour or two; six leaves room for a late upload.
SETTLE_HOURS = 6

#: How long to keep retrying a window whose stations reported too few hours.
#: Past this the data is not coming, and the forecast is unscorable.
GIVE_UP_HOURS = 72

_OPENAQ = "https://api.openaq.org/v3"
_OPEN_METEO_AQ = "https://air-quality-api.open-meteo.com/v1/air-quality"


class StationSource:
    """OpenAQ v3, the two calls scoring needs. Raises on HTTP failure.

    A class so the backtest can put a disk cache in front of it and the tests a
    fixture, without either knowing how OpenAQ pages its results.
    """

    def locations(self, latitude: float, longitude: float, radius_km: float) -> list[dict]:
        response = httpx.get(
            f"{_OPENAQ}/locations",
            params={
                "coordinates": f"{latitude},{longitude}",
                "radius": int(radius_km * 1000),
                "limit": 100,
            },
            headers={"X-API-Key": settings.openaq_api_key},
            timeout=30,
        )
        response.raise_for_status()
        return response.json().get("results", [])

    def hours(self, sensor_id: int, start: datetime, end: datetime) -> list[dict]:
        rows: list[dict] = []
        for page in range(1, 4):
            response = httpx.get(
                f"{_OPENAQ}/sensors/{sensor_id}/hours",
                params={
                    "datetime_from": start.isoformat(),
                    "datetime_to": end.isoformat(),
                    "limit": 1000,
                    "page": page,
                },
                headers={"X-API-Key": settings.openaq_api_key},
                timeout=30,
            )
            response.raise_for_status()
            batch = response.json().get("results", [])
            rows.extend(batch)
            if len(batch) < 1000:
                break
        return rows


@dataclass
class Observation:
    """What the stations recorded over one window, before it is set beside a forecast.

    `retryable` marks a shortfall that time may fix: a transient HTTP error, or
    too few hours reported so far. "No station within 25 km" never is.
    """

    status: str  # "scored" or "unscorable"
    reason: str = ""
    retryable: bool = False
    pollutant: str | None = None
    value: float | None = None
    days_covered: int = 0
    days_total: int = 0
    stations: list[str] = field(default_factory=list)
    persistence_value: float | None = None


def _parse(moment: object) -> datetime | None:
    if not isinstance(moment, str) or not moment:
        return None
    try:
        parsed = datetime.fromisoformat(moment)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _hour(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def hourly_series(rows: Iterable[dict]) -> dict[datetime, float]:
    """OpenAQ hour rows as {UTC hour: value}, faults and flagged hours dropped.

    Indian stations report on the half hour (05:00 IST is 23:30 UTC), so each
    value is filed under the hour nearest the middle of the period it covers.
    """
    series: dict[datetime, float] = {}
    low, high = PLAUSIBLE_RANGE
    for row in rows:
        if (row.get("flagInfo") or {}).get("hasFlags"):
            continue
        value = row.get("value")
        if not isinstance(value, int | float) or not low < value < high:
            continue
        period = row.get("period") or {}
        start = _parse((period.get("datetimeFrom") or {}).get("utc"))
        end = _parse((period.get("datetimeTo") or {}).get("utc")) or start
        if start is None or end is None:
            continue
        middle = start + (end - start) / 2
        series[_hour(middle + timedelta(minutes=30))] = float(value)
    return series


def median_by_hour(series: list[dict[datetime, float]]) -> dict[datetime, float]:
    """One series from several stations: the median of whoever reported each hour."""
    hours = sorted({hour for one in series for hour in one})
    return {
        hour: statistics.median([one[hour] for one in series if hour in one]) for hour in hours
    }


def day_means(
    series: dict[datetime, float], start: datetime, hours: int
) -> list[float | None]:
    """The window cut into consecutive 24-hour days from `start`, each one's mean.

    A day with fewer than `MIN_HOURS_PER_DAY` hours (pro rata, for a short last
    day) has no mean and is None.
    """
    start = _hour(start)
    days = max(1, math.ceil(hours / 24))
    means: list[float | None] = []
    for index in range(days):
        day_start = start + timedelta(hours=24 * index)
        length = min(24, hours - 24 * index)
        values = [
            series[day_start + timedelta(hours=h)]
            for h in range(length)
            if day_start + timedelta(hours=h) in series
        ]
        needed = math.ceil(MIN_HOURS_PER_DAY * length / 24)
        means.append(statistics.fmean(values) if len(values) >= needed else None)
    return means


def worst_day(
    series: dict[datetime, float], start: datetime, hours: int
) -> tuple[float | None, int, int]:
    """The worst daily mean in the window, with how many days could be measured.

    A forecast's band speaks to the worst of its window, so the observation it
    is scored against is the worst day. At least half the days must be measured:
    a three-day window judged on its one surviving day could miss the day that
    mattered, and would be scoring the gap rather than the forecast.
    """
    means = day_means(series, start, hours)
    measured = [m for m in means if m is not None]
    if not measured or len(measured) * 2 < len(means):
        return None, len(measured), len(means)
    return max(measured), len(measured), len(means)


def _active(location: dict, start: datetime, end: datetime) -> bool:
    """A reference monitor that was reporting at some point over the span.

    Low-cost sensors are left out on purpose. A forecast is scored against the
    instrument an authority would recognise, for the reason a citizen sensor
    cannot corroborate a hotspot on its own.
    """
    if location.get("isMonitor") is False:
        return False
    first = _parse((location.get("datetimeFirst") or {}).get("utc"))
    last = _parse((location.get("datetimeLast") or {}).get("utc"))
    if first is not None and first > end:
        return False
    return not (last is not None and last < start)


def observe(
    latitude: float,
    longitude: float,
    start: datetime,
    hours: int,
    source: StationSource | None = None,
) -> Observation:
    """What reference stations near a place recorded over a window. Never raises.

    PM2.5 is preferred, as the pollutant the forecast leads with; PM10 is used
    only where no nearby station reported PM2.5 at all. The 24 hours before the
    window are fetched in the same request, for the persistence baseline.
    """
    source = source or StationSource()
    start = _hour(start)
    end = start + timedelta(hours=hours)
    before = start - timedelta(hours=24)
    try:
        locations = source.locations(latitude, longitude, SCORING_RADIUS_KM)
    except Exception as exc:  # noqa: BLE001 - a scoring pass must not die on one fetch
        return Observation("unscorable", f"OpenAQ could not be read: {exc}", retryable=True)

    nearby = sorted(
        (loc for loc in locations if _active(loc, before, end)),
        key=lambda loc: loc.get("distance") or 0.0,
    )
    if not nearby:
        return Observation(
            "unscorable",
            f"No reference station within {SCORING_RADIUS_KM:.0f} km was reporting.",
        )

    failures: list[str] = []
    for pollutant in ("pm25", "pm10"):
        series: list[dict[datetime, float]] = []
        labels: list[str] = []
        for location in nearby:
            if len(series) >= MAX_STATIONS:
                break
            sensors = sorted(
                (
                    s["id"]
                    for s in location.get("sensors") or []
                    if (s.get("parameter") or {}).get("name") == pollutant
                ),
                reverse=True,  # OpenAQ's newer sensor ids carry the current data
            )
            for sensor_id in sensors:
                try:
                    one = hourly_series(source.hours(sensor_id, before, end))
                except Exception as exc:  # noqa: BLE001
                    failures.append(str(exc))
                    continue
                if one:
                    series.append(one)
                    km = (location.get("distance") or 0.0) / 1000
                    labels.append(f"{location.get('name', 'station')} ({km:.1f} km)")
                    break
        if not series:
            continue

        combined = median_by_hour(series)
        value, covered, total = worst_day(combined, start, hours)
        persistence = day_means(combined, before, 24)[0]
        if value is None:
            return Observation(
                "unscorable",
                f"Only {covered} of {total} days had {MIN_HOURS_PER_DAY} hours of "
                f"{'PM2.5' if pollutant == 'pm25' else 'PM10'} reported.",
                retryable=True,
                pollutant=pollutant,
                days_covered=covered,
                days_total=total,
                stations=labels,
            )
        return Observation(
            "scored",
            pollutant=pollutant,
            value=round(value, 1),
            days_covered=covered,
            days_total=total,
            stations=labels,
            persistence_value=None if persistence is None else round(persistence, 1),
        )

    if failures:
        return Observation(
            "unscorable", f"Station data could not be read: {failures[0]}", retryable=True
        )
    return Observation(
        "unscorable",
        f"No station within {SCORING_RADIUS_KM:.0f} km reported PM2.5 or PM10 in the window.",
        retryable=True,
    )


def score(record: ForecastRecord, observation: Observation) -> ForecastOutcome:
    """Set an observation beside the forecast it judges. Pure."""
    if observation.status != "scored" or observation.value is None:
        return ForecastOutcome(
            status="unscorable",
            reason=observation.reason,
            pollutant=observation.pollutant,  # type: ignore[arg-type]
            stations=observation.stations,
            days_covered=observation.days_covered,
            days_total=observation.days_total,
        )

    pollutant = observation.pollutant or "pm25"
    observed = band_for(pollutant, observation.value)
    persistence = observation.persistence_value
    cams = record.cams_worst_day.get(pollutant)
    return ForecastOutcome(
        status="scored",
        pollutant=pollutant,  # type: ignore[arg-type]
        observed_value=observation.value,
        observed_band=observed,  # type: ignore[arg-type]
        band_error=RISK_ORDER.index(record.risk) - RISK_ORDER.index(observed),
        stations=observation.stations,
        days_covered=observation.days_covered,
        days_total=observation.days_total,
        persistence_value=persistence,
        persistence_band=None if persistence is None else band_for(pollutant, persistence),  # type: ignore[arg-type]
        cams_value=None if cams is None else round(cams, 1),
        cams_band=None if cams is None else band_for(pollutant, cams),  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- #
# Skill
# --------------------------------------------------------------------------- #


def band_scores(pairs: Iterable[tuple[str, str]]) -> BandScores:
    """Exact and within-one-band agreement, and the confusion matrix.

    `pairs` is (called band, observed band). The matrix is keyed observed band
    first, then called band, and every cell is present so a reader can see the
    zeros.
    """
    confusion = {observed: {called: 0 for called in RISK_ORDER} for observed in RISK_ORDER}
    exact = within = total = 0
    for called, observed in pairs:
        confusion[observed][called] += 1
        gap = abs(RISK_ORDER.index(called) - RISK_ORDER.index(observed))
        total += 1
        exact += gap == 0
        within += gap <= 1
    return BandScores(
        scored=total,
        exact=exact,
        within_one=within,
        exact_rate=round(exact / total, 3) if total else None,
        within_one_rate=round(within / total, 3) if total else None,
        confusion=confusion,
    )


#: Below this many scored forecasts, every rate is an anecdote. Thirty gives a
#: 95% interval of roughly plus or minus 18 points on a rate near a half.
SMALL_SAMPLE = 30


def skill(
    records: Iterable[ForecastRecord],
    days: int | None = None,
    now: datetime | None = None,
    current_only: bool = True,
) -> ForecastSkill:
    """A skill summary over the last `days`, for this forecaster or all of them.

    `current_only` keeps records made by the forecaster now running — same code
    revision, same prompt hash. A score earned by last month's prompt is not
    evidence about this one, and it is this one a peer is deciding whether to
    trust.
    """
    days = settings.vayudoot_forecast_skill_days if days is None else days
    now = now or datetime.now(UTC)
    since = now - timedelta(days=days)
    version, digest = FORECASTER_VERSION, prompt_sha256()

    window = [
        r
        for r in records
        if r.made_at >= since
        and (not current_only or (r.forecaster_version == version and r.prompt_sha256 == digest))
    ]
    scored = [r for r in window if r.outcome is not None and r.outcome.status == "scored"]
    unscorable = [r for r in window if r.outcome is not None and r.outcome.status == "unscorable"]

    def comparison(name: str, description: str, band_of) -> BaselineComparison:
        both = [r for r in scored if band_of(r) is not None]
        return BaselineComparison(
            name=name,  # type: ignore[arg-type]
            description=description,
            compared=len(both),
            baseline=band_scores((band_of(r), r.outcome.observed_band) for r in both),
            forecast=band_scores((r.risk, r.outcome.observed_band) for r in both),
        )

    caveat = (
        "Forecasts along one corridor, or made the same day, share weather and are not "
        "independent. Scored against reference stations within 25 km, which cover cities "
        "far better than countryside."
    )
    if len(scored) < SMALL_SAMPLE:
        caveat = (
            f"Only {len(scored)} scored forecast(s): every rate here is anecdote, not "
            f"evidence. {caveat}"
        )

    return ForecastSkill(
        window_days=days,
        since=since,
        forecaster_version=version if current_only else "",
        prompt_sha256=digest if current_only else "",
        recorded=len(window),
        pending=sum(1 for r in window if r.outcome is None),
        scored=len(scored),
        unscorable=len(unscorable),
        forecast=band_scores((r.risk, r.outcome.observed_band) for r in scored),
        baselines=[
            comparison(
                "persistence",
                "The band the stations recorded over the 24 hours before the forecast, "
                "carried forward unchanged.",
                lambda r: r.outcome.persistence_band,
            ),
            comparison(
                "cams",
                "The raw Open-Meteo (CAMS) forecast for the same window, fetched when "
                "the forecast was made, mapped to a band with no model.",
                lambda r: r.outcome.cams_band,
            ),
        ],
        band_basis=BAND_BASIS,
        caveat=caveat,
    )


# --------------------------------------------------------------------------- #
# The live ledger
# --------------------------------------------------------------------------- #


def record(outlooks: Iterable[AirQualityForecast], corridor_id: str = "") -> list[ForecastRecord]:
    """Write forecasts to the ledger as they are served. No network.

    The no-model baseline is fetched afterwards by `capture_baselines`, off the
    request, so serving a forecast is not slowed by a second Open-Meteo call.
    """
    if not settings.vayudoot_forecast_ledger:
        return []
    version, digest = FORECASTER_VERSION, prompt_sha256()
    model_id = settings.model_id_for("fast")
    written = []
    for outlook in outlooks:
        made = outlook.generated_at
        entry = ForecastRecord(
            forecast_id=f"VDF-{uuid.uuid4().hex[:10].upper()}",
            made_at=made,
            latitude=outlook.latitude,
            longitude=outlook.longitude,
            location_name=outlook.location_name,
            corridor_id=corridor_id,
            horizon_hours=outlook.horizon_hours,
            window_start=made,
            window_end=made + timedelta(hours=outlook.horizon_hours),
            risk=outlook.risk,
            confidence=outlook.confidence,
            peak_window_start=outlook.peak_window_start,
            peak_window_end=outlook.peak_window_end,
            drivers=outlook.drivers,
            basis=outlook.basis,
            forecaster_version=version,
            prompt_sha256=digest,
            model_id=model_id,
        )
        store.save_forecast_record(entry)
        written.append(entry)
    return written


def cams_worst_day(latitude: float, longitude: float, hours: int) -> dict[str, float]:
    """The raw Open-Meteo forecast's worst daily mean from now, per pollutant.

    The same numbers the model's tool reads, cut into days the same way the
    observation is, so the baseline is judged by exactly the observed rule.
    Empty on any failure: a forecast without a baseline is still a forecast.
    """
    try:
        response = httpx.get(
            _OPEN_METEO_AQ,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "hourly": "pm2_5,pm10",
                "forecast_hours": hours,
            },
            timeout=20,
        )
        response.raise_for_status()
        hourly = response.json().get("hourly", {})
    except Exception as exc:  # noqa: BLE001
        log.info("CAMS baseline not captured: %s", exc)
        return {}
    return cams_from_hourly(hourly, hours)


def cams_from_hourly(hourly: dict, hours: int) -> dict[str, float]:
    """Worst daily means from an Open-Meteo `hourly` block. Pure; the backtest shares it."""
    # Open-Meteo writes times without an offset; they are UTC unless asked
    # otherwise, and `_parse` reads a naive time as UTC.
    times = [_parse(t) for t in hourly.get("time") or []]
    if not times or times[0] is None:
        return {}
    out: dict[str, float] = {}
    for key, pollutant in (("pm2_5", "pm25"), ("pm10", "pm10")):
        series = {
            _hour(t): float(v)
            for t, v in zip(times, hourly.get(key) or [], strict=False)
            if t is not None and v is not None
        }
        value, _, _ = worst_day(series, times[0], hours)
        if value is not None:
            out[pollutant] = round(value, 1)
    return out


def capture_baselines(records: Iterable[ForecastRecord]) -> None:
    """Fetch and store the no-model baseline for freshly recorded forecasts."""
    for entry in records:
        cams = cams_worst_day(entry.latitude, entry.longitude, entry.horizon_hours)
        if cams:
            store.save_forecast_record(entry.model_copy(update={"cams_worst_day": cams}))


def score_due(
    now: datetime | None = None, source: StationSource | None = None, limit: int = 25
) -> dict:
    """Score every forecast whose window has closed and settled. No model call.

    Oldest first, `limit` at a time, so one pass after a long pause cannot spend
    OpenAQ's hourly allowance in a burst.
    """
    now = now or datetime.now(UTC)
    source = source or StationSource()
    due = sorted(
        (
            r
            for r in store.forecast_records()
            if r.outcome is None and r.window_end + timedelta(hours=SETTLE_HOURS) <= now
        ),
        key=lambda r: r.made_at,
    )[:limit]

    summary = {"checked": len(due), "scored": 0, "unscorable": 0, "waiting": 0}
    for entry in due:
        observation = observe(
            entry.latitude, entry.longitude, entry.window_start, entry.horizon_hours, source
        )
        still_worth_waiting = now < entry.window_end + timedelta(hours=GIVE_UP_HOURS)
        if observation.status != "scored" and observation.retryable and still_worth_waiting:
            store.save_forecast_record(
                entry.model_copy(update={"scoring_attempts": entry.scoring_attempts + 1})
            )
            summary["waiting"] += 1
            continue
        outcome = score(entry, observation)
        store.save_forecast_record(
            entry.model_copy(
                update={"outcome": outcome, "scoring_attempts": entry.scoring_attempts + 1}
            )
        )
        summary[outcome.status] += 1
    return summary


_pass_lock = threading.Lock()
_last_pass: float | None = None


def claim_scoring_pass() -> bool:
    """Whether a scoring pass may start now. At most one per configured interval.

    Called by whatever wants a pass — the scan timer, or a read of the ledger —
    so that reading the ledger twice in a minute asks OpenAQ nothing new.
    """
    global _last_pass
    if not settings.vayudoot_forecast_ledger:
        return False
    interval = max(settings.vayudoot_forecast_scoring_interval_minutes, 1) * 60
    with _pass_lock:
        moment = time.monotonic()
        if _last_pass is not None and moment - _last_pass < interval:
            return False
        _last_pass = moment
        return True


def reset_scoring_clock() -> None:
    """For tests: forget when the last pass ran."""
    global _last_pass
    _last_pass = None
