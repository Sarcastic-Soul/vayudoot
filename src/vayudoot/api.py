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
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import (
    clustering,
    corridors,
    errors,
    federation,
    filing,
    hotspots,
    lifecycle,
    pack,
    register,
    scan,
    store,
)
from .agents import draft_rti_application, forecast_corridor, forecast_location
from .config import settings
from .images import UnsupportedImage, normalise, suffix_for
from .pipeline import new_case, run
from .ratelimit import limiter
from .schemas import (
    AirQualityForecast,
    Case,
    CaseStatus,
    Cluster,
    Corridor,
    CorridorForecast,
    Hotspot,
    HotspotFeed,
    NodeIdentity,
    Report,
    SensorReading,
    Signal,
    SignalSource,
)
from .tools.authorities import authority_table
from .tools.geocode import reverse_geocode, search_places

log = logging.getLogger(__name__)

# The citizen's own email or phone. It is needed server-side — the RTI names an
# applicant, clustering counts distinct reporters — but it has no business
# leaving the process. There is no login here by design, so `GET /cases` is
# world-readable: without this, one unauthenticated request returns every
# contact ever submitted. Applied to every route that returns a Case, and
# `test_no_case_route_leaks_the_reporter_contact` fails when a new one forgets.
CASE_EXCLUDE: dict = {"report": {"reporter_contact"}}
CASE_LIST_EXCLUDE: dict = {"__all__": CASE_EXCLUDE}



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

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Run the signal scan on a timer, if it has been switched on.

    Off by default and gated on `vayudoot_scan_enabled`, deliberately: this is a
    loop calling two external APIs unattended, and it should start because
    somebody watching the quota decided so, not because the process booted.

    Note what this is not. `docs/SCOPE.md` keeps automatic *escalation* out of
    scope because an unsupervised process acting on a legal deadline is a
    different class of risk. Scanning has no such property — it fetches public
    observations and writes them to a store. Nothing is filed, nothing is sent,
    and hard constraint 2 still holds: a human confirms before anything is filed.
    """
    task: asyncio.Task | None = None
    if settings.vayudoot_scan_enabled:
        task = asyncio.create_task(_scan_loop())
        _running.add(task)
        task.add_done_callback(_running.discard)
    try:
        yield
    finally:
        if task is not None:
            task.cancel()


async def _scan_loop() -> None:
    interval = max(settings.vayudoot_scan_interval_minutes, 1) * 60
    while True:
        try:
            # The scan is blocking HTTP; a thread keeps it off the event loop.
            summary = await asyncio.to_thread(scan.run_once)
            log.info("scan complete: %s", summary)
        except asyncio.CancelledError:
            raise
        except Exception:  # A failed scan must not end the loop.
            log.exception("scan failed; continuing")
        await asyncio.sleep(interval)


app = FastAPI(
    lifespan=lifespan,
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
    """Reject a body too large to be a set of photographs before it is parsed.

    Once the endpoint is entered the multipart parser has already consumed the
    whole request, so this is the only place a huge upload can be turned away
    without handling it. `Content-Length` is a claim, not proof, which is why the
    read in `_read_capped` counts the bytes as well.

    The body budget is the per-photograph limit times the number of photographs a
    report may carry. Each is still read and refused one at a time, so the memory
    high-water mark is one raw image, not the whole body.
    """
    declared = request.headers.get("content-length")
    limit = _body_budget()
    oversized = declared and declared.isdigit() and int(declared) > limit + _MULTIPART_OVERHEAD
    if request.method == "POST" and oversized:
        return JSONResponse(status_code=413, content={"detail": _too_large(int(declared))})
    return await call_next(request)


def _body_budget() -> int:
    return settings.vayudoot_max_upload_bytes * max(1, settings.vayudoot_max_images_per_report)


def _too_large(size: int | None = None) -> str:
    limit_mb = settings.vayudoot_max_upload_bytes / (1024 * 1024)
    most = settings.vayudoot_max_images_per_report
    seen = f" That one is {size / (1024 * 1024):.1f} MB." if size else ""
    return (
        f"That photograph is too large. The limit is {limit_mb:.0f} MB each, for up to "
        f"{most} photographs.{seen} Most phones can send a smaller copy; a resized "
        "photograph is enough here, since the image is scaled down before it is read anyway."
    )


def _too_many(count: int) -> str:
    most = settings.vayudoot_max_images_per_report
    return (
        f"That is {count} photographs; at most {most} are accepted. Every photograph is "
        "read by the model in the same call, so each one spends the day's metered "
        f"allowance. Send the {most} that show the event most clearly."
    )


async def _read_capped(image: UploadFile, budget: int) -> bytes:
    """Read an upload, refusing it the moment it goes past the limit.

    `budget` is what is left of the request's total allowance, so a caller cannot
    get around the per-photograph cap by sending several photographs just under it.
    """
    limit = min(settings.vayudoot_max_upload_bytes, budget)
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


async def _store_photographs(images: list[UploadFile]) -> list[str]:
    """Normalise every submitted photograph and write it to the uploads directory.

    Normalising at the door rather than at the model means an unreadable file is
    a 415 the citizen can act on, instead of a case that fails four seconds later
    for no visible reason.
    """
    submitted = [image for image in images if image is not None and image.filename]
    if not submitted:
        return []
    if len(submitted) > settings.vayudoot_max_images_per_report:
        raise HTTPException(413, _too_many(len(submitted)))

    uploads = settings.vayudoot_upload_dir
    uploads.mkdir(parents=True, exist_ok=True)

    remaining = _body_budget()
    paths: list[str] = []
    for position, image in enumerate(submitted, start=1):
        raw = await _read_capped(image, remaining)
        remaining -= len(raw)
        try:
            image_format, data = normalise(raw)
        except UnsupportedImage as exc:
            where = f" (photograph {position} of {len(submitted)})" if len(submitted) > 1 else ""
            raise HTTPException(
                415, f"That file could not be read as a photograph{where}: {exc}"
            ) from exc

        path = uploads / f"{uuid.uuid4().hex}{suffix_for(image_format)}"
        path.write_bytes(data)
        paths.append(str(path))
    return paths


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


@app.post("/reports", response_model=Case, status_code=202, response_model_exclude=CASE_EXCLUDE)
async def submit_report(
    request: Request,
    latitude: float = Form(...),
    longitude: float = Form(...),
    note: str = Form(""),
    contact: str = Form(""),
    image: list[UploadFile] | None = File(None),
) -> Case:
    """Accept a report and start the pipeline. Returns before the run finishes.

    `image` is repeatable: one angle is often not enough to classify a plume, and
    the confidence floor then halts a real event. Sending the field once is
    exactly what it always was.
    """
    # Metered before anything else: this is the endpoint that spends the day's
    # model quota, and the cheapest refusal is the one made before any work.
    decision = limiter.check(_client_key(request))
    if not decision.allowed:
        raise HTTPException(
            429, decision.message, headers={"Retry-After": str(decision.retry_after_seconds)}
        )

    report = Report(
        report_id=uuid.uuid4().hex,
        latitude=latitude,
        longitude=longitude,
        note=note,
        reporter_contact=contact,
        image_paths=await _store_photographs(image or []),
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


@app.get("/clusters", response_model=list[Cluster])
def list_clusters() -> list[Cluster]:
    """Repeat reports of the same problem at the same place, strongest first.

    Derived from the case store on every call rather than stored, because
    membership changes the moment a new report arrives and a cached copy would
    be wrong within the hour. The store is JSON files and a cluster pass is pure
    arithmetic over them, so recomputing costs nothing worth caching.
    """
    return clustering.clusters()


@app.get("/hotspots", response_model=list[Hotspot])
def list_hotspots() -> list[Hotspot]:
    """Places where pollution is happening, most confident first.

    The unit of work from v0.3 on, and not the same thing as `/clusters`. A
    cluster is repeat *citizen cases* at one place, used to argue a pattern
    inside a complaint. A hotspot is what the map shows, and unlike a cluster it
    can exist with no citizen involvement at all — a satellite detection or a
    station exceedance raises one on its own.

    Derived on every call for `/clusters`' reason: membership changes whenever a
    signal arrives, and a cached copy would be wrong within the hour.

    Two fields deserve to be read together. `corroborated` says whether any
    source outside the public supports this, and `confidence` is capped when it
    is false, however many reports there are. An interface that shows the
    confidence without the flag is hiding the part that matters — see hard
    constraint 7 in `CLAUDE.md`.
    """
    return hotspots.current()


@app.get("/hotspots/{hotspot_id}", response_model=Hotspot)
def get_hotspot(hotspot_id: str) -> Hotspot:
    found = next((h for h in hotspots.current() if h.hotspot_id == hotspot_id), None)
    if found is None:
        raise HTTPException(status_code=404, detail=f"Unknown hotspot: {hotspot_id}")
    return found


@app.get("/node", response_model=NodeIdentity)
def get_node() -> NodeIdentity:
    """Who this instance is on the network of instances.

    A second state standing up its own deployment is what federation is for, and
    the first thing it needs is to be able to say who it is and read who you are.
    """
    return federation.identity()


@app.get("/feed", response_model=HotspotFeed)
def get_feed() -> HotspotFeed:
    """This node's hotspots, published for its neighbours.

    The open contract that makes the system interoperable. What is shared is a
    detection layer, not trained weights — see `federation.py` for why that
    distinction is the honest reading of the brief rather than a smaller one.

    The projection is an explicit allowlist: no signals, no case ids, nothing
    identifying a reporter. Uncorroborated hotspots are published carrying their
    flag, because a neighbour deciding what to trust needs the weak signals as
    well as the strong ones.
    """
    if not settings.vayudoot_publish_feed:
        raise HTTPException(status_code=404, detail="This node does not publish a feed")
    return federation.publish(hotspots.current())


@app.get("/neighbours")
def get_neighbours() -> dict:
    """What this node's configured neighbours are currently reporting.

    Read live rather than cached, and failures are reported rather than hidden: a
    peer being unreachable is ordinary on a federated network, and an operator
    needs to see which of them answered.
    """
    results = [federation.fetch_neighbour(url) for url in settings.neighbour_feeds]
    return {
        "configured": len(results),
        "reachable": sum(1 for r in results if "error" not in r),
        "neighbours": [
            {
                "url": r["url"],
                "node": r["feed"].node.model_dump() if "feed" in r else None,
                "hotspot_count": r.get("hotspot_count", 0),
                "error": r.get("error"),
            }
            for r in results
        ],
    }


@app.get("/forecast", response_model=AirQualityForecast)
async def get_forecast(lat: float, lon: float, place: str = "") -> AirQualityForecast:
    """Where air quality is heading at one location, and why.

    Model-derived and labelled as such on the object itself. This is not an
    official forecast and not a health advisory; hard constraint 7 and the
    `disclaimer` field.

    The outlook reads this node's own hotspots and its neighbours' together. That
    is the whole point of federating: Punjab's burning is the best available
    explanation of a Delhi morning, and a node that can only see its own reports
    learns about it when the smoke arrives.
    """
    context = hotspots.current() + federation.as_context(federation.neighbour_hotspots())
    try:
        return await forecast_location(
            latitude=lat, longitude=lon, location_name=place, nearby_hotspots=context
        )
    except Exception as exc:
        # The forecast stage is a fast-tier call, so a quota trip reports as one.
        raise HTTPException(status_code=502, detail=errors.describe(exc, "fast")) from exc


@app.get("/corridors", response_model=list[Corridor])
def list_corridors() -> list[Corridor]:
    """The economic corridors this instance forecasts along.

    Data, not code: adding one is an edit to `data/corridors.json`, the same
    property the authority table has. A second state standing up its own
    instance adds its own corridors without touching Python.
    """
    return corridors.all_corridors()


@app.get("/corridors/{corridor_id}/forecast", response_model=CorridorForecast)
async def get_corridor_forecast(corridor_id: str) -> CorridorForecast:
    """The air quality outlook along one corridor.

    Model-derived, and labelled as such on the object. The corridor takes the
    worst risk any of its waypoints carries rather than an average: a corridor is
    a population strip and a supply line, so the segment in trouble is the thing
    an authority needs to see.

    Every waypoint is forecast against this node's hotspots *and* its
    neighbours'. That is the case the federation exists for — a corridor running
    out of Punjab into Delhi is forecast with Punjab's detections in hand.
    """
    corridor = corridors.get_corridor(corridor_id)
    if corridor is None:
        raise HTTPException(status_code=404, detail=f"Unknown corridor: {corridor_id}")

    context = hotspots.current() + federation.as_context(federation.neighbour_hotspots())
    try:
        return await forecast_corridor(corridor, hotspots=context)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=errors.describe(exc, "fast")) from exc


@app.post("/sensors/readings", response_model=Signal, status_code=201)
def submit_sensor_reading(reading: SensorReading, request: Request) -> Signal:
    """Accept a reading from a low-cost sensor somebody owns.

    The brief's phrase is "citizen-sourced data (photos, local sensor readings)",
    and only the first half existed.

    A reading is not a photograph and is not treated like one. Nobody has looked
    at it, it names no pollution type, and a cheap sensor is not a
    reference-grade instrument — so it enters as a `CITIZEN_SENSOR` signal, which
    is deliberately **not** independent for corroboration. Treating it as
    instrument evidence would reopen the hole hard constraint 7 closes: a sensor
    is as easy to place and misreport as an account is to create.

    Rate limited on the same budget as reports. This endpoint spends no model
    quota, but an open write to the signal store is an open write to the map.
    """
    decision = limiter.check(_client_key(request))
    if not decision.allowed:
        raise HTTPException(
            429, decision.message, headers={"Retry-After": str(decision.retry_after_seconds)}
        )

    exceedance = hotspots.exceedance_strength(reading.parameter, reading.value)
    if exceedance is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{reading.parameter} at {reading.value} is below the Indian standard "
                "or is not a pollutant with one. A reading that is not an exceedance "
                "is not evidence of an event."
            ),
        )

    signal = Signal(
        source=SignalSource.CITIZEN_SENSOR,
        signal_id=(
            f"sensor:{reading.sensor_id}:{reading.parameter}:"
            f"{reading.observed_at.isoformat()}"
        ),
        latitude=reading.latitude,
        longitude=reading.longitude,
        observed_at=reading.observed_at,
        strength=settings.vayudoot_citizen_sensor_reliability,
        magnitude=exceedance,
        summary=f"Citizen sensor {reading.sensor_id}: {reading.parameter} "
        f"{reading.value} {reading.unit}",
    )
    store.save_signals([signal])
    return signal


@app.get("/cases", response_model=list[Case], response_model_exclude=CASE_LIST_EXCLUDE)
def list_cases() -> list[Case]:
    return store.all_cases()


@app.get("/cases/{case_id}", response_model=Case, response_model_exclude=CASE_EXCLUDE)
def get_case(case_id: str) -> Case:
    return _require(case_id)


@app.get("/cases/{case_id}/cluster", response_model=Cluster | None)
def get_case_cluster(case_id: str) -> Cluster | None:
    """The pattern this case currently belongs to, or null if it is a one-off.

    Recomputed, not read from `case.cluster_id`. That field records what the
    drafting stage saw at the time; a case filed as a one-off can become the
    first member of a pattern weeks later, and this is the endpoint that says so.
    """
    return clustering.cluster_for(_require(case_id))


@app.get("/cases/{case_id}/photo")
def get_case_photo(case_id: str) -> FileResponse:
    """Serve the first submitted photograph.

    Unchanged on purpose: this URL predates multiple photographs and anything
    holding it — a bookmark, the interface, a printed pack — must keep resolving
    to the same picture. The rest are addressed by index below.
    """
    return _serve_photo(_require(case_id), 0)


@app.get("/cases/{case_id}/photo/{index}")
def get_case_photo_at(case_id: str, index: int) -> FileResponse:
    """Serve the nth submitted photograph, counting from zero."""
    return _serve_photo(_require(case_id), index)


def _serve_photo(case: Case, index: int) -> FileResponse:
    """Serve one of a case's photographs, and only from the uploads directory."""
    paths = case.report.image_paths
    if not paths:
        raise HTTPException(404, "This report has no photograph")
    if not 0 <= index < len(paths):
        raise HTTPException(
            404, f"This report has {len(paths)} photograph(s); there is no photograph {index}"
        )

    path = Path(paths[index]).resolve()
    uploads = settings.vayudoot_upload_dir.resolve()
    if uploads not in path.parents or not path.exists():
        raise HTTPException(404, "Photograph is no longer available")

    media_type = _IMAGE_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type)


@app.get("/cases/{case_id}/pack", response_class=HTMLResponse)
def get_case_pack(case_id: str) -> HTMLResponse:
    """The whole case as one document to print, attach, or hand over.

    Self-contained HTML: photographs embedded as data URIs, an SVG locator drawn
    from the case's own coordinates, styles inline. It opens offline with no
    external requests and prints to PDF from any browser, which is what makes the
    local-language half of the complaint render correctly. See `pack.py` for why
    that beats a PDF library here.

    The citizen's contact is deliberately not in it; this file is meant to be
    passed on.
    """
    case = _require(case_id)
    document = pack.render(case)
    return HTMLResponse(
        document,
        headers={
            # Named so a folder of packs sorts and reads sensibly, but shown in
            # the browser rather than downloaded: most people want to read it
            # and then print it, and a forced download hides both.
            "Content-Disposition": f'inline; filename="{case.case_id}-evidence-pack.html"'
        },
    )


@app.get("/register", response_model=list[register.PublicCase])
def get_register() -> list[register.PublicCase]:
    """Every filed complaint, as a shareable read-only record.

    Only cases a human confirmed and filed appear here, and every field is an
    explicit allowlist in `register.py`. The citizen's contact never appears, and
    neither does their free-text note.
    """
    return register.register()


@app.get("/register/{case_id}", response_model=register.PublicCase)
def get_register_case(case_id: str) -> register.PublicCase:
    """One filed complaint as a public record.

    A case that exists but is not public answers 404, exactly as a missing one
    does. The register must not confirm that a withdrawn or rejected complaint
    was ever made.
    """
    public = register.public_case(case_id)
    if public is None:
        raise HTTPException(404, f"No public case: {case_id}")
    return public


@app.get("/register/{case_id}/photo")
def get_register_photo(case_id: str) -> FileResponse:
    """The first photograph of a filed complaint."""
    return _serve_photo(_require_public(case_id), 0)


@app.get("/register/{case_id}/photo/{index}")
def get_register_photo_at(case_id: str, index: int) -> FileResponse:
    """The nth photograph of a filed complaint, counting from zero."""
    return _serve_photo(_require_public(case_id), index)


def _require_public(case_id: str) -> Case:
    """Load a case only if the register publishes it."""
    case = store.load(case_id)
    if case is None or not register.is_public(case):
        raise HTTPException(404, f"No public case: {case_id}")
    return case


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


@app.post("/cases/{case_id}/confirm", response_model=Case, response_model_exclude=CASE_EXCLUDE)
def confirm_and_file(case_id: str) -> Case:
    """The human-in-the-loop gate. Nothing is filed until a person confirms."""
    case = _require(case_id)
    if case.status is not CaseStatus.AWAITING_CONFIRMATION:
        raise HTTPException(409, f"Case is {case.status.value}, not awaiting confirmation")
    filing.file_complaint(case)
    store.save(case)
    return case


@app.post("/cases/{case_id}/escalate", response_model=Case, response_model_exclude=CASE_EXCLUDE)
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


@app.post("/cases/{case_id}/rti", response_model=Case, response_model_exclude=CASE_EXCLUDE)
async def draft_rti(case_id: str, redraft: bool = False) -> Case:
    """Draft a Right to Information application for a complaint that was ignored.

    A separate act from escalation, not a step inside it. Escalation re-files the
    same complaint to the tier above; this asks the *original* authority, through
    its Public Information Officer, what is on the file — a different addressee,
    a different statute, and a duty to reply within thirty days that the original
    complaint never carried. A citizen may do either, both, or neither, and an
    application made in their own name with their own fee cannot be an automatic
    consequence of a timer.

    Nothing is sent. The application is held on the case for a person to complete
    and file themselves; there is no transport here and no envelope written.

    The draft is cached on the case because it costs a primary-tier model call.
    Pass `redraft=true` to spend another one deliberately.
    """
    case = _require(case_id)
    if case.rti is not None and not redraft:
        return case
    if not filing.rti_available(case):
        raise HTTPException(409, _rti_not_available(case))

    try:
        case.rti = await draft_rti_application(case)
    except Exception as exc:
        if not errors.is_rate_limit(exc, tier="primary"):
            raise  # not a recognised rate limit; keep the default 500 and log it
        message = errors.describe(exc, tier="primary")
        log.warning("RTI draft rate-limited for case %s: %s", case_id, message)
        raise HTTPException(503, message) from exc
    case.rti_drafted_at = datetime.now(UTC)
    case.log(
        "RTI application drafted under the Right to Information Act, 2005. Held for the "
        "citizen to complete and file in their own name; nothing has been sent."
    )
    store.save(case)
    return case


@app.get("/cases/{case_id}/rti", response_class=PlainTextResponse)
def get_rti_text(case_id: str) -> str:
    """The drafted application as filing-ready text, for printing or pasting."""
    case = _require(case_id)
    if case.rti is None:
        raise HTTPException(404, f"No RTI application has been drafted for {case.case_id}")
    return case.rti.body_en


def _rti_not_available(case: Case) -> str:
    """Why an RTI cannot be drafted yet, which is not always a matter of time."""
    if case.status not in filing.RTI_FROM:
        return (
            f"Case is {case.status.value}; an RTI application asks what was done about a "
            "complaint that was actually filed and then went unanswered"
        )
    if case.filed_at is None or case.jurisdiction is None:
        return "This case has no filed complaint to ask about"
    days = case.jurisdiction.response_window_days
    return (
        f"The {days}-day statutory window since filing has not lapsed. Ask what was done "
        "only once the authority is actually late."
    )


@app.post("/cases/{case_id}/acknowledge", response_model=Case, response_model_exclude=CASE_EXCLUDE)
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


@app.post("/cases/{case_id}/resolve", response_model=Case, response_model_exclude=CASE_EXCLUDE)
def resolve_case(case_id: str, body: NoteRequest | None = None) -> Case:
    """Close the case: the pollution stopped, or the authority acted."""
    body = body or NoteRequest()
    case = _require(case_id)
    with _transition():
        lifecycle.resolve(case, note=body.note)
    store.save(case)
    return case


@app.post("/cases/{case_id}/withdraw", response_model=Case, response_model_exclude=CASE_EXCLUDE)
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
