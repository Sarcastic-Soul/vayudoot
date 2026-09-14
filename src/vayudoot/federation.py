"""Publishing hotspots to other instances, and reading theirs.

The brief asks for a platform "designed for interoperability so Indian cities and
states can share predictive models and coordinate resources". This module is the
honest version of that sentence.

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


def identity() -> NodeIdentity:
    """Who this instance says it is."""
    return NodeIdentity(
        node_id=settings.vayudoot_node_id,
        name=settings.vayudoot_node_name,
        region=settings.vayudoot_node_region,
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
