"""End-to-end demo run.

    uv run python scripts/demo.py path/to/photo.jpg 28.6139 77.2090

Requires a configured model provider. Prints every intermediate result so the
pipeline is inspectable rather than a black box.
"""

from __future__ import annotations

import asyncio
import sys
import uuid

from vayudoot import filing, store
from vayudoot.pipeline import run
from vayudoot.schemas import CaseStatus, Report


async def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 1

    image_path, lat, lon = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    note = sys.argv[4] if len(sys.argv) > 4 else ""

    report = Report(
        report_id=uuid.uuid4().hex,
        latitude=lat,
        longitude=lon,
        image_path=image_path,
        note=note,
    )

    case = await run(report)

    print(f"\nCase {case.case_id} — {case.status.value}")
    print(f"Location: {case.address or f'{lat}, {lon}'}\n")

    if case.evidence:
        e = case.evidence
        print(f"EVIDENCE      {e.pollution_type.value}  {e.severity}  confidence {e.confidence:.2f}")
        print(f"              {', '.join(e.visible_indicators) or 'no indicators recorded'}")
    if case.corroboration:
        c = case.corroboration
        print(f"CORROBORATION corroborated={c.corroborated}  "
              f"{c.satellite_fire_detections} satellite detection(s)")
        print(f"              {c.corroboration_notes}")
    if case.jurisdiction:
        j = case.jurisdiction
        print(f"JURISDICTION  {j.authority_name} ({j.authority_tier})")
        print(f"              {j.statute} — {j.section}")
    if case.complaint:
        print(f"COMPLAINT     {case.complaint.subject}\n")
        print(case.complaint.body_en)

    print("\nHISTORY")
    for line in case.history:
        print(f"  {line}")

    if case.status is CaseStatus.AWAITING_CONFIRMATION:
        answer = input("\nFile this complaint to the sandbox outbox? [y/N] ").strip().lower()
        if answer == "y":
            path = filing.file_complaint(case)
            store.save(case)
            print(f"Written to {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
