"""Postgres-backed persistence, exercised against a real database.

Skipped unless `DATABASE_URL` is actually configured — this is the one place
in the whole suite that talks to a real network service rather than the
default JSON-file backend every other test uses (`conftest.py` forces that
default for everything else, deliberately). Case ids are prefixed and the rows
are deleted afterwards, so this never leaves anything behind in whatever
database is configured.
"""

from __future__ import annotations

import pytest

from vayudoot import store
from vayudoot.config import Settings, settings
from vayudoot.schemas import Case, CaseStatus, Report

#: A separate Settings() reads `.env` directly, unaffected by conftest's
#: autouse fixture blanking the singleton's `database_url` for every test.
_REAL_DATABASE_URL = Settings().database_url

pytestmark = pytest.mark.skipif(
    not _REAL_DATABASE_URL,
    reason="DATABASE_URL is not configured; the Postgres backend is untested without it",
)


@pytest.fixture(autouse=True)
def postgres_backend(monkeypatch):
    monkeypatch.setattr(settings, "database_url", _REAL_DATABASE_URL)
    yield
    with store._pg().connection() as conn:
        conn.execute("DELETE FROM cases WHERE case_id LIKE 'VD-TESTPG%'")


def _case(case_id: str) -> Case:
    return Case(
        case_id=case_id,
        status=CaseStatus.DRAFT,
        report=Report(report_id="r1", latitude=28.6139, longitude=77.2090),
    )


def test_a_case_round_trips_through_postgres():
    case = _case("VD-TESTPG001")
    case.log("hello from the real database")
    store.save(case)

    loaded = store.load(case.case_id)
    assert loaded is not None
    assert loaded.history == case.history
    assert loaded.report.latitude == case.report.latitude


def test_saving_twice_updates_rather_than_duplicates():
    case = _case("VD-TESTPG002")
    store.save(case)
    case.status = CaseStatus.FILED
    store.save(case)

    with store._pg().connection() as conn:
        count = conn.execute(
            "SELECT count(*) FROM cases WHERE case_id = %s", (case.case_id,)
        ).fetchone()[0]
    assert count == 1
    assert store.load(case.case_id).status == CaseStatus.FILED


def test_a_missing_case_is_none():
    assert store.load("VD-TESTPG-NOPE") is None


def test_all_cases_includes_postgres_rows_newest_first():
    first = _case("VD-TESTPG010")
    store.save(first)
    second = _case("VD-TESTPG011")
    store.save(second)

    ids = [c.case_id for c in store.all_cases()]
    assert ids.index(second.case_id) < ids.index(first.case_id)
