"""Stage 1: what does the submission show?

A report carries zero or more photographs. All of them go into one message as
separate image content blocks, because they are angles on a single event and the
model has to reason across them rather than about each alone. The content block
shape is Bedrock's, which is what the Strands providers translate from:
`{"image": {"format": ..., "source": {"bytes": ...}}}`.

A report with no photograph at all is a supported path, not an error: a citizen
who cannot photograph safely — a fire at night, a vehicle already gone — still
has an observation worth classifying. The prompt handles that case and says what
a written account is worth compared to an image.
"""

from __future__ import annotations

from pathlib import Path

from strands import Agent
from strands.types.content import ContentBlock

from ..config import settings
from ..images import read_normalised
from ..models import build_model
from ..schemas import EvidencePacket, Report
from .prompts import EVIDENCE


def _image_block(path: Path) -> ContentBlock:
    # The format comes from the file's contents, not its name: a submission can
    # arrive as HEIC, TIFF or anything else a camera emits, and an extension is
    # only a claim. `read_normalised` converts whatever it finds into one of the
    # four formats a content block accepts.
    fmt, data = read_normalised(path)
    return {"image": {"format": fmt, "source": {"bytes": data}}}


def build_evidence_agent() -> Agent:
    return Agent(
        name="evidence",
        model=build_model(temperature=0.0),
        system_prompt=EVIDENCE,
        callback_handler=None,
    )


async def analyse_evidence(report: Report, agent: Agent | None = None) -> EvidencePacket:
    agent = agent or build_evidence_agent()

    prompt = (
        f"Citizen report submitted at {report.observed_at.isoformat()} "
        f"from {report.latitude}, {report.longitude}.\n"
        f"Citizen's note: {report.note or '(none provided)'}\n\n"
        "Classify what this report shows."
    )
    content: list[ContentBlock] = [{"text": prompt}]

    # The cap is enforced at intake, but a case can also be loaded from disk or
    # built by a script, so it is enforced again here: the cost of an extra image
    # block is paid at this call and nowhere else.
    existing = [Path(p) for p in report.image_paths if Path(p).exists()]
    used = existing[: settings.vayudoot_max_images_per_report]
    content.extend(_image_block(path) for path in used)

    if not used:
        content[0]["text"] += (
            "\n\nNo photograph was attached. Classify from the written account alone, and "
            "say in your reasoning that this rests on the citizen's description rather "
            "than on an image."
        )
    elif len(used) > 1:
        content[0]["text"] += (
            f"\n\n{len(used)} photographs are attached. They are the citizen's angles on "
            "one event; read them together."
        )

    result = await agent.invoke_async(content, structured_output_model=EvidencePacket)
    return result.structured_output
