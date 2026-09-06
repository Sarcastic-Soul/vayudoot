"""Executing an eval, offline and live.

Two modes, and the split is not "fewer cases" versus "more". They check
different things.

**Offline** touches no model and no network. It validates the manifest, replays
every recording through the real tools to prove the fixtures still match the
code that reads them, and runs the prompt guards. Everything here is free, so it
should run on every prompt edit and in CI.

**Live** adds the model calls: the evidence stage over each image or note, and
the corroboration graph over each recording. This is the half that measures the
prompt, and it spends metered free-tier quota, so the runner counts the calls
before making any of them and the caller has to agree.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from vayudoot.config import settings
from vayudoot.schemas import EvidencePacket, Report

from . import guards, replay, scoring
from .manifest import Case, Manifest, projected_calls


def offline(manifest: Manifest, cases: list[Case]) -> dict[str, Any]:
    """The free half: fixture integrity plus prompt guards.

    The result has the same shape as a live run so that both go through the same
    report and the same comparison. Cases here carry `structural` checks only;
    no model saw anything.
    """
    started = datetime.now(UTC)
    results = [_offline_case(case) for case in cases]
    return _record(
        manifest=manifest,
        cases=results,
        guard_results=guards.run(manifest.guards),
        live=False,
        started=started,
    )


def _offline_case(case: Case) -> dict[str, Any]:
    runnable, why = case.runnable
    base = {
        "id": case.id,
        "kind": case.kind,
        "synthetic": case.synthetic,
        "why": case.why,
        "expected": scoring.expected_summary(case),
        "observed": {},
        "checks": [],
        "duration_s": 0.0,
    }
    if not runnable:
        return {**base, "status": "skip", "detail": why}

    if case.kind != "corroboration":
        # There is nothing to verify offline about an image beyond its being
        # readable, and the manifest loader already proved it exists.
        return {**base, "status": "skip", "detail": "needs a model; run with --live"}

    try:
        recording = replay.load(case.recording)
        outputs = replay.tool_outputs(recording, case.latitude, case.longitude)
    except Exception as exc:  # noqa: BLE001 - a broken fixture is a failed case
        return {**base, "status": "error", "detail": f"{type(exc).__name__}: {exc}"}

    checks = [
        scoring.check(
            "replay_parses",
            all(isinstance(value, dict) for value in outputs.values()),
            f"{len(outputs)} tool output(s)",
        )
    ]
    for path, wanted in (case.expect.get("tool_facts") or {}).items():
        observed = _dig(outputs, path)
        checks.append(
            scoring.check(
                f"tool:{path}",
                observed == wanted,
                f"expected {wanted!r}, got {observed!r}",
            )
        )

    return {
        **base,
        "status": "pass" if all(c["passed"] for c in checks) else "fail",
        "checks": checks,
        "observed": {"tools": outputs},
        "detail": "recording replayed through the real tools",
    }


def _dig(data: Any, path: str) -> Any:
    """Follow a dotted path like `firms.detection_count` into nested dicts."""
    for part in path.split("."):
        if isinstance(data, list):
            try:
                data = data[int(part)]
                continue
            except (ValueError, IndexError):
                return None
        if not isinstance(data, dict):
            return None
        data = data.get(part)
    return data


#: Requests a minute the free tier allows. Gemini's free tier caps
#: `gemini-3.5-flash-lite` at fifteen, and the corroboration graph fires three
#: source agents in parallel plus a synthesis node — four requests inside a few
#: seconds. Running cases back to back therefore exhausts a *per-minute* quota
#: long before the daily one, which is how the first live run of this harness
#: failed: one case answered and the other six came back 429.
DEFAULT_RPM = 15


async def live(manifest: Manifest, cases: list[Case], rpm: int = DEFAULT_RPM) -> dict[str, Any]:
    """The metered half. Assumes the caller has already agreed to the cost.

    Cases run one at a time with a pause sized to the calls the previous one
    made, so the request rate stays under `rpm`. Pass `rpm=0` to run flat out on
    a provider that does not meter by the minute.
    """
    started = datetime.now(UTC)
    results = []
    for index, case in enumerate(cases):
        if index and rpm > 0:
            await asyncio.sleep(_pause_after(cases[index - 1], rpm))
        results.append(await _live_case(case))
    return _record(
        manifest=manifest,
        cases=results,
        guard_results=guards.run(manifest.guards),
        live=True,
        started=started,
        calls=projected_calls([c for c, r in zip(cases, results, strict=True)
                              if r["status"] in ("pass", "fail")]),
    )


def _pause_after(case: Case, rpm: int) -> float:
    """Seconds to wait so that `case`'s calls fit inside the per-minute budget.

    A small margin is added, because the clock the provider counts on is not the
    one being measured here and landing exactly on the limit loses the race.
    """
    calls = sum(case.cost.values())
    return (60.0 * calls / rpm) + 1.0


async def _live_case(case: Case) -> dict[str, Any]:
    base = {
        "id": case.id,
        "kind": case.kind,
        "synthetic": case.synthetic,
        "why": case.why,
        "expected": scoring.expected_summary(case),
        "observed": {},
        "checks": [],
    }
    runnable, why = case.runnable
    if not runnable:
        return {**base, "status": "skip", "detail": why, "duration_s": 0.0}

    clock = time.perf_counter()
    try:
        if case.kind == "corroboration":
            observed, checks = await _run_corroboration(case)
        else:
            observed, checks = await _run_evidence(case)
    except Exception as exc:  # noqa: BLE001 - one broken case must not end the run
        return {
            **base,
            "status": "error",
            "detail": f"{type(exc).__name__}: {exc}",
            "duration_s": round(time.perf_counter() - clock, 2),
        }

    return {
        **base,
        "status": "pass" if all(c["passed"] for c in checks) else "fail",
        "checks": checks,
        "observed": observed,
        "detail": "",
        "duration_s": round(time.perf_counter() - clock, 2),
    }


async def _run_evidence(case: Case) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    # Imported here rather than at module scope so that offline mode never
    # touches the agent modules, and so `--live` is the only path that can
    # construct a model provider.
    from vayudoot.agents.evidence import analyse_evidence

    report = Report(
        report_id=f"eval-{uuid.uuid4().hex[:8]}",
        latitude=case.latitude,
        longitude=case.longitude,
        image_path=str(case.image) if case.image else None,
        note=case.note,
    )
    packet: EvidencePacket = await analyse_evidence(report)
    observed = {
        "pollution_type": packet.pollution_type.value,
        "confidence": packet.confidence,
        "severity": packet.severity,
        "visible_indicators": packet.visible_indicators,
        "landmarks": packet.landmarks,
        "reasoning": packet.reasoning,
    }
    return observed, scoring.score_evidence(case, packet)


async def _run_corroboration(case: Case) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from vayudoot.agents.corroboration import corroborate

    recording = replay.load(case.recording)
    evidence = EvidencePacket(
        pollution_type=case.pollution_type or "unclear",
        confidence=0.8,
        severity=case.severity,
        visible_indicators=case.visible_indicators,
        reasoning="Supplied by the eval fixture, not by a model.",
    )
    report = Report(
        report_id=f"eval-{uuid.uuid4().hex[:8]}",
        latitude=case.latitude,
        longitude=case.longitude,
        note=case.note,
    )

    with replay.replaying(recording) as consulted:
        result = await corroborate(report, evidence)

    checks = scoring.score_corroboration(case, result)
    # The agents choose whether to call their tool at all. If a source was never
    # consulted the synthesis was reasoning about nothing, and the case's answer
    # is uninformative rather than correct.
    checks.append(
        scoring.check(
            "sources_consulted",
            len(set(consulted)) >= 3,
            f"{sorted(set(consulted)) or 'none'}",
        )
    )
    return (
        {
            "corroborated": result.corroborated,
            "satellite_fire_detections": result.satellite_fire_detections,
            "nearest_station_km": result.nearest_station_km,
            "dominant_pollutant": result.dominant_pollutant,
            "wind_from_degrees": result.wind_from_degrees,
            "corroboration_notes": result.corroboration_notes,
            "satellite_summary": result.satellite_summary,
            "air_quality_summary": result.air_quality_summary,
            "sources_consulted": sorted(set(consulted)),
        },
        checks,
    )


def _record(
    manifest: Manifest,
    cases: list[dict[str, Any]],
    guard_results: list[dict[str, Any]],
    live: bool,
    started: datetime,
    calls: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "vayudoot-eval-run/1",
        "manifest": manifest.name,
        "manifest_path": str(manifest.path),
        "live": live,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": _model_description() if live else {},
        "calls": calls or {"primary": 0, "fast": 0},
        # Recorded so a comparison can point at the prompt that changed instead
        # of leaving the reader to work out why the numbers moved.
        "fingerprints": guards_fingerprints(manifest),
        "guards": guard_results,
        "cases": cases,
        "metrics": scoring.summarise(cases),
    }


def guards_fingerprints(manifest: Manifest) -> dict[str, str]:
    return guards.fingerprints(manifest.guards)


def _model_description() -> dict[str, str]:
    return {
        "primary_provider": settings.provider_for("primary"),
        "primary_id": settings.model_id_for("primary"),
        "fast_provider": settings.provider_for("fast"),
        "fast_id": settings.model_id_for("fast"),
        "temperature": str(settings.vayudoot_model_temperature),
    }
