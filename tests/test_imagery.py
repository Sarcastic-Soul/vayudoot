"""Satellite imagery read by a model: the fetch, the reading, the cache, the routes.

The test that matters most is the last one. A model's reading of a coarse
picture is an annotation and must never become a corroborating signal; the
module docstring of `agents/imagery.py` says why, and that test is where the
decision is held in place.
"""

from __future__ import annotations

import io
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from fakes import StubAgent, imagery_assessment
from vayudoot import api, hotspots, store
from vayudoot.agents import imagery as imagery_agent
from vayudoot.schemas import (
    IMAGERY_DISCLAIMER,
    INDEPENDENT_SOURCES,
    ImageryReading,
    Signal,
    SignalSource,
)
from vayudoot.tools import imagery as imagery_tool


def _jpeg(level: int) -> bytes:
    """A small solid-grey JPEG; level 0 is the black of a missing pass."""
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (level, level, level)).save(buf, format="JPEG")
    return buf.getvalue()


GROUND = _jpeg(120)
BLANK = _jpeg(0)


class _Resp:
    def __init__(self, content: bytes, content_type: str = "image/jpeg", status: int = 200):
        self.content = content
        self.headers = {"content-type": content_type}
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture
def gibs(monkeypatch):
    """Answer GetMap requests from a table keyed by (TIME, LAYERS); record every call."""
    table: dict[tuple[str, str], object] = {}
    calls: list[dict] = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        answer = table.get((params["TIME"], params["LAYERS"]), _Resp(BLANK))
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(imagery_tool.httpx, "get", fake_get)
    return table, calls


SNPP, NOAA20 = imagery_tool.LAYERS


# --------------------------------------------------------------------------- #
# The fetch
# --------------------------------------------------------------------------- #


def test_the_frame_is_south_west_north_east(gibs):
    """WMS 1.3.0 in EPSG:4326 puts latitude first. Swapping it asks for a frame
    in the Southern Ocean and gets back a plausible, wrong picture."""
    table, calls = gibs
    table[("2026-09-28", SNPP)] = _Resp(GROUND)
    out = imagery_tool.fetch_true_colour(30.9, 75.85, today=date(2026, 9, 28))

    south, west, north, east = out["bbox"]
    assert south < 30.9 < north
    assert west < 75.85 < east
    assert calls[0]["BBOX"] == ",".join(str(v) for v in out["bbox"])
    assert calls[0]["CRS"] == "EPSG:4326"
    assert calls[0]["WIDTH"] == calls[0]["HEIGHT"] == imagery_tool.SIZE


def test_a_blank_day_falls_back_to_the_other_satellite_then_the_day_before(gibs):
    """GIBS answers a date it has not processed with HTTP 200 and a black JPEG,
    so a missing pass is found by looking at the pixels."""
    table, calls = gibs
    table[("2026-09-27", NOAA20)] = _Resp(GROUND)
    out = imagery_tool.fetch_true_colour(30.9, 75.85, today=date(2026, 9, 28))

    assert out["image"] == GROUND
    assert out["image_date"] == "2026-09-27"
    assert out["layer"] == NOAA20
    assert [(c["TIME"], c["LAYERS"]) for c in calls] == [
        ("2026-09-28", SNPP),
        ("2026-09-28", NOAA20),
        ("2026-09-27", SNPP),
        ("2026-09-27", NOAA20),
    ]
    assert "no processed pass" in out["attempts"][0]


def test_failures_come_back_as_an_error_and_never_raise(gibs):
    table, _ = gibs
    table[("2026-09-28", SNPP)] = RuntimeError("connection reset")
    table[("2026-09-28", NOAA20)] = _Resp(b"<ServiceException/>", "text/xml")
    table[("2026-09-27", SNPP)] = _Resp(b"not a jpeg at all")
    table[("2026-09-27", NOAA20)] = _Resp(b"", status=500)

    out = imagery_tool.fetch_true_colour(30.9, 75.85, days_back=1, today=date(2026, 9, 28))
    assert set(out) == {"error", "attempts"}
    joined = " ".join(out["attempts"])
    assert "connection reset" in joined
    assert "not an image (text/xml)" in joined
    assert "unreadable image" in joined
    assert "HTTP 500" in joined


def test_the_date_is_a_utc_day(gibs, monkeypatch):
    """At 20:00 IST it is already tomorrow in India and still today in UTC; GIBS
    composites are UTC days, so the first date asked for is the UTC one."""
    _, calls = gibs
    imagery_tool.fetch_true_colour(30.9, 75.85, days_back=0)
    assert calls[0]["TIME"] == datetime.now(UTC).date().isoformat()


# --------------------------------------------------------------------------- #
# The reading
# --------------------------------------------------------------------------- #


def _signal(source: SignalSource, n: int, hours_ago: int = 4) -> Signal:
    return Signal(
        source=source,
        signal_id=f"{source.value}:{n}",
        latitude=30.9010,
        longitude=75.8573,
        observed_at=datetime.now(UTC) - timedelta(hours=hours_ago),
        strength=0.8,
        magnitude=0.5,
        summary="Satellite thermal detection, 9.0 MW radiative power",
    )


def _hotspot(sources=(SignalSource.SATELLITE,)):
    store.save_signals([_signal(s, n) for n, s in enumerate(sources)])
    (spot,) = hotspots.current()
    return spot


def _snapshot(day: str = "2026-09-27", image: bytes = GROUND) -> dict:
    return {
        "image": image,
        "format": "jpeg",
        "image_date": day,
        "layer": NOAA20,
        "bbox": [30.675, 75.595, 31.125, 76.105],
        "attempts": [],
    }


class RecordingAgent(StubAgent):
    """A stub that keeps the content blocks, not only the text."""

    def __init__(self, output):
        super().__init__(output)
        self.contents: list = []

    async def invoke_async(self, prompt, *args, **kwargs):
        self.contents.append(prompt)
        return await super().invoke_async(prompt, *args, **kwargs)


async def test_provenance_comes_from_the_fetch_not_the_model():
    spot = _hotspot()
    agent = RecordingAgent(imagery_assessment())
    reading = await imagery_agent.read_hotspot_imagery(
        spot, agent=agent, fetch=lambda *a: _snapshot()
    )

    assert reading.hotspot_id == spot.hotspot_id
    assert reading.image_date == "2026-09-27"
    assert reading.layer == NOAA20
    assert reading.bbox == [30.675, 75.595, 31.125, 76.105]
    assert reading.plume_visible is True
    assert reading.disclaimer == IMAGERY_DISCLAIMER

    (content,) = agent.contents
    text, image = content
    assert image.inline_data.mime_type == "image/jpeg"
    assert image.inline_data.data == GROUND
    # The model is not told what it is expected to find.
    lowered = text.text.lower()
    assert "location of interest" in lowered
    for leading in ("fire", "burning", "hotspot", "detected"):
        assert leading not in lowered


async def test_a_reading_is_cached_per_hotspot_and_date():
    """The same picture is never paid for twice (constraint 5), and the image an
    operator is shown is the one the model read."""
    spot = _hotspot()
    agent = RecordingAgent(imagery_assessment())
    first = await imagery_agent.read_hotspot_imagery(
        spot, agent=agent, fetch=lambda *a: _snapshot()
    )
    # A later fetch of the same date returns a filled-in composite; the cache wins.
    second = await imagery_agent.read_hotspot_imagery(
        spot, agent=agent, fetch=lambda *a: _snapshot(image=_jpeg(200))
    )
    assert second == first
    assert len(agent.contents) == 1
    path = store.imagery_image(spot.hotspot_id, "2026-09-27")
    assert path.read_bytes() == GROUND

    # A new pass is a new picture and is read.
    await imagery_agent.read_hotspot_imagery(
        spot, agent=agent, fetch=lambda *a: _snapshot(day="2026-09-28")
    )
    assert len(agent.contents) == 2
    assert store.latest_imagery(spot.hotspot_id).image_date == "2026-09-28"

    # `reread` spends a call deliberately.
    await imagery_agent.read_hotspot_imagery(
        spot, agent=agent, fetch=lambda *a: _snapshot(day="2026-09-28"), reread=True
    )
    assert len(agent.contents) == 3


async def test_no_snapshot_is_an_error_and_no_model_call():
    spot = _hotspot()
    agent = RecordingAgent(imagery_assessment())
    with pytest.raises(imagery_agent.ImageryUnavailable, match="No usable"):
        await imagery_agent.read_hotspot_imagery(
            spot, agent=agent, fetch=lambda *a: {"error": "No usable satellite image"}
        )
    assert agent.contents == []


def test_the_imagery_agent_is_on_the_primary_tier(monkeypatch):
    """Constraint 5 names it: judgement on an image, the evidence stage's work."""
    tiers: list[str] = []
    monkeypatch.setattr(imagery_agent, "build_model", lambda **k: tiers.append(k["tier"]))
    monkeypatch.setattr(imagery_agent, "Agent", lambda **k: None)
    imagery_agent.build_imagery_agent()
    assert tiers == ["primary"]


def test_cache_names_cannot_be_steered_outside_the_directory():
    reading = ImageryReading(
        **imagery_assessment().model_dump(),
        hotspot_id="VDH-SAFE0001",
        image_date="2026-09-27",
        layer=SNPP,
        bbox=[0, 0, 1, 1],
    )
    for bad in (
        reading.model_copy(update={"hotspot_id": "../cases"}),
        reading.model_copy(update={"image_date": "../../x"}),
    ):
        with pytest.raises(ValueError):
            store.save_imagery(bad, GROUND)
    assert store.load_imagery("../cases", "2026-09-27") is None
    assert store.latest_imagery("../cases") is None


# --------------------------------------------------------------------------- #
# The routes
# --------------------------------------------------------------------------- #


@pytest.fixture
async def client():
    transport = ASGITransport(app=api.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def model(monkeypatch) -> RecordingAgent:
    agent = RecordingAgent(imagery_assessment())
    monkeypatch.setattr(imagery_agent, "build_imagery_agent", lambda: agent)
    return agent


async def test_read_then_serve_the_same_image(client, model, monkeypatch):
    monkeypatch.setattr(imagery_agent, "fetch_true_colour", lambda *a: _snapshot())
    spot = _hotspot()

    assert (await client.get(f"/hotspots/{spot.hotspot_id}/imagery")).status_code == 404
    assert (await client.get(f"/hotspots/{spot.hotspot_id}/imagery.jpg")).status_code == 404

    resp = await client.post(f"/hotspots/{spot.hotspot_id}/imagery")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["plume_visible"] is True
    assert body["image_date"] == "2026-09-27"
    assert body["disclaimer"] == IMAGERY_DISCLAIMER

    cached = (await client.get(f"/hotspots/{spot.hotspot_id}/imagery")).json()
    assert cached == body

    jpg = await client.get(f"/hotspots/{spot.hotspot_id}/imagery.jpg")
    assert jpg.status_code == 200
    assert jpg.headers["content-type"] == "image/jpeg"
    assert jpg.content == GROUND


async def test_imagery_routes_refuse_unknown_hotspots_and_report_fetch_failures(
    client, model, monkeypatch
):
    assert (await client.post("/hotspots/VDH-NOPE0000/imagery")).status_code == 404

    monkeypatch.setattr(
        imagery_agent, "fetch_true_colour", lambda *a: {"error": "No usable satellite image"}
    )
    spot = _hotspot()
    resp = await client.post(f"/hotspots/{spot.hotspot_id}/imagery")
    assert resp.status_code == 502
    assert "No usable" in resp.json()["detail"]
    assert model.contents == []


# --------------------------------------------------------------------------- #
# The decision this module exists to hold
# --------------------------------------------------------------------------- #


async def test_an_imagery_reading_never_corroborates_a_hotspot(client, model, monkeypatch):
    """A model's reading of a coarse image is an annotation, not a signal.

    Hard constraint 7: corroboration is what stops coordinated false reports
    from manufacturing a hotspot. If a reading of "smoke visible" counted as
    independent evidence, a hallucinated plume would corroborate those reports —
    the weakest input in the system would decide what the public map says. So a
    hotspot held up only by citizens stays uncorroborated, at the same
    confidence, after its imagery says there is a plume; no signal is stored;
    and there is no `SignalSource` for imagery to become one later by accident.
    """
    monkeypatch.setattr(imagery_agent, "fetch_true_colour", lambda *a: _snapshot())
    spot = _hotspot(sources=(SignalSource.CITIZEN_SENSOR, SignalSource.CITIZEN_REPORT))
    assert not spot.corroborated
    signals_before = store.all_signals()

    reading = (await client.post(f"/hotspots/{spot.hotspot_id}/imagery")).json()
    assert reading["plume_visible"] is True

    (after,) = hotspots.current()
    assert after.hotspot_id == spot.hotspot_id
    assert after.corroborated is False
    assert after.confidence == spot.confidence
    assert after.signal_count == spot.signal_count
    assert store.all_signals() == signals_before

    assert not any("imag" in s.value for s in SignalSource)
    assert all("imag" not in s.value for s in INDEPENDENT_SOURCES)


async def test_an_overloaded_model_is_a_503_not_a_500(client, monkeypatch):
    """AI Studio's free tier answers "high demand" for hours on a popular model.
    When the whole fallback chain does, the operator is told to try again rather
    than shown a 500 that says the code is broken. Nothing is cached."""
    from google.genai.errors import ServerError

    class Overloaded:
        async def invoke_async(self, *a, **k):
            raise ServerError(
                503, {"error": {"code": 503, "status": "UNAVAILABLE", "message": "high demand"}}
            )

    monkeypatch.setattr(imagery_agent, "build_imagery_agent", lambda: Overloaded())
    monkeypatch.setattr(imagery_agent, "fetch_true_colour", lambda *a: _snapshot())
    spot = _hotspot()
    resp = await client.post(f"/hotspots/{spot.hotspot_id}/imagery")
    assert resp.status_code == 503
    assert "overloaded" in resp.json()["detail"]
    assert store.latest_imagery(spot.hotspot_id) is None
