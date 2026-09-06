"""Filing and escalation.

SAFETY: live filing sends a formal complaint to a real regulator. It is disabled
unless VAYUDOOT_LIVE_FILING is explicitly true AND a real transport is wired in,
which it deliberately is not in this repository. Every demo run writes the
complaint to a local sandbox outbox instead. An unattended prototype must not be
able to spam a pollution control board.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import settings
from .schemas import Case, CaseStatus


class LiveFilingNotConfigured(RuntimeError):
    """Raised if live filing is switched on without a transport being wired in."""


def _outbox() -> Path:
    settings.vayudoot_sandbox_outbox.mkdir(parents=True, exist_ok=True)
    return settings.vayudoot_sandbox_outbox


def render(case: Case, recipient: str, subject: str, body: str) -> str:
    return (
        f"To: {recipient}\n"
        f"Subject: {subject}\n"
        f"Case-Id: {case.case_id}\n"
        f"X-Vayudoot-Mode: {'LIVE' if settings.vayudoot_live_filing else 'SANDBOX'}\n"
        f"\n{body}\n"
    )


def file_complaint(case: Case) -> Path:
    """Deliver the complaint. Writes to the sandbox outbox unless live filing is on."""
    if case.complaint is None or case.jurisdiction is None:
        raise ValueError("Case is not ready to file: complaint or jurisdiction missing")

    if settings.vayudoot_live_filing:
        raise LiveFilingNotConfigured(
            "Live filing is enabled but no delivery transport is configured. "
            "Wire a real transport deliberately, and confirm the recipient address is "
            "correct, before sending anything to an actual regulator."
        )

    envelope = render(
        case,
        recipient=case.jurisdiction.email,
        subject=case.complaint.subject,
        body=case.complaint.body_en,
    )
    path = _outbox() / f"{case.case_id}.eml"
    path.write_text(envelope)

    case.status = CaseStatus.FILED
    case.filed_at = datetime.now(UTC)
    case.log(f"Filed to {case.jurisdiction.authority_name} (sandbox outbox: {path})")
    return path


#: The statuses an escalation clock runs in, and the date each one runs from.
#:
#: An acknowledgement is a receipt, not a remedy, so it does not stop the clock —
#: otherwise one automated "we have received your complaint" would silence the
#: tracker forever, which is the exact behaviour this project exists to counter.
#: What it does is restart the clock from the day the authority replied. That is
#: fair in both directions: an authority that answers on day 29 is not escalated
#: the next morning, and an authority that answers and then does nothing is still
#: escalated a full window later.
#:
#: `escalated` is absent deliberately: a case is escalated once, to the tier
#: above. There is no third tier in the authority table to escalate to.
ESCALATION_CLOCK: dict[CaseStatus, str] = {
    CaseStatus.FILED: "filed_at",
    CaseStatus.ACKNOWLEDGED: "acknowledged_at",
}


def escalation_due(case: Case) -> bool:
    """True when the statutory response window has passed without the case moving.

    A resolved, withdrawn or already escalated case is never due, whatever its
    dates say.
    """
    started_field = ESCALATION_CLOCK.get(case.status)
    if started_field is None or case.jurisdiction is None:
        return False
    started_at = getattr(case, started_field)
    if started_at is None:
        return False
    return datetime.now(UTC) >= started_at + timedelta(days=case.jurisdiction.response_window_days)


#: Statuses an RTI application can be drafted from. A case that was never filed
#: has no complaint to ask about; a resolved or withdrawn one has nothing left to
#: ask. Escalated is included deliberately — escalating to the tier above and
#: asking the original authority what it did with the complaint are different
#: acts against different offices, and a citizen may well want both.
RTI_FROM: tuple[CaseStatus, ...] = (
    CaseStatus.FILED,
    CaseStatus.ACKNOWLEDGED,
    CaseStatus.ESCALATED,
)


def rti_available(case: Case) -> bool:
    """True when a case has gone unanswered long enough to justify an RTI.

    The clock runs from `filed_at` and nothing restarts it, which is the one
    place this differs from `escalation_due`. An acknowledgement restarts the
    escalation clock because it is a promise to act and deserves a fresh window.
    It does not restart this one: the question an RTI asks is "what is on the
    file about the complaint I filed on that date", and a receipt is not an
    answer to it. An escalated case is past its window by definition and stays
    eligible.
    """
    if case.status not in RTI_FROM:
        return False
    if case.jurisdiction is None or case.complaint is None or case.filed_at is None:
        return False
    window = timedelta(days=case.jurisdiction.response_window_days)
    return datetime.now(UTC) >= case.filed_at + window


def escalate(case: Case) -> Path:
    """Re-file to the next authority tier once the response window has lapsed."""
    if case.complaint is None or case.jurisdiction is None:
        raise ValueError("Case is not ready to escalate")
    if settings.vayudoot_live_filing:
        raise LiveFilingNotConfigured("Live filing is enabled but no transport is configured.")

    was_acknowledged = case.status is CaseStatus.ACKNOWLEDGED
    days = case.jurisdiction.response_window_days
    filed_on = case.filed_at.isoformat() if case.filed_at else "unknown date"
    if case.status is CaseStatus.ACKNOWLEDGED and case.acknowledged_at is not None:
        # Escalating an acknowledged case is a different complaint from escalating
        # an ignored one, and the escalation authority should be told which it is.
        preamble = (
            f"This complaint was filed with {case.jurisdiction.authority_name} on {filed_on} "
            f"and acknowledged on {case.acknowledged_at.isoformat()}, but no remedial action "
            f"has followed within the {days}-day window since that acknowledgement. It is "
            f"escalated for your attention."
        )
    else:
        preamble = (
            f"This complaint was filed with {case.jurisdiction.authority_name} on {filed_on} "
            f"and has received no response within the {days}-day window. It is escalated for "
            f"your attention."
        )
    body = f"{preamble}\n\n{case.complaint.body_en}"
    envelope = render(
        case,
        recipient=case.jurisdiction.escalation_email,
        subject=f"ESCALATED: {case.complaint.subject}",
        body=body,
    )
    path = _outbox() / f"{case.case_id}-escalated.eml"
    path.write_text(envelope)

    case.status = CaseStatus.ESCALATED
    case.escalated_at = datetime.now(UTC)
    since = "no remedial action" if was_acknowledged else "no response"
    case.log(
        f"Escalated to {case.jurisdiction.escalation_authority} after {days} days "
        f"with {since} (sandbox outbox: {path})"
    )
    return path
