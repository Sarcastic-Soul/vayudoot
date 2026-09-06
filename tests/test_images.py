"""Submitted photographs are decoded, not trusted.

The format a model sees has to come from the file's contents. An extension is a
claim the uploader makes, and the failure it used to cause was silent: an
unrecognised suffix was rewritten to `.jpg`, so HEIC bytes reached the model
labelled as JPEG and it saw nothing.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from fakes import image_bytes
from vayudoot.images import MAX_EDGE, SDK_FORMATS, UnsupportedImage, normalise, suffix_for


def _decode(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "GIF", "WEBP"])
def test_a_supported_format_passes_through_untouched(fmt):
    data = image_bytes(fmt)
    image_format, out = normalise(data)
    assert image_format in SDK_FORMATS
    assert out == data, "a format the model already accepts should not be re-encoded"


@pytest.mark.parametrize("fmt", ["TIFF", "BMP", "PPM", "AVIF", "JPEG2000"])
def test_an_unsupported_format_is_converted_rather_than_refused(fmt):
    image_format, out = normalise(image_bytes(fmt))
    assert image_format in SDK_FORMATS
    assert _decode(out).format.lower() in SDK_FORMATS


def test_transparency_survives_as_png_rather_than_being_flattened():
    """Flattening alpha onto an assumed background invents pixels."""
    image_format, out = normalise(image_bytes("PNG", size=(2000, 100), mode="RGBA"))
    assert image_format == "png"
    assert _decode(out).mode in ("RGBA", "LA", "P")


def test_an_oversized_photograph_is_capped():
    """A 12 megapixel phone photo is tokens spent on detail nothing needs."""
    image_format, out = normalise(image_bytes("JPEG", size=(4032, 3024)))
    assert max(_decode(out).size) == MAX_EDGE
    assert image_format == "jpeg"


def test_a_small_photograph_is_not_upscaled():
    _, out = normalise(image_bytes("JPEG", size=(64, 48)))
    assert _decode(out).size == (64, 48)


def test_an_exif_rotation_is_applied_to_the_pixels():
    """A model reads pixels; it does not read the orientation tag."""
    image = Image.new("RGB", (40, 20), (10, 20, 30))
    exif = image.getexif()
    exif[0x0112] = 6  # rotate 90 degrees clockwise
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)

    _, out = normalise(buffer.getvalue())
    assert _decode(out).size == (20, 40), "the image should have been turned upright"


def test_heic_is_read_as_heic_and_not_as_its_extension():
    """The iOS default, and the format the old extension mapping silently broke."""
    pillow_heif = pytest.importorskip("pillow_heif")
    from PIL import Image as PILImage

    buffer = io.BytesIO()
    pillow_heif.from_pillow(PILImage.new("RGB", (2400, 1800), (90, 100, 110))).save(
        buffer, format="HEIF", quality=70
    )

    image_format, out = normalise(buffer.getvalue())
    assert image_format == "jpeg"
    assert max(_decode(out).size) == MAX_EDGE


def test_bytes_that_are_not_an_image_are_refused():
    with pytest.raises(UnsupportedImage):
        normalise(b"this is a text file pretending to be a photograph")


def test_an_empty_upload_is_refused():
    with pytest.raises(UnsupportedImage):
        normalise(b"")


def test_every_supported_format_has_a_suffix():
    for image_format in SDK_FORMATS:
        assert suffix_for(image_format).startswith(".")
    assert suffix_for("heic") == ".jpg", "an unknown format falls back to the converted one"
