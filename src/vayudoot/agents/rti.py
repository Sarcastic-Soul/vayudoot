"""Right to Information drafting, for a complaint the authority ignored.

When the statutory window lapses, a second email is not a lever — the authority
already ignored the first one, and there is no duty to answer either. An
application under the Right to Information Act, 2005 is different in kind: it is
addressed to a designated Public Information Officer, it carries a statutory
thirty-day duty to reply under section 7(1), and a non-reply is itself a deemed
refusal that opens a first appeal under section 19(1). It converts silence from a
dead end into a step in a process with dates attached.

Two things follow from that and shape everything here.

The document is not a stronger complaint. An RTI application asks only for
information already on a file. Phrase it as a demand for action and it is refused
under section 2(f) as not being a request for information, and the applicant has
burned thirty days. The prompt spends most of its length on that one distinction.

The system cannot file it. An RTI application is made by a named citizen, with a
declaration of citizenship and a fee instrument, to an office whose real RTI
channel this instance does not know. So this module drafts and renders; nothing
sends. Every field only a human can supply is a bracketed placeholder in the text
and an entry in `placeholders`, and the authority address carried through is the
same `.invalid` placeholder the rest of the system uses.

Model tier is `primary`, deliberately. Constraint 5 reserves the primary tier for
judgement and this is the same judgement as complaint drafting: producing a legal
instrument whose failure mode is a rejection on a phrasing rule. It calls no
tools, so there is nothing mechanical here for the fast tier to do, and the cost
is one call for the small minority of cases that go unanswered past their window
— cached on the case afterwards so a redraft has to be asked for.
"""

from __future__ import annotations

from strands import Agent

from ..models import build_model
from ..schemas import Case, RTIApplication
from .prompts import RTI

#: Stamped on every rendered application. The complaint has an envelope with an
#: X-Vayudoot-Mode header saying the same thing; this document has no envelope,
#: because it is never handed to a transport at all.
NOT_FILED_NOTICE = (
    "[DRAFT — NOT FILED. Vayudoot does not send anything. Complete the bracketed fields "
    "below, then file this yourself through the authority's own RTI channel or at an RTI "
    "counter.]"
)


def build_rti_agent() -> Agent:
    return Agent(
        name="rti",
        model=build_model(temperature=0.2),
        system_prompt=RTI,
        callback_handler=None,
    )


async def draft_rti_application(case: Case, agent: Agent | None = None) -> RTIApplication:
    """Draft an RTI application asking what was done about this case's complaint."""
    if case.jurisdiction is None or case.complaint is None:
        raise ValueError("Case has no filed complaint to ask about")

    agent = agent or build_rti_agent()
    filed_on = case.filed_at.date().isoformat() if case.filed_at else "an unrecorded date"
    escalated_on = case.escalated_at.date().isoformat() if case.escalated_at else ""
    acknowledged_on = case.acknowledged_at.date().isoformat() if case.acknowledged_at else ""

    prompt = f"""Draft an RTI application for this unanswered complaint.

PUBLIC AUTHORITY
  Name: {case.jurisdiction.authority_name} ({case.jurisdiction.authority_tier})
  Office: {case.jurisdiction.office or '(no office address on record)'}
  Statute the complaint was filed under: {case.jurisdiction.statute}
  Section: {case.jurisdiction.section}
  Statutory response window: {case.jurisdiction.response_window_days} days

THE COMPLAINT THIS CONCERNS
  Internal reference: {case.case_id}
  Filed on: {filed_on}
  Acknowledged on: {acknowledged_on or '(never acknowledged)'}
  Escalated on: {escalated_on or '(not escalated)'}
  Current status: {case.status.value}
  Subject: {case.complaint.subject}
  Requested action: {case.complaint.requested_action or '(not recorded)'}
  Authority's response, if any: {case.response_note or '(none received)'}

THE UNDERLYING EVENT
  Observed at: {case.report.observed_at.isoformat()}
  Location: {case.address or f"{case.report.latitude}, {case.report.longitude}"}
  Coordinates: {case.report.latitude}, {case.report.longitude}
  Type: {case.evidence.pollution_type.value if case.evidence else 'not classified'}
  Severity: {case.evidence.severity if case.evidence else 'not classified'}

The applicant has no reference number issued by the authority, because none was
given. Where a reference number would normally go, ask the authority to supply it
rather than inventing one, and leave a placeholder for the applicant if they have
one from another channel."""

    result = await agent.invoke_async(prompt, structured_output_model=RTIApplication)
    application: RTIApplication = result.structured_output
    application.body_en = render_rti(application, case)
    return application


def render_rti(application: RTIApplication, case: Case) -> str:
    """Assemble the filing-ready text.

    Deterministic rather than model-written. The statutory scaffolding of an RTI
    application — the section 6(1) heading, the citizenship declaration, the
    applicant block, the appeal note — is fixed by law and identical on every
    application, so there is nothing for a model to decide and every reason for it
    to come out the same each time. The model writes the parts that are about this
    complaint; this writes the form around them.
    """
    authority = case.jurisdiction.authority_name if case.jurisdiction else ""
    on_record = case.jurisdiction.email if case.jurisdiction else ""
    filed_on = case.filed_at.date().isoformat() if case.filed_at else "an unrecorded date"

    questions = "\n".join(
        f"{n}. {question}" for n, question in enumerate(application.questions, start=1)
    ) or "1. [NO QUESTIONS WERE DRAFTED — do not file this application as it stands.]"

    placeholders = "\n".join(f"  - {item}" for item in application.placeholders)

    # `None` marks a line that is absent for this application; empty strings are
    # real blank lines in the layout and must survive.
    lines: list[str | None] = [
        NOT_FILED_NOTICE,
        "",
        "To,",
        application.pio_designation or "The Public Information Officer",
        application.public_authority or authority,
        application.office_address or "[OFFICE ADDRESS — confirm the RTI cell's address]",
        "",
        f"Subject: {application.subject}",
        "",
        "Application under Section 6(1) of the Right to Information Act, 2005",
        "",
        "Sir/Madam,",
        "",
        application.preamble,
        "",
        "I request the following information held by your public authority:",
        "",
        questions,
        "",
        f"Fee: {application.fee_note}" if application.fee_note else None,
        f"Appeal: {application.appeal_note}" if application.appeal_note else None,
        "",
        (
            "I am a citizen of India. I request that the information be provided within "
            "the thirty days allowed by Section 7(1) of the Act."
        ),
        "",
        "Applicant: [FULL NAME]",
        "Address: [POSTAL ADDRESS FOR THE REPLY]",
        f"Contact: {case.report.reporter_contact or '[TELEPHONE OR EMAIL]'}",
        "Date: [DATE OF SUBMISSION]",
        "Signature: [SIGNATURE]",
        "",
        "--",
        (
            f"Originating complaint: Vayudoot case {case.case_id}, filed with "
            f"{authority} on {filed_on}."
        ),
        (
            f"Authority address on record in this instance: {on_record} — this is a "
            "reserved placeholder address, not a real one. Replace it with the "
            "authority's published RTI channel before filing."
        ),
        "",
        "TO BE COMPLETED BEFORE FILING",
        placeholders or "  - The bracketed fields above.",
    ]
    return "\n".join(line for line in lines if line is not None)
