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
    DRAFT = "draft"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    FILED = "filed"
    ACKNOWLEDGED = "acknowledged"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    REJECTED = "rejected"


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
    confidence: float = Field(ge=0, le=1, description="0 to 1 confidence in the classification")
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
        description="True when independent data supports the citizen's report"
    )
    corroboration_notes: str = ""


class Jurisdiction(BaseModel):
    """Stage 3 output: who is actually responsible for this location."""

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
    evidence: EvidencePacket | None = None
    corroboration: Corroboration | None = None
    jurisdiction: Jurisdiction | None = None
    complaint: Complaint | None = None
    address: str = ""
    filed_at: datetime | None = None
    escalated_at: datetime | None = None
    history: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def log(self, entry: str) -> None:
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        self.history.append(f"{stamp} {entry}")
        self.updated_at = datetime.now(UTC)
