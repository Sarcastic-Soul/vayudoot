"""The corridor table is data a forecast is reported against, so it has to be
right before anything reasons over it. These tests check the data itself as much
as the loader: a transposed latitude and longitude is the kind of error that
produces a plausible-looking forecast for the wrong hemisphere.
"""

from vayudoot.corridors import all_corridors, corridors_near, get_corridor

#: Roughly India's bounding box. Generous on purpose — this is here to catch a
#: transposed or mistyped coordinate, not to police a border.
INDIA_BBOX = (6.0, 37.0, 68.0, 98.0)

DELHI = (28.6139, 77.2090)
CHENNAI = (13.0827, 80.2707)
#: Bharuch sits on the Vadodara-Surat leg of the Delhi-Mumbai corridor but is
#: sixty kilometres from either waypoint.
BHARUCH = (21.7051, 72.9959)


def test_the_table_loads_and_carries_the_corridors_the_brief_names():
    ids = {c.corridor_id for c in all_corridors()}
    assert len(ids) >= 6
    assert {"ncr", "delhi-mumbai", "punjab-haryana-stubble"} <= ids
    assert {"mumbai-pune", "chennai-bengaluru", "kolkata-durgapur"} <= ids


def test_corridor_ids_are_unique():
    corridors = all_corridors()
    assert len({c.corridor_id for c in corridors}) == len(corridors)


def test_every_corridor_is_described_and_placed():
    for corridor in all_corridors():
        assert corridor.name, corridor.corridor_id
        assert corridor.description, corridor.corridor_id
        assert corridor.states, corridor.corridor_id
        # Sparse sampling points, not a route: too few and the corridor is a
        # point, too many and every one costs a forecast call.
        assert 4 <= len(corridor.waypoints) <= 8, corridor.corridor_id


def test_every_waypoint_is_a_plausible_coordinate_inside_india():
    south, north, west, east = INDIA_BBOX
    for corridor in all_corridors():
        for lat, lon in corridor.waypoints:
            assert south <= lat <= north, (corridor.corridor_id, lat, lon)
            assert west <= lon <= east, (corridor.corridor_id, lat, lon)


def test_get_corridor_returns_a_known_corridor():
    corridor = get_corridor("ncr")
    assert corridor is not None
    assert "Capital" in corridor.name


def test_get_corridor_returns_none_for_an_unknown_id():
    """An id reaches this from a URL and from model output, so a miss is a miss."""
    assert get_corridor("atlantis") is None


def test_corridors_near_finds_the_capital_corridor_from_delhi():
    ids = [c.corridor_id for c in corridors_near(*DELHI, within_km=25)]
    assert "ncr" in ids


def test_corridors_near_does_not_find_the_capital_corridor_from_chennai():
    ids = [c.corridor_id for c in corridors_near(*CHENNAI, within_km=25)]
    assert "ncr" not in ids
    assert "chennai-bengaluru" in ids


def test_a_point_between_two_waypoints_is_still_on_the_corridor():
    """Distance is to the route, not to the nearest sampling point.

    Measuring to the nearest waypoint would put Bharuch sixty kilometres from a
    corridor that runs through it, and the corridor forecast would never reach
    the place that needs it.
    """
    ids = [c.corridor_id for c in corridors_near(*BHARUCH, within_km=25)]
    assert "delhi-mumbai" in ids


def test_corridors_near_returns_the_closest_first():
    near = corridors_near(*DELHI, within_km=500)
    assert near[0].corridor_id == "ncr"


def test_nothing_is_near_a_point_in_the_ocean():
    assert corridors_near(0.0, 70.0, within_km=100) == []
