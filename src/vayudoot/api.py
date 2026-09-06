"""HTTP surface. Thin: it validates input, calls the pipeline, and returns cases.

A full pipeline run is minutes of model calls, which is far longer than a browser
will wait on a form submission. So `POST /reports` creates the case, starts the
run in the background, and answers immediately with a case id. The interface then
polls `GET /cases/{id}` and watches `stage` advance.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import filing, lifecycle, store
from .config import settings
from .images import UnsupportedImage, normalise, suffix_for
from .pipeline import new_case, run
from .ratelimit import limiter
from .schemas import Case, CaseStatus, Report
from .tools.authorities import authority_table
from .tools.geocode import reverse_geocode, search_places

log = logging.getLogger(__name__)

#: How long a note on a lifecycle transition may be. These are one-line records
#: of what happened — "site inspected, burning stopped" — not correspondence.
NOTE_MAX = 500


class NoteRequest(BaseModel):
    """A short free-text note attached to a lifecycle transition."""

    note: str = Field(default="", max_length=NOTE_MAX)


class AcknowledgeRequest(NoteRequest):
    """A note, plus when the authority actually responded.

    The date is optional and defaults to now. It matters because the escalation
    clock restarts from it: a letter dated last week should not buy the authority
    a fresh window starting from the day it was typed in.
    """

    responded_at: datetime | None = None

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
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

#: Read the upload in pieces, so an oversized file is refused partway through
#: rather than after it is all in memory.
_CHUNK = 64 * 1024

#: Multipart framing around the file itself: boundaries, headers, the other form
#: fields. Small, but the declared body length has to be allowed to exceed the
#: image limit by something or a file exactly at the limit would be refused.
_MULTIPART_OVERHEAD = 16 * 1024


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _running.add(task)
    task.add_done_callback(_running.discard)


@app.middleware("http")
async def refuse_an_oversized_body(request: Request, call_next):
    """Reject a body too large to be a photograph before it is parsed.

    Once the endpoint is entered the multipart parser has already consumed the
    whole request, so this is the only place a huge upload can be turned away
    without handling it. `Content-Length` is a claim, not proof, which is why the
    read in `_read_capped` counts the bytes as well.
    """
    declared = request.headers.get("content-length")
    limit = settings.vayudoot_max_upload_bytes
    oversized = declared and declared.isdigit() and int(declared) > limit + _MULTIPART_OVERHEAD
    if request.method == "POST" and oversized:
        return JSONResponse(status_code=413, content={"detail": _too_large(int(declared))})
    return await call_next(request)


def _too_large(size: int | None = None) -> str:
    limit_mb = settings.vayudoot_max_upload_bytes / (1024 * 1024)
    seen = f" That one is {size / (1024 * 1024):.1f} MB." if size else ""
    return (
        f"That photograph is too large. The limit is {limit_mb:.0f} MB.{seen} "
        "Most phones can send a smaller copy; a resized photograph is enough here, "
        "since the image is scaled down before it is read anyway."
    )


async def _read_capped(image: UploadFile) -> bytes:
    """Read an upload, refusing it the moment it goes past the limit."""
    limit = settings.vayudoot_max_upload_bytes
    if image.size is not None and image.size > limit:
        raise HTTPException(413, _too_large(image.size))

    chunks: list[bytes] = []
    total = 0
    while chunk := await image.read(_CHUNK):
        total += len(chunk)
        if total > limit:
            raise HTTPException(413, _too_large(total))
        chunks.append(chunk)
    return b"".join(chunks)


def _client_key(request: Request) -> str:
    """Who to count this request against.

    Behind a platform proxy the socket address is the proxy's, so the first hop
    in `X-Forwarded-For` is the client. It is a header and therefore forgeable —
    a determined caller can spread itself across made-up addresses — which is
    exactly why the global daily cap exists underneath the per-client one.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded.strip():
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "model_provider": settings.vayudoot_model_provider,
        "model_id": settings.model_id,
        "live_filing": settings.vayudoot_live_filing,
        "running_cases": len(_running),
        "rate_limited": limiter.enabled,
        # The day's remaining model budget, in reports. Published because an
        # exhausted budget is the likeliest reason a deployed instance stops
        # accepting reports, and it should not have to be guessed from a 429.
        "reports_remaining_today": limiter.remaining_today() if limiter.enabled else None,
        "reports_per_day": settings.vayudoot_reports_per_day if limiter.enabled else None,
        "max_upload_bytes": settings.vayudoot_max_upload_bytes,
    }


@app.post("/reports", response_model=Case, status_code=202)
async def submit_report(
    request: Request,
    latitude: float = Form(...),
    longitude: float = Form(...),
    note: str = Form(""),
    contact: str = Form(""),
    image: UploadFile | None = File(None),
) -> Case:
    """Accept a report and start the pipeline. Returns before the run finishes."""
    # Metered before anything else: this is the endpoint that spends the day's
    # model quota, and the cheapest refusal is the one made before any work.
    decision = limiter.check(_client_key(request))
    if not decision.allowed:
        raise HTTPException(
            429, decision.message, headers={"Retry-After": str(decision.retry_after_seconds)}
        )

    image_path = None
    if image is not None and image.filename:
        # Normalise at the door rather than at the model. Whatever the phone sent
        # is decoded here, so an unreadable file is a 415 the citizen can act on
        # instead of a case that fails four seconds later for no visible reason.
        try:
            image_format, data = normalise(await _read_capped(image))
        except UnsupportedImage as exc:
            raise HTTPException(415, f"That file could not be read as a photograph: {exc}") from exc

        uploads = settings.vayudoot_upload_dir
        uploads.mkdir(parents=True, exist_ok=True)
        image_path = uploads / f"{uuid.uuid4().hex}{suffix_for(image_format)}"
        image_path.write_bytes(data)

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


@app.get("/geocode")
def geocode(lat: float | None = None, lon: float | None = None, q: str = "") -> dict:
    """Resolve coordinates to an address, or a place name to coordinates.

    The interface needs both so that a citizen never has to see a coordinate. It
    is the same Nominatim service the pipeline uses, exposed for the map.
    """
    if q.strip():
        return {"results": search_places(q)}
    if lat is None or lon is None:
        raise HTTPException(400, "Provide either q, or both lat and lon")
    return reverse_geocode(lat, lon)


@app.get("/authorities")
def authorities() -> dict:
    """The jurisdiction table this instance is running on.

    Published deliberately. Jurisdiction is resolved from a fixed table, so its
    coverage is the honest limit of the system, and a citizen should be able to
    see whether their region is in it rather than discovering it from a case that
    quietly resolved to a placeholder.
    """
    return authority_table()


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
        raise HTTPException(409, _not_due(case))
    filing.escalate(case)
    store.save(case)
    return case


def _not_due(case: Case) -> str:
    """Why this case cannot be escalated, which is not always a matter of time."""
    if case.status not in filing.ESCALATION_CLOCK:
        return f"Case is {case.status.value}; only a filed or acknowledged case can be escalated"
    return "The statutory response window has not yet lapsed"


@app.post("/cases/{case_id}/acknowledge", response_model=Case)
def acknowledge_case(case_id: str, body: AcknowledgeRequest | None = None) -> Case:
    """Record that the authority responded.

    This does not close the case. An acknowledgement is a receipt, so the
    escalation clock restarts from the response date rather than stopping: an
    authority that replies and then does nothing is escalated a window later.
    """
    body = body or AcknowledgeRequest()
    case = _require(case_id)
    with _transition():
        lifecycle.acknowledge(case, note=body.note, at=body.responded_at)
    store.save(case)
    return case


@app.post("/cases/{case_id}/resolve", response_model=Case)
def resolve_case(case_id: str, body: NoteRequest | None = None) -> Case:
    """Close the case: the pollution stopped, or the authority acted."""
    body = body or NoteRequest()
    case = _require(case_id)
    with _transition():
        lifecycle.resolve(case, note=body.note)
    store.save(case)
    return case


@app.post("/cases/{case_id}/withdraw", response_model=Case)
def withdraw_case(case_id: str, body: NoteRequest | None = None) -> Case:
    """The citizen takes the complaint back. Nothing further is filed or chased."""
    body = body or NoteRequest()
    case = _require(case_id)
    with _transition():
        lifecycle.withdraw(case, note=body.note)
    store.save(case)
    return case


@contextmanager
def _transition():
    """A refused lifecycle transition is a 409, not a 500."""
    try:
        yield
    except lifecycle.InvalidTransition as exc:
        raise HTTPException(409, str(exc)) from exc


def _require(case_id: str) -> Case:
    case = store.load(case_id)
    if case is None:
        raise HTTPException(404, f"No such case: {case_id}")
    return case


# The interface is served by this same process: one deployment, one URL, no CORS.
# Mounted last so it cannot shadow an API route.
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
