"""The BigQuery export: shape, geometry, privacy, and agreement with its own schemas.

No network anywhere. Neighbour feeds are handed in as already-read objects, and
the upload is checked against a stand-in for the client library.
"""

from __future__ import annotations

import json
import re
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from vayudoot import export, store
from vayudoot.config import settings
from vayudoot.schemas import (
    AlertStatus,
    Case,
    CaseStatus,
    EvidencePacket,
    FeedHotspot,
    ForecastOutcome,
    ForecastRecord,
    HotspotAlert,
    HotspotSnapshot,
    Jurisdiction,
    NodeIdentity,
    PollutionType,
    Report,
    Signal,
    SignalSource,
)

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 9, 29, 6, 0, tzinfo=UTC)
CONTACT = "+91 98100 12345"
LUDHIANA = (30.9010, 75.8573)


def _satellite(lat: float, lon: float, hours: int) -> Signal:
    seen = NOW - timedelta(hours=hours)
    return Signal(
        source=SignalSource.SATELLITE,
        signal_id=f"viirs:{lat:.5f}:{lon:.5f}:{seen.isoformat()}",
        latitude=lat,
        longitude=lon,
        observed_at=seen,
        strength=0.85,
        magnitude=0.9,
        summary="Satellite thermal detection, 112 MW radiative power",
    )


def _citizen_case(lat: float, lon: float) -> Case:
    report = Report(
        report_id="r1",
        latitude=lat,
        longitude=lon,
        note=f"Burning every night behind my house, call me on {CONTACT}",
        reporter_contact=CONTACT,
        observed_at=NOW - timedelta(hours=2),
    )
    return Case(
        case_id="VD-CITIZEN1",
        report=report,
        status=CaseStatus.AWAITING_CONFIRMATION,
        evidence=EvidencePacket(
            pollution_type=PollutionType.OPEN_WASTE_BURNING,
            confidence=0.8,
            severity="high",
        ),
    )


def _alert(hotspot) -> HotspotAlert:
    return HotspotAlert(
        alert_id="VDA-00000001",
        hotspot_id=hotspot.hotspot_id,
        hotspot=HotspotSnapshot.of(hotspot),
        area="Ludhiana, Punjab",
        jurisdiction=Jurisdiction(
            authority_name="Punjab Pollution Control Board",
            authority_tier="state",
            email="ppcb@ppcb.invalid",
            statute="Air (Prevention and Control of Pollution) Act, 1981",
            response_window_days=30,
        ),
        facts="FACTS BLOCK",
        status=AlertStatus.AWAITING_CONFIRMATION,
    )


@pytest.fixture
def seeded():
    """A store holding an instrument hotspot, a citizen case with contact, and an alert."""
    from vayudoot import hotspots

    store.save_signals([_satellite(*LUDHIANA, 30), _satellite(*LUDHIANA, 6)])
    store.save(_citizen_case(28.623456, 77.328765))
    spot = next(h for h in hotspots.current() if h.corroborated)
    store.save_alert(_alert(spot))
    store.save_forecast_record(_forecast())
    return spot


def _forecast() -> ForecastRecord:
    return ForecastRecord(
        forecast_id="VDF-00000001",
        made_at=NOW - timedelta(days=4),
        latitude=30.901034,
        longitude=75.857312,
        location_name="Ludhiana",
        corridor_id="punjab-delhi",
        horizon_hours=72,
        window_start=NOW - timedelta(days=4),
        window_end=NOW - timedelta(days=1),
        risk="high",
        confidence=0.6,
        forecaster_version="2",
        prompt_sha256="ab" * 32,
        model_id="gemini-3.5-flash-lite",
        outcome=ForecastOutcome(
            status="scored",
            pollutant="pm25",
            observed_value=140.0,
            observed_band="high",
            band_error=0,
            persistence_band="elevated",
            cams_band="elevated",
        ),
    )


def _neighbour() -> export.NeighbourFeed:
    node = NodeIdentity(node_id="lahore-node", name="Lahore demo", region="punjab-pk", country="pk")
    spot = FeedHotspot(
        hotspot_id="VDH-PK000001",
        node_id="lahore-node",
        pollution_type=PollutionType.UNCLEAR,
        centre_latitude=31.1187,
        centre_longitude=74.4503,
        radius_km=3.0,
        confidence=0.9,
        severity="severe",
        corroborated=True,
        signal_count=3,
        first_seen_at=NOW - timedelta(days=1),
        last_seen_at=NOW,
    )
    return export.NeighbourFeed("http://lahore.example/feed", node, "1.0", [spot])


def _write(tmp_path: Path, neighbours=None) -> tuple[export.Manifest, Path]:
    snapshot = export.collect(include_neighbours=False)
    snapshot.neighbours = neighbours or []
    out = tmp_path / "out"
    return export.write(snapshot, out), out


def _rows(out: Path, name: str) -> list[dict]:
    lines = (out / f"{name}.ndjson").read_text().splitlines()
    return [json.loads(line) for line in lines if line]


def test_export_writes_every_table_with_a_schema_and_a_manifest(tmp_path, seeded):
    manifest, out = _write(tmp_path, [_neighbour()])

    names = {t["name"] for t in manifest.tables}
    assert names == {
        "exports", "signals", "hotspots", "neighbour_hotspots", "alerts", "corridors",
        "forecast_ledger",
    }
    for entry in manifest.tables:
        assert (out / entry["data"]).exists()
        assert (out / entry["schema"]).exists()
        assert len(_rows(out, entry["name"])) == entry["rows"]
    assert json.loads((out / "manifest.json").read_text())["export_id"] == manifest.export_id

    hotspots = _rows(out, "hotspots")
    assert hotspots and all(r["node_id"] == settings.vayudoot_node_id for r in hotspots)
    assert all(r["country"] == "IN" for r in hotspots)
    assert all(r["export_id"] == manifest.export_id for r in hotspots)
    neighbour = _rows(out, "neighbour_hotspots")
    origins = [(r["source_node_id"], r["source_country"]) for r in neighbour]
    assert origins == [("lahore-node", "PK")]
    assert _rows(out, "exports")[0]["neighbour_hotspot_count"] == 1


def test_every_row_matches_its_schema_file(tmp_path, seeded):
    """The schema files are what BigQuery loads against, so they are what rows must match.

    Checked from the files on disk rather than the Python constants, because a
    load job reads the files.
    """
    manifest, out = _write(tmp_path, [_neighbour()])
    for entry in manifest.tables:
        schema = json.loads((out / entry["schema"]).read_text())
        assert all(f["mode"] in {"REQUIRED", "NULLABLE", "REPEATED"} for f in schema)
        for row in _rows(out, entry["name"]):
            assert export.check_row(row, schema) == [], entry["name"]
            assert set(row) == {f["name"] for f in schema}


def test_layout_names_real_columns_of_allowed_types(tmp_path):
    for spec in export.TABLES:
        fields = {f["name"]: f for f in spec.schema}
        if spec.partition_field:
            assert fields[spec.partition_field]["type"] == "TIMESTAMP"
        assert len(spec.clustering) <= 4
        for column in spec.clustering:
            assert fields[column]["mode"] != "REPEATED"


def test_hotspot_areas_are_polygons_never_points(tmp_path, seeded):
    """Hard constraint 7: a point is an address. Every area is a closed ring at the radius."""
    from vayudoot.tools.geo import haversine_km

    _, out = _write(tmp_path, [_neighbour()])
    rows = _rows(out, "hotspots") + _rows(out, "neighbour_hotspots") + _rows(out, "alerts")
    assert rows
    for row in rows:
        wkt = row["area"]
        assert wkt.startswith("POLYGON((") and "POINT" not in wkt
        pairs = re.findall(r"(-?\d+\.\d+) (-?\d+\.\d+)", wkt)
        assert len(pairs) == export.RING_VERTICES + 1
        assert pairs[0] == pairs[-1]
        radius = row.get("radius_km") or seeded.radius_km
        centre = (
            (row["centre_latitude"], row["centre_longitude"])
            if "centre_latitude" in row
            else (seeded.centre_latitude, seeded.centre_longitude)
        )
        for lon, lat in pairs:
            assert haversine_km(*centre, float(lat), float(lon)) == pytest.approx(radius, rel=0.01)


def test_no_contact_or_citizen_detail_leaks(tmp_path, seeded):
    """Nothing from a case beyond a coarsened, anonymised signal leaves the node."""
    _, out = _write(tmp_path)
    everything = "".join((out / f).read_text() for f in sorted(p.name for p in out.iterdir()))

    for leak in (CONTACT, "98100", "call me", "behind my house", "VD-CITIZEN1", "FACTS BLOCK"):
        assert leak not in everything
    assert ".invalid" not in everything  # authority emails stay out, as in the register
    for forbidden in ("reporter_contact", "note", "email", "case_ids", "facts", "brief"):
        for spec in export.TABLES:
            assert forbidden not in {f["name"] for f in spec.schema}

    citizen = [r for r in _rows(out, "signals") if r["source"] == "citizen_report"]
    assert len(citizen) == 1
    assert (citizen[0]["latitude"], citizen[0]["longitude"]) == (28.62, 77.33)
    assert citizen[0]["signal_id"].startswith("citizen-")
    assert citizen[0]["summary"] == ""
    assert citizen[0]["coordinate_decimals"] == 2


def test_alerts_export_status_and_authority_only(tmp_path, seeded):
    _, out = _write(tmp_path)
    (row,) = _rows(out, "alerts")
    assert row["status"] == "awaiting_confirmation"
    assert row["authority_name"] == "Punjab Pollution Control Board"
    assert row["sent_at"] is None


def test_a_row_that_breaks_its_schema_fails_before_anything_is_written(tmp_path, monkeypatch):
    broken = export.Table(
        "broken", "", [export._f("x", "INTEGER", "REQUIRED")], lambda s: [{"x": "one"}]
    )
    monkeypatch.setattr(export, "TABLES", [*export.TABLES, broken])
    with pytest.raises(export.ExportError, match="broken row 0"):
        _write(tmp_path)
    assert not (tmp_path / "out").exists()


def test_register_adds_a_table_to_every_export(tmp_path, monkeypatch):
    """The extension point the forecast ledger is meant to use."""
    monkeypatch.setattr(export, "TABLES", list(export.TABLES))
    schema = [*export._EXPORT_COLUMNS, export._f("risk", "STRING", "REQUIRED")]
    export.register(
        export.Table(
            "forecasts",
            "",
            schema,
            lambda s: [{**export._stamp(s), "risk": "high"}],
            partition_field="exported_at",
        )
    )
    manifest, out = _write(tmp_path)
    assert _rows(out, "forecasts")[0]["risk"] == "high"
    assert any("vayudoot.forecasts" in line for line in export.bq_commands(manifest, "p"))


def test_forecasts_export_with_their_outcome_and_a_coarse_point(tmp_path, seeded):
    """Skill can be compared across nodes in SQL only if every forecast carries its score."""
    _, out = _write(tmp_path)
    (row,) = _rows(out, "forecast_ledger")
    assert row["risk"] == "high" and row["observed_band"] == "high"
    assert row["band_error"] == 0 and row["cams_band"] == "elevated"
    assert (row["latitude"], row["longitude"]) == (30.9, 75.86)
    assert row["country"] == "IN"


def test_bq_commands_use_load_jobs_never_streaming(tmp_path, seeded):
    manifest, _ = _write(tmp_path)
    lines = export.bq_commands(manifest)
    commands = [line for line in lines if not line.startswith("#")]
    assert all(line.startswith("bq ") for line in commands)
    assert not any(" insert " in line for line in commands)
    assert any(" load --source_format=NEWLINE_DELIMITED_JSON" in line for line in commands)
    assert any("--time_partitioning_field=observed_at" in line for line in commands)
    # Empty this run, so created rather than loaded.
    assert any("mk --table" in line and "neighbour_hotspots" in line for line in commands)
    assert all(export.PROJECT_PLACEHOLDER in line for line in commands)


class _FakeBigQuery:
    """Just enough of `google.cloud.bigquery` to record what `upload` asks for."""

    def __init__(self):
        self.calls: list[tuple] = []
        lib = types.SimpleNamespace()
        lib.Dataset = lambda ref: types.SimpleNamespace(ref=ref, location=None)
        lib.Table = lambda ref, schema=None: types.SimpleNamespace(ref=ref, schema=schema)
        lib.SchemaField = types.SimpleNamespace(from_api_repr=lambda f: f["name"])
        lib.TimePartitioning = lambda type_, field: ("DAY", field)
        lib.TimePartitioningType = types.SimpleNamespace(DAY="DAY")
        lib.SourceFormat = types.SimpleNamespace(NEWLINE_DELIMITED_JSON="NDJSON")
        lib.WriteDisposition = types.SimpleNamespace(WRITE_APPEND="APPEND")
        lib.CreateDisposition = types.SimpleNamespace(CREATE_IF_NEEDED="CREATE")
        lib.LoadJobConfig = lambda **kw: kw
        self.lib = lib

    def create_dataset(self, ds, exists_ok):
        self.calls.append(("create_dataset", ds.ref))

    def create_table(self, table, exists_ok=False):
        self.calls.append(("create_table", table.ref, getattr(table, "view_query", None)))

    def delete_table(self, table, not_found_ok):
        self.calls.append(("delete_table", table.ref))

    def load_table_from_file(self, handle, table_id, job_config):
        self.calls.append(("load", table_id, job_config["write_disposition"]))
        return types.SimpleNamespace(result=lambda: None)

    def __getattr__(self, name):  # any streaming or query call is a failure
        raise AssertionError(f"upload must not call {name}")


def test_upload_uses_load_jobs_and_refuses_to_load_twice(tmp_path, seeded):
    manifest, out = _write(tmp_path)
    fake = _FakeBigQuery()

    result = export.upload(manifest, "proj", client=fake, library=fake.lib)
    assert result["skipped"] is False
    loads = [c for c in fake.calls if c[0] == "load"]
    assert {c[1] for c in loads} == {
        f"proj.vayudoot.{t['name']}" for t in manifest.tables if t["rows"]
    }
    assert all(c[2] == "APPEND" for c in loads)
    views = [c for c in fake.calls if c[0] == "create_table" and c[2]]
    assert {c[1].rsplit(".", 1)[1] for c in views} == set(export.VIEWS)
    assert all("`proj.vayudoot." in c[2] for c in views)

    again = export.upload(manifest, "proj", client=_FakeBigQuery(), library=fake.lib)
    assert again["skipped"] is True
    assert json.loads((out / "uploaded.json").read_text()) == ["proj.vayudoot"]


def test_the_script_without_a_project_prints_setup_and_commands(tmp_path, seeded, capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "export_bigquery_cli", ROOT / "scripts" / "export_bigquery.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    code = module.main(["--out", str(tmp_path / "cli"), "--no-neighbours", "--project", ""])
    printed = capsys.readouterr().out
    assert code == 0
    assert "Not uploading: no project id" in printed
    assert "console.cloud.google.com" in printed
    assert "gcloud auth application-default login" in printed
    assert "bq --project_id=YOUR_PROJECT_ID" in printed
    assert (tmp_path / "cli" / "views" / "hotspots_current.sql").exists()


# --------------------------------------------------------------------------- #
# The SQL in docs/bigquery.md and the views, checked against the schema
# --------------------------------------------------------------------------- #

_BQ_TYPES = {
    "STRING": "STRING",
    "INTEGER": "INT64",
    "FLOAT": "FLOAT64",
    "BOOLEAN": "BOOL",
    "TIMESTAMP": "TIMESTAMP",
    "GEOGRAPHY": "GEOGRAPHY",
}

#: Each view's columns are its base table's: every view selects `*` from one table.
_VIEW_BASE = {
    "latest_exports": "exports",
    "hotspots_current": "hotspots",
    "hotspots_seen": "hotspots",
    "neighbour_hotspots_current": "neighbour_hotspots",
    "neighbour_hotspots_seen": "neighbour_hotspots",
    "signals_latest": "signals",
    "alerts_current": "alerts",
    "corridors_current": "corridors",
    "forecast_ledger_latest": "forecast_ledger",
}


def _columns(schema: list[dict]) -> dict[str, str]:
    out = {}
    for f in schema:
        kind = _BQ_TYPES[f["type"]]
        out[f["name"]] = f"ARRAY<{kind}>" if f["mode"] == "REPEATED" else kind
    return out


def _sql_schema() -> dict:
    tables = {spec.name: _columns(spec.schema) for spec in export.TABLES}
    tables.update({view: tables[base] for view, base in _VIEW_BASE.items()})
    return tables


def _doc_queries() -> list[str]:
    text = (ROOT / "docs" / "bigquery.md").read_text()
    return re.findall(r"```sql\n(.*?)```", text, flags=re.DOTALL)


def _qualify(sql: str, schema: dict) -> None:
    sqlglot = pytest.importorskip("sqlglot")
    from sqlglot.optimizer.qualify import qualify

    expression = sqlglot.parse_one(sql, read="bigquery")
    qualify(expression, schema=schema, dialect="bigquery", validate_qualify_columns=True)


def test_views_cover_every_view():
    assert set(_VIEW_BASE) == set(export.VIEWS)


def test_every_view_resolves_against_the_schema():
    schema = {"proj": {"vayudoot": _sql_schema()}}
    for name in export.VIEWS:
        _qualify(export.view_sql(name, "proj"), schema)


def test_every_documented_query_resolves_against_the_schema():
    """A query in the docs that names a column the export does not write fails here."""
    queries = _doc_queries()
    assert len(queries) >= 5
    schema = {"vayudoot": _sql_schema()}
    for sql in queries:
        _qualify(sql, schema)


def test_the_schema_check_catches_a_misspelt_column():
    schema = {"vayudoot": _sql_schema()}
    with pytest.raises(Exception, match="hotspot_idd|Column"):
        _qualify("SELECT hotspot_idd FROM vayudoot.hotspots_current", schema)
