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
        model=build_model(temperature=0.0),
        system_prompt=JURISDICTION,
        tools=[reverse_geocode, lookup_authority],
        callback_handler=None,
    )


async def resolve_jurisdiction(
    report: Report, evidence: EvidencePacket, agent: Agent | None = None
) -> Jurisdiction:
    agent = agent or build_jurisdiction_agent()
    prompt = (
        f"Report location: latitude {report.latitude}, longitude {report.longitude}.\n"
        f"Pollution type: {evidence.pollution_type.value}\n\n"
        "Determine the responsible authority, the statute, and the escalation path."
    )
    result = await agent.invoke_async(prompt, structured_output_model=Jurisdiction)
    return result.structured_output
