"""Pipeline control flow, exercised without a model provider."""

from __future__ import annotations

import pytest

from fakes import patch_stages
from vayudoot import pipeline, store
from vayudoot.schemas import CaseStatus, Report, Stage


def _report() -> Report:
    return Report(report_id="r1", latitude=28.6139, longitude=77.2090, note="Waste burning")


async def test_full_run_reaches_awaiting_confirmation(monkeypatch):
    patch_stages(monkeypatch, pipeline)
    case = await pipeline.run(_report())

    assert case.status is CaseStatus.AWAITING_CONFIRMATION
    assert case.stage is Stage.COMPLETE
    assert case.evidence and case.corroboration and case.jurisdiction and case.complaint
    assert case.address == "Minto Road, New Delhi, Delhi"
    # The pipeline stops here. Nothing is filed without a human.
    assert case.filed_at is None


async def test_every_stage_is_persisted_as_it_completes(monkeypatch):
    """The interface polls the stored case while the run is in flight."""
    patch_stages(monkeypatch, pipeline)
    seen: list[tuple[Stage, bool]] = []

    real_save = store.save

    def spy(case):
        seen.append((case.stage, case.complaint is not None))
        return real_save(case)

    monkeypatch.setattr(pipeline.store, "save", spy)
    case = await pipeline.run(_report())

    stages = [stage for stage, _ in seen]
    assert stages[0] is Stage.RECEIVED
    assert stages.index(Stage.EVIDENCE) < stages.index(Stage.CORROBORATION)
    assert stages.index(Stage.CORROBORATION) < stages.index(Stage.JURISDICTION)
    assert stages.index(Stage.JURISDICTION) < stages.index(Stage.DRAFTING)
    assert stages[-1] is Stage.COMPLETE
    # The complaint only exists on the last two saves, so a poller cannot read a
    # draft that was never written.
    assert not any(has_complaint for stage, has_complaint in seen if stage is Stage.DRAFTING)
    assert store.load(case.case_id).stage is Stage.COMPLETE


async def test_low_confidence_halts_before_any_other_stage_runs(monkeypatch):
    patch_stages(monkeypatch, pipeline, confidence=0.2)

    def explode(*args, **kwargs):
        raise AssertionError("corroboration must not run below the confidence floor")

    monkeypatch.setattr(pipeline, "corroborate", explode)
    case = await pipeline.run(_report())

    assert case.status is CaseStatus.REJECTED
    assert case.stage is Stage.HALTED
    assert case.corroboration is None
    assert case.complaint is None
    assert "below the" in case.history[-1]


@pytest.mark.parametrize("stage", ["evidence", "corroboration", "jurisdiction", "drafting"])
async def test_a_failing_stage_leaves_a_readable_case(monkeypatch, stage):
    patch_stages(monkeypatch, pipeline, fail_at=stage)
    case = await pipeline.run(_report())

    assert case.status is CaseStatus.FAILED
    # The stage stays parked on whatever was running when it died.
    assert case.stage is Stage(stage)
    assert f"{stage} exploded" in case.error
    stored = store.load(case.case_id)
    assert stored is not None and stored.status is CaseStatus.FAILED


async def test_run_continues_a_case_created_by_the_caller(monkeypatch):
    """The API saves a case and returns its id before the run starts."""
    patch_stages(monkeypatch, pipeline)
    report = _report()
    case = pipeline.new_case(report)
    store.save(case)

    result = await pipeline.run(report, case=case)
    assert result.case_id == case.case_id
    assert len(store.all_cases()) == 1
