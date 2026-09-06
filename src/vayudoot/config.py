"""Runtime configuration.

Everything that varies between deployments lives here, so that switching model
provider or deployment target is a configuration change rather than a code
change. That is the whole reason the Strands provider abstraction is worth using.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["gemini", "ollama"]
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
    "gemini": {
        "primary": "gemini-3.5-flash",
        "fast": "gemini-3.5-flash-lite",
    },
    # Ollama defaults are the Ollama Cloud free-tier models rather than local
    # ones, because a laptop that cannot host a vision model is the common case.
    # gemma4:31b is multimodal, which the evidence stage requires; nothing else on
    # the free tier reads an image. Point OLLAMA_HOST at localhost and override
    # both ids to run locally instead.
    "ollama": {
        "primary": "gemma4:31b",
        "fast": "gpt-oss:20b",
    },
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        extra="ignore",
        protected_namespaces=(),
    )

    # Model provider. The fast tier can run on a different provider from the
    # primary one, which is how the running cost is spread across two free tiers:
    # the eight mechanical calls a report makes go to whichever provider has the
    # generous request allowance, and the two that need judgement go to whichever
    # has the better model. Leave the fast one unset to use a single provider.
    vayudoot_model_provider: Provider = "gemini"
    vayudoot_model_provider_fast: Provider | None = None
    vayudoot_model_id: str = ""
    vayudoot_model_id_fast: str = ""
    vayudoot_model_temperature: float = 0.2

    gemini_api_key: str = ""
    ollama_host: str = "https://ollama.com"
    ollama_api_key: str = ""

    # Evidence sources
    firms_map_key: str = ""
    openaq_api_key: str = ""

    # Filing safety
    vayudoot_live_filing: bool = False
    vayudoot_sandbox_outbox: Path = Path("./outbox")

    # Storage
    vayudoot_case_dir: Path = Path("./data/cases")
    vayudoot_upload_dir: Path = Path("./data/uploads")

    # Intake limits. One report costs about ten model calls, so an open endpoint
    # on a public URL is an open tap on the day's free-tier quota: a single
    # crawler that finds the form empties it before a citizen gets there. Both
    # caps are counted in process; see `ratelimit.py` for why that is enough here.
    vayudoot_rate_limit: bool = True
    #: Reports one client may submit inside the rolling window below.
    vayudoot_reports_per_client: int = 5
    vayudoot_rate_limit_window_seconds: int = 3600
    #: Reports the whole instance may accept in one UTC day. Ten model calls each,
    #: so this is the real budget line.
    vayudoot_reports_per_day: int = 60
    #: Largest photograph accepted, in bytes. Phone JPEGs are 2-6 MB; anything
    #: past this is refused before it is read into a container with little RAM.
    vayudoot_max_upload_bytes: int = 12 * 1024 * 1024

    def provider_for(self, tier: Tier = "primary") -> Provider:
        if tier == "fast" and self.vayudoot_model_provider_fast:
            return self.vayudoot_model_provider_fast
        return self.vayudoot_model_provider

    def model_id_for(self, tier: Tier = "primary") -> str:
        override = self.vayudoot_model_id if tier == "primary" else self.vayudoot_model_id_fast
        return override or DEFAULT_MODEL_IDS[self.provider_for(tier)][tier]

    @property
    def model_id(self) -> str:
        return self.model_id_for("primary")


settings = Settings()
