"""The Ollama Cloud safety cap: two rolling windows, no real quota to check
against, so this only has to prove the windows themselves behave.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from vayudoot.callbudget import OllamaBudgetExceeded, OllamaCallBudget
from vayudoot.config import settings
from vayudoot.models import build_model


class Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def budget(monkeypatch):
    monkeypatch.setattr(settings, "vayudoot_ollama_session_call_limit", 3)
    monkeypatch.setattr(settings, "vayudoot_ollama_session_window_hours", 4)
    monkeypatch.setattr(settings, "vayudoot_ollama_weekly_call_limit", 5)
    monkeypatch.setattr(settings, "vayudoot_ollama_weekly_window_days", 5)
    clock = Clock(datetime(2026, 1, 1, tzinfo=UTC))
    return OllamaCallBudget(now=clock), clock


def test_calls_under_the_cap_are_allowed(budget):
    limiter, _ = budget
    for _ in range(3):
        assert limiter.check().allowed


def test_the_session_cap_blocks_the_next_call(budget):
    limiter, _ = budget
    for _ in range(3):
        limiter.check()
    decision = limiter.check()

    assert not decision.allowed
    assert "safety cap" in decision.message
    assert "Ollama" in decision.message


def test_a_session_that_rolls_over_frees_the_budget(budget):
    limiter, clock = budget
    for _ in range(3):
        limiter.check()
    clock.now += timedelta(hours=4, minutes=1)

    assert limiter.check().allowed


def test_the_weekly_cap_blocks_even_across_session_rollovers(budget):
    """Session cap 3, weekly cap 5: three calls, a session rollover, then two
    more calls reach the weekly cap even though the session is fresh again."""
    limiter, clock = budget
    for _ in range(3):
        assert limiter.check().allowed  # weekly count: 3

    clock.now += timedelta(hours=4, minutes=1)  # session window rolls over
    assert limiter.check().allowed  # weekly count: 4, session count: 1
    assert limiter.check().allowed  # weekly count: 5, session count: 2

    decision = limiter.check()  # weekly count already at the cap of 5
    assert not decision.allowed
    assert "weekly" in decision.message.lower()


def test_build_model_raises_the_budget_error_for_ollama_cloud(monkeypatch, budget):
    limiter, _ = budget
    monkeypatch.setattr("vayudoot.models.ollama_budget", limiter)
    monkeypatch.setattr(settings, "vayudoot_model_provider", "ollama")
    monkeypatch.setattr(settings, "ollama_host", "https://ollama.com")
    for _ in range(3):
        build_model()

    with pytest.raises(OllamaBudgetExceeded):
        build_model()


def test_a_local_ollama_daemon_is_not_throttled(monkeypatch, budget):
    limiter, _ = budget
    monkeypatch.setattr("vayudoot.models.ollama_budget", limiter)
    monkeypatch.setattr(settings, "vayudoot_model_provider", "ollama")
    monkeypatch.setattr(settings, "ollama_host", "http://localhost:11434")

    for _ in range(5):
        build_model()  # would trip the session cap of 3 if the guard applied here
