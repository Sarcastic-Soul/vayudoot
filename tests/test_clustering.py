"""Repeat-report clustering.

Clustering is pure logic over stored cases, so almost all of it can be pinned
down exactly. The tests that matter most are the negative ones: what must *not*
group. A cluster is quoted in a legal document, so a wrong grouping is a false
statement to a regulator, which is worse than no grouping at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fakes import StubAgent, complaint
from vayudoot import clustering, store
from vayudoot.agents.drafting import draft_complaint
from vayudoot.config import settings
from vayudoot.schemas import (
    Case,
    CaseStatus,
    EvidencePacket,
    PollutionType,
    Report,
)
from vayudoot.tools.geo import point_at

BASE = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
LAT, LON = 28.6139, 77.2090

_counter = iter(range(1, 10_000))


def make_case(
    *,
    days: float = 0.0,
    metres_east: float = 0.0,
    pollution_type: PollutionType = PollutionType.OPEN_WASTE_BURNING,
    status: CaseStatus = CaseStatus.AWAITING_CONFIRMATION,
    contact: str = "",
    evidence: bool = True,
    save: bool = True,
) -> Case:
    """A case at a controlled offset from the origin, in time and in metres."""
    lat, lon = point_at(LAT, LON, bearing_deg=90, distance_km=metres_east / 1000)
    case = Case(
        case_id=f"VD-{next(_counter):08d}",
        status=status,
        report=Report(
            report_id=f"r{next(_counter)}",
            latitude=lat,
            longitude=lon,
            reporter_contact=contact,
            observed_at=BASE + timedelta(days=days),
        ),
    )
    if evidence:
        case.evidence = EvidencePacket(
            pollution_type=pollution_type, confidence=0.9, severity="high"
        )
    if save:
        store.save(case)
    return case


# --------------------------------------------------------------------------- #
# What groups
# --------------------------------------------------------------------------- #


def test_three_nearby_reports_of_one_type_are_a_pattern():
    for day, metres in ((0, 0), (4, 120), (9, 300)):
        make_case(days=day, metres_east=metres)

    found = clustering.clusters()
    assert len(found) == 1
    cluster = found[0]
    assert cluster.report_count == 3
    assert cluster.pollution_type is PollutionType.OPEN_WASTE_BURNING
    assert cluster.span_days == 9
    assert cluster.first_reported_at == BASE
    assert cluster.radius_km < settings.vayudoot_cluster_radius_km
    assert cluster.cluster_id.startswith("VDC-")


def test_members_are_ordered_by_observation_not_by_arrival():
    late = make_case(days=20)
    early = make_case(days=0)
    middle = make_case(days=10)

    members = [m.case_id for m in clustering.clusters()[0].members]
    assert members == [early.case_id, middle.case_id, late.case_id]


def test_a_gap_shorter_than_the_window_keeps_one_long_pattern():
    """The window is a maximum gap, not a maximum age.

    A site burning every three weeks for four months is one ongoing problem, and
    splitting it into five would throw away the whole argument.
    """
    for day in (0, 20, 40, 60, 80, 100, 120):
        make_case(days=day)

    found = clustering.clusters()
    assert len(found) == 1
    assert found[0].report_count == 7
    assert found[0].span_days == 120


def test_resolved_and_acknowledged_reports_still_count():
    """A problem that was fixed and came back is the strongest pattern there is."""
    make_case(days=0, status=CaseStatus.RESOLVED)
    make_case(days=5, status=CaseStatus.ACKNOWLEDGED)
    make_case(days=10, status=CaseStatus.FILED)

    assert clustering.clusters()[0].report_count == 3


# --------------------------------------------------------------------------- #
# What must not group
# --------------------------------------------------------------------------- #


def test_two_reports_are_not_a_pattern():
    make_case(days=0)
    make_case(days=3)
    assert clustering.clusters() == []


def test_a_different_pollution_type_is_a_different_problem():
    """Identical coordinates, and still two problems.

    A waste fire and a construction site at one address are not one complaint:
    they are different statutes, different remedies, and probably different
    parties. Merging them would produce a complaint citing the wrong rule.
    """
    for day in (0, 2, 4):
        make_case(days=day, pollution_type=PollutionType.OPEN_WASTE_BURNING)
    for day in (1, 3, 5):
        make_case(days=day, pollution_type=PollutionType.CONSTRUCTION_DUST)

    found = clustering.clusters()
    assert len(found) == 2
    assert {c.pollution_type for c in found} == {
        PollutionType.OPEN_WASTE_BURNING,
        PollutionType.CONSTRUCTION_DUST,
    }
    assert all(c.report_count == 3 for c in found)


def test_reports_beyond_the_radius_do_not_group():
    for day, metres in ((0, 0), (2, 5_000), (4, 10_000)):
        make_case(days=day, metres_east=metres)
    assert clustering.clusters() == []


def test_a_gap_longer_than_the_window_breaks_the_pattern():
    """January and November at one address are two episodes, not one pattern."""
    for day in (0, 2, 4):
        make_case(days=day)
    for day in (200, 202, 204):
        make_case(days=day)

    found = clustering.clusters()
    assert len(found) == 2
    assert {c.report_count for c in found} == {3}
    assert found[0].cluster_id != found[1].cluster_id


def test_proximity_is_measured_to_the_centroid_so_a_line_of_reports_does_not_chain():
    """Six reports 400 m apart span 2 km. Single linkage would call that one problem.

    Each hop is inside the radius, so linking to the nearest *member* would chain
    all six together and produce a "pattern" covering half a suburb. Linking to
    the running centroid instead breaks the line into pairs, none of which reaches
    the minimum, which is the correct answer: this is not one problem.
    """
    cases = [make_case(days=index, metres_east=index * 400) for index in range(6)]

    assert clustering.clusters() == []
    groups = clustering._link(cases)
    assert [len(g) for g in groups] == [2, 2, 2]


def test_withdrawn_and_rejected_reports_are_excluded():
    make_case(days=0)
    make_case(days=1)
    make_case(days=2, status=CaseStatus.WITHDRAWN)
    make_case(days=3, status=CaseStatus.REJECTED)
    make_case(days=4, status=CaseStatus.FAILED)

    assert clustering.clusters() == []


def test_an_unclassified_or_unclear_case_never_groups():
    make_case(days=0, evidence=False)
    make_case(days=1, pollution_type=PollutionType.UNCLEAR)
    make_case(days=2, pollution_type=PollutionType.UNCLEAR)
    make_case(days=3, evidence=False)
    assert clustering.clusters() == []


# --------------------------------------------------------------------------- #
# Identity, reporters, and phrasing
# --------------------------------------------------------------------------- #


def test_the_cluster_id_survives_a_new_report_joining():
    for day in (0, 2, 4):
        make_case(days=day)
    before = clustering.clusters()[0].cluster_id

    make_case(days=6, metres_east=200)
    after = clustering.clusters()[0]
    assert after.report_count == 4
    assert after.cluster_id == before


def test_reporters_are_counted_apart_because_anonymity_cannot_be_resolved():
    make_case(days=0, contact="asha@example.invalid")
    make_case(days=1, contact="ASHA@example.invalid ")
    make_case(days=2, contact="ravi@example.invalid")
    make_case(days=3)
    make_case(days=4)

    cluster = clustering.clusters()[0]
    assert cluster.report_count == 5
    # Two identified people, however many times each of them reported.
    assert cluster.distinct_reporters == 2
    assert cluster.anonymous_reports == 2


def test_one_person_reporting_repeatedly_is_visible_as_such():
    for day in (0, 3, 6, 9):
        make_case(days=day, contact="asha@example.invalid")
    cluster = clustering.clusters()[0]
    assert cluster.distinct_reporters == 1
    assert cluster.anonymous_reports == 0
    assert "1 identified reporter" in clustering.describe(cluster)


def test_describe_leads_with_the_position_of_a_named_case():
    cases = [make_case(days=day) for day in range(14)]
    cluster = clustering.clusters()[0]

    sentence = clustering.describe(cluster, cases[13].case_id)
    assert sentence.startswith("This is the 14th report of open waste burning within ")
    assert "since 12 August 2026" in sentence
    assert "14 reports over 13 days" in sentence


def test_describe_without_a_case_id_states_the_count_instead():
    for day in (0, 1, 2):
        make_case(days=day)
    sentence = clustering.describe(clustering.clusters()[0])
    assert sentence.startswith("3 reports of open waste burning within ")


@pytest.mark.parametrize(
    ("n", "expected"),
    [(1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (11, "11th"), (13, "13th"), (21, "21st")],
)
def test_ordinals(n, expected):
    assert clustering._ordinal(n) == expected


# --------------------------------------------------------------------------- #
# Lookups and settings
# --------------------------------------------------------------------------- #


def test_cluster_for_finds_the_group_a_case_belongs_to():
    cases = [make_case(days=day) for day in (0, 2, 4)]
    cluster = clustering.cluster_for(cases[1])
    assert cluster is not None
    assert cases[1].case_id in {m.case_id for m in cluster.members}


def test_cluster_for_returns_none_for_a_one_off():
    assert clustering.cluster_for(make_case()) is None


def test_cluster_for_sees_a_case_that_has_not_been_persisted():
    """The pipeline asks mid-run, and a `persist=False` run never writes at all."""
    make_case(days=0)
    make_case(days=2)
    live = make_case(days=4, save=False)

    cluster = clustering.cluster_for(live)
    assert cluster is not None
    assert cluster.report_count == 3
    assert cluster.members[-1].case_id == live.case_id


def test_the_thresholds_are_settings_not_constants(monkeypatch):
    monkeypatch.setattr(settings, "vayudoot_cluster_min_reports", 2)
    monkeypatch.setattr(settings, "vayudoot_cluster_radius_km", 0.05)

    make_case(days=0, metres_east=0)
    make_case(days=1, metres_east=30)
    make_case(days=2, metres_east=400)

    found = clustering.clusters()
    assert len(found) == 1
    assert found[0].report_count == 2


# --------------------------------------------------------------------------- #
# Drafting
# --------------------------------------------------------------------------- #


async def test_drafting_is_told_about_the_pattern():
    from fakes import corroboration, evidence, jurisdiction

    cases = [make_case(days=day) for day in range(14)]
    cluster = clustering.clusters()[0]
    agent = StubAgent(complaint())

    await draft_complaint(
        cases[13].report,
        evidence(),
        corroboration(),
        jurisdiction(),
        address="Minto Road, New Delhi",
        cluster=cluster,
        case_id=cases[13].case_id,
        agent=agent,
    )

    prompt = agent.prompts[0]
    assert "PATTERN OF REPEAT REPORTS" in prompt
    assert "This is the 14th report of open waste burning" in prompt
    assert cluster.cluster_id in prompt
    assert "Anonymous submissions: 14" in prompt


async def test_drafting_says_nothing_about_a_pattern_when_there_is_none():
    """The single-report path is unchanged: no block, not an empty one."""
    from fakes import corroboration, evidence, jurisdiction

    agent = StubAgent(complaint())
    await draft_complaint(
        make_case(save=False).report,
        evidence(),
        corroboration(),
        jurisdiction(),
        address="Minto Road, New Delhi",
        agent=agent,
    )
    assert "PATTERN" not in agent.prompts[0]


async def test_the_pipeline_records_the_cluster_it_drafted_against(monkeypatch):
    from fakes import patch_stages
    from vayudoot import pipeline

    patch_stages(monkeypatch, pipeline)
    for day in (0, 2):
        make_case(days=day)

    case = await pipeline.run(make_case(days=4, save=False).report)
    assert case.cluster_id.startswith("VDC-")
    assert any("This is the 3rd report" in entry for entry in case.history)


async def test_a_broken_cluster_lookup_does_not_break_the_run(monkeypatch):
    """The pipeline must not depend on there being a cluster, or on the lookup working."""
    from fakes import patch_stages
    from vayudoot import pipeline

    patch_stages(monkeypatch, pipeline)

    def explode(*args, **kwargs):
        raise RuntimeError("case store is unreadable")

    monkeypatch.setattr(pipeline.clustering, "cluster_for", explode)
    case = await pipeline.run(make_case(save=False).report)

    assert case.status is CaseStatus.AWAITING_CONFIRMATION
    assert case.complaint is not None
    assert case.cluster_id == ""
