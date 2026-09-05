import math

from vayudoot.tools.geo import bbox_around, haversine_km, point_at, upwind_point


def test_haversine_known_distance():
    # Delhi to Bengaluru is roughly 1740 km.
    d = haversine_km(28.6139, 77.2090, 12.9716, 77.5946)
    assert 1700 < d < 1780


def test_haversine_zero():
    assert haversine_km(28.6, 77.2, 28.6, 77.2) == 0


def test_point_at_north():
    lat, lon = point_at(0.0, 0.0, bearing_deg=0, distance_km=111.195)
    assert math.isclose(lat, 1.0, abs_tol=0.01)
    assert math.isclose(lon, 0.0, abs_tol=0.01)


def test_upwind_source_lies_toward_the_wind():
    # Wind from 270 degrees (from the west) means the source is to the west.
    lat, lon = upwind_point(28.6139, 77.2090, wind_from_degrees=270, distance_km=2)
    assert lon < 77.2090
    assert math.isclose(lat, 28.6139, abs_tol=0.01)


def test_bbox_contains_centre():
    west, south, east, north = bbox_around(28.6139, 77.2090, 10)
    assert west < 77.2090 < east
    assert south < 28.6139 < north
