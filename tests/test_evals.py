"""The harness that watches the prompts needs watching itself.

An eval that scores wrongly is worse than no eval: it reports a number, someone
trusts it, and a prompt gets edited in the wrong direction. So the scoring, the
manifest loader, the replay layer and the comparison are all exercised here —
offline, with no model and no network, in milliseconds.

Nothing in this file calls a model. The live half of the harness is tested by
running it; what is tested here is everything that decides what a live answer
*means*.

`scripts/` is not a package on the path, so it is added here rather than in
`pyproject.toml`: the harness is development tooling and the deployed service
must not import it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evalkit import guards, manifest, replay, report, runner, scoring

MANIFEST = ROOT / "evals" / "manifest.json"
LOCAL_MANIFEST = ROOT / "evals" / "manifest.local.json"


# --------------------------------------------------------------------------
# The committed fixture set
# --------------------------------------------------------------------------


def test_the_committed_manifest_loads_and_every_fixture_it_names_exists():
    """A fresh clone must be able to run the harness with no setup.

    Every image and recording the committed manifest points at is validated by
    the loader, so this failing means the fixture set is broken for everybody,
    not just here.
    """
    book = manifest.load(MANIFEST)
    assert book.cases and book.guards
    for case in book.cases:
        runnable, why = case.runnable
        assert runnable, f"{case.id}: {why}"


def test_the_committed_manifest_covers_all_three_axes():
    """A fixture set that quietly lost a whole axis still reports a pass rate."""
    kinds = {case.kind for case in manifest.load(MANIFEST).cases}
    assert kinds == set(manifest.KINDS)


def test_every_shipped_regression_has_a_case_or_a_guard():
    """The two bugs this harness exists for must stay covered by name.

    Renaming these fixtures is fine. Deleting them is what this catches.
    """
    book = manifest.load(MANIFEST)
    ids = {case.id for case in book.cases} | {guard.id for guard in book.guards}
    # Dropped structured output: the graph returned a NodeResult and the
    # synthesis answer was thrown away on every run.
    assert "corr-quiet-day" in ids
    # Corroboration invented from a wind bearing alone.
    assert "corr-wind-only" in ids
    assert "synthesis-wind-is-not-corroboration" in ids
    # A model that answered 1.00 to every photograph.
    assert "evidence-forbids-certainty" in ids


def test_the_local_manifest_is_valid_even_where_its_photographs_are_absent():
    """The optional manifest points outside the repository on purpose.

    It has to *load* anywhere — a case whose image is missing is skipped, not an
    error — or the harness stops working the moment someone clones this without
    the photographs.
    """
    book = manifest.load(LOCAL_MANIFEST)
    assert book.cases
    for case in book.cases:
        assert case.image is not None and case.image.is_absolute()


def test_a_case_whose_image_is_missing_is_skipped_rather_than_failed(tmp_path):
    case = manifest.Case(
        id="ghost",
        kind="classification",
        why="stand-in",
        expect={"pollution_type": "unclear"},
        image=tmp_path / "not-here.png",
    )
    runnable, why = case.runnable
    assert not runnable
    assert "not found" in why
    assert runner._offline_case(case)["status"] == "skip"


# --------------------------------------------------------------------------
# Manifest validation
# --------------------------------------------------------------------------


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "m.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


BASE_CASE = {
    "id": "c1",
    "kind": "classification",
    "why": "because",
    "note": "smoke",
    "expect": {"pollution_type": "open_waste_burning"},
}


@pytest.mark.parametrize(
    "mutation, fragment",
    [
        ({"kind": "vibes"}, "kind must be one of"),
        ({"expect": {"pollution_type": "smog"}}, "is not a PollutionType"),
        ({"expect": {"confidence_max": 1.4, "pollution_type": "unclear"}}, "between 0 and 1"),
        ({"why": "  "}, "needs a `why`"),
        ({"expect": {}}, "non-empty object"),
        ({"id": ""}, "has no id"),
        ({"note": "", "image": None}, "must carry a note"),
        ({"kind": "refusal"}, "must expect 'unclear'"),
        ({"kind": "corroboration"}, "needs a `recording`"),
    ],
)
def test_a_malformed_case_is_rejected_before_any_model_is_called(tmp_path, mutation, fragment):
    """Validation is strict on purpose.

    A typo in a manifest that only surfaces after eleven metered calls have been
    spent is a typo that gets found the expensive way.
    """
    with pytest.raises(manifest.ManifestError, match=fragment):
        manifest.load(_write(tmp_path, {"cases": [{**BASE_CASE, **mutation}]}))


def test_duplicate_case_ids_are_rejected(tmp_path):
    payload = {"cases": [BASE_CASE, {**BASE_CASE, "note": "different"}]}
    with pytest.raises(manifest.ManifestError, match="Duplicate case id"):
        manifest.load(_write(tmp_path, payload))


def test_a_guard_that_asserts_nothing_is_rejected(tmp_path):
    payload = {"guards": [{"id": "g", "target": "prompt:EVIDENCE", "why": "w"}]}
    with pytest.raises(manifest.ManifestError, match="asserts nothing"):
        manifest.load(_write(tmp_path, payload))


def test_selection_narrows_by_id_kind_and_limit():
    book = manifest.load(MANIFEST)
    assert [c.id for c in book.select(ids=["corr-quiet-day"])] == ["corr-quiet-day"]
    assert {c.kind for c in book.select(kinds=["corroboration"])} == {"corroboration"}
    assert len(book.select(limit=3)) == 3
    with pytest.raises(manifest.ManifestError, match="No such case"):
        book.select(ids=["nope"])


def test_the_projected_call_count_is_what_a_live_run_would_spend():
    """The number shown before spending quota has to be the real one.

    Evidence is one primary request. A corroboration case is seven fast ones:
    each of the three tool-using agents makes two requests, one to choose the
    tool call and one to summarise the result, and the synthesis node makes one.
    Counting agents instead of requests is what walked the first live run into a
    per-minute quota it believed it had room under.
    """
    book = manifest.load(MANIFEST)
    evidence = book.select(kinds=["classification", "refusal"])
    graph = book.select(kinds=["corroboration"])
    assert manifest.projected_calls(evidence) == {"primary": len(evidence), "fast": 0}
    assert manifest.projected_calls(graph) == {"primary": 0, "fast": 7 * len(graph)}


def test_live_pacing_keeps_the_corroboration_graph_under_a_per_minute_cap():
    """Found by running it: the free tier caps requests per *minute*, not just
    per day, and the graph makes four at once. Seven cases back to back returned
    one answer and six 429s, so the runner now waits between them."""
    book = manifest.load(MANIFEST)
    graph_case = book.select(kinds=["corroboration"], limit=1)[0]
    evidence_case = book.select(kinds=["classification"], limit=1)[0]
    # Seven requests at fifteen a minute is twenty-eight seconds, plus a margin.
    assert runner._pause_after(graph_case, rpm=15) == pytest.approx(29.0)
    assert runner._pause_after(evidence_case, rpm=15) == pytest.approx(5.0)
    # A faster allowance means less waiting, and the pacing scales with it.
    assert runner._pause_after(graph_case, rpm=60) < runner._pause_after(graph_case, rpm=15)


# --------------------------------------------------------------------------
# Prompt guards
# --------------------------------------------------------------------------


def test_every_committed_guard_holds_against_the_current_prompts():
    """The guards are the cheapest signal the harness has.

    If this fails, someone edited a prompt or a schema description and removed a
    line that a live run paid for. The guard's `why` says which one.
    """
    book = manifest.load(MANIFEST)
    failures = [g for g in guards.run(book.guards) if not g["passed"]]
    assert not failures, "\n".join(f"{g['id']}: {g['detail']} — {g['why']}" for g in failures)


def test_a_guard_matches_across_the_line_wrapping_of_a_prompt():
    """Prompts are hard-wrapped, so a guarded phrase usually straddles a newline.

    This is not hypothetical: the first version of the
    `synthesis-normal-is-not-corroboration` guard failed for exactly this reason
    while the prompt was intact.
    """
    guard = manifest.Guard(
        id="wrapped",
        target="prompt:SYNTHESIS",
        why="test",
        must_match=["A station reporting normal levels is not corroboration"],
    )
    assert guards.check(guard)["passed"]


def test_a_guard_fails_when_the_line_it_watches_is_deleted(monkeypatch):
    from vayudoot.agents import prompts

    monkeypatch.setattr(prompts, "SYNTHESIS", "Decide whether the report is corroborated.")
    guard = manifest.Guard(
        id="wind",
        target="prompt:SYNTHESIS",
        why="test",
        must_match=["weather is never corroboration"],
    )
    assert not guards.check(guard)["passed"]


def test_a_guard_pointed_at_nothing_fails_rather_than_raising():
    bad = ("prompt:NO_SUCH_PROMPT", "schema:Nope.field", "schema:Corroboration.nope", "x:y")
    for target in bad:
        result = guards.check(manifest.Guard(id="g", target=target, why="w", must_match=["a"]))
        assert not result["passed"]


def test_guards_can_watch_a_schema_field_description():
    """Field descriptions are prompt text: the structured-output call sends them."""
    text = guards.resolve("schema:Corroboration.corroborated")
    assert "Wind data alone" in text


def test_fingerprints_cover_every_prompt_and_change_when_one_does(monkeypatch):
    book = manifest.load(MANIFEST)
    before = guards.fingerprints(book.guards)
    assert {"prompt:EVIDENCE", "prompt:SYNTHESIS", "prompt:DRAFTING"} <= set(before)

    from vayudoot.agents import prompts

    monkeypatch.setattr(prompts, "SYNTHESIS", prompts.SYNTHESIS + "\nOne more sentence.")
    after = guards.fingerprints(book.guards)
    assert after["prompt:SYNTHESIS"] != before["prompt:SYNTHESIS"]
    assert after["prompt:EVIDENCE"] == before["prompt:EVIDENCE"]


# --------------------------------------------------------------------------
# Replay
# --------------------------------------------------------------------------


def test_every_recording_replays_through_the_real_tools():
    """A recording that has drifted from the tool that parses it is worthless.

    This is what makes the corroboration cases trustworthy: the model sees the
    same shape in an eval that it sees in production, because the same parsing
    code produced it.
    """
    book = manifest.load(MANIFEST)
    for case in book.select(kinds=["corroboration"]):
        outputs = replay.tool_outputs(
            replay.load(case.recording), case.latitude, case.longitude
        )
        assert set(outputs) == {"firms", "openaq", "weather"}
        for name, value in outputs.items():
            assert isinstance(value, dict), f"{case.id}/{name}"


def test_replay_restores_httpx_and_the_api_keys_afterwards():
    """The patch is per-module and temporary.

    A leaked patch would silently replay the *next* thing in the process, and in
    a live run the next thing is a model provider.
    """
    from vayudoot.config import settings
    from vayudoot.tools import firms, openaq, weather

    before = (firms.httpx, openaq.httpx, weather.httpx)
    keys = (settings.firms_map_key, settings.openaq_api_key)
    with replay.replaying({"open_meteo": {"json": {"current": {}}}}):
        assert firms.httpx is not before[0]
        assert settings.firms_map_key == "eval-replay"
    assert (firms.httpx, openaq.httpx, weather.httpx) == before
    assert (settings.firms_map_key, settings.openaq_api_key) == keys


def test_replay_reports_which_sources_were_consulted():
    recording = replay.load(ROOT / "evals" / "recordings" / "quiet-day.json")
    from vayudoot.tools import weather

    with replay.replaying(recording) as seen:
        weather.get_wind_conditions(latitude=28.6, longitude=77.2)
    assert seen == ["open_meteo"]


def test_a_missing_source_becomes_a_tool_error_not_an_exception():
    """Tools in this project return errors rather than raising, and the eval has
    to preserve that: "nothing answered" is a case the synthesis must handle."""
    outputs = replay.tool_outputs({}, 28.6, 77.2)
    assert all("error" in value for value in outputs.values())


def test_an_unknown_key_in_a_recording_is_rejected(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"firsm": {}}), encoding="utf-8")
    with pytest.raises(replay.RecordingError, match="unknown key"):
        replay.load(path)


def test_the_negative_recordings_really_do_carry_no_positive_signal():
    """The corroboration cases are only meaningful if their fixtures say what
    the manifest claims. A recording quietly edited to contain a fire would turn
    the sharpest negative in the set into a case that passes for the wrong
    reason."""
    book = manifest.load(MANIFEST)
    for case in book.select(kinds=["corroboration"]):
        if case.expect["corroborated"]:
            continue
        outputs = replay.tool_outputs(
            replay.load(case.recording), case.latitude, case.longitude
        )
        assert outputs["firms"].get("detection_count", 0) == 0, case.id
        for measurement in outputs["openaq"].get("measurements", []):
            if measurement["parameter"] == "pm25":
                assert measurement["value"] < 60, case.id


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


def _evidence_case(**expect) -> manifest.Case:
    return manifest.Case(
        id="e", kind=expect.pop("kind", "classification"), why="w", note="n", expect=expect
    )


def _packet(pollution_type="open_waste_burning", confidence=0.8, indicators=("smoke",)):
    from vayudoot.schemas import EvidencePacket

    return EvidencePacket(
        pollution_type=pollution_type,
        confidence=confidence,
        severity="high",
        visible_indicators=list(indicators),
        reasoning="because",
    )


def _named(checks, name):
    return next(c for c in checks if c["name"] == name)


def test_a_correct_classification_passes_and_a_wrong_one_does_not():
    case = _evidence_case(pollution_type="open_waste_burning")
    assert _named(scoring.score_evidence(case, _packet()), "classification")["passed"]
    wrong = _packet(pollution_type="vehicle_emission")
    assert not _named(scoring.score_evidence(case, wrong), "classification")["passed"]


def test_an_also_acceptable_answer_counts_as_correct():
    """Some photographs have more than one honest reading. Traffic under regional
    smog is the real example: both vehicle_emission and unclear are defensible,
    and forcing a single answer would score honesty as error."""
    case = _evidence_case(pollution_type="vehicle_emission", also_acceptable=["unclear"])
    checks = scoring.score_evidence(case, _packet(pollution_type="unclear"))
    assert _named(checks, "classification")["passed"]


def test_confidence_of_one_always_fails_however_right_the_answer_is():
    """1.0 is not a valid answer. The prompt says so, the schema says so, and a
    model already shipped that returned it on everything."""
    case = _evidence_case(pollution_type="open_waste_burning")
    checks = scoring.score_evidence(case, _packet(confidence=1.0))
    assert _named(checks, "classification")["passed"]
    assert not _named(checks, "not_certain")["passed"]


def test_a_refusal_is_only_scored_as_one_if_it_would_halt_the_pipeline():
    """`unclear` at high confidence is not a refusal.

    The pipeline halts below CONFIDENCE_FLOOR, so a confident `unclear` sails
    through into the drafting stage. The two halves are separate checks because
    they are separate failures.
    """
    from vayudoot.pipeline import CONFIDENCE_FLOOR

    case = _evidence_case(kind="refusal", pollution_type="unclear", requires_indicators=False)
    confident = scoring.score_evidence(case, _packet(pollution_type="unclear", confidence=0.9))
    assert _named(confident, "classification")["passed"]
    assert not _named(confident, "below_floor")["passed"]

    honest = scoring.score_evidence(
        case, _packet(pollution_type="unclear", confidence=CONFIDENCE_FLOOR - 0.1)
    )
    assert _named(honest, "below_floor")["passed"]


def test_the_confidence_window_is_enforced_at_both_ends():
    case = _evidence_case(
        pollution_type="open_waste_burning", confidence_min=0.5, confidence_max=0.9
    )
    assert _named(scoring.score_evidence(case, _packet(confidence=0.7)), "confidence_window")[
        "passed"
    ]
    for out_of_range in (0.3, 0.95):
        checks = scoring.score_evidence(case, _packet(confidence=out_of_range))
        assert not _named(checks, "confidence_window")["passed"]


def _corr_case(**expect) -> manifest.Case:
    return manifest.Case(
        id="c",
        kind="corroboration",
        why="w",
        expect={"corroborated": expect.pop("corroborated", False), **expect},
    )


def _corroboration(**kwargs):
    from vayudoot.schemas import Corroboration

    kwargs.setdefault("corroborated", False)
    kwargs.setdefault("corroboration_notes", "Nothing was detected.")
    return Corroboration(**kwargs)


def test_corroboration_is_scored_on_the_boolean_the_complaint_will_cite():
    case = _corr_case(corroborated=False)
    assert _named(scoring.score_corroboration(case, _corroboration()), "corroborated")["passed"]
    wrong = _corroboration(corroborated=True)
    assert not _named(scoring.score_corroboration(case, wrong), "corroborated")["passed"]


def test_the_empty_fallback_fails_even_though_its_answer_is_false():
    """The first corroboration bug produced exactly this object.

    Every run fell through to a fallback that says corroborated=false, so a
    suite of negative cases would have scored a broken stage at 100%. The
    fallback's own sentinel text is what tells the two apart.
    """
    fallback = _corroboration(
        corroborated=False,
        corroboration_notes="Corroboration graph returned no structured synthesis.",
    )
    checks = scoring.score_corroboration(_corr_case(corroborated=False), fallback)
    assert _named(checks, "corroborated")["passed"]
    assert not _named(checks, "structured_output")["passed"]


def test_an_invented_upwind_source_is_caught_in_the_notes():
    """The second shipped bug in prose form.

    Lexical, and therefore weaker than the other checks — it catches the
    phrasing that shipped, not the idea. That limit is why it is one check among
    several rather than the whole test.
    """
    case = _corr_case(
        corroborated=False,
        notes_must_not_match=[
            r"(factory|landfill)[^.]{0,40}\b(is|are|lies|located|situated|present)\b"
        ],
    )
    invented = _corroboration(
        corroboration_notes=(
            "No sensor returned a positive reading, but the wind is from 295 degrees "
            "and a factory is located at the upwind point."
        )
    )
    assert not _named(scoring.score_corroboration(case, invented), "no_invented_sources")["passed"]
    honest = _corroboration(
        corroboration_notes="The upwind point is 2 km to the north-west; what is there is unknown."
    )
    assert _named(scoring.score_corroboration(case, honest), "no_invented_sources")["passed"]


def test_a_numeric_field_expectation_tolerates_a_float_but_not_a_wrong_count():
    case = _corr_case(corroborated=True, fields={"satellite_fire_detections": 3})
    good = _corroboration(corroborated=True, satellite_fire_detections=3)
    assert _named(scoring.score_corroboration(case, good), "field:satellite_fire_detections")[
        "passed"
    ]
    bad = _corroboration(corroborated=True, satellite_fire_detections=1)
    assert not _named(scoring.score_corroboration(case, bad), "field:satellite_fire_detections")[
        "passed"
    ]


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------


def _scored(case_id, kind, status, checks, observed=None, expected=None):
    return {
        "id": case_id,
        "kind": kind,
        "status": status,
        "checks": [scoring.check(name, ok, "") for name, ok in checks],
        "observed": observed or {},
        "expected": expected or {},
    }


def test_a_saturated_classifier_is_visible_in_the_summary_at_full_accuracy():
    """The failure this project already shipped once: 90% accuracy and a
    confidence that carries no information, so the pipeline's floor never fires.
    Accuracy alone would call this an excellent run."""
    cases = [
        _scored(f"c{i}", "classification", "pass", [("classification", True)], {"confidence": 0.98})
        for i in range(5)
    ]
    metrics = scoring.summarise(cases)
    assert metrics["classification_accuracy"] == 1.0
    assert metrics["distinct_confidences"] == 1
    assert metrics["saturated_rate"] == 1.0


def test_confidence_gap_is_positive_when_confidence_tracks_correctness():
    cases = [
        _scored("a", "classification", "pass", [("classification", True)], {"confidence": 0.85}),
        _scored("b", "classification", "pass", [("classification", True)], {"confidence": 0.80}),
        _scored("c", "classification", "fail", [("classification", False)], {"confidence": 0.35}),
    ]
    metrics = scoring.summarise(cases)
    assert metrics["confidence_gap"] > 0
    assert metrics["brier"] < 0.2


def test_confidence_gap_is_none_when_nothing_was_got_wrong():
    """With no incorrect answers there is no gap to measure, and reporting a
    zero would read as "confidence carries no signal" rather than "not enough
    data" — a difference that matters at seventeen fixtures."""
    cases = [
        _scored("a", "classification", "pass", [("classification", True)], {"confidence": 0.8})
    ]
    assert scoring.summarise(cases)["confidence_gap"] is None


def test_a_false_corroboration_is_reported_separately_from_accuracy():
    """The asymmetry is the point. A wrong `false` under-claims; a wrong `true`
    puts a sensor reading into a legal document that no sensor produced."""
    cases = [
        _scored("neg", "corroboration", "fail", [("corroborated", False)],
                expected={"corroborated": False}),
        _scored("pos", "corroboration", "pass", [("corroborated", True)],
                expected={"corroborated": True}),
    ]
    metrics = scoring.summarise(cases)
    assert metrics["corroboration_accuracy"] == 0.5
    assert metrics["false_corroboration_rate"] == 1.0
    assert metrics["missed_corroboration_rate"] == 0.0


def test_an_offline_run_reports_no_corroboration_accuracy_at_all():
    """Offline, no model answered, so there is no accuracy — and reporting 0.0
    would look like a catastrophic score rather than an absent measurement."""
    run = runner.offline(manifest.load(MANIFEST), manifest.load(MANIFEST).cases)
    assert "corroboration_accuracy" not in run["metrics"]
    assert run["metrics"]["replay_integrity"] == 1.0


def test_a_skipped_case_is_not_a_passing_one():
    cases = [_scored("a", "classification", "skip", [])]
    metrics = scoring.summarise(cases)
    assert metrics["cases_run"] == 0
    assert metrics["cases_skipped"] == 1
    assert metrics["pass_rate"] is None


def test_a_check_that_did_not_run_counts_as_failed_not_as_passed():
    """A metric that improves when a check stops running is worse than none.

    The case below answered `corroborated` but never produced a
    `structured_output` check, so that rate has to read 0.0 rather than
    inheriting a pass from a check that was not there.
    """
    cases = [
        _scored("a", "corroboration", "fail", [("corroborated", True)],
                expected={"corroborated": False})
    ]
    metrics = scoring.summarise(cases)
    assert metrics["corroboration_accuracy"] == 1.0
    assert metrics["structured_output_rate"] == 0.0


# --------------------------------------------------------------------------
# The offline runner end to end
# --------------------------------------------------------------------------


def test_the_offline_run_passes_against_the_committed_fixtures():
    """This is what CI runs, and what should run after every prompt edit."""
    book = manifest.load(MANIFEST)
    run = runner.offline(book, book.cases)
    assert run["schema"] == "vayudoot-eval-run/1"
    assert run["live"] is False
    assert run["calls"] == {"primary": 0, "fast": 0}
    failed = [c for c in run["cases"] if c["status"] in ("fail", "error")]
    assert not failed, [(c["id"], c.get("detail")) for c in failed]
    assert all(g["passed"] for g in run["guards"])


def test_a_broken_recording_fails_its_case_without_ending_the_run(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    case = manifest.Case(
        id="broken", kind="corroboration", why="w", expect={"corroborated": False}, recording=bad
    )
    result = runner._offline_case(case)
    assert result["status"] == "error"
    assert "RecordingError" in result["detail"] or "JSON" in result["detail"]


def test_the_offline_run_renders_without_a_model_section():
    book = manifest.load(MANIFEST)
    text = report.render(runner.offline(book, book.select(kinds=["corroboration"])))
    assert "offline" in text
    assert "PROMPT GUARDS" in text
    assert "SUMMARY" in text


# --------------------------------------------------------------------------
# Comparison — the operation the harness exists for
# --------------------------------------------------------------------------


def _run_record(cases, guards_=(), fingerprints=None, metrics=None):
    return {
        "schema": "vayudoot-eval-run/1",
        "manifest": "test",
        "live": True,
        "finished_at": "2026-01-01T00:00:00+00:00",
        "fingerprints": fingerprints or {"prompt:SYNTHESIS": "aaa"},
        "guards": [{"id": g, "passed": ok} for g, ok in guards_],
        "cases": [{"id": cid, "status": status} for cid, status in cases],
        "metrics": metrics or {},
    }


def test_a_case_that_stopped_passing_is_a_regression():
    before = _run_record([("a", "pass"), ("b", "pass")])
    after = _run_record([("a", "pass"), ("b", "fail")])
    text, regressed = report.compare(before, after)
    assert regressed
    assert "WORSE" in text and "b: pass -> fail" in text


def test_a_case_that_started_passing_is_not_a_regression():
    text, regressed = report.compare(
        _run_record([("a", "fail")]), _run_record([("a", "pass")])
    )
    assert not regressed
    assert "better" in text


def test_a_guard_that_stopped_holding_is_a_regression():
    before = _run_record([], guards_=[("g", True)])
    after = _run_record([], guards_=[("g", False)])
    _, regressed = report.compare(before, after)
    assert regressed


def test_running_a_subset_is_not_reported_as_a_regression():
    """Skipping is the normal way to run this harness on a free tier.

    If a narrower selection counted as a regression, the exit code would be
    useless the first time anyone used --limit.
    """
    before = _run_record([("a", "pass"), ("b", "pass")])
    after = _run_record([("a", "pass"), ("b", "skip")])
    _, regressed = report.compare(before, after)
    assert not regressed


def test_a_changed_prompt_is_named_in_the_comparison():
    """Two runs differ for a reason. The comparison points at it rather than
    leaving the reader to guess which edit moved the numbers."""
    before = _run_record([("a", "pass")], fingerprints={"prompt:SYNTHESIS": "aaa"})
    after = _run_record([("a", "fail")], fingerprints={"prompt:SYNTHESIS": "bbb"})
    text, regressed = report.compare(before, after)
    assert regressed
    assert "PROMPTS CHANGED" in text
    assert "prompt:SYNTHESIS  aaa -> bbb" in text


def test_identical_runs_compare_clean():
    run = _run_record([("a", "pass")], guards_=[("g", True)], metrics={"pass_rate": 1.0})
    text, regressed = report.compare(run, run)
    assert not regressed
    assert "No regression." in text
    assert "No prompt or guarded schema text changed" in text


def test_metric_moves_are_labelled_in_the_direction_that_is_actually_better():
    """`false_corroboration_rate` going up is worse; accuracy going up is better.
    A comparison that got this backwards would recommend the wrong edit."""
    before = _run_record([], metrics={"false_corroboration_rate": 0.0, "pass_rate": 0.5})
    after = _run_record([], metrics={"false_corroboration_rate": 0.5, "pass_rate": 0.9})
    text, _ = report.compare(before, after)
    assert "false_corroboration_rate  0.000 -> 0.500  worse" in text
    assert "pass_rate                 0.500 -> 0.900  better" in text


def test_a_run_survives_a_round_trip_through_disk(tmp_path):
    book = manifest.load(MANIFEST)
    run = runner.offline(book, book.select(kinds=["corroboration"], limit=2))
    path = report.save(run, tmp_path, label="round trip")
    assert path.parent == tmp_path and "round-trip" in path.name
    assert report.load(path)["cases"] == run["cases"]


def test_a_file_that_is_not_a_run_record_is_refused(tmp_path):
    path = tmp_path / "other.json"
    path.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    with pytest.raises(ValueError, match="vayudoot-eval-run/1"):
        report.load(path)


# --------------------------------------------------------------------------
# The command line
# --------------------------------------------------------------------------


def _cli():
    import importlib.util

    spec = importlib.util.spec_from_file_location("vayudoot_eval_cli", ROOT / "scripts" / "eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_default_invocation_is_the_free_one():
    """`uv run python scripts/eval.py` with no arguments must never spend quota."""
    args = _cli()._parse([])
    assert args.command == "run"
    assert args.live is False


def test_options_work_without_naming_the_default_subcommand():
    args = _cli()._parse(["--kind", "corroboration", "--limit", "2"])
    assert args.command == "run" and args.kind == ["corroboration"] and args.limit == 2


def test_the_pacing_default_is_applied_without_being_asked_for():
    """The rate limit is the provider's, not the user's problem to remember."""
    assert _cli()._parse([]).rpm == runner.DEFAULT_RPM


def test_a_live_run_refuses_to_spend_quota_unattended(monkeypatch, capsys):
    """Without a terminal to confirm at and without --yes, it stops.

    A harness that could be triggered into spending a day's primary allowance by
    something non-interactive would be switched off, and an eval nobody runs is
    worse than none.
    """
    cli = _cli()
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    book = manifest.load(MANIFEST)
    assert cli._confirm(book.select(kinds=["classification"]), yes=False) is False
    assert "Refusing to spend quota" in capsys.readouterr().out


def test_the_projected_cost_is_printed_before_anything_is_spent(monkeypatch, capsys):
    cli = _cli()
    book = manifest.load(MANIFEST)
    assert cli._confirm(book.select(kinds=["corroboration"]), yes=True) is True
    out = capsys.readouterr().out
    assert "primary calls: 0" in out
    assert "fast calls:    49" in out


def test_an_oversized_live_selection_warns_about_the_daily_allowance(monkeypatch, capsys):
    cli = _cli()
    monkeypatch.setattr(cli, "PRIMARY_BUDGET_PER_DAY", 2)
    book = manifest.load(MANIFEST)
    cli._confirm(book.select(kinds=["classification", "refusal"]), yes=True)
    assert "exceeds a day's primary allowance" in capsys.readouterr().out


def test_the_cli_exits_non_zero_when_a_guard_fails():
    cli = _cli()
    passing = {"cases": [{"id": "a", "status": "pass"}], "guards": [{"id": "g", "passed": True}]}
    failing = {"cases": [{"id": "a", "status": "pass"}], "guards": [{"id": "g", "passed": False}]}
    assert cli._exit_code(passing) == 0
    assert cli._exit_code(failing) == 1
