"""Cloud Firestore as a store backend, on Firebase's free Spark plan.

Chosen when `FIREBASE_SERVICE_ACCOUNT` is set; `store.py` picks the backend and
owns the interface, and this module only answers the calls it forwards. Spark
needs no card and no billing account, which is what makes Firestore usable here
at all (hard constraint 3): Firebase's other storage, Cloud Storage for Firebase,
now needs the paid Blaze plan, so photographs and imagery stay on disk.

Spark's limits shape everything below: 1 GiB stored, 50,000 document reads and
20,000 writes a day.

**Reads come from memory.** `/hotspots` reads every case and every live signal
on every request. Read from Firestore each time, a few hundred map views would
spend the day's reads. The API runs as one process (one uvicorn worker on
Render), and that process is the only writer, so it keeps what it has read in
memory and writes through: every write goes to Firestore first and then to the
mirror, and each collection is read from Firestore once per process start. A
second process writing to the same database would make each mirror stale. If
the deployment ever runs more than one worker, this backend needs Firestore's
snapshot listeners before it does.

**Signals are bucketed.** A scan stores hundreds of observations an hour; one
document per signal would cost a write each, and a read each on every cold
start (Render's free instance sleeps after 15 idle minutes, so there are many).
Signals are grouped by UTC observation day and by a hash of their id into
`SHARDS` documents a day, named like `2026-09-29-3`. A scan then costs at most
`SHARDS` writes per day it touches, and a cold start reads `SHARDS` documents per
day of the retention window. A document holds at most 1 MiB; eight of them
hold about 16,000 signals a day, far more than the scan finds.

**Objects are stored as JSON text.** Firestore rejects an array directly inside
an array, and the schemas change over time. A string holds whatever pydantic
writes, and it is validated on the way back exactly as the other backends
validate theirs.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from .config import settings
from .schemas import Case, ForecastRecord, HotspotAlert, Signal

#: Signal documents per observation day. See the module docstring.
SHARDS = 8

CASES = "cases"
ALERTS = "alerts"
FORECASTS = "forecasts"
SIGNALS = "signals"

M = TypeVar("M", bound=BaseModel)


class Remote(Protocol):
    """The four Firestore operations this backend needs, so tests can supply their own."""

    def read_all(self, collection: str) -> dict[str, dict[str, Any]]: ...

    def read_range(
        self, collection: str, field: str, low: str, high: str | None
    ) -> dict[str, dict[str, Any]]:
        """Documents whose `field` is at least `low` and, when given, below `high`."""
        ...

    def write(self, collection: str, doc_id: str, data: dict[str, Any]) -> None: ...


def service_account_info(value: str) -> dict[str, Any]:
    """The service-account key, given as its JSON text or as a path to the file.

    A hosting provider's environment variable holds the text; a developer's
    machine has the downloaded file. Either is accepted so neither has to be
    turned into the other.
    """
    text = value.strip()
    if not text.startswith("{"):
        text = Path(text).expanduser().read_text()
    return json.loads(text)


class FirestoreRemote:
    """`Remote` backed by the real Firestore client.

    The client library is imported here rather than at the top of the module, so
    a deployment on the JSON or Postgres backend never loads it or its gRPC stack.
    """

    def __init__(self, service_account: str, database: str) -> None:
        from google.cloud import firestore
        from google.oauth2 import service_account as sa

        info = service_account_info(service_account)
        self._db = firestore.Client(
            project=info["project_id"],
            credentials=sa.Credentials.from_service_account_info(info),
            database=database,
        )

    def read_all(self, collection: str) -> dict[str, dict[str, Any]]:
        return {doc.id: doc.to_dict() or {} for doc in self._db.collection(collection).stream()}

    def read_range(
        self, collection: str, field: str, low: str, high: str | None
    ) -> dict[str, dict[str, Any]]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = self._db.collection(collection).where(filter=FieldFilter(field, ">=", low))
        if high is not None:
            query = query.where(filter=FieldFilter(field, "<", high))
        return {doc.id: doc.to_dict() or {} for doc in query.stream()}

    def write(self, collection: str, doc_id: str, data: dict[str, Any]) -> None:
        self._db.collection(collection).document(doc_id).set(data)


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _day(moment: datetime) -> str:
    return _aware(moment).astimezone(UTC).date().isoformat()


def _shard_id(signal: Signal) -> str:
    # sha256 rather than hash(): Python salts str hashes per process, and a
    # signal must land in the same document after every restart.
    k = int(hashlib.sha256(signal.signal_id.encode()).hexdigest(), 16) % SHARDS
    return f"{_day(signal.observed_at)}-{k}"


class Backend:
    """The mirror and the remote it writes through to. One per process."""

    def __init__(self, remote: Remote) -> None:
        self.remote = remote
        self._lock = threading.RLock()
        #: collection -> document id -> JSON text; a collection is absent until read.
        self._records: dict[str, dict[str, str]] = {}
        #: signal document id -> signal id -> JSON text.
        self._shards: dict[str, dict[str, str]] = {}
        #: The mirror holds every signal document for this day and after; None
        #: until the first signal read.
        self._signals_from: str | None = None

    # ------------------------------------------------------------------ records

    def _collection(self, name: str) -> dict[str, str]:
        if name not in self._records:
            docs = self.remote.read_all(name)
            self._records[name] = {
                doc_id: data["json"]
                for doc_id, data in docs.items()
                if isinstance(data.get("json"), str)
            }
        return self._records[name]

    def put(self, name: str, doc_id: str, obj: BaseModel, at: datetime) -> None:
        text = obj.model_dump_json()
        with self._lock:
            # `at` is not read back; it is there so the Firestore console and a
            # Looker Studio source can sort documents without parsing the JSON.
            self.remote.write(name, doc_id, {"json": text, "at": _aware(at)})
            # A collection not yet read is left unread: its first read fetches
            # everything, this write included.
            if name in self._records:
                self._records[name][doc_id] = text

    def get(self, name: str, doc_id: str) -> str | None:
        with self._lock:
            return self._collection(name).get(doc_id)

    def texts(self, name: str) -> list[str]:
        with self._lock:
            return list(self._collection(name).values())

    # ------------------------------------------------------------------ signals

    def _signals_since(self, day: str) -> None:
        """Make sure the mirror holds every signal document from `day` onwards."""
        if self._signals_from is not None and day >= self._signals_from:
            return
        docs = self.remote.read_range(SIGNALS, "day", day, self._signals_from)
        for doc_id, data in docs.items():
            items = data.get("items") or []
            self._shards[doc_id] = {}
            for text in items:
                try:
                    signal_id = json.loads(text)["signal_id"]
                except (TypeError, ValueError, KeyError):
                    continue
                self._shards[doc_id][signal_id] = text
        self._signals_from = day

    def save_signals(self, signals: Iterable[Signal]) -> int:
        batch = list(signals)
        if not batch:
            return 0
        with self._lock:
            # Every document the batch touches must be in the mirror before it is
            # rewritten, or the rewrite would drop what an earlier process stored.
            self._signals_since(min(_day(s.observed_at) for s in batch))
            # Changes are built on copies and reach the mirror only once their
            # write has succeeded, so a failed write leaves the two in step.
            changed: dict[str, dict[str, str]] = {}
            inserted = 0
            for signal in batch:
                doc_id = _shard_id(signal)
                if doc_id not in changed:
                    changed[doc_id] = dict(self._shards.get(doc_id, {}))
                if signal.signal_id in changed[doc_id]:
                    continue
                changed[doc_id][signal.signal_id] = signal.model_dump_json()
                inserted += 1
            for doc_id, shard in changed.items():
                if len(shard) == len(self._shards.get(doc_id, {})):
                    continue
                self.remote.write(
                    SIGNALS, doc_id, {"day": doc_id[:10], "items": list(shard.values())}
                )
                self._shards[doc_id] = shard
            return inserted

    def signal_texts(self, since: date | None) -> list[str]:
        low = since.isoformat() if since else ""
        with self._lock:
            self._signals_since(low)
            return [
                text
                for doc_id, shard in self._shards.items()
                if doc_id[:10] >= low
                for text in shard.values()
            ]


_backend: Backend | None = None
_backend_key: tuple[str, str] | None = None


def _connect(service_account: str, database: str) -> Remote:
    return FirestoreRemote(service_account, database)


def backend() -> Backend:
    """The process's backend, rebuilt only if the configured account changes.

    In practice that is only ever a test switching settings; a running
    deployment never changes its own credentials.
    """
    global _backend, _backend_key
    key = (settings.firebase_service_account, settings.firebase_database)
    if _backend is None or _backend_key != key:
        _backend = Backend(_connect(*key))
        _backend_key = key
    return _backend


def reset() -> None:
    """Forget the mirror, as a process restart would. For tests."""
    global _backend, _backend_key
    _backend = None
    _backend_key = None


# --------------------------------------------------------------------------- #
# The calls `store.py` forwards
# --------------------------------------------------------------------------- #


def _parsed(model: type[M], texts: Iterable[str]) -> list[M]:
    out = []
    for text in texts:
        try:
            out.append(model.model_validate_json(text))
        except ValueError:
            continue
    return out


def save(case: Case) -> None:
    backend().put(CASES, case.case_id, case, case.created_at)


def load(case_id: str) -> Case | None:
    text = backend().get(CASES, case_id)
    return Case.model_validate_json(text) if text else None


def all_cases() -> list[Case]:
    cases = _parsed(Case, backend().texts(CASES))
    return sorted(cases, key=lambda c: _aware(c.created_at), reverse=True)


def save_signals(signals: list[Signal]) -> int:
    return backend().save_signals(signals)


def signals_since(cutoff: datetime | None) -> list[Signal]:
    since = _aware(cutoff).astimezone(UTC).date() if cutoff else None
    signals = _parsed(Signal, backend().signal_texts(since))
    if cutoff is not None:
        signals = [s for s in signals if _aware(s.observed_at) >= _aware(cutoff)]
    return sorted(signals, key=lambda s: _aware(s.observed_at), reverse=True)


def save_alert(alert: HotspotAlert) -> None:
    backend().put(ALERTS, alert.alert_id, alert, alert.created_at)


def load_alert(alert_id: str) -> HotspotAlert | None:
    text = backend().get(ALERTS, alert_id)
    return HotspotAlert.model_validate_json(text) if text else None


def all_alerts() -> list[HotspotAlert]:
    alerts = _parsed(HotspotAlert, backend().texts(ALERTS))
    return sorted(alerts, key=lambda a: _aware(a.created_at), reverse=True)


def save_forecast_record(record: ForecastRecord) -> None:
    backend().put(FORECASTS, record.forecast_id, record, record.made_at)


def load_forecast_record(forecast_id: str) -> ForecastRecord | None:
    text = backend().get(FORECASTS, forecast_id)
    return ForecastRecord.model_validate_json(text) if text else None


def forecast_records(since: datetime | None = None) -> list[ForecastRecord]:
    records = _parsed(ForecastRecord, backend().texts(FORECASTS))
    if since is not None:
        records = [r for r in records if _aware(r.made_at) >= _aware(since)]
    return sorted(records, key=lambda r: _aware(r.made_at), reverse=True)
