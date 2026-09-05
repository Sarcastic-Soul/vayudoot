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


def escalation_due(case: Case) -> bool:
    """True when the statutory response window has passed with no acknowledgement."""
    if case.status is not CaseStatus.FILED or case.filed_at is None or case.jurisdiction is None:
        return False
    deadline = case.filed_at + timedelta(days=case.jurisdiction.response_window_days)
    return datetime.now(UTC) >= deadline


def escalate(case: Case) -> Path:
    """Re-file to the next authority tier once the response window has lapsed."""
    if case.complaint is None or case.jurisdiction is None:
        raise ValueError("Case is not ready to escalate")
    if settings.vayudoot_live_filing:
        raise LiveFilingNotConfigured("Live filing is enabled but no transport is configured.")

    days = case.jurisdiction.response_window_days
    body = (
        f"This complaint was filed with {case.jurisdiction.authority_name} on "
        f"{case.filed_at.isoformat() if case.filed_at else 'unknown date'} and has received no "
        f"response within the {days}-day window. It is escalated for your attention.\n\n"
        f"{case.complaint.body_en}"
    )
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
    case.log(
        f"Escalated to {case.jurisdiction.escalation_authority} after {days} days "
        f"with no response (sandbox outbox: {path})"
    )
    return path
