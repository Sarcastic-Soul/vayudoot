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
    RTIApplication,
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


def rti_application() -> RTIApplication:
    """What the RTI agent would return, minus the model.

    `body_en` is left empty on purpose: it is assembled by `agents.rti.render_rti`
    after the model answers, so a fake that filled it in would hide the renderer
    from every test that goes through the endpoint.
    """
    return RTIApplication(
        public_authority="Municipal Corporation of Delhi",
        pio_designation="The Public Information Officer",
        office_address="MCD Civic Centre, Minto Road, New Delhi",
        subject="Information on action taken on a complaint of open waste burning",
        preamble=(
            "A complaint of open waste burning was filed with your office and no reply has "
            "been received within the statutory window."
        ),
        questions=[
            "The reference number under which the said complaint was registered.",
            "The action taken report, if any, recorded against that complaint, with its date.",
            "The name and designation of the officer to whom the complaint was assigned.",
        ],
        fee_note="Application fee of Rs. 10, payable by [FEE INSTRUMENT].",
        appeal_note=(
            "First appeal under Section 19(1) to the First Appellate Authority of this "
            "public authority within thirty days."
        ),
        placeholders=["Applicant name", "Postal address", "Fee instrument"],
        body_local="",
        local_language="Hindi",
    )


class StubAgent:
    """Stands in for a Strands `Agent`.

    Records the prompt it was given, which is how a test can assert what a stage
    actually told the model, and answers with a fixed structured output.
    """

    def __init__(self, output):
        self.output = output
        self.prompts: list[str] = []

    async def invoke_async(self, prompt, structured_output_model=None, **kwargs):
        self.prompts.append(prompt)
        return type("Result", (), {"structured_output": self.output})()


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


def image_bytes(fmt: str = "PNG", size: tuple[int, int] = (24, 18), mode: str = "RGB") -> bytes:
    """A small real image. The API and the evidence stage both decode what they
    are given, so a handcrafted byte string is not good enough here."""
    import io

    from PIL import Image

    image = Image.new(mode, size, (120, 130, 140) if mode == "RGB" else (120, 130, 140, 255))
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()
