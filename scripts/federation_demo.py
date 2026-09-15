"""Two nodes, one machine: Punjab detects, Delhi forecasts.

    .venv/bin/python scripts/federation_demo.py

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
"""

from __future__ import annotations

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

DELHI = (28.6139, 77.2090)

# Real places in the stubble belt, all inside Punjab, spread widely enough that
# they are separate hotspots rather than one merged blob.
BURNING_SITES = [
    ("Ludhiana district", 30.9010, 75.8573),
    ("Patiala district", 30.3398, 76.3869),
    ("Bathinda district", 30.2110, 74.9455),
]


def seeded_signals() -> list[dict]:
    """Stubble-burning signals as a satellite pass would have recorded them.

    Two per site, hours apart, which is what a real VIIRS overpass pair looks
    like and what makes each site a hotspot with a span rather than a single
    detection.
    """
    now = datetime.now(UTC)
    out: list[dict] = []
    for name, lat, lon in BURNING_SITES:
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
                "summary": f"{name} CPCB station: pm25 134.0 µg/m³",
            }
        )
    return out


def write_signal_store(root: Path) -> int:
    """Seed a node's signal store directly on disk.

    Signals live in a sibling of the case directory, so a node's whole state is
    one temporary tree and the demo cannot touch a developer's real store.
    """
    signals = root / "signals"
    signals.mkdir(parents=True, exist_ok=True)
    for index, signal in enumerate(seeded_signals()):
        (signals / f"seed-{index:03d}.json").write_text(json.dumps(signal), encoding="utf-8")
    return len(seeded_signals())


def start_node(
    *, port: int, node_id: str, name: str, region: str, root: Path, neighbours: str = ""
) -> subprocess.Popen:
    env = {
        **os.environ,
        "VAYUDOOT_NODE_ID": node_id,
        "VAYUDOOT_NODE_NAME": name,
        "VAYUDOOT_NODE_REGION": region,
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


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        punjab_root = Path(tmp) / "punjab"
        delhi_root = Path(tmp) / "delhi"

        seeded = write_signal_store(punjab_root)
        delhi_root.mkdir(parents=True, exist_ok=True)

        rule("Starting two nodes")
        print(f"Seeded the Punjab node with {seeded} signals across {len(BURNING_SITES)} sites.")
        print("The Delhi node is started empty: no cases, no signals, nothing reported.")

        punjab = start_node(
            port=PUNJAB_PORT,
            node_id="punjab-node",
            name="Punjab State Air Quality Cell",
            region="punjab",
            root=punjab_root,
        )
        delhi = start_node(
            port=DELHI_PORT,
            node_id="delhi-node",
            name="Delhi Air Quality Cell",
            region="delhi",
            root=delhi_root,
            neighbours=f"http://127.0.0.1:{PUNJAB_PORT}/feed",
        )

        try:
            for port, label in ((PUNJAB_PORT, "Punjab"), (DELHI_PORT, "Delhi")):
                if not wait_for(port):
                    print(f"{label} node did not start on port {port}.")
                    return 1
            print(f"Punjab node on :{PUNJAB_PORT}, Delhi node on :{DELHI_PORT}.")

            rule("1. Punjab detects, from satellite and station evidence alone")
            punjab_spots = httpx.get(f"http://127.0.0.1:{PUNJAB_PORT}/hotspots", timeout=30).json()
            print(f"{len(punjab_spots)} hotspots, and not one citizen report among them:\n")
            for spot in punjab_spots:
                print(
                    f"  {spot['hotspot_id']}  {spot['pollution_type']:20} "
                    f"severity {spot['severity']:8} confidence {spot['confidence']:.2f}  "
                    f"corroborated {spot['corroborated']}  "
                    f"citizen reports: {len(spot['case_ids'])}"
                )

            rule("2. Delhi sees nothing of its own")
            delhi_spots = httpx.get(f"http://127.0.0.1:{DELHI_PORT}/hotspots", timeout=30).json()
            print(f"{len(delhi_spots)} hotspots in Delhi's own store.")

            rule("3. Delhi reads Punjab's feed")
            neighbours = httpx.get(f"http://127.0.0.1:{DELHI_PORT}/neighbours", timeout=30).json()
            for entry in neighbours["neighbours"]:
                node = entry["node"] or {}
                print(
                    f"  {entry['url']}\n"
                    f"    node: {node.get('name')} ({node.get('node_id')}, "
                    f"region {node.get('region')})\n"
                    f"    hotspots offered: {entry['hotspot_count']}  "
                    f"error: {entry['error'] or 'none'}"
                )

            feed = httpx.get(f"http://127.0.0.1:{PUNJAB_PORT}/feed", timeout=30).json()
            raw = json.dumps(feed)
            print("\n  The feed is an allowlist:")
            print(f"    carries case ids: {'case_ids' in raw}")
            carries_signals = '"signals"' in raw
            print(f"    carries signals:  {carries_signals}")
            print(f"    feed version:     {feed['feed_version']}")

            rule("4. Delhi forecasts, with Punjab's detections in hand")
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
            for process in (punjab, delhi):
                process.terminate()
            for process in (punjab, delhi):
                with contextlib.suppress(Exception):
                    process.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
