"""Stand-in stage functions.

The pipeline's shape — ordering, checkpointing, the confidence floor, what a
failure leaves behind — is worth testing on every commit, and none of it needs a
model. These replace the four agent stages with deterministic ones so the whole
pipeline runs offline in milliseconds.
"""

from __future__ import annotations

from vayudoot.schemas import (
    Complaint,
    Corroboration,
    EvidencePacket,
    Jurisdiction,
    PollutionType,
)


def evidence(confidence: float = 0.9) -> EvidencePacket:
    return EvidencePacket(
        pollution_type=PollutionType.OPEN_WASTE_BURNING,
        confidence=confidence,
        severity="high",
        visible_indicators=["dense black smoke", "smouldering refuse pile"],
        reasoning="Fake stage.",
    )


def corroboration() -> Corroboration:
    return Corroboration(
        corroborated=True,
        satellite_fire_detections=2,
        satellite_summary="Two VIIRS detections within 3 km.",
        air_quality_summary="PM2.5 elevated at the nearest station.",
        wind_speed_ms=2.4,
        wind_from_degrees=270.0,
        upwind_source_latitude=28.6139,
        upwind_source_longitude=77.1890,
        corroboration_notes="Fake stage.",
    )


def jurisdiction() -> Jurisdiction:
    return Jurisdiction(
        authority_name="Municipal Corporation of Delhi",
        authority_tier="municipal",
        office="MCD Civic Centre, Minto Road, New Delhi",
        email="mcd@example.invalid",
        statute="Solid Waste Management Rules, 2016",
        section="Rule 15",
        response_window_days=15,
        escalation_authority="Central Pollution Control Board",
        escalation_email="cpcb@example.invalid",
    )


def complaint() -> Complaint:
    return Complaint(
        subject="Open burning of waste at Minto Road",
        body_en="Body of the complaint.",
        body_local="शिकायत का मुख्य भाग।",
        local_language="Hindi",
        cited_statutes=["Solid Waste Management Rules, 2016, Rule 15"],
        requested_action="Inspection and a direction to stop.",
    )


def patch_stages(monkeypatch, module, *, confidence: float = 0.9, fail_at: str = "") -> None:
    """Replace the agent stages that `module` imported with deterministic ones."""

    async def _stage(name, value):
        if fail_at == name:
            raise RuntimeError(f"{name} exploded")
        return value

    stages = {
        "analyse_evidence": ("evidence", lambda: evidence(confidence)),
        "corroborate": ("corroboration", corroboration),
        "resolve_jurisdiction": ("jurisdiction", jurisdiction),
        "draft_complaint": ("drafting", complaint),
    }
    for attr, (name, factory) in stages.items():
        monkeypatch.setattr(
            module, attr, lambda *a, _n=name, _f=factory, **k: _stage(_n, _f())
        )
    monkeypatch.setattr(
        module, "reverse_geocode", lambda *a, **k: {"display_name": "Minto Road, New Delhi, Delhi"}
    )
