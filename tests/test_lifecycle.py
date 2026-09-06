"""The half of the case lifecycle that closes a case rather than chasing it.

A tracker that can only file and escalate is a tracker that never believes it
succeeded: it has no way to record that the authority replied, that the burning
stopped, or that the citizen made a mistake. These cover those three
transitions, the states they are refused from, and what an acknowledgement does
to the escalation clock.

Also here: the two guards the public URL needs — a cap on what one visitor and
one day can spend, and a cap on what an upload can cost to decode. Neither
sleeps; the limiter's clock is injected and the case dates are set directly.
"""

from __future__ import annotations

import io
import os
import struct
import zlib
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

import fakes
from vayudoot import api, filing, lifecycle, pipeline, store
from vayudoot.config import settings
from vayudoot.images import MAX_PIXELS, UnsupportedImage, normalise
from vayudoot.ratelimit import RateLimiter, limiter
from vayudoot.schemas import Case, CaseStatus, Report, Stage

WINDOW_DAYS = fakes.jurisdiction().response_window_days


@pytest.fixture
async def client():
    transport = ASGITransport(app=api.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _case(status: CaseStatus = CaseStatus.FILED, *, filed_days_ago: int = 0, **fields) -> Case:
    """A case sitting in `status`, saved to the isolated store."""
    case = Case(
        case_id=f"VD-{status.value[:6].upper():X<8}",
        report=Report(report_id="r", latitude=28.6139, longitude=77.2090),
        status=status,
        stage=Stage.COMPLETE,
        jurisdiction=fakes.jurisdiction(),
        complaint=fakes.complaint(),
        **fields,
    )
    if status in (CaseStatus.FILED, CaseStatus.ACKNOWLEDGED, CaseStatus.ESCALATED):
        case.filed_at = case.filed_at or datetime.now(UTC) - timedelta(days=filed_days_ago)
    store.save(case)
    return case


# -- acknowledgement ------------------------------------------------------


async def test_an_acknowledgement_is_recorded_against_the_case(client):
    case = _case(CaseStatus.FILED)
    resp = await client.post(
        f"/cases/{case.case_id}/acknowledge",
        json={"note": "Inspection scheduled for Tuesday"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["status"] == CaseStatus.ACKNOWLEDGED.value
    assert body["response_note"] == "Inspection scheduled for Tuesday"
    assert body["acknowledged_at"] is not None
    assert any("Acknowledged by" in entry for entry in body["history"])
    # And it survived to disk, not just to the response.
    assert store.load(case.case_id).status is CaseStatus.ACKNOWLEDGED


async def test_the_acknowledgement_date_defaults_to_now_but_can_be_given(client):
    case = _case(CaseStatus.FILED)
    letter_dated = datetime.now(UTC) - timedelta(days=6)
    body = (
        await client.post(
            f"/cases/{case.case_id}/acknowledge",
            json={"note": "Letter received", "responded_at": letter_dated.isoformat()},
        )
    ).json()
    assert body["acknowledged_at"].startswith(letter_dated.date().isoformat())

    fresh = _case(CaseStatus.ESCALATED)
    default = (await client.post(f"/cases/{fresh.case_id}/acknowledge", json={})).json()
    assert default["acknowledged_at"].startswith(datetime.now(UTC).date().isoformat())


async def test_an_escalated_case_can_still_be_acknowledged(client):
    case = _case(CaseStatus.ESCALATED)
    resp = await client.post(f"/cases/{case.case_id}/acknowledge", json={"note": "Reply from CPCB"})
    assert resp.status_code == 200
    assert resp.json()["status"] == CaseStatus.ACKNOWLEDGED.value


@pytest.mark.parametrize(
    "status",
    [
        CaseStatus.DRAFT,
        CaseStatus.AWAITING_CONFIRMATION,
        CaseStatus.ACKNOWLEDGED,
        CaseStatus.RESOLVED,
        CaseStatus.WITHDRAWN,
        CaseStatus.REJECTED,
        CaseStatus.FAILED,
    ],
)
async def test_acknowledging_from_anywhere_else_is_a_409(client, status):
    """Nobody can respond to a complaint that was never sent to them."""
    case = _case(status)
    resp = await client.post(f"/cases/{case.case_id}/acknowledge", json={"note": "no"})
    assert resp.status_code == 409
    assert status.value in resp.json()["detail"]


# -- the escalation clock -------------------------------------------------


def test_an_acknowledged_case_is_not_immediately_due_for_escalation():
    """The bug this closes: a case that was answered read as overdue forever."""
    case = _case(CaseStatus.FILED, filed_at=datetime.now(UTC) - timedelta(days=WINDOW_DAYS + 5))
    assert filing.escalation_due(case) is True

    lifecycle.acknowledge(case, "We are looking into it")
    assert filing.escalation_due(case) is False


def test_an_acknowledgement_restarts_the_clock_rather_than_stopping_it():
    """A receipt is not a remedy: silence after acknowledging is still escalated."""
    case = _case(CaseStatus.FILED, filed_at=datetime.now(UTC) - timedelta(days=90))

    lifecycle.acknowledge(case, "Noted", at=datetime.now(UTC) - timedelta(days=WINDOW_DAYS - 1))
    assert filing.escalation_due(case) is False, "the fresh window has not lapsed yet"

    case.acknowledged_at = datetime.now(UTC) - timedelta(days=WINDOW_DAYS + 1)
    assert filing.escalation_due(case) is True


async def test_an_acknowledged_case_escalates_and_says_so_in_the_envelope(client):
    case = _case(CaseStatus.FILED, filed_at=datetime.now(UTC) - timedelta(days=90))
    lifecycle.acknowledge(case, "Noted", at=datetime.now(UTC) - timedelta(days=WINDOW_DAYS + 1))
    store.save(case)

    resp = await client.post(f"/cases/{case.case_id}/escalate")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == CaseStatus.ESCALATED.value

    envelope = (await client.get(f"/cases/{case.case_id}/envelope")).text
    assert "acknowledged on" in envelope
    assert "no remedial action" in store.load(case.case_id).history[-1]


@pytest.mark.parametrize("status", [CaseStatus.RESOLVED, CaseStatus.WITHDRAWN])
def test_a_closed_case_is_never_due_however_old_it_is(status):
    case = _case(status, filed_at=datetime.now(UTC) - timedelta(days=365))
    assert filing.escalation_due(case) is False


async def test_a_withdrawn_case_cannot_be_escalated_over_http(client):
    case = _case(CaseStatus.FILED, filed_at=datetime.now(UTC) - timedelta(days=90))
    await client.post(f"/cases/{case.case_id}/withdraw", json={"note": "Wrong location"})

    resp = await client.post(f"/cases/{case.case_id}/escalate")
    assert resp.status_code == 409
    assert "withdrawn" in resp.json()["detail"]


# -- resolution -----------------------------------------------------------


@pytest.mark.parametrize(
    "status", [CaseStatus.FILED, CaseStatus.ESCALATED, CaseStatus.ACKNOWLEDGED]
)
async def test_a_live_case_can_be_resolved(client, status):
    case = _case(status)
    resp = await client.post(
        f"/cases/{case.case_id}/resolve", json={"note": "Burning stopped; site cleared"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == CaseStatus.RESOLVED.value
    assert body["resolved_at"] is not None
    assert body["resolution_note"] == "Burning stopped; site cleared"
    assert store.load(case.case_id).status is CaseStatus.RESOLVED


@pytest.mark.parametrize(
    "status",
    [CaseStatus.DRAFT, CaseStatus.AWAITING_CONFIRMATION, CaseStatus.RESOLVED, CaseStatus.FAILED],
)
async def test_resolving_something_that_was_never_filed_is_a_409(client, status):
    case = _case(status)
    assert (await client.post(f"/cases/{case.case_id}/resolve", json={})).status_code == 409


# -- withdrawal -----------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    [
        CaseStatus.DRAFT,
        CaseStatus.AWAITING_CONFIRMATION,
        CaseStatus.FILED,
        CaseStatus.ACKNOWLEDGED,
        CaseStatus.ESCALATED,
    ],
)
async def test_a_live_case_can_be_withdrawn(client, status):
    case = _case(status)
    resp = await client.post(
        f"/cases/{case.case_id}/withdraw", json={"note": "Submitted by mistake"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == CaseStatus.WITHDRAWN.value
    assert body["withdrawn_at"] is not None
    assert body["withdrawal_note"] == "Submitted by mistake"


@pytest.mark.parametrize(
    "status",
    [CaseStatus.RESOLVED, CaseStatus.WITHDRAWN, CaseStatus.REJECTED, CaseStatus.FAILED],
)
async def test_withdrawing_a_finished_case_is_a_409(client, status):
    case = _case(status)
    assert (await client.post(f"/cases/{case.case_id}/withdraw", json={})).status_code == 409


async def test_a_withdrawn_case_cannot_then_be_filed(client, monkeypatch):
    """The point of withdrawal: nothing further leaves the building."""
    fakes.patch_stages(monkeypatch, pipeline)
    resp = await client.post("/reports", data={"latitude": "28.6", "longitude": "77.2"})
    case_id = resp.json()["case_id"]
    while api._running:
        await __import__("asyncio").gather(*list(api._running), return_exceptions=True)

    assert (await client.post(f"/cases/{case_id}/withdraw", json={})).status_code == 200
    assert (await client.post(f"/cases/{case_id}/confirm")).status_code == 409
    assert (await client.post(f"/cases/{case_id}/acknowledge", json={})).status_code == 409
    assert not (settings.vayudoot_sandbox_outbox / f"{case_id}.eml").exists()


async def test_the_new_endpoints_404_on_an_unknown_case(client):
    for action in ("acknowledge", "resolve", "withdraw"):
        resp = await client.post(f"/cases/VD-NOPE/{action}", json={})
        assert resp.status_code == 404, action


# -- cases written before any of these fields existed ---------------------

#: A case as it was serialised before the lifecycle fields were added. Loading
#: this is the compatibility contract: the store is a directory of JSON files
#: that outlive a deployment, and adding a field must not orphan them.
LEGACY_CASE = """{
  "case_id": "VD-OLDCASE",
  "report": {
    "report_id": "abc",
    "latitude": 28.6139,
    "longitude": 77.209,
    "image_path": null,
    "note": "Waste burning",
    "reporter_contact": "",
    "observed_at": "2026-08-01T10:00:00Z"
  },
  "status": "filed",
  "stage": "complete",
  "evidence": null,
  "corroboration": null,
  "jurisdiction": null,
  "complaint": null,
  "address": "Minto Road, New Delhi",
  "filed_at": "2026-08-01T10:05:00Z",
  "escalated_at": null,
  "error": "",
  "history": ["2026-08-01T10:05:00+00:00 Filed"],
  "created_at": "2026-08-01T10:00:00Z",
  "updated_at": "2026-08-01T10:05:00Z"
}"""


def test_a_case_saved_before_these_fields_existed_still_loads():
    (settings.vayudoot_case_dir).mkdir(parents=True, exist_ok=True)
    (settings.vayudoot_case_dir / "VD-OLDCASE.json").write_text(LEGACY_CASE)

    case = store.load("VD-OLDCASE")
    assert case is not None
    assert case.status is CaseStatus.FILED
    assert case.acknowledged_at is None and case.resolved_at is None
    assert case.response_note == "" and case.withdrawal_note == ""
    assert [c.case_id for c in store.all_cases()] == ["VD-OLDCASE"]


def test_the_cases_already_on_this_machine_still_load(tmp_path):
    """The real store, not a fixture: two of these exist and must keep working."""
    from pathlib import Path

    real = Path(__file__).resolve().parents[1] / "data" / "cases"
    existing = sorted(real.glob("VD-*.json")) if real.exists() else []
    if not existing:
        pytest.skip("no stored cases on this machine to check against")

    for path in existing:
        (settings.vayudoot_case_dir).mkdir(parents=True, exist_ok=True)
        (settings.vayudoot_case_dir / path.name).write_text(path.read_text())
        loaded = store.load(path.stem)
        assert loaded is not None, f"{path.name} no longer loads"
        assert loaded.case_id == path.stem


# -- rate limiting --------------------------------------------------------


async def _submit(client, **headers) -> int:
    resp = await client.post(
        "/reports", data={"latitude": "28.6", "longitude": "77.2"}, headers=headers
    )
    return resp.status_code


async def test_one_client_is_capped_and_told_when_to_come_back(client, monkeypatch):
    fakes.patch_stages(monkeypatch, pipeline)
    monkeypatch.setattr(settings, "vayudoot_reports_per_client", 2)

    assert await _submit(client) == 202
    assert await _submit(client) == 202

    resp = await client.post("/reports", data={"latitude": "28.6", "longitude": "77.2"})
    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert "2 reports per visitor" in detail
    assert "Try again in about" in detail
    assert int(resp.headers["retry-after"]) > 0


async def test_the_daily_budget_holds_even_when_the_addresses_change(client, monkeypatch):
    """Per-client caps are forgeable; the global one is the actual budget line."""
    fakes.patch_stages(monkeypatch, pipeline)
    monkeypatch.setattr(settings, "vayudoot_reports_per_day", 1)

    assert await _submit(client, **{"x-forwarded-for": "203.0.113.1"}) == 202

    resp = await client.post(
        "/reports",
        data={"latitude": "28.6", "longitude": "77.2"},
        headers={"x-forwarded-for": "203.0.113.2"},
    )
    assert resp.status_code == 429
    assert "midnight UTC" in resp.json()["detail"]
    assert "1 report a day" in resp.json()["detail"]


async def test_health_publishes_the_remaining_budget(client, monkeypatch):
    fakes.patch_stages(monkeypatch, pipeline)
    monkeypatch.setattr(settings, "vayudoot_reports_per_day", 3)

    before = (await client.get("/health")).json()
    assert before["rate_limited"] is True
    assert before["reports_remaining_today"] == 3

    await _submit(client)
    after = (await client.get("/health")).json()
    assert after["reports_remaining_today"] == 2


async def test_the_cap_can_be_switched_off(client, monkeypatch):
    fakes.patch_stages(monkeypatch, pipeline)
    monkeypatch.setattr(settings, "vayudoot_rate_limit", False)
    monkeypatch.setattr(settings, "vayudoot_reports_per_client", 1)

    assert await _submit(client) == 202
    assert await _submit(client) == 202
    assert (await client.get("/health")).json()["rate_limited"] is False


def test_the_client_window_rolls_forward_without_waiting_for_it(monkeypatch):
    """The clock is injected precisely so this test does not sleep for an hour."""
    monkeypatch.setattr(settings, "vayudoot_reports_per_client", 2)
    monkeypatch.setattr(settings, "vayudoot_rate_limit_window_seconds", 3600)

    now = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    rolling = RateLimiter(now=lambda: now)

    assert rolling.check("a").allowed
    assert rolling.check("a").allowed
    refused = rolling.check("a")
    assert not refused.allowed and refused.scope == "client"
    assert 0 < refused.retry_after_seconds <= 3600
    # A different visitor is unaffected by the first one's spending.
    assert rolling.check("b").allowed

    now += timedelta(seconds=3601)
    assert rolling.check("a").allowed, "the window should have rolled off"


@pytest.mark.parametrize("setting", ["vayudoot_reports_per_client", "vayudoot_reports_per_day"])
def test_a_cap_of_zero_closes_intake_rather_than_crashing(monkeypatch, setting):
    """Setting a cap to zero is how an operator stops accepting reports. It used
    to reach into an empty deque and 500 instead of refusing."""
    monkeypatch.setattr(settings, setting, 0)
    refused = RateLimiter(now=lambda: datetime(2026, 9, 6, 12, 0, tzinfo=UTC)).check("a")
    assert not refused.allowed
    assert refused.retry_after_seconds > 0
    assert refused.message


def test_the_daily_budget_resets_when_the_utc_day_rolls_over(monkeypatch):
    monkeypatch.setattr(settings, "vayudoot_reports_per_day", 1)

    now = datetime(2026, 9, 6, 23, 30, tzinfo=UTC)
    rolling = RateLimiter(now=lambda: now)

    assert rolling.check("a").allowed
    refused = rolling.check("b")
    assert not refused.allowed and refused.scope == "global"
    assert refused.retry_after_seconds == 30 * 60
    assert rolling.remaining_today() == 0

    now += timedelta(hours=1)
    assert rolling.check("b").allowed
    assert rolling.remaining_today() == 0


def test_the_shipped_limiter_is_on_by_default():
    assert limiter.enabled is True
    assert settings.vayudoot_reports_per_day > settings.vayudoot_reports_per_client


# -- upload limits --------------------------------------------------------


def _incompressible_png(at_least: int) -> bytes:
    """A PNG of roughly a given size. Noise, so it does not compress away."""
    side = 64
    while True:
        image = Image.frombytes("RGB", (side, side), os.urandom(side * side * 3))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        if buffer.tell() >= at_least:
            return buffer.getvalue()
        side *= 2


def _declared_size_png(width: int, height: int) -> bytes:
    """A few bytes of PNG that claim enormous dimensions.

    The header is what a decoder trusts, so this is what a decompression bomb
    actually looks like: cheap to send, ruinous to decode.
    """

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"\x00" * 32))
        + chunk(b"IEND", b"")
    )


async def test_an_upload_past_the_cap_is_refused_before_it_is_decoded(client, monkeypatch):
    fakes.patch_stages(monkeypatch, pipeline)
    monkeypatch.setattr(settings, "vayudoot_max_upload_bytes", 4096)

    # Small enough that the body reaches the handler, large enough to be refused
    # there by the counted read.
    resp = await client.post(
        "/reports",
        data={"latitude": "28.6", "longitude": "77.2"},
        files={"image": ("photo.png", _incompressible_png(8_000), "image/png")},
    )
    assert resp.status_code == 413
    assert "too large" in resp.json()["detail"]
    assert store.all_cases() == [], "an oversized upload must not create a case"


async def test_a_body_too_large_to_parse_is_refused_by_its_declared_length(client, monkeypatch):
    fakes.patch_stages(monkeypatch, pipeline)
    monkeypatch.setattr(settings, "vayudoot_max_upload_bytes", 4096)

    # If the handler is reached at all, the multipart parser has already spooled
    # the whole body — so this asserts the refusal happens before that.
    def _never(_image):
        raise AssertionError("the body should have been refused before it was parsed")

    monkeypatch.setattr(api, "_read_capped", _never)

    resp = await client.post(
        "/reports",
        data={"latitude": "28.6", "longitude": "77.2"},
        files={"image": ("photo.png", _incompressible_png(200_000), "image/png")},
    )
    assert resp.status_code == 413
    assert store.all_cases() == []


async def test_a_photograph_under_the_cap_is_still_accepted(client, monkeypatch):
    fakes.patch_stages(monkeypatch, pipeline)
    monkeypatch.setattr(settings, "vayudoot_max_upload_bytes", 1024 * 1024)

    resp = await client.post(
        "/reports",
        data={"latitude": "28.6", "longitude": "77.2"},
        files={"image": ("photo.png", fakes.image_bytes("PNG"), "image/png")},
    )
    assert resp.status_code == 202


@pytest.mark.parametrize("size", [(10_000, 7_000), (30_000, 30_000)])
# Pillow warns before it raises, and the warning is the expected behaviour here.
# Left unfiltered it is the only warning in a green suite, which is exactly how
# people learn to stop reading them.
@pytest.mark.filterwarnings("ignore::PIL.Image.DecompressionBombWarning")
def test_a_decompression_bomb_is_refused_rather_than_decoded(size):
    """Two bombs: one over the limit, one over Pillow's own hard ceiling. Both
    must come back as `UnsupportedImage` rather than a Pillow error escaping."""
    assert size[0] * size[1] > MAX_PIXELS
    with pytest.raises(UnsupportedImage):
        normalise(_declared_size_png(*size))


async def test_a_bomb_submitted_over_http_is_a_415(client, monkeypatch):
    fakes.patch_stages(monkeypatch, pipeline)
    resp = await client.post(
        "/reports",
        data={"latitude": "28.6", "longitude": "77.2"},
        files={"image": ("bomb.png", _declared_size_png(30_000, 30_000), "image/png")},
    )
    assert resp.status_code == 415
    assert store.all_cases() == []
