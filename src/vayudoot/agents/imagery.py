"""A model's reading of a satellite picture of a hotspot.

The only place in the system where anyone looks at satellite *imagery* rather
than at a satellite's point detections. `tools/imagery.py` fetches a VIIRS
true-colour snapshot around the hotspot from NASA GIBS, and this asks Gemini
whether a smoke plume is visible in it and whether cloud is in the way.

**The reading is an annotation, not a corroborating signal.** That is the design
decision here and it must not be quietly undone. The reading is never turned
into a `Signal`, `SignalSource` has no member for it, it is not in
`INDEPENDENT_SOURCES`, and nothing in `hotspots.py` reads it, so it cannot move a
hotspot's confidence or its corroboration flag. Two reasons:

* It is a model's reading of a coarse image, not an instrument's measurement.
  A VIIRS true-colour pixel is 250-375 m; smoke and thin cloud look alike at
  that scale, and a model asked "is there smoke" is inclined to find some. A
  thermal detection is an instrument recording heat; this is an opinion about a
  picture of the same sky.
* Letting it gate publication would reopen the hole hard constraint 7 closes.
  Corroboration exists so that coordinated false reports cannot manufacture a
  hotspot. If a model's reading counted as independent evidence, a hallucinated
  plume would corroborate those reports — the weakest input in the system would
  be the one deciding what the public map says.

So the reading is shown to an operator beside the hotspot, labelled as
model-derived, and cited in an alert as supporting context. That is all it does.

**The model is not told why it is looking.** The prompt says the centre of the
frame is "a location of interest" and nothing else: not that a fire was
detected there, not what kind of hotspot it is. Telling it would invite it to
find what it was told to expect.

Model tier is `primary`: this is judgement on an image, the evidence stage's
kind of work. It runs only when an operator asks, outside any report run, and
the reading is cached per hotspot and image date (`store.save_imagery`) so the
same picture is never paid for twice. Hard constraint 5 records the reason.
"""

from __future__ import annotations

from collections.abc import Callable

from .. import store
from ..models import Agent, build_model, media_part, text_part
from ..schemas import Hotspot, ImageryAssessment, ImageryReading
from ..tools.imagery import fetch_true_colour
from .prompts import IMAGERY


class ImageryUnavailable(RuntimeError):
    """No usable snapshot could be fetched. Carries the tool's reason."""


def build_imagery_agent() -> Agent:
    return Agent(
        name="imagery",
        model=build_model(temperature=0.0, tier="primary"),
        system_prompt=IMAGERY,
    )


async def assess_snapshot(
    snapshot: dict, latitude: float, longitude: float, agent: Agent | None = None
) -> ImageryAssessment:
    """Ask the model about one fetched snapshot. `snapshot` is the tool's success dict."""
    agent = agent or build_imagery_agent()
    south, west, north, east = snapshot["bbox"]
    prompt = (
        f"Satellite image: {snapshot['layer']}, pass date {snapshot['image_date']} (UTC).\n"
        f"Frame: latitude {south} to {north}, longitude {west} to {east}; north is up.\n"
        f"The centre of the frame, {latitude:.4f}, {longitude:.4f}, is a location of "
        "interest.\n\n"
        "Is a smoke plume visible, and does cloud hide the centre?"
    )
    content = [
        text_part(prompt),
        media_part(snapshot["image"], f"image/{snapshot['format']}"),
    ]
    result = await agent.invoke_async(content, structured_output_model=ImageryAssessment)
    return result.structured_output


async def read_hotspot_imagery(
    hotspot: Hotspot,
    agent: Agent | None = None,
    fetch: Callable[..., dict] | None = None,
    reread: bool = False,
) -> ImageryReading:
    """The reading for the most recent usable snapshot of a hotspot, cached.

    The snapshot is always fetched — it is free and needs no key — because that
    is how the most recent processed date is found. The *model* is only asked
    when no reading is cached for that hotspot and date, or when `reread` asks
    for one deliberately.

    On a cache hit the cached image is kept rather than replaced with the one
    just fetched. GIBS can fill in more of a day's swath as the day goes on, and
    the picture an operator is shown has to be the exact picture the model read.
    """
    # Looked up at call time, not bound as a default, so it can be replaced.
    snapshot = (fetch or fetch_true_colour)(hotspot.centre_latitude, hotspot.centre_longitude)
    if "error" in snapshot:
        raise ImageryUnavailable(snapshot["error"])

    if not reread:
        cached = store.load_imagery(hotspot.hotspot_id, snapshot["image_date"])
        if cached is not None:
            return cached

    assessment = await assess_snapshot(
        snapshot, hotspot.centre_latitude, hotspot.centre_longitude, agent=agent
    )
    # Provenance is the caller's to set, never the model's: the model was asked
    # what it sees, not what it was shown.
    reading = ImageryReading(
        **assessment.model_dump(),
        hotspot_id=hotspot.hotspot_id,
        image_date=snapshot["image_date"],
        layer=snapshot["layer"],
        bbox=list(snapshot["bbox"]),
    )
    store.save_imagery(reading, snapshot["image"])
    return reading
