"""Typed contracts between pipeline stages.

Each agent stage produces one of these via Strands structured output, so the
handoff between stages is a validated object rather than free text.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field, model_validator


class PollutionType(str, Enum):
    OPEN_WASTE_BURNING = "open_waste_burning"
    CROP_RESIDUE_BURNING = "crop_residue_burning"
    INDUSTRIAL_EMISSION = "industrial_emission"
    CONSTRUCTION_DUST = "construction_dust"
    VEHICLE_EMISSION = "vehicle_emission"
    UNCLEAR = "unclear"


class CaseStatus(str, Enum):
    """The case's legal lifecycle.

    `draft` through `escalated` are the states the machinery drives. The last
    four are ends: `resolved` (the problem was dealt with), `withdrawn` (the
    citizen took the complaint back), `rejected` (the photograph did not support
    a complaint) and `failed` (the run died).
    """

    DRAFT = "draft"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    FILED = "filed"
    ACKNOWLEDGED = "acknowledged"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    WITHDRAWN = "withdrawn"
    REJECTED = "rejected"
    FAILED = "failed"


#: Statuses nothing moves out of. A case in one of these is finished, whether it
#: ended well or badly, so it can be neither filed, escalated nor withdrawn.
TERMINAL_STATUSES: frozenset[CaseStatus] = frozenset(
    {
        CaseStatus.RESOLVED,
        CaseStatus.WITHDRAWN,
        CaseStatus.REJECTED,
        CaseStatus.FAILED,
    }
)


class Stage(str, Enum):
    """Where a case has reached in the pipeline.

    `status` is the case's legal lifecycle; `stage` is how far the machinery has
    got. They are separate because a case can be `draft` for two minutes while
    four agents run, and the interface has to show something during those two
    minutes.

    There is no `failed` stage: a run that dies leaves `stage` parked on whatever
    was running when it died, which is the thing worth knowing, and records the
    failure in `status`.
    """

    RECEIVED = "received"
    EVIDENCE = "evidence"
    CORROBORATION = "corroboration"
    JURISDICTION = "jurisdiction"
    DRAFTING = "drafting"
    COMPLETE = "complete"
    HALTED = "halted"


#: Stages in the order the pipeline runs them, for rendering a timeline.
STAGE_ORDER: tuple[Stage, ...] = (
    Stage.RECEIVED,
    Stage.EVIDENCE,
    Stage.CORROBORATION,
    Stage.JURISDICTION,
    Stage.DRAFTING,
    Stage.COMPLETE,
)


class Report(BaseModel):
    """What the citizen submits.

    Photographs are a list. One angle is often not enough to classify a plume
    confidently — smoke from across a road and smoke from beside the pile are
    different pictures of one event — and the confidence floor then halts a real
    report. Several angles are more evidence of the same thing, never several
    events; `agents/prompts.EVIDENCE` says so to the model.

    A report submitted before the list existed carries a single `image_path`, and
    three such cases are on disk. Rather than rewriting them, `_accept_one_image`
    folds that key into `image_paths` on the way in, and `image_path` survives on
    the way out as the first photograph, so a stored case and an existing client
    both keep working.
    """

    report_id: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    image_paths: list[str] = Field(default_factory=list)
    note: str = ""
    reporter_contact: str = ""
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="before")
    @classmethod
    def _accept_one_image(cls, data: Any) -> Any:
        """Read the pre-list `image_path` key, from disk or from a caller."""
        if not isinstance(data, dict):
            return data
        if "image_path" not in data:
            return data

        data = dict(data)
        single = data.pop("image_path")
        if single and not data.get("image_paths"):
            data["image_paths"] = [single]
        return data

    @computed_field  # type: ignore[prop-decorator]
    @property
    def image_path(self) -> str | None:
        """The first photograph, for anything still expecting exactly one.

        Serialised, so a stored case round-trips through the old key and the
        `/cases/{id}/photo` URL keeps meaning what it always meant.
        """
        return self.image_paths[0] if self.image_paths else None


class EvidencePacket(BaseModel):
    """Stage 1 output: what the photo shows."""

    pollution_type: PollutionType
    confidence: float = Field(
        ge=0,
        le=1,
        description=(
            "Calibrated 0 to 1 confidence in the classification. A photograph seen out of "
            "context is never certain; 0.9 and above means unambiguous, 1.0 is not a "
            "valid answer."
        ),
    )
    severity: Literal["low", "moderate", "high", "severe"]
    visible_indicators: list[str] = Field(
        default_factory=list, description="What in the image supports the classification"
    )
    landmarks: list[str] = Field(
        default_factory=list, description="Identifiable landmarks, signage, or structures"
    )
    reasoning: str = ""


class Corroboration(BaseModel):
    """Stage 2 output: independent evidence around the report location."""

    air_quality_summary: str = ""
    nearest_station_km: float | None = None
    dominant_pollutant: str | None = None
    satellite_fire_detections: int = 0
    satellite_summary: str = ""
    wind_speed_ms: float | None = None
    wind_from_degrees: float | None = None
    upwind_source_latitude: float | None = None
    upwind_source_longitude: float | None = None
    corroborated: bool = Field(
        description=(
            "True only when a sensor returned a positive reading supporting the report: "
            "a satellite thermal detection, or a station reporting elevated pollutants. "
            "Wind data alone, or null and normal readings, are not corroboration."
        )
    )
    corroboration_notes: str = ""


class Jurisdiction(BaseModel):
    """Stage 3 output: who is actually responsible for this location."""

    coverage: Literal["exact", "fallback", "generic"] = Field(
        default="exact",
        description=(
            "Copy the lookup tool's coverage value exactly. 'exact' means the table named "
            "this authority for this region; 'fallback' means the local body was missing "
            "and this is one tier up; 'generic' means the region is absent entirely and "
            "this is a placeholder. Never upgrade a fallback or generic to exact."
        ),
    )
    coverage_note: str = Field(
        default="", description="Copy the lookup tool's coverage_note verbatim, or leave empty."
    )
    authority_name: str
    authority_tier: Literal["municipal", "state", "central"]
    office: str = ""
    email: str = ""
    statute: str = Field(description="The Act or bylaw the complaint is filed under")
    section: str = ""
    response_window_days: int = Field(
        default=30, description="Statutory window before escalation is warranted"
    )
    escalation_authority: str = ""
    escalation_email: str = ""
    reasoning: str = ""


class Complaint(BaseModel):
    """Stage 4 output: the filed document."""

    subject: str
    body_en: str
    body_local: str = ""
    local_language: str = ""
    cited_statutes: list[str] = Field(default_factory=list)
    requested_action: str = ""


class ClusterMember(BaseModel):
    """One report's place in a repeat pattern."""

    case_id: str
    observed_at: datetime
    latitude: float
    longitude: float
    status: CaseStatus
    distance_km: float = Field(description="Distance from the cluster's centre")


class Cluster(BaseModel):
    """Repeat reports of the same problem at the same place.

    Not a stage output: it is derived from the case store on demand rather than
    stored, because membership changes every time a new report arrives and a
    cached copy would be wrong within the hour. `cluster_id` is stable, so a
    complaint can cite it and the citation keeps resolving as the group grows.
    """

    cluster_id: str
    pollution_type: PollutionType
    centre_latitude: float
    centre_longitude: float
    radius_km: float = Field(description="Greatest distance from the centre to a member")
    report_count: int
    first_reported_at: datetime
    last_reported_at: datetime
    span_days: int
    #: Distinct non-empty reporter contacts. Repeat reports from one person are
    #: worth less than the same count from many, and this is the only part of
    #: that question the data can answer.
    distinct_reporters: int = 0
    #: Reports with no contact at all. These may be one person or twenty; nothing
    #: stored can tell, so they are counted apart rather than assumed independent.
    anonymous_reports: int = 0
    authority_name: str = ""
    address: str = ""
    members: list[ClusterMember] = Field(default_factory=list)


class RTIApplication(BaseModel):
    """A Right to Information application under the RTI Act, 2005.

    A different document from `Complaint`, not a stronger version of one. A
    complaint asks an authority to act; an RTI application asks it to disclose
    what is already written in a file, which is why it carries a statutory
    thirty-day duty to reply and an appeal route when it does not.
    """

    public_authority: str = Field(description="The public authority holding the records")
    pio_designation: str = Field(
        default="The Public Information Officer",
        description=(
            "Address the officer by designation. The officer's name is not known to this "
            "system and must never be invented."
        ),
    )
    office_address: str = Field(
        default="", description="The office address as supplied. Never invented."
    )
    subject: str
    preamble: str = Field(
        default="",
        description=(
            "One paragraph: which complaint this concerns, when it was filed, under what "
            "reference, and that the response window has lapsed."
        ),
    )
    questions: list[str] = Field(
        default_factory=list,
        description=(
            "Numbered requests for information already held on a file. Never a demand for "
            "action and never a request for an opinion; both are refused."
        ),
    )
    fee_note: str = Field(default="", description="The application fee and how it is paid")
    appeal_note: str = Field(
        default="", description="The first-appeal route if no reply arrives within thirty days"
    )
    placeholders: list[str] = Field(
        default_factory=list,
        description="Everything a human must fill in before this can be filed",
    )
    body_local: str = ""
    local_language: str = ""
    #: The assembled application. Written by `agents.rti.render` after drafting,
    #: not by the model, so the statutory scaffolding is identical every time.
    body_en: str = ""


class Case(BaseModel):
    """Everything known about one report, persisted across days."""

    case_id: str
    report: Report
    status: CaseStatus = CaseStatus.DRAFT
    stage: Stage = Stage.RECEIVED
    evidence: EvidencePacket | None = None
    corroboration: Corroboration | None = None
    jurisdiction: Jurisdiction | None = None
    complaint: Complaint | None = None
    address: str = ""
    #: The repeat-report pattern the complaint was drafted against, if there was
    #: one. A record of what the drafting stage actually saw, not a live answer:
    #: membership changes as reports arrive, so ask `GET /cases/{id}/cluster` for
    #: the current group.
    cluster_id: str = ""
    filed_at: datetime | None = None
    escalated_at: datetime | None = None
    # The lifecycle after filing. Every one of these is optional, because a case
    # written before they existed has to keep loading from disk unchanged.
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None
    withdrawn_at: datetime | None = None
    #: What the authority said when it responded.
    response_note: str = ""
    #: What actually happened on the ground, recorded when the case is closed.
    resolution_note: str = ""
    #: Why the citizen took the complaint back.
    withdrawal_note: str = ""
    #: An RTI application drafted once the statutory window lapsed. Held for the
    #: citizen to file in their own name; nothing sends it.
    rti: RTIApplication | None = None
    rti_drafted_at: datetime | None = None
    error: str = ""
    history: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def log(self, entry: str) -> None:
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        self.history.append(f"{stamp} {entry}")
        self.updated_at = datetime.now(UTC)
