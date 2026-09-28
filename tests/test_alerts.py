"""Hotspot alerts: the route from a detection nobody reported to an authority.

Three properties are asserted here beyond the happy path. Corroboration gates
the alert, because an alert is an outward claim in the system's own name (hard
constraint 7). Nothing is written to the outbox until a person confirms (hard
constraint 2). And the alert describes an area, never an address — the street a
geocoder returns must not reach the model or the envelope.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from google.genai.errors import ClientError
from httpx import ASGITransport, AsyncClient

from fakes import StubAgent, alert_brief, imagery_assessment
from vayudoot import alerts, api, hotspots, store
from vayudoot.agents import alert as alert_agent
from vayudoot.config import Settings, settings
from vayudoot.schemas import (
    AlertStatus,
    Exposure,
    HotspotAlert,
    HotspotSnapshot,
    ImageryReading,
    PollutionType,
    Signal,
    SignalSource,
)

#: What Nominatim says about a point in Ludhiana. `display_name` carries a plot
#: and a street on purpose: it is exactly what must never reach an alert.
LUDHIANA = {
    "display_name": "Plot 14, Industrial Road, Focal Point, Ludhiana, Punjab, 141010, India",
    "suburb": "Focal Point",
    "city": "Ludhiana",
    "district": "Ludhiana",
    "state": "Punjab",
    "postcode": "141010",
    "country": "India",
    "country_code": "in",
}

LAHORE = {
    "display_name": "Lahore, Punjab, Pakistan",
    "city": "Lahore",
    "district": "",
    "state": "Punjab",
    "country": "Pakistan",
    "country_code": "pk",
}


@pytest.fixture
async def client():
    transport = ASGITransport(app=api.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def geocode(monkeypatch):
    """Answer reverse geocoding from a fixed payload; returns a setter."""
    answer = {"value": LUDHIANA}
    monkeypatch.setattr(alerts, "reverse_geocode", lambda *a, **k: answer["value"])

    def use(payload: dict) -> None:
        answer["value"] = payload

    return use


@pytest.fixture
def stub(monkeypatch) -> StubAgent:
    """Replace the fast-tier alert agent. Nothing in this suite needs a provider."""
    agent = StubAgent(alert_brief())
    monkeypatch.setattr(alert_agent, "build_alert_agent", lambda: agent)
    return agent


def _signal(source: SignalSource, *, lat=30.9010, lon=75.8573, hours_ago=6, n=0) -> Signal:
    return Signal(
        source=source,
        signal_id=f"{source.value}:{n}:{lat}:{lon}",
        latitude=lat,
        longitude=lon,
        observed_at=datetime.now(UTC) - timedelta(hours=hours_ago),
        strength=0.85,
        magnitude=0.6,
        summary=(
            "Satellite thermal detection, 14.2 MW radiative power"
            if source is SignalSource.SATELLITE
            else "Citizen sensor asha-home-01: pm25 180 ug/m3"
        ),
    )


def corroborated_hotspot_id() -> str:
    """Store two satellite detections and return the hotspot they form."""
    store.save_signals(
        [_signal(SignalSource.SATELLITE, n=1), _signal(SignalSource.SATELLITE, n=2, hours_ago=3)]
    )
    (spot,) = hotspots.current()
    assert spot.corroborated
    return spot.hotspot_id


def uncorroborated_hotspot_id() -> str:
    """A hotspot held up only by a citizen's own sensor."""
    store.save_signals([_signal(SignalSource.CITIZEN_SENSOR, n=1)])
    (spot,) = hotspots.current()
    assert not spot.corroborated
    return spot.hotspot_id


# --------------------------------------------------------------------------- #
# Drafting and its gates
# --------------------------------------------------------------------------- #


async def test_an_unknown_hotspot_is_404(client, stub, geocode):
    resp = await client.post("/hotspots/VDH-NOPE0000/alert")
    assert resp.status_code == 404
    assert stub.prompts == []


async def test_an_uncorroborated_hotspot_cannot_be_alerted(client, stub, geocode):
    """Hard constraint 7: citizen-only evidence never becomes a claim in our name.

    Refused before any model call and before anything is stored, so a
    coordinated campaign cannot even spend the quota trying.
    """
    hotspot_id = uncorroborated_hotspot_id()
    resp = await client.post(f"/hotspots/{hotspot_id}/alert")

    assert resp.status_code == 409
    assert "not corroborated" in resp.json()["detail"]
    assert "complaint" in resp.json()["detail"]
    assert stub.prompts == []
    assert store.all_alerts() == []


async def test_a_hotspot_outside_india_is_not_given_an_invented_authority(client, stub, geocode):
    """The table is Indian. The generic fallback would address a Pakistani fire
    to an Indian state-board placeholder, so the answer is a refusal pointing at
    federation instead."""
    geocode(LAHORE)
    hotspot_id = corroborated_hotspot_id()
    resp = await client.post(f"/hotspots/{hotspot_id}/alert")

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "Pakistan" in detail
    assert "federation" in detail
    assert stub.prompts == []
    assert store.all_alerts() == []


async def test_a_geocoder_failure_is_a_502_not_a_guess(client, stub, geocode):
    geocode({"error": "Nominatim request failed: timed out"})
    hotspot_id = corroborated_hotspot_id()
    resp = await client.post(f"/hotspots/{hotspot_id}/alert")
    assert resp.status_code == 502
    assert store.all_alerts() == []


async def test_drafting_holds_the_alert_and_sends_nothing(client, stub, geocode):
    """Hard constraint 2: a drafted alert waits for a person."""
    hotspot_id = corroborated_hotspot_id()
    resp = await client.post(f"/hotspots/{hotspot_id}/alert")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["status"] == AlertStatus.AWAITING_CONFIRMATION.value
    assert body["alert_id"].startswith("VDA-")
    assert body["hotspot_id"] == hotspot_id
    assert body["sent_at"] is None
    assert body["brief"]["subject"]
    assert body["hotspot"]["corroborated"] is True
    assert "signals" not in body["hotspot"]
    assert not settings.vayudoot_sandbox_outbox.exists() or not any(
        settings.vayudoot_sandbox_outbox.iterdir()
    )
    assert store.load_alert(body["alert_id"]) is not None


async def test_jurisdiction_is_the_table_entry_for_the_hotspot_centre(client, stub, geocode):
    """An unclear hotspot looks up the default category — the Air Act, one tier up."""
    hotspot_id = corroborated_hotspot_id()
    body = (await client.post(f"/hotspots/{hotspot_id}/alert")).json()

    j = body["jurisdiction"]
    assert j["authority_name"] == "Punjab Pollution Control Board"
    assert j["email"].endswith(".invalid")
    assert j["coverage"] == "exact"
    assert "Air (Prevention and Control of Pollution) Act" in j["statute"]
    assert "No model was involved" in j["reasoning"]


async def test_the_alert_describes_an_area_never_an_address(client, stub, geocode):
    """Constraint 7. The geocoder names a plot and a road; neither may reach the
    model, the stored alert or the envelope."""
    hotspot_id = corroborated_hotspot_id()
    body = (await client.post(f"/hotspots/{hotspot_id}/alert")).json()

    assert body["area"] == "Ludhiana, Punjab"
    for text in (body["facts"], stub.prompts[0]):
        assert "Plot 14" not in text
        assert "Industrial Road" not in text
        assert "Focal Point" not in text
        assert "radius" in text
        assert "not the location of any one site" in text


async def test_the_facts_block_is_what_the_model_was_given(client, stub, geocode):
    hotspot_id = corroborated_hotspot_id()
    body = (await client.post(f"/hotspots/{hotspot_id}/alert")).json()
    facts = body["facts"]

    assert facts in stub.prompts[0]
    assert "Independently corroborated: yes" in facts
    assert "satellite thermal detections (NASA FIRMS VIIRS): 2" in facts
    assert "14.2 MW" in facts
    # Exposure is filled in by `hotspots` when the settlement table covers the
    # centre; either way the facts say something about it rather than nothing.
    assert "Population within" in facts or "Population nearby: not estimated." in facts
    assert "Region: Punjab" in stub.prompts[0]


async def test_citizen_signal_summaries_stay_out_of_the_facts(client, stub, geocode):
    """A citizen sensor's summary carries an id its owner chose. The count is
    enough; what a person typed is not forwarded to an authority."""
    store.save_signals(
        [_signal(SignalSource.SATELLITE, n=1), _signal(SignalSource.CITIZEN_SENSOR, n=2)]
    )
    (spot,) = hotspots.current()
    body = (await client.post(f"/hotspots/{spot.hotspot_id}/alert")).json()

    assert "citizen low-cost sensor readings: 1" in body["facts"]
    assert "asha-home-01" not in body["facts"]


async def test_a_pending_alert_is_returned_rather_than_drafted_again(client, stub, geocode):
    """Drafting costs a model call; asking twice must not spend two."""
    hotspot_id = corroborated_hotspot_id()
    first = (await client.post(f"/hotspots/{hotspot_id}/alert")).json()
    second = (await client.post(f"/hotspots/{hotspot_id}/alert")).json()
    assert second["alert_id"] == first["alert_id"]
    assert len(stub.prompts) == 1

    third = (await client.post(f"/hotspots/{hotspot_id}/alert?redraft=true")).json()
    assert third["alert_id"] != first["alert_id"]
    assert len(stub.prompts) == 2


async def test_a_rate_limited_draft_is_a_503_with_a_sentence(client, geocode, monkeypatch):
    class Throttled:
        async def invoke_async(self, *a, **k):
            raise ClientError(
                429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "quota"}}
            )

    monkeypatch.setattr(alert_agent, "build_alert_agent", lambda: Throttled())
    hotspot_id = corroborated_hotspot_id()
    resp = await client.post(f"/hotspots/{hotspot_id}/alert")
    assert resp.status_code == 503
    assert "quota" in resp.json()["detail"]
    assert store.all_alerts() == []


# --------------------------------------------------------------------------- #
# Confirming and reading back
# --------------------------------------------------------------------------- #


async def test_confirm_writes_the_envelope_to_the_sandbox_once(client, stub, geocode):
    hotspot_id = corroborated_hotspot_id()
    alert_id = (await client.post(f"/hotspots/{hotspot_id}/alert")).json()["alert_id"]

    before = await client.get(f"/alerts/{alert_id}/envelope")
    assert before.status_code == 409

    sent = (await client.post(f"/alerts/{alert_id}/confirm")).json()
    assert sent["status"] == AlertStatus.SENT.value
    assert sent["sent_at"] is not None

    envelope = (await client.get(f"/alerts/{alert_id}/envelope")).text
    assert "To: ppcb@example.invalid" in envelope
    assert f"Alert-Id: {alert_id}" in envelope
    assert f"Hotspot-Id: {hotspot_id}" in envelope
    assert "X-Vayudoot-Mode: SANDBOX" in envelope
    assert "Suggested verification steps:" in envelope
    assert "FACTS" in envelope and "not the location of any one site" in envelope
    assert "Punjabi:" in envelope
    assert "does not identify or accuse any party" in envelope

    again = await client.post(f"/alerts/{alert_id}/confirm")
    assert again.status_code == 409


async def test_alerts_list_newest_first_and_filter_by_hotspot(client, stub, geocode):
    hotspot_id = corroborated_hotspot_id()
    first = (await client.post(f"/hotspots/{hotspot_id}/alert")).json()["alert_id"]
    second = (await client.post(f"/hotspots/{hotspot_id}/alert?redraft=true")).json()["alert_id"]

    listed = [a["alert_id"] for a in (await client.get("/alerts")).json()]
    assert listed == [second, first]

    assert (await client.get("/alerts?hotspot_id=VDH-OTHER000")).json() == []
    assert len((await client.get(f"/alerts?hotspot_id={hotspot_id}")).json()) == 2

    assert (await client.get(f"/alerts/{first}")).json()["alert_id"] == first
    assert (await client.get("/alerts/VDA-NOPE0000")).status_code == 404
    assert (await client.get("/alerts/..%2Fcases")).status_code == 404


# --------------------------------------------------------------------------- #
# What the facts block carries when it has more to say
# --------------------------------------------------------------------------- #


async def test_a_cached_imagery_reading_is_cited_as_context_not_evidence(client, stub, geocode):
    hotspot_id = corroborated_hotspot_id()
    reading = ImageryReading(
        **imagery_assessment().model_dump(),
        hotspot_id=hotspot_id,
        image_date="2026-09-27",
        layer="VIIRS_SNPP_CorrectedReflectance_TrueColor",
        bbox=[30.7, 75.6, 31.1, 76.1],
    )
    store.save_imagery(reading, b"\xff\xd8 not really a jpeg")

    body = (await client.post(f"/hotspots/{hotspot_id}/alert")).json()
    assert body["imagery"]["image_date"] == "2026-09-27"
    assert "Satellite image reading (2026-09-27" in body["facts"]
    assert "Smoke plume visible: yes" in body["facts"]
    assert "does not count towards corroboration" in body["facts"]


def test_exposure_is_stated_as_a_lower_bound_when_present():
    now = datetime.now(UTC)
    snapshot = HotspotSnapshot(
        hotspot_id="VDH-TEST0001",
        pollution_type=PollutionType.CROP_RESIDUE_BURNING,
        centre_latitude=30.9,
        centre_longitude=75.85,
        radius_km=1.4,
        confidence=0.9,
        severity="high",
        corroborated=True,
        signal_count=3,
        source_counts={SignalSource.SATELLITE: 2, SignalSource.CITIZEN_REPORT: 1},
        first_seen_at=now - timedelta(days=2),
        last_seen_at=now,
        span_days=2,
        exposure=Exposure(
            population=1_618_879,
            radius_km=10,
            towns=["Ludhiana"],
            settlement_count=1,
        ),
    )
    facts = alerts.facts_block(snapshot, "Ludhiana, Punjab")
    assert "Population within 10 km: at least 1,618,879" in facts
    assert "A lower bound." in facts
    assert "Pollution type: crop residue burning" in facts
    assert "citizen photograph reports: 1" in facts


def test_the_alert_agent_is_on_the_fast_tier(monkeypatch):
    """Constraint 5: it summarises text it was handed, calling nothing."""
    tiers: list[str] = []
    monkeypatch.setattr(alert_agent, "build_model", lambda **k: tiers.append(k["tier"]))
    monkeypatch.setattr(alert_agent, "Agent", lambda **k: None)
    alert_agent.build_alert_agent()
    assert tiers == ["fast"]


# --------------------------------------------------------------------------- #
# Postgres
# --------------------------------------------------------------------------- #

_REAL_DATABASE_URL = Settings().database_url


@pytest.mark.skipif(not _REAL_DATABASE_URL, reason="DATABASE_URL is not configured")
async def test_alerts_round_trip_through_postgres(monkeypatch, stub, geocode):
    """The production backend. The alert is drafted against the file store so no
    test signals reach the real database; only the alert row does, and it is
    deleted afterwards."""
    hotspot_id = corroborated_hotspot_id()
    (spot,) = hotspots.current()
    alert = await alerts.draft_alert(spot)
    alert.alert_id = "VDA-TESTPG01"

    monkeypatch.setattr(settings, "database_url", _REAL_DATABASE_URL)
    try:
        store.save_alert(alert)
        loaded = store.load_alert("VDA-TESTPG01")
        assert isinstance(loaded, HotspotAlert)
        assert loaded.hotspot_id == hotspot_id
        assert loaded.status is AlertStatus.AWAITING_CONFIRMATION
        assert loaded.facts == alert.facts

        loaded.status = AlertStatus.SENT
        store.save_alert(loaded)
        assert store.load_alert("VDA-TESTPG01").status is AlertStatus.SENT
        assert "VDA-TESTPG01" in [a.alert_id for a in store.all_alerts()]
    finally:
        with store._pg().connection() as conn:
            conn.execute("DELETE FROM alerts WHERE alert_id LIKE 'VDA-TESTPG%'")
