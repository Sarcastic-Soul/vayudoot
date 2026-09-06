"""Stage 4: write the complaint."""

from __future__ import annotations

from strands import Agent

from ..clustering import describe
from ..models import build_model
from ..schemas import Cluster, Complaint, Corroboration, EvidencePacket, Jurisdiction, Report
from .prompts import DRAFTING


def build_drafting_agent() -> Agent:
    return Agent(
        name="drafting",
        model=build_model(temperature=0.3),
        system_prompt=DRAFTING,
        callback_handler=None,
    )


async def draft_complaint(
    report: Report,
    evidence: EvidencePacket,
    corroboration: Corroboration,
    jurisdiction: Jurisdiction,
    address: str = "",
    cluster: Cluster | None = None,
    case_id: str = "",
    agent: Agent | None = None,
) -> Complaint:
    """Write the complaint.

    `cluster` is optional and stays optional. A first report is the normal case
    and must draft exactly as it always did; a repeat report gets one extra block
    in the prompt. Nothing here requires a pattern to exist.
    """
    agent = agent or build_drafting_agent()

    prompt = f"""Draft a formal complaint.

ADDRESSEE
  Authority: {jurisdiction.authority_name} ({jurisdiction.authority_tier})
  Office: {jurisdiction.office}
  Statute: {jurisdiction.statute}
  Section: {jurisdiction.section}

INCIDENT
  Observed at: {report.observed_at.isoformat()}
  Location: {address or f"{report.latitude}, {report.longitude}"}
  Coordinates: {report.latitude}, {report.longitude}
  Type: {evidence.pollution_type.value}
  Severity: {evidence.severity}
  Classification confidence: {evidence.confidence:.2f}
  Evidence basis: {_basis(report)}
  Reported indicators: {', '.join(evidence.visible_indicators) or 'none recorded'}
  Citizen's note: {report.note or '(none)'}

INDEPENDENT EVIDENCE
  Corroborated: {corroboration.corroborated}
  Air quality: {corroboration.air_quality_summary or '(no data)'}
  Satellite: {corroboration.satellite_summary or '(no data)'}
  Satellite detections: {corroboration.satellite_fire_detections}
  Wind: {corroboration.wind_speed_ms} m/s from {corroboration.wind_from_degrees} degrees
  Plausible upwind source: {corroboration.upwind_source_latitude}, \
{corroboration.upwind_source_longitude}
  Notes: {corroboration.corroboration_notes}
{_pattern_block(cluster, case_id)}
Write the complaint body citing only the statute and section given above."""

    result = await agent.invoke_async(prompt, structured_output_model=Complaint)
    return result.structured_output


def _basis(report: Report) -> str:
    """What the classification was actually made from.

    Stated because a note-only report now reaches this stage. Before the evidence
    prompt handled the no-photograph path, such a case always halted at the
    confidence floor, so a complaint could safely assume a photograph existed.
    It no longer can, and a letter that refers to a photograph nobody has is a
    letter an authority can dismiss on the first reply.
    """
    count = len(report.image_paths)
    if count == 0:
        return "no photograph; the citizen's written account of what they observed"
    if count == 1:
        return "one photograph submitted by the citizen, plus their note"
    return f"{count} photographs of the same event submitted by the citizen, plus their note"


def _pattern_block(cluster: Cluster | None, case_id: str) -> str:
    """The repeat-report block, or nothing at all.

    Absent rather than empty when there is no pattern: a block reading "reports:
    1" invites the model to write a sentence about how this has only happened
    once, which is an argument against the complaint.
    """
    if cluster is None:
        return ""
    return f"""
PATTERN OF REPEAT REPORTS
  {describe(cluster, case_id)}
  Cluster reference: {cluster.cluster_id}
  Reports in this pattern: {cluster.report_count}
  First reported: {cluster.first_reported_at.date().isoformat()}
  Most recent report: {cluster.last_reported_at.date().isoformat()}
  Identified reporters: {cluster.distinct_reporters}
  Anonymous submissions: {cluster.anonymous_reports}
  (anonymous reports may be one person or many; the system cannot tell)
  Pattern centre: {cluster.centre_latitude}, {cluster.centre_longitude}
  Greatest distance from that centre: {cluster.radius_km:.3f} km
"""
