"""A safety cap on Ollama Cloud calls, since the provider's own limit is opaque.

Gemini's free tier publishes exact numbers (15 requests/minute, 250,000
tokens/minute, 500 requests/day for `gemini-3.5-flash-lite`), so a 429 from it
can be explained precisely. Ollama Cloud's free tier is metered as a session
percentage, reset every 4 hours, and a weekly percentage, reset every 5 days —
there is no request count to check against or report back.

Rather than fly blind, `build_model()` counts calls to the Ollama provider
against two rolling windows shaped like Ollama's own reset cadence, with
defaults picked to be a backstop rather than a real limit: high enough that
normal use and the offline test suite never reach them, low enough that a
retry loop or a scheduler bug cannot quietly spend a whole session or week of
budget before anyone notices. Tripping it raises `OllamaBudgetExceeded`, which
`errors.py` treats the same way as a genuine provider rate limit.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .config import settings


class OllamaBudgetExceeded(RuntimeError):
    """This deployment's own safety cap tripped, not Ollama's."""


@dataclass(frozen=True)
class Decision:
    allowed: bool
    message: str = ""


def _duration(delta: timedelta) -> str:
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return f"{max(1, round(delta.total_seconds() / 60))} minute(s)"
    if hours < 48:
        return f"{round(hours)} hour(s)"
    return f"{round(hours / 24)} day(s)"


class OllamaCallBudget:
    """Two rolling windows, checked before every call `build_model()` makes to
    Ollama. The clock is injected so tests can move time without sleeping."""

    def __init__(self, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.now(UTC))
        self._session: deque[datetime] = deque()
        self._weekly: deque[datetime] = deque()

    def reset(self) -> None:
        self._session.clear()
        self._weekly.clear()

    def check(self) -> Decision:
        now = self._now()
        session_window = timedelta(hours=settings.vayudoot_ollama_session_window_hours)
        weekly_window = timedelta(days=settings.vayudoot_ollama_weekly_window_days)

        while self._session and now - self._session[0] >= session_window:
            self._session.popleft()
        while self._weekly and now - self._weekly[0] >= weekly_window:
            self._weekly.popleft()

        if len(self._session) >= settings.vayudoot_ollama_session_call_limit:
            return Decision(
                allowed=False,
                message=(
                    f"This deployment's own safety cap of "
                    f"{settings.vayudoot_ollama_session_call_limit} Ollama Cloud calls per "
                    f"{_duration(session_window)} has been reached. This is a backstop against "
                    "runaway usage, not Ollama's own limit — that is published only as a session "
                    "percentage at https://ollama.com/settings/keys. Wait for the session to roll "
                    "over, or raise VAYUDOOT_OLLAMA_SESSION_CALL_LIMIT if this is a false alarm."
                ),
            )
        if len(self._weekly) >= settings.vayudoot_ollama_weekly_call_limit:
            return Decision(
                allowed=False,
                message=(
                    f"This deployment's own safety cap of "
                    f"{settings.vayudoot_ollama_weekly_call_limit} Ollama Cloud calls per "
                    f"{_duration(weekly_window)} has been reached. This is a backstop against "
                    "runaway usage, not Ollama's own limit — that is published only as a weekly "
                    "percentage at https://ollama.com/settings/keys. Wait for the week to roll "
                    "over, or raise VAYUDOOT_OLLAMA_WEEKLY_CALL_LIMIT if this is a false alarm."
                ),
            )

        self._session.append(now)
        self._weekly.append(now)
        return Decision(allowed=True)


#: One process, one budget — same reasoning as `ratelimit.limiter`.
budget = OllamaCallBudget()
