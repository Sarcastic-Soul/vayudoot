"""Population exposure per hotspot.

Most of these run against a tiny fixture table so the arithmetic is checkable by
hand. Two read the committed table itself, because it is data a public number is
built from and has to carry its provenance: a population figure with no source
attached is exactly the unsupported public claim hard constraint 7 warns about.

The property worth naming: exposure is carried on a hotspot and never read by
confidence or ranking. How many people live near a fire says how much it matters
if it is real, not whether it is.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from vayudoot import exposure, federation, hotspots
from vayudoot.config import settings
from vayudoot.schemas import PollutionType, Signal, SignalSource
from vayudoot.tools.geo import point_at

NOW = datetime(2026, 9, 14, 6, 0, tzinfo=UTC)
LUDHIANA = (30.9010, 75.8573)

#: Four places around Ludhiana at known distances, and one far away. Fictional
#: names on real geometry, so a test failure is about the arithmetic and never
#: about a GeoNames refresh.
FIXTURE_PLACES = [
    ("Centreville", 0.0, 0.0, 500_000),
    ("Fivekm", 90.0, 5.0, 40_000),
    ("Ninekm", 180.0, 9.0, 20_000),
    ("Elevenkm", 270.0, 11.0, 90_000),
    ("Faraway", 0.0, 300.0, 9_000_000),
]


@pytest.fixture
def table(tmp_path, monkeypatch):
    """Point the module at a hand-built table."""
    path = tmp_path / "settlements.csv"
    lines = [
        "# fixture table, not GeoNames",
        "name,country,latitude,longitude,population",
    ]
    for name, bearing, km, population in FIXTURE_PLACES:
        lat, lon = point_at(*LUDHIANA, bearing, km) if km else LUDHIANA
        lines.append(f"{name},IN,{lat:.6f},{lon:.6f},{population}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(exposure, "_DATA", path)
    return path


@pytest.fixture
def empty_table(tmp_path, monkeypatch):
    path = tmp_path / "empty.csv"
    path.write_text("name,country,latitude,longitude,population\n", encoding="utf-8")
    monkeypatch.setattr(exposure, "_DATA", path)
    return path


def satellite(at: tuple[float, float], suffix: str = "") -> Signal:
    return Signal(
        source=SignalSource.SATELLITE,
        signal_id=f"viirs:{at[0]}:{at[1]}{suffix}",
        latitude=at[0],
        longitude=at[1],
        observed_at=NOW,
        pollution_type=PollutionType.UNCLEAR,
        strength=0.85,
        magnitude=0.7,
    )


# --------------------------------------------------------------------------- #
# The lookup
# --------------------------------------------------------------------------- #


def test_only_settlements_whose_centre_is_in_reach_are_counted(table):
    found = exposure.exposure_for(*LUDHIANA, 10.0)

    assert found is not None
    assert found.population == 500_000 + 40_000 + 20_000
    assert found.settlement_count == 3
    assert found.radius_km == 10.0


def test_towns_are_the_largest_first(table):
    found = exposure.exposure_for(*LUDHIANA, 12.0)

    assert found is not None
    assert found.towns == ["Centreville", "Elevenkm", "Fivekm"]


def test_at_most_three_towns_are_named_however_many_are_counted(table):
    found = exposure.exposure_for(*LUDHIANA, 12.0)

    assert found is not None
    assert found.settlement_count == 4
    assert len(found.towns) == exposure.TOWNS_NAMED


def test_nothing_in_reach_is_none_not_zero(table):
    """Zero would say nobody lives there. The table only knows about towns over
    15,000 people, so all it can say is that none of *those* are in reach."""
    assert exposure.exposure_for(12.0, 70.0, 10.0) is None


def test_the_basis_says_what_was_counted_and_whose_data_it_is(table):
    found = exposure.exposure_for(*LUDHIANA, 10.0)

    assert found is not None
    assert "GeoNames" in found.basis
    assert "CC BY 4.0" in found.basis
    assert "15,000" in found.basis
    assert "coarse figure" in found.basis.lower()


def test_a_missing_table_is_no_exposure_rather_than_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(exposure, "_DATA", tmp_path / "does-not-exist.csv")
    assert exposure.exposure_for(*LUDHIANA, 10.0) is None


# --------------------------------------------------------------------------- #
# On a hotspot
# --------------------------------------------------------------------------- #


def test_a_hotspot_with_settlements_in_reach_carries_its_exposure(table, monkeypatch):
    monkeypatch.setattr(settings, "vayudoot_exposure_radius_km", 10.0)

    [spot] = hotspots.detect([satellite(LUDHIANA)])

    assert spot.exposure is not None
    assert spot.exposure.population == 560_000
    assert spot.exposure.towns[0] == "Centreville"


def test_a_hotspot_with_nobody_in_reach_has_no_exposure(table):
    [spot] = hotspots.detect([satellite((12.0, 70.0))])

    assert spot.exposure is None


def test_a_hotspot_wider_than_the_exposure_radius_counts_out_to_its_own_edge(
    table, monkeypatch
):
    """A hotspot spread over twelve kilometres has people breathing it at its
    edge; counting only the inner ten would drop them."""
    monkeypatch.setattr(settings, "vayudoot_exposure_radius_km", 3.0)
    monkeypatch.setattr(settings, "vayudoot_hotspot_min_radius_km", 11.5)

    [spot] = hotspots.detect([satellite(LUDHIANA)])

    assert spot.exposure is not None
    assert spot.exposure.radius_km == spot.radius_km
    assert "Elevenkm" in spot.exposure.towns


def test_exposure_never_moves_confidence_severity_or_ranking(tmp_path, monkeypatch, table):
    """PROPERTY. Population says how much a fire matters if real, not whether it is.

    Letting it lift confidence would rank a weak report from a suburb above a
    well-corroborated fire in empty farmland.
    """
    signals = [satellite(LUDHIANA), satellite((12.0, 70.0), ":sea")]
    with_people = [(h.hotspot_id, h.confidence, h.severity) for h in hotspots.detect(signals)]

    empty = tmp_path / "none.csv"
    empty.write_text("name,country,latitude,longitude,population\n", encoding="utf-8")
    monkeypatch.setattr(exposure, "_DATA", empty)
    without = [(h.hotspot_id, h.confidence, h.severity) for h in hotspots.detect(signals)]

    assert with_people == without


def test_exposure_is_not_published_on_the_feed(table):
    """A neighbour recomputes it from centre and radius with its own table; ours is
    not part of the detection. See `federation.publish`."""
    [spot] = hotspots.detect([satellite(LUDHIANA)])
    assert spot.exposure is not None

    feed = federation.publish([spot]).model_dump_json()
    geojson = str(federation.publish_geojson([spot]))

    assert "exposure" not in feed
    assert "Centreville" not in feed
    assert "exposure" not in geojson
    assert "Centreville" not in geojson


# --------------------------------------------------------------------------- #
# The committed table
# --------------------------------------------------------------------------- #


def test_the_committed_table_carries_its_attribution():
    head = exposure._DATA.read_text(encoding="utf-8").splitlines()[:10]
    text = "\n".join(head)
    assert "GeoNames" in text
    assert "CC BY 4.0" in text
    assert "build_settlements.py" in text


def test_the_committed_table_covers_india_and_its_upwind_neighbours():
    """Smoke from Pakistan, Bangladesh and Nepal reaches India, and a node standing
    up in any of them needs its own towns in the table."""
    exposure._load.cache_clear()
    countries = {s.country for s in exposure._load(exposure._DATA).settlements}
    assert {"IN", "PK", "BD", "NP"} <= countries
    # Compact enough to ship in the container and read on every cold start.
    assert exposure._DATA.stat().st_size < 1_000_000
