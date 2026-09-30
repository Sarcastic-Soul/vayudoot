"""CPCB's live station feed: parsing it, filtering it, and reading it as signals.

Offline. The feed document below has the shape the real one had when this was
written (`airquality.cpcb.gov.in/caaqms/rss_feed`), cut to three stations.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from vayudoot import hotspots
from vayudoot.schemas import SignalSource
from vayudoot.tools import cpcb

FEED = b"""<?xml version='1.0' encoding='UTF-8'?>
<AqIndex>
<Country id="India">
<State id="Delhi">
<City id="Delhi">
<Station id="Anand Vihar, Delhi - DPCC" lastupdate="30-09-2026 19:00:00"
         latitude="28.646835" longitude="77.316032">
<Pollutant_Index id="PM2.5" Min="120" Max="310" Avg="248" Hourly_sub_index="260" />
<Pollutant_Index id="PM10" Min="90" Max="240" Avg="180" Hourly_sub_index="190" />
<Pollutant_Index id="NO2" Min="20" Max="60" Avg="41" Hourly_sub_index="44" />
<Pollutant_Index id="CO" Min="NA" Max="NA" Avg="NA" Hourly_sub_index="NA" />
<Air_Quality_Index Value="248" Predominant_Parameter="PM2.5" />
</Station>
<Station id="No position, Delhi - DPCC" lastupdate="30-09-2026 19:00:00">
<Pollutant_Index id="PM2.5" Min="1" Max="400" Avg="300" Hourly_sub_index="300" />
<Air_Quality_Index Value="300" Predominant_Parameter="PM2.5" />
</Station>
</City>
</State>
<State id="Andhra Pradesh">
<City id="Anantapur">
<Station id="Gulzarpet, Anantapur - APPCB" lastupdate="30-09-2026 19:00:00"
         latitude="14.675886" longitude="77.593027">
<Pollutant_Index id="PM10" Min="42" Max="381" Avg="84" Hourly_sub_index="74" />
<Air_Quality_Index Value="84" Predominant_Parameter="PM10" />
</Station>
</City>
</State>
</Country>
</AqIndex>
"""

ANAND_VIHAR = (28.646835, 77.316032)


@pytest.fixture
def feed(monkeypatch):
    """Serve `FEED` in place of the network, and count the fetches."""
    fetches = []

    class Response:
        content = FEED

        def raise_for_status(self):
            pass

    def fake_get(url, **_):
        fetches.append(url)
        return Response()

    monkeypatch.setattr(cpcb.httpx, "get", fake_get)
    monkeypatch.setattr(cpcb, "_cache", None)
    return fetches


def test_the_feed_parses_to_stations_with_position_time_and_sub_indices():
    stations = cpcb.parse(FEED)

    # The station with no coordinates cannot be placed, so it is not a station.
    assert [s["name"] for s in stations] == [
        "Anand Vihar, Delhi - DPCC",
        "Gulzarpet, Anantapur - APPCB",
    ]
    anand = stations[0]
    assert anand["aqi"] == 248
    # `NA` is a pollutant that did not report, not a zero.
    assert anand["sub_indices"] == {"PM2.5": 248, "PM10": 180, "NO2": 41}
    # `lastupdate` is IST with no offset written down.
    observed = datetime.fromisoformat(anand["observed_at"])
    assert observed.astimezone(UTC) == datetime(2026, 9, 30, 13, 30, tzinfo=UTC)


def test_a_query_returns_only_stations_in_range_nearest_first(feed):
    result = cpcb.get_cpcb_stations(*ANAND_VIHAR, radius_km=25)

    assert [s["name"] for s in result["stations"]] == ["Anand Vihar, Delhi - DPCC"]
    assert result["stations"][0]["distance_km"] == 0


def test_one_fetch_serves_every_scan_point_in_a_pass(feed):
    """The feed is the whole country in one document. Forty scan points must
    cost one request, not forty."""
    for _ in range(40):
        cpcb.get_cpcb_stations(*ANAND_VIHAR)

    assert len(feed) == 1


def test_a_failed_fetch_is_an_error_payload_not_an_exception(monkeypatch):
    def refuse(*_, **__):
        raise OSError("Connection refused")

    monkeypatch.setattr(cpcb.httpx, "get", refuse)
    monkeypatch.setattr(cpcb, "_cache", None)

    result = cpcb.get_cpcb_stations(*ANAND_VIHAR)

    assert "Connection refused" in result["error"]
    assert result["stations"] == []


def test_only_a_sub_index_past_the_standard_becomes_a_signal(feed):
    """A sub-index of 100 is the national standard by construction of the
    National AQI. PM2.5 at 248 and PM10 at 180 are past it; NO2 at 41 is clean
    air, and clean air must not put a dot on the map."""
    signals = hotspots.signals_from_cpcb(cpcb.get_cpcb_stations(*ANAND_VIHAR))

    assert sorted(s.signal_id for s in signals) == [
        "station:cpcb:Anand Vihar, Delhi - DPCC:pm10",
        "station:cpcb:Anand Vihar, Delhi - DPCC:pm25",
    ]
    assert all(s.source is SignalSource.GROUND_STATION for s in signals)
    # Placed at the instrument, never at the point that was searched from.
    assert {(s.latitude, s.longitude) for s in signals} == {ANAND_VIHAR}
    pm25 = next(s for s in signals if s.signal_id.endswith("pm25"))
    assert pm25.magnitude == pytest.approx((248 - 100) / 200)
    assert "sub-index 248" in pm25.summary


def test_a_station_at_the_standard_is_not_past_it():
    payload = {
        "stations": [
            {"name": "S", "latitude": 1.0, "longitude": 2.0, "sub_indices": {"PM10": 100.0}}
        ]
    }

    assert hotspots.signals_from_cpcb(payload) == []
