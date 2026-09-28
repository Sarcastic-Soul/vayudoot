"""Publishing hotspots to other instances, and reading theirs.

The brief asks for a platform "designed for interoperability so BRICS nations can
share predictive models and coordinate resources". This module is the honest
version of that sentence.

**What is shared is a detection layer, not trained weights.** A node publishes
the hotspots it has found on a versioned open feed, and reads its neighbours'.
Federated training of a shared model is a real idea and is not what this is;
claiming it without building it would cost more than it earns. `docs/SCOPE.md`
records that decision under v0.3.

The reason it is worth building at all is the one case that matters most in
India: stubble burning in Punjab and Haryana arrives in Delhi about a day and a
half later. A Delhi instance that can only see Delhi's own reports finds out when
the smoke does. A Delhi instance reading a Punjab node's feed can forecast it
while the air is still clean, which is the difference between monitoring and
warning — and it needs no model training whatsoever, only a feed somebody
publishes.

The same smoke does not stop at the international border either. Pakistan's
Punjab burns the same paddy stubble on the same calendar, Lahore is fifty
kilometres from Amritsar, and the north-westerly that carries Ludhiana's smoke to
Delhi carries Lahore's with it. Nothing in the contract is Indian: a node says
which country it is in (`NodeIdentity.country`), and a feed from across a
border is read exactly like one from across a state line — as forecasting
context, never as our own detection.

Two properties are deliberate:

`FeedHotspot` is an explicit allowlist rather than a serialised `Hotspot`, for
`register.py`'s reason: a field added to `Hotspot` later stays private until
somebody publishes it on purpose. Signals and case ids are not in it. A neighbour
needs to know that something is burning and how sure we are; it has no business
knowing which of our citizens reported it.

A neighbour's hotspots never become our own. They are carried with their origin
node attached and used as forecasting context, never republished as ours and
never folded into our own detection. A node that laundered a neighbour's
detection into its own feed would let one bad instance contaminate the whole
network, and the corroboration rule in hard constraint 7 would be meaningless
because nobody could tell whose evidence it rested on.
"""

from __future__ import annotations

import httpx

from .config import settings
from .schemas import FeedHotspot, HotspotFeed, NodeIdentity
from .tools.geo import point_at


def identity() -> NodeIdentity:
    """Who this instance says it is."""
    return NodeIdentity(
        node_id=settings.vayudoot_node_id,
        name=settings.vayudoot_node_name,
        region=settings.vayudoot_node_region,
        country=settings.vayudoot_node_country.strip().upper(),
        instance_url=settings.vayudoot_node_url,
        contact=settings.vayudoot_node_contact,
    )


def publish(hotspots: list) -> HotspotFeed:
    """This node's hotspots, projected for publication.

    Uncorroborated hotspots are published too, carrying their flag and their
    capped confidence. Withholding them would be the wrong call: a neighbour
    deciding what to trust needs to see the weak signals as well as the strong
    ones, and the flag is what lets it decide. Hiding them would also mean a
    citizen-reported fire nobody has corroborated yet is invisible to the state
    downwind of it, which is precisely the gap this network exists to close.

    `Hotspot.exposure` is deliberately not published. It is not an observation:
    it is our gazetteer's arithmetic over the centre and radius, which are
    already on the feed, so a neighbour can compute it from its own population
    data — and should, because a node across a border may hold a better table for
    its own side than we do. Publishing ours would invite a neighbour to cite our
    population estimate as if it were part of the detection, and would change the
    1.0 contract for a number nobody reading the feed needs from us.
    """
    node_id = settings.vayudoot_node_id
    published = [
        FeedHotspot(
            hotspot_id=spot.hotspot_id,
            node_id=node_id,
            pollution_type=spot.pollution_type,
            centre_latitude=spot.centre_latitude,
            centre_longitude=spot.centre_longitude,
            radius_km=spot.radius_km,
            confidence=spot.confidence,
            severity=spot.severity,
            corroborated=spot.corroborated,
            signal_count=spot.signal_count,
            first_seen_at=spot.first_seen_at,
            last_seen_at=spot.last_seen_at,
        )
        for spot in hotspots
    ]
    return HotspotFeed(
        node=identity(),
        hotspot_count=len(published),
        hotspots=published,
    )


#: Vertices on the ring approximating a hotspot's circle. Thirty-two keeps the
#: polygon within half a percent of the true radius everywhere on the boundary,
#: which is far below the uncertainty in the radius itself, at a size a feed of a
#: few hundred hotspots can carry.
GEOJSON_RING_VERTICES = 32


def publish_geojson(hotspots: list) -> dict:
    """This node's feed as an RFC 7946 GeoJSON FeatureCollection.

    `/feed` is this project's own contract; GeoJSON is everybody's. QGIS, ArcGIS,
    Leaflet and Google Earth all open it with no code, which is what lets a state
    board or another country's environment agency look at what a node found
    without first adopting anything of ours.

    **Each hotspot is a polygon, never a point.** A point is an address, and a
    point on a public map is an accusation against whoever sits under it. The
    ring is the hotspot's published radius, so the area on the map is exactly the
    area the feed claims and no tighter. Hard constraint 7.

    **The properties are `publish()`'s projection, not a second allowlist.** The
    feature properties are the `FeedHotspot` fields and nothing else, produced by
    calling `publish()` and reshaping its output. Two separate projections would
    drift, and the one that drifted would be the one that leaked a case id.

    The node's identity rides on the collection as a foreign member (RFC 7946
    section 6.1), and each feature also carries the node id and country, because
    a GIS layer is routinely split and merged and a feature that has lost its
    collection must still say whose detection it is.
    """
    feed = publish(hotspots)
    node = feed.node.model_dump(mode="json")
    features = []
    for spot in feed.hotspots:
        properties = spot.model_dump(mode="json")
        properties["node_country"] = feed.node.country
        properties["feed_version"] = feed.feed_version
        features.append(
            {
                "type": "Feature",
                "id": spot.hotspot_id,
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        _circle_ring(spot.centre_latitude, spot.centre_longitude, spot.radius_km)
                    ],
                },
                "properties": properties,
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        # Foreign members. A reader that knows only RFC 7946 ignores them; one
        # that knows this contract gets the same header `/feed` carries.
        "feed_version": feed.feed_version,
        "node": node,
        "generated_at": feed.generated_at.isoformat(),
        "hotspot_count": feed.hotspot_count,
    }


def _circle_ring(latitude: float, longitude: float, radius_km: float) -> list[list[float]]:
    """A closed, counter-clockwise ring of [lon, lat] pairs around a centre.

    RFC 7946 requires the exterior ring of a polygon to be closed (first point
    repeated last) and counter-clockwise, and every position to be longitude
    first. Compass bearings run clockwise, so the ring walks them backwards.
    Vertices are placed geodesically with `geo.point_at`, so each one is the
    radius away from the centre on the ground rather than in degrees, which
    would squash the circle into an ellipse at Delhi's latitude.
    """
    step = 360.0 / GEOJSON_RING_VERTICES
    ring = []
    for index in range(GEOJSON_RING_VERTICES):
        lat, lon = point_at(latitude, longitude, (360.0 - index * step) % 360.0, radius_km)
        ring.append([round(lon, 6), round(lat, 6)])
    ring.append(list(ring[0]))
    return ring


def fetch_neighbour(url: str, timeout: float = 15.0) -> dict:
    """Read one neighbour's feed.

    Returns a plain dict and never raises, the same contract every tool in this
    project follows: a neighbour that is down, slow, or serving something
    unparseable is an ordinary condition on a federated network, not an
    exception. A node whose forecasting stops because a peer is offline is worse
    than one that carries on with less context.
    """
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # noqa: BLE001 - a peer being down is not exceptional
        return {"error": f"Neighbour feed {url} could not be read: {exc}", "url": url}

    try:
        feed = HotspotFeed.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 - a malformed peer must not crash us
        return {"error": f"Neighbour feed {url} was not a valid feed: {exc}", "url": url}

    if feed.node.node_id == settings.vayudoot_node_id:
        # Reading our own feed back — through a load balancer, a copied
        # configuration, or a neighbour that mirrors us — would double every
        # hotspot and look like independent agreement. It is not.
        return {"error": f"Neighbour feed {url} reports our own node id", "url": url}

    return {"url": url, "feed": feed, "hotspot_count": feed.hotspot_count}


def neighbour_hotspots() -> list[FeedHotspot]:
    """Every hotspot our configured neighbours are currently reporting.

    Failures are skipped rather than raised. The caller gets what could be read.
    """
    collected: list[FeedHotspot] = []
    for url in settings.neighbour_feeds:
        result = fetch_neighbour(url)
        feed = result.get("feed")
        if isinstance(feed, HotspotFeed):
            collected.extend(feed.hotspots)
    return collected


def as_context(feed_hotspots: list[FeedHotspot]) -> list:
    """Neighbour hotspots in the shape the forecast stage reads.

    `forecast_location` takes `Hotspot` objects, and a neighbour's are
    `FeedHotspot`. This adapts them for that one purpose. They are not stored,
    not detected against, and not republished — see the module docstring.
    """
    from .schemas import Hotspot

    return [
        Hotspot(
            hotspot_id=spot.hotspot_id,
            pollution_type=spot.pollution_type,
            centre_latitude=spot.centre_latitude,
            centre_longitude=spot.centre_longitude,
            radius_km=spot.radius_km,
            confidence=spot.confidence,
            severity=spot.severity,
            corroborated=spot.corroborated,
            signal_count=spot.signal_count,
            first_seen_at=spot.first_seen_at,
            last_seen_at=spot.last_seen_at,
            span_days=max((spot.last_seen_at - spot.first_seen_at).days, 0),
        )
        for spot in feed_hotspots
    ]
