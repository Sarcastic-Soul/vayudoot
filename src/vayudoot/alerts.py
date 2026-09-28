"""Alerting the responsible authority about a hotspot.

The brief asks the platform to "alert relevant authorities for rapid
intervention", and until this module the only route to an authority was a
citizen's complaint. A hotspot the satellites and stations found on their own —
the case the v0.3 reframe exists for — had no way to reach anyone.

This is that route, and three rules shape it.

**Only a corroborated hotspot can be alerted.** An alert is an outward claim
about a place, made in the system's own name, and hard constraint 7 says
corroboration gates any such claim. A hotspot resting only on citizen reports
already has an outward route — the citizen's own complaint, in their own name,
through the reporting pipeline — and that is the right one for it. Without this
gate, coordinated false reports would turn into an official-looking alert.

**Jurisdiction is a table lookup, so no model does it.** Reverse geocoding
gives the state and city; `lookup_authority` maps them to an authority. The
pipeline's jurisdiction stage wraps the same two tools in an agent because it
began that way; here there is nothing to judge, and spending a model call to
read a JSON table would be spending quota on arithmetic. A hotspot whose centre
is outside India is refused rather than resolved: the table holds Indian
authorities only, and the generic fallback would address a Pakistani or
Nepalese fire to an Indian state board placeholder. Such a hotspot reaches its
own country through this node's federation feed instead.

**The facts are Python; only the summary is the model's.** `facts_block`
renders the area, confidence, corroboration, severity, dates, per-source signal
counts, exposure and any imagery reading deterministically, and the same text
goes into the envelope. The model writes a subject, a few sentences in English
and the region's language, and a list of checks for an inspector — on the fast
tier, because it summarises text it was handed.

Nothing is sent from here. `draft_alert` stops at `awaiting_confirmation`, and
the API's confirm route is the only caller of `filing.file_alert`, which writes
to the sandbox outbox or raises. Hard constraints 1 and 2.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from . import store
from .agents.alert import write_alert_brief
from .schemas import (
    AlertStatus,
    Hotspot,
    HotspotAlert,
    HotspotSnapshot,
    ImageryReading,
    Jurisdiction,
    PollutionType,
    SignalSource,
)
from .tools.authorities import coverage_is_generic, lookup_authority
from .tools.geocode import reverse_geocode

#: Country codes this node holds authorities for. The authority table is
#: Indian, and a country outside it has its own regulators, reached through
#: federation rather than invented here.
SERVED_COUNTRIES: frozenset[str] = frozenset({"in"})

#: How each source is named in a facts block, in the order they are listed.
#: Instruments first, because they are what made the hotspot alertable.
SOURCE_LABELS: dict[SignalSource, str] = {
    SignalSource.SATELLITE: "satellite thermal detections (NASA FIRMS VIIRS)",
    SignalSource.GROUND_STATION: "ground station readings above the Indian standard",
    SignalSource.CITIZEN_REPORT: "citizen photograph reports",
    SignalSource.CITIZEN_SENSOR: "citizen low-cost sensor readings",
}

#: How many signal lines the facts block lists. The counts cover the rest; an
#: officer deciding whether to send an inspector needs a sample, not a dump.
MAX_EVIDENCE_LINES = 8


class AlertRefused(Exception):
    """An alert that must not be drafted, with the HTTP status that says why."""

    status_code = 409


class NotCorroborated(AlertRefused):
    status_code = 409


class OutsideJurisdiction(AlertRefused):
    status_code = 422


class JurisdictionUnavailable(AlertRefused):
    """Reverse geocoding failed, so there is no honest answer to "who"."""

    status_code = 502


def check_alertable(hotspot: Hotspot) -> None:
    """Refuse a hotspot that no independent instrument supports."""
    if not hotspot.corroborated:
        raise NotCorroborated(
            f"Hotspot {hotspot.hotspot_id} is not corroborated: every signal behind it came "
            "from the public, and no satellite or ground station agrees. An alert is a claim "
            "made in this system's name, and hard constraint 7 gates any such claim on "
            "independent evidence. The citizens who reported it can file their own complaint "
            "through the reporting pipeline; an alert becomes available if an instrument "
            "confirms it."
        )


def resolve_jurisdiction(hotspot: Hotspot) -> tuple[Jurisdiction, dict]:
    """The authority for the hotspot's centre, and the geocoder's answer.

    Deterministic: the two tools called directly, no model in between.
    """
    geo = reverse_geocode(hotspot.centre_latitude, hotspot.centre_longitude)
    if not isinstance(geo, dict) or "error" in geo:
        reason = geo.get("error") if isinstance(geo, dict) else "no answer"
        raise JurisdictionUnavailable(
            f"Could not place hotspot {hotspot.hotspot_id} in an administrative region, so "
            f"the responsible authority cannot be resolved: {reason}. Try again shortly."
        )

    country_code = str(geo.get("country_code", "")).strip().lower()
    if country_code not in SERVED_COUNTRIES:
        where = geo.get("country") or "no country the geocoder could name"
        raise OutsideJurisdiction(
            f"Hotspot {hotspot.hotspot_id} is centred in {where}, outside the jurisdiction "
            "this node holds authorities for. It will not invent one: the hotspot is "
            "published on this node's federation feed (/feed, /feed.geojson), which is how "
            "the authorities of that country reach it."
        )

    category = (
        "default"
        if hotspot.pollution_type is PollutionType.UNCLEAR
        else hotspot.pollution_type.value
    )
    found = lookup_authority(
        state=geo.get("state", ""), city=geo.get("city", ""), pollution_type=category
    )
    jurisdiction = Jurisdiction(
        **{k: v for k, v in found.items() if k in Jurisdiction.model_fields},
        reasoning=(
            "Resolved deterministically: reverse geocoding of the hotspot centre, then the "
            f"authority table for category '{category}'. No model was involved."
        ),
    )
    # The same backstop the pipeline applies: an address that only exists in
    # the generic entry means the region was absent, whatever else was said.
    if coverage_is_generic(jurisdiction.email):
        jurisdiction.coverage = "generic"
    return jurisdiction, geo


def area_label(geo: dict) -> str:
    """The area in words: city, district, state. Never the street.

    Nominatim answers with the nearest building at the zoom the pipeline uses,
    and an alert that names a building is an accusation against whoever is in
    it. The suburb is left out for the same reason — at this radius it can be
    an industrial estate's own name. Constraint 7.
    """
    parts: list[str] = []
    for key in ("city", "district", "state"):
        value = str(geo.get(key, "")).strip()
        if value and value not in parts:
            parts.append(value)
    return ", ".join(parts)


def facts_block(
    snapshot: HotspotSnapshot,
    area: str,
    hotspot: Hotspot | None = None,
    imagery: ImageryReading | None = None,
) -> str:
    """The alert's facts, rendered the same way every time.

    Built in Python rather than written by the model so that nothing in it can
    be embellished, and so the envelope an authority receives says exactly what
    the stored alert says. `hotspot` is optional and only supplies a sample of
    the signals behind the snapshot; everything else comes from the snapshot.
    """
    s = snapshot
    lat_dir = "N" if s.centre_latitude >= 0 else "S"
    lon_dir = "E" if s.centre_longitude >= 0 else "W"
    kind = (
        "unclear — instruments detect heat and polluted air, not what is burning"
        if s.pollution_type is PollutionType.UNCLEAR
        else s.pollution_type.value.replace("_", " ")
    )
    corroboration = (
        "yes — at least one satellite or ground station signal supports it"
        if s.corroborated
        else "no — citizen signals only"
    )

    lines = [
        f"Hotspot reference: {s.hotspot_id}",
        f"Area: a circle of radius {s.radius_km:.1f} km centred on "
        f"{abs(s.centre_latitude):.4f} {lat_dir}, {abs(s.centre_longitude):.4f} {lon_dir}"
        + (f", in {area}" if area else "")
        + ".",
        "  This describes an area. It is not the location of any one site or premises.",
        f"Pollution type: {kind}",
        f"Severity: {s.severity}",
        f"Confidence: {s.confidence:.2f} of 1",
        f"Independently corroborated: {corroboration}",
        f"First seen: {s.first_seen_at.isoformat(timespec='minutes')}",
        f"Last seen: {s.last_seen_at.isoformat(timespec='minutes')}",
        f"Span: {s.span_days} day(s)",
        f"Signals: {s.signal_count} in total",
    ]
    for source, label in SOURCE_LABELS.items():
        count = s.source_counts.get(source, 0)
        if count:
            lines.append(f"  {label}: {count}")

    if hotspot is not None:
        evidence = _evidence_lines(hotspot)
        if evidence:
            lines.append("Most recent instrument signals:")
            lines.extend(f"  {line}" for line in evidence)

    if s.exposure is not None:
        e = s.exposure
        towns = f"; largest: {', '.join(e.towns[:5])}" if e.towns else ""
        lines.append(
            f"Population within {e.radius_km:.0f} km: about {e.population:,} "
            f"({e.settlement_count} settlement(s) counted{towns}). A coarse figure: "
            "villages under 15,000 people are not counted and a town counts whole."
        )
    else:
        lines.append("Population nearby: not estimated.")

    if imagery is not None:
        lines.extend(
            [
                f"Satellite image reading ({imagery.image_date}, {imagery.layer}):",
                (
                    f"  Smoke plume visible: {'yes' if imagery.plume_visible else 'no'}; "
                    f"cloud over the area: {'yes' if imagery.cloud_obscured else 'no'}; "
                    f"confidence {imagery.confidence:.2f}."
                ),
                f"  {imagery.description}",
                (
                    "  A model's reading of a coarse image, included as context. It is not a "
                    "measurement and does not count towards corroboration."
                ),
            ]
        )
    return "\n".join(lines)


def _evidence_lines(hotspot: Hotspot) -> list[str]:
    """A sample of the instrument signals, newest first.

    Instrument signals only. A citizen signal's summary can carry what a person
    typed — a sensor id they chose — and the counts above already say how many
    citizens contributed.
    """
    instruments = [s for s in hotspot.signals if s.is_independent]
    newest = sorted(instruments, key=lambda s: _aware(s.observed_at), reverse=True)
    return [
        f"{s.observed_at.isoformat(timespec='minutes')} {s.summary or s.source.value}"
        for s in newest[:MAX_EVIDENCE_LINES]
    ]


def _aware(moment: datetime) -> datetime:
    """Signals from different sources do not all state a zone; sorting needs one."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def pending_for(hotspot_id: str) -> HotspotAlert | None:
    """An alert for this hotspot still waiting on a person, if there is one."""
    return next(
        (
            a
            for a in store.all_alerts()
            if a.hotspot_id == hotspot_id and a.status is AlertStatus.AWAITING_CONFIRMATION
        ),
        None,
    )


async def draft_alert(hotspot: Hotspot, agent=None) -> HotspotAlert:
    """Draft an alert for a hotspot and hold it for confirmation.

    Raises `AlertRefused` (with its HTTP status) for a hotspot that must not be
    alerted. Nothing is written until the model has answered, so a failed call
    leaves no half-drafted alert behind.
    """
    check_alertable(hotspot)
    jurisdiction, geo = resolve_jurisdiction(hotspot)
    area = area_label(geo)
    snapshot = HotspotSnapshot.of(hotspot)
    imagery = store.latest_imagery(hotspot.hotspot_id)
    facts = facts_block(snapshot, area, hotspot=hotspot, imagery=imagery)

    brief = await write_alert_brief(facts, jurisdiction, geo.get("state", ""), agent=agent)

    alert = HotspotAlert(
        alert_id=f"VDA-{uuid.uuid4().hex[:8].upper()}",
        hotspot_id=hotspot.hotspot_id,
        hotspot=snapshot,
        area=area,
        jurisdiction=jurisdiction,
        facts=facts,
        imagery=imagery,
        brief=brief,
    )
    alert.log(f"Drafted for {jurisdiction.authority_name} ({jurisdiction.coverage} match)")
    if jurisdiction.coverage != "exact":
        alert.log(
            f"Authority match is {jurisdiction.coverage}: "
            f"{jurisdiction.coverage_note or 'not an exact entry in the authority table'}"
        )
    alert.status = AlertStatus.AWAITING_CONFIRMATION
    alert.log("Awaiting confirmation before anything is sent")
    store.save_alert(alert)
    return alert


def render_body(alert: HotspotAlert) -> str:
    """The envelope body: the summary, the checks, the facts, and a plain footer."""
    brief = alert.brief
    parts: list[str] = []
    if brief is not None:
        parts.append(brief.summary_en.strip())
        if brief.suggested_checks:
            parts.append(
                "Suggested verification steps:\n"
                + "\n".join(f"  {i}. {check}" for i, check in enumerate(brief.suggested_checks, 1))
            )
    parts.append("FACTS\n" + alert.facts)
    if brief is not None and brief.summary_local.strip():
        parts.append(f"{brief.local_language or 'Local language'}:\n{brief.summary_local.strip()}")
    parts.append(
        "This alert was generated by Vayudoot from public satellite, ground station and "
        "citizen data, and confirmed by a person before sending. It describes conditions in "
        "an area and does not identify or accuse any party. The summary above the facts is "
        "model-written; the facts are not."
    )
    return "\n\n".join(parts)
