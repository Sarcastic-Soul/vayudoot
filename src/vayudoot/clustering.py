"""Grouping repeat reports of the same problem at the same place.

One photograph of a burning waste pile is an incident. Fifteen photographs of the
same pile over a month is a pattern, and a pattern is the argument a regulator
actually acts on: it converts "please inspect" into "this has been reported
fourteen times since 12 August and nothing has changed".

Everything needed is already on disk. A case carries coordinates, a classified
pollution type, an observation time and a jurisdiction, so this module is pure
logic over `store.all_cases()` with no new external dependency.

Three decisions are worth stating, because they are what makes a group *the same
problem* rather than merely nearby:

Proximity is measured to the group's centroid, not to any member. Linking a case
to its nearest *member* chains: a line of reports 400 m apart would walk across a
city and report one absurd cluster. Centroid linkage bounds a group's diameter to
roughly twice the radius, which is the behaviour a complaint can defend.

The pollution type must match exactly. Two waste fires 400 m apart on one street
are plausibly one problem; a waste fire and a construction site at identical
coordinates are two, and merging them would produce a complaint that cites the
wrong statute against the wrong party. `unclear` never groups, because a case the
evidence stage could not classify has no problem to be the same as.

The window is a maximum *gap*, not a maximum age. A site that burns every
fortnight for six months is one ongoing pattern; a fire in January and another in
November are two episodes that happen to share a postcode.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta

from . import store
from .config import settings
from .schemas import Case, CaseStatus, Cluster, ClusterMember, PollutionType
from .tools.geo import haversine_km

#: Reports that do not count towards a pattern.
#:
#: `rejected` fell below the classification confidence floor, so the photograph
#: never supported a complaint. `withdrawn` was taken back by the citizen and
#: must not go on inflating a count against an authority. `failed` died mid-run
#: and may have no evidence at all.
#:
#: `resolved` and `acknowledged` deliberately stay in. A problem that was fixed
#: and came back is the strongest pattern there is, and dropping the closed
#: reports would hide exactly that.
EXCLUDED_STATUSES: frozenset[CaseStatus] = frozenset(
    {CaseStatus.REJECTED, CaseStatus.WITHDRAWN, CaseStatus.FAILED}
)


def clusters(cases: Iterable[Case] | None = None) -> list[Cluster]:
    """Every repeat-report pattern in the case store, strongest first."""
    pool = list(cases) if cases is not None else store.all_cases()
    minimum = settings.vayudoot_cluster_min_reports

    found: list[Cluster] = []
    for members in _groups(pool):
        if len(members) >= minimum:
            found.append(_summarise(members))
    return sorted(found, key=lambda c: (c.report_count, c.last_reported_at), reverse=True)


def cluster_for(case: Case, cases: Iterable[Case] | None = None) -> Cluster | None:
    """The pattern `case` belongs to, or None if it is a one-off.

    The live case is merged into the pool rather than read back from disk, so
    this answers correctly during a pipeline run that has not persisted yet, and
    for a run with `persist=False` that never will.
    """
    pool = list(cases) if cases is not None else store.all_cases()
    pool = [other for other in pool if other.case_id != case.case_id] + [case]
    for cluster in clusters(pool):
        if any(member.case_id == case.case_id for member in cluster.members):
            return cluster
    return None


def describe(cluster: Cluster, case_id: str = "") -> str:
    """One sentence a complaint can use verbatim.

    Given a `case_id` in the cluster it leads with that report's position, which
    is the phrasing that carries weight: "this is the 14th report" says more than
    "there are 14 reports".
    """
    label = cluster.pollution_type.value.replace("_", " ")
    where = _distance_label(cluster.radius_km)
    since = _date_label(cluster.first_reported_at)

    position = _position(cluster, case_id)
    if position:
        lead = (
            f"This is the {_ordinal(position)} report of {label} within {where} "
            f"of this location since {since}"
        )
    else:
        lead = (
            f"{cluster.report_count} reports of {label} within {where} of this "
            f"location since {since}"
        )

    days = max(cluster.span_days, 1)
    return f"{lead}: {cluster.report_count} reports over {_plural(days, 'day')}, {_who(cluster)}."


# --------------------------------------------------------------------------- #
# Grouping
# --------------------------------------------------------------------------- #


def _eligible(case: Case) -> bool:
    return (
        case.status not in EXCLUDED_STATUSES
        and case.evidence is not None
        and case.evidence.pollution_type is not PollutionType.UNCLEAR
    )


def _observed(case: Case) -> datetime:
    at = case.report.observed_at
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def _groups(cases: Iterable[Case]) -> list[list[Case]]:
    """Partition eligible cases into same-problem groups, one pollution type at a time."""
    by_type: dict[PollutionType, list[Case]] = {}
    for case in sorted((c for c in cases if _eligible(c)), key=_observed):
        assert case.evidence is not None  # _eligible guarantees it
        by_type.setdefault(case.evidence.pollution_type, []).append(case)

    groups: list[list[Case]] = []
    for same_type in by_type.values():
        groups.extend(_link(same_type))
    return groups


def _link(cases: Sequence[Case]) -> list[list[Case]]:
    """Leader clustering in observation order, joining to the nearest centroid.

    `cases` must already be sorted by observation time and share one pollution
    type. Order is deterministic, so the same store always yields the same
    groups — which is what lets a cluster id be stable.
    """
    radius = settings.vayudoot_cluster_radius_km
    max_gap = timedelta(days=settings.vayudoot_cluster_window_days)

    groups: list[list[Case]] = []
    for case in cases:
        lat, lon = case.report.latitude, case.report.longitude
        best: list[Case] | None = None
        best_km = math.inf
        for group in groups:
            if _observed(case) - _observed(group[-1]) > max_gap:
                continue
            centre_lat, centre_lon = _centroid(group)
            km = haversine_km(lat, lon, centre_lat, centre_lon)
            if km <= radius and km < best_km:
                best, best_km = group, km
        if best is None:
            groups.append([case])
        else:
            best.append(case)
    return groups


def _centroid(group: Sequence[Case]) -> tuple[float, float]:
    """Arithmetic mean of the members' coordinates.

    A flat mean is wrong on a globe and irrelevant here: every group spans well
    under a kilometre, where the error is centimetres.
    """
    return (
        sum(c.report.latitude for c in group) / len(group),
        sum(c.report.longitude for c in group) / len(group),
    )


# --------------------------------------------------------------------------- #
# Summarising
# --------------------------------------------------------------------------- #


def cluster_id(pollution_type: PollutionType, seed_case_id: str) -> str:
    """A stable identity for a group, so it can be linked to and cited.

    Derived from the pollution type and the earliest member, both of which are
    fixed for the life of the group: later reports join it, they never displace
    its seed. A cluster keeps its id as it grows, which is the property a
    complaint citing a reference actually needs.
    """
    digest = hashlib.sha256(f"{pollution_type.value}:{seed_case_id}".encode()).hexdigest()
    return f"VDC-{digest[:8].upper()}"


def _summarise(group: Sequence[Case]) -> Cluster:
    ordered = sorted(group, key=_observed)
    assert ordered[0].evidence is not None  # _eligible guarantees it
    pollution_type = ordered[0].evidence.pollution_type
    centre_lat, centre_lon = _centroid(ordered)

    members = [
        ClusterMember(
            case_id=case.case_id,
            observed_at=_observed(case),
            latitude=case.report.latitude,
            longitude=case.report.longitude,
            status=case.status,
            distance_km=round(
                haversine_km(case.report.latitude, case.report.longitude, centre_lat, centre_lon), 4
            ),
        )
        for case in ordered
    ]

    # Whether repeat reports are independent is the difference between a pattern
    # and one persistent neighbour, and the honest answer is partial: a contact
    # string can be compared, an anonymous submission cannot. Both counts are
    # published so nothing downstream has to guess, and so the drafting stage can
    # be told not to claim independence it cannot show.
    contacts = {
        case.report.reporter_contact.strip().lower()
        for case in ordered
        if case.report.reporter_contact.strip()
    }
    anonymous = sum(1 for case in ordered if not case.report.reporter_contact.strip())

    first, last = _observed(ordered[0]), _observed(ordered[-1])
    newest_first = list(reversed(ordered))

    return Cluster(
        cluster_id=cluster_id(pollution_type, ordered[0].case_id),
        pollution_type=pollution_type,
        centre_latitude=round(centre_lat, 6),
        centre_longitude=round(centre_lon, 6),
        radius_km=round(max(m.distance_km for m in members), 4),
        report_count=len(members),
        first_reported_at=first,
        last_reported_at=last,
        span_days=(last - first).days,
        distinct_reporters=len(contacts),
        anonymous_reports=anonymous,
        # The most recently resolved of each, because the authority table or the
        # geocoder may have improved since the first report was filed.
        authority_name=next(
            (c.jurisdiction.authority_name for c in newest_first if c.jurisdiction), ""
        ),
        address=next((c.address for c in newest_first if c.address), ""),
        members=members,
    )


# --------------------------------------------------------------------------- #
# Phrasing
# --------------------------------------------------------------------------- #


def _position(cluster: Cluster, case_id: str) -> int:
    if not case_id:
        return 0
    for index, member in enumerate(cluster.members, start=1):
        if member.case_id == case_id:
            return index
    return 0


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _date_label(at: datetime) -> str:
    return f"{at.day} {at.strftime('%B %Y')}"


def _distance_label(radius_km: float) -> str:
    """Round the group's actual extent up to something a complaint can state.

    The configured radius is not the honest number: the centroid moves as members
    join, so a member can end up a little beyond it. This reports the real extent,
    rounded up to the nearest 50 m — finer than a phone's GPS fix, so a tighter
    figure would be false precision.
    """
    metres = max(50, math.ceil(radius_km * 1000 / 50.0) * 50)
    return f"{metres} m" if metres < 1000 else f"{metres / 1000:.1f} km"


def _who(cluster: Cluster) -> str:
    identified, anonymous = cluster.distinct_reporters, cluster.anonymous_reports
    if identified and anonymous:
        return (
            f"from {_plural(identified, 'identified reporter')} and "
            f"{_plural(anonymous, 'anonymous submission')}"
        )
    if identified:
        return f"from {_plural(identified, 'identified reporter')}"
    return f"from {_plural(anonymous, 'anonymous submission')}"
