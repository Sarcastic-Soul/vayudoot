"""Case persistence.

Cases outlive a single request: a complaint filed today is chased for weeks, so
state has to survive process restarts. JSON files on disk are deliberate for the
prototype — swapping in Postgres means replacing this module and nothing else.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import settings
from .schemas import Case


def _dir() -> Path:
    settings.vayudoot_case_dir.mkdir(parents=True, exist_ok=True)
    return settings.vayudoot_case_dir


def save(case: Case) -> Path:
    path = _dir() / f"{case.case_id}.json"
    path.write_text(case.model_dump_json(indent=2))
    return path


def load(case_id: str) -> Case | None:
    path = _dir() / f"{case_id}.json"
    if not path.exists():
        return None
    return Case.model_validate_json(path.read_text())


def all_cases() -> list[Case]:
    cases = []
    for path in sorted(_dir().glob("*.json")):
        try:
            cases.append(Case.model_validate_json(path.read_text()))
        except (json.JSONDecodeError, ValueError):
            continue
    return sorted(cases, key=lambda c: c.created_at, reverse=True)
