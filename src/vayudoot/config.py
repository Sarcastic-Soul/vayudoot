"""Runtime configuration.

Everything that varies between the three hackathon submissions lives here, so
that switching model provider or deployment target is a configuration change
rather than a code change. That is the whole reason the Strands provider
abstraction is worth using.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["bedrock", "gemini", "anthropic", "ollama"]

# Sensible default model per provider, used when VAYUDOOT_MODEL_ID is unset.
DEFAULT_MODEL_IDS: dict[str, str] = {
    "bedrock": "global.anthropic.claude-sonnet-4-6",
    "gemini": "gemini-2.5-flash",
    "anthropic": "claude-sonnet-4-6",
    "ollama": "llama3.2",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        extra="ignore",
        protected_namespaces=(),
    )

    # Model provider
    vayudoot_model_provider: Provider = "bedrock"
    vayudoot_model_id: str = ""
    vayudoot_model_temperature: float = 0.2

    aws_region: str = "us-west-2"
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    ollama_host: str = "http://localhost:11434"

    # Evidence sources
    firms_map_key: str = ""
    openaq_api_key: str = ""

    # Filing safety
    vayudoot_live_filing: bool = False
    vayudoot_sandbox_outbox: Path = Path("./outbox")

    # Storage
    vayudoot_case_dir: Path = Path("./data/cases")

    @property
    def model_id(self) -> str:
        return self.vayudoot_model_id or DEFAULT_MODEL_IDS[self.vayudoot_model_provider]


settings = Settings()
