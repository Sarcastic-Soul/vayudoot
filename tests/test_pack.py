"""The evidence pack.

Two things make or break this document. It has to be genuinely self-contained,
because a pack is normally read offline and a broken image or a missing
stylesheet is exactly the failure you cannot see coming; and it has to render
the local-language half of the complaint, because a complaint drafted in Hindi
and printed as boxes is worse than one that was never translated. Both are
asserted here rather than eyeballed.
"""

from __future__ import annotations

import asyncio
import re

import pytest
from httpx import ASGITransport, AsyncClient

from fakes import complaint, corroboration, evidence, image_bytes, jurisdiction, patch_stages
from vayudoot import api, pack, pipeline, store
from vayudoot.config import settings
from vayudoot.schemas import Case, CaseStatus, Report, Stage

PNG = image_bytes("PNG")

CONTACT = "priya.sharma@example.invalid"

#: Scripts the complaint is actually drafted in. Each has to survive the round
#: trip from the model through the case file into the document as itself.
SCRIPTS = {
    "Hindi": "दिल्ली में कूड़ा जलाने की शिकायत। कृपया निरीक्षण करें।",
    "Marathi": "कचरा जाळण्याची तक्रार. कृपया तपासणी करा.",
    "Kannada": "ಕಸ ಸುಡುವ ಬಗ್ಗೆ ದೂರು. ದಯವಿಟ್ಟು ಪರಿಶೀಲಿಸಿ.",
    "Tamil": "குப்பை எரிப்பு குறித்த புகார். தயவுசெய்து ஆய்வு செய்யவும்.",
}


@pytest.fixture
async def client():
    transport = ASGITransport(app=api.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _drain() -> None:
    while api._running:
        await asyncio.gather(*list(api._running), return_exceptions=True)


def photo_on_disk(name: str = "photo.png", data: bytes = PNG) -> str:
    uploads = settings.vayudoot_upload_dir
    uploads.mkdir(parents=True, exist_ok=True)
    path = uploads / name
    path.write_bytes(data)
    return str(path)


def make_case(image_paths: list[str] | None = None, **overrides) -> Case:
    case = Case(
        case_id="VD-PACK0001",
        report=Report(
            report_id="r",
            latitude=28.6139,
            longitude=77.2090,
            note="Rubbish burning on the vacant plot",
            reporter_contact=CONTACT,
            image_paths=image_paths or [],
        ),
        status=CaseStatus.FILED,
        stage=Stage.COMPLETE,
        evidence=evidence(),
        corroboration=corroboration(),
        jurisdiction=jurisdiction(),
        complaint=complaint(),
        address="Minto Road, New Delhi",
    )
    case.log("Report received")
    case.log("Filed to Municipal Corporation of Delhi")
    for key, value in overrides.items():
        setattr(case, key, value)
    return case


# --------------------------------------------------------------------------- #
# Self-contained
# --------------------------------------------------------------------------- #


def test_nothing_in_the_pack_is_fetched_from_the_network():
    """Offline is the normal reading condition for this document."""
    document = pack.render(make_case([photo_on_disk()]))

    assert "<link" not in document
    assert "<script" not in document
    assert "@import" not in document
    assert not re.search(r'(?:src|href)\s*=\s*["\']https?://', document)
    assert not re.search(r"url\(\s*['\"]?https?://", document)
    # The one http string that survives is the SVG namespace, which is an
    # identifier and not an address anything resolves.
    for url in re.findall(r"https?://[^\s\"'<>)]+", document):
        assert url == "http://www.w3.org/2000/svg", url


def test_the_photograph_is_embedded_rather_than_linked():
    document = pack.render(make_case([photo_on_disk()]))

    assert "data:image/png;base64," in document
    assert "/cases/VD-PACK0001/photo" not in document


def test_every_photograph_of_a_multi_angle_report_is_embedded():
    case = make_case([photo_on_disk("a.png"), photo_on_disk("b.png", image_bytes("PNG", (12, 9)))])

    document = pack.render(case)

    assert document.count("data:image/png;base64,") == 2
    assert "Photograph 1 of 2" in document
    assert "angles on one event" in document


def test_a_photograph_outside_the_uploads_directory_is_not_read():
    """Same containment rule as the photo endpoint, for the same reason."""
    case = make_case(["/etc/passwd"])

    document = pack.render(case)

    assert "data:image" not in document
    assert "no longer on disk" in document


def test_a_note_only_report_says_the_complaint_rests_on_testimony():
    document = pack.render(make_case([]))

    assert "No photograph was submitted" in document
    assert "written account" in document
    assert "Rubbish burning on the vacant plot" in document


# --------------------------------------------------------------------------- #
# The local language
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("language,body", sorted(SCRIPTS.items()))
def test_the_local_language_complaint_survives_into_the_document(language, body):
    case = make_case([])
    case.complaint.local_language = language
    case.complaint.body_local = body

    document = pack.render(case)

    assert body in document
    assert language in document

    # The two ways this goes wrong in practice. Mojibake is UTF-8 bytes read back
    # as Latin-1, which turns every Devanagari character into the "à¤" run; and
    # an escaping layer can turn the script into numeric entities, which render
    # but are not the text a reader can copy out of the document.
    written = document.encode("utf-8")
    assert body.encode("utf-8") in written
    assert "à¤" not in document and "Ã" not in document
    assert not re.search(r"&#\d{4,};", document)


def test_the_document_declares_utf_8():
    assert '<meta charset="utf-8">' in pack.render(make_case([]))


def test_the_pack_carries_both_language_versions():
    document = pack.render(make_case([]))

    assert "Body of the complaint." in document
    assert "शिकायत का मुख्य भाग।" in document


# --------------------------------------------------------------------------- #
# What is and is not in it
# --------------------------------------------------------------------------- #


def test_the_reporter_contact_is_not_in_a_document_meant_to_be_shared():
    document = pack.render(make_case([photo_on_disk()]))

    assert CONTACT not in document
    assert "Reporter contact is withheld" in document


def test_the_pack_says_nothing_was_delivered_to_a_regulator():
    document = pack.render(make_case([]))

    assert "Nothing here was delivered to a regulator by this system" in document
    assert "sandbox outbox" in document


def test_the_pack_carries_the_case_the_complaint_rests_on():
    document = pack.render(make_case([]))

    assert "Municipal Corporation of Delhi" in document
    assert "Solid Waste Management Rules, 2016" in document
    assert "Two VIIRS detections within 3 km." in document
    assert "Minto Road, New Delhi" in document
    assert "Filed to Municipal Corporation of Delhi" in document


def test_a_fallback_authority_match_is_flagged_in_the_pack():
    case = make_case([])
    case.jurisdiction.coverage = "fallback"
    case.jurisdiction.coverage_note = "The local body is not in the table; this is one tier up."

    document = pack.render(case)

    assert "not an exact entry in the jurisdiction table" in document
    assert "one tier up" in document


# --------------------------------------------------------------------------- #
# The locator diagram
# --------------------------------------------------------------------------- #


def test_the_map_is_an_svg_drawn_from_the_cases_own_coordinates():
    document = pack.render(make_case([]))

    assert "<svg" in document and "</svg>" in document
    assert "A diagram, not a map" in document
    # The back-traced upwind point from the corroboration fake is marked.
    assert "Upwind point" in document
    assert "stroke-dasharray" in document


def test_the_diagram_works_for_a_case_with_one_point_and_no_wind():
    case = make_case([])
    case.corroboration.upwind_source_latitude = None
    case.corroboration.upwind_source_longitude = None

    svg = pack.locator_svg(case)

    assert svg.startswith("<svg")
    assert "Upwind point" not in svg
    # A single point still gets a scale bar rather than a division by zero.
    assert re.search(r">\d+(?:\.\d+)? ?(?:m|km)<", svg)


# --------------------------------------------------------------------------- #
# The endpoint
# --------------------------------------------------------------------------- #


async def test_the_pack_endpoint_serves_html(client):
    store.save(make_case([photo_on_disk()]))

    resp = await client.get("/cases/VD-PACK0001/pack")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "VD-PACK0001-evidence-pack.html" in resp.headers["content-disposition"]
    assert "शिकायत का मुख्य भाग।" in resp.text
    assert CONTACT not in resp.text


async def test_the_pack_of_an_unknown_case_is_a_404(client):
    assert (await client.get("/cases/VD-NOPE/pack")).status_code == 404


async def test_a_pack_can_be_produced_the_moment_a_case_exists(client, monkeypatch):
    """Not only for filed cases: the pack is how a citizen reads their own case."""
    patch_stages(monkeypatch, pipeline)
    resp = await client.post(
        "/reports",
        data={"latitude": "28.6139", "longitude": "77.2090"},
        files={"image": ("photo.png", PNG, "image/png")},
    )
    case_id = resp.json()["case_id"]
    await _drain()

    document = await client.get(f"/cases/{case_id}/pack")

    assert document.status_code == 200
    assert "awaiting confirmation" in document.text
    assert "data:image/png;base64," in document.text
