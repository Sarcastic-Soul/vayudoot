"""Rendering a run, saving it, and diffing two of them.

Comparing a prompt before and after an edit is the whole point of the harness,
so the comparison is a command rather than something the reader does by eye
across two terminal scrollbacks. The run file is the unit of comparison: it
carries the per-case results, the metrics, and a fingerprint of every prompt, so
a diff can say *these two cases flipped, and here is the prompt that changed*.

The text report is written to be read in a terminal by someone who has just
edited a prompt and wants to know whether it helped. Failures come first and
carry the observed value; passes are one line each.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Metrics where a larger number is better. Everything numeric that is not in
#: here is treated as lower-is-better when a comparison decides the direction of
#: a change, which is why the two error rates and the Brier score are absent.
HIGHER_IS_BETTER = {
    "pass_rate",
    "check_pass_rate",
    "cases_passed",
    "classification_accuracy",
    "corroboration_accuracy",
    "structured_output_rate",
    "refusal_rate",
    "refusal_below_floor_rate",
    "distinct_confidences",
    "confidence_gap",
    "replay_integrity",
}

#: Metrics with no better or worse direction — reported, never scored.
NEUTRAL = {
    "cases_run",
    "cases_skipped",
    "mean_confidence",
    "min_confidence",
    "max_confidence",
}

STATUS_MARK = {"pass": "ok  ", "fail": "FAIL", "error": "ERR ", "skip": "skip"}


def save(run: dict[str, Any], directory: Path, label: str = "") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    mode = "live" if run.get("live") else "offline"
    suffix = f"-{_slug(label)}" if label else ""
    path = directory / f"{stamp}-{mode}{suffix}.json"
    path.write_text(json.dumps(run, indent=2, sort_keys=False, default=str), encoding="utf-8")
    return path


def load(path: str | Path) -> dict[str, Any]:
    run = json.loads(Path(path).read_text(encoding="utf-8"))
    if run.get("schema") != "vayudoot-eval-run/1":
        raise ValueError(f"{path} is not a vayudoot-eval-run/1 file")
    return run


def render(run: dict[str, Any]) -> str:
    lines: list[str] = []
    mode = "LIVE" if run.get("live") else "offline"
    lines.append(f"Vayudoot prompt eval — {mode} — manifest {run['manifest']}")
    if run.get("model"):
        model = run["model"]
        lines.append(
            f"  primary {model['primary_provider']}/{model['primary_id']}   "
            f"fast {model['fast_provider']}/{model['fast_id']}   "
            f"temperature {model['temperature']}"
        )
    calls = run.get("calls") or {}
    if calls.get("primary") or calls.get("fast"):
        lines.append(f"  spent {calls['primary']} primary and {calls['fast']} fast model calls")
    lines.append("")

    lines.extend(_guard_section(run.get("guards") or []))
    lines.extend(_case_section(run.get("cases") or []))
    lines.extend(_metric_section(run.get("metrics") or {}))
    return "\n".join(lines)


def _guard_section(guards: list[dict[str, Any]]) -> list[str]:
    if not guards:
        return []
    failed = [g for g in guards if not g["passed"]]
    lines = [f"PROMPT GUARDS  {len(guards) - len(failed)}/{len(guards)} holding"]
    for guard in failed:
        lines.append(f"  FAIL  {guard['id']}  ({guard['target']})")
        lines.append(f"        {guard['detail']}")
        lines.append(f"        why: {guard.get('why', '')}")
    lines.append("")
    return lines


def _case_section(cases: list[dict[str, Any]]) -> list[str]:
    if not cases:
        return []
    lines = ["CASES"]
    for case in cases:
        mark = STATUS_MARK.get(case["status"], case["status"])
        tag = " [synthetic]" if case.get("synthetic") else ""
        lines.append(f"  {mark}  {case['id']:<26} {case['kind']}{tag}")
        if case["status"] == "skip":
            lines.append(f"          {case.get('detail', '')}")
            continue
        if case["status"] == "error":
            # A provider error carries its whole JSON body, which is hundreds of
            # lines of quota metadata. The run file keeps all of it; the terminal
            # gets the first line, which is the part that says what went wrong.
            lines.append(f"          {_first_line(case.get('detail', ''))}")
            continue
        for check in case["checks"]:
            if not check["passed"]:
                lines.append(f"          x {check['name']}: {check['detail']}")
        if case["status"] == "fail":
            lines.append(f"          why this case exists: {case['why']}")
            notes = (case.get("observed") or {}).get("corroboration_notes") or ""
            if notes:
                lines.append(f"          notes: {notes[:200]}")
    lines.append("")
    return lines


def _first_line(text: str, limit: int = 160) -> str:
    head = text.strip().splitlines()[0] if text.strip() else ""
    return head if len(head) <= limit else head[:limit] + " ..."


def _metric_section(metrics: dict[str, Any]) -> list[str]:
    if not metrics:
        return []
    lines = ["SUMMARY"]
    width = max(len(k) for k in metrics)
    for key, value in metrics.items():
        lines.append(f"  {key:<{width}}  {_fmt(value)}")
    return lines


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def compare(before: dict[str, Any], after: dict[str, Any]) -> tuple[str, bool]:
    """Diff two runs. Returns the report and whether anything regressed.

    A regression is a case that used to pass and now does not, a guard that used
    to hold and now does not, or a case that now errors. Metrics move for
    reasons that include noise; case transitions are the thing to act on, so
    they decide the exit code and metrics are reported alongside.
    """
    lines = [
        f"Comparing  {before.get('finished_at', '?')}  ->  {after.get('finished_at', '?')}",
        f"  manifest {before['manifest']} -> {after['manifest']}",
        "",
    ]
    regressed = False

    changed_prompts = _fingerprint_diff(before, after)
    if changed_prompts:
        lines.append("PROMPTS CHANGED BETWEEN RUNS")
        for name, (old, new) in changed_prompts.items():
            lines.append(f"  {name}  {old} -> {new}")
        lines.append("")
    else:
        lines.append("No prompt or guarded schema text changed between these runs.")
        lines.append("")

    guard_lines, guard_regressed = _transitions(
        {g["id"]: g["passed"] for g in before.get("guards") or []},
        {g["id"]: g["passed"] for g in after.get("guards") or []},
        "GUARDS",
    )
    lines.extend(guard_lines)
    regressed |= guard_regressed

    case_lines, case_regressed = _transitions(
        {c["id"]: c["status"] for c in before.get("cases") or []},
        {c["id"]: c["status"] for c in after.get("cases") or []},
        "CASES",
    )
    lines.extend(case_lines)
    regressed |= case_regressed

    lines.extend(_metric_diff(before.get("metrics") or {}, after.get("metrics") or {}))
    lines.append("")
    lines.append("REGRESSED" if regressed else "No regression.")
    return "\n".join(lines), regressed


def _fingerprint_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, tuple[str, str]]:
    old = before.get("fingerprints") or {}
    new = after.get("fingerprints") or {}
    return {
        name: (old.get(name, "absent"), new.get(name, "absent"))
        for name in sorted(set(old) | set(new))
        if old.get(name) != new.get(name)
    }


def _transitions(
    before: dict[str, Any], after: dict[str, Any], heading: str
) -> tuple[list[str], bool]:
    """List every id whose status changed, and say whether any got worse."""
    lines = [heading]
    regressed = False
    moved = 0
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        moved += 1
        worse = _is_worse(old, new)
        regressed |= worse
        mark = "WORSE " if worse else "better" if _is_better(old, new) else "moved "
        lines.append(f"  {mark}  {key}: {_label(old)} -> {_label(new)}")
    if not moved:
        lines.append("  no change")
    lines.append("")
    return lines, regressed


def _label(value: Any) -> str:
    if value is None:
        return "absent"
    if value is True:
        return "pass"
    if value is False:
        return "fail"
    return str(value)


#: Statuses that mean "this case did not run here", either because the selection
#: excluded it or because its fixture is absent on this machine.
SOFT = {None, "skip"}


def _is_worse(old: Any, new: Any) -> bool:
    """A case that stopped running is not evidence that anything got worse.

    Running a subset is the normal way to use this harness — the primary tier's
    free allowance is about ten calls a day — and the optional photograph
    manifest skips wherever those files are absent. If either counted as a
    regression the exit code would be wrong the first time anyone passed
    `--limit`, and an exit code that is wrong is an exit code nobody gates on.

    A case that moves the other way, from skipped to failing, *is* a regression:
    it ran and it did not pass.
    """
    if new in SOFT:
        return False
    return _rank(old) > _rank(new)


def _is_better(old: Any, new: Any) -> bool:
    return _rank(old) < _rank(new)


def _rank(value: Any) -> int:
    """Order statuses so that a comparison can say which way a case moved."""
    return {True: 3, "pass": 3, None: 2, "skip": 2, False: 1, "fail": 1, "error": 0}.get(value, 2)


def _metric_diff(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    lines = ["METRICS"]
    keys = [k for k in {**before, **after} if k not in NEUTRAL or k in before or k in after]
    width = max((len(k) for k in keys), default=10)
    for key in keys:
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        arrow = _direction(key, old, new)
        lines.append(f"  {key:<{width}}  {_fmt(old)} -> {_fmt(new)}  {arrow}")
    if len(lines) == 1:
        lines.append("  no change")
    lines.append("")
    return lines


def _direction(key: str, old: Any, new: Any) -> str:
    if key in NEUTRAL or not isinstance(old, (int, float)) or not isinstance(new, (int, float)):
        return ""
    if new == old:
        return ""
    up = new > old
    good = up if key in HIGHER_IS_BETTER else not up
    return "better" if good else "worse"


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() or c == "-" else "-" for c in text.lower()).strip("-")[:40]
