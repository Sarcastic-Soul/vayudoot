"""Recorded upstream responses, replayed into the corroboration tools.

The corroboration stage is the one that has been wrong twice, so it is the one
worth evaluating hardest — and it is also the one whose inputs move under you.
FIRMS returns different fires every day, OpenAQ stations go offline, and the
wind changes. An eval that hit them live would score the weather rather than the
prompt, and would fail differently every run.

So the network is replaced with a recording. The substitution is at the module's
`httpx` reference rather than at the tool function, which means the tool's own
parsing runs for real: a recording that no longer matches what
`find_satellite_fire_detections` expects fails offline, for free, instead of
quietly feeding the model a shape it will never see in production.

`httpx` is patched per tool module and never globally. The model providers use
httpx too, and a global patch would replay the model call as well.

A recording is a JSON object keyed by source:

    {
      "firms":            {"text": "country_id,latitude,...\\n"},
      "openaq_locations": {"json": {...}},
      "openaq_latest":    {"json": {...}},
      "open_meteo":       {"json": {...}}
    }

Each value is one of:

    {"json": ...}                 a 200 response carrying that body
    {"text": "..."}               a 200 response carrying that text
    {"status": 503, "text": ""}   a response the tool will raise_for_status on
    {"unavailable": "reason"}     a transport failure, as when the API is down
    absent or null                the same as unavailable

Every one of those paths ends with the tool returning a dict, because tools in
this project return errors rather than raising. Recording the failure modes
matters as much as recording the happy ones: "no corroboration because nothing
answered" is the case the synthesis has to get right.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx

from vayudoot.config import settings
from vayudoot.tools import firms, openaq, weather

#: Which recording key serves a given request URL. Order matters: the OpenAQ
#: `latest` endpoint is a longer path under the same prefix as `locations`.
_ROUTES: tuple[tuple[str, str], ...] = (
    ("firms.modaps.eosdis.nasa.gov", "firms"),
    ("api.openaq.org/v3/locations/", "openaq_latest"),
    ("api.openaq.org/v3/locations", "openaq_locations"),
    ("api.open-meteo.com", "open_meteo"),
)

SOURCES = tuple(key for _, key in _ROUTES)


class RecordingError(ValueError):
    """A recording is malformed or does not cover a request that was made."""


class _Response:
    """The slice of `httpx.Response` the three tools actually touch."""

    def __init__(self, status_code: int, text: str, body: Any) -> None:
        self.status_code = status_code
        self.text = text
        self._body = body

    def json(self) -> Any:
        if self._body is not None:
            return self._body
        return json.loads(self.text or "null")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"Replayed status {self.status_code}", request=None, response=None
            )


class _Client:
    """Stands in for the `httpx` module inside one tool module."""

    def __init__(self, recording: dict[str, Any], seen: list[str]) -> None:
        self._recording = recording
        self._seen = seen

    def get(self, url: str, **_: Any) -> _Response:
        key = _route(url)
        self._seen.append(key)
        entry = self._recording.get(key)
        if entry is None:
            raise httpx.ConnectError(f"No recording for {key}")
        if not isinstance(entry, dict):
            raise RecordingError(f"Recording entry {key!r} must be an object")
        if "unavailable" in entry:
            raise httpx.ConnectError(str(entry["unavailable"]))
        return _Response(
            status_code=int(entry.get("status", 200)),
            text=str(entry.get("text", "")),
            body=entry.get("json"),
        )


def _route(url: str) -> str:
    for fragment, key in _ROUTES:
        if fragment in url:
            return key
    raise RecordingError(f"No recording route matches {url}")


def load(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        recording = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RecordingError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(recording, dict):
        raise RecordingError(f"{path}: a recording must be a JSON object")
    unknown = set(recording) - set(SOURCES) - {"id", "why", "captured"}
    if unknown:
        raise RecordingError(
            f"{path}: unknown key(s) {', '.join(sorted(unknown))}; "
            f"sources are {', '.join(SOURCES)}"
        )
    return recording


@contextlib.contextmanager
def replaying(recording: dict[str, Any]) -> Iterator[list[str]]:
    """Serve the three corroboration tools from `recording` for the block.

    Yields the list of recording keys requested, so a caller can assert that a
    source was actually consulted rather than assumed.

    The two API keys are set to a placeholder for the duration. Without them
    both tools short-circuit before any request, and the recording would never
    be read — which would silently turn every corroboration case into a test of
    the "not configured" branch.
    """
    seen: list[str] = []
    modules = (firms, openaq, weather)
    saved = [module.httpx for module in modules]
    saved_keys = (settings.firms_map_key, settings.openaq_api_key)
    client = _Client(recording, seen)
    for module in modules:
        module.httpx = client
    settings.firms_map_key = "eval-replay"
    settings.openaq_api_key = "eval-replay"
    try:
        yield seen
    finally:
        for module, original in zip(modules, saved, strict=True):
            module.httpx = original
        settings.firms_map_key, settings.openaq_api_key = saved_keys


def tool_outputs(recording: dict[str, Any], latitude: float, longitude: float) -> dict[str, Any]:
    """Run the three real tools against a recording and return what they gave.

    This is the offline half of a corroboration case: no model is involved, so
    it verifies the fixture against the code that will read it. If the FIRMS CSV
    header changes shape, or an OpenAQ payload loses the field the tool digs
    for, this is where it shows up.
    """
    with replaying(recording):
        return {
            "firms": firms.find_satellite_fire_detections(
                latitude=latitude, longitude=longitude
            ),
            "openaq": openaq.get_nearby_air_quality(latitude=latitude, longitude=longitude),
            "weather": weather.get_wind_conditions(latitude=latitude, longitude=longitude),
        }
