"""Stage 2: independent corroboration, as an ADK workflow graph.

Three evidence sources are genuinely independent of one another, so they fan out
in parallel and a synthesis agent joins them. This is where a multi-agent shape
earns its place rather than decorating a pipeline that is really a straight line.

    satellite ──┐
    ground   ───┼──> synthesis
    weather  ──┘

In ADK terms it is a `Workflow` graph: the three source agents fan out from the
start node and run at once, each writing its summary into session state under
its own name; a `JoinNode` waits for all three; then the synthesis agent runs
once. (ADK 2 deprecates `ParallelAgent` and `SequentialAgent` in favour of
`Workflow`.) Synthesis reads the task and the three summaries from state rather
than from the conversation, so what it is given is exactly what the source
agents wrote and nothing else.
"""

from __future__ import annotations

import asyncio
from typing import Any

from google.adk.workflow import START, JoinNode, Workflow

from ..models import Agent, build_model, run_once
from ..schemas import Corroboration, EvidencePacket, Report
from ..tools import find_satellite_fire_detections, get_nearby_air_quality, get_wind_conditions
from .prompts import GROUND_STATION, METEOROLOGY, SATELLITE, SYNTHESIS

#: The source agents, in the order their summaries are shown to synthesis.
SOURCES = ("satellite", "ground_station", "meteorology")

#: How long the whole fan-out and synthesis may take. A source whose API hangs
#: should cost the report its corroboration, not stall the case indefinitely.
TIMEOUT_SECONDS = 180


def build_corroboration_graph() -> Workflow:
    satellite = Agent(
        name="satellite",
        model=build_model(temperature=0.0, tier="fast"),
        system_prompt=SATELLITE,
        tools=[find_satellite_fire_detections],
    )
    ground = Agent(
        name="ground_station",
        model=build_model(temperature=0.0, tier="fast"),
        system_prompt=GROUND_STATION,
        tools=[get_nearby_air_quality],
    )
    weather = Agent(
        name="meteorology",
        model=build_model(temperature=0.0, tier="fast"),
        system_prompt=METEOROLOGY,
        tools=[get_wind_conditions],
    )
    # Synthesis is on the fast tier too. It merges three summaries that the source
    # agents already wrote; it reads no image and calls no tool. On the Gemini free
    # tier the primary model allows 20 requests a day against the fast model's 500,
    # so every avoidable primary call costs a whole report.
    synthesis = Agent(
        name="synthesis",
        model=build_model(temperature=0.0, tier="fast"),
        system_prompt=SYNTHESIS,
    )

    sources = tuple(a.llm_agent(output_key=a.name) for a in (satellite, ground, weather))
    return Workflow(
        name="corroboration",
        edges=[
            (
                START,
                sources,
                # Waits for all three sources, so synthesis runs once, not per source.
                JoinNode(name="sources_done"),
                synthesis.llm_agent(
                    output_schema=Corroboration,
                    output_key="synthesis",
                    instruction=_synthesis_instruction,
                    include_contents="none",
                ),
            )
        ],
    )


def _synthesis_instruction(ctx: Any) -> str:
    """The synthesis prompt, followed by the task and each source's summary."""
    blocks = [SYNTHESIS, "THE REPORT", str(ctx.state.get("task", ""))]
    for name in SOURCES:
        summary = ctx.state.get(name) or "(this source returned nothing)"
        blocks += [f"{name.upper().replace('_', ' ')} ANALYSIS", str(summary)]
    return "\n\n".join(blocks)


async def corroborate(
    report: Report, evidence: EvidencePacket, graph=None
) -> Corroboration:
    graph = graph or build_corroboration_graph()

    task = (
        f"Report location: latitude {report.latitude}, longitude {report.longitude}.\n"
        f"Observed at: {report.observed_at.isoformat()}\n"
        f"Reported pollution type: {evidence.pollution_type.value}\n"
        f"Reported severity: {evidence.severity}\n"
        f"Visible indicators: {', '.join(evidence.visible_indicators) or 'none recorded'}\n\n"
        "Gather independent evidence for this report using your tool."
    )

    try:
        state = await asyncio.wait_for(
            run_once(graph, task, state={"task": task}), timeout=TIMEOUT_SECONDS
        )
    except TimeoutError:
        return Corroboration(
            corroborated=False,
            corroboration_notes=(
                f"Corroboration did not finish within {TIMEOUT_SECONDS} seconds, so no "
                "independent evidence was weighed."
            ),
        )
    structured = _synthesis_output(state)

    if structured is None:
        return Corroboration(
            corroborated=False,
            corroboration_notes="Corroboration graph returned no structured synthesis.",
        )
    return structured


def _synthesis_output(state: dict[str, Any]) -> Corroboration | None:
    """The synthesis agent's answer, read from the session state it was written to.

    ADK stores an agent's validated output under its `output_key`, as a dict
    when the agent has an output schema and as the raw text otherwise, so both
    are accepted. Anything missing or unparseable yields None, and the caller
    records that no synthesis came back rather than inventing one.
    """
    answer = state.get("synthesis")
    if not answer:
        return None
    try:
        if isinstance(answer, str):
            return Corroboration.model_validate_json(answer)
        return Corroboration.model_validate(answer)
    except ValueError:
        return None
