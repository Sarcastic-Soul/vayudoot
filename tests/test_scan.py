"""The periodic scan, and the signal store underneath it.

Fully offline. No test here touches the network: both source tools are replaced
with the payload they would have returned, which is also the point — what is
being tested is the conversion and the storage, not NASA's uptime.

One of these is a correctness test rather than a behaviour test and is marked
where it appears: `test_scanning_the_same_ground_twice_stores_no_duplicates`.
A duplicated signal does not merely take up space, it changes the answer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from vayudoot import scan, store
from vayudoot.config import settings
from vayudoot.schemas import Case, CaseStatus, Report, Signal, SignalSource

NOW = datetime(2026, 9, 14, 6, 0, tzinfo=UTC)

#: Ludhiana, in the Punjab stubble belt — a place with plenty of satellite
#: detections and no reason for a citizen report to exist.
LUDHIANA = (30.9010, 75.8573)
#: About 900 m away: inside any sensible scan radius, so a second scan point
#: here would fetch the same square of sky.
NEXT_DOOR = (30.9085, 75.8600)
#: Delhi, far enough that it is genuinely a second place to look.
DELHI = (28.6139, 77.2090)


FIRMS_PAYLOAD = {
    "source": "VIIRS_SNPP_NRT",
    "search_radius_km": 50.0,
    "days_searched": 2,
    "detection_count": 2,
    "detections": [
        {
            "distance_km": 3.1,
            "latitude": 30.9210,
            "longitude": 75.8801,
            "acquired_date": "2026-09-14",
            "acquired_time_utc": "0612",
            "confidence": "high",
            "brightness_kelvin": "331.2",
            "fire_radiative_power_mw": "48.2",
        },
        {
            "distance_km": 7.4,
            "latitude": 30.8604,
            "longitude": 75.9102,
            "acquired_date": "2026-09-14",
            "acquired_time_utc": "0612",
            "confidence": "nominal",
            "brightness_kelvin": "318.7",
            "fire_radiative_power_mw": "12.6",
        },
    ],
}

#: One pollutant well past its standard and one comfortably under it, because a
#: clean reading must not put a dot on the map — see `hotspots._exceedance`.
OPENAQ_PAYLOAD = {
    "nearest_station": "Ludhiana - PAU",
    "station_id": 8118,
    "latitude": 30.9008,
    "longitude": 75.8070,
    "distance_km": 4.9,
    "provider": "CPCB",
    "measurements": [
        {
            "parameter": "pm25",
            "value": 186.0,
            "unit": "µg/m³",
            "measured_at": "2026-09-14T06:00:00+00:00",
        },
        {
            "parameter": "no2",
            "value": 11.0,
            "unit": "µg/m³",
            "measured_at": "2026-09-14T06:00:00+00:00",
        },
    ],
}

FIRMS_SIGNALS = 2
OPENAQ_SIGNALS = 1


@pytest.fixture
def sources(monkeypatch):
    """Replace both evidence tools, and hand back the call log.

    Returned as a dict of lists so a test can assert what the scan asked for —
    and, for the disabled case, that it asked for nothing at all.
    """
    calls: dict[str, list[dict]] = {"firms": [], "openaq": []}

    def install(firms=FIRMS_PAYLOAD, openaq=OPENAQ_PAYLOAD):
        def fake_firms(**kwargs):
            calls["firms"].append(kwargs)
            return firms() if callable(firms) else firms

        def fake_openaq(**kwargs):
            calls["openaq"].append(kwargs)
            return openaq() if callable(openaq) else openaq

        monkeypatch.setattr(scan, "find_satellite_fire_detections", fake_firms)
        monkeypatch.setattr(scan, "get_nearby_air_quality", fake_openaq)
        return calls

    install.calls = calls
    return install


@pytest.fixture
def without_corridors(monkeypatch):
    """Scan only the cases, ignoring the corridor file.

    `corridors.json` ships with waypoints across the whole country, which is the
    point of it — but a test about where a *case* sends the scan cannot say
    anything if thirty national waypoints arrive alongside. The corridors' own
    contribution is asserted separately, below.
    """
    monkeypatch.setattr(scan, "_corridor_waypoints", list)


def stored_case(case_id: str = "VD-SCAN0001", at: tuple[float, float] = LUDHIANA) -> Case:
    case = Case(
        case_id=case_id,
        status=CaseStatus.FILED,
        report=Report(
            report_id=f"R-{case_id}",
            latitude=at[0],
            longitude=at[1],
            observed_at=NOW,
        ),
    )
    store.save(case)
    return case


def a_signal(signal_id: str, *, observed_at: datetime) -> Signal:
    return Signal(
        source=SignalSource.SATELLITE,
        signal_id=signal_id,
        latitude=LUDHIANA[0],
        longitude=LUDHIANA[1],
        observed_at=observed_at,
    )


# --------------------------------------------------------------------------- #
# Fetching and converting
# --------------------------------------------------------------------------- #


def test_a_scan_turns_a_firms_payload_into_stored_signals(sources):
    """The thing that was missing: evidence arriving with no citizen involved.

    Nobody has reported anything here. The detections exist because a satellite
    passed over, which is what lets the map have content in a district that has
    never opened the app.
    """
    sources()

    new = scan.scan_points([LUDHIANA])

    stored = store.all_signals()
    assert new == FIRMS_SIGNALS + OPENAQ_SIGNALS
    assert len(stored) == new
    satellite = [s for s in stored if s.source is SignalSource.SATELLITE]
    assert len(satellite) == FIRMS_SIGNALS
    assert satellite[0].signal_id.startswith("viirs:")
    assert satellite[0].observed_at == datetime(2026, 9, 14, 6, 12, tzinfo=UTC)


def test_a_clean_station_reading_produces_no_signal(sources):
    """Only an exceedance is evidence of something happening.

    The station reports PM2.5 far over its standard and NO2 well under it; one
    signal, not two. A station reporting clean air must not put a dot anywhere.
    """
    sources()

    scan.scan_point(*LUDHIANA)
    scan.scan_points([LUDHIANA])

    station = [s for s in store.all_signals() if s.source is SignalSource.GROUND_STATION]
    assert len(station) == OPENAQ_SIGNALS
    assert "pm25" in station[0].summary


def test_scan_point_fetches_but_does_not_store(sources):
    """`scan_point` is the diagnostic call; `scan_points` is the one that writes."""
    sources()

    found = scan.scan_point(*LUDHIANA)

    assert len(found) == FIRMS_SIGNALS + OPENAQ_SIGNALS
    assert store.all_signals() == []


def test_a_scan_uses_the_configured_radius_and_window(sources, monkeypatch):
    calls = sources()
    monkeypatch.setattr(settings, "vayudoot_scan_radius_km", 25.0)
    monkeypatch.setattr(settings, "vayudoot_scan_days", 3)

    scan.scan_points([LUDHIANA])

    assert calls["firms"][0]["radius_km"] == 25.0
    assert calls["firms"][0]["days"] == 3
    assert calls["openaq"][0]["radius_km"] == 25.0


# --------------------------------------------------------------------------- #
# Deduplication: a correctness property, not tidiness
# --------------------------------------------------------------------------- #


def test_scanning_the_same_ground_twice_stores_no_duplicates(sources):
    """The scan runs on a timer, and VIIRS publishes the same pass for hours.

    Duplicate signals are not untidiness, they are a wrong answer. A hotspot's
    confidence rises with how many distinct sources agree and its severity with
    how persistent the evidence looks, so the same fire stored twice reports as a
    more serious, better corroborated event than the evidence supports — and the
    map's job is to be believed. `signal_id` is built to identify the
    observation for exactly this reason.
    """
    sources()

    first = scan.scan_points([LUDHIANA])
    second = scan.scan_points([LUDHIANA])

    assert first == FIRMS_SIGNALS + OPENAQ_SIGNALS
    assert second == 0
    assert len(store.all_signals()) == first


def test_overlapping_scan_points_count_one_detection_once(sources):
    """Two points 900 m apart see the same fire. It is still one fire."""
    sources()

    new = scan.scan_points([LUDHIANA, NEXT_DOOR])

    assert new == FIRMS_SIGNALS + OPENAQ_SIGNALS
    assert len(store.all_signals()) == new


# --------------------------------------------------------------------------- #
# Degrading rather than failing
# --------------------------------------------------------------------------- #


def test_an_error_from_one_source_still_yields_the_others_signals(sources):
    """Tools report failure as `{"error": ...}` rather than raising.

    A scan that discarded the satellite detections it already had because OpenAQ
    was briefly down would lose real evidence to an unrelated outage.
    """
    sources(openaq={"error": "OpenAQ locations request failed: timed out", "stations": []})

    new = scan.scan_points([LUDHIANA])

    assert new == FIRMS_SIGNALS
    assert all(s.source is SignalSource.SATELLITE for s in store.all_signals())


def test_a_source_that_raises_costs_one_source_not_the_scan(sources):
    """Belt and braces: the convention says tools do not raise, and this is the
    one caller that runs unattended, where being wrong about that is expensive."""

    def explode():
        raise RuntimeError("httpx grew a new failure mode")

    sources(firms=explode)

    new = scan.scan_points([LUDHIANA])

    assert new == OPENAQ_SIGNALS


def test_run_once_reports_a_failed_source_rather_than_reporting_clean_air(
    sources, monkeypatch, without_corridors
):
    """An expired key and a quiet sky look identical in a signal count.

    They are the two states most worth telling apart, so the summary carries the
    sentence the tool gave rather than only a number.
    """
    sources(firms={"error": "FIRMS_MAP_KEY is not configured", "detections": []})
    monkeypatch.setattr(settings, "vayudoot_scan_enabled", True)
    stored_case()

    summary = scan.run_once()

    assert summary["enabled"] is True
    assert summary["points_scanned"] == 1
    assert summary["signals_found"] == OPENAQ_SIGNALS
    assert summary["signals_new"] == OPENAQ_SIGNALS
    assert any("FIRMS_MAP_KEY" in error for error in summary["errors"])


# --------------------------------------------------------------------------- #
# Retention
# --------------------------------------------------------------------------- #


def test_signals_past_the_retention_window_are_history_not_live():
    """Detection reads the live window; the record keeps everything.

    A fire that burnt out last month must not hold a dot on a map of what is
    happening now, and deleting the observation would throw away the evidence
    that it happened at all.
    """
    now = datetime.now(UTC)
    beyond = now - timedelta(days=settings.vayudoot_signal_retention_days + 5)

    store.save_signals(
        [
            a_signal("viirs:recent", observed_at=now - timedelta(hours=2)),
            a_signal("viirs:ancient", observed_at=beyond),
        ]
    )

    live = {s.signal_id for s in store.live_signals()}
    assert live == {"viirs:recent"}
    assert {s.signal_id for s in store.all_signals()} == {"viirs:recent", "viirs:ancient"}


def test_a_naive_timestamp_does_not_break_the_retention_comparison():
    """Not every source states a zone, and comparing naive with aware raises."""
    naive = datetime.now(UTC).replace(tzinfo=None)
    store.save_signals([a_signal("viirs:naive", observed_at=naive)])

    assert len(store.live_signals()) == 1


# --------------------------------------------------------------------------- #
# Where the scan looks, and whether it looks at all
# --------------------------------------------------------------------------- #


def test_the_scan_is_a_no_op_when_disabled(sources, monkeypatch):
    """Off by default, and off means no external call is made at all.

    An unattended loop against two external APIs is switched on by whoever is
    watching the quota. A scan that still fetched and merely declined to store
    would have spent the requests anyway.
    """
    calls = sources()
    monkeypatch.setattr(settings, "vayudoot_scan_enabled", False)
    stored_case()

    summary = scan.run_once()

    assert summary == {
        "enabled": False,
        "points_scanned": 0,
        "signals_found": 0,
        "signals_new": 0,
        "errors": [],
    }
    assert calls["firms"] == []
    assert calls["openaq"] == []
    assert store.all_signals() == []


def test_scan_targets_come_from_the_places_the_instance_knows_about(without_corridors):
    stored_case("VD-SCAN0001", at=LUDHIANA)
    stored_case("VD-SCAN0002", at=DELHI)

    targets = scan.scan_targets()

    assert set(targets) == {LUDHIANA, DELHI}


def test_scan_targets_drop_points_that_would_fetch_the_same_data(without_corridors):
    """Two cases in the same neighbourhood are one scan, not two.

    Each scan covers a radius; two points well inside it are the same square of
    sky and the same nearest station, and the second fetch buys nothing but a
    request against a free tier.
    """
    stored_case("VD-SCAN0001", at=LUDHIANA)
    stored_case("VD-SCAN0002", at=NEXT_DOOR)

    targets = scan.scan_targets()

    assert len(targets) == 1
    assert targets[0] in {LUDHIANA, NEXT_DOOR}


def test_a_scan_with_nowhere_to_look_is_honest_about_it(sources, monkeypatch, without_corridors):
    sources()
    monkeypatch.setattr(settings, "vayudoot_scan_enabled", True)

    summary = scan.run_once()

    assert summary["points_scanned"] == 0
    assert summary["signals_found"] == 0
    assert summary["errors"] == []


def test_corridors_give_the_scan_reach_where_nobody_has_reported():
    """The other half of a non-empty map, and the more important half.

    Case coordinates only ever point the scan at places somebody has already
    reported from. Corridor waypoints cross states that have never submitted
    anything, which is where satellite evidence has to arrive on its own.
    """
    pytest.importorskip("vayudoot.corridors")

    assert store.all_cases() == []
    assert scan.scan_targets() != []
