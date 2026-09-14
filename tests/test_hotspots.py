"""Hotspot detection.

Two of these tests exist to hold a hard constraint rather than to check a
function, and they are marked where they appear: an uncorroborated hotspot's
confidence cap, and the minimum published radius. Both are hard constraint 7 in
`CLAUDE.md` — a hotspot is a public claim about a place — and a change that makes
either fail is a safety regression, not a failing test to update.

The third property worth naming: a hotspot must be able to exist with no citizen
involvement at all. That is the whole of the v0.3 reframe, and
`test_satellite_alone_raises_a_hotspot` is where it is enforced.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from vayudoot import hotspots
from vayudoot.config import settings
from vayudoot.schemas import (
    Case,
    CaseStatus,
    EvidencePacket,
    PollutionType,
    Report,
    Signal,
    SignalSource,
)

NOW = datetime(2026, 9, 14, 6, 0, tzinfo=UTC)

# Two points about 900 m apart in Delhi: inside the 2 km detection radius,
# outside the 500 m clustering radius. Enough to show the two modules answer
# different questions over the same ground.
HERE = (28.6139, 77.2090)
NEAR = (28.6215, 77.2115)
FAR = (28.7500, 77.4000)


def signal(
    source: SignalSource = SignalSource.CITIZEN_REPORT,
    *,
    at: tuple[float, float] = HERE,
    when: datetime | None = None,
    pollution_type: PollutionType = PollutionType.UNCLEAR,
    strength: float = 0.8,
    magnitude: float = 0.5,
    signal_id: str = "",
) -> Signal:
    return Signal(
        source=source,
        signal_id=signal_id or f"{source.value}-{at[0]}-{when or NOW}",
        latitude=at[0],
        longitude=at[1],
        observed_at=when or NOW,
        pollution_type=pollution_type,
        strength=strength,
        magnitude=magnitude,
    )


def case(
    case_id: str = "VD-TEST0001",
    *,
    at: tuple[float, float] = HERE,
    when: datetime | None = None,
    status: CaseStatus = CaseStatus.FILED,
    pollution_type: PollutionType = PollutionType.OPEN_WASTE_BURNING,
    confidence: float = 0.9,
    severity: str = "high",
    with_evidence: bool = True,
) -> Case:
    evidence = (
        EvidencePacket(
            pollution_type=pollution_type,
            confidence=confidence,
            severity=severity,
            visible_indicators=["thick smoke"],
        )
        if with_evidence
        else None
    )
    return Case(
        case_id=case_id,
        status=status,
        report=Report(
            report_id=f"R-{case_id}",
            latitude=at[0],
            longitude=at[1],
            observed_at=when or NOW,
        ),
        evidence=evidence,
    )


# --------------------------------------------------------------------------- #
# The reframe: a hotspot does not need a citizen
# --------------------------------------------------------------------------- #


def test_satellite_alone_raises_a_hotspot():
    """The v0.3 reframe in one assertion.

    Clustering can only produce a group where somebody has already reported.
    Detection must not inherit that, or the map is empty everywhere nobody has
    used the app — which is most of India, and an empty map reads as clean air.
    """
    found = hotspots.detect([signal(SignalSource.SATELLITE)])

    assert len(found) == 1
    assert found[0].signal_count == 1
    assert found[0].case_ids == []
    assert found[0].corroborated is True


def test_a_station_exceedance_alone_raises_a_hotspot():
    found = hotspots.detect([signal(SignalSource.GROUND_STATION)])
    assert len(found) == 1
    assert found[0].corroborated is True


def test_a_citizen_photograph_upgrades_a_satellite_detection_rather_than_sitting_beside_it():
    """The division of labour the whole design rests on.

    VIIRS sees heat and cannot say what is burning. The photograph says. They
    must end up as one hotspot carrying the classification, not as two dots.
    """
    found = hotspots.detect(
        [
            signal(SignalSource.SATELLITE, at=HERE),
            signal(
                SignalSource.CITIZEN_REPORT,
                at=NEAR,
                pollution_type=PollutionType.OPEN_WASTE_BURNING,
            ),
        ]
    )

    assert len(found) == 1
    assert found[0].pollution_type is PollutionType.OPEN_WASTE_BURNING
    assert found[0].signal_count == 2
    assert found[0].source_counts == {
        SignalSource.CITIZEN_REPORT: 1,
        SignalSource.SATELLITE: 1,
    }


# --------------------------------------------------------------------------- #
# Hard constraint 7: a hotspot is a public claim about a place
# --------------------------------------------------------------------------- #


def test_citizen_reports_alone_cannot_climb_past_the_uncorroborated_cap():
    """HARD CONSTRAINT 7. Not a tuning assertion — do not relax this to pass.

    Volume is exactly what a coordinated campaign can manufacture, so the cap is
    a cap and not a penalty: twenty confident reports must not out-rank one
    satellite detection, because twenty accounts are cheaper to obtain than an
    instrument in orbit.
    """
    many = [
        signal(
            SignalSource.CITIZEN_REPORT,
            at=HERE,
            when=NOW + timedelta(hours=n),
            pollution_type=PollutionType.OPEN_WASTE_BURNING,
            strength=1.0,
            signal_id=f"case-{n}",
        )
        for n in range(20)
    ]

    found = hotspots.detect(many)

    assert len(found) == 1
    assert found[0].corroborated is False
    assert found[0].confidence <= settings.vayudoot_hotspot_uncorroborated_cap


def test_one_independent_signal_lifts_the_cap():
    """The other half of the same rule: corroboration is what unlocks confidence."""
    reports = [
        signal(
            SignalSource.CITIZEN_REPORT,
            when=NOW + timedelta(hours=n),
            pollution_type=PollutionType.OPEN_WASTE_BURNING,
            strength=1.0,
            signal_id=f"case-{n}",
        )
        for n in range(3)
    ]

    without = hotspots.detect(reports)[0]
    with_satellite = hotspots.detect([*reports, signal(SignalSource.SATELLITE)])[0]

    assert without.confidence <= settings.vayudoot_hotspot_uncorroborated_cap
    assert with_satellite.confidence > without.confidence


def test_a_hotspot_is_never_published_tighter_than_the_minimum_radius():
    """HARD CONSTRAINT 7. Not a tuning assertion — do not relax this to pass.

    Two signals at identical coordinates have a true spread of zero. Published
    at zero, the hotspot is a pin on a building and therefore a public
    accusation against whoever occupies it, with no name needed.
    """
    found = hotspots.detect(
        [
            signal(SignalSource.SATELLITE, at=HERE, signal_id="a"),
            signal(SignalSource.SATELLITE, at=HERE, signal_id="b"),
        ]
    )

    assert found[0].radius_km >= settings.vayudoot_hotspot_min_radius_km


def test_a_wider_spread_is_reported_at_its_true_radius():
    """The floor is a floor, not a fixed size — a real spread must still show.

    It takes three signals to get past it, and that is arithmetic rather than an
    awkward fixture. With two signals the centroid is the midpoint, so the radius
    is half the separation, and the separation cannot exceed the 2 km detection
    radius — so a two-signal hotspot always publishes at the 1 km floor. Three
    in a line chain outwards and the true spread shows.
    """
    found = hotspots.detect(
        [
            signal(SignalSource.SATELLITE, at=(28.6139, 77.2090), signal_id="a"),
            signal(SignalSource.SATELLITE, at=(28.6139, 77.2213), signal_id="b"),
            signal(SignalSource.SATELLITE, at=(28.6139, 77.2336), signal_id="c"),
        ]
    )

    assert found[0].signal_count == 3
    assert found[0].radius_km > settings.vayudoot_hotspot_min_radius_km


# --------------------------------------------------------------------------- #
# Grouping
# --------------------------------------------------------------------------- #


def test_different_pollution_types_never_merge():
    """A waste fire and a construction site at one address are two problems.

    Merging them would put the wrong statute in the complaint drafted from the
    hotspot. Same rule as `clustering`, and for the same reason.
    """
    found = hotspots.detect(
        [
            signal(
                SignalSource.CITIZEN_REPORT,
                pollution_type=PollutionType.OPEN_WASTE_BURNING,
                signal_id="a",
            ),
            signal(
                SignalSource.CITIZEN_REPORT,
                pollution_type=PollutionType.CONSTRUCTION_DUST,
                signal_id="b",
            ),
        ]
    )

    assert len(found) == 2
    assert {h.pollution_type for h in found} == {
        PollutionType.OPEN_WASTE_BURNING,
        PollutionType.CONSTRUCTION_DUST,
    }


def test_signals_beyond_the_radius_are_separate_hotspots():
    found = hotspots.detect(
        [
            signal(SignalSource.SATELLITE, at=HERE, signal_id="a"),
            signal(SignalSource.SATELLITE, at=FAR, signal_id="b"),
        ]
    )
    assert len(found) == 2


def test_the_window_is_a_maximum_gap_not_a_maximum_age():
    """A site burning fortnightly for months is one event, not many.

    Consecutive signals inside the window chain, however old the first is.
    """
    days = settings.vayudoot_hotspot_window_days
    found = hotspots.detect(
        [
            signal(SignalSource.SATELLITE, when=NOW - timedelta(days=days * 3), signal_id="a"),
            signal(SignalSource.SATELLITE, when=NOW - timedelta(days=days * 2), signal_id="b"),
            signal(SignalSource.SATELLITE, when=NOW - timedelta(days=days), signal_id="c"),
            signal(SignalSource.SATELLITE, when=NOW, signal_id="d"),
        ]
    )

    assert len(found) == 1
    assert found[0].signal_count == 4
    assert found[0].span_days == days * 3


def test_a_gap_wider_than_the_window_splits_the_hotspot():
    found = hotspots.detect(
        [
            signal(
                SignalSource.SATELLITE,
                when=NOW - timedelta(days=settings.vayudoot_hotspot_window_days * 2 + 1),
                signal_id="a",
            ),
            signal(SignalSource.SATELLITE, when=NOW, signal_id="b"),
        ]
    )
    assert len(found) == 2


def test_the_hotspot_id_is_stable_as_the_hotspot_grows():
    """A hotspot that is linked to or cited must keep resolving as signals join."""
    seed = signal(
        SignalSource.CITIZEN_REPORT,
        pollution_type=PollutionType.OPEN_WASTE_BURNING,
        signal_id="seed",
    )
    later = signal(
        SignalSource.SATELLITE,
        when=NOW + timedelta(days=1),
        signal_id="later",
    )

    first = hotspots.detect([seed])[0]
    grown = hotspots.detect([seed, later])[0]

    assert first.hotspot_id == grown.hotspot_id
    assert grown.signal_count == 2


def test_detection_is_ordered_by_confidence():
    found = hotspots.detect(
        [
            signal(SignalSource.SATELLITE, at=HERE, strength=0.9, signal_id="strong"),
            signal(SignalSource.SATELLITE, at=FAR, strength=0.3, signal_id="weak"),
        ]
    )
    assert [h.confidence for h in found] == sorted(
        (h.confidence for h in found), reverse=True
    )


# --------------------------------------------------------------------------- #
# Building signals from cases
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("status", sorted(hotspots.EXCLUDED_STATUSES))
def test_excluded_cases_never_become_signals(status):
    """A withdrawn or rejected case must not hold a place on a public map."""
    assert hotspots.signal_from_case(case(status=status)) is None


def test_an_unclassified_case_becomes_no_signal():
    """`unclear` means the evidence stage could not say what it was looking at.

    There is no event to place, and inventing one from a photograph nobody could
    read is the failure mode the confidence floor exists to prevent.
    """
    assert hotspots.signal_from_case(case(pollution_type=PollutionType.UNCLEAR)) is None


def test_a_case_without_evidence_becomes_no_signal():
    assert hotspots.signal_from_case(case(with_evidence=False)) is None


def test_the_evidence_confidence_carries_through_as_signal_strength():
    built = hotspots.signal_from_case(case(confidence=0.72))
    assert built is not None
    assert built.strength == pytest.approx(0.72)
    assert built.source is SignalSource.CITIZEN_REPORT
    assert built.is_independent is False


def test_a_resolved_case_still_counts():
    """A problem that was fixed and came back is the strongest pattern there is."""
    assert hotspots.signal_from_case(case(status=CaseStatus.RESOLVED)) is not None


# --------------------------------------------------------------------------- #
# Building signals from the satellite payload
# --------------------------------------------------------------------------- #


def test_satellite_detections_become_signals_at_their_own_coordinates():
    built = hotspots.signals_from_satellite(
        {
            "detections": [
                {
                    "latitude": 28.61,
                    "longitude": 77.20,
                    "acquired_date": "2026-09-14",
                    "acquired_time_utc": "0630",
                    "confidence": "high",
                    "fire_radiative_power_mw": "12.4",
                }
            ]
        }
    )

    assert len(built) == 1
    assert built[0].latitude == 28.61
    assert built[0].observed_at == datetime(2026, 9, 14, 6, 30, tzinfo=UTC)
    assert built[0].strength == 0.85
    assert built[0].is_independent is True


def test_a_thermal_detection_is_never_classified():
    """VIIRS sees heat, not fuel.

    Calling a detection over farmland crop residue burning would be the system
    inventing the single fact the complaint's statute turns on.
    """
    built = hotspots.signals_from_satellite(
        {"detections": [{"latitude": 30.2, "longitude": 75.8, "confidence": "nominal"}]}
    )
    assert built[0].pollution_type is PollutionType.UNCLEAR


def test_satellite_confidence_is_read_as_a_band_or_a_percentage():
    """FIRMS publishes one or the other depending on the product."""
    as_band = hotspots.signals_from_satellite(
        {"detections": [{"latitude": 1.0, "longitude": 1.0, "confidence": "l"}]}
    )
    as_percent = hotspots.signals_from_satellite(
        {"detections": [{"latitude": 1.0, "longitude": 1.0, "confidence": "80"}]}
    )

    assert as_band[0].strength == 0.3
    assert as_percent[0].strength == pytest.approx(0.8)


def test_an_errored_satellite_payload_yields_no_signals():
    """Tools return `{"error": ...}` rather than raising; detection must cope."""
    payload = {"error": "FIRMS request failed", "detections": []}
    assert hotspots.signals_from_satellite(payload) == []


# --------------------------------------------------------------------------- #
# Building signals from the station payload
# --------------------------------------------------------------------------- #


def station_payload(parameter: str, value: float) -> dict:
    return {
        "nearest_station": "Anand Vihar",
        "station_id": 1234,
        "latitude": 28.6469,
        "longitude": 77.3152,
        "measurements": [
            {
                "parameter": parameter,
                "value": value,
                "unit": "µg/m³",
                "measured_at": "2026-09-14T06:00:00+00:00",
            }
        ],
    }


def test_a_reading_below_its_standard_is_not_a_signal():
    """Clean air is not a weak signal. It is the absence of one.

    A station reporting normal values must never put a dot on the map, however
    many times it is read.
    """
    assert hotspots.signals_from_stations(station_payload("pm25", 40.0)) == []


def test_a_reading_above_its_standard_becomes_a_signal():
    """How far past the standard is the magnitude; the instrument is the strength.

    A station is believed because it is a reference-grade instrument, not because
    the number it reported is large.
    """
    built = hotspots.signals_from_stations(station_payload("pm25", 120.0))

    assert len(built) == 1
    assert built[0].source is SignalSource.GROUND_STATION
    assert built[0].magnitude == pytest.approx(0.5)
    assert built[0].strength == hotspots.STATION_RELIABILITY
    assert built[0].latitude == 28.6469


def test_magnitude_saturates_at_three_times_the_standard():
    built = hotspots.signals_from_stations(station_payload("pm25", 600.0))
    assert built[0].magnitude == 1.0


def test_the_signal_sits_at_the_station_not_at_the_coordinates_searched_from():
    """Placing it at the query point would draw a hotspot around whoever asked."""
    built = hotspots.signals_from_stations(station_payload("pm10", 300.0))
    assert (built[0].latitude, built[0].longitude) == (28.6469, 77.3152)


def test_a_payload_without_station_coordinates_yields_no_signals():
    """Older cached payloads predate the coordinates; they must not be guessed."""
    payload = station_payload("pm25", 500.0)
    del payload["latitude"]
    assert hotspots.signals_from_stations(payload) == []


def test_an_unknown_pollutant_has_no_standard_and_is_ignored():
    assert hotspots.signals_from_stations(station_payload("radon", 9999.0)) == []


def test_one_station_over_standard_on_two_pollutants_gives_two_signals():
    """Two observations of the same air, which is what they are."""
    payload = station_payload("pm25", 200.0)
    payload["measurements"].append(
        {
            "parameter": "no2",
            "value": 200.0,
            "unit": "µg/m³",
            "measured_at": "2026-09-14T06:00:00+00:00",
        }
    )

    built = hotspots.signals_from_stations(payload)
    assert len(built) == 2
    assert {s.signal_id for s in built} == {"station:1234:pm25", "station:1234:no2"}


# --------------------------------------------------------------------------- #
# Severity
# --------------------------------------------------------------------------- #


def test_severity_and_confidence_are_different_questions():
    """A single clear photograph of a small fire: sure it is real, small event.

    They are routinely far apart, and collapsing them into one number would lose
    the distinction an operations view is read for.
    """
    small_but_certain = hotspots.detect(
        [
            signal(SignalSource.SATELLITE, strength=0.95, signal_id="a"),
        ]
    )[0]
    persistent_but_faint = hotspots.detect(
        [
            signal(
                SignalSource.GROUND_STATION,
                when=NOW + timedelta(days=n),
                strength=0.3,
                signal_id=f"s{n}",
            )
            for n in range(8)
        ]
    )[0]

    # High confidence, and the severity of one modest event.
    assert small_but_certain.confidence > persistent_but_faint.confidence
    # Faint readings, but eight of them: more worth dispatching to than the
    # confidence alone suggests.
    assert persistent_but_faint.severity != "low"


def test_being_certain_of_a_small_thing_is_not_severe():
    """The regression this split exists to prevent.

    An earlier version fed `strength` into severity. Because a citizen signal's
    strength is the evidence stage's *confidence*, one clear photograph of a
    modest fire came out `severe` — a model being sure of what it saw reported
    as the event being serious. That is precisely the overclaim hard constraint 7
    is about, and on a public map it is the difference between information and
    alarm.
    """
    certain_but_small = hotspots.signal_from_case(
        case("VD-SMALL001", confidence=1.0, severity="low")
    )
    assert certain_but_small is not None

    found = hotspots.detect([certain_but_small])[0]

    assert found.severity == "low"
    # Still fully believed. The two numbers are independent, which is the point.
    assert found.confidence == pytest.approx(settings.vayudoot_hotspot_uncorroborated_cap)


def test_the_evidence_severity_band_carries_through_as_magnitude():
    bands = {
        "low": "low",
        "moderate": "moderate",
        "high": "high",
        "severe": "severe",
    }
    for band, expected in bands.items():
        built = hotspots.signal_from_case(case(f"VD-BAND{band}", severity=band))
        assert built is not None
        assert hotspots.detect([built])[0].severity == expected


def test_fire_radiative_power_is_the_satellite_magnitude():
    """FRP is the one genuinely physical magnitude any source here reports."""
    small = hotspots.signals_from_satellite(
        {"detections": [{"latitude": 1.0, "longitude": 1.0, "fire_radiative_power_mw": "5"}]}
    )
    large = hotspots.signals_from_satellite(
        {"detections": [{"latitude": 1.0, "longitude": 1.0, "fire_radiative_power_mw": "250"}]}
    )

    assert small[0].magnitude == pytest.approx(0.05)
    assert large[0].magnitude == 1.0


def test_a_detection_without_power_is_not_treated_as_a_small_one():
    """Absent is not small, so it falls to the middle rather than to zero."""
    built = hotspots.signals_from_satellite(
        {"detections": [{"latitude": 1.0, "longitude": 1.0, "confidence": "high"}]}
    )
    assert built[0].magnitude == 0.5


def test_persistence_raises_severity():
    """Ten of the same event is worse than one of it, at equal magnitude."""
    once = hotspots.detect([signal(SignalSource.SATELLITE, magnitude=0.7, signal_id="a")])[0]
    often = hotspots.detect(
        [
            signal(
                SignalSource.SATELLITE,
                when=NOW + timedelta(hours=n),
                magnitude=0.7,
                signal_id=f"s{n}",
            )
            for n in range(10)
        ]
    )[0]

    assert once.severity == "high"
    assert often.severity == "severe"


# --------------------------------------------------------------------------- #
# The HTTP surface
# --------------------------------------------------------------------------- #


@pytest.fixture
async def client():
    from httpx import ASGITransport, AsyncClient

    from vayudoot import api

    transport = ASGITransport(app=api.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_the_hotspots_endpoint_reports_what_the_store_supports(client, monkeypatch):
    from vayudoot import store

    monkeypatch.setattr(
        store,
        "all_cases",
        lambda: [
            case("VD-AAAA0001", at=HERE, when=NOW),
            case("VD-AAAA0002", at=NEAR, when=NOW + timedelta(hours=2)),
        ],
    )

    response = await client.get("/hotspots")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert sorted(body[0]["case_ids"]) == ["VD-AAAA0001", "VD-AAAA0002"]


async def test_the_hotspots_endpoint_publishes_the_corroboration_flag(client, monkeypatch):
    """The flag must travel with the confidence.

    An interface given the number without it would rank a hotspot nobody
    independent has confirmed alongside one an instrument recorded. Hard
    constraint 7.
    """
    from vayudoot import store

    monkeypatch.setattr(store, "all_cases", lambda: [case("VD-AAAA0003")])

    body = (await client.get("/hotspots")).json()

    assert body[0]["corroborated"] is False
    assert body[0]["confidence"] <= settings.vayudoot_hotspot_uncorroborated_cap


async def test_a_hotspot_can_be_fetched_by_its_id(client, monkeypatch):
    from vayudoot import store

    monkeypatch.setattr(store, "all_cases", lambda: [case("VD-AAAA0004")])

    listed = (await client.get("/hotspots")).json()[0]
    fetched = await client.get(f"/hotspots/{listed['hotspot_id']}")

    assert fetched.status_code == 200
    assert fetched.json()["hotspot_id"] == listed["hotspot_id"]


async def test_an_unknown_hotspot_is_a_404(client):
    assert (await client.get("/hotspots/VDH-NOTREAL")).status_code == 404


async def test_an_empty_store_is_an_empty_list_not_an_error(client, monkeypatch):
    from vayudoot import store

    monkeypatch.setattr(store, "all_cases", list)
    response = await client.get("/hotspots")

    assert response.status_code == 200
    assert response.json() == []


# --------------------------------------------------------------------------- #
# The join between scanned signals and citizen cases
# --------------------------------------------------------------------------- #


def test_scanned_signals_and_citizen_cases_are_detected_together(monkeypatch):
    """The two halves of the evidence must meet.

    `scan.py` fills the signal store and cases arrive from citizens. If
    `current()` read only one of them, the scan would fill a store nothing looks
    at — or the map would go back to being citizen-only, which is the state the
    v0.3 reframe exists to end.
    """
    from vayudoot import store

    monkeypatch.setattr(store, "all_cases", lambda: [case("VD-JOIN0001", at=HERE)])
    monkeypatch.setattr(
        store, "live_signals", lambda: [signal(SignalSource.SATELLITE, at=NEAR)]
    )

    found = hotspots.current()

    assert len(found) == 1
    assert found[0].corroborated is True
    assert found[0].case_ids == ["VD-JOIN0001"]
    assert found[0].signal_count == 2


def test_a_signal_present_in_both_sources_is_counted_once(monkeypatch):
    """Signal count drives severity and the agreement term in confidence.

    Two copies of one reading must never read as two instruments agreeing.
    """
    from vayudoot import store

    duplicated = signal(SignalSource.GROUND_STATION, signal_id="station:1234:pm25")
    monkeypatch.setattr(store, "all_cases", list)
    monkeypatch.setattr(store, "live_signals", lambda: [duplicated, duplicated])

    found = hotspots.current()

    assert found[0].signal_count == 1


def test_a_scan_alone_puts_hotspots_on_the_map(monkeypatch):
    """No citizen has used this instance, and the map is still not empty."""
    from vayudoot import store

    monkeypatch.setattr(store, "all_cases", list)
    monkeypatch.setattr(
        store,
        "live_signals",
        lambda: [signal(SignalSource.SATELLITE, at=FAR, signal_id="viirs:1")],
    )

    found = hotspots.current()

    assert len(found) == 1
    assert found[0].case_ids == []


# --------------------------------------------------------------------------- #
# Units
# --------------------------------------------------------------------------- #


def test_carbon_monoxide_in_micrograms_is_not_a_thousandfold_exceedance():
    """REGRESSION. Found by scanning Ludhiana with the real OpenAQ API.

    The NAAQS notification writes CO's 24-hour standard as 2 mg/m³ and the
    standards table copied that number verbatim, while OpenAQ reports CO in
    µg/m³. A real reading of 1680 µg/m³ — 1.68 mg/m³, comfortably below the
    standard — scored as a maximum-severity exceedance. Clean air rendering as a
    severe hotspot on a public map is exactly the harm hard constraint 7 is about.
    """
    payload = station_payload("co", 1680.0)
    payload["measurements"][0]["unit"] = "µg/m³"

    assert hotspots.signals_from_stations(payload) == []


def test_carbon_monoxide_genuinely_over_the_standard_is_still_a_signal():
    """The fix must not silence CO altogether."""
    payload = station_payload("co", 4000.0)
    payload["measurements"][0]["unit"] = "µg/m³"

    built = hotspots.signals_from_stations(payload)

    assert len(built) == 1
    assert built[0].magnitude == pytest.approx(0.5)


def test_a_reading_reported_in_milligrams_is_converted_before_comparing():
    """A source that does report mg/m³ must not be read as a thousand times less."""
    payload = station_payload("co", 4.0)
    payload["measurements"][0]["unit"] = "mg/m3"

    built = hotspots.signals_from_stations(payload)

    assert len(built) == 1
    assert built[0].magnitude == pytest.approx(0.5)


def test_an_unrecognised_unit_is_refused_rather_than_assumed():
    """Guessing wrong is how a thousand-fold error reaches the map.

    Refusing to guess costs one signal, which is the cheaper mistake.
    """
    payload = station_payload("pm25", 500.0)
    payload["measurements"][0]["unit"] = "parts per furlong"

    assert hotspots.signals_from_stations(payload) == []


def test_a_missing_unit_is_read_as_micrograms():
    """Most sources report µg/m³ and many omit the unit; that is a fair default.

    Assuming the common case when nothing is stated is different from assuming a
    named unit means something other than what it says.
    """
    payload = station_payload("pm25", 200.0)
    del payload["measurements"][0]["unit"]

    assert len(hotspots.signals_from_stations(payload)) == 1
