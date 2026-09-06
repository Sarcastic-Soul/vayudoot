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
