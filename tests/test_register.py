"""The public register, and the privacy line it has to hold.

The register is the one surface in this project where getting a field wrong
publishes a citizen's phone number. So most of what is checked here is not that
the right things appear but that the wrong ones cannot: the projection is an
allowlist, the contact is absent from every string in the output, and a case the
citizen took back stops being visible at all.
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from fakes import complaint, corroboration, evidence, image_bytes, jurisdiction, patch_stages
from vayudoot import api, lifecycle, pipeline, register, store
from vayudoot.schemas import Case, CaseStatus, Report, Stage

PNG = image_bytes("PNG")

CONTACT = "priya.sharma@example.invalid"
PHONE = "+91 98765 43210"

#: Every field the register may publish. A change to this set is a change to what
#: the register discloses, so it is written down rather than derived: a new field
#: on `PublicCase` fails this test until somebody has looked at it.
PUBLISHED_FIELDS = {
    "case_id",
    "status",
    "stage",
    "address",
    "latitude",
    "longitude",
    "observed_at",
    "photograph_count",
    "cluster_id",
    "filed_at",
    "acknowledged_at",
    "escalated_at",
    "resolved_at",
    "evidence",
    "corroboration",
    "jurisdiction",
    "complaint",
}


@pytest.fixture
async def client():
    transport = ASGITransport(app=api.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _drain() -> None:
    while api._running:
        await asyncio.gather(*list(api._running), return_exceptions=True)


def make_case(
    case_id: str = "VD-TESTCASE",
    status: CaseStatus = CaseStatus.FILED,
    contact: str = CONTACT,
    note: str = "Burning behind our lane",
) -> Case:
    case = Case(
        case_id=case_id,
        report=Report(
            report_id="r",
            latitude=28.6139,
            longitude=77.2090,
            note=note,
            reporter_contact=contact,
        ),
        status=status,
        stage=Stage.COMPLETE,
        evidence=evidence(),
        corroboration=corroboration(),
        jurisdiction=jurisdiction(),
        complaint=complaint(),
        address="Minto Road, New Delhi",
    )
    return case


def strings_in(public: register.PublicCase) -> str:
    """Every string the register would serve for this case, flattened."""
    return public.model_dump_json()


# --------------------------------------------------------------------------- #
# Who is public
# --------------------------------------------------------------------------- #


def test_only_filed_cases_are_public():
    public = {status for status in CaseStatus if register.is_public(make_case(status=status))}

    assert public == {
        CaseStatus.FILED,
        CaseStatus.ACKNOWLEDGED,
        CaseStatus.ESCALATED,
        CaseStatus.RESOLVED,
    }


def test_a_case_nobody_confirmed_is_not_public():
    """A draft is a machine's opinion about a place until a human confirms it."""
    assert not register.is_public(make_case(status=CaseStatus.DRAFT))
    assert not register.is_public(make_case(status=CaseStatus.AWAITING_CONFIRMATION))


def test_a_case_that_failed_the_confidence_floor_is_not_public():
    assert not register.is_public(make_case(status=CaseStatus.REJECTED))
    assert not register.is_public(make_case(status=CaseStatus.FAILED))


def test_withdrawing_a_filed_case_removes_it_from_the_register():
    """Withdrawal is a revocation of the consent the register runs on."""
    case = make_case()
    assert register.is_public(case)

    lifecycle.withdraw(case, note="Wrong location")

    assert not register.is_public(case)


# --------------------------------------------------------------------------- #
# The allowlist
# --------------------------------------------------------------------------- #


def test_the_published_field_list_is_exactly_what_was_reviewed():
    assert set(register.PublicCase.model_fields) == PUBLISHED_FIELDS


def test_the_reporter_contact_never_appears():
    served = strings_in(register.project(make_case()))

    assert CONTACT not in served
    assert "reporter_contact" not in served


def test_a_contact_that_leaked_into_the_complaint_is_scrubbed():
    """The allowlist cannot catch this one; the scrub behind it can.

    The complaint body is written by a model that was shown the citizen's note,
    and a note routinely carries a phone number.
    """
    case = make_case(contact=PHONE, note=f"Burning behind our lane, call me on {PHONE}")
    case.complaint.body_en = f"The complainant may be reached on {PHONE} for an inspection."
    case.address = f"Minto Road, New Delhi ({PHONE})"

    served = strings_in(register.project(case))

    assert PHONE not in served
    assert "[contact withheld]" in served


def test_the_citizens_own_note_is_not_published():
    case = make_case(note="Burning behind our lane, ask for Priya at house 14")

    assert "house 14" not in strings_in(register.project(case))


def test_lifecycle_notes_are_not_published():
    """Free text typed after filing can name an officer or a neighbour."""
    case = make_case()
    lifecycle.acknowledge(case, note="Inspector Rakesh Menon called on Tuesday")
    lifecycle.resolve(case, note="Sorted out by the neighbour at number 12")

    served = strings_in(register.project(case))

    assert "Rakesh Menon" not in served
    assert "number 12" not in served
    assert register.project(case).resolved_at is not None


def test_the_history_log_is_not_published():
    case = make_case()
    case.log(f"Filed on behalf of {CONTACT}")

    assert CONTACT not in strings_in(register.project(case))
    assert "history" not in strings_in(register.project(case))


def test_landmarks_and_authority_addresses_are_not_published():
    case = make_case()
    case.evidence.landmarks = ["Sign reading Sharma Metal Works"]

    served = strings_in(register.project(case))

    assert "Sharma Metal Works" not in served
    assert "mcd@example.invalid" not in served


def test_what_the_register_does_publish():
    """The record has to actually carry the complaint, or it records nothing."""
    public = register.project(make_case())

    assert public.complaint.subject == "Open burning of waste at Minto Road"
    assert public.complaint.body_local == "शिकायत का मुख्य भाग।"
    assert public.jurisdiction.authority_name == "Municipal Corporation of Delhi"
    assert public.evidence.pollution_type.value == "open_waste_burning"
    assert public.corroboration.corroborated is True
    assert public.address == "Minto Road, New Delhi"


# --------------------------------------------------------------------------- #
# The endpoints
# --------------------------------------------------------------------------- #


async def test_the_register_lists_only_filed_cases(client):
    store.save(make_case("VD-FILED0001", status=CaseStatus.FILED))
    store.save(make_case("VD-DRAFT0001", status=CaseStatus.DRAFT))
    store.save(make_case("VD-GONE0001", status=CaseStatus.WITHDRAWN))

    listed = (await client.get("/register")).json()

    assert [entry["case_id"] for entry in listed] == ["VD-FILED0001"]
    assert CONTACT not in (await client.get("/register")).text


async def test_a_case_the_register_does_not_publish_is_a_404(client):
    store.save(make_case("VD-GONE0001", status=CaseStatus.WITHDRAWN))

    # 404 rather than 403: the register must not confirm that a withdrawn
    # complaint was ever made.
    assert (await client.get("/register/VD-GONE0001")).status_code == 404
    assert (await client.get("/register/VD-NOSUCH")).status_code == 404


async def test_one_public_case_is_served_without_the_contact(client):
    store.save(make_case("VD-FILED0001"))

    resp = await client.get("/register/VD-FILED0001")

    assert resp.status_code == 200
    assert CONTACT not in resp.text
    assert resp.json()["complaint"]["body_en"] == "Body of the complaint."


async def test_the_register_serves_photographs_only_for_public_cases(client, monkeypatch):
    patch_stages(monkeypatch, pipeline)
    resp = await client.post(
        "/reports",
        data={"latitude": "28.6139", "longitude": "77.2090", "contact": CONTACT},
        files={"image": ("photo.png", PNG, "image/png")},
    )
    case_id = resp.json()["case_id"]
    await _drain()

    # Not filed yet, so not in the register.
    assert (await client.get(f"/register/{case_id}/photo")).status_code == 404

    await client.post(f"/cases/{case_id}/confirm")
    photo = await client.get(f"/register/{case_id}/photo")
    assert photo.status_code == 200
    assert photo.content == PNG

    case = store.load(case_id)
    lifecycle.withdraw(case)
    store.save(case)
    assert (await client.get(f"/register/{case_id}/photo")).status_code == 404


async def test_the_register_reports_how_many_photographs_a_case_carries(client, monkeypatch):
    patch_stages(monkeypatch, pipeline)
    resp = await client.post(
        "/reports",
        data={"latitude": "28.6139", "longitude": "77.2090"},
        files=[
            ("image", ("one.png", PNG, "image/png")),
            ("image", ("two.png", PNG, "image/png")),
        ],
    )
    case_id = resp.json()["case_id"]
    await _drain()
    await client.post(f"/cases/{case_id}/confirm")

    assert (await client.get(f"/register/{case_id}")).json()["photograph_count"] == 2
    assert (await client.get(f"/register/{case_id}/photo/1")).status_code == 200


def test_a_short_contact_is_left_alone(monkeypatch):
    """A two-character contact would match inside ordinary words.

    The allowlist is what keeps such a contact out of the register; blanking every
    occurrence of "hi" across a complaint would destroy the document to protect
    nothing.
    """
    case = make_case(contact="hi")

    assert "complaint" in strings_in(register.project(case))


def test_the_register_survives_an_empty_store():
    assert register.register() == []


# -- the case routes themselves ------------------------------------------


async def test_no_case_route_leaks_the_reporter_contact(client, monkeypatch):
    """The register is an allowlist, but it was never the leak.

    There is no login here by design, so `GET /cases` is world-readable. Before
    this guard, one unauthenticated request returned every contact ever
    submitted, and `GET /cases/{id}` returned one to anyone holding an id. The
    contact is still needed server-side — the RTI names an applicant, clustering
    counts distinct reporters — so it stays on the model and is excluded at the
    boundary instead.
    """
    patch_stages(monkeypatch, pipeline)
    contact = "leaky@example.invalid"
    created = await client.post(
        "/reports",
        data={"latitude": "28.6", "longitude": "77.2", "contact": contact},
    )
    assert created.status_code == 202
    case_id = created.json()["case_id"]
    await _drain()

    # Stored, because the pipeline needs it.
    assert store.load(case_id).report.reporter_contact == contact

    routes = [
        ("get", "/cases"),
        ("get", f"/cases/{case_id}"),
        ("post", f"/cases/{case_id}/confirm"),
        ("post", f"/cases/{case_id}/withdraw"),
    ]
    for method, path in routes:
        resp = await getattr(client, method)(path)
        assert contact not in resp.text, f"{method.upper()} {path} leaked the contact"

    # And no future Case-returning route may forget the exclusion.
    unguarded = [
        route.path
        for route in api.app.routes
        if getattr(route, "response_model", None) in (Case, list[Case])
        and not getattr(route, "response_model_exclude", None)
    ]
    assert not unguarded, f"these routes return a Case without excluding the contact: {unguarded}"
