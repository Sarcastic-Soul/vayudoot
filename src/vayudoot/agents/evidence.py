"""Stage 1: what does the photograph show?"""

from __future__ import annotations

from pathlib import Path

from strands import Agent
from strands.types.content import ContentBlock

from ..models import build_model
from ..schemas import EvidencePacket, Report
from .prompts import EVIDENCE

_FORMATS = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".gif": "gif", ".webp": "webp"}


def _image_block(path: Path) -> ContentBlock:
    fmt = _FORMATS.get(path.suffix.lower())
    if fmt is None:
        raise ValueError(f"Unsupported image format: {path.suffix}")
    return {"image": {"format": fmt, "source": {"bytes": path.read_bytes()}}}


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
        "Classify what the photograph shows."
    )
    content: list[ContentBlock] = [{"text": prompt}]

    if report.image_path:
        path = Path(report.image_path)
        if path.exists():
            content.append(_image_block(path))
        else:
            content[0]["text"] += "\n\nNo photograph was attached; classify from the note alone."

    result = await agent.invoke_async(content, structured_output_model=EvidencePacket)
    return result.structured_output
