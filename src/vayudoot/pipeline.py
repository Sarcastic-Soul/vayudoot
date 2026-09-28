"""The case pipeline: photo in, filed and tracked complaint out.

Stages hand typed objects to one another rather than free text, so a failure is
localised and every intermediate result is inspectable. Stage 2 fans out into a
Strands agent graph internally; the rest are single agents.

The case is persisted after every stage rather than once at the end. A full run
is minutes of model calls, and the interface polls the case while it runs, so
partial state has to be readable from disk the moment it exists.
"""

from __future__ import annotations

import logging
import uuid

from . import clustering, errors, store
from .agents import analyse_evidence, corroborate, draft_complaint, resolve_jurisdiction
from .agents.voice import TIER as VOICE_TIER
from .agents.voice import hear_voice_note
from .schemas import Case, CaseStatus, Cluster, Report, Stage
from .tools.authorities import coverage_is_generic
from .tools.geocode import reverse_geocode

log = logging.getLogger(__name__)

#: Which tier was doing the work when a given stage was running, so a failure
#: there can be traced to the provider actually responsible for it.
_TIER_FOR_STAGE = {
    Stage.EVIDENCE: "primary",
    Stage.CORROBORATION: "fast",
    Stage.JURISDICTION: "fast",
    Stage.DRAFTING: "primary",
}

# Below this confidence the agent will not put a complaint in front of the user
# without flagging it. A wrong classification becomes a formal complaint against
# a real party.
CONFIDENCE_FLOOR = 0.55


def new_case(report: Report) -> Case:
    return Case(case_id=f"VD-{uuid.uuid4().hex[:8].upper()}", report=report)


async def run(report: Report, persist: bool = True, case: Case | None = None) -> Case:
    """Run a report through every stage up to a complaint awaiting confirmation.

    Filing is deliberately not part of this function. A human confirms before
    anything is sent; see `vayudoot.filing.file_complaint`.

    `case` lets a caller supply a case that has already been created and saved,
    which is how the API returns a case id to the browser before the pipeline
    has finished running.
    """
    case = case or new_case(report)

    def checkpoint(stage: Stage) -> None:
        case.stage = stage
        if persist:
            store.save(case)

    if not case.history:
        case.log("Report received")
    checkpoint(Stage.RECEIVED)

    try:
        return await _run_stages(report, case, checkpoint, persist)
    except Exception as exc:  # a failed run must leave a readable case, not a 500
        log.exception("Pipeline failed for case %s", case.case_id)
        case.status = CaseStatus.FAILED
        tier = _TIER_FOR_STAGE.get(case.stage, "primary")
        case.error = errors.describe(exc, tier)
        case.log(f"Failed during {case.stage.value}: {case.error}")
        if persist:
            store.save(case)
        return case


async def _run_stages(report: Report, case: Case, checkpoint, persist: bool) -> Case:
    checkpoint(Stage.EVIDENCE)
    if report.audio_path and not await _hear(report, case):
        if persist:
            store.save(case)
        return case
    case.evidence = await analyse_evidence(report, voice=case.voice)
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
        checkpoint(Stage.HALTED)
        return case

    checkpoint(Stage.CORROBORATION)
    case.corroboration = await corroborate(report, case.evidence)
    case.log(
        "Corroborated by independent evidence"
        if case.corroboration.corroborated
        else "No independent corroboration found; proceeding with the citizen report alone"
    )

    checkpoint(Stage.JURISDICTION)
    case.jurisdiction = await resolve_jurisdiction(report, case.evidence)

    # The agent reports its own coverage, so check the one case that can be
    # checked: an address that only exists in the generic fallback entry means
    # the region was not in the table, whatever the model claimed.
    if coverage_is_generic(case.jurisdiction.email):
        case.jurisdiction.coverage = "generic"

    case.log(
        f"Jurisdiction: {case.jurisdiction.authority_name} under {case.jurisdiction.statute}"
    )
    if case.jurisdiction.coverage != "exact":
        case.log(
            f"Authority match is {case.jurisdiction.coverage}: "
            f"{case.jurisdiction.coverage_note or 'not an exact entry in the authority table'}"
        )

    geo = reverse_geocode(report.latitude, report.longitude)
    case.address = geo.get("display_name", "") if isinstance(geo, dict) else ""

    checkpoint(Stage.DRAFTING)
    cluster = _pattern(case)
    if cluster is not None:
        case.cluster_id = cluster.cluster_id
        case.log(clustering.describe(cluster, case.case_id))

    case.complaint = await draft_complaint(
        report,
        case.evidence,
        case.corroboration,
        case.jurisdiction,
        case.address,
        cluster=cluster,
        case_id=case.case_id,
        voice=case.voice,
    )
    case.status = CaseStatus.AWAITING_CONFIRMATION
    case.log("Complaint drafted, awaiting citizen confirmation before filing")

    checkpoint(Stage.COMPLETE)
    if persist:
        store.save(case)
    return case


async def _hear(report: Report, case: Case) -> bool:
    """Hear the voice note into `case.voice`. False when the run cannot go on.

    Runs inside the evidence stage rather than as a stage of its own: it exists
    to feed the evidence agent, and a new `Stage` would add a step to every
    case's timeline, voice note or not.

    A voice note that cannot be heard is not fatal when the report has anything
    else — a photograph or a written note is still a report, and failing it
    because a clip would not play would throw away what the citizen did send.
    It is fatal when the voice note was the whole report. Then the case fails
    here with the reason, rather than spending a primary-tier evidence call
    classifying an empty report into a halt that blames the photograph.

    Nothing here touches corroboration or confidence. The account is handed to
    the evidence and drafting stages as the reporter's claim, and that is all.
    """
    something_else = bool(report.image_paths or report.note.strip())
    try:
        case.voice = await hear_voice_note(report)
    except Exception as exc:  # noqa: BLE001 - a clip that will not play is not a failed report
        reason = errors.describe(exc, VOICE_TIER)
        log.warning("Voice note for case %s could not be heard: %s", case.case_id, reason)
        if something_else:
            case.log(f"The voice note could not be heard ({reason}); going on without it")
            return True
        case.status = CaseStatus.FAILED
        case.error = f"The voice note could not be heard, and it was the whole report. {reason}"
        case.log(f"Failed during {case.stage.value}: {case.error}")
        return False

    voice = case.voice
    if not voice.heard_speech:
        case.log("The voice note had no speech that could be made out")
        if not something_else:
            case.status = CaseStatus.FAILED
            case.error = (
                "The voice note had no speech that could be made out, and the report carries "
                "no photograph or written note to go on. Record it again closer to the phone."
            )
            case.log(f"Failed during {case.stage.value}: {case.error}")
            return False
        return True

    omitted = f"; {voice.names_omitted} name(s) left out" if voice.names_omitted else ""
    case.log(f"Voice note heard in {voice.language or 'an unidentified language'}{omitted}")
    return True


def _pattern(case: Case) -> Cluster | None:
    """The repeat-report pattern this case belongs to, if there is one.

    Never fatal. A complaint drafted without its pattern is weaker; a run that
    dies because the pattern lookup hit a half-written case file on disk is
    worse. The pipeline does not depend on a cluster existing and must not
    depend on the lookup succeeding either.
    """
    try:
        return clustering.cluster_for(case)
    except Exception:
        log.warning("Cluster lookup failed for case %s", case.case_id, exc_info=True)
        return None
