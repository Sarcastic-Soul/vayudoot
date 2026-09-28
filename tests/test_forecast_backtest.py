"""The backtest's own arithmetic: what the model is shown, and how it is compared.

No network and no model. The backtest's worth is entirely in not letting the
answer into the question, so the pieces that decide what the model sees are
tested as closely as the scoring.
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import forecast_backtest as bt

ISSUED = datetime(2025, 11, 5, tzinfo=UTC)


def hourly(first: str, count: int) -> dict:
    """An Open-Meteo `hourly` block: naive UTC times, one value per hour."""
    start = datetime.fromisoformat(first)
    stamps = [(start + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(count)]
    return {"time": stamps, "pm2_5": list(range(count))}


def test_the_model_sees_hours_from_the_issue_time_not_from_the_run():
    """A wind run starts twelve hours before the issue time; those hours are
    the past and are not offered as forecast."""
    run = hourly("2025-11-04T12:00", 132)

    sliced = bt._slice(run, ISSUED, 72)

    assert sliced["pm2_5"][0] == 12
    assert len(sliced["pm2_5"]) == 72


def test_the_dates_the_model_sees_are_moved_a_whole_number_of_weeks():
    sliced = bt._slice(hourly("2025-11-05T00:00", 72), ISSUED, 72)

    first = datetime.fromisoformat(sliced["time"][0])
    assert first.date() == date(2026, 11, 4)
    assert first.weekday() == ISSUED.weekday()


def test_a_series_that_does_not_reach_the_issue_time_gives_nothing():
    assert bt._slice(hourly("2025-11-06T00:00", 72), ISSUED, 72) == {}


def test_agent_cases_are_chosen_without_looking_at_the_outcome():
    """Two sets of rows identical but for what was observed pick the same cases.
    Choosing on the outcome would tilt the sample towards easy days."""
    cases = {c.case_id: c for c in bt.all_cases()[:40]}

    def rows(observed: str) -> list[dict]:
        return [
            {"case_id": cid, "group": c.group, "observed": observed,
             "persistence": "high", "cams": "elevated"}
            for cid, c in cases.items()
        ]

    first = [c.case_id for c in bt.pick_agent_cases(rows("low"), cases, seed=7)]
    second = [c.case_id for c in bt.pick_agent_cases(rows("severe"), cases, seed=7)]
    assert first == second


def test_every_method_is_scored_on_the_same_rows():
    rows = [
        {"observed": "high", "agent": "high", "persistence": "high", "cams": "elevated"},
        {"observed": "low", "agent": "elevated", "persistence": None, "cams": "low"},
    ]

    summary = bt.summarise(rows, ["agent", "persistence", "cams"])

    assert summary["n"] == 1
    assert summary["methods"]["agent"]["exact"] == 1
    assert summary["methods"]["cams"]["exact"] == 0
    assert summary["methods"]["cams"]["agent_vs"] == {
        "agent_right_only": 1, "baseline_right_only": 0, "p_value": 1.0,
    }


@pytest.mark.parametrize(
    ("hits", "n", "low", "high"),
    [(0, 10, 0.0, 0.278), (5, 10, 0.237, 0.763), (10, 10, 0.722, 1.0)],
)
def test_the_interval_is_wilsons(hits, n, low, high):
    got = bt.wilson(hits, n)
    assert got[0] == pytest.approx(low, abs=0.001)
    assert got[1] == pytest.approx(high, abs=0.001)


@pytest.mark.parametrize(
    ("wins", "losses", "p"),
    [(0, 0, 1.0), (5, 5, 1.0), (8, 0, 0.0078), (9, 1, 0.0215)],
)
def test_the_sign_test_is_exact(wins, losses, p):
    assert bt.sign_test(wins, losses) == pytest.approx(p, abs=0.0005)
