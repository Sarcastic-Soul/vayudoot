"""Turn a model provider's rate-limit error into one sentence a citizen can read.

Every agent in this project asks for structured output (see `CLAUDE.md`), and
neither SDK's structured-output path wraps its own exceptions the way each
provider's plain chat path does: a 429 from Gemini surfaces as
`google.genai.errors.ClientError`, whose message is the API's full JSON error
body, and Ollama's `ollama.ResponseError` carries only a bare HTTP status code.
Both are written for a developer's log, not for someone waiting on their
report. This module recognises the two shapes — and Strands' own
`ModelThrottledException`, in case a future call path goes through it instead,
and `callbudget.OllamaBudgetExceeded`, this deployment's own safety cap — and
replaces them with a plain sentence naming the provider and tier. Every other
exception is left exactly as it was; nothing here changes what gets logged,
only what a citizen is shown.
"""

from __future__ import annotations

from collections.abc import Iterator

from .callbudget import OllamaBudgetExceeded
from .config import Tier, settings

#: What each tier was doing when it failed, for the sentence that names it.
_TIER_WORK = {
    "primary": "reading the photograph or drafting the complaint",
    "fast": "checking the corroborating evidence",
}

#: Numbers confirmed against the free tier's own published limits, keyed by
#: model id. Only models actually shipped in `DEFAULT_MODEL_IDS` are listed —
#: an unlisted model gets the generic wording rather than an invented number.
_GEMINI_KNOWN_LIMITS = {
    "gemini-3.5-flash-lite": "15 requests/minute, 250,000 tokens/minute, and 500 requests/day",
}


def is_rate_limit(exc: Exception, tier: Tier) -> bool:
    """Whether `exc` is a recognised free-tier rate limit from `tier`'s provider."""
    return _is_rate_limit(exc, settings.provider_for(tier))


def describe(exc: Exception, tier: Tier) -> str:
    """A message for `case.error`.

    A clean sentence when `exc` is a recognised free-tier rate limit from the
    provider configured for `tier`; otherwise the same `Type: message` format
    every other pipeline failure has always used.
    """
    fallback = f"{type(exc).__name__}: {exc}"
    budget_trip = _find(exc, OllamaBudgetExceeded)
    if budget_trip is not None:
        # callbudget.py already wrote the full sentence; nothing to add here.
        return str(budget_trip)
    if not is_rate_limit(exc, tier):
        return fallback

    provider = settings.provider_for(tier)
    model_id = settings.model_id_for(tier)
    work = _TIER_WORK[tier]

    if provider == "gemini":
        limits = _GEMINI_KNOWN_LIMITS.get(model_id)
        known = f" Its free-tier limits are {limits}." if limits else ""
        retry = _gemini_retry_seconds(exc)
        wait = (
            f"Retry in about {retry} seconds." if retry is not None
            else "Per-minute limits clear within a minute; the daily allowance resets at "
            "midnight Pacific time."
        )
        return (
            f"{model_id} (Gemini) has hit its free-tier request quota while {work}."
            f"{known} {wait}"
        )
    if provider == "ollama":
        return (
            f"{model_id} (Ollama Cloud) has hit its free-tier quota while {work}. "
            "The allowance is published as a session and weekly percentage rather "
            "than a request count — check the meter at https://ollama.com/settings/keys "
            "and try again shortly."
        )
    return fallback


def _is_rate_limit(exc: Exception, provider: str) -> bool:
    from strands.types.exceptions import ModelThrottledException

    for candidate in _chain(exc):
        if isinstance(candidate, (ModelThrottledException, OllamaBudgetExceeded)):
            return True
        if provider == "gemini" and _is_gemini_rate_limit(candidate):
            return True
        if provider == "ollama" and _is_ollama_rate_limit(candidate):
            return True
    return False


def _is_gemini_rate_limit(exc: Exception) -> bool:
    try:
        from google.genai.errors import ClientError
    except ImportError:
        return False
    return isinstance(exc, ClientError) and (
        exc.code == 429 or exc.status == "RESOURCE_EXHAUSTED"
    )


def _is_ollama_rate_limit(exc: Exception) -> bool:
    try:
        from ollama import ResponseError
    except ImportError:
        return False
    return isinstance(exc, ResponseError) and exc.status_code == 429


def _gemini_retry_seconds(exc: Exception | None) -> int | None:
    """Google's own suggested wait, when the API bothered to send one.

    A 429 body can carry a `google.rpc.RetryInfo` detail alongside the
    `QuotaFailure` — e.g. `{"@type": "...RetryInfo", "retryDelay": "20s"}` —
    which is the API naming the exact remaining wait rather than the generic
    per-minute-or-per-day guess this module would otherwise give.
    """
    for candidate in _chain(exc):
        details = getattr(candidate, "details", None)
        if not isinstance(details, dict):
            continue
        body = details.get("error", details)
        for detail in body.get("details") or []:
            if not isinstance(detail, dict):
                continue
            if str(detail.get("@type", "")).endswith("RetryInfo"):
                delay = str(detail.get("retryDelay", ""))
                if delay.endswith("s"):
                    try:
                        return round(float(delay[:-1]))
                    except ValueError:
                        return None
    return None


def _find(exc: Exception | None, kind: type) -> Exception | None:
    for candidate in _chain(exc):
        if isinstance(candidate, kind):
            return candidate
    return None


def _chain(exc: Exception | None) -> Iterator[Exception]:
    """`exc`, then each exception it was raised from or during.

    A Strands graph node (`corroborate`'s parallel fan-out) can wrap the
    provider's own exception rather than let it propagate directly, so every
    lookup in this module has to walk the chain rather than inspect `exc`
    alone.
    """
    seen: set[int] = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__
