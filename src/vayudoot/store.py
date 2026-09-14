"""Persistence for the two things that outlive a request: cases and signals.

A complaint filed today is chased for weeks, and a satellite pass that happened
last night cannot be re-fetched after the fact, so both have to survive process
restarts — and, on a public deployment, a container that gets rebuilt or
redeployed under them. Two backends, chosen by whether `VAYUDOOT_DATABASE_URL`
is set:

* unset (the default, and what every test uses) — JSON files on disk. Fast,
  needs nothing running, and wrong for a public URL: the disk is ephemeral
  there.
* set — one row per object in Postgres, `data` as `jsonb`. Any standard Postgres
  works; nothing here is provider-specific.

Either way the interface above this module is the same handful of functions, so
the pipeline, the API, `clustering.py` and `scan.py` never know which backend
they are talking to.

Cases and signals are stored differently on purpose. A case is mutable and is
written back at every stage, so saving it upserts. A signal is a record that an
instrument observed something at a moment, which cannot change afterwards, so
saving one is an insert that does nothing if the observation is already held —
see `save_signals`.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .config import settings
from .schemas import Case, Signal

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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS signals (
                    signal_id TEXT PRIMARY KEY,
                    data JSONB NOT NULL,
                    observed_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS signals_observed_at_idx ON signals (observed_at)"
            )
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


# --------------------------------------------------------------------------- #
# Signals
# --------------------------------------------------------------------------- #


def _signal_dir() -> Path:
    """Where the JSON backend keeps signals: beside the case store, not in it.

    `all_cases` globs every `*.json` in the case directory and drops whatever
    fails to validate, so a signal filed in there would be read and thrown away
    on every listing. A sibling directory keeps the two globs from seeing each
    other's files without asking a deployment to configure a second path.
    """
    path = settings.vayudoot_case_dir.parent / "signals"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _signal_path(signal_id: str) -> Path:
    """One file per signal id, named so that the id and the file agree exactly.

    Signal ids are built to be stable, not to be filenames: they carry colons and
    decimal points (`viirs:28.61390:77.20900:2026-09-14T06:00:00+00:00`). The
    digest is what makes the mapping one-to-one, so `save_signals` can test for a
    duplicate by asking whether the file exists rather than by reading the whole
    store. The readable prefix is there only so a person looking for a particular
    station can find it by eye.
    """
    digest = hashlib.sha256(signal_id.encode()).hexdigest()[:12]
    slug = re.sub(r"[^a-z0-9]+", "-", signal_id.lower()).strip("-")[:48]
    return _signal_dir() / f"{slug}-{digest}.json"


def _aware(moment: datetime) -> datetime:
    """Treat a naive timestamp as UTC.

    Signals come from three sources and only some of them state a zone. Comparing
    a naive timestamp with an aware one raises, and handing a naive one to a
    `timestamptz` column makes Postgres guess the session's zone, so both
    backends normalise here rather than trusting the source.
    """
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def save_signals(signals: list[Signal]) -> int:
    """Persist signals and return how many of them had not been seen before.

    Deduplicated on `signal_id`, which every builder in `hotspots.py` constructs
    to identify the *observation* rather than the fetch — a VIIRS detection by
    its coordinates and acquisition time, a station reading by its station and
    parameter. That makes deduplication a correctness property rather than
    tidiness: a hotspot's severity rises with how persistent it looks and its
    confidence with how many sources agree, so a scan that ran twice over
    overlapping ground would otherwise talk the system into a more serious
    hotspot than the evidence supports.

    An id already held is left exactly as it was stored. The first record of an
    observation is the record; re-reading it later cannot tell us anything new
    about a moment that has already passed.
    """
    # Overlapping scan points routinely return the same detection inside one
    # batch, so the batch is collapsed before it reaches either backend.
    unique: dict[str, Signal] = {signal.signal_id: signal for signal in signals}
    if not unique:
        return 0

    if _use_postgres():
        inserted = 0
        with _pg().connection() as conn:
            for signal in unique.values():
                cursor = conn.execute(
                    """
                    INSERT INTO signals (signal_id, data, observed_at) VALUES (%s, %s, %s)
                    ON CONFLICT (signal_id) DO NOTHING
                    """,
                    (
                        signal.signal_id,
                        Jsonb(signal.model_dump(mode="json")),
                        _aware(signal.observed_at),
                    ),
                )
                inserted += cursor.rowcount or 0
        return inserted

    inserted = 0
    for signal in unique.values():
        path = _signal_path(signal.signal_id)
        if path.exists():
            continue
        path.write_text(signal.model_dump_json(indent=2))
        inserted += 1
    return inserted


def live_signals() -> list[Signal]:
    """Stored signals recent enough to still describe what is happening now.

    Anything older than `vayudoot_signal_retention_days` is history rather than a
    live hotspot: the fire is out, and leaving it in detection would hold a dot
    on the map long after there is anything at the place to look at. Nothing is
    deleted — `all_signals` still has it — because the record of what was
    observed is worth keeping even once it stops being current.
    """
    cutoff = datetime.now(UTC) - timedelta(days=settings.vayudoot_signal_retention_days)

    if _use_postgres():
        with _pg().connection() as conn:
            rows = conn.execute(
                "SELECT data FROM signals WHERE observed_at >= %s ORDER BY observed_at DESC",
                (cutoff,),
            ).fetchall()
        return _validated(row[0] for row in rows)

    return [s for s in all_signals() if _aware(s.observed_at) >= cutoff]


def all_signals() -> list[Signal]:
    """Every stored signal, most recently observed first.

    The whole record, retention window included, for tests and for answering
    "what did this instance actually see" when a hotspot needs explaining.
    """
    if _use_postgres():
        with _pg().connection() as conn:
            rows = conn.execute("SELECT data FROM signals ORDER BY observed_at DESC").fetchall()
        return _validated(row[0] for row in rows)

    signals = []
    for path in sorted(_signal_dir().glob("*.json")):
        try:
            signals.append(Signal.model_validate_json(path.read_text()))
        except (json.JSONDecodeError, ValueError):
            continue
    return sorted(signals, key=lambda s: _aware(s.observed_at), reverse=True)


def _validated(rows) -> list[Signal]:
    """Signals from stored rows, skipping any the current schema rejects.

    Same tolerance `all_cases` applies to a case file: one row written by an
    older version of the schema must not take down a whole listing.
    """
    signals = []
    for data in rows:
        try:
            signals.append(Signal.model_validate(data))
        except ValueError:
            continue
    return signals
