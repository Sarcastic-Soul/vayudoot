"""HTTP surface. Thin: it validates input, calls the pipeline, and returns cases.

A full pipeline run is minutes of model calls, which is far longer than a browser
will wait on a form submission. So `POST /reports` creates the case, starts the
run in the background, and answers immediately with a case id. The interface then
polls `GET /cases/{id}` and watches `stage` advance.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import filing, store
from .config import settings
from .pipeline import new_case, run
from .schemas import Case, CaseStatus, Report

log = logging.getLogger(__name__)

app = FastAPI(
    title="Vayudoot",
    description="An agent that takes a citizen pollution report from photo to filed, "
    "tracked, escalated complaint.",
    version="0.1.0",
)

WEB_DIR = Path(__file__).resolve().parent / "web"

# asyncio only holds a weak reference to a running task, so a task that nothing
# else references can be garbage collected mid-run. Keep them until they finish.
_running: set[asyncio.Task] = set()

_IMAGE_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _running.add(task)
    task.add_done_callback(_running.discard)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "model_provider": settings.vayudoot_model_provider,
        "model_id": settings.model_id,
        "live_filing": settings.vayudoot_live_filing,
        "running_cases": len(_running),
    }


@app.post("/reports", response_model=Case, status_code=202)
async def submit_report(
    latitude: float = Form(...),
    longitude: float = Form(...),
    note: str = Form(""),
    contact: str = Form(""),
    image: UploadFile | None = File(None),
) -> Case:
    """Accept a report and start the pipeline. Returns before the run finishes."""
    image_path = None
    if image is not None and image.filename:
        uploads = settings.vayudoot_upload_dir
        uploads.mkdir(parents=True, exist_ok=True)
        suffix = Path(image.filename).suffix.lower()
        if suffix not in _IMAGE_MEDIA_TYPES:
            suffix = ".jpg"
        image_path = uploads / f"{uuid.uuid4().hex}{suffix}"
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

    case = new_case(report)
    case.log("Report received")
    store.save(case)
    _spawn(run(report, case=case))
    return case


@app.get("/cases", response_model=list[Case])
def list_cases() -> list[Case]:
    return store.all_cases()


@app.get("/cases/{case_id}", response_model=Case)
def get_case(case_id: str) -> Case:
    return _require(case_id)


@app.get("/cases/{case_id}/photo")
def get_case_photo(case_id: str) -> FileResponse:
    """Serve the submitted photograph, and only from the uploads directory."""
    case = _require(case_id)
    if not case.report.image_path:
        raise HTTPException(404, "This report has no photograph")

    path = Path(case.report.image_path).resolve()
    uploads = settings.vayudoot_upload_dir.resolve()
    if uploads not in path.parents or not path.exists():
        raise HTTPException(404, "Photograph is no longer available")

    media_type = _IMAGE_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type)


@app.get("/cases/{case_id}/envelope", response_class=PlainTextResponse)
def get_case_envelope(case_id: str) -> str:
    """The filed envelope exactly as it was written to the sandbox outbox."""
    case = _require(case_id)
    if case.status not in (CaseStatus.FILED, CaseStatus.ESCALATED):
        raise HTTPException(409, f"Case is {case.status.value}; nothing has been filed")

    escalated = case.status is CaseStatus.ESCALATED
    name = f"{case.case_id}-escalated.eml" if escalated else f"{case.case_id}.eml"
    path = settings.vayudoot_sandbox_outbox / name
    if not path.exists():
        raise HTTPException(404, f"No envelope in the outbox for {case.case_id}")
    return path.read_text()


@app.post("/cases/{case_id}/confirm", response_model=Case)
def confirm_and_file(case_id: str) -> Case:
    """The human-in-the-loop gate. Nothing is filed until a person confirms."""
    case = _require(case_id)
    if case.status is not CaseStatus.AWAITING_CONFIRMATION:
        raise HTTPException(409, f"Case is {case.status.value}, not awaiting confirmation")
    filing.file_complaint(case)
    store.save(case)
    return case


@app.post("/cases/{case_id}/escalate", response_model=Case)
def escalate_case(case_id: str) -> Case:
    case = _require(case_id)
    if not filing.escalation_due(case):
        raise HTTPException(409, "The statutory response window has not yet lapsed")
    filing.escalate(case)
    store.save(case)
    return case


def _require(case_id: str) -> Case:
    case = store.load(case_id)
    if case is None:
        raise HTTPException(404, f"No such case: {case_id}")
    return case


# The interface is served by this same process: one deployment, one URL, no CORS.
# Mounted last so it cannot shadow an API route.
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
