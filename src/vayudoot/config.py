"""Runtime configuration.

Everything that varies between deployments lives here, so that switching model
provider or deployment target is a configuration change rather than a code
change. That is the whole reason the Strands provider abstraction is worth using.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["bedrock", "gemini", "ollama"]
Tier = Literal["primary", "fast"]

# Two tiers, because inference is the only real running cost of this project.
#
#   primary  judgement work: reading a photograph, drafting a legal complaint
#   fast     mechanical work: calling one tool and summarising its output
#
# The corroboration graph runs three agents in parallel and each does nothing but
# call a tool and summarise. Running those on the primary model multiplies the
# cost of every report for no gain in quality.
DEFAULT_MODEL_IDS: dict[str, dict[str, str]] = {
    "bedrock": {
        "primary": "us.amazon.nova-pro-v1:0",
        "fast": "us.amazon.nova-lite-v1:0",
    },
    "gemini": {
        "primary": "gemini-3.5-flash",
        "fast": "gemini-3.5-flash-lite",
    },
    "ollama": {
        "primary": "llama3.2",
        "fast": "llama3.2",
    },
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
    vayudoot_model_id_fast: str = ""
    vayudoot_model_temperature: float = 0.2

    aws_region: str = "us-west-2"
    gemini_api_key: str = ""
    ollama_host: str = "http://localhost:11434"

    # Evidence sources
    firms_map_key: str = ""
    openaq_api_key: str = ""

    # Filing safety
    vayudoot_live_filing: bool = False
    vayudoot_sandbox_outbox: Path = Path("./outbox")

    # Storage
    vayudoot_case_dir: Path = Path("./data/cases")
    vayudoot_upload_dir: Path = Path("./data/uploads")

    def model_id_for(self, tier: Tier = "primary") -> str:
        override = self.vayudoot_model_id if tier == "primary" else self.vayudoot_model_id_fast
        return override or DEFAULT_MODEL_IDS[self.vayudoot_model_provider][tier]

    @property
    def model_id(self) -> str:
        return self.model_id_for("primary")


settings = Settings()
