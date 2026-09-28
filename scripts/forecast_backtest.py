"""Backtest the forecast agent on past days, against two baselines.

    uv run python scripts/forecast_backtest.py                  # baselines + up to 60 model calls
    uv run python scripts/forecast_backtest.py --max-calls 0    # baselines only, no model
    uv run python scripts/forecast_backtest.py --max-calls 120  # a bigger agent sample

The ledger (`vayudoot/ledger.py`) scores forecasts as they are made, which cannot
leak but takes weeks to say anything. This asks the same question of the past,
where the answer is already known, and so has to work hard not to let the answer
into the question. `docs/forecast-evaluation.md` has the results and the limits;
what follows is how each input is rebuilt as it looked at the issue time.

**Issue time** is 00:00 UTC on each case date (05:30 in India). The window scored
is the 72 hours that follow, the live forecaster's horizon.

**Wind** comes from Open-Meteo's Single Runs API: one ECMWF IFS run, initialised
at 12:00 UTC the day before and published hours before the issue time. It is the
wind forecast the tool would really have returned. Where that run is missing the
00:00 run of the day before is used, then 12:00 two days before; the run used is
recorded per case.

**Air quality is the one input that leaks.** Open-Meteo keeps no previous runs of
its CAMS air-quality forecast: the `_previous_dayN` variables come back empty and
the `run` parameter is refused. Its only past series is an archive stitched from
the first hours of successive CAMS runs, so the value at hour 48 of a window comes
from a run started close to hour 48, not from a 48-hour forecast. That is nearer
to an analysis than a forecast. The agent and the CAMS baseline both read it, so
the comparison between them is fair, but both look better than they would live.
Persistence reads only stations before the issue time and does not leak.

**Fires** come from NASA FIRMS VIIRS (standard processing where available, near
real time after that), the two days before the issue time, within the
forecaster's upwind reach, turned into hotspots by the same `hotspots.detect` the
live system uses. A live node sees only the fires its scan points found, so this
gives the model a fuller picture of the fires than production does.

**Observations** are the ledger's own `observe()`: OpenAQ reference monitors
within 25 km, worst 24-hour mean over the window, the same four bands.

**Dates the model sees are shifted forward 364 days** (a whole number of weeks,
so weekdays still line up). The prompt carries no date, but the tool output
does, and a model that has read news about Delhi on 5 November 2025 could
otherwise remember the answer. What it may still know is climatology — Delhi in
November is usually bad — which a live forecaster knows too.

**Every agent run gets a fresh agent**, run one at a time. A Strands `Agent`
keeps its conversation, and a reused one would read the previous case's tool
results.

Everything fetched is cached under `data/backtest/` (git-ignored), and so is
every model answer, keyed by the forecaster version and prompt hash. A rerun
spends nothing unless the prompt changed.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import math
import random
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vayudoot import hotspots, ledger
from vayudoot.agents import forecast
from vayudoot.config import settings
from vayudoot.schemas import ForecastRecord
from vayudoot.tools import weather
from vayudoot.tools.geo import bbox_around, haversine_km

HORIZON = 72
SHIFT = timedelta(days=364)
FIRMS_DAYS = 2
#: FIRMS keeps standard-processing data up to about three months back; after
#: that only near-real-time. Read from its data_availability endpoint.
FIRMS_SP_UNTIL = date(2026, 6, 30)

LOCATIONS: dict[str, tuple[str, str, float, float]] = {
    # key: (name, region, latitude, longitude)
    "delhi": ("Delhi", "NCR", 28.6139, 77.2090),
    "ghaziabad": ("Ghaziabad", "NCR", 28.6692, 77.4538),
    "gurugram": ("Gurugram", "NCR", 28.4595, 77.0266),
    "ludhiana": ("Ludhiana", "Punjab-Haryana", 30.9010, 75.8573),
    "amritsar": ("Amritsar", "Punjab-Haryana", 31.6340, 74.8723),
    "patiala": ("Patiala", "Punjab-Haryana", 30.3398, 76.3869),
    "bathinda": ("Bathinda", "Punjab-Haryana", 30.2110, 74.9455),
    "jalandhar": ("Jalandhar", "Punjab-Haryana", 31.3260, 75.5762),
    "chandigarh": ("Chandigarh", "Punjab-Haryana", 30.7333, 76.7794),
    "hisar": ("Hisar", "Punjab-Haryana", 29.1492, 75.7217),
    "lucknow": ("Lucknow", "Other", 26.8467, 80.9462),
    "kanpur": ("Kanpur", "Other", 26.4499, 80.3319),
    "patna": ("Patna", "Other", 25.5941, 85.1376),
    "jaipur": ("Jaipur", "Other", 26.9124, 75.7873),
    "kolkata": ("Kolkata", "Other", 22.5726, 88.3639),
    "mumbai": ("Mumbai", "Other", 19.0760, 72.8777),
    "ahmedabad": ("Ahmedabad", "Other", 23.0225, 72.5714),
    "hyderabad": ("Hyderabad", "Other", 17.3850, 78.4867),
    "bengaluru": ("Bengaluru", "Other", 12.9716, 77.5946),
    "chennai": ("Chennai", "Other", 13.0827, 80.2707),
}


def _dates(start: date, end: date, step: int) -> list[date]:
    out, day = [], start
    while day <= end:
        out.append(day)
        day += timedelta(days=step)
    return out


#: Three days apart in the burning season, so the 72-hour windows do not overlap
#: and no observed day is counted twice for one place.
DATES: dict[str, list[date]] = {
    "burning": _dates(date(2025, 10, 15), date(2025, 11, 26), 3),
    "winter": [date(2025, 12, 10), date(2025, 12, 24), date(2026, 1, 7), date(2026, 1, 21),
               date(2026, 2, 4)],
    "summer": [date(2026, 3, 11), date(2026, 4, 8), date(2026, 5, 6), date(2026, 6, 3)],
    "monsoon": [date(2026, 7, 15), date(2026, 8, 12)],
}


@dataclass
class Case:
    key: str
    name: str
    region: str
    latitude: float
    longitude: float
    day: date
    season: str

    @property
    def case_id(self) -> str:
        return f"{self.key}-{self.day.isoformat()}"

    @property
    def issued(self) -> datetime:
        return datetime(self.day.year, self.day.month, self.day.day, tzinfo=UTC)

    @property
    def group(self) -> str:
        if self.season == "burning" and self.region != "Other":
            return "burning season, NCR and Punjab-Haryana"
        if self.season == "burning":
            return "burning season, elsewhere"
        return "rest of the year"


def all_cases() -> list[Case]:
    return [
        Case(key, name, region, lat, lon, day, season)
        for season, days in DATES.items()
        for day in days
        for key, (name, region, lat, lon) in LOCATIONS.items()
    ]


# --------------------------------------------------------------------------- #
# Disk cache
# --------------------------------------------------------------------------- #


class Cache:
    def __init__(self, root: Path):
        self.root = root

    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    def get(self, *parts: str):
        path = self.path(*parts)
        return json.loads(path.read_text()) if path.exists() else None

    def put(self, value, *parts: str):
        path = self.path(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, default=str))
        return value


class CachedStations(ledger.StationSource):
    """OpenAQ behind a disk cache, a month of a sensor at a time.

    Fetching whole months means the burning season's fifteen windows at one
    place cost two requests per sensor rather than fifteen. OpenAQ allows 60
    requests a minute, so each network call is spaced out.
    """

    def __init__(self, cache: Cache):
        self.cache = cache
        self.calls = 0

    def _wait(self):
        self.calls += 1
        time.sleep(1.1)

    def locations(self, latitude, longitude, radius_km):
        name = f"{latitude:.4f}_{longitude:.4f}_{radius_km:.0f}.json"
        hit = self.cache.get("openaq", "locations", name)
        if hit is not None:
            return hit
        self._wait()
        return self.cache.put(super().locations(latitude, longitude, radius_km),
                              "openaq", "locations", name)

    def hours(self, sensor_id, start, end):
        rows: list[dict] = []
        month = datetime(start.year, start.month, 1, tzinfo=UTC)
        while month < end:
            following = (month + timedelta(days=32)).replace(day=1)
            name = f"{sensor_id}_{month:%Y-%m}.json"
            hit = self.cache.get("openaq", "hours", name)
            if hit is None:
                self._wait()
                hit = self.cache.put(super().hours(sensor_id, month, following),
                                     "openaq", "hours", name)
            rows.extend(hit)
            month = following
        return rows


# --------------------------------------------------------------------------- #
# Inputs as they were at the issue time
# --------------------------------------------------------------------------- #


def cams_archive(cache: Cache, lat: float, lon: float, day: date) -> dict:
    """Open-Meteo's stitched CAMS archive from the issue day for five days. Leaks; see top."""
    name = f"{lat:.2f}_{lon:.2f}_{day}.json"
    hit = cache.get("cams", name)
    if hit is not None:
        return hit
    response = httpx.get(
        weather._AIR_QUALITY_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "hourly": "pm2_5,pm10",
            "start_date": day.isoformat(),
            "end_date": (day + timedelta(days=5)).isoformat(),
        },
        timeout=30,
    )
    response.raise_for_status()
    return cache.put(response.json().get("hourly", {}), "cams", name)


def wind_run(cache: Cache, lat: float, lon: float, day: date) -> dict:
    """The newest ECMWF IFS run published before the issue time, hour by hour."""
    name = f"{lat:.2f}_{lon:.2f}_{day}.json"
    hit = cache.get("wind", name)
    if hit is not None:
        return hit
    issued = datetime(day.year, day.month, day.day, tzinfo=UTC)
    for back in (12, 24, 36):
        run = issued - timedelta(hours=back)
        response = httpx.get(
            "https://single-runs-api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "run": run.strftime("%Y-%m-%dT%H:%M"),
                "models": "ecmwf_ifs",
                "hourly": "wind_speed_10m,wind_direction_10m",
                "wind_speed_unit": "ms",
                "forecast_hours": back + 120,
            },
            timeout=30,
        )
        if response.status_code == 400:
            continue
        response.raise_for_status()
        hourly = response.json().get("hourly", {})
        return cache.put({"run": run.isoformat(), "hourly": hourly}, "wind", name)
    return cache.put({"run": None, "hourly": {}}, "wind", name)


def firms_detections(cache: Cache, case: Case) -> dict:
    """VIIRS fire detections in the two days before the issue time, within reach."""
    name = f"{case.case_id}.json"
    hit = cache.get("firms", name)
    if hit is not None:
        return hit
    first = case.day - timedelta(days=FIRMS_DAYS)
    source = "VIIRS_SNPP_SP" if case.day - timedelta(days=1) <= FIRMS_SP_UNTIL else "VIIRS_SNPP_NRT"
    reach = settings.vayudoot_forecast_upwind_km
    west, south, east, north = bbox_around(case.latitude, case.longitude, reach)
    area = f"{west:.3f},{south:.3f},{east:.3f},{north:.3f}"
    url = (
        "https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
        f"{settings.firms_map_key}/{source}/{area}/{FIRMS_DAYS}/{first.isoformat()}"
    )
    response = httpx.get(url, timeout=60)
    response.raise_for_status()
    detections = []
    for row in csv.DictReader(io.StringIO(response.text)):
        try:
            d_lat, d_lon = float(row["latitude"]), float(row["longitude"])
        except (KeyError, ValueError):
            continue
        if row.get("acq_date", "") >= case.day.isoformat():
            continue  # nothing observed at or after the issue time
        km = haversine_km(case.latitude, case.longitude, d_lat, d_lon)
        if km > reach:
            continue
        detections.append(
            {
                "distance_km": round(km, 2),
                "latitude": d_lat,
                "longitude": d_lon,
                "acquired_date": row.get("acq_date"),
                "acquired_time_utc": row.get("acq_time"),
                "confidence": row.get("confidence"),
                "fire_radiative_power_mw": row.get("frp"),
            }
        )
    return cache.put({"source": source, "detections": detections}, "firms", name)


def _shifted(times: list[str]) -> list[str]:
    return [
        (datetime.fromisoformat(t) + SHIFT).strftime("%Y-%m-%dT%H:%M") for t in times
    ]


def _slice(hourly: dict, start: datetime, hours: int) -> dict:
    """The `hours` hours from `start`, with times shifted as the model will see them."""
    stamp = start.strftime("%Y-%m-%dT%H:%M")
    times = hourly.get("time") or []
    if stamp not in times:
        return {}
    i = times.index(stamp)
    out = {key: values[i : i + hours] for key, values in hourly.items() if key != "time"}
    out["time"] = _shifted(times[i : i + hours])
    return out


class Replay:
    """Stands in for `httpx` inside `tools/weather.py` for one case.

    Answers the two forecast tools from the past, for whatever coordinates the
    model asks about — it may ask about an upwind point as well as the case —
    fetching and caching those on demand, still as of the issue time.
    """

    def __init__(self, cache: Cache, case: Case):
        self.cache = cache
        self.case = case
        self.requests: list[str] = []

    def get(self, url, params=None, **_):
        params = params or {}
        lat, lon = float(params["latitude"]), float(params["longitude"])
        span = int(params.get("forecast_hours") or HORIZON)
        self.requests.append(f"{url} {lat:.2f},{lon:.2f} {span}h")
        if url == weather._AIR_QUALITY_URL:
            hourly = _slice(cams_archive(self.cache, lat, lon, self.case.day),
                            self.case.issued, span)
        else:
            run = wind_run(self.cache, lat, lon, self.case.day)
            hourly = _slice(run["hourly"], self.case.issued, span)
        request = httpx.Request("GET", url)
        return httpx.Response(200, json={"hourly": hourly}, request=request)


# --------------------------------------------------------------------------- #
# The agent, once per case
# --------------------------------------------------------------------------- #


def agent_key() -> str:
    return f"v{forecast.FORECASTER_VERSION}-{forecast.prompt_sha256()[:12]}"


async def run_agent(cache: Cache, case: Case) -> dict:
    """One forecast, from a fresh agent, with the tools answering from the past."""
    fires = firms_detections(cache, case)
    signals = hotspots.signals_from_satellite(fires)
    spots = hotspots.detect(signals)

    agent = forecast.build_forecast_agent()
    replay = Replay(cache, case)
    started = time.monotonic()
    try:
        with mock.patch.object(weather, "httpx", SimpleNamespace(get=replay.get)):
            outlook = await forecast.forecast_location(
                latitude=case.latitude,
                longitude=case.longitude,
                location_name=case.name,
                nearby_hotspots=spots,
                agent=agent,
            )
    finally:
        cycles = agent.event_loop_metrics.cycle_count
    return {
        "case_id": case.case_id,
        "risk": outlook.risk,
        "confidence": outlook.confidence,
        "drivers": outlook.drivers,
        "basis": outlook.basis,
        "model_calls": cycles,
        "model_id": (getattr(agent.model, "config", None) or {}).get("model_id", ""),
        "tool_requests": replay.requests,
        "fires_seen": len(fires["detections"]),
        "hotspots_seen": len(forecast.upwind_hotspots(case.latitude, case.longitude, spots)),
        "firms_source": fires["source"],
        "wind_run": wind_run(cache, case.latitude, case.longitude, case.day)["run"],
        "seconds": round(time.monotonic() - started, 1),
        "forecaster": agent_key(),
    }


# --------------------------------------------------------------------------- #
# Statistics
# --------------------------------------------------------------------------- #


def wilson(hits: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% interval for a rate. Honest at small n, where the normal one is not."""
    if n == 0:
        return (0.0, 0.0)
    p = hits / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def sign_test(wins: int, losses: int) -> float:
    """Two-sided exact p-value that wins and losses are a coin toss (ties dropped)."""
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def summarise(rows: list[dict], methods: list[str]) -> dict:
    """Scores for each method over exactly the rows where every method has a band."""
    usable = [r for r in rows if all(r.get(m) for m in methods)]
    out: dict = {"n": len(usable), "methods": {}}
    for method in methods:
        scores = ledger.band_scores((r[method], r["observed"]) for r in usable)
        errors = [
            forecast.RISK_ORDER.index(r[method]) - forecast.RISK_ORDER.index(r["observed"])
            for r in usable
        ]
        out["methods"][method] = {
            "exact": scores.exact,
            "exact_rate": scores.exact_rate,
            "exact_ci": wilson(scores.exact, scores.scored),
            "within_one": scores.within_one,
            "within_one_rate": scores.within_one_rate,
            "mean_band_error": round(sum(errors) / len(errors), 2) if errors else None,
            "confusion": scores.confusion,
        }
    if "agent" in methods:
        for other in (m for m in methods if m != "agent"):
            wins = sum(1 for r in usable if r["agent"] == r["observed"] != r[other])
            losses = sum(1 for r in usable if r[other] == r["observed"] != r["agent"])
            out["methods"][other]["agent_vs"] = {
                "agent_right_only": wins,
                "baseline_right_only": losses,
                "p_value": round(sign_test(wins, losses), 3),
            }
    return out


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #


def observe_all(cache: Cache, cases: list[Case]) -> list[dict]:
    """Observed outcome, persistence and CAMS for every case. No model."""
    stations = CachedStations(cache)
    rows = []
    for number, case in enumerate(cases, 1):
        obs = ledger.observe(case.latitude, case.longitude, case.issued, HORIZON, stations)
        row = {
            "case_id": case.case_id,
            "group": case.group,
            "season": case.season,
            "region": case.region,
            "status": obs.status,
            "reason": obs.reason,
        }
        if obs.status == "scored":
            try:
                hourly = cams_archive(cache, case.latitude, case.longitude, case.day)
                cams = ledger.cams_from_hourly(_slice(hourly, case.issued, HORIZON), HORIZON)
            except httpx.HTTPError as exc:
                print(f"  CAMS failed for {case.case_id}: {exc}", file=sys.stderr)
                cams = {}
            record = ForecastRecord(
                forecast_id=case.case_id,
                made_at=case.issued,
                latitude=case.latitude,
                longitude=case.longitude,
                horizon_hours=HORIZON,
                window_start=case.issued,
                window_end=case.issued + timedelta(hours=HORIZON),
                risk="low",  # a placeholder: only the baselines are read from this outcome
                confidence=0.0,
                forecaster_version=forecast.FORECASTER_VERSION,
                prompt_sha256=forecast.prompt_sha256(),
                cams_worst_day=cams,
            )
            outcome = ledger.score(record, obs)
            row.update(
                pollutant=outcome.pollutant,
                observed_value=outcome.observed_value,
                observed=outcome.observed_band,
                persistence_value=outcome.persistence_value,
                persistence=outcome.persistence_band,
                cams_value=outcome.cams_value,
                cams=outcome.cams_band,
                stations=outcome.stations,
            )
        rows.append(row)
        if number % 25 == 0:
            print(f"  observed {number}/{len(cases)} ({stations.calls} OpenAQ requests)")
    return rows


def pick_agent_cases(rows: list[dict], cases: dict[str, Case], seed: int) -> list[Case]:
    """Scorable cases in a fixed order that spreads the budget across groups.

    Chosen only on whether the case can be scored and has every baseline, never
    on what was observed, so the sample is not tilted towards easy days. Two
    burning-season cases in NCR and Punjab for every one elsewhere or later,
    because that season is what the forecaster exists for.
    """
    usable = [r for r in rows if r.get("observed") and r.get("persistence") and r.get("cams")]
    rng = random.Random(seed)
    groups: dict[str, list[dict]] = {}
    for row in usable:
        groups.setdefault(row["group"], []).append(row)
    for members in groups.values():
        rng.shuffle(members)
    pattern = [
        "burning season, NCR and Punjab-Haryana",
        "burning season, NCR and Punjab-Haryana",
        "burning season, elsewhere",
        "rest of the year",
    ]
    ordered: list[Case] = []
    while any(groups.values()):
        for name in pattern:
            if groups.get(name):
                ordered.append(cases[groups[name].pop()["case_id"]])
    return ordered


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--max-calls", type=int, default=60,
                        help="model requests to spend at most (default 60; 0 for none)")
    parser.add_argument("--cache", type=Path, default=ROOT / "data" / "backtest")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--pause", type=float, default=15.0,
                        help="seconds between forecasts, for the per-minute limit")
    args = parser.parse_args()

    cache = Cache(args.cache)
    cases = all_cases()
    by_id = {c.case_id: c for c in cases}

    print(f"Observing {len(cases)} cases (no model calls)...")
    rows = observe_all(cache, cases)
    scored = [r for r in rows if r["status"] == "scored"]
    print(f"  {len(scored)} scorable, {len(rows) - len(scored)} unscorable")

    spent = 0
    failures = 0
    answers: dict[str, dict] = {}
    for case in pick_agent_cases(rows, by_id, args.seed):
        name = f"{case.case_id}-{agent_key()}.json"
        hit = cache.get("agent", name)
        if hit is not None:
            answers[case.case_id] = hit
            continue
        # A forecast takes two or three requests: the tool calls, then the answer.
        if spent + 3 > args.max_calls:
            continue
        # The free tier allows 15 requests a minute per model, shared with
        # everything else on the key, so forecasts are spaced out.
        await asyncio.sleep(args.pause)
        try:
            answer = await run_agent(cache, case)
        except Exception as exc:  # noqa: BLE001 - one failed case must not end the run
            spent += 3  # assume the worst about what a failure cost
            failures += 1
            text = str(exc)
            print(f"  agent failed on {case.case_id}: {text[:300]}", file=sys.stderr)
            if "PerDay" in text:
                # The day's allowance is gone. Retrying spends nothing useful.
                print("  daily quota exhausted, stopping the agent runs", file=sys.stderr)
                break
            if failures >= 3:
                print("  three failures, stopping the agent runs", file=sys.stderr)
                break
            if "429" in text:
                await asyncio.sleep(60)  # a per-minute limit: let the minute pass once
            continue
        spent += answer["model_calls"]
        answers[case.case_id] = cache.put(answer, "agent", name)
        print(f"  {case.case_id}: agent said {answer['risk']} "
              f"({answer['model_calls']} calls, {spent} spent)")

    for row in rows:
        if row["case_id"] in answers:
            row["agent"] = answers[row["case_id"]]["risk"]

    with_agent = [r for r in scored if r.get("agent")]
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "forecaster": agent_key(),
        "model_calls_spent_this_run": spent,
        "cases": len(rows),
        "scorable": len(scored),
        "unscorable_reasons": _count(r["reason"].split(":")[0] for r in rows
                                     if r["status"] != "scored"),
        "observed_bands": _count(r["observed"] for r in scored),
        "baselines_all": summarise(scored, ["persistence", "cams"]),
        "baselines_by_group": {
            g: summarise([r for r in scored if r["group"] == g], ["persistence", "cams"])
            for g in sorted({r["group"] for r in scored})
        },
        "agent_all": summarise(with_agent, ["agent", "persistence", "cams"]),
        "agent_by_group": {
            g: summarise([r for r in with_agent if r["group"] == g],
                         ["agent", "persistence", "cams"])
            for g in sorted({r["group"] for r in with_agent})
        },
        "agent_answers": list(answers.values()),
        "rows": rows,
    }
    cache.put(report, "results.json")
    _print(report)


def _count(values) -> dict:
    out: dict = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _print(report: dict) -> None:
    def table(title: str, summary: dict) -> None:
        print(f"\n{title} (n={summary['n']})")
        for method, s in summary["methods"].items():
            if s["exact_rate"] is None:
                continue
            low, high = s["exact_ci"]
            line = (f"  {method:<12} exact {s['exact_rate']:.2f} [{low:.2f}-{high:.2f}]  "
                    f"within one {s['within_one_rate']:.2f}  bias {s['mean_band_error']:+.2f}")
            if "agent_vs" in s:
                v = s["agent_vs"]
                line += (f"  | agent only right {v['agent_right_only']}, "
                         f"{method} only right {v['baseline_right_only']}, p={v['p_value']}")
            print(line)

    print(f"\nForecaster {report['forecaster']}; {report['model_calls_spent_this_run']} "
          "model calls spent this run")
    print(f"Cases {report['cases']}, scorable {report['scorable']}")
    print(f"Observed bands: {report['observed_bands']}")
    print(f"Unscorable: {report['unscorable_reasons']}")
    table("Baselines, every scorable case", report["baselines_all"])
    for group, summary in report["baselines_by_group"].items():
        table(f"Baselines, {group}", summary)
    table("Agent against baselines, same cases", report["agent_all"])
    for group, summary in report["agent_by_group"].items():
        table(f"Agent, {group}", summary)


if __name__ == "__main__":
    asyncio.run(main())
