"""HTTP surface. Thin: it validates input, calls the pipeline, and returns cases."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from . import filing, store
from .config import settings
from .pipeline import run
from .schemas import Case, CaseStatus, Report

app = FastAPI(
    title="Vayudoot",
    description="An agent that takes a citizen pollution report from photo to filed, "
    "tracked, escalated complaint.",
    version="0.1.0",
)

UPLOADS = Path("./data/uploads")


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "model_provider": settings.vayudoot_model_provider,
        "model_id": settings.model_id,
        "live_filing": settings.vayudoot_live_filing,
    }


@app.post("/reports", response_model=Case)
async def submit_report(
    latitude: float = Form(...),
    longitude: float = Form(...),
    note: str = Form(""),
    contact: str = Form(""),
    image: UploadFile | None = File(None),
) -> Case:
    image_path = None
    if image is not None and image.filename:
        UPLOADS.mkdir(parents=True, exist_ok=True)
        suffix = Path(image.filename).suffix or ".jpg"
        image_path = UPLOADS / f"{uuid.uuid4().hex}{suffix}"
        with image_path.open("wb") as fh:
            shutil.copyfileobj(image.file, fh)

    report = Report(
        report_id=uuid.uuid4().hex,
        latitude=latitude,
        longitude=longitude,
        note=note,
        reporter_contact=contact,
        image_path=str(image_path) if image_path else None,
    )
    return await run(report)


@app.get("/cases", response_model=list[Case])
def list_cases() -> list[Case]:
    return store.all_cases()


@app.get("/cases/{case_id}", response_model=Case)
def get_case(case_id: str) -> Case:
    case = store.load(case_id)
    if case is None:
        raise HTTPException(404, f"No such case: {case_id}")
    return case


@app.post("/cases/{case_id}/confirm", response_model=Case)
def confirm_and_file(case_id: str) -> Case:
    """The human-in-the-loop gate. Nothing is filed until a person confirms."""
    case = store.load(case_id)
    if case is None:
        raise HTTPException(404, f"No such case: {case_id}")
    if case.status is not CaseStatus.AWAITING_CONFIRMATION:
        raise HTTPException(409, f"Case is {case.status.value}, not awaiting confirmation")
    filing.file_complaint(case)
    store.save(case)
    return case


@app.post("/cases/{case_id}/escalate", response_model=Case)
def escalate_case(case_id: str) -> Case:
    case = store.load(case_id)
    if case is None:
        raise HTTPException(404, f"No such case: {case_id}")
    if not filing.escalation_due(case):
        raise HTTPException(409, "The statutory response window has not yet lapsed")
    filing.escalate(case)
    store.save(case)
    return case
