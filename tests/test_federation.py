"""Publishing hotspots to other nodes, and reading theirs.

Three of these hold properties rather than check functions, and each is marked
where it appears: the feed is an allowlist, a neighbour's hotspots are never
laundered into our own, and a feed reporting our own node id is refused. The
first two are the reasons `federation.py` exists in the shape it does; the third
is the failure that would silently manufacture corroboration out of nothing.
"""

from __future__ import annotations

import itertools
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from vayudoot import federation
from vayudoot.config import settings
from vayudoot.schemas import FeedHotspot, Hotspot, HotspotFeed, PollutionType
from vayudoot.tools.geo import haversine_km

NOW = datetime(2026, 9, 14, 6, 0, tzinfo=UTC)


def hotspot(
    hotspot_id: str = "VDH-AAAA1111",
    *,
    corroborated: bool = True,
    confidence: float = 0.9,
    at: tuple[float, float] = (30.9010, 75.8573),  # Ludhiana, Punjab
) -> Hotspot:
    return Hotspot(
        hotspot_id=hotspot_id,
        pollution_type=PollutionType.CROP_RESIDUE_BURNING,
        centre_latitude=at[0],
        centre_longitude=at[1],
        radius_km=2.5,
        confidence=confidence,
        severity="severe",
        corroborated=corroborated,
        signal_count=4,
        first_seen_at=NOW - timedelta(days=1),
        last_seen_at=NOW,
        span_days=1,
        case_ids=["VD-SECRET01"],
    )


def feed_payload(
    node_id: str = "punjab-node", hotspots: list | None = None, country: str = "IN"
) -> dict:
    return json.loads(
        HotspotFeed(
            node=federation.NodeIdentity(
                node_id=node_id, name="Punjab node", region="punjab", country=country
            ),
            hotspot_count=len(hotspots or []),
            hotspots=hotspots or [],
        ).model_dump_json()
    )


# --------------------------------------------------------------------------- #
# Publishing
# --------------------------------------------------------------------------- #


def test_the_feed_is_an_allowlist_not_a_serialised_hotspot():
    """PROPERTY. A field added to `Hotspot` later must stay private by default.

    `register.py` makes the same choice for the same reason. Here it also keeps
    the reporters out: a neighbour needs to know something is burning and how
    sure we are, not which of our citizens said so.
    """
    published = federation.publish([hotspot()])
    fields = set(published.hotspots[0].model_dump().keys())

    assert "case_ids" not in fields
    assert "signals" not in fields
    # And nothing resembling a reporter reached the wire at all.
    assert "VD-SECRET01" not in published.model_dump_json()


def test_the_feed_carries_the_publishing_node_on_every_hotspot(monkeypatch):
    monkeypatch.setattr(settings, "vayudoot_node_id", "punjab-node")
    published = federation.publish([hotspot(), hotspot("VDH-BBBB2222")])

    assert published.hotspot_count == 2
    assert {h.node_id for h in published.hotspots} == {"punjab-node"}


def test_uncorroborated_hotspots_are_published_with_their_flag_intact():
    """Weak signals travel, and travel marked.

    Withholding them would hide a citizen-reported fire from the state downwind
    of it, which is the gap this network exists to close. Publishing them
    unmarked would be worse. So: published, flagged, capped.
    """
    published = federation.publish([hotspot(corroborated=False, confidence=0.6)])

    assert published.hotspots[0].corroborated is False
    assert published.hotspots[0].confidence == 0.6


def test_an_empty_feed_is_still_a_valid_feed():
    published = federation.publish([])
    assert published.hotspot_count == 0
    assert published.node.node_id == settings.vayudoot_node_id


def test_the_node_says_which_country_it_is_in(monkeypatch):
    """Smoke crosses national borders as readily as state ones; the field is what
    lets a neighbour tell a cross-border feed from a domestic one."""
    monkeypatch.setattr(settings, "vayudoot_node_country", "pk")

    assert federation.identity().country == "PK"
    assert federation.publish([]).node.country == "PK"


def test_an_unconfigured_node_is_in_india():
    assert federation.identity().country == "IN"


# --------------------------------------------------------------------------- #
# GeoJSON
# --------------------------------------------------------------------------- #


def test_the_geojson_feed_is_a_feature_collection_of_polygons():
    collection = federation.publish_geojson([hotspot(), hotspot("VDH-BBBB2222")])

    assert collection["type"] == "FeatureCollection"
    assert len(collection["features"]) == 2
    for feature in collection["features"]:
        assert feature["type"] == "Feature"
        assert feature["geometry"]["type"] == "Polygon"


def test_a_hotspot_is_never_published_as_a_point():
    """PROPERTY. A point is an address; a point on a public map is an accusation
    against whoever sits under it. Hard constraint 7."""
    raw = json.dumps(federation.publish_geojson([hotspot()]))
    assert '"Point"' not in raw
    assert '"MultiPoint"' not in raw


def test_the_ring_is_closed_counter_clockwise_and_longitude_first():
    """RFC 7946 section 3.1.6: closed, exterior ring counter-clockwise, [lon, lat]."""
    [ring] = federation.publish_geojson([hotspot()])["features"][0]["geometry"]["coordinates"]

    assert ring[0] == ring[-1]
    assert len(ring) == federation.GEOJSON_RING_VERTICES + 1
    # Longitude first: Ludhiana is at 75.9 E, 30.9 N, so a transposed ring would
    # put every first coordinate near 30.
    assert all(70 < lon < 80 and 28 < lat < 33 for lon, lat in ring)
    # Shoelace formula: positive signed area is counter-clockwise.
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in itertools.pairwise(ring))
    assert area > 0


def test_every_vertex_sits_at_the_published_radius():
    """The area on the map is exactly the area the feed claims and no tighter."""
    spot = hotspot()
    [ring] = federation.publish_geojson([spot])["features"][0]["geometry"]["coordinates"]

    for lon, lat in ring:
        km = haversine_km(spot.centre_latitude, spot.centre_longitude, lat, lon)
        assert km == pytest.approx(spot.radius_km, rel=0.01)


def test_geojson_properties_are_exactly_the_feed_allowlist(monkeypatch):
    """The properties come from `publish()`, so the two projections cannot drift."""
    monkeypatch.setattr(settings, "vayudoot_node_country", "PK")
    [feature] = federation.publish_geojson([hotspot()])["features"]

    allowlist = set(FeedHotspot.model_fields)
    assert set(feature["properties"]) == allowlist | {"node_country", "feed_version"}
    assert feature["properties"]["node_country"] == "PK"
    assert feature["id"] == feature["properties"]["hotspot_id"]


def test_geojson_never_carries_a_signal_or_a_case_id():
    """The allowlist, asserted again for the second serialisation."""
    raw = json.dumps(federation.publish_geojson([hotspot()]))

    assert "VD-SECRET01" not in raw
    assert "case_ids" not in raw
    assert '"signals"' not in raw


def test_the_node_rides_on_the_collection_as_a_foreign_member(monkeypatch):
    monkeypatch.setattr(settings, "vayudoot_node_id", "lahore-node")
    monkeypatch.setattr(settings, "vayudoot_node_country", "PK")

    collection = federation.publish_geojson([hotspot()])

    assert collection["node"]["node_id"] == "lahore-node"
    assert collection["node"]["country"] == "PK"
    assert collection["feed_version"] == "1.0"
    assert collection["hotspot_count"] == 1
    json.dumps(collection)  # serialisable as it stands


def test_an_empty_geojson_feed_is_still_valid():
    collection = federation.publish_geojson([])
    assert collection["type"] == "FeatureCollection"
    assert collection["features"] == []


# --------------------------------------------------------------------------- #
# Reading a neighbour
# --------------------------------------------------------------------------- #


def test_a_neighbours_feed_is_read(respx_mock):
    respx_mock.get("https://punjab.example.invalid/feed").mock(
        return_value=httpx.Response(
            200, json=feed_payload(hotspots=federation.publish([hotspot()]).hotspots)
        )
    )

    result = federation.fetch_neighbour("https://punjab.example.invalid/feed")

    assert "error" not in result
    assert result["hotspot_count"] == 1


def test_a_neighbour_that_is_down_is_an_ordinary_condition_not_an_exception(respx_mock):
    """A node whose forecasting stops because a peer is offline is worse than one
    that carries on with less context. Same contract as every tool here."""
    respx_mock.get("https://punjab.example.invalid/feed").mock(
        side_effect=httpx.ConnectError("refused")
    )

    result = federation.fetch_neighbour("https://punjab.example.invalid/feed")

    assert "error" in result
    assert result["url"] == "https://punjab.example.invalid/feed"


def test_a_malformed_feed_does_not_crash_the_reader(respx_mock):
    respx_mock.get("https://punjab.example.invalid/feed").mock(
        return_value=httpx.Response(200, json={"not": "a feed"})
    )

    assert "error" in federation.fetch_neighbour("https://punjab.example.invalid/feed")


def test_a_feed_reporting_our_own_node_id_is_refused(respx_mock, monkeypatch):
    """PROPERTY. Reading ourselves back would manufacture agreement from nothing.

    Through a load balancer, a copied configuration, or a neighbour that mirrors
    us, our own hotspots would return as somebody else's and double — and two
    copies of one detection look exactly like two independent detections.
    """
    monkeypatch.setattr(settings, "vayudoot_node_id", "delhi-node")
    respx_mock.get("https://mirror.example.invalid/feed").mock(
        return_value=httpx.Response(200, json=feed_payload(node_id="delhi-node"))
    )

    result = federation.fetch_neighbour("https://mirror.example.invalid/feed")

    assert "error" in result
    assert "own node id" in result["error"]


def test_a_feed_from_across_a_national_border_is_read_like_any_other(respx_mock, monkeypatch):
    """Nothing in the contract is Indian. A Pakistani Punjab node's feed is read
    by a Delhi node exactly as an Indian Punjab node's is, and its hotspots are
    context for the forecast like any neighbour's."""
    monkeypatch.setattr(settings, "vayudoot_node_id", "delhi-node")
    monkeypatch.setattr(settings, "vayudoot_neighbour_feeds", "https://lahore.example.invalid/feed")
    lahore = hotspot("VDH-LAHORE01", at=(31.5497, 74.3436))
    respx_mock.get("https://lahore.example.invalid/feed").mock(
        return_value=httpx.Response(
            200,
            json=feed_payload(
                node_id="lahore-node",
                country="PK",
                hotspots=federation.publish([lahore]).hotspots,
            ),
        )
    )

    result = federation.fetch_neighbour("https://lahore.example.invalid/feed")
    assert result["feed"].node.country == "PK"

    [context] = federation.as_context(federation.neighbour_hotspots())
    assert context.hotspot_id == "VDH-LAHORE01"
    assert context.case_ids == []
    # And still never ours.
    assert federation.publish([]).hotspot_count == 0


def test_a_feed_from_before_country_existed_is_still_read(respx_mock):
    """A node running an older build publishes no `country`. The field defaults,
    so adding it did not break the 1.0 contract."""
    payload = feed_payload()
    del payload["node"]["country"]
    respx_mock.get("https://old.example.invalid/feed").mock(
        return_value=httpx.Response(200, json=payload)
    )

    result = federation.fetch_neighbour("https://old.example.invalid/feed")

    assert "error" not in result
    assert result["feed"].node.country == "IN"


def test_neighbour_hotspots_skips_the_peers_that_failed(respx_mock, monkeypatch):
    monkeypatch.setattr(
        settings,
        "vayudoot_neighbour_feeds",
        "https://up.example.invalid/feed,https://down.example.invalid/feed",
    )
    respx_mock.get("https://up.example.invalid/feed").mock(
        return_value=httpx.Response(
            200, json=feed_payload(hotspots=federation.publish([hotspot()]).hotspots)
        )
    )
    respx_mock.get("https://down.example.invalid/feed").mock(
        side_effect=httpx.ConnectError("refused")
    )

    collected = federation.neighbour_hotspots()

    assert len(collected) == 1


def test_no_configured_neighbours_is_a_node_that_federates_with_nobody(monkeypatch):
    monkeypatch.setattr(settings, "vayudoot_neighbour_feeds", "")
    assert federation.neighbour_hotspots() == []


def test_neighbour_urls_are_split_and_trimmed(monkeypatch):
    monkeypatch.setattr(
        settings, "vayudoot_neighbour_feeds", " https://a.invalid/f , https://b.invalid/f ,"
    )
    assert settings.neighbour_feeds == ["https://a.invalid/f", "https://b.invalid/f"]


# --------------------------------------------------------------------------- #
# What a neighbour's hotspots may be used for
# --------------------------------------------------------------------------- #


def test_a_neighbours_hotspot_is_context_and_never_becomes_ours():
    """PROPERTY. A node must not launder a neighbour's detection into its own.

    If it did, one bad instance would contaminate the whole network and the
    corroboration rule in hard constraint 7 would be meaningless, because nobody
    could tell whose evidence a hotspot rested on.
    """
    theirs = FeedHotspot(
        hotspot_id="VDH-PUNJAB01",
        node_id="punjab-node",
        pollution_type=PollutionType.CROP_RESIDUE_BURNING,
        centre_latitude=30.9010,
        centre_longitude=75.8573,
        radius_km=3.0,
        confidence=0.95,
        severity="severe",
        corroborated=True,
        signal_count=6,
        first_seen_at=NOW - timedelta(days=1),
        last_seen_at=NOW,
    )

    as_context = federation.as_context([theirs])

    assert len(as_context) == 1
    # Carried for forecasting, with no signals and no cases of ours attached.
    assert as_context[0].signals == []
    assert as_context[0].case_ids == []
    # And it is not in what we publish, because we publish what we detected.
    assert federation.publish([]).hotspot_count == 0


def test_context_preserves_the_corroboration_state_of_the_origin():
    theirs = federation.publish([hotspot(corroborated=False, confidence=0.6)]).hotspots
    assert federation.as_context(theirs)[0].corroborated is False


@pytest.mark.parametrize("field", ["confidence", "severity", "pollution_type"])
def test_context_preserves_what_the_forecast_stage_reads(field):
    original = hotspot()
    published = federation.publish([original]).hotspots
    restored = federation.as_context(published)[0]

    assert getattr(restored, field) == getattr(original, field)


# --------------------------------------------------------------------------- #
# The HTTP surface
# --------------------------------------------------------------------------- #


@pytest.fixture
async def client():
    from httpx import ASGITransport, AsyncClient

    from vayudoot import api

    transport = ASGITransport(app=api.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_a_node_publishes_who_it_is(client, monkeypatch):
    monkeypatch.setattr(settings, "vayudoot_node_id", "punjab-node")
    monkeypatch.setattr(settings, "vayudoot_node_region", "punjab")

    body = (await client.get("/node")).json()

    assert body["node_id"] == "punjab-node"
    assert body["region"] == "punjab"


async def test_the_node_endpoint_says_which_country(client, monkeypatch):
    monkeypatch.setattr(settings, "vayudoot_node_country", "PK")
    assert (await client.get("/node")).json()["country"] == "PK"


async def test_the_geojson_feed_is_served_as_geojson(client, monkeypatch):
    from vayudoot import hotspots as hotspot_module

    monkeypatch.setattr(hotspot_module, "current", lambda: [hotspot()])

    response = await client.get("/feed.geojson")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/geo+json")
    body = response.json()
    assert body["type"] == "FeatureCollection"
    assert body["features"][0]["geometry"]["type"] == "Polygon"
    assert "VD-SECRET01" not in response.text


async def test_the_geojson_feed_is_withheld_when_the_feed_is(client, monkeypatch):
    monkeypatch.setattr(settings, "vayudoot_publish_feed", False)
    assert (await client.get("/feed.geojson")).status_code == 404


async def test_the_feed_is_served_as_a_versioned_document(client):
    body = (await client.get("/feed")).json()

    assert body["feed_version"] == "1.0"
    assert "node" in body
    assert "hotspots" in body


async def test_a_node_may_decline_to_publish(client, monkeypatch):
    monkeypatch.setattr(settings, "vayudoot_publish_feed", False)
    assert (await client.get("/feed")).status_code == 404


async def test_the_feed_never_carries_a_case_id(client, monkeypatch):
    """The allowlist, asserted at the edge rather than only at the projection."""
    from vayudoot import hotspots as hotspot_module

    monkeypatch.setattr(hotspot_module, "current", lambda: [hotspot()])

    raw = (await client.get("/feed")).text

    assert "VD-SECRET01" not in raw
    assert "case_ids" not in raw


async def test_neighbours_reports_which_peers_answered(client, monkeypatch, respx_mock):
    monkeypatch.setattr(
        settings,
        "vayudoot_neighbour_feeds",
        "https://up.example.invalid/feed,https://down.example.invalid/feed",
    )
    respx_mock.get("https://up.example.invalid/feed").mock(
        return_value=httpx.Response(200, json=feed_payload())
    )
    respx_mock.get("https://down.example.invalid/feed").mock(
        side_effect=httpx.ConnectError("refused")
    )

    body = (await client.get("/neighbours")).json()

    assert body["configured"] == 2
    assert body["reachable"] == 1
    failed = [n for n in body["neighbours"] if n["error"]]
    assert len(failed) == 1


async def test_a_node_with_no_neighbours_reports_none(client, monkeypatch):
    monkeypatch.setattr(settings, "vayudoot_neighbour_feeds", "")
    body = (await client.get("/neighbours")).json()

    assert body == {"configured": 0, "reachable": 0, "neighbours": []}
