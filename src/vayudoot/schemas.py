"""Typed contracts between pipeline stages.

Each agent stage produces one of these via Strands structured output, so the
handoff between stages is a validated object rather than free text.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


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
    """What the citizen submits."""

    report_id: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    image_path: str | None = None
    note: str = ""
    reporter_contact: str = ""
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


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
    error: str = ""
    history: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def log(self, entry: str) -> None:
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        self.history.append(f"{stamp} {entry}")
        self.updated_at = datetime.now(UTC)
