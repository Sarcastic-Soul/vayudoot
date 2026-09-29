"""The synthesis answer is read out of session state correctly, and the graph is shaped right.

ADK writes an agent's answer into session state under its `output_key`: a dict
when the agent has an output schema, raw text otherwise. The unit tests of the
pipeline cannot see a mistake here, because they replace the whole stage, so
these pin the unwrapping and the fan-out.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from google.adk.models import Gemini
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from fakes import corroboration as sample
from fakes import evidence
from vayudoot.agents.corroboration import _synthesis_instruction, _synthesis_output, corroborate
from vayudoot.agents.prompts import SYNTHESIS
from vayudoot.schemas import Report


def test_a_dict_answer_is_validated():
    expected = sample()
    assert _synthesis_output({"synthesis": expected.model_dump(mode="json")}) == expected


def test_a_text_answer_is_parsed():
    expected = sample()
    assert _synthesis_output({"synthesis": expected.model_dump_json()}) == expected


def test_no_synthesis_in_state_yields_nothing():
    assert _synthesis_output({}) is None


def test_an_unparseable_synthesis_yields_nothing():
    assert _synthesis_output({"synthesis": "not json"}) is None


async def test_the_three_sources_run_in_parallel_and_synthesis_runs_once_after(monkeypatch):
    """The fan-out is the point of the graph: three sources at once, then one join.

    Each model call is held for a moment. If the sources ran one after another,
    their start times would be spread by that delay; if synthesis ran per source
    rather than after the join, it would be called three times.
    """
    started: list[tuple[float, str]] = []
    clock = asyncio.get_running_loop().time
    answer = sample().model_dump_json()

    async def fake_generate(self, llm_request, stream=False):
        prompt = str(llm_request.config.system_instruction)
        started.append((clock(), prompt))
        await asyncio.sleep(0.2)
        text = answer if prompt.startswith(SYNTHESIS[:40]) else "A summary."
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))

    monkeypatch.setattr(Gemini, "generate_content_async", fake_generate)
    report = Report(report_id="r", latitude=28.6, longitude=77.2)

    result = await corroborate(report, evidence())

    assert result == sample()
    sources = [t for t, prompt in started if not prompt.startswith(SYNTHESIS[:40])]
    synthesis = [t for t, prompt in started if prompt.startswith(SYNTHESIS[:40])]
    assert len(sources) == 3
    assert max(sources) - min(sources) < 0.1
    assert len(synthesis) == 1
    assert synthesis[0] >= max(sources) + 0.2


def test_synthesis_sees_the_task_and_every_summary_even_a_missing_one():
    """A source that wrote nothing is named as such, so synthesis cannot mistake
    a missing summary for a negative reading it never received."""
    ctx = SimpleNamespace(
        state={"task": "Report at 28.6, 77.2", "satellite": "Two detections 3 km north."}
    )
    text = _synthesis_instruction(ctx)
    assert "Report at 28.6, 77.2" in text
    assert "Two detections 3 km north." in text
    assert text.count("(this source returned nothing)") == 2
