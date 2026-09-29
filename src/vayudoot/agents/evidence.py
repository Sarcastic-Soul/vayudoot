"""Stage 1: what does the submission show?

A report carries zero or more photographs. All of them go into one message as
separate Gemini inline-data parts, because they are angles on a single event and
the model has to reason across them rather than about each alone.

A report with no photograph at all is a supported path, not an error: a citizen
who cannot photograph safely — a fire at night, a vehicle already gone — still
has an observation worth classifying. The prompt handles that case and says what
a written account is worth compared to an image.

A voice note arrives here already heard, as a `VoiceAccount` in a block headed
as the reporter's claim (`agents/voice.spoken_account_block`). It is testimony
from the same person as the photograph, so it can make an account specific
enough to classify but can never be a second source. The prompt says so, and
`ACCOUNT_ONLY_CEILING` holds a report with no photograph to the written-account
ceiling in code as well, so a fluent voice note cannot talk a classification
past what testimony is worth.
"""

from __future__ import annotations

from pathlib import Path

from google.genai import types

from ..config import settings
from ..images import read_normalised
from ..models import Agent, build_model, media_part, text_part
from ..schemas import EvidencePacket, Report, VoiceAccount
from .prompts import EVIDENCE
from .voice import spoken_account_block

#: The most confidence a classification may carry when no photograph was read:
#: the top of the written-account band in `prompts.EVIDENCE`. Enforced here as
#: well as asked for there, because a spoken account is now the likeliest way a
#: report arrives without a photograph, and testimony read back fluently is still
#: testimony.
ACCOUNT_ONLY_CEILING = 0.8


def _image_part(path: Path) -> types.Part:
    # The format comes from the file's contents, not its name: a submission can
    # arrive as HEIC, TIFF or anything else a camera emits, and an extension is
    # only a claim. `read_normalised` converts whatever it finds into one of the
    # four formats every model reads.
    fmt, data = read_normalised(path)
    return media_part(data, f"image/{fmt}")


def build_evidence_agent() -> Agent:
    return Agent(
        name="evidence",
        model=build_model(temperature=0.0),
        system_prompt=EVIDENCE,
    )


async def analyse_evidence(
    report: Report, agent: Agent | None = None, voice: VoiceAccount | None = None
) -> EvidencePacket:
    agent = agent or build_evidence_agent()

    spoken = spoken_account_block(voice)
    prompt = (
        f"Citizen report submitted at {report.observed_at.isoformat()} "
        f"from {report.latitude}, {report.longitude}.\n"
        f"Citizen's note: {report.note or '(none provided)'}\n"
        + (f"\n{spoken}" if spoken else "")
        + "\nClassify what this report shows."
    )
    # The cap is enforced at intake, but a case can also be loaded from disk or
    # built by a script, so it is enforced again here: the cost of an extra image
    # is paid at this call and nowhere else.
    existing = [Path(p) for p in report.image_paths if Path(p).exists()]
    used = existing[: settings.vayudoot_max_images_per_report]

    if not used:
        prompt += (
            "\n\nNo photograph was attached. Classify from the citizen's account alone, and "
            "say in your reasoning that this rests on the citizen's description rather "
            "than on an image."
        )
    elif len(used) > 1:
        prompt += (
            f"\n\n{len(used)} photographs are attached. They are the citizen's angles on "
            "one event; read them together."
        )
    content = [text_part(prompt), *(_image_part(path) for path in used)]

    result = await agent.invoke_async(content, structured_output_model=EvidencePacket)
    packet: EvidencePacket = result.structured_output
    if not used and packet.confidence > ACCOUNT_ONLY_CEILING:
        packet.confidence = ACCOUNT_ONLY_CEILING
    return packet
