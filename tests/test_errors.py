"""Gemini rate limits become one readable sentence, not an SDK error dump.

A 429 arrives as a `ClientError` whose message is the full JSON error body, and
ADK re-raises it as a subclass with a paragraph of developer advice on top.
`errors.describe` is what a citizen actually sees on a failed case, so it has to
recognise both and leave every other exception untouched.
"""

from __future__ import annotations

import pytest
from google.genai.errors import ClientError

from vayudoot import errors
from vayudoot.config import settings


@pytest.fixture(autouse=True)
def default_models(monkeypatch):
    monkeypatch.setattr(settings, "vayudoot_model_id", "")
    monkeypatch.setattr(settings, "vayudoot_model_id_fast", "")


def _gemini_quota_error() -> ClientError:
    return ClientError(
        429,
        {"error": {"code": 429, "message": "Quota exceeded.", "status": "RESOURCE_EXHAUSTED"}},
    )


def test_gemini_quota_error_becomes_a_plain_sentence():
    message = errors.describe(_gemini_quota_error(), tier="primary")

    assert "free-tier request quota" in message
    assert "Gemini" in message
    # None of the API's own JSON error body leaks into what a citizen reads.
    assert "RESOURCE_EXHAUSTED" not in message
    assert "{" not in message


def test_gemini_error_names_the_tier_that_failed():
    message = errors.describe(_gemini_quota_error(), tier="fast")

    assert "corroborating evidence" in message



def test_a_non_rate_limit_error_from_the_is_untouched():
    body = {"error": {"code": 400, "message": "bad request", "status": "INVALID_ARGUMENT"}}
    exc = ClientError(400, body)

    assert errors.describe(exc, tier="primary") == f"{type(exc).__name__}: {exc}"
    assert not errors.is_rate_limit(exc, tier="primary")


def test_an_unrelated_exception_keeps_the_original_format():
    exc = RuntimeError("evidence exploded")

    assert errors.describe(exc, tier="primary") == "RuntimeError: evidence exploded"



def test_a_wrapped_exception_is_still_recognised():
    """A stage can wrap the SDK's exception in its own rather than let it
    propagate directly; the check has to walk the `__cause__` chain."""
    wrapper = RuntimeError("graph node failed")
    wrapper.__cause__ = _gemini_quota_error()

    assert errors.is_rate_limit(wrapper, tier="primary")


def test_flash_lite_names_its_own_published_limits():
    """The fast tier's default model has confirmed numbers; the message should
    use them rather than the generic per-minute-or-per-day guess."""
    message = errors.describe(_gemini_quota_error(), tier="fast")

    assert "15 requests/minute" in message
    assert "250,000 tokens/minute" in message
    assert "500 requests/day" in message


def test_a_retry_delay_from_the_api_is_used_when_present():
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



def test_a_spent_daily_quota_says_so_instead_of_suggesting_a_retry():
    """A daily 429 still carries a RetryInfo of seconds; following it wastes a request."""
    body = {
        "error": {
            "code": 429,
            "message": "Quota exceeded for metric generate_content_free_tier_requests.",
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [
                        {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}
                    ],
                },
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "17s"},
            ],
        }
    }
    message = errors.describe(ClientError(429, body), tier="primary")

    assert errors.DAILY_QUOTA_SPENT in message
    assert "Retry in about" not in message


def test_a_per_minute_quota_is_not_mistaken_for_the_daily_one():
    assert not errors.is_daily_quota(_gemini_quota_error())


def test_adk_s_own_resource_exhausted_wrapper_is_recognised():
    """ADK re-raises a 429 as `_ResourceExhaustedError`, whose text starts with
    developer advice. It must still become the plain sentence."""
    from google.adk.models.google_llm import _ResourceExhaustedError

    exc = _ResourceExhaustedError(_gemini_quota_error())
    message = errors.describe(exc, tier="primary")

    assert errors.is_rate_limit(exc, tier="primary")
    assert "free-tier request quota" in message
