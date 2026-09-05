"""Model provider factory.

No module in this project constructs a provider directly. They all call
`build_model()`, which reads the configured provider at runtime. Swapping the
whole system from Amazon Bedrock to Google Gemini is one environment variable.
"""

from __future__ import annotations

from typing import Any

from .config import Provider, Tier, settings


def build_model(temperature: float | None = None, tier: Tier = "primary") -> Any:
    """Return a Strands model instance for the configured provider.

    `tier` picks between the primary model, used where judgement matters, and the
    fast model, used by agents that only call a tool and summarise the result.
    """
    provider: Provider = settings.vayudoot_model_provider
    temp = settings.vayudoot_model_temperature if temperature is None else temperature
    model_id = settings.model_id_for(tier)

    if provider == "bedrock":
        from strands.models import BedrockModel

        return BedrockModel(
            model_id=model_id,
            region_name=settings.aws_region,
            temperature=temp,
        )

    if provider == "gemini":
        from strands.models.gemini import GeminiModel

        return GeminiModel(
            client_args={"api_key": settings.gemini_api_key},
            model_id=model_id,
            params={"temperature": temp},
        )

    if provider == "anthropic":
        from strands.models.anthropic import AnthropicModel

        return AnthropicModel(
            client_args={"api_key": settings.anthropic_api_key},
            model_id=model_id,
            params={"temperature": temp, "max_tokens": 4096},
        )

    if provider == "ollama":
        from strands.models.ollama import OllamaModel

        return OllamaModel(host=settings.ollama_host, model_id=model_id)

    raise ValueError(f"Unknown model provider: {provider}")
