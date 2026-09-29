"""Model selection and the fallback chain.

Both tiers are on Gemini. What can still go wrong silently is which model id a
tier resolves to, and whether a rate-limited or overloaded model hands the call
to the next one in its chain — the wrong model still answers, so these rules
are pinned here.
"""

from __future__ import annotations

import asyncio

import pytest
from google.adk.models import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from google.genai.errors import ClientError, ServerError

from vayudoot import models
from vayudoot.config import DEFAULT_MODEL_IDS, settings


@pytest.fixture
def ids(monkeypatch):
    def configure(model_id="", model_id_fast=""):
        monkeypatch.setattr(settings, "vayudoot_model_id", model_id)
        monkeypatch.setattr(settings, "vayudoot_model_id_fast", model_id_fast)

    configure()
    return configure


@pytest.fixture
def fake_gemini(monkeypatch):
    """Replace the network call with a script: each entry is raised or answered."""
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(models, "_throttled_at", {})
    asked: list[LlmRequest] = []
    script: list[Exception | None] = []

    async def fake_generate(self, llm_request, stream=False):
        asked.append(llm_request)
        outcome = script.pop(0) if script else None
        if outcome is not None:
            raise outcome
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part.from_text(text="ok")])
        )

    monkeypatch.setattr(Gemini, "generate_content_async", fake_generate)
    return asked, script


def _run(model) -> list[LlmResponse]:
    async def collect():
        request = LlmRequest(model=model.model, config=types.GenerateContentConfig())
        return [r async for r in model.generate_content_async(request)]

    return asyncio.run(collect())


def test_each_tier_has_its_own_default_model(ids):
    assert settings.model_id_for("primary") == DEFAULT_MODEL_IDS["primary"]
    assert settings.model_id_for("fast") == DEFAULT_MODEL_IDS["fast"]
    assert DEFAULT_MODEL_IDS["primary"] != DEFAULT_MODEL_IDS["fast"]


def test_an_explicit_model_id_overrides_the_table(ids):
    ids(model_id="a-model", model_id_fast="b-model")
    assert settings.model_id_for("primary") == "a-model"
    assert settings.model_id_for("fast") == "b-model"


def test_the_default_model_heads_a_chain_of_fallbacks(ids):
    """AI Studio meters each model separately, so the chain is the daily allowance."""
    chain = settings.model_chain_for("primary")
    assert chain[0] == DEFAULT_MODEL_IDS["primary"]
    assert len(chain) > 1
    assert all(model.startswith("gemini-") for model in chain)


def test_an_explicit_model_id_has_no_fallbacks(ids):
    ids(model_id="gemini-exact")
    assert settings.model_chain_for("primary") == ["gemini-exact"]


def test_a_rate_limited_model_falls_through_to_the_next(ids, fake_gemini):
    """A 429 before the first response moves to the next model; the caller never sees it."""
    asked, script = fake_gemini
    script.append(ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "q"}}))
    model = models.build_model(tier="primary")

    responses = _run(model)

    chain = settings.model_chain_for("primary")
    assert [r.model for r in asked] == chain[:2]
    assert len(responses) == 1
    assert model.answered_by == chain[1]
    assert chain[0] in models._throttled_at


def test_an_overloaded_model_falls_through_too(ids, fake_gemini):
    """A 503 "high demand" is worth another model as much as a 429 is.

    A live cross-border demo run failed three times on exactly this while the
    chain's other models were idle, because only 429s moved down the chain.
    """
    asked, script = fake_gemini
    script.append(ServerError(503, {"error": {"status": "UNAVAILABLE", "message": "busy"}}))
    model = models.build_model(tier="fast")

    _run(model)

    assert len(asked) == 2
    assert model.answered_by == settings.model_chain_for("fast")[1]


def test_a_bad_request_is_not_retried_on_another_model(ids, fake_gemini):
    asked, script = fake_gemini
    script.append(ClientError(400, {"error": {"status": "INVALID_ARGUMENT", "message": "bad"}}))
    model = models.build_model(tier="primary")

    with pytest.raises(ClientError):
        _run(model)
    assert len(asked) == 1


def test_a_recently_throttled_model_is_skipped_without_asking(ids, fake_gemini):
    asked, _ = fake_gemini
    chain = settings.model_chain_for("primary")
    models._throttled_at[chain[0]] = __import__("time").monotonic()

    _run(models.build_model(tier="primary"))

    assert [r.model for r in asked] == [chain[1]]


def test_the_tier_temperature_reaches_the_request(ids, fake_gemini):
    asked, _ = fake_gemini
    _run(models.build_model(temperature=0.0, tier="fast"))
    assert asked[0].config.temperature == 0.0
