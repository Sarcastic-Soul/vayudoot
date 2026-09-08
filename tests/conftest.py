"""Shared fixtures.

Every test that touches disk gets its own directory. `settings` is a module-level
singleton, so a test that forgets to redirect it writes into the developer's real
case store, which is both wrong and confusing.

The rate limiter is a module-level singleton for the same reason, and its
counters are in memory rather than on disk, so isolating storage is not enough:
without a reset, submissions made by one test count against the next one and the
suite starts failing in whatever order it happens to run.
"""

import pytest

from vayudoot.callbudget import budget as ollama_budget
from vayudoot.config import settings
from vayudoot.ratelimit import limiter


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "vayudoot_case_dir", tmp_path / "cases")
    monkeypatch.setattr(settings, "vayudoot_upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "vayudoot_sandbox_outbox", tmp_path / "outbox")
    monkeypatch.setattr(settings, "vayudoot_live_filing", False)
    # Force the JSON-file backend regardless of a developer's own shell — a
    # stray DATABASE_URL must never make the suite touch a real database.
    # test_store_postgres.py overrides this deliberately.
    monkeypatch.setattr(settings, "database_url", "")
    limiter.reset()
    ollama_budget.reset()
    return tmp_path
