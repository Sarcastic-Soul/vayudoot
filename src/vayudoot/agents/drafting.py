"""Stage 4: write the complaint."""

from __future__ import annotations

from strands import Agent

from ..models import build_model
from ..schemas import Complaint, Corroboration, EvidencePacket, Jurisdiction, Report
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
    agent: Agent | None = None,
) -> Complaint:
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
  Visible indicators: {', '.join(evidence.visible_indicators) or 'none recorded'}
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

Write the complaint body citing only the statute and section given above."""

    result = await agent.invoke_async(prompt, structured_output_model=Complaint)
    return result.structured_output
