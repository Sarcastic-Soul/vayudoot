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

    # Ollama Cloud's free tier publishes no request count, only a session
    # percentage (resets every 4 hours) and a weekly one (resets every 5 days) —
    # see `docs/deployment.md`. There is nothing to mirror precisely, so this is
    # a safety cap rather than a copy of the real quota: high enough that normal
    # use and the test suite never reach it, low enough to stop a retry loop or a
    # scheduler bug from quietly burning a session or a week of the budget.
    # `errors.py` turns a trip into the same kind of plain sentence as an actual
    # provider rate limit.
    vayudoot_ollama_session_call_limit: int = 200
    vayudoot_ollama_session_window_hours: float = 4
    vayudoot_ollama_weekly_call_limit: int = 1000
    vayudoot_ollama_weekly_window_days: float = 5

    # Evidence sources
    firms_map_key: str = ""
    openaq_api_key: str = ""

    # Filing safety
    vayudoot_live_filing: bool = False
    vayudoot_sandbox_outbox: Path = Path("./outbox")

    # Storage
    vayudoot_case_dir: Path = Path("./data/cases")
    vayudoot_upload_dir: Path = Path("./data/uploads")
    #: A Postgres connection string (Neon, Supabase, or any other host — the
    #: store is plain SQL, nothing provider-specific). Unprefixed, like the
    #: other external-service credentials above, because it's the name every
    #: Postgres host already hands you. Empty, the default and what every test
    #: uses, keeps cases as JSON files under `vayudoot_case_dir` instead; see
    #: `store.py`. That default is fine for a demo but not for a public
    #: deployment, where the container's disk does not survive a restart.
    database_url: str = ""

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
    #: Applied per photograph; a report's whole body is allowed this much times
    #: the image cap below.
    vayudoot_max_upload_bytes: int = 12 * 1024 * 1024
    #: Photographs one report may carry. Every one of them is an image block in
    #: the same evidence call, and at the 1568-pixel edge `images.py` normalises
    #: to, each costs on the order of 1,500 tokens against a metered free tier —
    #: so the cap is a budget line, not a form-validation nicety. Four is what a
    #: citizen standing in front of a fire actually takes: the event, a wider
    #: frame for context, a closer one for what is burning, and a sign or
    #: landmark. Past that the angles repeat and the classification does not
    #: improve, so the marginal image is quota spent for nothing.
    vayudoot_max_images_per_report: int = 4

    # Repeat-report clustering. Grouping is pure logic over stored cases, so
    # these three numbers are the whole definition of "the same problem" — and
    # each is a judgement about pollution, not a tuning knob.
    #
    #: How far apart two reports can be and still be one problem. 500 m is a
    #: couple of street blocks: it holds together two sightings of one waste fire
    #: photographed from either end of a lane, while keeping the next
    #: neighbourhood out. It is also above a phone's GPS error in an urban canyon
    #: (tens of metres) and above VIIRS's 375 m thermal pixel, so a tighter radius
    #: would be splitting groups on noise the evidence cannot resolve anyway.
    vayudoot_cluster_radius_km: float = 0.5
    #: The longest gap between consecutive reports that still reads as one
    #: ongoing pattern. 30 days is the default statutory response window, which
    #: makes the pattern argument land where it bites: everything inside it
    #: happened while the authority had the case and was obliged to act. Note
    #: this is a maximum gap, not a maximum age — a site burning fortnightly for
    #: six months is one pattern, not thirteen.
    vayudoot_cluster_window_days: int = 30
    #: Reports needed before a group is a pattern worth citing. Two sightings a
    #: fortnight apart are a coincidence and citing them as a pattern invites the
    #: dismissal; three is the smallest number that reads as recurrence. It also
    #: keeps every one-off report out of the clusters listing.
    vayudoot_cluster_min_reports: int = 3

    # Hotspot detection. A hotspot is the unit of work from v0.3 on and these
    # numbers are its whole definition, so each is a judgement about pollution
    # rather than a tuning knob. See `hotspots.py`.
    #
    #: How far apart two observations can be and still be one event. Wider than
    #: the 500 m clustering radius, and deliberately: clustering groups citizen
    #: photographs of one visible pile, where tight is right, while detection
    #: must also group a VIIRS pixel — 375 m on its own, and located to the pixel
    #: rather than to the fire inside it — against a photograph taken from the
    #: roadside. 2 km absorbs that error without merging neighbourhoods.
    vayudoot_hotspot_radius_km: float = 2.0
    #: The smallest radius a hotspot may be published with, whatever the signals
    #: say. Hard constraint 7: a hotspot drawn around one building is a public
    #: accusation against whoever occupies it. 1 km is a neighbourhood — enough
    #: to dispatch an inspector to, not enough to point at a gate.
    vayudoot_hotspot_min_radius_km: float = 1.0
    #: Longest gap between consecutive signals that still reads as one ongoing
    #: event. Shorter than clustering's 30 days, which is a statutory window and
    #: answers a different question — whether an authority sat on a pattern.
    #: This answers whether something is happening *now*, and a fortnight is
    #: already generous for that: a seasonal burn or an industrial stack running
    #: nightly produces signals far more often.
    vayudoot_hotspot_window_days: int = 14
    #: Signals needed before a hotspot is published. One is deliberate and is the
    #: sharpest difference from clustering, which needs three. A single VIIRS
    #: detection is an instrument in orbit recording a fire; requiring it to
    #: repeat would discard exactly the hyper-local event the brief says
    #: monitoring misses. Confidence, not suppression, is how a thin hotspot is
    #: reported honestly.
    vayudoot_hotspot_min_signals: int = 1
    #: The most confidence a hotspot may carry when every signal supporting it
    #: came from the public. Hard constraint 7: without a cap, coordinated false
    #: reporting manufactures a hotspot and a public map becomes a weapon. 0.6
    #: sits below the 0.7 the severity bands treat as "high", so an uncorroborated
    #: hotspot is always visible, always marked, and never top of the list.
    vayudoot_hotspot_uncorroborated_cap: float = 0.6
    #: Indian National Ambient Air Quality Standards, CPCB notification
    #: S.O. 384(E) of 18 November 2009, 24-hour averages in µg/m³ (CO in mg/m³,
    #: which is the unit its standard is written in). A station reading below its
    #: standard produces no signal at all; see `hotspots._exceedance`.
    #:
    #: These are the Indian standards, not the WHO guidelines, which are several
    #: times stricter. A hotspot is raised so that an Indian authority acts on
    #: it, and it must be measured against the number that authority is bound by
    #: — a map flagging half the country for exceeding a guideline nobody is
    #: obliged to meet tells an inspector nothing.
    naaqs_standards: dict[str, float] = {
        "pm25": 60.0,
        "pm2.5": 60.0,
        "pm10": 100.0,
        "no2": 80.0,
        "so2": 80.0,
        "o3": 100.0,
        "co": 2.0,
        "nh3": 400.0,
    }

    # Signal scanning. The scan is what makes the map non-empty: hotspot
    # detection can already raise a hotspot from satellite or station evidence,
    # but something has to go and fetch that evidence. See `scan.py`.
    #
    #: Whether the periodic scan runs at all. Off by default, and deliberately:
    #: an unattended loop calling two external APIs is the kind of thing that
    #: should be switched on by whoever is watching the quota, not by importing
    #: a module.
    vayudoot_scan_enabled: bool = False
    #: Minutes between scans. VIIRS passes roughly twice a day, so anything under
    #: an hour is polling for data that has not moved; 60 keeps the map fresh
    #: without spending requests on unchanged answers.
    vayudoot_scan_interval_minutes: int = 60
    #: How far back each scan looks for satellite detections. FIRMS allows up to
    #: 10 days. Two covers a missed scan and a satellite gap without dragging in
    #: fires that have long since burnt out.
    vayudoot_scan_days: int = 2
    #: Radius each scan point covers, in kilometres.
    vayudoot_scan_radius_km: float = 50.0
    #: How long a stored signal stays eligible for detection. Past this it is
    #: history, not a live hotspot. Matched to the hotspot window so a signal
    #: cannot age out of a hotspot it is still holding together.
    vayudoot_signal_retention_days: int = 30

    # Forecasting. Hard constraint 7: everything here produces a model's
    # reasoning over public data, never an official advisory.
    #
    #: How far ahead a forecast looks. Open-Meteo publishes well past this;
    #: 72 hours is where a wind forecast stops being worth acting on, and a
    #: longer horizon would be confidence the inputs do not support.
    vayudoot_forecast_horizon_hours: int = 72
    #: How far upwind to look for hotspots that could reach a location.
    #:
    #: Set against the horizon above, not against a single night. At the 3-5 m/s
    #: typical of the Indo-Gangetic plain in burning season, air covers roughly
    #: 260-430 km a day, so over 72 hours a 400 km reach is the conservative end
    #: rather than the generous one.
    #:
    #: The number is checked against the case the whole thing exists for:
    #: Ludhiana to Delhi is 286 km. A tighter reach — 200 km was the first
    #: guess — puts Punjab's burning outside Delhi's forecast entirely, which is
    #: precisely the event Indian air quality forecasting exists to catch.
    vayudoot_forecast_upwind_km: float = 400.0

    # Federation. A node publishes the hotspots it found and can read a
    # neighbour's; see `federation.py`. What is shared is a detection layer, not
    # trained weights.
    #
    #: This instance's identity on that network. The defaults describe a single
    #: unconfigured deployment rather than pretending to be a state.
    vayudoot_node_id: str = "vayudoot-local"
    vayudoot_node_name: str = "Vayudoot (unconfigured node)"
    vayudoot_node_region: str = "unspecified"
    vayudoot_node_url: str = ""
    vayudoot_node_contact: str = ""
    #: Neighbour feed URLs, comma-separated. A node reads these and folds their
    #: hotspots into its own forecasting, which is how a Punjab detection reaches
    #: a Delhi outlook. Empty is a node that federates with nobody.
    vayudoot_neighbour_feeds: str = ""
    #: Whether this node publishes its own feed. On by default: a node that reads
    #: neighbours without publishing is taking from a commons it does not supply.
    vayudoot_publish_feed: bool = True

    @property
    def neighbour_feeds(self) -> list[str]:
        return [url.strip() for url in self.vayudoot_neighbour_feeds.split(",") if url.strip()]

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
