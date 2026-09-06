"""Turning model answers into checks and checks into numbers.

Accuracy alone is not the thing to optimise here, so it is not the headline. Two
other properties matter more, because both are failure modes this project has
actually shipped:

**Calibration.** The pipeline halts a case below `CONFIDENCE_FLOOR`. That floor
is machinery that only works if the confidence means something — a model that
answers 0.95 to everything has 90% accuracy and a floor that never fires. So the
summary reports the spread of confidence, how much of it is saturated at the
top, and whether confidence is higher when the answer is right than when it is
wrong. That last number, `confidence_gap`, is the one to watch: a positive gap
is a confidence signal worth thresholding, a gap near zero is a constant wearing
a decimal point.

**Corroboration honesty.** Getting `corroborated` wrong is not symmetric. A
false negative under-claims and the complaint is filed on the citizen's word
alone, which is what the prompt already tells the drafting stage to say. A false
positive puts evidence into a legal document that no sensor ever produced. So
`false_corroboration_rate` — wrong answers on the cases where the honest answer
is "no" — is reported separately from accuracy, and is the number that should
never rise.

Every check carries the observed value in its detail, so a run file explains
itself without the reader going back to the manifest.
"""

from __future__ import annotations

import re
from typing import Any

from vayudoot.pipeline import CONFIDENCE_FLOOR
from vayudoot.schemas import Corroboration, EvidencePacket, PollutionType

from .manifest import Case

#: Confidence at or above this counts as saturated. The evidence prompt reserves
#: 0.9+ for an image "no reasonable person would read differently", so a fixture
#: set where most answers land here is a fixture set the model is not reading.
SATURATION = 0.95


def check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def score_evidence(case: Case, packet: EvidencePacket) -> list[dict[str, Any]]:
    """Checks for a classification or refusal case."""
    expect = case.expect
    accepted = {expect["pollution_type"], *(expect.get("also_acceptable") or [])}
    observed = packet.pollution_type.value

    checks = [
        check(
            "classification",
            observed in accepted,
            f"expected {' or '.join(sorted(accepted))}, got {observed}",
        )
    ]

    low = expect.get("confidence_min")
    high = expect.get("confidence_max")
    if low is not None or high is not None:
        floor_ok = low is None or packet.confidence >= float(low)
        ceil_ok = high is None or packet.confidence <= float(high)
        window = f"[{'-' if low is None else low}, {'-' if high is None else high}]"
        checks.append(
            check(
                "confidence_window",
                floor_ok and ceil_ok,
                f"confidence {packet.confidence:.2f} against {window}",
            )
        )

    # 1.0 is not a valid answer, and the prompt and the schema both say so. This
    # is the check that tells you whether that fix is still holding.
    checks.append(
        check(
            "not_certain",
            packet.confidence < 1.0,
            f"confidence {packet.confidence:.2f}",
        )
    )

    if case.kind == "refusal":
        # A refusal is only worth anything if the pipeline would act on it. The
        # evidence prompt asks for "unclear ... with low confidence" and the
        # pipeline halts below the floor, so both halves are checked, separately,
        # because a model that says `unclear` at 0.9 has failed differently from
        # one that says `industrial_emission`.
        checks.append(
            check(
                "below_floor",
                packet.confidence < CONFIDENCE_FLOOR,
                f"confidence {packet.confidence:.2f} against the {CONFIDENCE_FLOOR} floor",
            )
        )

    if expect.get("requires_indicators", True):
        checks.append(
            check(
                "gave_reasons",
                bool(packet.visible_indicators or packet.reasoning.strip()),
                f"{len(packet.visible_indicators)} indicator(s), "
                f"{len(packet.reasoning)} chars of reasoning",
            )
        )

    return checks


def score_corroboration(case: Case, result: Corroboration) -> list[dict[str, Any]]:
    """Checks for a corroboration case run over a recording."""
    expect = case.expect
    wanted = bool(expect["corroborated"])
    checks = [
        check(
            "corroborated",
            result.corroborated is wanted,
            f"expected {wanted}, got {result.corroborated}",
        )
    ]

    # The first corroboration bug was not a wrong answer, it was no answer: the
    # graph's structured output was dropped and every run fell through to an
    # empty fallback that happens to say corroborated=false. A case expecting
    # false would have passed while the stage was completely broken, so the
    # fallback's own sentinel text is checked for explicitly.
    checks.append(
        check(
            "structured_output",
            "returned no structured synthesis" not in result.corroboration_notes,
            result.corroboration_notes[:120] or "(no notes)",
        )
    )

    for field_name, wanted_value in (expect.get("fields") or {}).items():
        observed = getattr(result, field_name, None)
        checks.append(
            check(
                f"field:{field_name}",
                _close_enough(observed, wanted_value),
                f"expected {wanted_value!r}, got {observed!r}",
            )
        )

    # The second bug was an invented fact: the synthesis reasoned from a wind
    # bearing that industrial infrastructure was present upwind. No tool here can
    # establish that. This is a lexical check and therefore weaker than the
    # others — it catches the phrasing that shipped, not the idea.
    patterns = expect.get("notes_must_not_match") or []
    if patterns:
        prose = f"{result.corroboration_notes}\n{result.satellite_summary}\n" \
                f"{result.air_quality_summary}"
        hits = [p for p in patterns if re.search(p, prose, re.IGNORECASE)]
        checks.append(
            check(
                "no_invented_sources",
                not hits,
                f"matched {', '.join(hits)}" if hits else "no fabricated source claim",
            )
        )

    return checks


def _close_enough(observed: Any, wanted: Any) -> bool:
    if isinstance(wanted, (int, float)) and isinstance(observed, (int, float)):
        return abs(float(observed) - float(wanted)) <= 0.51
    return observed == wanted


def summarise(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll per-case results up into the numbers two runs get compared on.

    Only cases that actually ran contribute. A skipped case is not a passing one.
    """
    ran = [c for c in cases if c["status"] in ("pass", "fail")]
    evidence = [c for c in ran if c["kind"] in ("classification", "refusal")]
    # A corroboration case runs in both modes, but offline it only replays the
    # tools — no model answered, so there is no `corroborated` check to score.
    # Selecting on the check rather than the kind is what stops an offline run
    # reporting a corroboration accuracy of zero, which is not a low score but
    # an absent one.
    corroboration = [c for c in ran if _has(c, "corroborated")]

    metrics: dict[str, Any] = {
        "cases_run": len(ran),
        "cases_skipped": sum(1 for c in cases if c["status"] == "skip"),
        "cases_errored": sum(1 for c in cases if c["status"] == "error"),
        "cases_passed": sum(1 for c in ran if c["status"] == "pass"),
        "pass_rate": _ratio(sum(1 for c in ran if c["status"] == "pass"), len(ran)),
        "check_pass_rate": _ratio(
            sum(1 for c in ran for k in c["checks"] if k["passed"]),
            sum(len(c["checks"]) for c in ran),
        ),
    }
    replayed = [c for c in ran if _has(c, "replay_parses")]
    if replayed:
        metrics["replay_integrity"] = _ratio(
            sum(_named(c, "replay_parses") for c in replayed), len(replayed)
        )
    metrics.update(_evidence_metrics(evidence))
    metrics.update(_corroboration_metrics(corroboration))
    return metrics


def _has(case: dict[str, Any], name: str) -> bool:
    """Whether the named check ran at all, regardless of its result."""
    return any(entry["name"] == name for entry in case["checks"])


def _evidence_metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    if not cases:
        return {}

    correct = [_named(c, "classification") for c in cases]
    confidences = [float(c["observed"].get("confidence", 0.0)) for c in cases]
    refusals = [c for c in cases if c["kind"] == "refusal"]

    right = [conf for conf, ok in zip(confidences, correct, strict=True) if ok]
    wrong = [conf for conf, ok in zip(confidences, correct, strict=True) if not ok]

    metrics = {
        "classification_accuracy": _ratio(sum(correct), len(cases)),
        "mean_confidence": _mean(confidences),
        "min_confidence": round(min(confidences), 3),
        "max_confidence": round(max(confidences), 3),
        # A model that answers the same number every time has one distinct value
        # and a floor that can never fire. This is the cheapest possible read on
        # whether confidence carries information at all.
        "distinct_confidences": len({round(c, 2) for c in confidences}),
        "saturated_rate": _ratio(sum(1 for c in confidences if c >= SATURATION), len(confidences)),
        "certain_answers": sum(1 for c in confidences if c >= 1.0),
        # Brier score over the classifier's own confidence: mean squared error
        # between the stated confidence and whether the answer was right. Lower
        # is better, and unlike ECE it degrades gracefully at small N.
        "brier": _mean(
            [
                (conf - (1.0 if ok else 0.0)) ** 2
                for conf, ok in zip(confidences, correct, strict=True)
            ]
        ),
        "confidence_gap": (
            round(_mean(right) - _mean(wrong), 3) if right and wrong else None
        ),
    }
    if refusals:
        metrics["refusal_rate"] = _ratio(
            sum(_named(c, "classification") for c in refusals), len(refusals)
        )
        metrics["refusal_below_floor_rate"] = _ratio(
            sum(_named(c, "below_floor") for c in refusals), len(refusals)
        )
    return metrics


def _corroboration_metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    if not cases:
        return {}
    negatives = [c for c in cases if c["expected"].get("corroborated") is False]
    positives = [c for c in cases if c["expected"].get("corroborated") is True]
    metrics = {
        "corroboration_accuracy": _ratio(
            sum(_named(c, "corroborated") for c in cases), len(cases)
        ),
        "structured_output_rate": _ratio(
            sum(_named(c, "structured_output") for c in cases), len(cases)
        ),
    }
    if negatives:
        # The number that must never rise. A wrong `true` here is a sensor
        # reading asserted in a legal document that no sensor produced.
        metrics["false_corroboration_rate"] = _ratio(
            sum(not _named(c, "corroborated") for c in negatives), len(negatives)
        )
    if positives:
        metrics["missed_corroboration_rate"] = _ratio(
            sum(not _named(c, "corroborated") for c in positives), len(positives)
        )
    return metrics


def _named(case: dict[str, Any], name: str) -> bool:
    """Whether the named check passed. A check that did not run counts as failed.

    Deliberately not "counts as passed": the summary is read as a score, and a
    metric that silently improves when a check stops running is worse than no
    metric.
    """
    for entry in case["checks"]:
        if entry["name"] == name:
            return bool(entry["passed"])
    return False


def _ratio(part: float, whole: float) -> float | None:
    return None if not whole else round(part / whole, 3)


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def expected_summary(case: Case) -> dict[str, Any]:
    """The expectation, flattened into the run file so it is self-describing."""
    if case.kind == "corroboration":
        return {"corroborated": case.expect.get("corroborated")}
    return {
        "pollution_type": case.expect.get("pollution_type"),
        "also_acceptable": case.expect.get("also_acceptable") or [],
    }


def known_types() -> list[str]:
    return [t.value for t in PollutionType]
