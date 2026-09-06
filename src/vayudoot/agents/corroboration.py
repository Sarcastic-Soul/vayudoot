"""Stage 2: independent corroboration, as a Strands agent graph.

Three evidence sources are genuinely independent of one another, so they fan out
in parallel and a synthesis node joins them. This is where a graph earns its
place rather than decorating a pipeline that is really a straight line.

    satellite ──┐
    ground   ───┼──> synthesis
    weather  ──┘
"""

from __future__ import annotations

from strands import Agent
from strands.multiagent import GraphBuilder

from ..models import build_model
from ..schemas import Corroboration, EvidencePacket, Report
from ..tools import find_satellite_fire_detections, get_nearby_air_quality, get_wind_conditions
from .prompts import GROUND_STATION, METEOROLOGY, SATELLITE, SYNTHESIS


def build_corroboration_graph():
    satellite = Agent(
        name="satellite",
        model=build_model(temperature=0.0, tier="fast"),
        system_prompt=SATELLITE,
        tools=[find_satellite_fire_detections],
        callback_handler=None,
    )
    ground = Agent(
        name="ground_station",
        model=build_model(temperature=0.0, tier="fast"),
        system_prompt=GROUND_STATION,
        tools=[get_nearby_air_quality],
        callback_handler=None,
    )
    weather = Agent(
        name="meteorology",
        model=build_model(temperature=0.0, tier="fast"),
        system_prompt=METEOROLOGY,
        tools=[get_wind_conditions],
        callback_handler=None,
    )
    # Synthesis is on the fast tier too. It merges three summaries that the source
    # agents already wrote; it reads no image and calls no tool. On the Gemini free
    # tier the primary model allows 20 requests a day against the fast model's 500,
    # so every avoidable primary call costs a whole report.
    synthesis = Agent(
        name="synthesis",
        model=build_model(temperature=0.0, tier="fast"),
        system_prompt=SYNTHESIS,
        callback_handler=None,
        structured_output_model=Corroboration,
    )

    builder = GraphBuilder()
    builder.add_node(satellite, "satellite")
    builder.add_node(ground, "ground_station")
    builder.add_node(weather, "meteorology")
    builder.add_node(synthesis, "synthesis")

    for source in ("satellite", "ground_station", "meteorology"):
        builder.set_entry_point(source)
        builder.add_edge(source, "synthesis")

    builder.set_execution_timeout(180)
    return builder.build()


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

    result = await graph.invoke_async(task)
    structured = _synthesis_output(result)

    if structured is None:
        return Corroboration(
            corroborated=False,
            corroboration_notes="Corroboration graph returned no structured synthesis.",
        )
    return structured


def _synthesis_output(result) -> Corroboration | None:
    """Dig the synthesis node's structured output out of the graph result.

    A graph hands back a `NodeResult`, which wraps the `AgentResult` rather than
    forwarding its attributes. Reading `structured_output` off the node itself
    silently yields None on every run, so this reaches through to the agent
    result, and falls back to the node's agent results for a multi-turn node.
    """
    node = result.results.get("synthesis")
    if node is None:
        return None

    structured = getattr(node.result, "structured_output", None)
    if structured is not None:
        return structured

    for agent_result in reversed(node.get_agent_results()):
        structured = getattr(agent_result, "structured_output", None)
        if structured is not None:
            return structured
    return None
