"""Provider and model selection.

The two tiers may sit on different providers, which is how the running cost is
spread across two free tiers. Getting this wrong is silent — the wrong provider
still answers — so the resolution rules are pinned here.
"""

from __future__ import annotations

import pytest

from vayudoot.config import DEFAULT_MODEL_IDS, settings


@pytest.fixture
def providers(monkeypatch):
    def configure(primary="gemini", fast=None, model_id="", model_id_fast=""):
        monkeypatch.setattr(settings, "vayudoot_model_provider", primary)
        monkeypatch.setattr(settings, "vayudoot_model_provider_fast", fast)
        monkeypatch.setattr(settings, "vayudoot_model_id", model_id)
        monkeypatch.setattr(settings, "vayudoot_model_id_fast", model_id_fast)

    return configure


def test_one_provider_serves_both_tiers_when_no_split_is_configured(providers):
    providers(primary="ollama")
    assert settings.provider_for("primary") == "ollama"
    assert settings.provider_for("fast") == "ollama"


def test_the_fast_tier_can_sit_on_another_provider(providers):
    providers(primary="ollama", fast="gemini")
    assert settings.provider_for("primary") == "ollama"
    assert settings.provider_for("fast") == "gemini"


def test_model_ids_follow_the_tier_provider_not_the_primary_one(providers):
    """The bug this guards: reading fast ids out of the primary provider's table."""
    providers(primary="ollama", fast="gemini")
    assert settings.model_id_for("primary") == DEFAULT_MODEL_IDS["ollama"]["primary"]
    assert settings.model_id_for("fast") == DEFAULT_MODEL_IDS["gemini"]["fast"]


def test_an_explicit_model_id_overrides_the_table(providers):
    providers(primary="ollama", fast="gemini", model_id="a-model", model_id_fast="b-model")
    assert settings.model_id_for("primary") == "a-model"
    assert settings.model_id_for("fast") == "b-model"


def test_every_provider_has_both_tiers_in_the_table():
    for provider, tiers in DEFAULT_MODEL_IDS.items():
        assert set(tiers) == {"primary", "fast"}, provider


def test_the_default_gemini_model_heads_a_chain_of_fallbacks(providers):
    """AI Studio meters each model separately, so the chain is the daily allowance."""
    providers(primary="gemini")
    chain = settings.model_chain_for("primary")
    assert chain[0] == DEFAULT_MODEL_IDS["gemini"]["primary"]
    assert len(chain) > 1
    assert all(model.startswith("gemini-") for model in chain)


def test_an_explicit_model_id_has_no_fallbacks(providers):
    providers(primary="gemini", model_id="gemini-exact")
    assert settings.model_chain_for("primary") == ["gemini-exact"]


def test_a_rate_limited_model_falls_through_to_the_next(providers, monkeypatch):
    """A 429 before the first chunk moves to the next model; the caller never sees it."""
    import asyncio

    from strands.models.gemini import GeminiModel
    from strands.types.exceptions import ModelThrottledException

    from vayudoot import models

    providers(primary="gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(models, "_throttled_at", {})
    asked: list[str] = []

    async def fake_stream(self, *args, **kwargs):
        asked.append(self.config["model_id"])
        if len(asked) == 1:
            raise ModelThrottledException("429")
        yield {"answered_by": self.config["model_id"]}

    monkeypatch.setattr(GeminiModel, "stream", fake_stream)
    model = models.build_model(tier="primary")

    async def collect():
        return [event async for event in model.stream([])]

    events = asyncio.run(collect())
    chain = settings.model_chain_for("primary")
    assert asked == chain[:2]
    assert events == [{"answered_by": chain[1]}]
    assert chain[0] in models._throttled_at


def test_an_overloaded_model_falls_through_too(providers, monkeypatch):
    """A 503 "high demand" arrives as the SDK's ServerError, not Strands' throttle.

    A live cross-border demo run failed three times on exactly this while the
    chain's other models were idle, because only 429s moved down the chain.
    """
    import asyncio

    from google.genai.errors import ServerError
    from strands.models.gemini import GeminiModel

    from vayudoot import models

    providers(primary="gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(models, "_throttled_at", {})
    asked: list[str] = []

    async def fake_stream(self, *args, **kwargs):
        asked.append(self.config["model_id"])
        if len(asked) == 1:
            raise ServerError(503, {"error": {"status": "UNAVAILABLE", "message": "busy"}})
        yield {"answered_by": self.config["model_id"]}

    monkeypatch.setattr(GeminiModel, "stream", fake_stream)
    model = models.build_model(tier="fast")

    async def collect():
        return [event async for event in model.stream([])]

    events = asyncio.run(collect())
    assert len(asked) == 2
    assert events == [{"answered_by": settings.model_chain_for("fast")[1]}]


def test_a_bad_request_is_not_retried_on_another_model(providers, monkeypatch):
    import asyncio

    import pytest as _pytest
    from google.genai.errors import ClientError
    from strands.models.gemini import GeminiModel

    from vayudoot import models

    providers(primary="gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(models, "_throttled_at", {})
    asked: list[str] = []

    async def fake_stream(self, *args, **kwargs):
        asked.append(self.config["model_id"])
        raise ClientError(400, {"error": {"status": "INVALID_ARGUMENT", "message": "bad"}})
        yield  # pragma: no cover

    monkeypatch.setattr(GeminiModel, "stream", fake_stream)
    model = models.build_model(tier="primary")

    async def collect():
        return [event async for event in model.stream([])]

    with _pytest.raises(ClientError):
        asyncio.run(collect())
    assert len(asked) == 1
