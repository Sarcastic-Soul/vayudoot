"""Shared fixtures.

Every test that touches disk gets its own directory. `settings` is a module-level
singleton, so a test that forgets to redirect it writes into the developer's real
case store, which is both wrong and confusing.
"""

import pytest

from vayudoot.config import settings


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "vayudoot_case_dir", tmp_path / "cases")
    monkeypatch.setattr(settings, "vayudoot_upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "vayudoot_sandbox_outbox", tmp_path / "outbox")
    monkeypatch.setattr(settings, "vayudoot_live_filing", False)
    return tmp_path
