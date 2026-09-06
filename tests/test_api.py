"""The HTTP surface, including the human-in-the-loop gate.

The pipeline runs in a background task, so these tests await the tasks the app
started rather than sleeping and hoping.
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from fakes import image_bytes, patch_stages
from vayudoot import api, pipeline, store
from vayudoot.config import settings
from vayudoot.schemas import Case, CaseStatus, Report, Stage

PNG = image_bytes("PNG")


@pytest.fixture
async def client():
    transport = ASGITransport(app=api.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _drain() -> None:
    """Wait for the background pipeline tasks the app started."""
    while api._running:
        await asyncio.gather(*list(api._running), return_exceptions=True)


async def _submit(client, **overrides) -> dict:
    data = {"latitude": "28.6139", "longitude": "77.2090", "note": "Waste burning"} | overrides
    files = {"image": ("photo.png", PNG, "image/png")}
    resp = await client.post("/reports", data=data, files=files)
    assert resp.status_code == 202, resp.text
    return resp.json()


async def test_health_reports_that_live_filing_is_off(client):
    body = (await client.get("/health")).json()
    assert body["status"] == "ok"
    assert body["live_filing"] is False


async def test_submission_returns_before_the_run_finishes(client, monkeypatch):
    patch_stages(monkeypatch, pipeline)
    created = await _submit(client)

    assert created["case_id"].startswith("VD-")
    assert created["stage"] == Stage.RECEIVED.value
    assert created["complaint"] is None
    # The case is on disk immediately, so the browser can poll it.
    assert store.load(created["case_id"]) is not None

    await _drain()
    done = (await client.get(f"/cases/{created['case_id']}")).json()
    assert done["status"] == CaseStatus.AWAITING_CONFIRMATION.value
    assert done["stage"] == Stage.COMPLETE.value
    assert done["complaint"]["subject"]


async def test_confirm_files_to_the_sandbox_and_is_not_repeatable(client, monkeypatch):
    patch_stages(monkeypatch, pipeline)
    case_id = (await _submit(client))["case_id"]
    await _drain()

    filed = (await client.post(f"/cases/{case_id}/confirm")).json()
    assert filed["status"] == CaseStatus.FILED.value
    assert (settings.vayudoot_sandbox_outbox / f"{case_id}.eml").exists()

    again = await client.post(f"/cases/{case_id}/confirm")
    assert again.status_code == 409


async def test_envelope_is_only_available_once_something_is_filed(client, monkeypatch):
    patch_stages(monkeypatch, pipeline)
    case_id = (await _submit(client))["case_id"]
    await _drain()

    assert (await client.get(f"/cases/{case_id}/envelope")).status_code == 409

    await client.post(f"/cases/{case_id}/confirm")
    envelope = await client.get(f"/cases/{case_id}/envelope")
    assert envelope.status_code == 200
    assert "X-Vayudoot-Mode: SANDBOX" in envelope.text
    assert "@example.invalid" in envelope.text


async def test_photograph_is_served_back_and_only_from_the_uploads_directory(client, monkeypatch):
    patch_stages(monkeypatch, pipeline)
    case_id = (await _submit(client))["case_id"]
    await _drain()

    photo = await client.get(f"/cases/{case_id}/photo")
    assert photo.status_code == 200
    assert photo.content == PNG

    # A case pointing anywhere else is refused rather than read off the filesystem.
    case = store.load(case_id)
    case.report.image_path = "/etc/passwd"
    store.save(case)
    assert (await client.get(f"/cases/{case_id}/photo")).status_code == 404


async def test_a_report_without_a_photograph_is_accepted(client, monkeypatch):
    patch_stages(monkeypatch, pipeline)
    resp = await client.post("/reports", data={"latitude": "28.6", "longitude": "77.2"})
    assert resp.status_code == 202
    await _drain()
    assert resp.json()["report"]["image_path"] is None


async def test_unknown_case_is_a_404(client):
    assert (await client.get("/cases/VD-NOPE")).status_code == 404
    assert (await client.post("/cases/VD-NOPE/confirm")).status_code == 404


async def test_escalation_is_refused_before_the_window_lapses(client, monkeypatch):
    patch_stages(monkeypatch, pipeline)
    case_id = (await _submit(client))["case_id"]
    await _drain()
    await client.post(f"/cases/{case_id}/confirm")

    assert (await client.post(f"/cases/{case_id}/escalate")).status_code == 409


async def test_cases_are_listed_newest_first(client, monkeypatch):
    patch_stages(monkeypatch, pipeline)
    first = (await _submit(client))["case_id"]
    await _drain()
    second = (await _submit(client))["case_id"]
    await _drain()

    listed = [c["case_id"] for c in (await client.get("/cases")).json()]
    assert listed == [second, first]


async def test_the_interface_is_served_by_the_same_process(client):
    page = await client.get("/")
    assert page.status_code == 200
    assert "Vayudoot" in page.text
    assert (await client.get("/app.js")).status_code == 200
    assert (await client.get("/styles.css")).status_code == 200


async def test_a_failed_run_is_visible_over_http(client, monkeypatch):
    patch_stages(monkeypatch, pipeline, fail_at="jurisdiction")
    case_id = (await _submit(client))["case_id"]
    await _drain()

    body = (await client.get(f"/cases/{case_id}")).json()
    assert body["status"] == CaseStatus.FAILED.value
    assert body["stage"] == Stage.JURISDICTION.value
    assert "jurisdiction exploded" in body["error"]
    # A failed case cannot be filed.
    assert (await client.post(f"/cases/{case_id}/confirm")).status_code == 409


def test_case_round_trips_through_the_store(tmp_path):
    case = Case(case_id="VD-STORE001", report=Report(report_id="r", latitude=1.0, longitude=2.0))
    case.log("hello")
    store.save(case)
    assert store.load("VD-STORE001").history == case.history
    assert store.load("VD-MISSING") is None


async def test_the_authority_table_is_published(client):
    """Coverage is the honest limit of the system, so it is visible up front."""
    body = (await client.get("/authorities")).json()
    assert body["region_count"] > 0 and body["municipal_count"] > 0
    assert body["addresses_are_placeholders"] is True
    assert all(
        r["state_board"]["email"].endswith(".invalid") for r in body["regions"]
    ), "the published table must not carry a routable address"


async def test_geocode_needs_a_point_or_a_query(client):
    assert (await client.get("/geocode")).status_code == 400


async def test_a_fallback_authority_is_visible_on_the_case(client, monkeypatch):
    patch_stages(monkeypatch, pipeline)
    case_id = (await _submit(client))["case_id"]
    await _drain()

    body = (await client.get(f"/cases/{case_id}")).json()
    assert body["jurisdiction"]["coverage"] in {"exact", "fallback", "generic"}
