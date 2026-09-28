"""Two nodes, one machine: Punjab detects, Delhi forecasts.

    .venv/bin/python scripts/federation_demo.py
    .venv/bin/python scripts/federation_demo.py --cross-border

Runs the case the whole federation exists for. Stubble burning in Punjab arrives
in Delhi about a day and a half later; it is the best-documented pollution event
in India and it crosses a state boundary, which is exactly why no single-state
system catches it.

Two real processes and the real HTTP contract. The Punjab node is a genuine
second instance of this application with its own node identity, its own signal
store and its own `/feed`; the Delhi node subscribes to that feed by URL, the way
a real deployment would. Nothing is mocked — if the contract in
`docs/federation.md` were wrong, this would fail.

What is seeded is the Punjab node's *signals*, because the demo has to run in
September rather than in November and a satellite cannot be asked to produce a
fire on request. Everything downstream of those signals — detection, the feed,
the subscription, the forecast — is the real code path.

Needs a configured model provider for the forecast half. Without one it still
demonstrates detection and the feed, and says so.

`--cross-border` adds a third node on the other side of an international border:
a node in Pakistan's Punjab (country `PK`) with burning seeded around Kasur,
Raiwind and Sheikhupura, publishing on the same feed contract. Delhi subscribes
to both Punjabs and forecasts with both in hand. Still one forecast call, still
the real HTTP path.

Be clear about what that shows. It demonstrates that the contract works across a
border — that nothing in a feed, a node identity or the reader is Indian, and a
Delhi instance can consume a Pakistani one without a line of code changing. It
does not claim that any Pakistani agency runs a node, has been approached, or
has agreed to anything. The node is this same application started with `PK` in
its configuration, which is exactly what one would be.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

PUNJAB_PORT = 8791
DELHI_PORT = 8792
LAHORE_PORT = 8793

DELHI = (28.6139, 77.2090)

# Real places in the stubble belt, all inside Punjab, spread widely enough that
# they are separate hotspots rather than one merged blob.
BURNING_SITES = [
    ("Ludhiana district", 30.9010, 75.8573),
    ("Patiala district", 30.3398, 76.3869),
    ("Bathinda district", 30.2110, 74.9455),
]

# Real places in Pakistan's Punjab rice-wheat belt, the other half of the same
# paddy country. Raiwind is the farmland edge of Lahore district rather than the
# city centre, because stubble burns in fields, not in the old city.
CROSS_BORDER_SITES = [
    ("Kasur district", 31.1187, 74.4503),
    ("Lahore district (Raiwind)", 31.2490, 74.2153),
    ("Sheikhupura district", 31.7131, 73.9783),
]

#: How far the Delhi node reaches for upwind hotspots in the cross-border run.
#: The shipped default, 400 km, was tuned on Ludhiana (286 km from Delhi) and
#: stops short of Lahore (428 km) and Sheikhupura (464 km). The demo raises it
#: for the Delhi node only, through the same environment variable an operator
#: would use, and says so on screen rather than hiding it.
CROSS_BORDER_REACH_KM = "500"


def seeded_signals(sites: list[tuple[str, float, float]] = BURNING_SITES) -> list[dict]:
    """Stubble-burning signals as a satellite pass would have recorded them.

    Two per site, hours apart, which is what a real VIIRS overpass pair looks
    like and what makes each site a hotspot with a span rather than a single
    detection.
    """
    now = datetime.now(UTC)
    out: list[dict] = []
    for name, lat, lon in sites:
        for hours, power in ((30, 68.0), (6, 112.0)):
            seen = now - timedelta(hours=hours)
            out.append(
                {
                    "source": "satellite",
                    "signal_id": f"viirs:{lat:.5f}:{lon:.5f}:{seen.isoformat()}",
                    "latitude": lat,
                    "longitude": lon,
                    "observed_at": seen.isoformat(),
                    "pollution_type": "unclear",
                    "strength": 0.85,
                    "magnitude": min(power / 100, 1.0),
                    "summary": f"Satellite thermal detection, {power} MW radiative power",
                }
            )
        out.append(
            {
                "source": "ground_station",
                "signal_id": f"station:{name}:pm25",
                "latitude": lat + 0.01,
                "longitude": lon + 0.01,
                "observed_at": (now - timedelta(hours=3)).isoformat(),
                "pollution_type": "unclear",
                "strength": 0.9,
                "magnitude": 0.62,
                "summary": f"{name} ground station: pm25 134.0 µg/m³",
            }
        )
    return out


def write_signal_store(
    root: Path, sites: list[tuple[str, float, float]] = BURNING_SITES
) -> int:
    """Seed a node's signal store directly on disk.

    Signals live in a sibling of the case directory, so a node's whole state is
    one temporary tree and the demo cannot touch a developer's real store.
    """
    signals = root / "signals"
    signals.mkdir(parents=True, exist_ok=True)
    seeded = seeded_signals(sites)
    for index, signal in enumerate(seeded):
        (signals / f"seed-{index:03d}.json").write_text(json.dumps(signal), encoding="utf-8")
    return len(seeded)


def start_node(
    *,
    port: int,
    node_id: str,
    name: str,
    region: str,
    root: Path,
    neighbours: str = "",
    country: str = "IN",
    extra_env: dict[str, str] | None = None,
) -> subprocess.Popen:
    env = {
        **os.environ,
        "VAYUDOOT_NODE_ID": node_id,
        "VAYUDOOT_NODE_NAME": name,
        "VAYUDOOT_NODE_REGION": region,
        "VAYUDOOT_NODE_COUNTRY": country,
        "VAYUDOOT_NODE_URL": f"http://127.0.0.1:{port}",
        "VAYUDOOT_PUBLISH_FEED": "true",
        "VAYUDOOT_NEIGHBOUR_FEEDS": neighbours,
        "VAYUDOOT_CASE_DIR": str(root / "cases"),
        "VAYUDOOT_UPLOAD_DIR": str(root / "uploads"),
        # The JSON backend, whatever the developer's shell says. A demo must
        # never reach a real database.
        "DATABASE_URL": "",
        # Nothing unattended should start calling external APIs during a demo.
        "VAYUDOOT_SCAN_ENABLED": "false",
        **(extra_env or {}),
    }
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "vayudoot.api:app", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_for(port: int, seconds: float = 30.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        with contextlib.suppress(Exception):
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                return True
        time.sleep(0.4)
    return False


def rule(title: str) -> None:
    print(f"\n{'─' * 72}\n{title}\n{'─' * 72}")


def print_hotspots(spots: list[dict]) -> None:
    for spot in spots:
        people = spot.get("exposure") or {}
        exposure = (
            f"~{people['population']:,} people within {people['radius_km']:g} km "
            f"({', '.join(people['towns'])})"
            if people
            else "no town over 15,000 in reach"
        )
        print(
            f"  {spot['hotspot_id']}  {spot['pollution_type']:20} "
            f"severity {spot['severity']:8} confidence {spot['confidence']:.2f}  "
            f"corroborated {spot['corroborated']}  "
            f"citizen reports: {len(spot['case_ids'])}\n"
            f"    exposure: {exposure}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--cross-border",
        action="store_true",
        help="Add a node in Pakistan's Punjab (country PK) publishing on the same contract",
    )
    parser.add_argument(
        "--no-forecast",
        action="store_true",
        help="Stop before the one model call; detection and the feeds still run",
    )
    args = parser.parse_args()
    cross_border = args.cross_border

    with tempfile.TemporaryDirectory() as tmp:
        punjab_root = Path(tmp) / "punjab"
        lahore_root = Path(tmp) / "lahore"
        delhi_root = Path(tmp) / "delhi"

        seeded = write_signal_store(punjab_root)
        delhi_root.mkdir(parents=True, exist_ok=True)

        feeds = [f"http://127.0.0.1:{PUNJAB_PORT}/feed"]
        rule(f"Starting {'three' if cross_border else 'two'} nodes")
        print(f"Seeded the Punjab node with {seeded} signals across {len(BURNING_SITES)} sites.")
        if cross_border:
            seeded_pk = write_signal_store(lahore_root, CROSS_BORDER_SITES)
            feeds.append(f"http://127.0.0.1:{LAHORE_PORT}/feed")
            print(
                f"Seeded the Pakistan Punjab node with {seeded_pk} signals across "
                f"{len(CROSS_BORDER_SITES)} sites."
            )
        print("The Delhi node is started empty: no cases, no signals, nothing reported.")

        processes: list[subprocess.Popen] = []
        ports = [(PUNJAB_PORT, "Punjab")]
        processes.append(
            start_node(
                port=PUNJAB_PORT,
                node_id="punjab-node",
                name="Punjab State Air Quality Cell",
                region="punjab",
                root=punjab_root,
            )
        )
        if cross_border:
            ports.append((LAHORE_PORT, "Pakistan Punjab"))
            processes.append(
                start_node(
                    port=LAHORE_PORT,
                    node_id="lahore-node",
                    # Named for what it is. No Pakistani agency runs this node or
                    # has been asked to; see the module docstring.
                    name="Lahore demonstration node (Pakistan's Punjab)",
                    region="punjab-pk",
                    country="PK",
                    root=lahore_root,
                )
            )
        ports.append((DELHI_PORT, "Delhi"))
        processes.append(
            start_node(
                port=DELHI_PORT,
                node_id="delhi-node",
                name="Delhi Air Quality Cell",
                region="delhi",
                root=delhi_root,
                neighbours=",".join(feeds),
                extra_env=(
                    {"VAYUDOOT_FORECAST_UPWIND_KM": CROSS_BORDER_REACH_KM}
                    if cross_border
                    else None
                ),
            )
        )

        try:
            for port, label in ports:
                if not wait_for(port):
                    print(f"{label} node did not start on port {port}.")
                    return 1
            print(", ".join(f"{label} node on :{port}" for port, label in ports) + ".")

            rule("1. Punjab detects, from satellite and station evidence alone")
            punjab_spots = httpx.get(f"http://127.0.0.1:{PUNJAB_PORT}/hotspots", timeout=30).json()
            print(f"{len(punjab_spots)} hotspots, and not one citizen report among them:\n")
            print_hotspots(punjab_spots)

            if cross_border:
                rule("1b. Across the border, Pakistan's Punjab detects the same way")
                lahore_spots = httpx.get(
                    f"http://127.0.0.1:{LAHORE_PORT}/hotspots", timeout=30
                ).json()
                node = httpx.get(f"http://127.0.0.1:{LAHORE_PORT}/node", timeout=30).json()
                print(
                    f"Node {node['node_id']} ({node['name']}), country {node['country']}.\n"
                    f"{len(lahore_spots)} hotspots:\n"
                )
                print_hotspots(lahore_spots)

            rule("2. Delhi sees nothing of its own")
            delhi_spots = httpx.get(f"http://127.0.0.1:{DELHI_PORT}/hotspots", timeout=30).json()
            print(f"{len(delhi_spots)} hotspots in Delhi's own store.")

            title = "both Punjabs' feeds" if cross_border else "Punjab's feed"
            rule(f"3. Delhi reads {title}")
            neighbours = httpx.get(f"http://127.0.0.1:{DELHI_PORT}/neighbours", timeout=30).json()
            for entry in neighbours["neighbours"]:
                node = entry["node"] or {}
                print(
                    f"  {entry['url']}\n"
                    f"    node: {node.get('name')} ({node.get('node_id')}, "
                    f"region {node.get('region')}, country {node.get('country')})\n"
                    f"    hotspots offered: {entry['hotspot_count']}  "
                    f"error: {entry['error'] or 'none'}"
                )

            source_port = LAHORE_PORT if cross_border else PUNJAB_PORT
            feed = httpx.get(f"http://127.0.0.1:{source_port}/feed", timeout=30).json()
            raw = json.dumps(feed)
            print("\n  The feed is an allowlist:")
            print(f"    carries case ids: {'case_ids' in raw}")
            carries_signals = '"signals"' in raw
            print(f"    carries signals:  {carries_signals}")
            print(f"    carries exposure: {'exposure' in raw}")
            print(f"    feed version:     {feed['feed_version']}")

            geojson = httpx.get(f"http://127.0.0.1:{source_port}/feed.geojson", timeout=30)
            collection = geojson.json()
            shapes = sorted({f["geometry"]["type"] for f in collection["features"]})
            print("\n  And the same feed as GeoJSON, for any GIS:")
            print(f"    content type:     {geojson.headers.get('content-type')}")
            print(
                f"    features:         {len(collection['features'])} "
                f"({', '.join(shapes) or 'none'}; never a point)"
            )
            print(f"    node country:     {collection['node']['country']}")

            if args.no_forecast:
                rule("4. Forecast skipped (--no-forecast)")
                return 0

            whose = "both Punjabs'" if cross_border else "Punjab's"
            rule(f"4. Delhi forecasts, with {whose} detections in hand")
            if cross_border:
                print(
                    f"Delhi's upwind reach is set to {CROSS_BORDER_REACH_KM} km for this run "
                    "(VAYUDOOT_FORECAST_UPWIND_KM).\nThe shipped 400 km was tuned on Ludhiana "
                    "(286 km) and stops short of Lahore (428 km).\n"
                )
            print("Calling the model. This is the only step that needs a provider.\n")
            try:
                response = httpx.get(
                    f"http://127.0.0.1:{DELHI_PORT}/forecast",
                    params={"lat": DELHI[0], "lon": DELHI[1], "place": "Delhi"},
                    timeout=180,
                )
                if response.status_code != 200:
                    print(f"  Forecast unavailable ({response.status_code}): {response.text[:200]}")
                    print("  Detection and the feed above are unaffected.")
                    return 0

                outlook = response.json()
                print(f"  risk: {outlook['risk']}   confidence: {outlook['confidence']}")
                print("\n  drivers:")
                for driver in outlook["drivers"]:
                    print(f"    - {driver}")
                print("\n  basis:")
                for item in outlook["basis"]:
                    print(f"    - {item}")
                print(f"\n  {outlook['disclaimer']}")
            except Exception as exc:  # noqa: BLE001 - a demo reports, it does not raise
                print(f"  Forecast could not be produced: {exc}")
                print("  Detection and the feed above are unaffected.")

            rule("What this showed")
            if cross_border:
                print(
                    "Two nodes in two countries raised hotspots from instruments alone.\n"
                    "Delhi read both over the same feed contract and forecast with them.\n"
                    "Nothing in the contract is Indian: the Pakistani node is this same\n"
                    "application with PK in its configuration. That demonstrates the\n"
                    "contract works across a border. It does not mean any Pakistani agency\n"
                    "runs a node; none has been asked.\n"
                )
            else:
                print(
                    "Punjab raised hotspots from instruments alone, with no citizen involved.\n"
                    "Delhi, which has detected nothing itself, read them over the real feed\n"
                    "and forecast with them. No shared model, no central authority, no\n"
                    "agreement between the two beyond a URL and a schema.\n"
                )
            print(
                "If the outlook above says the air is arriving from somewhere other than\n"
                "Punjab, that is the system working rather than failing. The link between\n"
                "Punjab's fires and Delhi's air is seasonal: it runs on the north-westerly\n"
                "wind of October and November, and for much of the rest of the year the\n"
                "wind is southerly and the smoke goes elsewhere. The model is given the\n"
                "hotspots and the forecast wind together and asked to check one against\n"
                "the other before claiming a connection — so out of season it reports the\n"
                "hotspots as present and not contributing, which is the true answer and\n"
                "the harder one to get."
            )
            return 0
        finally:
            for process in processes:
                process.terminate()
            for process in processes:
                with contextlib.suppress(Exception):
                    process.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
