"""Turn a Gemini rate-limit error into one sentence a citizen can read.

A 429 from Gemini surfaces as `google.genai.errors.ClientError` (ADK re-raises
it as a subclass of the same), whose message is the API's full JSON error body
with a paragraph of developer advice on top. That is written for a developer's
log, not for someone waiting on their report. This module recognises it and
replaces it with a plain sentence naming the model and tier. Every other
exception is left exactly as it was; nothing here changes what gets logged,
only what a citizen is shown.
"""

from __future__ import annotations

from collections.abc import Iterator

from google.genai.errors import ClientError

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
    """Whether `exc` is a recognised Gemini free-tier rate limit.

    `tier` is unused now that both tiers are on Gemini; it stays so callers
    keep naming the stage that failed.
    """
    return any(_is_gemini_rate_limit(candidate) for candidate in _chain(exc))


def describe(exc: Exception, tier: Tier) -> str:
    """A message for `case.error`.

    A clean sentence when `exc` is a recognised Gemini free-tier rate limit;
    otherwise the same `Type: message` format every other pipeline failure has
    always used.
    """
    if not is_rate_limit(exc, tier):
        return f"{type(exc).__name__}: {exc}"

    model_id = settings.model_id_for(tier)
    work = _TIER_WORK[tier]
    limits = _GEMINI_KNOWN_LIMITS.get(model_id)
    known = f" Its free-tier limits are {limits}." if limits else ""
    retry = _gemini_retry_seconds(exc)
    if is_daily_quota(exc):
        # Checked before the retry delay: a spent daily quota still comes with a
        # RetryInfo of a few seconds, and following it only spends another
        # rejected request.
        wait = f"{DAILY_QUOTA_SPENT}; it resets at midnight Pacific time."
    elif retry is not None:
        wait = f"Retry in about {retry} seconds."
    else:
        wait = (
            "Per-minute limits clear within a minute; the daily allowance resets at "
            "midnight Pacific time."
        )
    return (
        f"{model_id} (Gemini) has hit its free-tier request quota while {work}."
        f"{known} {wait}"
    )


#: The words a daily-quota failure carries in its message. A caller that retries
#: (`scripts/demo_prep.py`) looks for them, so they are one constant.
DAILY_QUOTA_SPENT = "The daily request allowance is spent"


def is_daily_quota(exc: Exception) -> bool:
    """Whether a Gemini rate limit is the per-day quota rather than the per-minute one.

    The 429 body names the quota it hit (`...PerDayPerProjectPerModel-FreeTier`)
    in a `QuotaFailure` detail, and the same id appears in the message text. A
    per-day limit will not clear by waiting minutes, so a retry loop has to
    tell the two apart.
    """
    return any("PerDay" in str(candidate) for candidate in _chain(exc))


def _is_gemini_rate_limit(exc: Exception) -> bool:
    return isinstance(exc, ClientError) and (
        exc.code == 429 or exc.status == "RESOURCE_EXHAUSTED"
    )


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


def _chain(exc: Exception | None) -> Iterator[Exception]:
    """`exc`, then each exception it was raised from or during.

    ADK re-raises a 429 as its own exception `from` the SDK's, and a stage may
    wrap either in its own error, so every lookup in this module has to walk
    the chain rather than inspect `exc` alone.
    """
    seen: set[int] = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__
