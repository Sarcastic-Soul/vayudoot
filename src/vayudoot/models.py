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


def _worth_another_model(exc: Exception) -> bool:
    """Whether a failure belongs to this model rather than to the request.

    Three kinds do, and each is worth moving down the chain for: a 429 (this
    model's quota is spent), a 503 (this model is overloaded — AI Studio's free
    tier answers "high demand" for hours at a time on a popular model while its
    siblings are idle), and a 404 (this model id was retired). Strands turns
    only the first into `ModelThrottledException`; a 503 arrives as the SDK's
    `ServerError`, which is why this does not rely on Strands' mapping.
    Anything else — a bad request, a schema the model cannot follow — would fail
    the same way on every model, so it is raised at once.
    """
    from google.genai.errors import APIError
    from strands.types.exceptions import ModelThrottledException

    if isinstance(exc, ModelThrottledException):
        return True
    if isinstance(exc, APIError):
        return exc.code in (404, 429, 500, 503) or exc.status in (
            "RESOURCE_EXHAUSTED", "UNAVAILABLE", "NOT_FOUND",
        )
    return False


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

        def _format_request_content_part(self, content: Any, tool_use_id_to_name: Any) -> Any:
            """Send an `audio` content block to Gemini as inline data.

            Strands has an `audio` content block — `{"audio": {"format": "ogg",
            "source": {"bytes": ...}}}`, the same Bedrock-shaped envelope as an
            image — and its Bedrock provider sends it, but as of strands-agents
            1.57 its Gemini provider does not: `_format_request_content_part`
            handles document, image, text and tool blocks and raises `TypeError`
            on anything else. Gemini itself reads audio as ordinary inline data,
            exactly as the SDK already sends an image, so this is the one missing
            branch and nothing more.

            Done here, on the class `build_model()` already returns, so a voice
            note goes through the same provider, fallback chain and error mapping
            as every other call, and nothing constructs a Gemini client of its
            own. A private method, so a Strands upgrade could move it;
            `tests/test_voice.py` formats a real audio block through this class
            and fails if the hook stops being reached. If a later Strands handles
            audio itself, delete this.

            The MIME type is set here rather than looked up by `mimetypes`, which
            is what the SDK does for images and which has no entry for WebM or
            M4A audio on most systems.
            """
            if "audio" in content:
                from google.genai import types

                from .audio import mime_type

                block = content["audio"]
                return types.Part(
                    inline_data=types.Blob(
                        data=block["source"]["bytes"], mime_type=mime_type(block["format"])
                    )
                )
            return super()._format_request_content_part(content, tool_use_id_to_name)

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
                except Exception as exc:
                    if started or not _worth_another_model(exc):
                        raise
                    _throttled_at[model_id] = time.monotonic()
                    last = exc
            assert last is not None
            raise last

        async def structured_output(self, *args: Any, **kwargs: Any):
            last: Exception | None = None
            for model_id in self._candidates():
                self.update_config(model_id=model_id)
                try:
                    async for event in super().structured_output(*args, **kwargs):
                        yield event
                    return
                except Exception as exc:
                    if not _worth_another_model(exc):
                        raise
                    _throttled_at[model_id] = time.monotonic()
                    last = ModelThrottledException(str(exc))
            assert last is not None
            raise last

    return FallbackGeminiModel
