"""The evidence pack: one document a citizen can print, attach, or hand over.

Regulators, journalists and NGOs want paper. A case is a JSON file and a web
page, and neither of those is something anyone can put in front of a person at a
desk. This assembles everything the case knows — the photographs, the
corroboration, a locator diagram, the complaint in both languages, the pattern
if there is one, and the timeline — into a single file.

Why HTML and not PDF
--------------------
The complaint is drafted in English *and* the region's language, so the document
has to render Devanagari, Kannada, Marathi and Tamil correctly or it is worse
than useless. That rules out most of the pure-Python PDF libraries: they need a
font with the right coverage embedded and configured, several of them silently
drop glyphs they cannot shape rather than failing, and Indic scripts need proper
shaping (reordered matras, conjuncts) that a simple glyph-by-glyph writer does
not do. Shipping a document that quietly loses half a complaint is the failure
mode to design against.

A self-contained HTML file avoids all of it. Text is UTF-8 and the browser
already has a shaping engine and system fonts for these scripts, so the local
language renders the way it does everywhere else on the machine. It needs no new
dependency, which matters on a free tier. It prints to PDF from any browser, so
the PDF is still available to anyone who wants one. And it is readable as a file
by anything, including the person who receives it by email.

Self-contained means self-contained
-----------------------------------
Nothing in the document may fetch anything when it is opened. Photographs are
embedded as `data:` URIs, the stylesheet is inline, and the map is an SVG drawn
here from the report's own coordinates rather than a tile from a basemap
service. A tiled map would need a key, would bill somebody, and would render as
a broken image the moment the file is opened offline — which is exactly when a
pack is being read.

What is deliberately not in it
------------------------------
`report.reporter_contact`. The whole point of this document is that it gets
handed to people, and a citizen who wanted their phone number on a complaint can
write it on the copy they send. The pack says the contact is held on the case
rather than pretending there is none.
"""

from __future__ import annotations

import base64
import math
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from . import clustering, filing
from .config import settings
from .schemas import Case, Cluster

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


@lru_cache(maxsize=1)
def _environment() -> Environment:
    # Autoescape unconditionally rather than by file extension: everything in
    # this document except the SVG this module draws is model output or citizen
    # text, and the file suffix is `.html.j2`, which `select_autoescape` does not
    # recognise as HTML.
    return Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)


def render(case: Case, cluster: Cluster | None = None) -> str:
    """Return the whole pack as one self-contained HTML document."""
    if cluster is None:
        cluster = _pattern(case)

    return _environment().get_template("pack.html.j2").render(
        case=case,
        report=case.report,
        cluster=cluster,
        photographs=photographs(case),
        map_svg=locator_svg(case, cluster),
        pattern_sentence=clustering.describe(cluster, case.case_id) if cluster else "",
        escalation_due=filing.escalation_due(case),
        rti_available=filing.rti_available(case),
        generated_at=datetime.now(UTC),
        live_filing=settings.vayudoot_live_filing,
    )


def _pattern(case: Case) -> Cluster | None:
    """The pattern this case sits in, if the store can still answer.

    Never fatal. A pack without its pattern block is a slightly weaker document;
    a pack that 500s because a case file on disk was half-written is no document
    at all.
    """
    try:
        return clustering.cluster_for(case)
    except Exception:  # noqa: BLE001 - the pack is worth more than the pattern
        return None


# --------------------------------------------------------------------------- #
# Photographs
# --------------------------------------------------------------------------- #


def photographs(case: Case) -> list[dict[str, str]]:
    """Every readable photograph on the case, embedded as a `data:` URI.

    A missing file is skipped rather than raising: uploads and cases have
    separate lifetimes, and a pack of everything that survives is more useful
    than an error saying one thing did not.
    """
    embedded: list[dict[str, str]] = []
    uploads = settings.vayudoot_upload_dir.resolve()

    for position, raw in enumerate(case.report.image_paths, start=1):
        path = Path(raw).resolve()
        # Same containment rule as the photo endpoint: a case may name a path,
        # but only the uploads directory is ever read from.
        if uploads not in path.parents or not path.exists():
            continue
        media_type = _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        embedded.append(
            {
                "src": f"data:{media_type};base64,{encoded}",
                "caption": f"Photograph {position} of {len(case.report.image_paths)}",
            }
        )
    return embedded


# --------------------------------------------------------------------------- #
# The locator diagram
# --------------------------------------------------------------------------- #

WIDTH, HEIGHT, PAD = 640, 400, 44

#: Smallest area the diagram will draw, in metres. A single point has no extent,
#: and a scale bar computed from a zero span is a division by zero.
MIN_SPAN_M = 400.0

#: Scale-bar lengths worth printing. Anything else reads as false precision.
BAR_STEPS_M = (50, 100, 200, 500, 1000, 2000, 5000, 10000)


def locator_svg(case: Case, cluster: Cluster | None = None) -> str:
    """Draw the report location, the back-traced source, and any repeat reports.

    A diagram rather than a map, and labelled as one in the document. There is no
    basemap underneath it, because every tile service needs a key or a bill and
    because a pack must open with no external requests at all. What it can honestly
    show is the geometry the case actually established: where the report was, where
    the wind says a source would have to lie, and where the other reports in the
    pattern fell.
    """
    report = case.report
    points: list[tuple[float, float, str, str]] = [
        (report.latitude, report.longitude, "report", "Report")
    ]

    corroboration = case.corroboration
    if (
        corroboration is not None
        and corroboration.upwind_source_latitude is not None
        and corroboration.upwind_source_longitude is not None
    ):
        points.append(
            (
                corroboration.upwind_source_latitude,
                corroboration.upwind_source_longitude,
                "upwind",
                "Upwind point",
            )
        )

    if cluster is not None:
        for member in cluster.members:
            if member.case_id == case.case_id:
                continue
            points.append((member.latitude, member.longitude, "member", member.case_id))

    project, scale = _projection(points)
    parts = [
        (
            f'<svg viewBox="0 0 {WIDTH} {HEIGHT}" width="100%" role="img" '
            'aria-label="Locator diagram of the report" xmlns="http://www.w3.org/2000/svg">'
        ),
        (
            f'<rect x="0" y="0" width="{WIDTH}" height="{HEIGHT}" fill="#f4f6f4" '
            'stroke="#c3ccc3" stroke-width="1"/>'
        ),
    ]

    origin = project(points[0][0], points[0][1])
    for lat, lon, kind, _ in points[1:]:
        if kind == "upwind":
            x, y = project(lat, lon)
            parts.append(
                f'<line x1="{origin[0]:.1f}" y1="{origin[1]:.1f}" x2="{x:.1f}" y2="{y:.1f}" '
                'stroke="#8a7a52" stroke-width="1.5" stroke-dasharray="5 4"/>'
            )

    for lat, lon, kind, label in points:
        parts.append(_marker(project(lat, lon), kind, label))

    parts.append(_scale_bar(scale))
    parts.append(
        f'<g transform="translate({WIDTH - 34} {PAD - 16})">'
        '<path d="M0 22 L0 0 M0 0 L-5 7 M0 0 L5 7" stroke="#4a544a" stroke-width="1.6" '
        'fill="none"/>'
        '<text x="0" y="34" text-anchor="middle" font-size="11" fill="#4a544a">N</text>'
        "</g>"
    )
    parts.append("</svg>")
    return "".join(parts)


def _projection(points: list[tuple[float, float, str, str]]):
    """An equirectangular projection fitted to `points`, plus pixels per metre.

    Flat-earth arithmetic, which is exact enough: every diagram here spans well
    under a few kilometres, where the error is centimetres.
    """
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    centre_lat = (min(lats) + max(lats)) / 2
    centre_lon = (min(lons) + max(lons)) / 2
    metres_per_lon = 111_320.0 * max(math.cos(math.radians(centre_lat)), 0.01)

    span_x = max((max(lons) - min(lons)) * metres_per_lon, MIN_SPAN_M)
    span_y = max((max(lats) - min(lats)) * 110_574.0, MIN_SPAN_M)
    scale = min((WIDTH - 2 * PAD) / span_x, (HEIGHT - 2 * PAD) / span_y)

    def project(lat: float, lon: float) -> tuple[float, float]:
        x = WIDTH / 2 + (lon - centre_lon) * metres_per_lon * scale
        y = HEIGHT / 2 - (lat - centre_lat) * 110_574.0 * scale
        return x, y

    return project, scale


def _marker(at: tuple[float, float], kind: str, label: str) -> str:
    x, y = at
    if kind == "report":
        shape = (
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9" fill="#b23b2e" fill-opacity="0.22"/>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="#b23b2e"/>'
        )
    elif kind == "upwind":
        shape = (
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="none" stroke="#8a7a52" '
            'stroke-width="1.8"/>'
        )
    else:
        shape = f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.2" fill="#4a6b8a" fill-opacity="0.85"/>'

    escaped = label.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        f"{shape}"
        f'<text x="{x:.1f}" y="{y - 12:.1f}" text-anchor="middle" font-size="11" '
        f'fill="#33403a">{escaped}</text>'
    )


def _scale_bar(scale: float) -> str:
    """A bar of a round number of metres, sized to the drawing's own scale."""
    widest = (WIDTH - 2 * PAD) / 2.5
    metres = BAR_STEPS_M[0]
    for step in BAR_STEPS_M:
        if step * scale <= widest:
            metres = step
    length = metres * scale
    label = f"{metres} m" if metres < 1000 else f"{metres / 1000:g} km"
    y = HEIGHT - 22
    return (
        f'<g stroke="#4a544a" stroke-width="1.4">'
        f'<line x1="{PAD}" y1="{y}" x2="{PAD + length:.1f}" y2="{y}"/>'
        f'<line x1="{PAD}" y1="{y - 4}" x2="{PAD}" y2="{y + 4}"/>'
        f'<line x1="{PAD + length:.1f}" y1="{y - 4}" x2="{PAD + length:.1f}" y2="{y + 4}"/>'
        "</g>"
        f'<text x="{PAD}" y="{y - 8}" font-size="11" fill="#4a544a">{label}</text>'
    )
