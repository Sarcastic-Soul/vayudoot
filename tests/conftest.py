"""Shared fixtures.

Every test that touches disk gets its own directory. `settings` is a module-level
singleton, so a test that forgets to redirect it writes into the developer's real
case store, which is both wrong and confusing.

The rate limiter is a module-level singleton for the same reason, and its
counters are in memory rather than on disk, so isolating storage is not enough:
without a reset, submissions made by one test count against the next one and the
suite starts failing in whatever order it happens to run.
"""

import os

import pytest

from vayudoot.config import settings
from vayudoot.ratelimit import limiter


def pytest_collection_modifyitems(config, items):
    """Under `VAYUDOOT_TEST_STORE=firestore`, skip tests about the JSON files themselves."""
    if os.environ.get("VAYUDOOT_TEST_STORE") != "firestore":
        return
    skip = pytest.mark.skip(reason="exercises the JSON-file store directly")
    for item in items:
        if item.get_closest_marker("json_files"):
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "vayudoot_case_dir", tmp_path / "cases")
    monkeypatch.setattr(settings, "vayudoot_upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "vayudoot_sandbox_outbox", tmp_path / "outbox")
    monkeypatch.setattr(settings, "vayudoot_alert_dir", tmp_path / "alerts")
    monkeypatch.setattr(settings, "vayudoot_imagery_dir", tmp_path / "imagery")
    monkeypatch.setattr(settings, "vayudoot_forecast_dir", tmp_path / "forecasts")
    # Recording a forecast fetches its no-model baseline from Open-Meteo in the
    # background, which a test must not do by accident. test_ledger.py turns the
    # ledger back on with that request mocked.
    monkeypatch.setattr(settings, "vayudoot_forecast_ledger", False)
    monkeypatch.setattr(settings, "vayudoot_live_filing", False)
    # Force the JSON-file backend regardless of a developer's own shell — a
    # stray DATABASE_URL must never make the suite touch a real database.
    # test_store_postgres.py overrides this deliberately.
    monkeypatch.setattr(settings, "database_url", "")
    # Same for a Firebase key in `.env`: test_store_firestore.py swaps in an
    # in-memory Firestore, and nothing else may reach the real one.
    monkeypatch.setattr(settings, "firebase_service_account", "")
    if os.environ.get("VAYUDOOT_TEST_STORE") == "firestore":
        _use_memory_firestore(monkeypatch)
    limiter.reset()
    return tmp_path


def _use_memory_firestore(monkeypatch):
    """Run the whole suite against the Firestore backend, over an in-memory fake.

    `VAYUDOOT_TEST_STORE=firestore pytest` repeats every test that touches the
    store on that backend instead of JSON files, which is how the backend is
    shown to behave like the other two rather than only in its own tests. Each
    test gets an empty database and a cold mirror.
    """
    from fakes import MemoryFirestore
    from vayudoot import firestore_store

    remote = MemoryFirestore()
    monkeypatch.setattr(settings, "firebase_service_account", "memory")
    monkeypatch.setattr(firestore_store, "_connect", lambda *_: remote)
    firestore_store.reset()


@pytest.fixture(autouse=True)
def fresh_forecast_cache():
    """The API caches forecasts in memory; one test's answer must not be another's."""
    from vayudoot import api

    api._forecast_cache.clear()
    yield
    api._forecast_cache.clear()
