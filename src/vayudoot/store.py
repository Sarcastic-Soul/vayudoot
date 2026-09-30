"""Persistence for what outlives a request: cases, signals and hotspot alerts.

A complaint filed today is chased for weeks, and a satellite pass that happened
last night cannot be re-fetched after the fact, so both have to survive process
restarts — and, on a public deployment, a container that gets rebuilt or
redeployed under them. Three backends, chosen by what is configured:

* nothing (the default, and what every test uses) — JSON files on disk. Fast,
  needs nothing running, and wrong for a public URL: the disk is ephemeral
  there.
* `FIREBASE_SERVICE_ACCOUNT` — Cloud Firestore on Firebase's free Spark plan,
  through an in-memory mirror that keeps reads inside the daily quota. The
  shipped deployment's choice, and it wins if both are set. See
  `firestore_store.py`, which holds all of it.
* `DATABASE_URL` — one row per object in Postgres, `data` as `jsonb`. Any
  standard Postgres works; nothing here is provider-specific.

Whichever it is, the interface above this module is the same handful of functions, so
the pipeline, the API, `clustering.py` and `scan.py` never know which backend
they are talking to.

Cases and signals are stored differently on purpose. A case is mutable and is
written back at every stage, so saving it upserts. A signal is a record that an
instrument observed something at a moment, which cannot change afterwards, so
saving one is an insert that does nothing if the observation is already held —
see `save_signals`. A hotspot alert is stored exactly like a case: it is drafted,
held for confirmation and then marked sent, so it too is upserted. So is a
forecast ledger record, which is written when the forecast is made and written
again when its outcome is scored.

Satellite imagery is the exception to "either backend": see "Imagery" below.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from . import firestore_store
from .config import settings
from .schemas import Case, ForecastRecord, HotspotAlert, ImageryReading, Signal

_pool: ConnectionPool | None = None
_pool_url: str | None = None
_pool_lock = threading.Lock()

#: Any fixed number; every process creating the schema takes the same lock.
_SCHEMA_LOCK = 0x76617975


def _use_firestore() -> bool:
    return bool(settings.firebase_service_account)


def _use_postgres() -> bool:
    return bool(settings.database_url) and not _use_firestore()


def _dir() -> Path:
    settings.vayudoot_case_dir.mkdir(parents=True, exist_ok=True)
    return settings.vayudoot_case_dir


def _pg() -> ConnectionPool:
    """The connection pool for the configured database, (re)opened whenever
    the URL changes — which in practice is only ever a test switching backends
    with `monkeypatch`, since a running deployment never changes its own URL.

    Opening is serialised twice over. FastAPI runs sync routes on a thread
    pool, so the first page load sends several requests here at once: without
    the thread lock each opened its own pool, and one could be handed a pool
    whose tables another thread had not created yet ("relation does not
    exist"). And `CREATE TABLE IF NOT EXISTS` is not safe when two sessions run
    it together — both pass the check and one fails on Postgres's catalogue
    ("duplicate key value violates unique constraint pg_type_typname_nsp_index")
    — so the schema is created under an advisory lock that also holds between
    processes. The pool is published only once its tables exist."""
    global _pool, _pool_url
    url = settings.database_url
    if _pool is not None and _pool_url == url:
        return _pool
    with _pool_lock:
        if _pool is not None and _pool_url == url:
            return _pool
        if _pool is not None:
            _pool.close()
            _pool = None
        pool = ConnectionPool(url, min_size=1, max_size=5, open=True)
        _create_schema(pool)
        _pool, _pool_url = pool, url
    return _pool


def _create_schema(pool: ConnectionPool) -> None:
    """Every table and index, in one transaction under `_SCHEMA_LOCK`."""
    with pool.connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK,))
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
        conn.execute("CREATE INDEX IF NOT EXISTS signals_observed_at_idx ON signals (observed_at)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                alert_id TEXT PRIMARY KEY,
                data JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS alerts_created_at_idx ON alerts (created_at)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS forecasts (
                forecast_id TEXT PRIMARY KEY,
                data JSONB NOT NULL,
                made_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS forecasts_made_at_idx ON forecasts (made_at)")


def save(case: Case) -> None:
    if _use_firestore():
        return firestore_store.save(case)
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
    if _use_firestore():
        return firestore_store.load(case_id)
    if _use_postgres():
        with _pg().connection() as conn:
            row = conn.execute("SELECT data FROM cases WHERE case_id = %s", (case_id,)).fetchone()
        return Case.model_validate(row[0]) if row else None

    path = _dir() / f"{case_id}.json"
    if not path.exists():
        return None
    return Case.model_validate_json(path.read_text())


def all_cases() -> list[Case]:
    if _use_firestore():
        return firestore_store.all_cases()
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

    if _use_firestore():
        return firestore_store.save_signals(list(unique.values()))

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

    if _use_firestore():
        return firestore_store.signals_since(cutoff)

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
    if _use_firestore():
        return firestore_store.signals_since(None)
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


# --------------------------------------------------------------------------- #
# Hotspot alerts
# --------------------------------------------------------------------------- #


def _alert_dir() -> Path:
    """Where the JSON backend keeps alerts: never the case directory.

    `all_cases` globs every `*.json` it finds there and drops what fails to
    validate, so an alert filed beside the cases would be read and silently
    thrown away on every listing — the reason signals have a directory of their
    own, applied again.
    """
    settings.vayudoot_alert_dir.mkdir(parents=True, exist_ok=True)
    return settings.vayudoot_alert_dir


def _safe_name(identifier: str) -> str:
    """An id that is safe to use as a filename, or ValueError.

    Alert and hotspot ids are generated by this system (`VDA-…`, `VDH-…`), but
    both also arrive in URL paths, and a path segment is whatever the caller
    typed. No underscore either: it separates the id from the date in an imagery
    filename, and allowing it in the id would make that split ambiguous.
    """
    if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", identifier):
        raise ValueError(f"Not a valid id: {identifier!r}")
    return identifier


def save_alert(alert: HotspotAlert) -> None:
    if _use_firestore():
        return firestore_store.save_alert(alert)
    if _use_postgres():
        with _pg().connection() as conn:
            conn.execute(
                """
                INSERT INTO alerts (alert_id, data, created_at) VALUES (%s, %s, %s)
                ON CONFLICT (alert_id) DO UPDATE SET data = EXCLUDED.data
                """,
                (alert.alert_id, Jsonb(alert.model_dump(mode="json")), _aware(alert.created_at)),
            )
        return

    path = _alert_dir() / f"{_safe_name(alert.alert_id)}.json"
    path.write_text(alert.model_dump_json(indent=2))


def load_alert(alert_id: str) -> HotspotAlert | None:
    if _use_firestore():
        return firestore_store.load_alert(alert_id)
    if _use_postgres():
        with _pg().connection() as conn:
            row = conn.execute(
                "SELECT data FROM alerts WHERE alert_id = %s", (alert_id,)
            ).fetchone()
        return HotspotAlert.model_validate(row[0]) if row else None

    try:
        path = _alert_dir() / f"{_safe_name(alert_id)}.json"
    except ValueError:
        return None
    if not path.exists():
        return None
    return HotspotAlert.model_validate_json(path.read_text())


def all_alerts() -> list[HotspotAlert]:
    """Every alert, newest first, skipping any the current schema rejects."""
    if _use_firestore():
        return firestore_store.all_alerts()
    if _use_postgres():
        with _pg().connection() as conn:
            rows = conn.execute("SELECT data FROM alerts ORDER BY created_at DESC").fetchall()
        alerts = []
        for (data,) in rows:
            try:
                alerts.append(HotspotAlert.model_validate(data))
            except ValueError:
                continue
        return alerts

    alerts = []
    for path in _alert_dir().glob("*.json"):
        try:
            alerts.append(HotspotAlert.model_validate_json(path.read_text()))
        except (json.JSONDecodeError, ValueError):
            continue
    return sorted(alerts, key=lambda a: _aware(a.created_at), reverse=True)


# --------------------------------------------------------------------------- #
# Forecast ledger
# --------------------------------------------------------------------------- #
#
# Every forecast served, and later what the stations recorded over its window.
# Stored on whichever backend is configured, unlike imagery: a forecast cannot
# be re-made after the fact, so a lost record is a hole in the skill score that
# nothing can fill. See `ledger.py`.


def _forecast_dir() -> Path:
    """Its own directory, for the reason alerts have one: never the case glob."""
    settings.vayudoot_forecast_dir.mkdir(parents=True, exist_ok=True)
    return settings.vayudoot_forecast_dir


def save_forecast_record(record: ForecastRecord) -> None:
    if _use_firestore():
        return firestore_store.save_forecast_record(record)
    if _use_postgres():
        with _pg().connection() as conn:
            conn.execute(
                """
                INSERT INTO forecasts (forecast_id, data, made_at) VALUES (%s, %s, %s)
                ON CONFLICT (forecast_id) DO UPDATE SET data = EXCLUDED.data
                """,
                (
                    record.forecast_id,
                    Jsonb(record.model_dump(mode="json")),
                    _aware(record.made_at),
                ),
            )
        return

    path = _forecast_dir() / f"{_safe_name(record.forecast_id)}.json"
    path.write_text(record.model_dump_json(indent=2))


def load_forecast_record(forecast_id: str) -> ForecastRecord | None:
    if _use_firestore():
        return firestore_store.load_forecast_record(forecast_id)
    if _use_postgres():
        with _pg().connection() as conn:
            row = conn.execute(
                "SELECT data FROM forecasts WHERE forecast_id = %s", (forecast_id,)
            ).fetchone()
        return ForecastRecord.model_validate(row[0]) if row else None

    try:
        path = _forecast_dir() / f"{_safe_name(forecast_id)}.json"
    except ValueError:
        return None
    if not path.exists():
        return None
    return ForecastRecord.model_validate_json(path.read_text())


def forecast_records(since: datetime | None = None) -> list[ForecastRecord]:
    """Ledger records made at or after `since`, newest first.

    Records the current schema rejects are skipped, as everywhere else here.
    """
    if _use_firestore():
        return firestore_store.forecast_records(since)
    if _use_postgres():
        with _pg().connection() as conn:
            if since is None:
                rows = conn.execute("SELECT data FROM forecasts ORDER BY made_at DESC").fetchall()
            else:
                rows = conn.execute(
                    "SELECT data FROM forecasts WHERE made_at >= %s ORDER BY made_at DESC",
                    (_aware(since),),
                ).fetchall()
        records = []
        for (data,) in rows:
            try:
                records.append(ForecastRecord.model_validate(data))
            except ValueError:
                continue
        return records

    records = []
    for path in _forecast_dir().glob("*.json"):
        try:
            record = ForecastRecord.model_validate_json(path.read_text())
        except (json.JSONDecodeError, ValueError):
            continue
        if since is None or _aware(record.made_at) >= _aware(since):
            records.append(record)
    return sorted(records, key=lambda r: _aware(r.made_at), reverse=True)


# --------------------------------------------------------------------------- #
# Imagery
# --------------------------------------------------------------------------- #
#
# A satellite snapshot and the model's reading of it, one pair per hotspot and
# image date, kept as files whatever backend is configured. That is a deliberate
# exception to the rest of this module, and it holds for three reasons.
#
# It is a cache, not a record. The snapshot can be fetched again from NASA GIBS
# at any time for free, so losing it on a redeploy costs at most one primary
# model call to read it again — the thing the cache exists to save, but not a
# thing that can be lost for good the way a case or a satellite pass can.
#
# Where the reading matters as a record, it is copied. A hotspot alert that
# cited an imagery reading carries the reading inside itself, and the alert is
# stored on whichever backend is configured.
#
# And the image has to be served back byte for byte: the operator must see the
# exact picture the model read, which is a file on disk rather than a JSON row.


def _imagery_dir() -> Path:
    settings.vayudoot_imagery_dir.mkdir(parents=True, exist_ok=True)
    return settings.vayudoot_imagery_dir


def _imagery_stem(hotspot_id: str, image_date: str) -> Path:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", image_date):
        raise ValueError(f"Not an image date: {image_date!r}")
    return _imagery_dir() / f"{_safe_name(hotspot_id)}_{image_date}"


def save_imagery(reading: ImageryReading, image: bytes) -> None:
    """Keep a snapshot and its reading together.

    The image is written first. A reading must never exist without the exact
    picture it describes beside it; an image without a reading is harmless and
    is simply read again.
    """
    stem = _imagery_stem(reading.hotspot_id, reading.image_date)
    stem.with_suffix(".jpg").write_bytes(image)
    stem.with_suffix(".json").write_text(reading.model_dump_json(indent=2))


def load_imagery(hotspot_id: str, image_date: str) -> ImageryReading | None:
    """The cached reading for one hotspot and image date, if both files exist."""
    try:
        stem = _imagery_stem(hotspot_id, image_date)
    except ValueError:
        return None
    if not (stem.with_suffix(".json").exists() and stem.with_suffix(".jpg").exists()):
        return None
    try:
        return ImageryReading.model_validate_json(stem.with_suffix(".json").read_text())
    except ValueError:
        return None


def latest_imagery(hotspot_id: str) -> ImageryReading | None:
    """The most recent cached reading for a hotspot, by image date."""
    try:
        prefix = _safe_name(hotspot_id)
    except ValueError:
        return None
    # ISO dates sort as strings, so the last file by name is the newest pass.
    for path in sorted(_imagery_dir().glob(f"{prefix}_*.json"), reverse=True):
        reading = load_imagery(hotspot_id, path.stem.removeprefix(f"{prefix}_"))
        if reading is not None:
            return reading
    return None


def imagery_image(hotspot_id: str, image_date: str) -> Path | None:
    """The cached snapshot file for one hotspot and date, if it is there."""
    try:
        path = _imagery_stem(hotspot_id, image_date).with_suffix(".jpg")
    except ValueError:
        return None
    return path if path.exists() else None
