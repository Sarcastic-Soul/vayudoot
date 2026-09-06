"""Structural checks on the text the model actually reads.

A prompt is source code that happens to be prose, and this project's prompts
carry lines that were paid for with a live run: "weather is never corroboration
on its own", "never report 1.0". Nothing stops the next edit from tidying one of
those away, and no offline test would notice.

A guard is a regex assertion over one piece of that text, declared in the
manifest with the reason it exists. It costs nothing, needs no model, and fails
the moment a line goes missing. It cannot tell you the prompt got *better* —
only that a specific thing it used to say, it still says.

The same treatment covers the field descriptions in `schemas.py`, because those
go to the model as part of the structured-output schema. They are prompt text
that happens to live in a Pydantic model.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from vayudoot import schemas
from vayudoot.agents import prompts

from .manifest import Guard


class TargetError(ValueError):
    """A guard points at text that does not exist."""


def resolve(target: str) -> str:
    """Return the text a guard target names.

    Two forms:

        prompt:SYNTHESIS                   a constant in agents/prompts.py
        schema:Corroboration.corroborated  a field description in schemas.py
    """
    kind, _, rest = target.partition(":")
    if kind == "prompt":
        text = getattr(prompts, rest, None)
        if not isinstance(text, str):
            raise TargetError(f"No prompt named {rest!r} in agents/prompts.py")
        return text
    if kind == "schema":
        model_name, _, field_name = rest.partition(".")
        model = getattr(schemas, model_name, None)
        fields = getattr(model, "model_fields", None)
        if fields is None:
            raise TargetError(f"No Pydantic model named {model_name!r} in schemas.py")
        if field_name not in fields:
            raise TargetError(f"{model_name} has no field {field_name!r}")
        return fields[field_name].description or ""
    raise TargetError(f"Unknown target form {target!r}; expected 'prompt:' or 'schema:'")


def flatten(text: str) -> str:
    """Collapse every run of whitespace to one space.

    Prompts are hard-wrapped at column 88 and schema descriptions are wrapped by
    black, so the line breaks fall wherever the formatter put them. A guard that
    had to know where a phrase wraps would break on a reflow that changed
    nothing the model reads, and the author of the next guard would learn this
    the same way it was learned here: by writing the obvious pattern and
    watching it fail.
    """
    return re.sub(r"\s+", " ", text)


def check(guard: Guard) -> dict[str, Any]:
    """Evaluate one guard. Never raises: a bad target is a failed guard."""
    try:
        text = flatten(resolve(guard.target))
    except TargetError as exc:
        return {"id": guard.id, "target": guard.target, "passed": False, "detail": str(exc)}

    problems: list[str] = []
    if not text.strip():
        problems.append("the target text is empty")
    for pattern in guard.must_match:
        if not re.search(pattern, text, re.IGNORECASE):
            problems.append(f"missing /{pattern}/")
    for pattern in guard.must_not_match:
        if re.search(pattern, text, re.IGNORECASE):
            problems.append(f"unexpectedly matches /{pattern}/")

    return {
        "id": guard.id,
        "target": guard.target,
        "passed": not problems,
        "detail": "; ".join(problems) or "holds",
        "why": guard.why,
    }


def run(guards: list[Guard]) -> list[dict[str, Any]]:
    return [check(guard) for guard in guards]


def fingerprints(guards: list[Guard]) -> dict[str, str]:
    """A short hash of every prompt, plus any schema text a guard watches.

    Recorded in the run file so that comparing two runs can say *the SYNTHESIS
    prompt changed* rather than leaving the reader to guess why the numbers
    moved. Prompts are hashed unconditionally; schema descriptions only when a
    guard names one, since there is no list of "prompt-bearing fields" to walk.
    """
    marks: dict[str, str] = {}
    for name in dir(prompts):
        if name.isupper() and isinstance(getattr(prompts, name), str):
            marks[f"prompt:{name}"] = _digest(getattr(prompts, name))
    for guard in guards:
        if guard.target.startswith("schema:") and guard.target not in marks:
            try:
                marks[guard.target] = _digest(resolve(guard.target))
            except TargetError:
                marks[guard.target] = "missing"
    return dict(sorted(marks.items()))


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
