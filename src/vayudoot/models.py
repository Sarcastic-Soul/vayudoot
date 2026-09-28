"""Model provider factory.

No module in this project constructs a provider directly. They all call
`build_model()`, which reads the configured provider at runtime. Swapping the
whole system from Google Gemini to Ollama is one environment variable.
"""

from __future__ import annotations

from typing import Any

from .callbudget import OllamaBudgetExceeded
from .callbudget import budget as ollama_budget
from .config import Provider, Tier, settings


def build_model(
    temperature: float | None = None, tier: Tier = "primary", gemini_tools: list | None = None
) -> Any:
    """Return a Strands model instance for the configured provider.

    `tier` picks between the primary model, used where judgement matters, and the
    fast model, used by agents that only call a tool and summarise the result.
    The two tiers may sit on different providers; `settings.provider_for()` is
    the only thing that decides which.

    `gemini_tools` passes Gemini's built-in tools — Grounding with Google Maps,
    Google Search — through to the request. Ignored on any other provider, so a
    caller that wants grounding must cope with not getting it.

    On Gemini the model walks `settings.model_chain_for(tier)` when one answers
    429; see `MODEL_FALLBACKS` in `config.py` for why.
    """
    provider: Provider = settings.provider_for(tier)
    temp = settings.vayudoot_model_temperature if temperature is None else temperature
    model_id = settings.model_id_for(tier)

    if provider == "gemini":
        config: dict[str, Any] = {"params": {"temperature": temp}}
        if gemini_tools:
            config["gemini_tools"] = gemini_tools
        return _gemini_with_fallback()(
            client_args={"api_key": settings.gemini_api_key},
            model_id=model_id,
            chain=settings.model_chain_for(tier),
            **config,
        )

    if provider == "ollama":
        from strands.models.ollama import OllamaModel

        # The safety cap exists for Ollama Cloud's opaque session/weekly quota;
        # a local daemon has no such quota to protect and should not be throttled
        # by a guard that exists for a budget it does not have.
        if _is_ollama_cloud(settings.ollama_host):
            decision = ollama_budget.check()
            if not decision.allowed:
                raise OllamaBudgetExceeded(decision.message)

        # The same provider serves a local daemon and Ollama Cloud; the only
        # difference is the host and a bearer token. Sending an empty header
        # would break a local daemon, so it is only added when a key is set.
        client_args: dict[str, Any] = {}
        if settings.ollama_api_key:
            client_args["headers"] = {"Authorization": f"Bearer {settings.ollama_api_key}"}

        return OllamaModel(
            host=settings.ollama_host,
            model_id=model_id,
            ollama_client_args=client_args or None,
            temperature=temp,
        )

    raise ValueError(f"Unknown model provider: {provider}")


def _is_ollama_cloud(host: str) -> bool:
    return "ollama.com" in host


#: When each model last answered 429, so the next call skips straight past it
#: rather than spending a request to be told again. Process-wide on purpose:
#: the quota is per key and model, not per agent.
_throttled_at: dict[str, float] = {}

#: How long a rate-limited model is skipped. A per-minute limit clears inside
#: this; a per-day one costs one quick rejected request per interval, which is
#: cheaper than tracking the day boundary AI Studio resets on.
THROTTLE_COOLDOWN_SECONDS = 60.0


def _gemini_with_fallback():
    """Build the class lazily so importing this module never imports Gemini."""
    import time

    from strands.models.gemini import GeminiModel
    from strands.types.exceptions import ModelThrottledException

    class FallbackGeminiModel(GeminiModel):
        """A `GeminiModel` that moves down its chain when a model is rate limited.

        Only a failure before the first streamed chunk falls through. Once a model
        has started answering, a 429 mid-stream is re-raised, because splicing
        two models' halves of one response would be worse than failing.
        """

        def __init__(self, *, chain: list[str], **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self._chain = chain or [self.config["model_id"]]

        def _candidates(self) -> list[str]:
            now = time.monotonic()
            fresh = [
                m for m in self._chain
                if now - _throttled_at.get(m, -1e9) > THROTTLE_COOLDOWN_SECONDS
            ]
            # Everything cooling down: try them all anyway rather than fail
            # without asking.
            return fresh or list(self._chain)

        async def stream(self, *args: Any, **kwargs: Any):
            last: Exception | None = None
            for model_id in self._candidates():
                self.update_config(model_id=model_id)
                started = False
                try:
                    async for event in super().stream(*args, **kwargs):
                        started = True
                        yield event
                    return
                except ModelThrottledException as exc:
                    if started:
                        raise
                    _throttled_at[model_id] = time.monotonic()
                    last = exc
            assert last is not None
            raise last

        async def structured_output(self, *args: Any, **kwargs: Any):
            from google.genai.errors import ClientError

            last: Exception | None = None
            for model_id in self._candidates():
                self.update_config(model_id=model_id)
                try:
                    async for event in super().structured_output(*args, **kwargs):
                        yield event
                    return
                except ClientError as exc:
                    if exc.status not in ("RESOURCE_EXHAUSTED", "UNAVAILABLE"):
                        raise
                    _throttled_at[model_id] = time.monotonic()
                    last = ModelThrottledException(exc.message or str(exc))
            assert last is not None
            raise last

    return FallbackGeminiModel
