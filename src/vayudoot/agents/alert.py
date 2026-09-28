"""The situation summary at the top of a hotspot alert.

A small job on purpose. Everything an officer could check — where, how big, how
sure, from which instruments — is in the alert's facts block, which
`alerts.facts_block` builds in Python so that it says the same thing every time
and cannot be embellished. The model is given that block and writes only the
prose above it: a subject line, a few sentences, the same in the region's main
language, and a short list of checks an inspector could make.

Fast tier. It reads a block of text it was handed and summarises it, calling no
tool — the work flash-lite is for. The two primary-tier stages in a report run
read a photograph and draft a legal document; this does neither. Constraint 5.

The prompt carries hard constraint 7 into the prose: an area, never an address;
conditions, never accusations; no responsible party named or implied.
"""

from __future__ import annotations

from strands import Agent

from ..models import build_model
from ..schemas import AlertBrief, Jurisdiction
from .prompts import ALERT, local_language_line


def build_alert_agent() -> Agent:
    return Agent(
        name="alert",
        model=build_model(temperature=0.2, tier="fast"),
        system_prompt=ALERT,
        callback_handler=None,
    )


async def write_alert_brief(
    facts: str,
    jurisdiction: Jurisdiction,
    region: str,
    country: str = "",
    agent: Agent | None = None,
) -> AlertBrief:
    """Summarise a facts block for the authority it is addressed to.

    `region` is the state or province. Where the authority table names the
    region's language — South Africa's provinces, where no model should have to
    choose among the official languages, and Brazil, where it is always
    Portuguese — that language is passed on and the model is told to use it.
    Where the table leaves it out, as India's does, the model is told the region
    and names its language itself, the same way the complaint drafter is.
    """
    agent = agent or build_alert_agent()
    language = local_language_line(jurisdiction.local_language)
    prompt = f"""Write the situation summary for this alert.

ADDRESSED TO
  {jurisdiction.authority_name} ({jurisdiction.authority_tier})
  Region: {region or "unknown"}
  Country: {country or jurisdiction.country or "unknown"}{language}

FACTS
{facts}
"""
    result = await agent.invoke_async(prompt, structured_output_model=AlertBrief)
    return result.structured_output
