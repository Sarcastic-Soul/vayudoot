"""What happens to a case after it has been filed.

Filing and escalation are in `filing.py` because they produce an envelope and
are governed by the live-filing safety rule. These three are different: nothing
leaves the building. They record what came back — the authority replied, the
problem was fixed, the citizen changed their mind — and they are the half of
"track and escalate" that closes a case rather than chasing it.

Each transition is a plain function on a `Case`. It validates the status it is
allowed from, sets the fields, and appends to `history`; persisting is the
caller's job, exactly as it is for `filing.file_complaint`.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from .schemas import TERMINAL_STATUSES, Case, CaseStatus


class InvalidTransition(RuntimeError):
    """The case is not in a status this transition is allowed from."""

    def __init__(self, case: Case, allowed: Iterable[CaseStatus]) -> None:
        names = ", ".join(status.value for status in allowed)
        super().__init__(f"Case is {case.status.value}; this is only possible from: {names}")
        self.case_status = case.status


#: An authority can only respond to something it was actually sent.
ACKNOWLEDGE_FROM = (CaseStatus.FILED, CaseStatus.ESCALATED)

#: A case can be closed as resolved whether or not anyone ever acknowledged it.
#: The point is the pollution stopping, not the paperwork.
RESOLVE_FROM = (CaseStatus.FILED, CaseStatus.ESCALATED, CaseStatus.ACKNOWLEDGED)

#: Anything that has not already ended can be taken back.
WITHDRAW_FROM = tuple(status for status in CaseStatus if status not in TERMINAL_STATUSES)


def _require(case: Case, allowed: Iterable[CaseStatus]) -> None:
    if case.status not in tuple(allowed):
        raise InvalidTransition(case, allowed)


def acknowledge(case: Case, note: str = "", at: datetime | None = None) -> Case:
    """Record that the authority responded.

    `at` is when the response arrived, which is not necessarily now: a citizen
    entering a letter dated last week should be able to say so, and the
    escalation clock restarts from that date rather than from data entry.
    """
    _require(case, ACKNOWLEDGE_FROM)

    responded_at = at or datetime.now(UTC)
    if responded_at.tzinfo is None:
        responded_at = responded_at.replace(tzinfo=UTC)

    case.status = CaseStatus.ACKNOWLEDGED
    case.acknowledged_at = responded_at
    case.response_note = note.strip()
    authority = case.jurisdiction.authority_name if case.jurisdiction else "the authority"
    case.log(
        f"Acknowledged by {authority} on {responded_at.date().isoformat()}"
        + (f": {case.response_note}" if case.response_note else "")
    )
    return case


def resolve(case: Case, note: str = "") -> Case:
    """Close the case: the underlying problem was actually dealt with."""
    _require(case, RESOLVE_FROM)

    case.status = CaseStatus.RESOLVED
    case.resolved_at = datetime.now(UTC)
    case.resolution_note = note.strip()
    case.log("Resolved" + (f": {case.resolution_note}" if case.resolution_note else ""))
    return case


def withdraw(case: Case, note: str = "") -> Case:
    """The citizen takes the complaint back.

    Allowed from anything that has not already ended, including before filing —
    a report submitted by mistake or against the wrong location should be
    stoppable without waiting for the pipeline to finish with it.
    """
    if case.status in TERMINAL_STATUSES:
        raise InvalidTransition(case, WITHDRAW_FROM)

    case.status = CaseStatus.WITHDRAWN
    case.withdrawn_at = datetime.now(UTC)
    case.withdrawal_note = note.strip()
    reason = f": {case.withdrawal_note}" if case.withdrawal_note else ""
    case.log(f"Withdrawn by the citizen{reason}")
    return case
