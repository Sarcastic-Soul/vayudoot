"""Caps on the one endpoint that spends money.

A report costs about ten model calls, all of them from a free tier with a daily
allowance. `POST /reports` on a public URL is therefore an open tap: a crawler
that finds the form can empty the day's budget in a minute, and the failure is
invisible — the next citizen's report just fails at the evidence stage.

Two caps, because they answer different problems:

* a rolling per-client cap, so one visitor cannot monopolise the instance
* a global daily cap, which is the actual budget line and holds even when the
  traffic arrives from a hundred addresses

Counters live in this process's memory and are lost on restart. That is a
deliberate choice, not an omission: the app is a single process with a
JSON-file case store, so there is no shared state to put them in, and adding
Redis would break the free-tier rule for a prototype whose whole store is a
directory of files. The consequence is that a restart hands out a fresh budget.
Acceptable here — a restart is rare, and this is a spend guard rather than a
security boundary. A multi-process deployment would need to move these counters
somewhere shared, and that is the point at which this module gets replaced.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from .config import settings


@dataclass(frozen=True)
class Decision:
    """The answer to one request, and what to tell the caller if it is no."""

    allowed: bool
    scope: str = ""
    retry_after_seconds: int = 0
    message: str = ""


def _reports(count: int) -> str:
    return f"{count} report{'s' if count != 1 else ''}"


def _duration(seconds: int) -> str:
    """A rough human duration. The exact second is noise in an apology."""
    if seconds < 60:
        return "a minute"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours = round(seconds / 3600)
    return f"{hours} hour{'s' if hours != 1 else ''}"


class RateLimiter:
    """Fixed budgets over a rolling client window and a UTC day.

    The clock is injected so tests can move time without sleeping.
    """

    def __init__(self, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.now(UTC))
        self._clients: dict[str, deque[datetime]] = {}
        self._day: date | None = None
        self._day_count = 0

    # -- state ------------------------------------------------------------

    def reset(self) -> None:
        self._clients.clear()
        self._day = None
        self._day_count = 0

    @property
    def enabled(self) -> bool:
        return settings.vayudoot_rate_limit

    def remaining_today(self) -> int:
        """Reports the instance can still accept before the UTC day rolls over."""
        self._roll_day(self._now())
        return max(0, settings.vayudoot_reports_per_day - self._day_count)

    # -- decisions --------------------------------------------------------

    def check(self, client: str) -> Decision:
        """Consume one unit of budget for `client`, or explain why it cannot."""
        if not self.enabled:
            return Decision(allowed=True)

        now = self._now()
        self._roll_day(now)

        if self._day_count >= settings.vayudoot_reports_per_day:
            retry_after = int((_next_utc_midnight(now) - now).total_seconds())
            return Decision(
                allowed=False,
                scope="global",
                retry_after_seconds=retry_after,
                message=(
                    f"This instance accepts {_reports(settings.vayudoot_reports_per_day)} a day "
                    "and has reached that limit — a report costs about ten model calls and the "
                    "quota is a free tier. The budget resets at midnight UTC, in about "
                    f"{_duration(retry_after)}."
                ),
            )

        window = timedelta(seconds=settings.vayudoot_rate_limit_window_seconds)
        recent = self._clients.setdefault(client, deque())
        while recent and now - recent[0] >= window:
            recent.popleft()

        if len(recent) >= settings.vayudoot_reports_per_client:
            # The deque is empty when the cap is zero, which is a legitimate way
            # to close intake; there is no earlier request to expire, so the wait
            # is a whole window.
            oldest = recent[0] if recent else now
            retry_after = max(1, int((oldest + window - now).total_seconds()))
            return Decision(
                allowed=False,
                scope="client",
                retry_after_seconds=retry_after,
                message=(
                    f"This instance accepts {_reports(settings.vayudoot_reports_per_client)} "
                    f"per visitor every {_duration(int(window.total_seconds()))}, and you have "
                    f"reached that limit. Try again in about {_duration(retry_after)}."
                ),
            )

        recent.append(now)
        self._day_count += 1
        return Decision(allowed=True)

    # -- internals --------------------------------------------------------

    def _roll_day(self, now: datetime) -> None:
        today = now.date()
        if self._day != today:
            self._day = today
            self._day_count = 0
            # Client windows are rolling and expire on their own; dropping the
            # empty ones here keeps the dict from growing for the life of the
            # process on an instance nobody is using.
            self._clients = {k: v for k, v in self._clients.items() if v}


def _next_utc_midnight(now: datetime) -> datetime:
    return datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC)


#: The instance-wide limiter. One process, one budget.
limiter = RateLimiter()
