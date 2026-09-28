"""Recognise a submitted voice note, and measure it where the file says how long it is.

The photograph's rule holds here too: the format is decided by reading the
bytes, never by the file name or the browser's content type. A browser records
WebM on Chrome, Ogg on Firefox and MP4 on Safari; a phone's voice-memo app
shares M4A, AAC, MP3 or WAV; and the name of any of them is only a claim.

Nothing is transcoded. There is no ffmpeg in the container and Gemini reads
every format accepted here as it arrives, so the bytes are stored and sent
exactly as the citizen recorded them. A file whose leading bytes match none of
the formats below is refused at the door with a 415, rather than becoming a
case that fails when the model is handed noise.

Duration is read from the container: WAV, Ogg, M4A and MP3 state it, and so
does WebM when the recorder wrote a Duration. Chrome's MediaRecorder does not,
so for WebM without one the clusters are walked to the last audio block. What
is still unmeasured — a raw AAC stream, a file this cannot parse — falls to
the byte cap in `config.py`, which always applies; the duration cap applies
whenever the length is known. At the 32-64 kbit/s a browser records speech at,
the byte cap is several minutes of audio, so an unmeasured file costs at most
a few thousand audio tokens on the fast tier.
"""

from __future__ import annotations

import struct

#: What each accepted format is sent to the model as, and stored as.
#:
#: The keys are the formats Strands' `AudioFormat` literal already names, so an
#: audio content block built from them is the SDK's own shape. The MIME types
#: are what Gemini's inline data accepts; `audio/mp4` rather than `audio/m4a`,
#: because the second is not a registered type and is refused.
AUDIO_FORMATS: dict[str, tuple[str, str]] = {
    "webm": ("audio/webm", ".webm"),
    "ogg": ("audio/ogg", ".ogg"),
    "mp3": ("audio/mp3", ".mp3"),
    "m4a": ("audio/mp4", ".m4a"),
    "aac": ("audio/aac", ".aac"),
    "wav": ("audio/wav", ".wav"),
}

#: MP3 bitrates in kbit/s, indexed by the header's bitrate field, for MPEG-1
#: Layer III and for MPEG-2/2.5 Layer III. Only Layer III is spoken audio in
#: practice; the other layers are accepted but not measured.
_MP3_KBPS = {
    1: (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0),
    2: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0),
}
_MP3_RATES = {1: (44100, 48000, 32000), 2: (22050, 24000, 16000), 25: (11025, 12000, 8000)}


class UnsupportedAudio(ValueError):
    """The bytes are not a voice note in any format accepted here."""


def sniff(data: bytes) -> str:
    """The format of `data`, as a key of `AUDIO_FORMATS`, or raise."""
    if len(data) < 16:
        raise UnsupportedAudio("the file is empty or too short to be a recording")
    head = data[:12]
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"  # EBML: WebM, or Matroska audio, which Gemini reads the same way
    if head[:4] == b"OggS":
        return "ogg"
    if head[4:8] == b"ftyp":
        return "m4a"
    if head[:3] == b"ID3":
        return "mp3"
    if head[0] == 0xFF and head[1] & 0xF6 == 0xF0:
        return "aac"  # ADTS: sync word with layer bits 00
    if head[0] == 0xFF and head[1] & 0xE0 == 0xE0 and (head[1] >> 1) & 0x3:
        return "mp3"  # MPEG audio frame sync with a real layer
    raise UnsupportedAudio(
        "it is not a recording in a format accepted here (WebM, Ogg, MP3, M4A, AAC or WAV)"
    )


def mime_type(audio_format: str) -> str:
    return AUDIO_FORMATS.get(audio_format, ("application/octet-stream", ""))[0]


def suffix_for(audio_format: str) -> str:
    return AUDIO_FORMATS[audio_format][1]


def duration_seconds(data: bytes, audio_format: str) -> float | None:
    """How long the recording is, when the container says so; otherwise None.

    Never raises. A header this cannot parse is a length it does not know, not a
    file it refuses; `sniff` has already decided whether the file is audio.
    """
    reader = {
        "wav": _wav,
        "ogg": _ogg,
        "m4a": _mp4,
        "mp3": _mp3,
        "webm": _webm,
    }.get(audio_format)
    if reader is None:
        return None
    try:
        seconds = reader(data)
    except (struct.error, IndexError, ValueError, ZeroDivisionError):
        return None
    return seconds if seconds is not None and seconds >= 0 else None


def _wav(data: bytes) -> float | None:
    offset, byte_rate = 12, 0
    while offset + 8 <= len(data):
        chunk, size = data[offset : offset + 4], struct.unpack_from("<I", data, offset + 4)[0]
        body = offset + 8
        if chunk == b"fmt ":
            byte_rate = struct.unpack_from("<I", data, body + 8)[0]
        elif chunk == b"data":
            # A recorder that streamed the file may leave the size unset
            # (0 or 0xFFFFFFFF); what is actually there is the honest answer.
            size = min(size, len(data) - body) if size else len(data) - body
            return size / byte_rate if byte_rate else None
        offset = body + size + (size & 1)
    return None


def _ogg(data: bytes) -> float | None:
    """Last page's granule position over the stream's sample clock."""
    if b"OpusHead" in data[:512]:
        at = data.index(b"OpusHead")
        pre_skip = struct.unpack_from("<H", data, at + 10)[0]
        rate = 48000  # Opus granules always count at 48 kHz, whatever the input rate
    elif b"\x01vorbis" in data[:512]:
        at = data.index(b"\x01vorbis")
        pre_skip, rate = 0, struct.unpack_from("<I", data, at + 12)[0]
    else:
        return None
    last = data.rfind(b"OggS")
    granule = struct.unpack_from("<q", data, last + 6)[0]
    return max(granule - pre_skip, 0) / rate if granule >= 0 and rate else None


def _mp4(data: bytes) -> float | None:
    at = data.find(b"mvhd")
    if at < 0:
        return None
    body = at + 4
    if data[body] == 1:
        timescale, length = struct.unpack_from(">IQ", data, body + 20)
    else:
        timescale, length = struct.unpack_from(">II", data, body + 12)
    return length / timescale if timescale else None


def _mp3(data: bytes) -> float | None:
    offset = 0
    if data[:3] == b"ID3":
        size = data[6:10]
        offset = 10 + (size[0] << 21 | size[1] << 14 | size[2] << 7 | size[3])
    while offset + 4 <= len(data) and not (
        data[offset] == 0xFF and data[offset + 1] & 0xE0 == 0xE0
    ):
        offset += 1
    if offset + 4 > len(data):
        return None
    b1, b2 = data[offset + 1], data[offset + 2]
    version = {3: 1, 2: 2, 0: 25}.get((b1 >> 3) & 0x3)
    if version is None or (b1 >> 1) & 0x3 != 1:  # Layer III only
        return None
    rate = _MP3_RATES[version][(b2 >> 2) & 0x3]
    samples_per_frame = 1152 if version == 1 else 576

    # A VBR file carries its frame count in a Xing or Info header in the first
    # frame; a bitrate estimate from that frame alone can be out by half.
    frame = data[offset : offset + 200]
    for tag in (b"Xing", b"Info"):
        at = frame.find(tag)
        if at >= 0 and struct.unpack_from(">I", frame, at + 4)[0] & 0x1:
            frames = struct.unpack_from(">I", frame, at + 8)[0]
            return frames * samples_per_frame / rate

    kbps = _MP3_KBPS[1 if version == 1 else 2][(b2 >> 4) & 0xF]
    return (len(data) - offset) * 8 / (kbps * 1000) if kbps else None


_CLUSTER = b"\x1f\x43\xb6\x75"


def _webm(data: bytes) -> float | None:
    """The Segment Info `Duration` element, or else the time of the last block.

    The header is searched only before the first Cluster, so a byte pattern
    inside the audio itself cannot be mistaken for it. Chrome's MediaRecorder
    writes no Duration at all, so when there is none the clusters are walked
    (`_webm_blocks`) — which is what lets the duration cap apply to the
    commonest recording there is.
    """
    first = data.find(_CLUSTER)
    header = data[: first if first >= 0 else 4096]
    scale = 1_000_000  # TimecodeScale default, in nanoseconds
    at = header.find(b"\x2a\xd7\xb1")
    if at >= 0:
        width = header[at + 3] & 0x0F if header[at + 3] & 0x80 else 0
        if width:
            scale = int.from_bytes(header[at + 4 : at + 4 + width], "big")
    at = header.find(b"\x44\x89")
    if at < 0:
        ticks = _webm_blocks(data, first) if first >= 0 else None
        return ticks * scale / 1e9 if ticks is not None else None
    marker = header[at + 2]
    if marker == 0x88:
        ticks = struct.unpack_from(">d", header, at + 3)[0]
    elif marker == 0x84:
        ticks = struct.unpack_from(">f", header, at + 3)[0]
    else:
        return None
    return ticks * scale / 1e9


def _vint(data: bytes, pos: int, marker: bool) -> tuple[int, int] | None:
    """An EBML variable-length integer at `pos`: (value, width), or None.

    `marker` keeps the length bit, which is how element IDs are written; sizes
    drop it. A size of all ones is "unknown", which Chrome writes for every
    Cluster it streams; it comes back as -1.
    """
    if pos >= len(data) or not data[pos]:
        return None
    first = data[pos]
    width = 9 - first.bit_length()
    if pos + width > len(data):
        return None
    raw = int.from_bytes(data[pos : pos + width], "big")
    if marker:
        return raw, width
    value = raw & ((1 << (7 * width)) - 1)
    return (-1 if value == (1 << (7 * width)) - 1 else value), width


def _webm_blocks(data: bytes, pos: int) -> int | None:
    """The timecode of the last audio block, in TimecodeScale ticks.

    Walks the elements from the first Cluster in order rather than searching
    for byte patterns, so nothing inside an audio frame can be read as a
    timecode. Descends into Clusters and BlockGroups, whose size may be
    unknown; skips everything else by its stated size. Stops, keeping what it
    has, at the first thing it cannot parse — a truncated tail is still a
    clip whose length is known up to there.
    """
    cluster, block, blockgroup, simple, timecode = 0x1F43B675, 0xA1, 0xA0, 0xA3, 0xE7
    base, last = 0, None
    while pos < len(data):
        element = _vint(data, pos, marker=True)
        size = element and _vint(data, pos + element[1], marker=False)
        if not element or not size:
            break
        (ident, id_width), (length, size_width) = element, size
        body = pos + id_width + size_width
        if ident in (cluster, blockgroup):
            pos = body
            continue
        if length < 0 or body + length > len(data):
            break
        if ident == timecode:
            base = int.from_bytes(data[body : body + length], "big")
        elif ident in (simple, block):
            track = _vint(data, body, marker=False)
            if track and body + track[1] + 2 <= body + length:
                (relative,) = struct.unpack_from(">h", data, body + track[1])
                last = max(last or 0, base + relative)
        pos = body + length
    return last
