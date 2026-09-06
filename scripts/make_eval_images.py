"""Regenerate the synthetic images in `evals/images/`.

    uv run python scripts/make_eval_images.py

The images are committed, so a fresh clone can run the harness without this
script. It exists so that the fixtures are reproducible rather than a set of
opaque binaries: anyone can read what each one is meant to be and regenerate it.

Every image here is *synthetic* — drawn by this script, not photographed. That
is stated in the manifest for each case, and it bounds what these fixtures can
honestly test. A procedurally drawn grey blob is not a photograph of smoke, so
no case expects a model to classify one as `open_waste_burning`. What they test
is the opposite and more valuable property: that an image which is not a
photograph of a pollution event comes back `unclear`, with confidence below the
pipeline's floor, rather than being confidently forced into a category.

Two of them are adversarial on purpose. `plume-shape` and `ember-glow` are drawn
to carry the *colours and silhouette* of a fire without being a photograph of
one; a classifier that pattern-matches on hue rather than reading the scene will
fail those two and pass the rest.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parents[1] / "evals" / "images"
SIZE = (640, 480)
#: Fixed so a regeneration produces byte-identical files and the diff stays empty.
SEED = 20260906


def _canvas(colour: tuple[int, int, int] = (255, 255, 255)) -> Image.Image:
    return Image.new("RGB", SIZE, colour)


def noise_static() -> Image.Image:
    """Uniform RGB static. Not a photograph of anything at all.

    Drawn at a quarter scale and enlarged without interpolation: per-pixel noise
    at full size is a megabyte of incompressible PNG, and a fixture set is only
    useful if it is small enough that nobody minds it being in the repository.
    """
    rng = random.Random(SEED)
    small = (SIZE[0] // 4, SIZE[1] // 4)
    image = Image.new("RGB", small)
    image.putdata(
        [
            (rng.randrange(256), rng.randrange(256), rng.randrange(256))
            for _ in range(small[0] * small[1])
        ]
    )
    return image.resize(SIZE, Image.NEAREST)


def empty_sky() -> Image.Image:
    """A clear vertical gradient. Sky with nothing in it."""
    image = _canvas()
    draw = ImageDraw.Draw(image)
    for y in range(SIZE[1]):
        t = y / SIZE[1]
        draw.line(
            [(0, y), (SIZE[0], y)],
            fill=(int(70 + 120 * t), int(120 + 100 * t), int(190 + 50 * t)),
        )
    return image


def document_page() -> Image.Image:
    """A page of text. A screenshot, not an observation of the world."""
    rng = random.Random(SEED + 1)
    image = _canvas((250, 250, 248))
    draw = ImageDraw.Draw(image)
    y = 48
    while y < SIZE[1] - 40:
        width = rng.randrange(220, SIZE[0] - 80)
        draw.rectangle([48, y, 48 + width, y + 7], fill=(48, 48, 54))
        y += 22
    draw.rectangle([48, 20, 300, 32], fill=(20, 20, 24))
    return image


def plume_shape() -> Image.Image:
    """Adversarial: a grey blob on blue, drawn to read as a smoke plume.

    It has the silhouette and the palette of smoke and none of the texture of a
    photograph. A classifier that matches on shape will call this open burning.
    """
    rng = random.Random(SEED + 2)
    image = empty_sky()
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 380, SIZE[0], SIZE[1]], fill=(96, 92, 84))
    x, y, radius = 300.0, 380.0, 18.0
    for _ in range(90):
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=(105, 103, 100))
        x += rng.uniform(-4, 9)
        y -= rng.uniform(2, 6)
        radius += rng.uniform(0.2, 0.9)
    return image.filter(ImageFilter.GaussianBlur(9))


def ember_glow() -> Image.Image:
    """Adversarial: an orange radial gradient. Firelight without a fire."""
    image = _canvas()
    pixels = image.load()
    cx, cy = SIZE[0] / 2, SIZE[1] * 0.62
    longest = math.hypot(cx, cy)
    for y in range(SIZE[1]):
        for x in range(SIZE[0]):
            t = min(1.0, math.hypot(x - cx, y - cy) / longest)
            pixels[x, y] = (int(255 - 90 * t), int(170 - 140 * t), int(40 - 35 * t))
    return image.filter(ImageFilter.GaussianBlur(2))


IMAGES = {
    "noise-static.png": noise_static,
    "empty-sky.png": empty_sky,
    "document-page.png": document_page,
    "plume-shape.png": plume_shape,
    "ember-glow.png": ember_glow,
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, build in IMAGES.items():
        path = OUT / name
        build().save(path, format="PNG", optimize=True)
        print(f"{path.relative_to(OUT.parents[1])}  {path.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
