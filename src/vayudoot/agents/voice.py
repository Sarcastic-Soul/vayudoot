"""Hear a citizen's voice note: transcript, translation, and what it describes.

A citizen standing near a burning dump can say more in twenty seconds than they
will type on a phone — and can say it in their own language, which the typed
note quietly assumed was English. So a report may carry a voice note, and this
stage turns it into a `VoiceAccount`: what was said in the language it was said
in, an English translation, and the useful parts pulled out — how often it
happens, for how long, what it smells like, who is coughing.

**Gemini hears the audio itself.** Cloud Speech-to-Text and Translation need a
billing account, which is why voice was out of scope before; Gemini through AI
Studio takes audio as an ordinary content block on the free tier. Strands'
Gemini provider does not send audio blocks, so `models.FallbackGeminiModel`
adds the one missing branch — see its `_format_request_content_part`. On Ollama
there is no audio input at all, and this stage says so instead of pretending.

**No named party leaves this module.** The model is asked to replace every
name of a person or business with `[name omitted]` and to list what it left
out. `redact` then removes each listed name from every field, whatever the
model did with the text, and drops the list. That is hard constraint 7 and the
non-goal of naming a responsible party, enforced in code rather than hoped for.

**It is not evidence of anything.** A voice note is the same citizen as the
photograph and the written note, heard a second way. It goes to the evidence
and drafting stages marked as the reporter's own claim, never becomes a
`Signal`, and cannot move corroboration or a hotspot's confidence.

Model tier is `fast`, for three reasons. Hearing and translating is closer to
transcription than to judgement: the judgement about what the report shows is
still the evidence stage's, on `primary`. Every voice report pays for this
call, so it goes where the request allowance is (500 a day per flash-lite model
against 20 per flash model) and a report keeps its two primary calls. And
flash-lite was good enough when tried: on noisy synthetic clips in Hindi (WebM
Opus), Tamil (M4A AAC) and Brazilian Portuguese (Ogg Opus) it produced
word-accurate transcripts in the right script, faithful translations and the
right time pattern, duration and health effects. What it got wrong was the
edges of a name — see `_TRAILING_NAME` — which is why names are enforced in
code rather than left to either tier.
"""

from __future__ import annotations

import re
from pathlib import Path

from strands import Agent
from strands.types.content import ContentBlock

from ..audio import UnsupportedAudio, sniff
from ..config import settings
from ..models import build_model
from ..schemas import NAME_OMITTED, Report, VoiceAccount, VoiceHearing
from .prompts import VOICE

#: The rest of a business name the model half-removed. In live tests flash-lite
#: turned "Sharma Plastics" into "[name omitted] Plastics" about half the time,
#: dropping the surname and keeping the trade. Capitalised words straight after
#: the placeholder are, in English text, the rest of the same proper noun —
#: "Plastics", "Industries Pvt. Ltd." — so they go with it. Latin script only:
#: Devanagari has no capitals to go by, which is why the prompt also asks for
#: whole names in `named_parties`.
_TRAILING_NAME = re.compile(re.escape(NAME_OMITTED) + r"(?:[ ]+[A-Z][\w&.'-]*)+")

#: The tier this stage runs on. Named once so the pipeline can attribute a
#: failure here to the provider actually responsible for it.
TIER = "fast"


class VoiceUnavailable(RuntimeError):
    """The voice note cannot be heard: missing, unreadable, or no audio-capable model."""


def build_voice_agent() -> Agent:
    if settings.provider_for(TIER) != "gemini":
        raise VoiceUnavailable(
            "Voice notes are heard by Gemini, and the fast tier is configured for "
            f"{settings.provider_for(TIER)}, which takes no audio input."
        )
    return Agent(
        name="voice",
        model=build_model(temperature=0.0, tier=TIER),
        system_prompt=VOICE,
        callback_handler=None,
    )


def _audio_block(path: Path) -> ContentBlock:
    data = path.read_bytes()
    try:
        audio_format = sniff(data)
    except UnsupportedAudio as exc:
        raise VoiceUnavailable(f"The stored voice note could not be read: {exc}") from exc
    return {"audio": {"format": audio_format, "source": {"bytes": data}}}


async def hear_voice_note(report: Report, agent: Agent | None = None) -> VoiceAccount:
    """Transcribe, translate and summarise the report's voice note."""
    path = Path(report.audio_path) if report.audio_path else None
    if path is None or not path.exists():
        raise VoiceUnavailable("The report's voice note is no longer on disk.")

    block = _audio_block(path)
    agent = agent or build_voice_agent()
    prompt = (
        f"A citizen recorded this voice note at {report.observed_at.isoformat()} to report air "
        "pollution near them. Transcribe it, translate it into English, and fill in what it "
        "describes. Leave out every name."
    )
    content: list[ContentBlock] = [{"text": prompt}, block]
    result = await agent.invoke_async(content, structured_output_model=VoiceHearing)
    model = getattr(getattr(agent, "model", None), "config", {}) or {}
    return redact(result.structured_output, model=model.get("model_id", ""))


def redact(hearing: VoiceHearing, model: str = "") -> VoiceAccount:
    """The stored account: every listed name removed from every field, and the list dropped.

    Matching ignores case and runs longest name first, so "Sharma Plastics" is
    removed whole before "Sharma" is looked for. A name the model listed but
    also already replaced is simply not found, which is fine; one it listed and
    forgot to replace is caught here. `names_omitted` counts the distinct strings
    the model listed, not the places they appeared — and the same name in two
    scripts is two strings, so it says names were removed, not how many people.
    """
    names = sorted(
        {n.strip() for n in hearing.named_parties if len(n.strip()) >= 2}, key=len, reverse=True
    )
    pattern = (
        re.compile("|".join(re.escape(n) for n in names), re.IGNORECASE) if names else None
    )

    def scrub(text: str) -> str:
        if not text:
            return text
        if pattern:
            text = pattern.sub(NAME_OMITTED, text)
        return _TRAILING_NAME.sub(NAME_OMITTED, text)

    fields = hearing.model_dump(exclude={"named_parties"})
    for key, value in fields.items():
        if isinstance(value, str):
            fields[key] = scrub(value)
        elif isinstance(value, list):
            fields[key] = [scrub(v) if isinstance(v, str) else v for v in value]
    return VoiceAccount(**fields, names_omitted=len(names), model=model)


def spoken_account_block(voice: VoiceAccount | None) -> str:
    """The voice account as a prompt block for the evidence and drafting stages.

    Absent rather than empty when there is nothing to say, for the same reason
    as drafting's pattern block: an empty block invites a sentence about it.
    Headed as the reporter's claim, because the reader of this block is a model
    that must not treat it as an observation.
    """
    if voice is None or not voice.heard_speech:
        return ""
    language = voice.language or "an unidentified language"
    lines = [
        "REPORTER'S SPOKEN ACCOUNT",
        (
            f"  (The citizen's own voice note, spoken in {language}, transcribed and translated "
            "by a model. Their claim, not an observation, and the same source as the rest of "
            "their report.)"
        ),
        f"  In translation: {voice.translation_en or '(empty)'}",
    ]
    extras = {
        "What they describe": voice.what_is_described,
        "When it happens": voice.time_pattern,
        "For how long": voice.duration,
        "Smells mentioned": ", ".join(voice.smells),
        "Effects on health mentioned": ", ".join(voice.health_effects),
    }
    lines += [f"  {label}: {value}" for label, value in extras.items() if value]
    if voice.names_omitted:
        lines.append(
            "  Names the speaker said were removed and must not be guessed at or restored."
        )
    return "\n".join(lines) + "\n"
