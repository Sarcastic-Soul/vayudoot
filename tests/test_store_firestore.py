"""The Firestore backend, over an in-memory Firestore that counts what it bills.

What can go wrong here that the other backends do not share is the mirror: a
read served from memory that should have come from Firestore, or a rewrite of a
signal document that drops what an earlier process stored. The quota numbers
matter as much as correctness — Spark allows 50,000 reads and 20,000 writes a
day, and a backend that is right but spends them per page view stops working by
lunchtime. The whole rest of the suite can also run on this backend:
`VAYUDOOT_TEST_STORE=firestore pytest`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from fakes import MemoryFirestore
from vayudoot import firestore_store, hotspots, store
from vayudoot.config import settings
from vayudoot.schemas import (
    AlertStatus,
    Case,
    CaseStatus,
    ForecastRecord,
    HotspotAlert,
    HotspotSnapshot,
    Jurisdiction,
    Report,
    Signal,
    SignalSource,
)

NOW = datetime.now(UTC).replace(microsecond=0)


@pytest.fixture
def remote(monkeypatch) -> MemoryFirestore:
    fake = MemoryFirestore()
    monkeypatch.setattr(settings, "firebase_service_account", "memory")
    monkeypatch.setattr(firestore_store, "_connect", lambda *_: fake)
    firestore_store.reset()
    yield fake
    firestore_store.reset()


def restart() -> None:
    """What a Render instance waking from sleep does to the mirror."""
    firestore_store.reset()


def _case(case_id: str, age_hours: int = 0) -> Case:
    return Case(
        case_id=case_id,
        created_at=NOW - timedelta(hours=age_hours),
        status=CaseStatus.DRAFT,
        report=Report(report_id="r1", latitude=28.6139, longitude=77.2090),
    )


def _signal(n: int, age_hours: float = 1) -> Signal:
    seen = NOW - timedelta(hours=age_hours)
    return Signal(
        source=SignalSource.SATELLITE,
        signal_id=f"viirs:{28 + n / 1000:.5f}:77.20900:{seen.isoformat()}",
        latitude=28 + n / 1000,
        longitude=77.209,
        observed_at=seen,
        strength=0.8,
        summary="Satellite thermal detection",
    )


def test_firestore_wins_over_postgres_when_both_are_set(remote, monkeypatch):
    monkeypatch.setattr(settings, "database_url", "postgresql://nowhere.invalid/db")
    store.save(_case("VD-FS1"))
    assert remote.docs["cases"]["VD-FS1"]["json"]


def test_a_case_round_trips_and_is_upserted(remote):
    case = _case("VD-FS1")
    store.save(case)
    case.log("second stage")
    store.save(case)

    restart()
    loaded = store.load("VD-FS1")
    assert loaded is not None and loaded.case_id == "VD-FS1"
    assert any("second stage" in entry for entry in loaded.history)
    assert len(remote.docs["cases"]) == 1
    assert store.load("VD-MISSING") is None


def test_cases_list_newest_first(remote):
    store.save(_case("VD-OLD", age_hours=5))
    store.save(_case("VD-NEW", age_hours=1))
    restart()
    assert [c.case_id for c in store.all_cases()] == ["VD-NEW", "VD-OLD"]


def test_reads_after_the_first_come_from_memory(remote):
    """The map lists every case on every request; only the first may cost reads."""
    for n in range(5):
        store.save(_case(f"VD-FS{n}"))
    restart()

    store.all_cases()
    first = remote.reads
    for _ in range(50):
        store.all_cases()
        store.load("VD-FS3")
    assert first == 5
    assert remote.reads == first


def test_a_write_after_the_mirror_is_loaded_is_visible_without_a_read(remote):
    store.all_cases()
    reads = remote.reads
    store.save(_case("VD-LATE"))
    assert [c.case_id for c in store.all_cases()] == ["VD-LATE"]
    assert remote.reads == reads


def test_a_document_the_schema_rejects_is_skipped_not_fatal(remote):
    store.save(_case("VD-GOOD"))
    remote.docs["cases"]["VD-BAD"] = {"json": json.dumps({"case_id": "VD-BAD"})}
    restart()
    assert [c.case_id for c in store.all_cases()] == ["VD-GOOD"]


def test_signals_are_deduplicated_within_and_across_batches(remote):
    batch = [_signal(1), _signal(2), _signal(1)]
    assert store.save_signals(batch) == 2
    assert store.save_signals([_signal(2), _signal(3)]) == 1
    assert len(store.all_signals()) == 3


def test_a_scan_costs_a_handful_of_writes_not_one_per_signal(remote):
    """Two hundred observations in one day land in at most `SHARDS` documents."""
    assert store.save_signals([_signal(n) for n in range(200)]) == 200
    assert remote.writes <= firestore_store.SHARDS
    assert store.save_signals([_signal(n) for n in range(200)]) == 0
    assert remote.writes <= firestore_store.SHARDS, "a batch of duplicates rewrote a document"


def test_a_new_process_adds_to_a_signal_document_without_dropping_it(remote):
    """The rewrite that a merge needs must start from what is already stored."""
    first = [_signal(n) for n in range(40)]
    store.save_signals(first)
    restart()

    assert store.save_signals([_signal(n) for n in range(40, 80)]) == 40
    restart()
    assert {s.signal_id for s in store.all_signals()} >= {s.signal_id for s in first}
    assert len(store.all_signals()) == 80


def test_live_signals_honour_the_retention_window(remote, monkeypatch):
    monkeypatch.setattr(settings, "vayudoot_signal_retention_days", 3)
    store.save_signals([_signal(1, age_hours=2), _signal(2, age_hours=24 * 10)])
    restart()
    assert [s.latitude for s in store.live_signals()] == [28.001]
    assert len(store.all_signals()) == 2


def test_a_cold_start_reads_only_the_retention_window(remote, monkeypatch):
    """Render sleeps after fifteen idle minutes, so a cold start happens many times a day."""
    monkeypatch.setattr(settings, "vayudoot_signal_retention_days", 2)
    for day in range(30):
        store.save_signals([_signal(n, age_hours=24 * day + 1) for n in range(20)])
    restart()

    before = remote.reads
    store.live_signals()
    # The window touches three calendar days; the other twenty-seven are not read.
    assert remote.reads - before <= 3 * firestore_store.SHARDS
    reads = remote.reads
    store.live_signals()
    assert remote.reads == reads


def test_alerts_and_forecast_records_round_trip(remote):
    store.save_signals([_signal(1, age_hours=2), _signal(1, age_hours=30)])
    spot = hotspots.current()[0]
    alert = HotspotAlert(
        alert_id="VDA-FS000001",
        hotspot_id=spot.hotspot_id,
        hotspot=HotspotSnapshot.of(spot),
        area="Delhi",
        jurisdiction=Jurisdiction(
            authority_name="Delhi Pollution Control Committee",
            authority_tier="state",
            email="dpcc@dpcc.invalid",
            statute="Air (Prevention and Control of Pollution) Act, 1981",
            response_window_days=30,
        ),
        facts="FACTS",
        status=AlertStatus.AWAITING_CONFIRMATION,
    )
    store.save_alert(alert)
    record = ForecastRecord(
        forecast_id="VDF-FS000001",
        made_at=NOW - timedelta(days=2),
        latitude=28.6,
        longitude=77.2,
        location_name="Delhi",
        horizon_hours=72,
        window_start=NOW,
        window_end=NOW + timedelta(hours=72),
        risk="high",
        confidence=0.5,
        forecaster_version="test",
        prompt_sha256="0" * 64,
    )
    store.save_forecast_record(record)
    restart()

    assert store.load_alert("VDA-FS000001").facts == "FACTS"
    assert [a.alert_id for a in store.all_alerts()] == ["VDA-FS000001"]
    assert store.load_forecast_record("VDF-FS000001").risk == "high"
    assert store.forecast_records(since=NOW - timedelta(days=3))
    assert store.forecast_records(since=NOW - timedelta(days=1)) == []


def test_the_service_account_is_accepted_as_text_or_as_a_file(tmp_path):
    key = {"type": "service_account", "project_id": "vayudoot-test"}
    assert firestore_store.service_account_info(json.dumps(key)) == key
    path = tmp_path / "key.json"
    path.write_text(json.dumps(key))
    assert firestore_store.service_account_info(str(path)) == key
