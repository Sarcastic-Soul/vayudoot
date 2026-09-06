"""The public case register: a filed complaint as a visible, shareable record.

A case is already deep-linkable. The accountability value of this project comes
from a complaint being something other people can see — a register is what turns
one citizen's report into a record an authority can be asked about.

That makes this the one part of the system with a real privacy risk, so two
decisions are load-bearing.

Who is in it
------------
Only cases that were actually filed: `filed`, `acknowledged`, `escalated`,
`resolved`. Filing is the moment a human confirmed the draft and the complaint
became a formal approach to a public authority, which is the act worth
publishing. Everything else stays out, and each exclusion is a different reason:

- `draft` and `awaiting_confirmation` were never confirmed by anyone. Publishing
  a complaint the citizen has not yet agreed to send is publishing a machine's
  opinion about a place under their name.
- `rejected` fell below the classification confidence floor. The photograph did
  not support a complaint, and a public record saying otherwise is a smear.
- `failed` died mid-run and may hold nothing but a stack trace.
- `withdrawn` is the citizen taking the complaint back, which is a revocation of
  exactly the consent the register runs on. A withdrawn case leaves the register
  even though it was once filed.

`resolved` stays in deliberately: an outcome is the most useful thing a register
can carry, and dropping closed cases would make the record look like nothing is
ever fixed.

What is in it
-------------
An allowlist, not a denylist. `PublicCase` and the models around it name every
field that may be published, and `project()` fills them one at a time. A field
added to `Case` or `Report` later is therefore private until somebody adds it
here on purpose — which is the property a denylist cannot give you, because
nobody remembers to update a list of removals.

The models live in this file rather than in `schemas.py` on purpose. The
allowlist is only reviewable if the field list and the code that fills it can be
read side by side.

Three things are worth saying about specific omissions:

- `report.reporter_contact` is the obvious one, and never appears. `_scrub`
  is a second line behind the allowlist: it strips the contact string out of the
  projected free text as well, because the complaint body is written by a model
  that was shown the citizen's note and a note can contain a phone number.
- `report.note` is the citizen's own free text, unreviewed, and routinely
  contains "call me on ..." or a house number. It is not projected.
- The lifecycle notes (`response_note`, `resolution_note`, `withdrawal_note`)
  are free text typed after filing and can name an individual officer or a
  neighbour. The dates carry the accountability signal on their own: filed on
  this day, answered on that one, closed on a third.

Authority email addresses are also left out. They are reserved placeholders in
this instance, and publishing a placeholder as if it were a filing address
invites somebody to use it.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from . import store
from .schemas import Case, CaseStatus, PollutionType, Stage

#: The statuses a case is published under. See the module docstring for why each
#: of the others is absent; changing this set is a policy decision.
PUBLIC_STATUSES: frozenset[CaseStatus] = frozenset(
    {
        CaseStatus.FILED,
        CaseStatus.ACKNOWLEDGED,
        CaseStatus.ESCALATED,
        CaseStatus.RESOLVED,
    }
)

#: Shortest contact string `_scrub` will search for. A two-character contact
#: would match inside ordinary words and blank half the complaint, and the
#: allowlist is the real protection; this pass is the backstop behind it.
MIN_SCRUBBABLE = 4


class PublicEvidence(BaseModel):
    """What the report showed. `landmarks` is not published.

    Landmarks are the one evidence field that can carry a name off a signboard,
    and naming a responsible party from a photograph is a permanent non-goal of
    this project. The address already says where this is.
    """

    pollution_type: PollutionType
    confidence: float
    severity: str
    visible_indicators: list[str] = Field(default_factory=list)
    reasoning: str = ""


class PublicCorroboration(BaseModel):
    """Independent sensor evidence. Machine readings; no personal data in any of it."""

    corroborated: bool
    air_quality_summary: str = ""
    nearest_station_km: float | None = None
    dominant_pollutant: str | None = None
    satellite_fire_detections: int = 0
    satellite_summary: str = ""
    wind_speed_ms: float | None = None
    wind_from_degrees: float | None = None
    corroboration_notes: str = ""


class PublicJurisdiction(BaseModel):
    """Who the complaint went to, and under what. Email addresses are omitted."""

    authority_name: str
    authority_tier: str
    office: str = ""
    statute: str
    section: str = ""
    response_window_days: int
    escalation_authority: str = ""
    coverage: str = "exact"
    coverage_note: str = ""


class PublicComplaint(BaseModel):
    """The complaint as filed, in both languages."""

    subject: str
    body_en: str
    body_local: str = ""
    local_language: str = ""
    cited_statutes: list[str] = Field(default_factory=list)
    requested_action: str = ""


class PublicCase(BaseModel):
    """One case as the register publishes it.

    Every field here was added deliberately. Nothing is copied wholesale from
    `Case`, and no `**case.model_dump()` may ever appear in `project()`.
    """

    case_id: str
    status: CaseStatus
    stage: Stage
    address: str = ""
    latitude: float
    longitude: float
    observed_at: datetime
    #: How many photographs the complaint was filed with. The pictures themselves
    #: are served by the register endpoint; the count is here so a reader knows
    #: how many to ask for.
    photograph_count: int = 0
    cluster_id: str = ""
    filed_at: datetime | None = None
    acknowledged_at: datetime | None = None
    escalated_at: datetime | None = None
    resolved_at: datetime | None = None
    evidence: PublicEvidence | None = None
    corroboration: PublicCorroboration | None = None
    jurisdiction: PublicJurisdiction | None = None
    complaint: PublicComplaint | None = None


def is_public(case: Case) -> bool:
    """Whether this case appears in the register at all."""
    return case.status in PUBLIC_STATUSES


def project(case: Case) -> PublicCase:
    """Build the public view of a case, field by named field."""
    report = case.report
    public = PublicCase(
        case_id=case.case_id,
        status=case.status,
        stage=case.stage,
        address=case.address,
        latitude=report.latitude,
        longitude=report.longitude,
        observed_at=report.observed_at,
        photograph_count=len(report.image_paths),
        cluster_id=case.cluster_id,
        filed_at=case.filed_at,
        acknowledged_at=case.acknowledged_at,
        escalated_at=case.escalated_at,
        resolved_at=case.resolved_at,
        evidence=_evidence(case),
        corroboration=_corroboration(case),
        jurisdiction=_jurisdiction(case),
        complaint=_complaint(case),
    )
    return _scrub(public, report.reporter_contact)


def register() -> list[PublicCase]:
    """Every publishable case, most recently filed first."""
    published = [case for case in store.all_cases() if is_public(case)]
    published.sort(key=lambda c: (c.filed_at or c.created_at), reverse=True)
    return [project(case) for case in published]


def public_case(case_id: str) -> PublicCase | None:
    """One publishable case, or None if there is no such public case.

    A case that exists but is not publishable is indistinguishable from one that
    does not exist. That is deliberate: the register must not confirm that a
    withdrawn or rejected complaint was ever made.
    """
    case = store.load(case_id)
    if case is None or not is_public(case):
        return None
    return project(case)


def _evidence(case: Case) -> PublicEvidence | None:
    if case.evidence is None:
        return None
    return PublicEvidence(
        pollution_type=case.evidence.pollution_type,
        confidence=case.evidence.confidence,
        severity=case.evidence.severity,
        visible_indicators=list(case.evidence.visible_indicators),
        reasoning=case.evidence.reasoning,
    )


def _corroboration(case: Case) -> PublicCorroboration | None:
    if case.corroboration is None:
        return None
    source = case.corroboration
    return PublicCorroboration(
        corroborated=source.corroborated,
        air_quality_summary=source.air_quality_summary,
        nearest_station_km=source.nearest_station_km,
        dominant_pollutant=source.dominant_pollutant,
        satellite_fire_detections=source.satellite_fire_detections,
        satellite_summary=source.satellite_summary,
        wind_speed_ms=source.wind_speed_ms,
        wind_from_degrees=source.wind_from_degrees,
        corroboration_notes=source.corroboration_notes,
    )


def _jurisdiction(case: Case) -> PublicJurisdiction | None:
    if case.jurisdiction is None:
        return None
    source = case.jurisdiction
    return PublicJurisdiction(
        authority_name=source.authority_name,
        authority_tier=source.authority_tier,
        office=source.office,
        statute=source.statute,
        section=source.section,
        response_window_days=source.response_window_days,
        escalation_authority=source.escalation_authority,
        coverage=source.coverage,
        coverage_note=source.coverage_note,
    )


def _complaint(case: Case) -> PublicComplaint | None:
    if case.complaint is None:
        return None
    source = case.complaint
    return PublicComplaint(
        subject=source.subject,
        body_en=source.body_en,
        body_local=source.body_local,
        local_language=source.local_language,
        cited_statutes=list(source.cited_statutes),
        requested_action=source.requested_action,
    )


def _scrub(public: PublicCase, contact: str) -> PublicCase:
    """Remove the reporter's contact from every projected string.

    The allowlist already excludes the contact field itself. This exists because
    the complaint body is written by a model that was shown the citizen's note,
    and a note that reads "burning behind our lane, call me on 98xxxxxxxx" can
    put the contact into prose that is otherwise publishable.
    """
    needle = contact.strip()
    if len(needle) < MIN_SCRUBBABLE:
        return public

    pattern = re.compile(re.escape(needle), re.IGNORECASE)
    cleaned = _walk(public.model_dump(), pattern)
    return PublicCase.model_validate(cleaned)


def _walk(value: Any, pattern: re.Pattern[str]) -> Any:
    if isinstance(value, str):
        return pattern.sub("[contact withheld]", value)
    if isinstance(value, dict):
        return {key: _walk(item, pattern) for key, item in value.items()}
    if isinstance(value, list):
        return [_walk(item, pattern) for item in value]
    return value
