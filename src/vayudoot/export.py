"""Exporting a node's detections for analysis across nations, in BigQuery.

One node answers "what is burning near me". The questions a network is for are
different — how many hotspots each country had last week, which node's
detections are corroborated most often, where the authorities are sitting on
alerts, which corridors run through smoke on both sides of a border — and they
need every node's data in one place with SQL over it. BigQuery's sandbox is that
place at no cost and with no card (hard constraints 3 and 6), so this module
writes what a node knows as files BigQuery loads directly.

**The files are the product; the upload is a convenience.** An export is a
directory of newline-delimited JSON, one file per table, each with a BigQuery
JSON schema beside it and a `manifest.json` saying what was written. That is
useful with no Google Cloud project at all — the files open in anything — and
it is also the durable copy: the sandbox deletes every table 60 days after it is
created, so the way back is to load the files again. `scripts/export_bigquery.py`
loads them when the client library, credentials and a project are present, and
prints the exact `bq` commands when they are not.

What leaves the node, and what does not
---------------------------------------
Every table is an allowlist, built field by field, for `register.py`'s reason: a
field added to a schema later stays private until somebody exports it on
purpose.

* **Hotspots carry an area, never a point.** `area` is a WKT polygon at the
  hotspot's published radius, loaded as `GEOGRAPHY`. A point is an address, and
  hard constraint 7 says a hotspot is never drawn on one. The centre and radius
  are there too, because `/feed` already publishes them.
* **No cases, and nothing from them.** A case holds the reporter's contact and
  their own note. Neither is exported, and nor is anything else from a case:
  the public register is the route for filed complaints.
* **Citizen signals are coarsened.** A citizen report's signal sits where the
  photograph was taken, which is often where somebody lives. Its coordinates are
  rounded to two decimals (about a kilometre, the hotspot minimum radius), its
  id — a case id — is replaced by a digest, and its summary is dropped, because
  a sensor's summary carries whatever name its owner gave it. Instrument signals
  (satellite, station) are public observations and are exported as observed.
* **Alerts are status, not letters.** Who an alert went to, under what statute,
  and whether it was sent. Not the authority's email (a reserved placeholder in
  this instance, and publishing it invites somebody to use it — the register's
  rule), not the facts block, not the model's brief.
* **A neighbour's hotspots stay a neighbour's.** They go to their own table,
  carrying the node that published them, and never into `hotspots`. That is the
  federation rule applied to analysis: a detection copied into our own table
  would count twice and could no longer say whose evidence it rests on.

Snapshots, not upserts
----------------------
The sandbox refuses DML and streaming inserts, so nothing can be updated in
place: every load is a load job appending one export. Each row carries the
`export_id` and `exported_at` of the run that wrote it, and the views this
module defines (`VIEWS`) pick the latest copy — the current map per node, the
latest state of each alert, each signal once. Queries go through the views.

Adding a table
--------------
`register()` takes a `Table`. The forecast ledger is the intended first user:
when a store API for past forecasts exists, a `Table` whose `rows` reads it is
all that exporting it takes — the writer, the schema check, the manifest, the
upload and the `bq` commands all work from the registry.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .config import settings
from .schemas import (
    FeedHotspot,
    Hotspot,
    HotspotAlert,
    NodeIdentity,
    Signal,
    SignalSource,
)
from .tools.geo import point_at

#: Vertices on an exported hotspot's ring. The same number the GeoJSON feed
#: uses, so a polygon here and a polygon on `/feed.geojson` are the same shape.
RING_VERTICES = 32

#: Decimal places a citizen signal's coordinates keep. Two is about 1.1 km of
#: latitude, which matches the hotspot minimum radius: an export must not be
#: sharper about where a citizen stood than the map is.
CITIZEN_COORDINATE_DECIMALS = 2

CITIZEN_SOURCES = frozenset({SignalSource.CITIZEN_REPORT, SignalSource.CITIZEN_SENSOR})

DEFAULT_DATASET = "vayudoot"
DEFAULT_LOCATION = "US"


class ExportError(Exception):
    """A row that does not match its own table's schema. A bug, never data."""


# --------------------------------------------------------------------------- #
# What an export reads
# --------------------------------------------------------------------------- #


@dataclass
class NeighbourFeed:
    """One neighbour's feed as it was read during this export."""

    url: str
    node: NodeIdentity
    feed_version: str
    hotspots: list[FeedHotspot]


@dataclass
class Snapshot:
    """Everything one export reads, gathered once so every table agrees."""

    node: NodeIdentity
    exported_at: datetime
    hotspots: list[Hotspot] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)
    alerts: list[HotspotAlert] = field(default_factory=list)
    neighbours: list[NeighbourFeed] = field(default_factory=list)
    neighbour_errors: list[str] = field(default_factory=list)
    corridors: list = field(default_factory=list)

    @property
    def export_id(self) -> str:
        return f"{self.node.node_id}-{self.exported_at.strftime('%Y%m%dT%H%M%SZ')}"


def collect(include_neighbours: bool = True) -> Snapshot:
    """Read this node's store and, optionally, its neighbours' feeds.

    Reads whichever backend is configured, exactly as the API does. Neighbours
    are read live over HTTP; one that is down is recorded in `neighbour_errors`
    and the export carries on, for `federation.fetch_neighbour`'s reason.
    """
    from . import corridors, federation, hotspots, store

    neighbours: list[NeighbourFeed] = []
    errors: list[str] = []
    if include_neighbours:
        for url in settings.neighbour_feeds:
            result = federation.fetch_neighbour(url)
            if "feed" in result:
                feed = result["feed"]
                neighbours.append(
                    NeighbourFeed(url, feed.node, feed.feed_version, list(feed.hotspots))
                )
            else:
                errors.append(result.get("error", f"{url}: unreadable"))

    return Snapshot(
        node=federation.identity(),
        exported_at=datetime.now(UTC),
        hotspots=hotspots.current(),
        signals=_all_signals(store, hotspots),
        alerts=store.all_alerts(),
        neighbours=neighbours,
        neighbour_errors=errors,
        corridors=corridors.all_corridors(),
    )


def _all_signals(store, hotspots) -> list[Signal]:
    """Stored signals and the ones citizen cases stand for, each once.

    A citizen report's signal is not stored: `hotspots.current` derives it from
    the case on every call. The export derives it the same way, so the signals
    table holds everything the hotspots were built from — coarsened on the way
    out by `signal_rows`.
    """
    derived = (hotspots.signal_from_case(case) for case in store.all_cases())
    unique: dict[str, Signal] = {}
    for signal in [*store.all_signals(), *(s for s in derived if s is not None)]:
        unique.setdefault(signal.signal_id, signal)
    return list(unique.values())


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #


def _f(name: str, kind: str, mode: str = "NULLABLE", description: str = "") -> dict:
    out = {"name": name, "type": kind, "mode": mode}
    if description:
        out["description"] = description
    return out


#: Columns every table starts with, so any row can be traced to the run that
#: wrote it and the views can pick the latest copy.
_EXPORT_COLUMNS = [
    _f("export_id", "STRING", "REQUIRED", "The export run that wrote this row"),
    _f("exported_at", "TIMESTAMP", "REQUIRED", "When that run read the node"),
]


@dataclass(frozen=True)
class Table:
    """One exported table: its schema, how it is laid out, and how its rows are built.

    `partition_field` is a TIMESTAMP column partitioned by day, or None for a
    table too small to be worth partitioning. `clustering` is at most four
    top-level columns, BigQuery's limit.
    """

    name: str
    description: str
    schema: list[dict]
    rows: Callable[[Snapshot], Iterable[dict]]
    partition_field: str | None = None
    clustering: tuple[str, ...] = ()


def _stamp(snapshot: Snapshot) -> dict:
    return {"export_id": snapshot.export_id, "exported_at": _ts(snapshot.exported_at)}


def _ts(moment: datetime | None) -> str | None:
    """A timestamp BigQuery's JSON loader reads unambiguously: ISO 8601 in UTC."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat()


def circle_wkt(latitude: float, longitude: float, radius_km: float) -> str:
    """A hotspot's area as a closed WKT polygon of `RING_VERTICES` points.

    Vertices are placed geodesically, so each is the radius away on the ground.
    WKT is longitude first. BigQuery reads a WKT polygon as the smaller of the
    two regions its ring bounds, so the ring's direction does not matter here;
    it runs counter-clockwise anyway, the way the GeoJSON feed's does.
    """
    step = 360.0 / RING_VERTICES
    ring = []
    for index in range(RING_VERTICES):
        lat, lon = point_at(latitude, longitude, (360.0 - index * step) % 360.0, radius_km)
        ring.append(f"{lon:.6f} {lat:.6f}")
    ring.append(ring[0])
    return f"POLYGON(({', '.join(ring)}))"


def line_wkt(points: Iterable[tuple[float, float]]) -> str:
    """A corridor's waypoints, (lat, lon), as a WKT linestring."""
    return f"LINESTRING({', '.join(f'{lon:.6f} {lat:.6f}' for lat, lon in points)})"


def _value(item) -> str:
    return getattr(item, "value", item)


# -- signals ---------------------------------------------------------------- #

SIGNALS_SCHEMA = [
    *_EXPORT_COLUMNS,
    _f("node_id", "STRING", "REQUIRED"),
    _f("country", "STRING", "REQUIRED", "ISO 3166-1 alpha-2 of the node that holds the signal"),
    _f("signal_id", "STRING", "REQUIRED", "Stable observation id; a digest for citizen signals"),
    _f("source", "STRING", "REQUIRED", "satellite, ground_station, citizen_report, citizen_sensor"),
    _f("independent", "BOOLEAN", "REQUIRED", "True for sources nobody reporting controls"),
    _f("latitude", "FLOAT", "REQUIRED"),
    _f("longitude", "FLOAT", "REQUIRED"),
    _f("coordinate_decimals", "INTEGER", "NULLABLE", "Set when coordinates were coarsened"),
    _f("observed_at", "TIMESTAMP", "REQUIRED"),
    _f("pollution_type", "STRING", "REQUIRED"),
    _f("strength", "FLOAT", "REQUIRED", "How sure we are the observation is real"),
    _f("magnitude", "FLOAT", "REQUIRED", "How large the observed event is"),
    _f("summary", "STRING", "NULLABLE", "Empty for citizen signals"),
]


def signal_rows(snapshot: Snapshot) -> Iterable[dict]:
    node = snapshot.node
    for signal in snapshot.signals:
        citizen = signal.source in CITIZEN_SOURCES
        lat, lon = signal.latitude, signal.longitude
        if citizen:
            lat = round(lat, CITIZEN_COORDINATE_DECIMALS)
            lon = round(lon, CITIZEN_COORDINATE_DECIMALS)
        yield {
            **_stamp(snapshot),
            "node_id": node.node_id,
            "country": node.country,
            "signal_id": _citizen_digest(signal.signal_id) if citizen else signal.signal_id,
            "source": _value(signal.source),
            "independent": signal.is_independent,
            "latitude": float(lat),
            "longitude": float(lon),
            "coordinate_decimals": CITIZEN_COORDINATE_DECIMALS if citizen else None,
            "observed_at": _ts(signal.observed_at),
            "pollution_type": _value(signal.pollution_type),
            "strength": float(signal.strength),
            "magnitude": float(signal.magnitude),
            "summary": "" if citizen else signal.summary,
        }


def _citizen_digest(signal_id: str) -> str:
    """A stable stand-in for a citizen signal's id.

    Stable so the `signals_latest` view can still collapse repeat exports of one
    signal; a digest so the export does not hand out a case id that the register
    or the case API would resolve.
    """
    return "citizen-" + hashlib.sha256(signal_id.encode()).hexdigest()[:16]


# -- hotspots --------------------------------------------------------------- #

_AREA_COLUMNS = [
    _f("pollution_type", "STRING", "REQUIRED"),
    _f("centre_latitude", "FLOAT", "REQUIRED"),
    _f("centre_longitude", "FLOAT", "REQUIRED"),
    _f("radius_km", "FLOAT", "REQUIRED"),
    _f("area", "GEOGRAPHY", "REQUIRED", "The hotspot as a polygon at its radius; never a point"),
    _f("confidence", "FLOAT", "REQUIRED"),
    _f("severity", "STRING", "REQUIRED"),
    _f("corroborated", "BOOLEAN", "REQUIRED", "Whether an instrument supports it"),
    _f("signal_count", "INTEGER", "REQUIRED"),
    _f("first_seen_at", "TIMESTAMP", "REQUIRED"),
    _f("last_seen_at", "TIMESTAMP", "REQUIRED"),
]

HOTSPOTS_SCHEMA = [
    *_EXPORT_COLUMNS,
    _f("node_id", "STRING", "REQUIRED", "The node that detected it"),
    _f("country", "STRING", "REQUIRED", "ISO 3166-1 alpha-2 of the detecting node"),
    _f("hotspot_id", "STRING", "REQUIRED"),
    *_AREA_COLUMNS,
    _f("span_days", "INTEGER", "REQUIRED"),
    _f("satellite_signals", "INTEGER", "REQUIRED"),
    _f("ground_station_signals", "INTEGER", "REQUIRED"),
    _f("citizen_report_signals", "INTEGER", "REQUIRED"),
    _f("citizen_sensor_signals", "INTEGER", "REQUIRED"),
    _f("exposure_population", "INTEGER", "NULLABLE", "People in towns within reach"),
    _f("exposure_radius_km", "FLOAT", "NULLABLE"),
    _f("exposure_towns", "STRING", "REPEATED"),
]


def _area_fields(spot: Hotspot | FeedHotspot) -> dict:
    return {
        "pollution_type": _value(spot.pollution_type),
        "centre_latitude": float(spot.centre_latitude),
        "centre_longitude": float(spot.centre_longitude),
        "radius_km": float(spot.radius_km),
        "area": circle_wkt(spot.centre_latitude, spot.centre_longitude, spot.radius_km),
        "confidence": float(spot.confidence),
        "severity": spot.severity,
        "corroborated": bool(spot.corroborated),
        "signal_count": int(spot.signal_count),
        "first_seen_at": _ts(spot.first_seen_at),
        "last_seen_at": _ts(spot.last_seen_at),
    }


def hotspot_rows(snapshot: Snapshot) -> Iterable[dict]:
    node = snapshot.node
    for spot in snapshot.hotspots:
        counts = {_value(k): v for k, v in spot.source_counts.items()}
        exposure = spot.exposure
        yield {
            **_stamp(snapshot),
            "node_id": node.node_id,
            "country": node.country,
            "hotspot_id": spot.hotspot_id,
            **_area_fields(spot),
            "span_days": int(spot.span_days),
            "satellite_signals": int(counts.get("satellite", 0)),
            "ground_station_signals": int(counts.get("ground_station", 0)),
            "citizen_report_signals": int(counts.get("citizen_report", 0)),
            "citizen_sensor_signals": int(counts.get("citizen_sensor", 0)),
            "exposure_population": exposure.population if exposure else None,
            "exposure_radius_km": float(exposure.radius_km) if exposure else None,
            "exposure_towns": list(exposure.towns) if exposure else [],
        }


# -- neighbour hotspots ----------------------------------------------------- #

NEIGHBOUR_HOTSPOTS_SCHEMA = [
    *_EXPORT_COLUMNS,
    _f("reader_node_id", "STRING", "REQUIRED", "The node that read the feed"),
    _f("reader_country", "STRING", "REQUIRED"),
    _f("feed_url", "STRING", "REQUIRED"),
    _f("feed_version", "STRING", "REQUIRED"),
    _f("source_node_id", "STRING", "REQUIRED", "The node that detected it"),
    _f("source_node_name", "STRING", "NULLABLE"),
    _f("source_region", "STRING", "NULLABLE"),
    _f("source_country", "STRING", "REQUIRED", "ISO 3166-1 alpha-2 of the detecting node"),
    _f("hotspot_id", "STRING", "REQUIRED"),
    *_AREA_COLUMNS,
]


def neighbour_hotspot_rows(snapshot: Snapshot) -> Iterable[dict]:
    reader = snapshot.node
    for feed in snapshot.neighbours:
        for spot in feed.hotspots:
            yield {
                **_stamp(snapshot),
                "reader_node_id": reader.node_id,
                "reader_country": reader.country,
                "feed_url": feed.url,
                "feed_version": feed.feed_version,
                # The feed's own per-hotspot node id wins over the header: a
                # feed row always says whose detection it is.
                "source_node_id": spot.node_id or feed.node.node_id,
                "source_node_name": feed.node.name,
                "source_region": feed.node.region,
                "source_country": (feed.node.country or "").upper(),
                "hotspot_id": spot.hotspot_id,
                **_area_fields(spot),
            }


# -- alerts ----------------------------------------------------------------- #

ALERTS_SCHEMA = [
    *_EXPORT_COLUMNS,
    _f("node_id", "STRING", "REQUIRED"),
    _f("country", "STRING", "REQUIRED"),
    _f("alert_id", "STRING", "REQUIRED"),
    _f("hotspot_id", "STRING", "REQUIRED"),
    _f("status", "STRING", "REQUIRED", "draft, awaiting_confirmation or sent"),
    _f("created_at", "TIMESTAMP", "REQUIRED"),
    _f("updated_at", "TIMESTAMP", "REQUIRED"),
    _f("sent_at", "TIMESTAMP", "NULLABLE"),
    _f("area_name", "STRING", "NULLABLE", "City, district and state; never a street"),
    _f("area", "GEOGRAPHY", "REQUIRED", "The hotspot's polygon when the alert was drafted"),
    _f("pollution_type", "STRING", "REQUIRED"),
    _f("severity", "STRING", "REQUIRED"),
    _f("confidence", "FLOAT", "REQUIRED"),
    _f("corroborated", "BOOLEAN", "REQUIRED"),
    _f("exposure_population", "INTEGER", "NULLABLE"),
    _f("authority_name", "STRING", "REQUIRED"),
    _f("authority_tier", "STRING", "REQUIRED"),
    _f("jurisdiction_coverage", "STRING", "REQUIRED", "exact, fallback or generic"),
    _f("statute", "STRING", "NULLABLE"),
    _f("response_window_days", "INTEGER", "NULLABLE"),
    _f("cited_imagery", "BOOLEAN", "REQUIRED", "Whether a satellite image reading was cited"),
]


def alert_rows(snapshot: Snapshot) -> Iterable[dict]:
    node = snapshot.node
    for alert in snapshot.alerts:
        spot = alert.hotspot
        law = alert.jurisdiction
        exposure = spot.exposure
        yield {
            **_stamp(snapshot),
            "node_id": node.node_id,
            "country": node.country,
            "alert_id": alert.alert_id,
            "hotspot_id": alert.hotspot_id,
            "status": _value(alert.status),
            "created_at": _ts(alert.created_at),
            "updated_at": _ts(alert.updated_at),
            "sent_at": _ts(alert.sent_at),
            "area_name": alert.area,
            "area": circle_wkt(spot.centre_latitude, spot.centre_longitude, spot.radius_km),
            "pollution_type": _value(spot.pollution_type),
            "severity": spot.severity,
            "confidence": float(spot.confidence),
            "corroborated": bool(spot.corroborated),
            "exposure_population": exposure.population if exposure else None,
            "authority_name": law.authority_name,
            "authority_tier": law.authority_tier,
            "jurisdiction_coverage": law.coverage,
            "statute": law.statute,
            "response_window_days": law.response_window_days,
            "cited_imagery": alert.imagery is not None,
        }


# -- corridors -------------------------------------------------------------- #

CORRIDORS_SCHEMA = [
    *_EXPORT_COLUMNS,
    _f("node_id", "STRING", "REQUIRED", "The node whose corridor table this came from"),
    _f("corridor_id", "STRING", "REQUIRED"),
    _f("name", "STRING", "REQUIRED"),
    _f("states", "STRING", "REPEATED"),
    _f("countries", "STRING", "REPEATED"),
    _f("waypoint_count", "INTEGER", "REQUIRED"),
    _f("path", "GEOGRAPHY", "REQUIRED", "The waypoints joined as a line"),
]


def corridor_rows(snapshot: Snapshot) -> Iterable[dict]:
    for corridor in snapshot.corridors:
        if len(corridor.waypoints) < 2:
            continue
        yield {
            **_stamp(snapshot),
            "node_id": snapshot.node.node_id,
            "corridor_id": corridor.corridor_id,
            "name": corridor.name,
            "states": list(corridor.states),
            "countries": list(corridor.countries),
            "waypoint_count": len(corridor.waypoints),
            "path": line_wkt(corridor.waypoints),
        }


# -- export runs ------------------------------------------------------------ #

EXPORTS_SCHEMA = [
    *_EXPORT_COLUMNS,
    _f("node_id", "STRING", "REQUIRED"),
    _f("node_name", "STRING", "NULLABLE"),
    _f("region", "STRING", "NULLABLE"),
    _f("country", "STRING", "REQUIRED"),
    _f("vayudoot_version", "STRING", "NULLABLE"),
    _f("signal_count", "INTEGER", "REQUIRED"),
    _f("hotspot_count", "INTEGER", "REQUIRED"),
    _f("alert_count", "INTEGER", "REQUIRED"),
    _f("neighbour_hotspot_count", "INTEGER", "REQUIRED"),
    _f("neighbour_errors", "STRING", "REPEATED"),
]


def export_rows(snapshot: Snapshot) -> Iterable[dict]:
    """One row per export run.

    It is what `hotspots_current` keys on: a node whose latest export had no
    hotspots must show none, and the hotspot table alone cannot say that — its
    newest rows for that node would be from an older run.
    """
    node = snapshot.node
    yield {
        **_stamp(snapshot),
        "node_id": node.node_id,
        "node_name": node.name,
        "region": node.region,
        "country": node.country,
        "vayudoot_version": __version__,
        "signal_count": len(snapshot.signals),
        "hotspot_count": len(snapshot.hotspots),
        "alert_count": len(snapshot.alerts),
        "neighbour_hotspot_count": sum(len(f.hotspots) for f in snapshot.neighbours),
        "neighbour_errors": list(snapshot.neighbour_errors),
    }


# Partitioning and clustering, and why, for the sandbox's limits (10 GiB of
# storage, 1 TiB of queries a month, every table and partition gone after 60
# days). At one node's volume none of these tables comes near either limit, and
# BigQuery bills at least 10 MB per table a query touches, so partitioning is
# not about bytes. It is about the 60 days: a table partitioned by day loses its
# oldest days one at a time, instead of the whole history at once. Clustering by
# country and node is what the cross-nation queries filter and group on.
#
# Snapshot tables partition on `exported_at`, because the views read the latest
# export and that prunes to one day. Signals partition on `observed_at`, the
# column every signal question filters on — with one consequence worth knowing:
# a signal observed more than 60 days ago lands in a partition the sandbox has
# already expired, and is dropped. The NDJSON file keeps it.
# Small reference tables (runs, corridors) are not partitioned at all.
TABLES: list[Table] = [
    Table(
        "exports",
        "One row per export run: which node, when, and how much it held.",
        EXPORTS_SCHEMA,
        export_rows,
        partition_field=None,
        clustering=("country", "node_id"),
    ),
    Table(
        "signals",
        "Observations: satellite, station, citizen report, citizen sensor.",
        SIGNALS_SCHEMA,
        signal_rows,
        partition_field="observed_at",
        clustering=("country", "node_id", "source"),
    ),
    Table(
        "hotspots",
        "This node's own hotspots, one snapshot per export. Areas, never points.",
        HOTSPOTS_SCHEMA,
        hotspot_rows,
        partition_field="exported_at",
        clustering=("country", "node_id", "corroborated"),
    ),
    Table(
        "neighbour_hotspots",
        "Hotspots read from neighbours' feeds, with the node that detected each.",
        NEIGHBOUR_HOTSPOTS_SCHEMA,
        neighbour_hotspot_rows,
        partition_field="exported_at",
        clustering=("source_country", "source_node_id", "reader_node_id"),
    ),
    Table(
        "alerts",
        "Hotspot alerts: who they went to and whether they were sent. No letters.",
        ALERTS_SCHEMA,
        alert_rows,
        partition_field="exported_at",
        clustering=("country", "node_id", "status"),
    ),
    Table(
        "corridors",
        "The corridors this node forecasts along, as lines.",
        CORRIDORS_SCHEMA,
        corridor_rows,
        partition_field=None,
        clustering=("corridor_id",),
    ),
]


def register(table: Table) -> None:
    """Add a table to every export. The extension point for the forecast ledger.

    A table registered twice under one name replaces the first, so a module that
    registers at import time is safe to import again.
    """
    for index, existing in enumerate(TABLES):
        if existing.name == table.name:
            TABLES[index] = table
            return
    TABLES.append(table)


def table(name: str) -> Table:
    return next(t for t in TABLES if t.name == name)


# --------------------------------------------------------------------------- #
# Views: the latest copy of everything
# --------------------------------------------------------------------------- #

#: View name -> SQL, with `{ds}` standing for the fully qualified dataset
#: (`project.dataset`). Every query in `docs/bigquery.md` reads these rather
#: than the tables, because the tables hold one copy per export.
VIEWS: dict[str, str] = {
    # The export run each node made last.
    "latest_exports": """
SELECT * FROM `{ds}.exports`
WHERE TRUE
QUALIFY ROW_NUMBER() OVER (PARTITION BY node_id ORDER BY exported_at DESC) = 1
""",
    # Each node's map as of its latest export. Keyed on the exports table so a
    # node whose last export was empty shows nothing, not an older map.
    "hotspots_current": """
SELECT h.*
FROM `{ds}.hotspots` AS h
JOIN `{ds}.latest_exports` AS l
  ON h.node_id = l.node_id AND h.export_id = l.export_id
""",
    # Every hotspot any export has seen, once, at its most recent snapshot.
    "hotspots_seen": """
SELECT * FROM `{ds}.hotspots`
WHERE TRUE
QUALIFY ROW_NUMBER() OVER (PARTITION BY node_id, hotspot_id ORDER BY exported_at DESC) = 1
""",
    # What each reading node's neighbours reported, as of its latest export.
    "neighbour_hotspots_current": """
SELECT n.*
FROM `{ds}.neighbour_hotspots` AS n
JOIN `{ds}.latest_exports` AS l
  ON n.reader_node_id = l.node_id AND n.export_id = l.export_id
""",
    # Every neighbour hotspot once, however many nodes read it how many times.
    "neighbour_hotspots_seen": """
SELECT * FROM `{ds}.neighbour_hotspots`
WHERE TRUE
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY source_node_id, hotspot_id ORDER BY exported_at DESC
) = 1
""",
    "signals_latest": """
SELECT * FROM `{ds}.signals`
WHERE TRUE
QUALIFY ROW_NUMBER() OVER (PARTITION BY node_id, signal_id ORDER BY exported_at DESC) = 1
""",
    "alerts_current": """
SELECT * FROM `{ds}.alerts`
WHERE TRUE
QUALIFY ROW_NUMBER() OVER (PARTITION BY node_id, alert_id ORDER BY exported_at DESC) = 1
""",
    "corridors_current": """
SELECT * FROM `{ds}.corridors`
WHERE TRUE
QUALIFY ROW_NUMBER() OVER (PARTITION BY corridor_id ORDER BY exported_at DESC) = 1
""",
}


def view_sql(name: str, project: str, dataset: str = DEFAULT_DATASET) -> str:
    return VIEWS[name].strip().format(ds=f"{project}.{dataset}")


# --------------------------------------------------------------------------- #
# Checking and writing
# --------------------------------------------------------------------------- #


def check_row(row: dict, schema: list[dict]) -> list[str]:
    """Every way a row disagrees with its schema, as readable problems.

    Checked on the way out, so a bad row fails here with a sentence rather than
    in a load job with a byte offset. BigQuery refuses a row with an unknown
    field unless told to ignore it, so an extra key is a problem too.
    """
    problems: list[str] = []
    fields = {f["name"]: f for f in schema}
    for key in row:
        if key not in fields:
            problems.append(f"{key}: not in the schema")
    for name, spec in fields.items():
        value = row.get(name)
        mode = spec.get("mode", "NULLABLE")
        if mode == "REPEATED":
            if not isinstance(value, list):
                problems.append(f"{name}: REPEATED needs a list, got {type(value).__name__}")
                continue
            problems.extend(_type_problem(name, spec["type"], v) for v in value)
            continue
        if value is None:
            if mode == "REQUIRED":
                problems.append(f"{name}: REQUIRED but missing")
            continue
        problems.append(_type_problem(name, spec["type"], value))
    return [p for p in problems if p]


def _type_problem(name: str, kind: str, value) -> str:
    ok = {
        "STRING": lambda v: isinstance(v, str),
        "INTEGER": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "FLOAT": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "BOOLEAN": lambda v: isinstance(v, bool),
        "TIMESTAMP": _is_timestamp,
        "GEOGRAPHY": lambda v: (
            isinstance(v, str) and v.split("(", 1)[0].strip() in {"POLYGON", "LINESTRING"}
        ),
    }.get(kind)
    if ok is None:
        return f"{name}: no check for type {kind}"
    return "" if ok(value) else f"{name}: {value!r} is not a {kind}"


def _is_timestamp(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False


@dataclass
class Manifest:
    """What an export wrote, and enough to load it without reading the code."""

    export_id: str
    exported_at: str
    node: dict
    directory: str
    tables: list[dict]
    neighbour_errors: list[str]

    def to_json(self) -> str:
        return json.dumps(self.__dict__, indent=2)

    @classmethod
    def read(cls, directory: Path) -> Manifest:
        return cls(**json.loads((Path(directory) / "manifest.json").read_text()))


def write(snapshot: Snapshot, out_dir: Path) -> Manifest:
    """Write every registered table as NDJSON plus its schema, and a manifest.

    Each row is checked against its schema before anything is written, so a
    failed export leaves no partial files that look like a good one.
    """
    out_dir = Path(out_dir)
    built: list[tuple[Table, list[dict]]] = []
    for spec in TABLES:
        rows = list(spec.rows(snapshot))
        for index, row in enumerate(rows):
            if problems := check_row(row, spec.schema):
                raise ExportError(f"{spec.name} row {index}: " + "; ".join(problems))
        built.append((spec, rows))

    out_dir.mkdir(parents=True, exist_ok=True)
    listed = []
    for spec, rows in built:
        data = out_dir / f"{spec.name}.ndjson"
        schema = out_dir / f"{spec.name}.schema.json"
        data.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
        schema.write_text(json.dumps(spec.schema, indent=2) + "\n", encoding="utf-8")
        listed.append(
            {
                "name": spec.name,
                "description": spec.description,
                "rows": len(rows),
                "data": data.name,
                "schema": schema.name,
                "partition_field": spec.partition_field,
                "clustering": list(spec.clustering),
            }
        )

    manifest = Manifest(
        export_id=snapshot.export_id,
        exported_at=_ts(snapshot.exported_at) or "",
        node=snapshot.node.model_dump(mode="json", exclude={"contact"}),
        directory=str(out_dir.resolve()),
        tables=listed,
        neighbour_errors=list(snapshot.neighbour_errors),
    )
    (out_dir / "manifest.json").write_text(manifest.to_json() + "\n", encoding="utf-8")
    return manifest


def export(out_dir: Path, include_neighbours: bool = True) -> Manifest:
    """Read this node and write an export directory. No network but neighbours'."""
    return write(collect(include_neighbours=include_neighbours), out_dir)


# --------------------------------------------------------------------------- #
# Loading: `bq` commands, or the client library
# --------------------------------------------------------------------------- #

PROJECT_PLACEHOLDER = "YOUR_PROJECT_ID"


def bq_commands(
    manifest: Manifest,
    project: str = "",
    dataset: str = DEFAULT_DATASET,
    location: str = DEFAULT_LOCATION,
) -> list[str]:
    """The exact shell commands that load an export, for when the library is absent.

    Load jobs only (`bq load`), never `bq insert`: the sandbox refuses streaming
    inserts. An empty table is created with `bq mk` rather than loaded, so the
    views that read it still resolve. Views are written with `bq mk --view` —
    a table definition, not DML — from the files `write_view_files` leaves.
    """
    project = project or PROJECT_PLACEHOLDER
    root = Path(manifest.directory)
    base = f"bq --project_id={project} --location={location}"
    lines = [
        "# Once: the dataset. 'already exists' is fine.",
        f"{base} mk --dataset {project}:{dataset}",
    ]
    for entry in manifest.tables:
        target = f"{project}:{dataset}.{entry['name']}"
        layout = []
        if entry["partition_field"]:
            layout.append(
                f"--time_partitioning_type=DAY --time_partitioning_field={entry['partition_field']}"
            )
        if entry["clustering"]:
            layout.append(f"--clustering_fields={','.join(entry['clustering'])}")
        flags = " ".join(layout)
        schema = root / entry["schema"]
        if entry["rows"]:
            lines.append(
                f"{base} load --source_format=NEWLINE_DELIMITED_JSON {flags} "
                f"{target} {root / entry['data']} {schema}"
            )
        else:
            lines.append(f"# {entry['name']} is empty this run: create it so the views resolve.")
            lines.append(f"{base} mk --table {flags} {target} {schema}")
    lines.append("# Views (latest copy of everything). Re-running them is a no-op error.")
    for name in VIEWS:
        path = root / "views" / f"{name}.sql"
        lines.append(
            f'{base} mk --use_legacy_sql=false --view "$(cat {path})" {project}:{dataset}.{name}'
        )
    return lines


def write_view_files(
    manifest: Manifest, project: str = "", dataset: str = DEFAULT_DATASET
) -> list[Path]:
    """Write each view's SQL, qualified with the project, for `bq mk --view`."""
    folder = Path(manifest.directory) / "views"
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for name in VIEWS:
        path = folder / f"{name}.sql"
        path.write_text(view_sql(name, project or PROJECT_PLACEHOLDER, dataset) + "\n")
        written.append(path)
    return written


def upload(
    manifest: Manifest,
    project: str,
    dataset: str = DEFAULT_DATASET,
    location: str = DEFAULT_LOCATION,
    client=None,
    library=None,
) -> dict:
    """Load an export into BigQuery with load jobs, creating what is missing.

    Needs `google-cloud-bigquery` (the `[bigquery]` extra) and application
    default credentials. Everything it does is allowed in the sandbox: a dataset
    and tables are created, files are loaded with load jobs (free, and not
    streaming), and views are table definitions. Nothing is updated in place.

    Refuses to load the same export into the same dataset twice — the views pick
    the latest copy by time, and two copies of one run would count twice. The
    record of what was loaded where is a file in the export directory.
    """
    if library is None:
        from google.cloud import bigquery
    else:  # a stand-in, so the tests can check the calls without a network
        bigquery = library

    root = Path(manifest.directory)
    target = f"{project}.{dataset}"
    marker = root / "uploaded.json"
    done = json.loads(marker.read_text()) if marker.exists() else []
    if target in done:
        return {"target": target, "skipped": True, "reason": "this export is already loaded"}

    client = client or bigquery.Client(project=project, location=location)
    ds = bigquery.Dataset(target)
    ds.location = location
    client.create_dataset(ds, exists_ok=True)

    loaded: dict[str, int] = {}
    for entry in manifest.tables:
        schema_json = json.loads((root / entry["schema"]).read_text())
        schema = [bigquery.SchemaField.from_api_repr(f) for f in schema_json]
        partitioning = (
            bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY, field=entry["partition_field"]
            )
            if entry["partition_field"]
            else None
        )
        clustering = entry["clustering"] or None
        table_id = f"{target}.{entry['name']}"
        if not entry["rows"]:
            empty = bigquery.Table(table_id, schema=schema)
            empty.time_partitioning = partitioning
            empty.clustering_fields = clustering
            client.create_table(empty, exists_ok=True)
            loaded[entry["name"]] = 0
            continue
        config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            schema=schema,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
            time_partitioning=partitioning,
            clustering_fields=clustering,
        )
        with (root / entry["data"]).open("rb") as handle:
            job = client.load_table_from_file(handle, table_id, job_config=config)
        job.result()
        loaded[entry["name"]] = entry["rows"]

    for name in VIEWS:
        view = bigquery.Table(f"{target}.{name}")
        view.view_query = view_sql(name, project, dataset)
        view.view_use_legacy_sql = False
        client.delete_table(view, not_found_ok=True)
        client.create_table(view)

    marker.write_text(json.dumps([*done, target], indent=2) + "\n")
    return {"target": target, "skipped": False, "loaded": loaded, "views": list(VIEWS)}
