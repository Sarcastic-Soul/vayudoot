"""Provider rate limits become one readable sentence, not an SDK error dump.

Every agent calls the provider's structured-output path, and neither SDK wraps
its own rate-limit exception there the way each provider's plain chat path
does: Gemini's is a `ClientError` whose message is the full JSON error body,
Ollama's is a `ResponseError` with only a bare status code. `errors.describe`
is what a citizen actually sees on a failed case, so it has to recognise both
shapes and leave every other exception untouched.
"""

from __future__ import annotations

import pytest
from google.genai.errors import ClientError
from ollama import ResponseError

from vayudoot import errors
from vayudoot.callbudget import OllamaBudgetExceeded
from vayudoot.config import settings


@pytest.fixture
def providers(monkeypatch):
    def configure(primary="gemini", fast=None):
        monkeypatch.setattr(settings, "vayudoot_model_provider", primary)
        monkeypatch.setattr(settings, "vayudoot_model_provider_fast", fast)

    return configure


def _gemini_quota_error() -> ClientError:
    return ClientError(
        429,
        {"error": {"code": 429, "message": "Quota exceeded.", "status": "RESOURCE_EXHAUSTED"}},
    )


def test_gemini_quota_error_becomes_a_plain_sentence(providers):
    providers(primary="gemini")
    message = errors.describe(_gemini_quota_error(), tier="primary")

    assert "free-tier request quota" in message
    assert "Gemini" in message
    # None of the API's own JSON error body leaks into what a citizen reads.
    assert "RESOURCE_EXHAUSTED" not in message
    assert "{" not in message


def test_gemini_error_names_the_tier_that_failed(providers):
    providers(primary="ollama", fast="gemini")
    message = errors.describe(_gemini_quota_error(), tier="fast")

    assert "corroborating evidence" in message


def test_ollama_quota_error_becomes_a_plain_sentence(providers):
    providers(primary="ollama")
    message = errors.describe(ResponseError("rate limit exceeded", status_code=429), tier="primary")

    assert "free-tier quota" in message
    assert "Ollama Cloud" in message


def test_a_non_rate_limit_error_from_the_configured_provider_is_untouched(providers):
    providers(primary="gemini")
    body = {"error": {"code": 400, "message": "bad request", "status": "INVALID_ARGUMENT"}}
    exc = ClientError(400, body)

    assert errors.describe(exc, tier="primary") == f"{type(exc).__name__}: {exc}"
    assert not errors.is_rate_limit(exc, tier="primary")


def test_an_unrelated_exception_keeps_the_original_format(providers):
    providers(primary="gemini")
    exc = RuntimeError("evidence exploded")

    assert errors.describe(exc, tier="primary") == "RuntimeError: evidence exploded"


def test_a_rate_limit_from_the_wrong_provider_is_not_matched(providers):
    """The tier's *configured* provider decides, not whichever SDK raised."""
    providers(primary="ollama")

    assert not errors.is_rate_limit(_gemini_quota_error(), tier="primary")


def test_a_wrapped_exception_is_still_recognised(providers):
    """A Strands graph node can wrap the provider's exception rather than
    let it propagate directly; the check has to walk the `__cause__` chain."""
    providers(primary="gemini")
    wrapper = RuntimeError("graph node failed")
    wrapper.__cause__ = _gemini_quota_error()

    assert errors.is_rate_limit(wrapper, tier="primary")


def test_flash_lite_names_its_own_published_limits(providers):
    """The fast tier's default model has confirmed numbers; the message should
    use them rather than the generic per-minute-or-per-day guess."""
    providers(primary="ollama", fast="gemini")
    message = errors.describe(_gemini_quota_error(), tier="fast")

    assert "15 requests/minute" in message
    assert "250,000 tokens/minute" in message
    assert "500 requests/day" in message


def test_a_retry_delay_from_the_api_is_used_when_present(providers):
    providers(primary="gemini")
    body = {
        "error": {
            "code": 429,
            "message": "Quota exceeded.",
            "status": "RESOURCE_EXHAUSTED",
            "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "17s"}],
        }
    }
    message = errors.describe(ClientError(429, body), tier="primary")

    assert "Retry in about 17 seconds" in message


def test_ollama_budget_trip_is_recognised_and_passed_through_unchanged(providers):
    """`callbudget.py` already writes the full sentence; `describe` must not
    template over it, only recognise it as a rate limit."""
    providers(primary="ollama")
    exc = OllamaBudgetExceeded("this deployment's own safety cap tripped")

    assert errors.is_rate_limit(exc, tier="primary")
    assert errors.describe(exc, tier="primary") == str(exc)
