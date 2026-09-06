"""Normalise a submitted photograph into something a model can read.

A citizen photographs a pollution event with whatever is in their pocket, and
what arrives is not necessarily what a model accepts. Model content blocks take
four formats — PNG, JPEG, GIF, WebP — while phones produce HEIC by default on
iOS, and people upload TIFF, BMP and anything else a camera or a screenshot tool
emits. Trusting the file extension is worse than useless here: an unrecognised
one used to be renamed to `.jpg`, which meant HEIC bytes were handed over
labelled as JPEG and the model saw nothing at all.

So the format is decided by reading the file, never by its name. Anything
outside the four supported formats is converted; everything else passes through
untouched unless it needs rotating or shrinking.

What that covers in practice is everything Pillow can decode — around seventy
extensions, including AVIF, HEIC, TIFF, BMP, JPEG 2000, ICO and PSD — rather than
a list maintained here. A list would need updating every time a phone vendor
changed its default, which is exactly how the HEIC bug happened.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

try:  # HEIC/HEIF is the iOS default, and Pillow cannot read it unaided.
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover - the dependency is declared
    pass

# What a model content block accepts, mapped to the file suffix to store it as.
SDK_FORMATS = {"png": ".png", "jpeg": ".jpg", "gif": ".gif", "webp": ".webp"}

# Longest edge, in pixels. A 12 megapixel phone photograph carries far more
# detail than a classification needs, and every pixel above this is tokens spent
# for nothing — which matters, because inference is the only running cost here.
MAX_EDGE = 1568

JPEG_QUALITY = 88

# A decompression bomb is a small file that declares enormous dimensions: a few
# kilobytes of PNG can claim 30000x30000 and cost 3.6 GB to decode, which on a
# free-tier container is the whole machine. Pillow's own default limit is around
# 89 megapixels and it only *warns* below twice that, so the ceiling is set here
# and enforced explicitly against the header before anything is decoded. 64
# megapixels is comfortably above every mainstream phone camera and far below
# anything that could exhaust the container.
MAX_PIXELS = 64_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class UnsupportedImage(ValueError):
    """The bytes are not an image, or are an image nothing here can read."""


def normalise(data: bytes) -> tuple[str, bytes]:
    """Return `(format, bytes)` that a model content block will accept.

    The format is one of `SDK_FORMATS`. Raises `UnsupportedImage` if the bytes
    cannot be decoded at all.
    """
    if not data:
        raise UnsupportedImage("Empty file")

    try:
        image = Image.open(io.BytesIO(data))
        # `open` reads the header only, so the declared size is known here —
        # before any of those pixels have been allocated. Refuse outright rather
        # than leaving it to Pillow, which only warns until twice the limit.
        _refuse_a_bomb(image.size)
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise UnsupportedImage(f"Could not read the image: {exc}") from exc

    fmt = (image.format or "").lower()
    fmt = "jpeg" if fmt == "mpo" else fmt  # burst/HDR JPEGs report as MPO

    oversized = max(image.size) > MAX_EDGE
    rotated = image.getexif().get(0x0112, 1) not in (1, None)

    # An animated GIF or WebP loses its frames on a round trip through Pillow, and
    # a still one is already acceptable, so leave both alone.
    if fmt in SDK_FORMATS and getattr(image, "is_animated", False):
        return fmt, data

    if fmt in SDK_FORMATS and not oversized and not rotated:
        return fmt, data

    return _convert(image, fmt)


def _refuse_a_bomb(size: tuple[int, int]) -> None:
    pixels = size[0] * size[1]
    if pixels > MAX_PIXELS:
        raise UnsupportedImage(
            f"That image declares {pixels / 1_000_000:.0f} megapixels, over the "
            f"{MAX_PIXELS // 1_000_000} megapixel limit; it is too large to decode safely."
        )


def _convert(image: Image.Image, source_format: str) -> tuple[str, bytes]:
    """Re-encode, honouring EXIF rotation and capping the longest edge."""
    # Phone photographs are usually stored in one orientation with an EXIF tag
    # saying which way is up. A model reading the raw pixels sees the picture on
    # its side, so apply the rotation rather than passing the tag along.
    image = ImageOps.exif_transpose(image) or image

    if max(image.size) > MAX_EDGE:
        image.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)

    buffer = io.BytesIO()
    # Transparency only survives in PNG, and flattening it onto an assumed
    # background would invent pixels that were never photographed.
    if image.mode in ("RGBA", "LA", "P") and _has_alpha(image, source_format):
        image.convert("RGBA").save(buffer, format="PNG", optimize=True)
        return "png", buffer.getvalue()

    image.convert("RGB").save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return "jpeg", buffer.getvalue()


def _has_alpha(image: Image.Image, source_format: str) -> bool:
    if source_format == "jpeg":  # JPEG has no alpha channel to preserve
        return False
    return image.mode in ("RGBA", "LA") or "transparency" in image.info


def suffix_for(image_format: str) -> str:
    """The file suffix a normalised image should be stored under."""
    return SDK_FORMATS.get(image_format, ".jpg")


def read_normalised(path: Path) -> tuple[str, bytes]:
    """Normalise an image already on disk."""
    return normalise(path.read_bytes())
