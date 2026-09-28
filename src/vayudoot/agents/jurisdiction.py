"""Stage 3: who is actually responsible for this location?"""

from __future__ import annotations

from strands import Agent

from ..models import build_model
from ..schemas import EvidencePacket, Jurisdiction, Report
from ..tools import lookup_authority, reverse_geocode
from .prompts import JURISDICTION


def build_jurisdiction_agent() -> Agent:
    return Agent(
        name="jurisdiction",
        model=build_model(temperature=0.0, tier="fast"),
        system_prompt=JURISDICTION,
        tools=[reverse_geocode, lookup_authority],
        callback_handler=None,
    )


async def resolve_jurisdiction(
    report: Report, evidence: EvidencePacket, agent: Agent | None = None, country: str = ""
) -> Jurisdiction:
    """Resolve the authority for a report.

    `country` is the geocoder's country code when the pipeline already has it.
    Stated in the prompt so the lookup is asked for the right country's table
    even if the model reads the geocoder's answer carelessly; the pipeline then
    checks the answer against the table itself.
    """
    agent = agent or build_jurisdiction_agent()
    hint = f"Country code (from reverse geocoding): {country}\n" if country else ""
    prompt = (
        f"Report location: latitude {report.latitude}, longitude {report.longitude}.\n"
        f"{hint}"
        f"Pollution type: {evidence.pollution_type.value}\n\n"
        "Determine the responsible authority, the statute, and the escalation path."
    )
    result = await agent.invoke_async(prompt, structured_output_model=Jurisdiction)
    return result.structured_output
