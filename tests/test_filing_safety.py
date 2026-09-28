"""Filing safety is the one behaviour that must never regress.

A prototype that can email a real pollution control board is a liability, so these
tests assert the guard rails rather than the happy path.
"""

from datetime import UTC, datetime

import pytest

from vayudoot.config import settings
from vayudoot.filing import LiveFilingNotConfigured, escalation_due, file_alert, file_complaint
from vayudoot.schemas import (
    AlertBrief,
    AlertStatus,
    Case,
    CaseStatus,
    Complaint,
    Hotspot,
    HotspotAlert,
    HotspotSnapshot,
    Jurisdiction,
    PollutionType,
    Report,
    SignalSource,
)


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


# --------------------------------------------------------------------------- #
# Hotspot alerts
#
# An alert is addressed to an authority too, and unlike a complaint nobody
# asked for it: the system drafts it from a detection. It gets exactly the same
# guard rails — a sandbox file, a refusal when live filing is switched on, and
# a recipient on the reserved `.invalid` TLD whichever region it resolves to.
# --------------------------------------------------------------------------- #


def _alert(tmp_path, jurisdiction: Jurisdiction | None = None) -> HotspotAlert:
    settings.vayudoot_sandbox_outbox = tmp_path / "outbox"
    now = datetime.now(UTC)
    return HotspotAlert(
        alert_id="VDA-TEST0001",
        hotspot_id="VDH-TEST0001",
        hotspot=HotspotSnapshot(
            hotspot_id="VDH-TEST0001",
            pollution_type=PollutionType.UNCLEAR,
            centre_latitude=30.9,
            centre_longitude=75.85,
            radius_km=1.0,
            confidence=0.8,
            severity="moderate",
            corroborated=True,
            signal_count=2,
            source_counts={SignalSource.SATELLITE: 2},
            first_seen_at=now,
            last_seen_at=now,
            span_days=0,
        ),
        area="Ludhiana, Punjab",
        jurisdiction=jurisdiction or _case(tmp_path).jurisdiction,
        facts="Area: a circle of radius 1.0 km.",
        brief=AlertBrief(subject="Test alert", summary_en="Summary.", suggested_checks=[]),
        status=AlertStatus.AWAITING_CONFIRMATION,
    )


def test_an_alert_writes_to_sandbox_not_the_network(tmp_path):
    settings.vayudoot_live_filing = False
    alert = _alert(tmp_path)
    path = file_alert(alert, "Body.")
    assert path.exists()
    assert "X-Vayudoot-Mode: SANDBOX" in path.read_text()
    assert alert.status is AlertStatus.SENT


def test_live_filing_refuses_an_alert_too(tmp_path):
    alert = _alert(tmp_path)
    settings.vayudoot_live_filing = True
    try:
        with pytest.raises(LiveFilingNotConfigured):
            file_alert(alert, "Body.")
    finally:
        settings.vayudoot_live_filing = False
    assert alert.status is AlertStatus.AWAITING_CONFIRMATION
    assert not (tmp_path / "outbox").exists() or not any((tmp_path / "outbox").iterdir())


def test_an_unconfirmed_alert_cannot_be_filed(tmp_path):
    """Hard constraint 2 holds at the filing layer, not only at the route."""
    settings.vayudoot_live_filing = False
    alert = _alert(tmp_path)
    alert.status = AlertStatus.DRAFT
    with pytest.raises(ValueError):
        file_alert(alert, "Body.")


def test_every_alert_recipient_is_on_the_reserved_tld(monkeypatch):
    """Whatever state and category a hotspot resolves to, the address an alert
    would go to — and the one it would escalate to — is `.invalid`. Includes a
    state the table does not know, which falls back to the generic entry."""
    from vayudoot import alerts
    from vayudoot.tools.authorities import _load

    table = _load()
    categories = list(table["categories"])
    seen = 0
    for state, region in [*table["states"].items(), ("atlantis", {})]:
        cities = ["", *region.get("municipal", {})]
        for city in cities:
            for category in categories:
                geo = {"state": state, "city": city, "country_code": "in"}
                monkeypatch.setattr(alerts, "reverse_geocode", lambda *a, _g=geo, **k: _g)
                spot = _alert_hotspot(category)
                jurisdiction, _ = alerts.resolve_jurisdiction(spot)
                assert jurisdiction.email.endswith(".invalid"), (state, city, category)
                if jurisdiction.escalation_email:
                    assert jurisdiction.escalation_email.endswith(".invalid")
                seen += 1
    assert seen > len(categories)


def _alert_hotspot(category: str) -> Hotspot:
    try:
        pollution_type = PollutionType(category)
    except ValueError:
        pollution_type = PollutionType.UNCLEAR
    now = datetime.now(UTC)
    return Hotspot(
        hotspot_id="VDH-TEST0002",
        pollution_type=pollution_type,
        centre_latitude=30.9,
        centre_longitude=75.85,
        radius_km=1.0,
        confidence=0.8,
        severity="moderate",
        corroborated=True,
        signal_count=2,
        source_counts={SignalSource.SATELLITE: 2},
        first_seen_at=now,
        last_seen_at=now,
        span_days=0,
    )
