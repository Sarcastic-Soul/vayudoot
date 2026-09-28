"""Satellite true-colour snapshots from NASA GIBS.

Everything else the system takes from satellites is a *point*: FIRMS reports that
VIIRS saw heat at a coordinate. Nobody ever looked at a picture. This fetches one
— the VIIRS corrected-reflectance true-colour composite for the day, cut to a
square around a hotspot — so a model can be asked whether smoke is visible there.

GIBS is free, needs no key and no account, which is why it is used rather than
Earth Engine or Vertex: both need a Google Cloud project with billing, and hard
constraint 3 rules that out.

**Checked against the live service, not remembered.** Three things here were
read off `GetCapabilities` for `wms/epsg4326/best` on 2026-09-28 rather than
assumed:

* The layer names. `VIIRS_SNPP_CorrectedReflectance_TrueColor` and
  `VIIRS_NOAA20_CorrectedReflectance_TrueColor` are both published, daily, with
  gaps in the archive — SNPP has days missing in 2026, which is why a second
  satellite is tried before giving up on a date.
* The axis order. WMS 1.3.0 with `CRS=EPSG:4326` takes `BBOX` as
  *lat, lon* — south, west, north, east — not the lon, lat of every other tool
  in this project. The capabilities document says so itself: its EPSG:4326
  bounding box is `minx=-90 miny=-180`. Get this wrong and the request succeeds
  and returns a picture of somewhere else, which is the worst kind of bug.
* What a missing day looks like. A date with no processed pass is not an error:
  GIBS answers 200 with a JPEG that is entirely black. So "did it work" is
  decided by looking at the pixels, not the status code.

Not a Strands `@tool`. It returns image bytes, which are no use to a model as a
tool result; the imagery agent is handed the picture as a content block instead.
It keeps the tool convention all the same — a plain dict, never an exception —
because a snapshot that could not be fetched is an ordinary answer for an
operator to read, not a crash.
"""

from __future__ import annotations

import io
from datetime import UTC, date, datetime, timedelta

import httpx

from ..config import settings
from .geo import bbox_around

_URL = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"

#: Tried in this order for each date. Both are the same instrument on two
#: satellites in the same orbit about fifty minutes apart, so either picture
#: answers the same question.
LAYERS: tuple[str, ...] = (
    "VIIRS_SNPP_CorrectedReflectance_TrueColor",
    "VIIRS_NOAA20_CorrectedReflectance_TrueColor",
)

#: Pixels per side. Small on purpose: the image is sent to a model, and every
#: pixel is quota. 512 is about 100 m per pixel over the default 50 km frame,
#: already finer than the 250-375 m the instrument resolves, so a bigger image
#: would be spending tokens on interpolation.
SIZE = 512

#: Luminance (0-255) below which a pixel counts as "no data". A missing swath
#: is pure black; the darkest real ground — water, dense forest — sits well
#: above this in a corrected-reflectance composite.
_BLANK_LEVEL = 8

#: Share of blank pixels past which a snapshot is treated as not available for
#: that date. Half, not all: a pass processed partway through leaves a black
#: wedge, and a frame that is mostly wedge cannot answer the question even if
#: some of it is ground.
_BLANK_SHARE = 0.5


def snapshot_bbox(latitude: float, longitude: float, half_side_km: float) -> list[float]:
    """The frame as [south, west, north, east] — the order WMS 1.3.0 EPSG:4326 wants."""
    west, south, east, north = bbox_around(latitude, longitude, half_side_km)
    return [round(v, 5) for v in (south, west, north, east)]


def blank_share(image: bytes) -> float:
    """How much of an image is the black of a missing pass, 0 to 1.

    Raises on bytes that are not an image; `fetch_true_colour` catches that.
    """
    from PIL import Image

    with Image.open(io.BytesIO(image)) as picture:
        histogram = picture.convert("L").histogram()
    total = sum(histogram) or 1
    return sum(histogram[:_BLANK_LEVEL]) / total


def fetch_true_colour(
    latitude: float,
    longitude: float,
    half_side_km: float | None = None,
    days_back: int | None = None,
    today: date | None = None,
) -> dict:
    """The most recent usable true-colour snapshot around a point.

    Tries today first, then each earlier day up to `days_back`, and on each day
    each layer in `LAYERS`. Today's pass usually does not exist until the
    afternoon overpass over India has been processed, so falling back a day is
    the normal path, not the exceptional one.

    Returns `{"image": bytes, "format": "jpeg", "image_date", "layer", "bbox",
    "attempts"}` on success, or `{"error": str, "attempts": [...]}`. Never raises.
    """
    half = settings.vayudoot_imagery_half_side_km if half_side_km is None else half_side_km
    back = settings.vayudoot_imagery_days_back if days_back is None else days_back
    # Dates are UTC because GIBS composites are UTC days; an India-local date
    # would ask for tomorrow's image every evening after 18:30 IST.
    start = today or datetime.now(UTC).date()
    bbox = snapshot_bbox(latitude, longitude, half)

    attempts: list[str] = []
    for offset in range(max(back, 0) + 1):
        day = (start - timedelta(days=offset)).isoformat()
        for layer in LAYERS:
            outcome = _get(layer, day, bbox)
            if isinstance(outcome, bytes):
                attempts.append(f"{day} {layer}: ok")
                return {
                    "image": outcome,
                    "format": "jpeg",
                    "image_date": day,
                    "layer": layer,
                    "bbox": bbox,
                    "attempts": attempts,
                }
            attempts.append(f"{day} {layer}: {outcome}")

    return {
        "error": (
            f"No usable satellite image in the last {back + 1} days around "
            f"{latitude:.4f}, {longitude:.4f}. " + "; ".join(attempts)
        ),
        "attempts": attempts,
    }


def _get(layer: str, day: str, bbox: list[float]) -> bytes | str:
    """One GetMap request: the JPEG bytes, or a short reason it was not usable."""
    params = {
        "SERVICE": "WMS",
        "REQUEST": "GetMap",
        "VERSION": "1.3.0",
        "LAYERS": layer,
        "STYLES": "",
        "CRS": "EPSG:4326",
        "BBOX": ",".join(str(v) for v in bbox),
        "WIDTH": SIZE,
        "HEIGHT": SIZE,
        "FORMAT": "image/jpeg",
        "TIME": day,
    }
    try:
        resp = httpx.get(_URL, params=params, timeout=30)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return f"request failed ({exc})"

    # A WMS error is an XML ServiceException, sometimes with a 200 status.
    content_type = resp.headers.get("content-type", "")
    if not content_type.startswith("image/"):
        return f"not an image ({content_type or 'no content type'})"

    try:
        share = blank_share(resp.content)
    except Exception as exc:  # noqa: BLE001
        return f"unreadable image ({exc})"
    if share > _BLANK_SHARE:
        return f"no processed pass ({share:.0%} of the frame is empty)"
    return resp.content
