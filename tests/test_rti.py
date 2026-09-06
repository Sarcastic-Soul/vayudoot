"""RTI follow-up drafting.

Two things are being asserted here. The first is the gate: an RTI application
only makes sense for a complaint that was actually filed and then ignored past
its window, and every other case has to be refused with a reason. The second is
the safety property — the drafted application is a document held for a human, not
something the system sends. No transport is touched, nothing reaches the outbox,
and every address that appears in the text is on the reserved `.invalid` TLD.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from fakes import StubAgent, complaint, jurisdiction, rti_application
from vayudoot import api, filing, store
from vayudoot.agents.rti import NOT_FILED_NOTICE, draft_rti_application, render_rti
from vayudoot.config import settings
from vayudoot.schemas import Case, CaseStatus, Report

#: Anything shaped like an address in a document a citizen might file.
ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def make_case(*, status: CaseStatus = CaseStatus.FILED, days_since_filing: int = 40) -> Case:
    case = Case(
        case_id="VD-RTI00001",
        status=status,
        report=Report(
            report_id="r1",
            latitude=28.6139,
            longitude=77.2090,
            reporter_contact="asha@example.invalid",
        ),
        jurisdiction=jurisdiction(),
        complaint=complaint(),
        address="Minto Road, New Delhi, Delhi",
    )
    if status is not CaseStatus.DRAFT:
        case.filed_at = datetime.now(UTC) - timedelta(days=days_since_filing)
    store.save(case)
    return case


@pytest.fixture
async def client():
    transport = ASGITransport(app=api.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def stub_agent(monkeypatch):
    """Replace the model call. Nothing in this suite needs a provider."""
    agent = StubAgent(rti_application())
    calls: list[Case] = []

    async def fake(case, agent_override=None):
        calls.append(case)
        return await draft_rti_application(case, agent=agent)

    monkeypatch.setattr(api, "draft_rti_application", fake)
    fake.calls = calls  # type: ignore[attr-defined]
    return fake


# --------------------------------------------------------------------------- #
# The gate
# --------------------------------------------------------------------------- #


def test_the_window_is_measured_from_filing_and_nothing_restarts_it():
    """The one place this differs from `escalation_due`.

    An acknowledgement buys the authority a fresh escalation window because it is
    a promise to act. It does not reset the record an applicant is asking for, so
    the RTI clock keeps running from the day the complaint was filed.
    """
    fresh = make_case(days_since_filing=1)
    assert filing.rti_available(fresh) is False

    lapsed = make_case(days_since_filing=40)
    assert filing.rti_available(lapsed) is True

    acknowledged = make_case(status=CaseStatus.ACKNOWLEDGED, days_since_filing=40)
    acknowledged.acknowledged_at = datetime.now(UTC)
    assert filing.rti_available(acknowledged) is True
    # The same case is not escalatable, because that clock did restart.
    assert filing.escalation_due(acknowledged) is False


def test_an_escalated_case_can_still_ask_what_was_done():
    """Escalation and an RTI are different acts against different offices."""
    case = make_case(status=CaseStatus.ESCALATED, days_since_filing=60)
    assert filing.rti_available(case) is True


@pytest.mark.parametrize(
    "status",
    [CaseStatus.AWAITING_CONFIRMATION, CaseStatus.RESOLVED, CaseStatus.WITHDRAWN],
)
def test_a_case_that_is_not_an_ignored_complaint_is_refused(status):
    case = make_case(status=status, days_since_filing=90)
    assert filing.rti_available(case) is False


async def test_the_endpoint_refuses_before_the_window_lapses(client, stub_agent):
    case = make_case(days_since_filing=2)
    resp = await client.post(f"/cases/{case.case_id}/rti")

    assert resp.status_code == 409
    assert "statutory window since filing has not lapsed" in resp.json()["detail"]
    assert stub_agent.calls == []
    assert store.load(case.case_id).rti is None


async def test_the_endpoint_explains_a_status_refusal_differently(client, stub_agent):
    case = make_case(status=CaseStatus.RESOLVED, days_since_filing=90)
    resp = await client.post(f"/cases/{case.case_id}/rti")

    assert resp.status_code == 409
    assert "went unanswered" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
# Drafting
# --------------------------------------------------------------------------- #


async def test_drafting_stores_the_application_on_the_case(client, stub_agent):
    case = make_case()
    body = (await client.post(f"/cases/{case.case_id}/rti")).json()

    assert body["rti"]["public_authority"] == "Municipal Corporation of Delhi"
    assert len(body["rti"]["questions"]) == 3
    assert body["rti_drafted_at"] is not None
    assert body["status"] == CaseStatus.FILED.value  # drafting changes nothing else

    stored = store.load(case.case_id)
    assert stored.rti is not None
    assert any("RTI application drafted" in entry for entry in stored.history)


async def test_a_second_request_reuses_the_draft_rather_than_the_model(client, stub_agent):
    """One primary-tier call per case. Inference is the only running cost."""
    case = make_case()
    first = (await client.post(f"/cases/{case.case_id}/rti")).json()
    second = (await client.post(f"/cases/{case.case_id}/rti")).json()

    assert len(stub_agent.calls) == 1
    assert first["rti"]["body_en"] == second["rti"]["body_en"]

    await client.post(f"/cases/{case.case_id}/rti?redraft=true")
    assert len(stub_agent.calls) == 2


async def test_the_text_endpoint_serves_the_rendered_application(client, stub_agent):
    case = make_case()
    assert (await client.get(f"/cases/{case.case_id}/rti")).status_code == 404

    await client.post(f"/cases/{case.case_id}/rti")
    text = (await client.get(f"/cases/{case.case_id}/rti")).text
    assert text.startswith(NOT_FILED_NOTICE)
    assert "Section 6(1) of the Right to Information Act, 2005" in text


async def test_the_prompt_gives_the_model_the_case_and_never_an_officer_name(client):
    case = make_case()
    agent = StubAgent(rti_application())
    await draft_rti_application(case, agent=agent)

    prompt = agent.prompts[0]
    assert case.case_id in prompt
    assert "Municipal Corporation of Delhi" in prompt
    assert case.filed_at.date().isoformat() in prompt
    assert "no reference number issued by the authority" in prompt


async def test_drafting_refuses_a_case_with_no_complaint_to_ask_about():
    case = make_case()
    case.complaint = None
    with pytest.raises(ValueError, match="no filed complaint"):
        await draft_rti_application(case, agent=StubAgent(rti_application()))


# --------------------------------------------------------------------------- #
# Safety: it is a document, not a transmission
# --------------------------------------------------------------------------- #


async def test_nothing_is_sent_and_nothing_reaches_the_outbox(client, stub_agent):
    case = make_case()
    await client.post(f"/cases/{case.case_id}/rti")

    outbox = settings.vayudoot_sandbox_outbox
    written = list(outbox.glob("*")) if outbox.exists() else []
    assert written == [], "an RTI application must not be handed to any transport"
    assert store.load(case.case_id).status is CaseStatus.FILED


async def test_every_address_in_the_drafted_application_is_reserved(client, stub_agent):
    case = make_case()
    await client.post(f"/cases/{case.case_id}/rti")
    text = (await client.get(f"/cases/{case.case_id}/rti")).text

    addresses = ADDRESS.findall(text)
    assert addresses, "the authority's address on record should be carried through"
    for address in addresses:
        assert address.endswith(".invalid"), f"{address} is not a reserved address"


def test_the_rendered_form_says_what_a_human_must_still_supply():
    case = make_case()
    text = render_rti(rti_application(), case)

    assert NOT_FILED_NOTICE in text
    assert "TO BE COMPLETED BEFORE FILING" in text
    for placeholder in ("[FULL NAME]", "[POSTAL ADDRESS FOR THE REPLY]", "[DATE OF SUBMISSION]"):
        assert placeholder in text
    # The authority address is a placeholder and the document has to say so.
    assert "placeholder address, not a real one" in text
    assert "I am a citizen of India." in text


def test_the_questions_are_numbered_in_order():
    case = make_case()
    text = render_rti(rti_application(), case)
    assert "1. The reference number" in text
    assert "3. The name and designation" in text


def test_an_application_with_no_questions_refuses_to_look_fileable():
    case = make_case()
    application = rti_application()
    application.questions = []
    assert "do not file this application as it stands" in render_rti(application, case)
