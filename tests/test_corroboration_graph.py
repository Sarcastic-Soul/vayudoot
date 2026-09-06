"""The graph result is unwrapped correctly.

A `NodeResult` wraps an `AgentResult` rather than forwarding its attributes, so
reading `structured_output` off the node returns None on every real run and the
synthesis is silently replaced by an empty Corroboration. The unit tests could
not see it, because they replace the whole stage. These pin the unwrapping.
"""

from __future__ import annotations

from types import SimpleNamespace

from fakes import corroboration as sample
from vayudoot.agents.corroboration import _synthesis_output


def _result(node) -> SimpleNamespace:
    return SimpleNamespace(results={"synthesis": node} if node else {})


def test_structured_output_is_read_through_the_agent_result():
    expected = sample()
    node = SimpleNamespace(
        result=SimpleNamespace(structured_output=expected),
        get_agent_results=list,
    )
    assert _synthesis_output(_result(node)) is expected


def test_the_last_agent_result_is_used_when_the_node_carries_none():
    expected = sample()
    node = SimpleNamespace(
        result=SimpleNamespace(structured_output=None),
        get_agent_results=lambda: [
            SimpleNamespace(structured_output=None),
            SimpleNamespace(structured_output=expected),
        ],
    )
    assert _synthesis_output(_result(node)) is expected


def test_a_graph_with_no_synthesis_node_yields_nothing():
    assert _synthesis_output(_result(None)) is None


def test_a_synthesis_that_produced_no_structure_yields_nothing():
    node = SimpleNamespace(
        result=SimpleNamespace(structured_output=None),
        get_agent_results=lambda: [SimpleNamespace(structured_output=None)],
    )
    assert _synthesis_output(_result(node)) is None
