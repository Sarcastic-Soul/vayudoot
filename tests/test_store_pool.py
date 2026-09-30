"""Opening the Postgres pool under concurrent first requests, without a database.

`test_store_postgres.py` needs a real database and skips without one; this
does not, because the bug it guards against is in the Python, not the SQL.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import ClassVar

from vayudoot import store
from vayudoot.config import settings


class _FakePool:
    """Counts how many pools were opened and how many times a schema was made."""

    opened: ClassVar[list[_FakePool]] = []
    lock = threading.Lock()

    def __init__(self, url, **_):
        self.url = url
        self.schema_runs = 0
        self.ready = False
        with self.lock:
            _FakePool.opened.append(self)

    @contextmanager
    def connection(self):
        yield self

    def execute(self, sql, params=None):
        if "CREATE TABLE IF NOT EXISTS cases" in sql:
            self.schema_runs += 1
            # Widen the window a racing thread would slip through.
            time.sleep(0.05)
        if "forecasts_made_at_idx" in sql:
            self.ready = True

    def close(self):
        pass


def test_concurrent_first_requests_open_one_pool_and_see_its_tables(monkeypatch):
    """The first page load sends several requests at once, each on its own
    thread. Each used to open its own pool and run the schema, which on real
    Postgres failed with "duplicate key value violates unique constraint
    pg_type_typname_nsp_index", and a request could be handed a pool whose
    tables did not exist yet ("relation forecasts does not exist")."""
    _FakePool.opened = []
    monkeypatch.setattr(store, "ConnectionPool", _FakePool)
    monkeypatch.setattr(store, "_pool", None)
    monkeypatch.setattr(store, "_pool_url", None)
    monkeypatch.setattr(settings, "database_url", "postgresql://example.invalid/db")

    got: list[_FakePool] = []
    ready: list[bool] = []

    def first_request():
        pool = store._pg()
        got.append(pool)
        ready.append(pool.ready)

    threads = [threading.Thread(target=first_request) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(_FakePool.opened) == 1
    assert _FakePool.opened[0].schema_runs == 1
    assert all(pool is _FakePool.opened[0] for pool in got)
    assert all(ready), "a request was handed the pool before its tables existed"
