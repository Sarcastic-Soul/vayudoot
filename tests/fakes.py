"""Stand-in stage functions.

The pipeline's shape — ordering, checkpointing, the confidence floor, what a
failure leaves behind — is worth testing on every commit, and none of it needs a
model. These replace the four agent stages with deterministic ones so the whole
pipeline runs offline in milliseconds.
"""

from __future__ import annotations

from vayudoot.schemas import (
    AlertBrief,
    Complaint,
    Corroboration,
    EvidencePacket,
    ImageryAssessment,
    Jurisdiction,
    PollutionType,
    RTIApplication,
    VoiceAccount,
    VoiceHearing,
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


def alert_brief() -> AlertBrief:
    """What the fast-tier alert agent would return, minus the model."""
    return AlertBrief(
        subject="Satellite-detected burning, Ludhiana district, 2026-09-27",
        summary_en=(
            "Satellite thermal detections and an elevated PM2.5 reading place a pollution "
            "event within a 1.5 km radius in Ludhiana district. The instruments detect heat "
            "and polluted air; they do not show what is burning."
        ),
        summary_local="लुधियाना ज़िले में उपग्रह द्वारा आग का पता चला।",
        local_language="Punjabi",
        suggested_checks=[
            "Site visit to the area during the evening burn window.",
            "Check the nearest station's hourly PM2.5 record for the same period.",
        ],
    )


def imagery_assessment(plume: bool = True) -> ImageryAssessment:
    """What the primary-tier imagery agent would return, minus the model."""
    return ImageryAssessment(
        plume_visible=plume,
        cloud_obscured=False,
        description="A grey plume drawn out to the south-east over cultivated fields.",
        confidence=0.7,
    )


def voice_hearing(**overrides) -> VoiceHearing:
    """What the fast-tier voice agent would return for a Hindi note, minus the model.

    Deliberately left carrying a name in the translation and in `named_parties`,
    the way a model that half-follows the prompt answers, so that anything built
    from it has to go through `agents.voice.redact` to come out clean.
    """
    fields = {
        "heard_speech": True,
        "language": "Hindi",
        "language_code": "hi",
        "transcript": "स्कूल के पीछे वाली फैक्ट्री हर रात दस बजे के बाद प्लास्टिक जलाती है।",
        "translation_en": "The Sharma Plastics factory behind the school burns plastic every "
        "night after 10 pm.",
        "what_is_described": "Plastic burnt at a factory behind a school, nightly.",
        "pollution_type_hint": PollutionType.OPEN_WASTE_BURNING,
        "time_pattern": "every night after 10 pm",
        "duration": "about three months",
        "smells": ["burning plastic"],
        "health_effects": ["children coughing"],
        "confidence": 0.85,
        "named_parties": ["Sharma Plastics", "शर्मा"],
    }
    return VoiceHearing(**(fields | overrides))


def voice_account() -> VoiceAccount:
    """The stored account a pipeline test gets, already through the redactor."""
    from vayudoot.agents.voice import redact

    return redact(voice_hearing(), model="fake-flash-lite")


class StubAgent:
    """Stands in for a `models.Agent`.

    Records the prompt it was given, which is how a test can assert what a stage
    actually told the model, and answers with a fixed structured output.
    """

    def __init__(self, output):
        self.output = output
        self.prompts: list[str] = []

    async def invoke_async(self, prompt, structured_output_model=None, **kwargs):
        self.prompts.append(prompt)
        return type("Result", (), {"structured_output": self.output})()


def patch_stages(
    monkeypatch, module, *, confidence: float = 0.9, fail_at: str = "", fail_with=None
) -> None:
    """Replace the agent stages that `module` imported with deterministic ones.

    `fail_with` is an exception factory (no arguments) used instead of the
    default `RuntimeError` when `fail_at` names the failing stage — for tests
    that need a specific exception type, such as a provider rate limit, to
    reach the pipeline's failure handling.
    """

    async def _stage(name, value):
        if fail_at == name:
            raise (fail_with() if fail_with else RuntimeError(f"{name} exploded"))
        return value

    stages = {
        "analyse_evidence": ("evidence", lambda: evidence(confidence)),
        "corroborate": ("corroboration", corroboration),
        "resolve_jurisdiction": ("jurisdiction", jurisdiction),
        "draft_complaint": ("drafting", complaint),
        # Only reached when the report carries a voice note.
        "hear_voice_note": ("voice", voice_account),
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


class MemoryFirestore:
    """An in-memory stand-in for `firestore_store.Remote`, counting what it bills.

    Firestore charges per document read and per document written, and the Spark
    plan's daily allowance of both is what `firestore_store` is built around, so
    the counts are the thing its tests assert on. A query that matches nothing
    still costs one read, as it does on the real service.
    """

    def __init__(self) -> None:
        self.docs: dict[str, dict[str, dict]] = {}
        self.reads = 0
        self.writes = 0

    def _billed(self, found: dict[str, dict]) -> dict[str, dict]:
        self.reads += max(1, len(found))
        return {doc_id: dict(data) for doc_id, data in found.items()}

    def read_all(self, collection: str) -> dict[str, dict]:
        return self._billed(self.docs.get(collection, {}))

    def read_range(self, collection: str, field: str, low: str, high: str | None):
        return self._billed(
            {
                doc_id: data
                for doc_id, data in self.docs.get(collection, {}).items()
                if data.get(field, "") >= low and (high is None or data.get(field, "") < high)
            }
        )

    def write(self, collection: str, doc_id: str, data: dict) -> None:
        self.writes += 1
        self.docs.setdefault(collection, {})[doc_id] = dict(data)
