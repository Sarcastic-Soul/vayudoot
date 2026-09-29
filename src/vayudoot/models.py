"""Model factory and the one agent shape every stage uses.

Every model call in this project goes to Gemini through Google's Agent
Development Kit (ADK). No module constructs a model directly: they all call
`build_model()`, which is where the API key, the tier's model id and the
fallback chain are decided.

`Agent` is a thin wrapper around ADK's `LlmAgent` and `InMemoryRunner`. ADK is
built for long conversations held in sessions; every stage here is one
question with one typed answer, so the wrapper opens a fresh in-memory session
per call, runs it, and hands back the parsed schema. That keeps each stage's
code to "build an agent, ask it, read `structured_output`", and keeps ADK's
runner, session and event types in this one module.
"""

from __future__ import annotations

import copy
import time
import uuid
import warnings
from collections.abc import AsyncGenerator, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.models import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types
from google.genai.errors import APIError
from pydantic import BaseModel, Field, PrivateAttr

from .config import Tier, settings

# ADK flags the JSON-schema function declarations it builds for tools and for
# structured output as experimental, once per request. The feature is what
# every stage here relies on, and the warning says nothing a log reader can act
# on, so it is silenced once rather than repeated on every call.
warnings.filterwarnings(
    "ignore", message=r"\[EXPERIMENTAL\] feature FeatureName\.JSON_SCHEMA_FOR_FUNC_DECL"
)

#: When each model last failed in a way that belongs to the model, so the next
#: call skips straight past it rather than spending a request to be told again.
#: Process-wide on purpose: the quota is per key and model, not per agent.
_throttled_at: dict[str, float] = {}

#: How long a rate-limited model is skipped. A per-minute limit clears inside
#: this; a per-day one costs one quick rejected request per interval, which is
#: cheaper than tracking the day boundary AI Studio resets on.
THROTTLE_COOLDOWN_SECONDS = 60.0


def _worth_another_model(exc: Exception) -> bool:
    """Whether a failure belongs to this model rather than to the request.

    Three kinds do, and each is worth moving down the chain for: a 429 (this
    model's quota is spent), a 503 (this model is overloaded — AI Studio's free
    tier answers "high demand" for hours at a time on a popular model while its
    siblings are idle), and a 404 (this model id was retired). ADK re-raises a
    429 as its own `ClientError` subclass, which is still an `APIError`.
    Anything else — a bad request, a schema the model cannot follow — would fail
    the same way on every model, so it is raised at once.
    """
    if isinstance(exc, APIError):
        return exc.code in (404, 429, 500, 503) or exc.status in (
            "RESOURCE_EXHAUSTED", "UNAVAILABLE", "NOT_FOUND",
        )
    return False


class FallbackGemini(Gemini):
    """An ADK `Gemini` model that moves down its chain when a model cannot answer.

    Only a failure before the first response falls through. Once a model has
    started answering, a failure is re-raised, because splicing two models'
    halves of one response would be worse than failing.

    `temperature` lives here rather than on each agent so that `build_model()`
    stays the one place a call's settings are decided; it fills in the request
    only when the agent did not set one.
    """

    chain: list[str] = Field(default_factory=list)
    temperature: float | None = None
    _answered_by: str = PrivateAttr(default="")

    @property
    def answered_by(self) -> str:
        """The model id that produced the last answer, or the configured one before any."""
        return self._answered_by or self.model

    def _candidates(self) -> list[str]:
        chain = self.chain or [self.model]
        now = time.monotonic()
        fresh = [
            m for m in chain if now - _throttled_at.get(m, -1e9) > THROTTLE_COOLDOWN_SECONDS
        ]
        # Everything cooling down: try them all anyway rather than fail without asking.
        return fresh or list(chain)

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        last: Exception | None = None
        for model_id in self._candidates():
            # The parent mutates the request (appends content, sets headers), so
            # each attempt gets its own copy of the one the flow built.
            attempt = copy.deepcopy(llm_request)
            attempt.model = model_id
            if self.temperature is not None:
                attempt.config = attempt.config or types.GenerateContentConfig()
                if attempt.config.temperature is None:
                    attempt.config.temperature = self.temperature
            started = False
            try:
                async for response in super().generate_content_async(attempt, stream=stream):
                    started = True
                    self._answered_by = model_id
                    yield response
                return
            except Exception as exc:
                if started or not _worth_another_model(exc):
                    raise
                _throttled_at[model_id] = time.monotonic()
                last = exc
        assert last is not None
        raise last


def build_model(temperature: float | None = None, tier: Tier = "primary") -> FallbackGemini:
    """Return the Gemini model for `tier`.

    `tier` picks between the primary model, used where judgement matters, and the
    fast model, used by agents that only call a tool and summarise the result.
    The model walks `settings.model_chain_for(tier)` when one is rate limited,
    overloaded or retired; see `MODEL_FALLBACKS` in `config.py` for why.
    """
    temp = settings.vayudoot_model_temperature if temperature is None else temperature
    return FallbackGemini(
        model=settings.model_id_for(tier),
        chain=settings.model_chain_for(tier),
        temperature=temp,
        # Keyword arguments rather than a shared `genai.Client`: ADK builds one
        # client per event loop from these, and the test suite runs many loops.
        client_kwargs={"api_key": settings.gemini_api_key},
    )


#: What a stage passes as its question: plain text, or text and media parts.
Content = str | Sequence[types.Part]


def text_part(text: str) -> types.Part:
    return types.Part.from_text(text=text)


def media_part(data: bytes, mime_type: str) -> types.Part:
    """An image or audio part. Gemini reads both as inline data."""
    return types.Part.from_bytes(data=data, mime_type=mime_type)


@dataclass
class AgentResult:
    """What one call hands back: the parsed schema when one was asked for, and the text."""

    structured_output: Any
    text: str


class Agent:
    """One Gemini agent: a system prompt, a model, and optionally some tools.

    Tools are plain functions with a docstring and typed arguments; ADK reads
    both to describe the tool to the model, so there is no decorator.
    """

    def __init__(
        self,
        *,
        name: str,
        model: FallbackGemini,
        system_prompt: str,
        tools: Sequence[Callable[..., Any]] = (),
    ) -> None:
        self.name = name
        self.model = model
        self.system_prompt = system_prompt
        self.tools = list(tools)

    def llm_agent(
        self,
        output_schema: type[BaseModel] | None = None,
        output_key: str | None = None,
        instruction: Callable[[Any], str] | None = None,
        include_contents: str = "default",
    ) -> LlmAgent:
        """The ADK agent behind this one, for composing into ADK workflow agents.

        The instruction is always passed as a function. ADK treats a string
        instruction as a template and fills `{name}` from session state, which
        would break any prompt that contains a brace; a function's return value
        is used as written.
        """
        prompt = self.system_prompt
        return LlmAgent(
            name=self.name,
            model=self.model,
            instruction=instruction or (lambda _ctx: prompt),
            tools=self.tools,
            output_schema=output_schema,
            output_key=output_key,
            include_contents=include_contents,
        )

    async def invoke_async(
        self, content: Content, structured_output_model: type[BaseModel] | None = None
    ) -> AgentResult:
        agent = self.llm_agent(output_schema=structured_output_model, output_key="answer")
        state = await run_once(agent, content)
        answer = state.get("answer")
        text = answer if isinstance(answer, str) else ""
        structured = None
        if structured_output_model is not None and answer is not None:
            structured = (
                structured_output_model.model_validate_json(answer)
                if isinstance(answer, str)
                else structured_output_model.model_validate(answer)
            )
        return AgentResult(structured_output=structured, text=text)


async def run_once(
    agent: Any, content: Content, state: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Run an ADK agent or workflow once in a fresh in-memory session; return its final state.

    Every stage's answer is read from state (each agent writes its answer under
    its `output_key`) rather than from the event stream, so a workflow agent's
    several answers are all there when it finishes.
    """
    # An `LlmAgent` goes in as an agent; a `Workflow` graph is a node.
    target = {"agent": agent} if isinstance(agent, BaseAgent) else {"node": agent}
    runner = InMemoryRunner(app_name="vayudoot", **target)
    session = await runner.session_service.create_session(
        app_name="vayudoot", user_id="vayudoot", session_id=uuid.uuid4().hex, state=state or {}
    )
    parts = [text_part(content)] if isinstance(content, str) else list(content)
    message = types.Content(role="user", parts=parts)
    async for _event in runner.run_async(
        user_id="vayudoot", session_id=session.id, new_message=message
    ):
        pass
    final = await runner.session_service.get_session(
        app_name="vayudoot", user_id="vayudoot", session_id=session.id
    )
    return dict(final.state) if final else {}
