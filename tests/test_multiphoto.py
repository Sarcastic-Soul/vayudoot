"""Several photographs of one event, and the single-photograph past.

Two properties are being defended here. One is the new behaviour: a report can
carry more than one angle, they all reach the model in one message, and there is
a cap on how many because every image is tokens against a metered free tier. The
other is that nothing already on disk broke — three real cases and the
`LEGACY_CASE` fixture in `test_lifecycle.py` were written when `image_path` was a
single string, and they must keep loading and keep classifying.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from fakes import StubAgent, evidence, image_bytes, patch_stages
from vayudoot import api, pipeline, store
from vayudoot.agents.evidence import analyse_evidence
from vayudoot.config import settings
from vayudoot.schemas import Report

PNG = image_bytes("PNG", size=(24, 18))
JPEG = image_bytes("JPEG", size=(30, 20))

LEGACY_REPORT = """{
  "report_id": "abc",
  "latitude": 28.6139,
  "longitude": 77.209,
  "image_path": "/tmp/one-photo.jpg",
  "note": "Waste burning",
  "reporter_contact": "",
  "observed_at": "2026-08-01T10:00:00Z"
}"""


@pytest.fixture
async def client():
    transport = ASGITransport(app=api.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _drain() -> None:
    while api._running:
        await asyncio.gather(*list(api._running), return_exceptions=True)


def _content(agent: StubAgent) -> list:
    """The single message the evidence stage sent."""
    assert len(agent.prompts) == 1
    return agent.prompts[0]


# --------------------------------------------------------------------------- #
# The schema keeps reading what is already on disk
# --------------------------------------------------------------------------- #


def test_a_report_written_with_one_image_path_still_loads():
    report = Report.model_validate_json(LEGACY_REPORT)

    assert report.image_paths == ["/tmp/one-photo.jpg"]
    assert report.image_path == "/tmp/one-photo.jpg"


def test_the_old_key_survives_serialisation():
    """Anything still reading `report.image_path` keeps getting the first photograph."""
    report = Report(report_id="r", latitude=1.0, longitude=2.0, image_paths=["a.jpg", "b.jpg"])

    dumped = report.model_dump()
    assert dumped["image_paths"] == ["a.jpg", "b.jpg"]
    assert dumped["image_path"] == "a.jpg"
    assert Report.model_validate(dumped).image_paths == ["a.jpg", "b.jpg"]


def test_a_report_with_no_photograph_reports_none():
    report = Report(report_id="r", latitude=1.0, longitude=2.0)

    assert report.image_paths == []
    assert report.image_path is None


# --------------------------------------------------------------------------- #
# The evidence stage
# --------------------------------------------------------------------------- #


async def test_every_photograph_becomes_its_own_image_block(tmp_path):
    first, second = tmp_path / "a.png", tmp_path / "b.jpg"
    first.write_bytes(PNG)
    second.write_bytes(JPEG)
    report = Report(
        report_id="r", latitude=28.6, longitude=77.2, image_paths=[str(first), str(second)]
    )
    agent = StubAgent(evidence())

    await analyse_evidence(report, agent=agent)

    content = _content(agent)
    images = [block for block in content if "image" in block]
    assert len(images) == 2
    assert {block["image"]["format"] for block in images} == {"png", "jpeg"}
    assert all(block["image"]["source"]["bytes"] for block in images)
    assert "2 photographs are attached" in content[0]["text"]


async def test_a_legacy_single_photograph_case_still_classifies(tmp_path):
    """One photograph, addressed the way it always was, still reaches the model."""
    only = tmp_path / "one.png"
    only.write_bytes(PNG)
    report = Report.model_validate(
        {
            "report_id": "r",
            "latitude": 28.6,
            "longitude": 77.2,
            "image_path": str(only),
        }
    )
    agent = StubAgent(evidence())

    packet = await analyse_evidence(report, agent=agent)

    content = _content(agent)
    assert packet.confidence == 0.9
    assert [block for block in content if "image" in block]
    # A single photograph gets no "several photographs" preamble.
    assert "photographs are attached" not in content[0]["text"]


async def test_a_report_with_no_photograph_says_so_to_the_model():
    report = Report(report_id="r", latitude=28.6, longitude=77.2, note="Stubble burning")
    agent = StubAgent(evidence())

    await analyse_evidence(report, agent=agent)

    content = _content(agent)
    assert not [block for block in content if "image" in block]
    assert "No photograph was attached" in content[0]["text"]


async def test_the_stage_caps_the_images_even_when_the_case_carries_more(tmp_path, monkeypatch):
    """The cap is a cost control, so it is enforced where the cost is paid."""
    monkeypatch.setattr(settings, "vayudoot_max_images_per_report", 2)
    paths = []
    for name in ("a", "b", "c", "d"):
        path = tmp_path / f"{name}.png"
        path.write_bytes(PNG)
        paths.append(str(path))
    agent = StubAgent(evidence())

    await analyse_evidence(
        Report(report_id="r", latitude=28.6, longitude=77.2, image_paths=paths), agent=agent
    )

    assert len([block for block in _content(agent) if "image" in block]) == 2


async def test_a_missing_file_is_skipped_rather_than_fatal(tmp_path):
    present = tmp_path / "there.png"
    present.write_bytes(PNG)
    report = Report(
        report_id="r",
        latitude=28.6,
        longitude=77.2,
        image_paths=[str(tmp_path / "gone.png"), str(present)],
    )
    agent = StubAgent(evidence())

    await analyse_evidence(report, agent=agent)

    assert len([block for block in _content(agent) if "image" in block]) == 1


# --------------------------------------------------------------------------- #
# Intake
# --------------------------------------------------------------------------- #


async def test_several_photographs_are_accepted_and_stored(client, monkeypatch):
    patch_stages(monkeypatch, pipeline)

    resp = await client.post(
        "/reports",
        data={"latitude": "28.6139", "longitude": "77.2090"},
        files=[
            ("image", ("one.png", PNG, "image/png")),
            ("image", ("two.jpg", JPEG, "image/jpeg")),
        ],
    )
    assert resp.status_code == 202, resp.text
    await _drain()

    case = store.load(resp.json()["case_id"])
    assert len(case.report.image_paths) == 2
    assert case.report.image_path == case.report.image_paths[0]
    uploads = settings.vayudoot_upload_dir.resolve()
    assert all(uploads in Path(p).resolve().parents for p in case.report.image_paths)


async def test_one_photograph_is_submitted_exactly_as_before(client, monkeypatch):
    patch_stages(monkeypatch, pipeline)

    resp = await client.post(
        "/reports",
        data={"latitude": "28.6139", "longitude": "77.2090"},
        files={"image": ("photo.png", PNG, "image/png")},
    )
    assert resp.status_code == 202
    await _drain()

    body = resp.json()
    assert len(body["report"]["image_paths"]) == 1
    assert body["report"]["image_path"] == body["report"]["image_paths"][0]


async def test_too_many_photographs_are_refused(client, monkeypatch):
    monkeypatch.setattr(settings, "vayudoot_max_images_per_report", 2)
    patch_stages(monkeypatch, pipeline)

    resp = await client.post(
        "/reports",
        data={"latitude": "28.6139", "longitude": "77.2090"},
        files=[("image", (f"{n}.png", PNG, "image/png")) for n in range(3)],
    )

    assert resp.status_code == 413
    assert "at most 2" in resp.json()["detail"]
    assert not list(settings.vayudoot_case_dir.glob("*.json"))


async def test_one_unreadable_photograph_names_which_one(client, monkeypatch):
    patch_stages(monkeypatch, pipeline)

    resp = await client.post(
        "/reports",
        data={"latitude": "28.6139", "longitude": "77.2090"},
        files=[
            ("image", ("good.png", PNG, "image/png")),
            ("image", ("bad.png", b"not an image at all", "image/png")),
        ],
    )

    assert resp.status_code == 415
    assert "photograph 2 of 2" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
# Serving them back
# --------------------------------------------------------------------------- #


async def test_photographs_are_addressable_one_at_a_time(client, monkeypatch):
    patch_stages(monkeypatch, pipeline)
    resp = await client.post(
        "/reports",
        data={"latitude": "28.6139", "longitude": "77.2090"},
        files=[
            ("image", ("one.png", PNG, "image/png")),
            ("image", ("two.jpg", JPEG, "image/jpeg")),
        ],
    )
    case_id = resp.json()["case_id"]
    await _drain()

    # The URL that predates several photographs still means the first one.
    bare = await client.get(f"/cases/{case_id}/photo")
    indexed = await client.get(f"/cases/{case_id}/photo/0")
    second = await client.get(f"/cases/{case_id}/photo/1")

    assert bare.status_code == 200
    assert bare.content == indexed.content == PNG
    assert second.status_code == 200
    assert second.content == JPEG
    assert second.headers["content-type"] == "image/jpeg"

    missing = await client.get(f"/cases/{case_id}/photo/7")
    assert missing.status_code == 404
    assert "2 photograph" in missing.json()["detail"]
