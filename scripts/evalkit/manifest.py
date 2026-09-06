"""Loading and validating an eval manifest.

A manifest is data. Adding a case is a JSON edit and nothing else, for the same
reason the authority table is a JSON file: a fixture set that needs a code
change to grow does not grow.

Validation is deliberately strict and happens before any model is called. A
typo in a `pollution_type`, a missing image, or a recording that no longer
matches the tool that reads it are all things worth finding for free rather
than after eleven metered calls.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vayudoot.schemas import PollutionType

#: The kinds of case the runner knows how to execute.
#:
#:   classification  run the evidence stage, expect a specific PollutionType
#:   refusal         run the evidence stage, expect `unclear` below the floor
#:   corroboration   run the corroboration graph over recorded tool responses
KINDS = ("classification", "refusal", "corroboration")

#: Model *requests* each kind of case costs, by tier — not agents, requests. The
#: distinction was learned by running this against a per-minute quota:
#:
#:   evidence       one agent, no tools, structured output on the same call = 1
#:   corroboration  three source agents, each of which makes two requests (one
#:                  to choose the tool call, one to summarise what came back),
#:                  plus a synthesis node that calls no tool = 3 * 2 + 1 = 7
#:
#: Counting agents rather than requests under-reported a corroboration case by
#: nearly half, which is enough to walk into a 429 while believing there was
#: room. If an agent ever needs a second tool round trip the true number goes up
#: again, so this is a floor, not a guarantee.
CALL_COST: dict[str, dict[str, int]] = {
    "classification": {"primary": 1, "fast": 0},
    "refusal": {"primary": 1, "fast": 0},
    "corroboration": {"primary": 0, "fast": 7},
}


class ManifestError(ValueError):
    """The manifest is malformed, or points at something that is not there."""


@dataclass(frozen=True)
class Case:
    """One fixture, already validated against the schemas it refers to."""

    id: str
    kind: str
    why: str
    expect: dict[str, Any]
    synthetic: bool = False
    note: str = ""
    latitude: float = 28.6139
    longitude: float = 77.2090
    image: Path | None = None
    recording: Path | None = None
    pollution_type: str = ""
    severity: str = "moderate"
    visible_indicators: list[str] = field(default_factory=list)

    @property
    def cost(self) -> dict[str, int]:
        return CALL_COST[self.kind]

    @property
    def runnable(self) -> tuple[bool, str]:
        """Whether the case can run here, and why not if it cannot.

        The optional local manifest points at photographs outside the
        repository, so a case is skipped rather than failed when its image is
        absent. The harness has to work on a fresh clone with no fixtures but
        its own.
        """
        if self.image is not None and not self.image.exists():
            return False, f"image not found: {self.image}"
        return True, ""


@dataclass(frozen=True)
class Guard:
    """A structural assertion about prompt or schema text.

    Every guard records a regression that was found the expensive way. They cost
    nothing to check, so they run in offline mode and catch the specific case of
    a prompt edit that deletes a line someone paid for in a live run.
    """

    id: str
    target: str
    why: str
    must_match: list[str] = field(default_factory=list)
    must_not_match: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Manifest:
    path: Path
    name: str
    description: str
    cases: list[Case]
    guards: list[Guard]

    def select(
        self, ids: list[str] | None = None, kinds: list[str] | None = None, limit: int = 0
    ) -> list[Case]:
        chosen = self.cases
        if ids:
            wanted = set(ids)
            unknown = wanted - {c.id for c in chosen}
            if unknown:
                raise ManifestError(f"No such case: {', '.join(sorted(unknown))}")
            chosen = [c for c in chosen if c.id in wanted]
        if kinds:
            chosen = [c for c in chosen if c.kind in set(kinds)]
        if limit:
            chosen = chosen[:limit]
        return chosen


def projected_calls(cases: list[Case]) -> dict[str, int]:
    """How many model calls running `cases` live would spend, by tier."""
    total = {"primary": 0, "fast": 0}
    for case in cases:
        for tier, count in case.cost.items():
            total[tier] += count
    return total


def load(path: str | Path) -> Manifest:
    path = Path(path).resolve()
    if not path.exists():
        raise ManifestError(f"No manifest at {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{path} is not valid JSON: {exc}") from exc
    return parse(raw, path)


def parse(raw: dict[str, Any], path: Path) -> Manifest:
    """Build a `Manifest` from already-decoded JSON.

    Split out from `load` so the tests can exercise validation without writing
    files, and so an in-memory manifest is a first-class thing.
    """
    if not isinstance(raw, dict):
        raise ManifestError(f"{path}: the manifest must be a JSON object")

    root = path.parent
    cases = [_case(entry, root, index) for index, entry in enumerate(raw.get("cases") or [])]
    _reject_duplicates(cases)
    guards = [_guard(entry, index) for index, entry in enumerate(raw.get("guards") or [])]

    if not cases and not guards:
        raise ManifestError(f"{path}: the manifest has neither cases nor guards")

    return Manifest(
        path=path,
        name=str(raw.get("name") or path.stem),
        description=str(raw.get("description") or ""),
        cases=cases,
        guards=guards,
    )


def _reject_duplicates(cases: list[Case]) -> None:
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            raise ManifestError(f"Duplicate case id: {case.id}")
        seen.add(case.id)


def _case(entry: Any, root: Path, index: int) -> Case:
    where = f"cases[{index}]"
    if not isinstance(entry, dict):
        raise ManifestError(f"{where} is not an object")

    case_id = str(entry.get("id") or "").strip()
    if not case_id:
        raise ManifestError(f"{where} has no id")
    where = f"case {case_id!r}"

    kind = str(entry.get("kind") or "")
    if kind not in KINDS:
        raise ManifestError(f"{where}: kind must be one of {', '.join(KINDS)}, got {kind!r}")

    if not str(entry.get("why") or "").strip():
        raise ManifestError(
            f"{where}: every case needs a `why`. A fixture whose purpose nobody "
            "wrote down is a fixture nobody can correct later."
        )

    expect = entry.get("expect")
    if not isinstance(expect, dict) or not expect:
        raise ManifestError(f"{where}: `expect` must be a non-empty object")

    image = _relative(entry.get("image"), root)
    recording = _relative(entry.get("recording"), root)

    if kind == "corroboration":
        if recording is None:
            raise ManifestError(f"{where}: a corroboration case needs a `recording`")
        if not recording.exists():
            raise ManifestError(f"{where}: recording not found at {recording}")
        _expect_corroboration(where, expect)
    else:
        _expect_evidence(where, kind, expect)
        if image is None and not str(entry.get("note") or "").strip():
            raise ManifestError(
                f"{where}: a case with no image must carry a note, or the model "
                "is being asked to classify nothing at all"
            )

    return Case(
        id=case_id,
        kind=kind,
        why=str(entry["why"]).strip(),
        expect=expect,
        synthetic=bool(entry.get("synthetic", False)),
        note=str(entry.get("note") or ""),
        latitude=float(entry.get("latitude", 28.6139)),
        longitude=float(entry.get("longitude", 77.2090)),
        image=image,
        recording=recording,
        pollution_type=str(entry.get("pollution_type") or ""),
        severity=str(entry.get("severity") or "moderate"),
        visible_indicators=list(entry.get("visible_indicators") or []),
    )


def _expect_evidence(where: str, kind: str, expect: dict[str, Any]) -> None:
    valid = {t.value for t in PollutionType}
    declared = [expect.get("pollution_type"), *(expect.get("also_acceptable") or [])]
    for value in declared:
        if value is None:
            continue
        if value not in valid:
            raise ManifestError(
                f"{where}: {value!r} is not a PollutionType. Valid: {', '.join(sorted(valid))}"
            )
    if expect.get("pollution_type") is None:
        raise ManifestError(f"{where}: expect.pollution_type is required")
    if kind == "refusal" and expect["pollution_type"] != PollutionType.UNCLEAR.value:
        raise ManifestError(
            f"{where}: a refusal case must expect 'unclear'. If it should be "
            "classified, it is a classification case."
        )
    for bound in ("confidence_min", "confidence_max"):
        value = expect.get(bound)
        if value is not None and not 0.0 <= float(value) <= 1.0:
            raise ManifestError(f"{where}: {bound} must be between 0 and 1")


def _expect_corroboration(where: str, expect: dict[str, Any]) -> None:
    if not isinstance(expect.get("corroborated"), bool):
        raise ManifestError(f"{where}: expect.corroborated must be true or false")
    for key in ("fields", "tool_facts"):
        value = expect.get(key, {})
        if not isinstance(value, dict):
            raise ManifestError(f"{where}: expect.{key} must be an object")
    patterns = expect.get("notes_must_not_match", [])
    if not isinstance(patterns, list) or any(not isinstance(p, str) for p in patterns):
        raise ManifestError(f"{where}: expect.notes_must_not_match must be a list of strings")


def _guard(entry: Any, index: int) -> Guard:
    where = f"guards[{index}]"
    if not isinstance(entry, dict):
        raise ManifestError(f"{where} is not an object")
    guard_id = str(entry.get("id") or "").strip()
    if not guard_id:
        raise ManifestError(f"{where} has no id")
    target = str(entry.get("target") or "").strip()
    if not target:
        raise ManifestError(f"guard {guard_id!r} has no target")
    must = list(entry.get("must_match") or [])
    must_not = list(entry.get("must_not_match") or [])
    if not must and not must_not:
        raise ManifestError(f"guard {guard_id!r} asserts nothing")
    if not str(entry.get("why") or "").strip():
        raise ManifestError(f"guard {guard_id!r} has no `why`")
    return Guard(
        id=guard_id,
        target=target,
        why=str(entry["why"]).strip(),
        must_match=must,
        must_not_match=must_not,
    )


def _relative(value: Any, root: Path) -> Path | None:
    if not value:
        return None
    path = Path(str(value)).expanduser()
    return path if path.is_absolute() else (root / path).resolve()
