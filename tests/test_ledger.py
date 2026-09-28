"""The forecast ledger: recording forecasts, and scoring them against stations.

Everything here runs on fixtures. No network, and no model: scoring must never
spend a model call, and the tests would not notice if it did unless the model is
simply not there to call.

What matters most, in order: that the band mapping is the one written down in
`ledger.py` and nowhere else; that a forecast with no station near it is never
counted as right or wrong; and that a baseline is only ever compared with the
forecaster on the same forecasts.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from fakes import StubAgent
from vayudoot import ledger, store
from vayudoot.agents import forecast
from vayudoot.config import settings
from vayudoot.schemas import AirQualityForecast, ForecastOutcome, ForecastRecord

T0 = datetime(2025, 11, 5, 0, 0, tzinfo=UTC)
DELHI = (28.6139, 77.2090)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def hour_row(at: datetime, value: float, *, flagged: bool = False) -> dict:
    """One OpenAQ hour row, on the half hour the way Indian stations report."""
    start = at - timedelta(minutes=30)
    return {
        "value": value,
        "flagInfo": {"hasFlags": flagged},
        "period": {
            "datetimeFrom": {"utc": start.isoformat().replace("+00:00", "Z")},
            "datetimeTo": {"utc": (start + timedelta(hours=1)).isoformat().replace("+00:00", "Z")},
        },
    }


def hours(start: datetime, count: int, value: float, *, every: int = 1) -> list[dict]:
    return [hour_row(start + timedelta(hours=h), value) for h in range(0, count, every)]


def location(
    loc_id: int,
    name: str,
    km: float,
    sensors: dict[str, list[int]],
    *,
    monitor: bool = True,
    last: str = "2026-09-01T00:00:00Z",
) -> dict:
    return {
        "id": loc_id,
        "name": name,
        "distance": km * 1000,
        "isMonitor": monitor,
        "datetimeFirst": {"utc": "2016-01-01T00:00:00Z"},
        "datetimeLast": {"utc": last},
        "sensors": [
            {"id": sid, "parameter": {"name": parameter}}
            for parameter, ids in sensors.items()
            for sid in ids
        ],
    }


class FakeStations(ledger.StationSource):
    def __init__(self, locations: list[dict], series: dict[int, list[dict]]):
        self._locations = locations
        self._series = series
        self.hour_calls: list[int] = []

    def locations(self, latitude, longitude, radius_km):
        return self._locations

    def hours(self, sensor_id, start, end):
        self.hour_calls.append(sensor_id)
        return self._series.get(sensor_id, [])


def a_record(risk: str = "high", **overrides) -> ForecastRecord:
    fields = {
        "forecast_id": "VDF-TEST000001",
        "made_at": T0,
        "latitude": DELHI[0],
        "longitude": DELHI[1],
        "location_name": "Delhi",
        "horizon_hours": 72,
        "window_start": T0,
        "window_end": T0 + timedelta(hours=72),
        "risk": risk,
        "confidence": 0.6,
        "forecaster_version": forecast.FORECASTER_VERSION,
        "prompt_sha256": forecast.prompt_sha256(),
    }
    fields.update(overrides)
    return ForecastRecord(**fields)


def scored(risk: str, observed: str, *, persistence=None, cams=None, **overrides):
    return a_record(
        risk,
        outcome=ForecastOutcome(
            status="scored",
            pollutant="pm25",
            observed_value=100.0,
            observed_band=observed,
            persistence_band=persistence,
            cams_band=cams,
        ),
        **overrides,
    )


# --------------------------------------------------------------------------- #
# The band mapping
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("pollutant", "value", "band"),
    [
        ("pm25", 0.0, "low"),
        ("pm25", 60.0, "low"),
        ("pm25", 60.1, "elevated"),
        ("pm25", 120.0, "elevated"),
        ("pm25", 120.1, "high"),
        ("pm25", 250.0, "high"),
        ("pm25", 250.1, "severe"),
        ("pm25", 900.0, "severe"),
        ("pm10", 100.0, "low"),
        ("pm10", 100.1, "elevated"),
        ("pm10", 350.0, "elevated"),
        ("pm10", 430.0, "high"),
        ("pm10", 430.1, "severe"),
    ],
)
def test_observed_values_map_to_the_bands_written_in_ledger(pollutant, value, band):
    assert ledger.band_for(pollutant, value) == band


def test_low_is_anchored_to_the_standard_the_model_is_shown():
    """The prompt defines no numbers; its one anchor is "the standard", which
    the tool prints beside every value. Low must mean within that standard, or
    the score is judging the model against bands it was never told about."""
    assert ledger.BAND_LIMITS["pm25"][0] == settings.naaqs_standards["pm25"]
    assert ledger.BAND_LIMITS["pm10"][0] == settings.naaqs_standards["pm10"]


def test_the_bands_are_the_forecasts_own_bands_in_the_same_order():
    assert [row["risk"] for row in ledger.band_definitions()] == forecast.RISK_ORDER
    assert ledger.band_definitions()[-1]["pm25_to"] is None


# --------------------------------------------------------------------------- #
# Turning station hours into one number
# --------------------------------------------------------------------------- #


def test_hours_on_the_half_hour_are_filed_under_the_nearest_hour():
    series = ledger.hourly_series([hour_row(T0, 90.0)])
    assert series == {T0: 90.0}


def test_flagged_hours_and_instrument_fault_codes_are_dropped():
    rows = [
        hour_row(T0, 90.0, flagged=True),
        hour_row(T0 + timedelta(hours=1), 999.0),
        hour_row(T0 + timedelta(hours=2), 0.0),
        hour_row(T0 + timedelta(hours=3), 80.0),
    ]
    assert ledger.hourly_series(rows) == {T0 + timedelta(hours=3): 80.0}


def test_several_stations_combine_by_median_hour_by_hour():
    one = {T0: 100.0, T0 + timedelta(hours=1): 50.0}
    two = {T0: 300.0}
    three = {T0: 120.0}
    assert ledger.median_by_hour([one, two, three]) == {
        T0: 120.0,
        T0 + timedelta(hours=1): 50.0,
    }


def test_a_day_needs_sixteen_hours_to_have_a_mean():
    fifteen = {T0 + timedelta(hours=h): 100.0 for h in range(15)}
    sixteen = {T0 + timedelta(hours=h): 100.0 for h in range(16)}
    assert ledger.day_means(fifteen, T0, 24) == [None]
    assert ledger.day_means(sixteen, T0, 24) == [100.0]


def test_the_worst_day_is_what_a_forecast_is_judged_on():
    series = {T0 + timedelta(hours=h): (80.0 if h < 24 else 300.0 if h < 48 else 90.0)
              for h in range(72)}
    value, covered, total = ledger.worst_day(series, T0, 72)
    assert (value, covered, total) == (300.0, 3, 3)


def test_a_window_with_most_days_missing_is_not_judged_on_what_is_left():
    """One surviving day of three could be the quiet one."""
    series = {T0 + timedelta(hours=h): 80.0 for h in range(24)}
    assert ledger.worst_day(series, T0, 72) == (None, 1, 3)


def test_two_days_of_three_are_enough():
    series = {T0 + timedelta(hours=h): 80.0 for h in range(48)}
    assert ledger.worst_day(series, T0, 72) == (80.0, 2, 3)


def test_the_cams_baseline_is_cut_into_days_by_the_same_rule():
    times = [(T0 + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(72)]
    hourly = {
        "time": times,
        "pm2_5": [50.0] * 24 + [130.0] * 24 + [70.0] * 24,
        "pm10": [None] * 72,
    }
    assert ledger.cams_from_hourly(hourly, 72) == {"pm25": 130.0}


# --------------------------------------------------------------------------- #
# Observing a window
# --------------------------------------------------------------------------- #


def test_no_station_close_enough_is_unscorable_and_final():
    obs = ledger.observe(*DELHI, T0, 72, FakeStations([], {}))
    assert obs.status == "unscorable"
    assert not obs.retryable
    assert "25 km" in obs.reason


def test_a_low_cost_sensor_does_not_score_a_forecast():
    """The instrument an authority recognises, for the reason a citizen sensor
    cannot corroborate a hotspot on its own."""
    stations = FakeStations(
        [location(1, "Somebody's balcony", 2, {"pm25": [11]}, monitor=False)],
        {11: hours(T0 - timedelta(hours=24), 96, 200.0)},
    )
    assert ledger.observe(*DELHI, T0, 72, stations).status == "unscorable"


def test_a_station_that_stopped_reporting_years_ago_is_not_asked():
    stations = FakeStations(
        [location(1, "Closed 2018", 1, {"pm25": [11]}, last="2018-02-22T04:00:00Z")],
        {11: hours(T0 - timedelta(hours=24), 96, 200.0)},
    )
    assert ledger.observe(*DELHI, T0, 72, stations).status == "unscorable"
    assert stations.hour_calls == []


def test_pm25_is_preferred_and_persistence_comes_from_the_day_before():
    before = T0 - timedelta(hours=24)
    stations = FakeStations(
        [location(1, "R K Puram", 6, {"pm25": [11], "pm10": [12]})],
        {
            11: hours(before, 24, 70.0) + hours(T0, 72, 140.0),
            12: hours(before, 96, 400.0),
        },
    )
    obs = ledger.observe(*DELHI, T0, 72, stations)
    assert obs.status == "scored"
    assert obs.pollutant == "pm25"
    assert obs.value == 140.0
    assert obs.persistence_value == 70.0
    assert obs.stations == ["R K Puram (6.0 km)"]


def test_pm10_is_used_only_where_nobody_reported_pm25():
    stations = FakeStations(
        [location(1, "Ludhiana", 4, {"pm10": [12]})],
        {12: hours(T0 - timedelta(hours=24), 96, 200.0)},
    )
    obs = ledger.observe(*DELHI, T0, 72, stations)
    assert obs.pollutant == "pm10"
    assert ledger.band_for("pm10", obs.value) == "elevated"


def test_the_newest_sensor_is_asked_first_and_the_old_one_only_if_it_is_empty():
    stations = FakeStations(
        [location(1, "R K Puram", 6, {"pm25": [35, 12234787]})],
        {35: [], 12234787: hours(T0 - timedelta(hours=24), 96, 100.0)},
    )
    ledger.observe(*DELHI, T0, 72, stations)
    assert stations.hour_calls == [12234787]


def test_too_few_hours_is_unscorable_but_worth_retrying():
    stations = FakeStations(
        [location(1, "R K Puram", 6, {"pm25": [11]})],
        {11: hours(T0, 72, 100.0, every=3)},
    )
    obs = ledger.observe(*DELHI, T0, 72, stations)
    assert obs.status == "unscorable"
    assert obs.retryable


def test_an_openaq_failure_never_raises():
    class Down(ledger.StationSource):
        def locations(self, *args):
            raise httpx.ConnectError("down")

    obs = ledger.observe(*DELHI, T0, 72, Down())
    assert obs.status == "unscorable" and obs.retryable


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #


def test_a_score_records_the_band_error_and_both_baselines_by_one_rule():
    record = a_record("elevated", cams_worst_day={"pm25": 95.0, "pm10": 180.0})
    obs = ledger.Observation("scored", pollutant="pm25", value=180.0, persistence_value=130.0)

    outcome = ledger.score(record, obs)

    assert outcome.observed_band == "high"
    assert outcome.band_error == -1
    assert outcome.persistence_band == "high"
    assert outcome.cams_band == "elevated"
    assert outcome.cams_value == 95.0


def test_an_unscorable_outcome_carries_no_band_to_be_counted():
    outcome = ledger.score(a_record(), ledger.Observation("unscorable", "No station"))
    assert outcome.status == "unscorable"
    assert outcome.observed_band is None and outcome.band_error is None


def test_band_scores_fill_the_whole_confusion_matrix():
    result = ledger.band_scores([("high", "high"), ("elevated", "high"), ("low", "severe")])

    assert result.scored == 3
    assert result.exact == 1
    assert result.within_one == 2
    assert result.exact_rate == pytest.approx(1 / 3, abs=0.001)
    assert result.confusion["high"] == {"low": 0, "elevated": 1, "high": 1, "severe": 0}
    assert set(result.confusion) == set(forecast.RISK_ORDER)
    assert sum(sum(row.values()) for row in result.confusion.values()) == 3


def test_no_scored_forecasts_has_no_rate_rather_than_zero():
    result = ledger.band_scores([])
    assert result.exact_rate is None and result.within_one_rate is None


def test_unscorable_forecasts_are_never_counted_as_right_or_wrong():
    records = [
        scored("high", "high"),
        a_record("low", forecast_id="VDF-TEST000002",
                 outcome=ForecastOutcome(status="unscorable", reason="No station")),
        a_record("severe", forecast_id="VDF-TEST000003"),
    ]
    result = ledger.skill(records, days=3650, now=T0 + timedelta(days=5))

    assert result.scored == 1
    assert result.unscorable == 1
    assert result.pending == 1
    assert result.forecast.exact_rate == 1.0


def test_a_baseline_is_compared_on_exactly_the_same_forecasts():
    """Otherwise the comparison measures the samples rather than the methods."""
    records = [
        scored("high", "high", persistence="elevated"),
        scored("low", "severe", forecast_id="VDF-TEST000002"),  # no persistence here
    ]
    result = ledger.skill(records, days=3650, now=T0 + timedelta(days=5))
    persistence = next(b for b in result.baselines if b.name == "persistence")

    assert result.forecast.scored == 2
    assert persistence.compared == 1
    assert persistence.forecast.exact_rate == 1.0
    assert persistence.baseline.exact_rate == 0.0


def test_a_published_skill_counts_only_the_forecaster_now_running():
    records = [
        scored("high", "high"),
        scored("low", "severe", forecast_id="VDF-TEST000002", prompt_sha256="0" * 64),
    ]
    now = T0 + timedelta(days=5)

    current = ledger.skill(records, days=3650, now=now)
    everything = ledger.skill(records, days=3650, now=now, current_only=False)

    assert current.scored == 1 and current.prompt_sha256 == forecast.prompt_sha256()
    assert everything.scored == 2 and everything.prompt_sha256 == ""


def test_a_small_sample_says_so():
    result = ledger.skill([scored("high", "high")], days=3650, now=T0 + timedelta(days=5))
    assert "anecdote" in result.caveat


# --------------------------------------------------------------------------- #
# The live ledger
# --------------------------------------------------------------------------- #


def an_outlook(risk: str = "high") -> AirQualityForecast:
    return AirQualityForecast(
        latitude=DELHI[0], longitude=DELHI[1], location_name="Delhi", risk=risk,
        confidence=0.7, generated_at=T0, drivers=["north-westerly wind"],
        basis=["Open-Meteo air quality forecast"],
    )


@pytest.fixture
def ledger_on(monkeypatch):
    monkeypatch.setattr(settings, "vayudoot_forecast_ledger", True)
    ledger.reset_scoring_clock()
    yield
    ledger.reset_scoring_clock()


def test_a_forecast_is_recorded_as_it_was_made(ledger_on):
    (written,) = ledger.record([an_outlook("severe")], corridor_id="ncr")

    stored = store.load_forecast_record(written.forecast_id)
    assert stored.risk == "severe"
    assert stored.corridor_id == "ncr"
    assert stored.window_end - stored.window_start == timedelta(hours=72)
    assert stored.prompt_sha256 == forecast.prompt_sha256()
    assert stored.forecaster_version == forecast.FORECASTER_VERSION
    assert stored.basis == ["Open-Meteo air quality forecast"]
    assert stored.outcome is None


def test_a_node_can_switch_the_ledger_off():
    assert ledger.record([an_outlook()]) == []
    assert store.forecast_records() == []


def test_ledger_files_never_land_in_the_case_directory(ledger_on):
    ledger.record([an_outlook()])
    assert store.all_cases() == []
    assert not list(settings.vayudoot_case_dir.glob("*.json"))


def delhi_stations(value: float) -> FakeStations:
    return FakeStations(
        [location(1, "R K Puram", 6, {"pm25": [11]})],
        {11: hours(T0 - timedelta(hours=24), 96, value)},
    )


def test_nothing_is_scored_before_its_window_has_closed_and_settled(ledger_on):
    ledger.record([an_outlook()])
    early = T0 + timedelta(hours=72 + ledger.SETTLE_HOURS - 1)

    summary = ledger.score_due(now=early, source=delhi_stations(150.0))

    assert summary["checked"] == 0
    assert store.forecast_records()[0].outcome is None


def test_scoring_adds_an_outcome_and_never_touches_the_prediction(ledger_on):
    (written,) = ledger.record([an_outlook("elevated")])

    ledger.score_due(now=T0 + timedelta(days=4), source=delhi_stations(150.0))

    after = store.load_forecast_record(written.forecast_id)
    assert after.risk == "elevated"
    assert after.made_at == written.made_at
    assert after.outcome.status == "scored"
    assert after.outcome.observed_band == "high"
    assert after.outcome.band_error == -1


def test_a_short_window_waits_and_then_gives_up(ledger_on):
    (written,) = ledger.record([an_outlook()])
    thin = FakeStations(
        [location(1, "R K Puram", 6, {"pm25": [11]})], {11: hours(T0, 72, 100.0, every=4)}
    )

    first = ledger.score_due(now=T0 + timedelta(days=4), source=thin)
    assert first["waiting"] == 1
    assert store.load_forecast_record(written.forecast_id).outcome is None

    late = T0 + timedelta(hours=72 + ledger.GIVE_UP_HOURS + 1)
    ledger.score_due(now=late, source=thin)
    assert store.load_forecast_record(written.forecast_id).outcome.status == "unscorable"


def test_a_scoring_pass_is_claimed_at_most_once_per_interval(ledger_on):
    assert ledger.claim_scoring_pass() is True
    assert ledger.claim_scoring_pass() is False


def test_the_baseline_is_fetched_for_the_forecast_window(ledger_on, respx_mock):
    times = [(T0 + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(72)]
    route = respx_mock.get("https://air-quality-api.open-meteo.com/v1/air-quality").mock(
        return_value=httpx.Response(
            200, json={"hourly": {"time": times, "pm2_5": [200.0] * 72, "pm10": [300.0] * 72}}
        )
    )
    records = ledger.record([an_outlook()])

    ledger.capture_baselines(records)

    assert route.calls.last.request.url.params["forecast_hours"] == "72"
    stored = store.load_forecast_record(records[0].forecast_id)
    assert stored.cams_worst_day == {"pm25": 200.0, "pm10": 300.0}


def test_a_failed_baseline_fetch_leaves_the_forecast_without_one(ledger_on, respx_mock):
    respx_mock.get("https://air-quality-api.open-meteo.com/v1/air-quality").mock(
        return_value=httpx.Response(503)
    )
    records = ledger.record([an_outlook()])
    ledger.capture_baselines(records)
    assert store.load_forecast_record(records[0].forecast_id).cams_worst_day == {}


# --------------------------------------------------------------------------- #
# Over HTTP
# --------------------------------------------------------------------------- #


@pytest.fixture
async def client():
    from httpx import ASGITransport, AsyncClient

    from vayudoot import api

    transport = ASGITransport(app=api.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_a_served_forecast_is_in_the_ledger_once(client, monkeypatch, ledger_on):
    monkeypatch.setattr(forecast, "build_forecast_agent", lambda: StubAgent(an_outlook()))
    monkeypatch.setattr(ledger, "capture_baselines", lambda records: None)
    monkeypatch.setattr(ledger, "claim_scoring_pass", lambda: False)

    await client.get("/forecast", params={"lat": 28.61, "lon": 77.21, "place": "Delhi"})
    await client.get("/forecast", params={"lat": 28.61, "lon": 77.21, "place": "Delhi"})

    body = (await client.get("/forecasts/ledger")).json()
    assert len(body) == 1
    assert body[0]["risk"] == "high"
    assert body[0]["outcome"] is None


async def test_the_ledger_can_be_filtered_by_status(client, monkeypatch, ledger_on):
    monkeypatch.setattr(ledger, "claim_scoring_pass", lambda: False)
    store.save_forecast_record(scored("high", "high"))
    store.save_forecast_record(a_record(forecast_id="VDF-TEST000002"))

    assert len((await client.get("/forecasts/ledger?status=pending")).json()) == 1
    assert len((await client.get("/forecasts/ledger?status=scored")).json()) == 1


async def test_skill_is_served_with_its_baselines(client, monkeypatch, ledger_on):
    monkeypatch.setattr(ledger, "claim_scoring_pass", lambda: False)
    recent = datetime.now(UTC) - timedelta(days=5)
    store.save_forecast_record(
        scored("high", "high", persistence="high", cams="elevated", made_at=recent)
    )

    body = (await client.get("/forecasts/skill")).json()

    assert body["scored"] == 1
    assert body["forecast"]["exact_rate"] == 1.0
    assert {b["name"] for b in body["baselines"]} == {"persistence", "cams"}
    cams = next(b for b in body["baselines"] if b["name"] == "cams")
    assert cams["baseline"]["within_one_rate"] == 1.0
    assert body["forecast"]["confusion"]["high"]["high"] == 1
    assert body["band_basis"]
