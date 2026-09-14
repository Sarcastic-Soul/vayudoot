"""Publishing hotspots to other nodes, and reading theirs.

Three of these hold properties rather than check functions, and each is marked
where it appears: the feed is an allowlist, a neighbour's hotspots are never
laundered into our own, and a feed reporting our own node id is refused. The
first two are the reasons `federation.py` exists in the shape it does; the third
is the failure that would silently manufacture corroboration out of nothing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from vayudoot import federation
from vayudoot.config import settings
from vayudoot.schemas import FeedHotspot, Hotspot, HotspotFeed, PollutionType

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


def feed_payload(node_id: str = "punjab-node", hotspots: list | None = None) -> dict:
    return json.loads(
        HotspotFeed(
            node=federation.NodeIdentity(
                node_id=node_id, name="Punjab node", region="punjab"
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
