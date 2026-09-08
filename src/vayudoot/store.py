"""Case persistence.

Cases outlive a single request: a complaint filed today is chased for weeks, so
state has to survive process restarts — and, on a public deployment, a
container that gets rebuilt or redeployed under it. Two backends, chosen by
whether `VAYUDOOT_DATABASE_URL` is set:

* unset (the default, and what every test uses) — JSON files on disk. Fast,
  needs nothing running, and wrong for a public URL: the disk is ephemeral
  there.
* set — one row per case in Postgres, `data` as `jsonb`. Any standard Postgres
  works; nothing here is provider-specific.

Either way the interface above this module is the same three functions, so the
pipeline, the API and `clustering.py` never know which backend they are
talking to.
"""

from __future__ import annotations

import json
from pathlib import Path

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .config import settings
from .schemas import Case

_pool: ConnectionPool | None = None
_pool_url: str | None = None


def _use_postgres() -> bool:
    return bool(settings.database_url)


def _dir() -> Path:
    settings.vayudoot_case_dir.mkdir(parents=True, exist_ok=True)
    return settings.vayudoot_case_dir


def _pg() -> ConnectionPool:
    """The connection pool for the configured database, (re)opened whenever
    the URL changes — which in practice is only ever a test switching backends
    with `monkeypatch`, since a running deployment never changes its own URL."""
    global _pool, _pool_url
    url = settings.database_url
    if _pool is None or _pool_url != url:
        if _pool is not None:
            _pool.close()
        _pool = ConnectionPool(url, min_size=1, max_size=5, open=True)
        _pool_url = url
        with _pool.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cases (
                    case_id TEXT PRIMARY KEY,
                    data JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS cases_created_at_idx ON cases (created_at)")
    return _pool


def save(case: Case) -> None:
    if _use_postgres():
        with _pg().connection() as conn:
            conn.execute(
                """
                INSERT INTO cases (case_id, data, created_at) VALUES (%s, %s, %s)
                ON CONFLICT (case_id) DO UPDATE SET data = EXCLUDED.data
                """,
                (case.case_id, Jsonb(case.model_dump(mode="json")), case.created_at),
            )
        return

    path = _dir() / f"{case.case_id}.json"
    path.write_text(case.model_dump_json(indent=2))


def load(case_id: str) -> Case | None:
    if _use_postgres():
        with _pg().connection() as conn:
            row = conn.execute("SELECT data FROM cases WHERE case_id = %s", (case_id,)).fetchone()
        return Case.model_validate(row[0]) if row else None

    path = _dir() / f"{case_id}.json"
    if not path.exists():
        return None
    return Case.model_validate_json(path.read_text())


def all_cases() -> list[Case]:
    if _use_postgres():
        with _pg().connection() as conn:
            rows = conn.execute("SELECT data FROM cases ORDER BY created_at DESC").fetchall()
        cases = []
        for (data,) in rows:
            try:
                cases.append(Case.model_validate(data))
            except ValueError:
                continue
        return cases

    cases = []
    for path in sorted(_dir().glob("*.json")):
        try:
            cases.append(Case.model_validate_json(path.read_text()))
        except (json.JSONDecodeError, ValueError):
            continue
    return sorted(cases, key=lambda c: c.created_at, reverse=True)
