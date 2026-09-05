"""The case pipeline: photo in, filed and tracked complaint out.

Stages hand typed objects to one another rather than free text, so a failure is
localised and every intermediate result is inspectable. Stage 2 fans out into a
Strands agent graph internally; the rest are single agents.
"""

from __future__ import annotations

import uuid

from . import store
from .agents import analyse_evidence, corroborate, draft_complaint, resolve_jurisdiction
from .schemas import Case, CaseStatus, Report
from .tools.geocode import reverse_geocode

# Below this confidence the agent will not put a complaint in front of the user
# without flagging it. A wrong classification becomes a formal complaint against
# a real party.
CONFIDENCE_FLOOR = 0.55


def new_case(report: Report) -> Case:
    return Case(case_id=f"VD-{uuid.uuid4().hex[:8].upper()}", report=report)


async def run(report: Report, persist: bool = True) -> Case:
    """Run a report through every stage up to a complaint awaiting confirmation.

    Filing is deliberately not part of this function. A human confirms before
    anything is sent; see `vayudoot.filing.file_complaint`.
    """
    case = new_case(report)
    case.log("Report received")

    case.evidence = await analyse_evidence(report)
    case.log(
        f"Classified as {case.evidence.pollution_type.value} "
        f"({case.evidence.severity}, confidence {case.evidence.confidence:.2f})"
    )

    if case.evidence.confidence < CONFIDENCE_FLOOR:
        case.status = CaseStatus.REJECTED
        case.log(
            f"Halted: classification confidence {case.evidence.confidence:.2f} is below the "
            f"{CONFIDENCE_FLOOR} floor. A human should review the photograph before proceeding."
        )
        if persist:
            store.save(case)
        return case

    case.corroboration = await corroborate(report, case.evidence)
    case.log(
        "Corroborated by independent evidence"
        if case.corroboration.corroborated
        else "No independent corroboration found; proceeding with the citizen report alone"
    )

    case.jurisdiction = await resolve_jurisdiction(report, case.evidence)
    case.log(
        f"Jurisdiction: {case.jurisdiction.authority_name} "
        f"under {case.jurisdiction.statute}"
    )

    geo = reverse_geocode(report.latitude, report.longitude)
    case.address = geo.get("display_name", "") if isinstance(geo, dict) else ""

    case.complaint = await draft_complaint(
        report, case.evidence, case.corroboration, case.jurisdiction, case.address
    )
    case.status = CaseStatus.AWAITING_CONFIRMATION
    case.log("Complaint drafted, awaiting citizen confirmation before filing")

    if persist:
        store.save(case)
    return case
