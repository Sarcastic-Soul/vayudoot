"""Voice notes: recognising the file, sending it to Gemini, hearing it, and keeping it in its place.

Three decisions are held in place here, and each test says which.

* No named party leaves the voice stage (hard constraint 7 and the standing
  non-goal). The model is asked to leave names out, and `redact` enforces it.
* A voice note is the reporter's claim, never a second source. It reaches the
  evidence and drafting prompts marked as such, never reaches corroboration,
  and a report with no photograph stays under the written-account ceiling.
* The recording is not served back. A voice identifies its speaker.
"""

from __future__ import annotations

import asyncio
import io
import struct
import wave

import pytest
from httpx import ASGITransport, AsyncClient

from fakes import StubAgent, evidence, image_bytes, patch_stages, voice_account, voice_hearing
from vayudoot import api, audio, hotspots, pipeline, store
from vayudoot.agents import drafting as drafting_agent
from vayudoot.agents import evidence as evidence_agent
from vayudoot.agents import voice as voice_agent
from vayudoot.config import settings
from vayudoot.models import build_model
from vayudoot.schemas import (
    NAME_OMITTED,
    VOICE_DISCLAIMER,
    Case,
    CaseStatus,
    Report,
    Stage,
    VoiceAccount,
)

# --------------------------------------------------------------------------- #
# Small real recordings, or headers shaped exactly like them
# --------------------------------------------------------------------------- #


def wav_bytes(seconds: float = 1.5, rate: int = 8000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"\x00\x00" * int(seconds * rate))
    return buffer.getvalue()


def _ogg_page(granule: int, body: bytes) -> bytes:
    return b"OggS" + bytes([0, 0]) + struct.pack("<qIII", granule, 1, 0, 0) + b"\x01" + (
        bytes([len(body)]) + body
    )


def ogg_opus_bytes(seconds: float) -> bytes:
    head = b"OpusHead" + bytes([1, 1]) + struct.pack("<HI", 312, 48000) + b"\x00\x00\x00"
    return _ogg_page(0, head) + _ogg_page(0, b"OpusTags") + _ogg_page(
        int(seconds * 48000) + 312, b"\x00" * 40
    )


def m4a_bytes(seconds: float) -> bytes:
    ftyp = struct.pack(">I", 20) + b"ftypM4A " + b"\x00\x00\x00\x00" + b"M4A "
    mvhd = b"mvhd" + b"\x00\x00\x00\x00" + struct.pack(">IIII", 0, 0, 1000, int(seconds * 1000))
    return ftyp + struct.pack(">I", 8 + len(mvhd) + 8) + b"moov" + struct.pack(
        ">I", len(mvhd) + 4
    ) + mvhd + b"\x00" * 64


def webm_bytes(seconds: float | None) -> bytes:
    """An EBML header with, optionally, a Segment Info Duration — which Chrome omits."""
    info = b"\x2a\xd7\xb1\x83\x0f\x42\x40"  # TimecodeScale = 1,000,000 ns
    if seconds is not None:
        info += b"\x44\x89\x88" + struct.pack(">d", seconds * 1000)
    return b"\x1a\x45\xdf\xa3\x9f\x42\x82\x84webm" + b"\x00" * 16 + info + (
        b"\x1f\x43\xb6\x75" + b"\x00" * 64
    )


def mp3_bytes(seconds: float, kbps: int = 32) -> bytes:
    """CBR MPEG-1 Layer III frames at 32 kbit/s, 44.1 kHz."""
    header = bytes([0xFF, 0xFB, 0x10, 0x00])  # bitrate index 1 = 32 kbit/s
    return b"ID3\x03\x00\x00\x00\x00\x00\x00" + header + b"\x00" * (
        int(seconds * kbps * 1000 / 8) - 4
    )


# --------------------------------------------------------------------------- #
# audio.py: format from the bytes, length from the container
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("data", "expected", "seconds"),
    [
        (wav_bytes(1.5), "wav", 1.5),
        (ogg_opus_bytes(12.0), "ogg", 12.0),
        (m4a_bytes(20.0), "m4a", 20.0),
        (webm_bytes(30.0), "webm", 30.0),
        (webm_bytes(None), "webm", None),
        (mp3_bytes(4.0), "mp3", 4.0),
        (bytes([0xFF, 0xF1, 0x50, 0x80]) + b"\x00" * 60, "aac", None),
    ],
)
def test_the_format_comes_from_the_bytes_and_the_length_from_the_container(
    data, expected, seconds
):
    assert audio.sniff(data) == expected
    measured = audio.duration_seconds(data, expected)
    if seconds is None:
        assert measured is None
    else:
        assert measured == pytest.approx(seconds, abs=0.05)


@pytest.mark.parametrize("data", [b"", b"hello", image_bytes("PNG"), b"%PDF-1.7" + b"\x00" * 64])
def test_anything_that_is_not_a_recording_is_refused(data):
    with pytest.raises(audio.UnsupportedAudio):
        audio.sniff(data)


def test_every_accepted_format_has_a_mime_type_gemini_reads():
    """`audio/mp4`, not `audio/m4a`: the second is not a registered type."""
    assert audio.mime_type("m4a") == "audio/mp4"
    assert all(mime.startswith("audio/") for mime, _ in audio.AUDIO_FORMATS.values())


# --------------------------------------------------------------------------- #
# models.py: the audio block reaches Gemini
# --------------------------------------------------------------------------- #


def _gemini(monkeypatch, tier="fast"):
    monkeypatch.setattr(settings, "vayudoot_model_provider", "gemini")
    monkeypatch.setattr(settings, "vayudoot_model_provider_fast", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    return build_model(tier=tier)


def test_an_audio_block_is_sent_to_gemini_as_inline_audio(monkeypatch):
    """The hook in `FallbackGeminiModel`. If this fails after a Strands upgrade,
    the private method it overrides has moved, and voice notes have stopped
    reaching the model."""
    model = _gemini(monkeypatch)
    clip = wav_bytes(0.5)
    messages = [
        {
            "role": "user",
            "content": [
                {"text": "Transcribe."},
                {"audio": {"format": "wav", "source": {"bytes": clip}}},
            ],
        }
    ]
    parts = model._format_request_content(messages)[0].parts
    assert parts[0].text == "Transcribe."
    assert parts[1].inline_data.mime_type == "audio/wav"
    assert parts[1].inline_data.data == clip


def test_strands_gemini_still_needs_the_hook(monkeypatch):
    """Why the hook exists. Skips, rather than fails, the day Strands formats
    audio itself — at which point the override in `models.py` can go."""
    from strands.models.gemini import GeminiModel

    base = GeminiModel(client_args={"api_key": "test-key"}, model_id="gemini-test")
    block = {"audio": {"format": "wav", "source": {"bytes": b"RIFF"}}}
    try:
        base._format_request_content_part(block, {})
    except TypeError:
        return
    pytest.skip("Strands now formats audio blocks itself; the models.py hook can go")


def test_a_non_gemini_fast_tier_says_it_cannot_hear(monkeypatch):
    monkeypatch.setattr(settings, "vayudoot_model_provider_fast", "ollama")
    with pytest.raises(voice_agent.VoiceUnavailable, match="no audio input"):
        voice_agent.build_voice_agent()


# --------------------------------------------------------------------------- #
# agents/voice.py: no named party leaves the stage
# --------------------------------------------------------------------------- #


def _names_in(account: VoiceAccount) -> str:
    return account.model_dump_json().lower()


def test_every_listed_name_is_removed_from_every_field_and_the_list_is_dropped():
    hearing = voice_hearing(
        transcript="वो शर्मा प्लास्टिक्स वाले हैं, शर्मा जी की फैक्ट्री।",
        what_is_described="Sharma Plastics burns plastic.",
        health_effects=["sharma plastics smoke makes children cough"],
    )
    account = voice_agent.redact(hearing, model="gemini-test")

    dumped = _names_in(account)
    assert "sharma" not in dumped
    assert "शर्मा" not in dumped
    assert "named_parties" not in account.model_dump()
    assert NAME_OMITTED in account.transcript
    assert NAME_OMITTED in account.translation_en
    # Two distinct names were reported; the count says the account was edited.
    assert account.names_omitted == 2
    # Places are not names, and are how an inspector finds the area.
    assert "behind the school" in account.translation_en


def test_the_rest_of_a_half_removed_business_name_goes_with_it():
    """Flash-lite did this in live tests: it dropped the surname and kept the trade."""
    hearing = voice_hearing(
        translation_en="They are [name omitted] Plastics Pvt. Ltd. and it smells.",
        named_parties=[],
    )
    account = voice_agent.redact(hearing)
    assert account.translation_en == "They are [name omitted] and it smells."
    assert account.names_omitted == 0


async def test_hearing_sends_the_recording_and_returns_a_clean_account(tmp_path):
    clip = tmp_path / "note.ogg"
    clip.write_bytes(ogg_opus_bytes(8.0))
    report = Report(report_id="r", latitude=28.6, longitude=77.2, audio_path=str(clip))
    agent = StubAgent(voice_hearing())

    account = await voice_agent.hear_voice_note(report, agent=agent)

    sent = agent.prompts[0]
    assert sent[1]["audio"]["format"] == "ogg"
    assert sent[1]["audio"]["source"]["bytes"] == clip.read_bytes()
    assert isinstance(account, VoiceAccount)
    assert "sharma" not in _names_in(account)
    assert account.disclaimer == VOICE_DISCLAIMER


async def test_a_missing_recording_is_unavailable_not_a_crash(tmp_path):
    report = Report(
        report_id="r", latitude=28.6, longitude=77.2, audio_path=str(tmp_path / "gone.webm")
    )
    with pytest.raises(voice_agent.VoiceUnavailable):
        await voice_agent.hear_voice_note(report, agent=StubAgent(voice_hearing()))


# --------------------------------------------------------------------------- #
# The account is the reporter's claim, never a second source
# --------------------------------------------------------------------------- #


def test_the_prompt_block_marks_the_account_as_a_claim():
    block = voice_agent.spoken_account_block(voice_account())
    assert block.startswith("REPORTER'S SPOKEN ACCOUNT")
    assert "not an observation" in block
    assert "same source" in block
    assert "every night after 10 pm" in block
    assert "must not be guessed at" in block
    assert voice_agent.spoken_account_block(None) == ""
    silent = voice_account().model_copy(update={"heard_speech": False})
    assert voice_agent.spoken_account_block(silent) == ""


async def test_evidence_sees_the_account_and_stays_under_the_testimony_ceiling():
    """A voice-only report cannot be classified past what testimony is worth,
    however sure the model says it is."""
    report = Report(report_id="r", latitude=28.6, longitude=77.2)
    agent = StubAgent(evidence(confidence=0.95))

    packet = await evidence_agent.analyse_evidence(report, agent=agent, voice=voice_account())

    prompt = agent.prompts[0][0]["text"]
    assert "REPORTER'S SPOKEN ACCOUNT" in prompt
    assert "Sharma" not in prompt
    assert packet.confidence == evidence_agent.ACCOUNT_ONLY_CEILING


async def test_a_photograph_is_not_held_to_the_testimony_ceiling(tmp_path):
    photo = tmp_path / "p.png"
    photo.write_bytes(image_bytes("PNG"))
    report = Report(report_id="r", latitude=28.6, longitude=77.2, image_paths=[str(photo)])
    packet = await evidence_agent.analyse_evidence(
        report, agent=StubAgent(evidence(confidence=0.88)), voice=voice_account()
    )
    assert packet.confidence == 0.88


async def test_drafting_can_quote_the_translation_and_names_the_basis():
    from fakes import corroboration, jurisdiction

    report = Report(report_id="r", latitude=28.6, longitude=77.2)
    agent = StubAgent(None)
    await drafting_agent.draft_complaint(
        report, evidence(), corroboration(), jurisdiction(), agent=agent, voice=voice_account()
    )
    prompt = agent.prompts[0]
    assert "spoken account (a voice note, translated)" in prompt
    assert "In translation: The [name omitted] factory behind the school" in prompt
    assert "Sharma" not in prompt


def test_a_voice_note_does_not_change_the_citizen_signal():
    """One citizen, one signal. The voice note is not counted a second time and
    does not move its strength."""
    base = Case(
        case_id="VD-1",
        report=Report(report_id="r", latitude=28.6, longitude=77.2),
        evidence=evidence(0.7),
        status=CaseStatus.AWAITING_CONFIRMATION,
    )
    heard = base.model_copy(update={"voice": voice_account()})
    assert hotspots.signal_from_case(heard) == hotspots.signal_from_case(base)


# --------------------------------------------------------------------------- #
# The pipeline
# --------------------------------------------------------------------------- #


def _voice_report(tmp_path, **fields) -> Report:
    clip = tmp_path / "note.webm"
    clip.write_bytes(webm_bytes(None))
    return Report(
        report_id="r1", latitude=28.6139, longitude=77.2090, audio_path=str(clip), **fields
    )


async def test_the_account_is_heard_and_passed_to_evidence_and_drafting_only(
    monkeypatch, tmp_path
):
    patch_stages(monkeypatch, pipeline)
    seen: dict[str, dict] = {}

    def spy(name, original):
        async def wrapped(*args, **kwargs):
            seen[name] = kwargs
            return await original(*args, **kwargs)

        return wrapped

    for name in ("analyse_evidence", "corroborate", "draft_complaint"):
        monkeypatch.setattr(pipeline, name, spy(name, getattr(pipeline, name)))

    case = await pipeline.run(_voice_report(tmp_path))

    assert case.status is CaseStatus.AWAITING_CONFIRMATION
    assert case.voice is not None and case.voice.language == "Hindi"
    assert seen["analyse_evidence"]["voice"] == case.voice
    assert seen["draft_complaint"]["voice"] == case.voice
    assert "voice" not in seen["corroborate"], "a voice note is not independent evidence"
    assert any("Voice note heard in Hindi; 2 name(s) left out" in h for h in case.history)
    stored = store.load(case.case_id)
    assert stored.voice == case.voice
    assert "sharma" not in stored.model_dump_json().lower()


async def test_a_voice_note_that_will_not_play_does_not_sink_a_report_with_a_photo(
    monkeypatch, tmp_path
):
    patch_stages(monkeypatch, pipeline, fail_at="voice")
    case = await pipeline.run(_voice_report(tmp_path, image_paths=["/nowhere.png"]))

    assert case.status is CaseStatus.AWAITING_CONFIRMATION
    assert case.voice is None
    assert any("could not be heard" in h for h in case.history)


async def test_a_voice_only_report_that_cannot_be_heard_fails_with_the_reason(
    monkeypatch, tmp_path
):
    patch_stages(monkeypatch, pipeline, fail_at="voice")

    async def never(*a, **k):
        raise AssertionError("no primary call on an empty report")

    monkeypatch.setattr(pipeline, "analyse_evidence", never)
    case = await pipeline.run(_voice_report(tmp_path))

    assert case.status is CaseStatus.FAILED
    assert case.stage is Stage.EVIDENCE
    assert "voice note could not be heard" in case.error
    assert "voice exploded" in case.error


async def test_a_voice_only_report_with_no_speech_fails_before_evidence(monkeypatch, tmp_path):
    patch_stages(monkeypatch, pipeline)
    silent = voice_account().model_copy(
        update={"heard_speech": False, "transcript": "", "translation_en": ""}
    )

    async def hear(*a, **k):
        return silent

    async def never(*a, **k):
        raise AssertionError("no primary call on an empty report")

    monkeypatch.setattr(pipeline, "hear_voice_note", hear)
    monkeypatch.setattr(pipeline, "analyse_evidence", never)
    case = await pipeline.run(_voice_report(tmp_path))

    assert case.status is CaseStatus.FAILED
    assert "no speech" in case.error


async def test_a_report_without_a_voice_note_never_calls_the_voice_stage(monkeypatch):
    patch_stages(monkeypatch, pipeline, fail_at="voice")
    case = await pipeline.run(Report(report_id="r", latitude=28.6, longitude=77.2, note="Smoke"))
    assert case.status is CaseStatus.AWAITING_CONFIRMATION
    assert case.voice is None


# --------------------------------------------------------------------------- #
# The route
# --------------------------------------------------------------------------- #


@pytest.fixture
async def client():
    transport = ASGITransport(app=api.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _drain() -> None:
    while api._running:
        await asyncio.gather(*list(api._running), return_exceptions=True)


FORM = {"latitude": "28.6139", "longitude": "77.2090"}


async def test_a_voice_note_is_accepted_beside_a_photograph(client, monkeypatch):
    patch_stages(monkeypatch, pipeline)
    files = [
        ("image", ("photo.png", image_bytes("PNG"), "image/png")),
        ("audio", ("note.webm", webm_bytes(None), "audio/webm;codecs=opus")),
    ]
    resp = await client.post("/reports", data=FORM, files=files)
    assert resp.status_code == 202, resp.text
    path = resp.json()["report"]["audio_path"]
    assert path.endswith(".webm")
    assert settings.vayudoot_upload_dir.resolve() in type(settings.vayudoot_upload_dir)(
        path
    ).resolve().parents

    await _drain()
    done = (await client.get(f"/cases/{resp.json()['case_id']}")).json()
    assert done["voice"]["language"] == "Hindi"
    assert done["voice"]["disclaimer"] == VOICE_DISCLAIMER
    assert "named_parties" not in done["voice"]
    assert "sharma" not in str(done).lower()


async def test_a_voice_note_alone_is_a_report(client, monkeypatch):
    """A hotspot does not need a photograph, and nor does a report: a spoken
    account is the account a person near a fire at night can give."""
    patch_stages(monkeypatch, pipeline)
    resp = await client.post(
        "/reports", data=FORM, files={"audio": ("note.m4a", m4a_bytes(12), "audio/mp4")}
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["report"]["image_paths"] == []


async def test_a_file_that_is_not_a_recording_is_a_415(client, monkeypatch):
    patch_stages(monkeypatch, pipeline)
    resp = await client.post(
        "/reports", data=FORM, files={"audio": ("note.webm", b"not audio at all" * 4, "audio/webm")}
    )
    assert resp.status_code == 415
    assert "voice note" in resp.json()["detail"]
    assert store.all_cases() == []


async def test_an_oversized_voice_note_is_a_413_and_stores_nothing(client, monkeypatch):
    patch_stages(monkeypatch, pipeline)
    monkeypatch.setattr(settings, "vayudoot_max_audio_bytes", 4096)
    files = [
        ("image", ("photo.png", image_bytes("PNG"), "image/png")),
        ("audio", ("note.wav", wav_bytes(1.0), "audio/wav")),  # 16 kB
    ]
    resp = await client.post("/reports", data=FORM, files=files)
    assert resp.status_code == 413
    assert "voice note is too large" in resp.json()["detail"]
    assert store.all_cases() == []
    # Checked before the photographs are written, so none is left behind.
    uploads = settings.vayudoot_upload_dir
    assert not uploads.exists() or not any(uploads.iterdir())


async def test_a_voice_note_past_the_length_cap_is_a_413(client, monkeypatch):
    patch_stages(monkeypatch, pipeline)
    monkeypatch.setattr(settings, "vayudoot_max_audio_seconds", 5)
    resp = await client.post(
        "/reports", data=FORM, files={"audio": ("note.ogg", ogg_opus_bytes(30), "audio/ogg")}
    )
    assert resp.status_code == 413
    assert "30 seconds" in resp.json()["detail"]


async def test_health_publishes_the_voice_limits(client):
    body = (await client.get("/health")).json()
    assert body["max_audio_seconds"] == settings.vayudoot_max_audio_seconds
    assert body["max_audio_bytes"] == settings.vayudoot_max_audio_bytes


def test_no_route_serves_a_recording():
    """A voice identifies its speaker, and `GET /cases` is world-readable. The
    account is on the case; the recording stays on disk."""
    served = [getattr(route, "path", "") for route in api.app.routes]
    assert not [p for p in served if any(w in p for w in ("audio", "voice", "recording"))]
