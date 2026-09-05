"""Filing safety is the one behaviour that must never regress.

A hackathon project that can email a real pollution control board is a liability,
so these tests assert the guard rails rather than the happy path.
"""

import pytest

from vayudoot.config import settings
from vayudoot.filing import LiveFilingNotConfigured, escalation_due, file_complaint
from vayudoot.schemas import Case, CaseStatus, Complaint, Jurisdiction, Report


def _case(tmp_path) -> Case:
    settings.vayudoot_sandbox_outbox = tmp_path / "outbox"
    return Case(
        case_id="VD-TEST0001",
        report=Report(report_id="r1", latitude=28.6139, longitude=77.2090),
        jurisdiction=Jurisdiction(
            authority_name="Test Board",
            authority_tier="state",
            email="board@example.invalid",
            statute="Air (Prevention and Control of Pollution) Act, 1981",
            response_window_days=30,
            escalation_email="central@example.invalid",
        ),
        complaint=Complaint(subject="Test complaint", body_en="Body."),
    )


def test_filing_writes_to_sandbox_not_the_network(tmp_path):
    settings.vayudoot_live_filing = False
    case = _case(tmp_path)
    path = file_complaint(case)
    assert path.exists()
    assert "X-Vayudoot-Mode: SANDBOX" in path.read_text()
    assert case.status is CaseStatus.FILED


def test_live_filing_refuses_without_a_configured_transport(tmp_path):
    case = _case(tmp_path)
    settings.vayudoot_live_filing = True
    try:
        with pytest.raises(LiveFilingNotConfigured):
            file_complaint(case)
    finally:
        settings.vayudoot_live_filing = False


def test_escalation_not_due_immediately_after_filing(tmp_path):
    settings.vayudoot_live_filing = False
    case = _case(tmp_path)
    file_complaint(case)
    assert escalation_due(case) is False
