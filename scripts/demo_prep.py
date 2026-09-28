"""Warm a running node before a demo recording, so nothing on camera waits on Gemini.

    .venv/bin/python scripts/demo_prep.py --dry-run
    .venv/bin/python scripts/demo_prep.py
    .venv/bin/python scripts/demo_prep.py --url http://127.0.0.1:8000 --only imagery alert

The Gemini free tier answers 503 "high demand" for long stretches, and a failed
call on camera is the biggest risk in the recording. Every model call the demo
needs can be made beforehand, because the server keeps each answer:

* the satellite image reading is cached on disk per hotspot and image date;
* an alert draft is kept `awaiting_confirmation`, and asking again returns it;
* forecasts are cached in the server's memory for
  `VAYUDOOT_FORECAST_CACHE_MINUTES` (30 by default — raise it, see below).

So this script seeds the demo hotspots if they are missing, reads the demo
hotspot's satellite image, drafts its alert, and warms the Delhi forecast and
the corridor forecasts, retrying 503s with backoff. Then it prints what is warm
and, for anything cold, the exact command to try again.

**It never spends twice.** Before any paid call it asks the free read that
would show the answer already exists (`GET /hotspots/{id}/imagery`,
`GET /alerts?hotspot_id=`), and asks again before every retry, in case a call
that timed out on this side finished on the server's. It never passes
`reread` or `redraft`. A forecast is simply asked for: once the server has one
cached, asking again is free.

**It never confirms or files anything.** Confirming the alert is the human's
action on camera — hard constraint 2 — and it is the moment the demo exists to
show. The only POSTs this script can make are the imagery read and the alert
draft, and `Node.post` refuses every other path, `/confirm` included.

Seeding writes signal files into the node's store directory, because satellite
and station signals have no HTTP write route (only the scan makes them). That
works for a local node on the JSON backend (`DATABASE_URL=` empty), which is
what `docs/pitch/video-script.md` records against. What it seeds is
demonstration data, the same as `federation_demo.py`'s: the Punjab stubble
sites from that script, reused rather than copied, and one citizen-sensor-only
area in Delhi that shows what an uncorroborated hotspot looks like.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from federation_demo import BURNING_SITES, DELHI, seeded_signals

DEFAULT_URL = "http://127.0.0.1:8000"
RECOMMENDED_CACHE_MINUTES = 240

#: The demo hotspot: the first stubble site, Ludhiana.
DEMO_SITE = BURNING_SITES[0]

#: The citizen-only area. A broad residential district rather than any one
#: facility, because even a seeded hotspot drawn on a named site is an
#: accusation on screen (hard constraint 7).
CITIZEN_SITE = ("Rohini, North West Delhi", 28.7041, 77.1025)

#: How near a hotspot's centre must be to a seed site to count as that site.
SITE_MATCH_KM = 10.0

#: The only POSTs this script may make. Both are cached by the server and
#: neither sends anything anywhere.
ALLOWED_POSTS = (
    re.compile(r"^/hotspots/[A-Za-z0-9-]+/imagery$"),
    re.compile(r"^/hotspots/[A-Za-z0-9-]+/alert$"),
)
#: Query parameters that would spend a second model call on purpose.
FORBIDDEN_PARAMS = frozenset({"reread", "redraft"})

STEPS = ("seed", "imagery", "alert", "forecast", "corridors")


class Refused(Exception):
    """A request this script must never make."""


class Node:
    """HTTP to one node, with the guard that keeps this script from sending anything."""

    def __init__(self, url: str, client: httpx.Client | None = None, timeout: float = 240.0):
        self.url = url.rstrip("/")
        self.client = client or httpx.Client(base_url=self.url, timeout=timeout)

    def get(self, path: str, **params) -> httpx.Response:
        return self.client.get(path, params=params or None)

    def post(self, path: str, **params) -> httpx.Response:
        if not any(pattern.match(path) for pattern in ALLOWED_POSTS):
            raise Refused(f"demo_prep never POSTs to {path}: confirming and filing are human")
        if FORBIDDEN_PARAMS & set(params):
            raise Refused(f"demo_prep never passes {sorted(FORBIDDEN_PARAMS & set(params))}")
        return self.client.post(path, params=params or None)


@dataclass
class Item:
    """One line of the checklist."""

    name: str
    warm: bool
    detail: str
    next_command: str = ""


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(body, dict) and "detail" in body:
        return str(body["detail"])[:200]
    return json.dumps(body)[:200]


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from vayudoot.tools.geo import haversine_km

    return haversine_km(lat1, lon1, lat2, lon2)


def _near(spots: list[dict], lat: float, lon: float, corroborated: bool) -> dict | None:
    matches = [
        s
        for s in spots
        if bool(s.get("corroborated")) is corroborated
        and _distance_km(s["centre_latitude"], s["centre_longitude"], lat, lon) <= SITE_MATCH_KM
    ]
    return max(matches, key=lambda s: s.get("confidence", 0), default=None)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def citizen_signals(site=CITIZEN_SITE, now: datetime | None = None) -> list[dict]:
    """Low-cost sensor readings from two citizens' devices, and nothing else.

    Built as `POST /sensors/readings` would build them — same source, same
    reliability, magnitude from the same exceedance arithmetic — but written to
    disk, so seeding does not use up the report rate limit the on-camera report
    needs. Citizen sensors are not independent evidence, so the hotspot they
    make is uncorroborated and its confidence is capped: the point of seeding it.
    """
    from vayudoot.config import settings
    from vayudoot.hotspots import exceedance_strength
    from vayudoot.schemas import Signal, SignalSource

    now = now or datetime.now(UTC)
    _, lat, lon = site
    readings = (
        ("demo-sensor-a", 0.000, 0.000, 5, 168.0),
        ("demo-sensor-b", 0.004, 0.003, 2, 142.0),
    )
    out = []
    for sensor, dlat, dlon, hours, value in readings:
        seen = now - timedelta(hours=hours)
        signal = Signal(
            source=SignalSource.CITIZEN_SENSOR,
            signal_id=f"sensor:{sensor}:pm25:{seen.isoformat()}",
            latitude=lat + dlat,
            longitude=lon + dlon,
            observed_at=seen,
            strength=settings.vayudoot_citizen_sensor_reliability,
            magnitude=exceedance_strength("pm25", value, "ug/m3") or 0.5,
            summary=f"Citizen sensor {sensor}: pm25 {value} ug/m3",
        )
        out.append(signal.model_dump(mode="json"))
    return out


def _with_retry(
    call: Callable[[], httpx.Response],
    *,
    attempts: int,
    backoff: float,
    sleep: Callable[[float], None],
    landed: Callable[[], object] | None = None,
) -> tuple[httpx.Response | None, object, str]:
    """Make a call, retrying a 503 or a lost answer with backoff.

    Returns `(response, found, note)`. `found` is set when `landed` — a free
    read — shows the answer arrived after all; then no further call is made.
    Only 503 and transport failures are retried: anything else is an answer.
    """
    note = ""
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            wait = backoff * 2 ** (attempt - 2)
            print(f"    503 or no answer; waiting {wait:.0f}s before attempt {attempt}/{attempts}")
            sleep(wait)
            if landed is not None and (found := landed()) is not None:
                return None, found, "the earlier call finished on the server"
        try:
            response = call()
        except httpx.TransportError as exc:
            note = f"no answer from the node ({type(exc).__name__})"
            continue
        if response.status_code == 503:
            note = _detail(response)
            continue
        return response, None, ""
    return None, None, f"still unavailable after {attempts} attempts: {note}"


class Prep:
    def __init__(
        self,
        node: Node,
        *,
        data_dir: Path | None,
        dry_run: bool = False,
        steps: tuple[str, ...] = STEPS,
        corridors: list[str] | None = None,
        hotspot_id: str = "",
        attempts: int = 4,
        backoff: float = 20.0,
        corridor_pause: float = 45.0,
        cache_minutes: int = 30,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.node = node
        self.data_dir = data_dir
        self.dry_run = dry_run
        self.steps = steps
        self.corridors = corridors
        self.hotspot_id = hotspot_id
        self.attempts = attempts
        self.backoff = backoff
        self.corridor_pause = corridor_pause
        self.cache_minutes = cache_minutes
        self.sleep = sleep
        self.items: list[Item] = []

    # -- helpers ------------------------------------------------------------ #

    def _add(self, name: str, warm: bool, detail: str, next_command: str = "") -> None:
        self.items.append(Item(name, warm, detail, next_command))
        print(f"  [{'warm' if warm else 'COLD'}] {name}: {detail}")

    def _rerun(self, *steps: str) -> str:
        return (
            f".venv/bin/python scripts/demo_prep.py --url {self.node.url} --only {' '.join(steps)}"
        )

    def _retry(self, call, landed=None):
        return _with_retry(
            call, attempts=self.attempts, backoff=self.backoff, sleep=self.sleep, landed=landed
        )

    def _hotspots(self) -> list[dict]:
        response = self.node.get("/hotspots")
        response.raise_for_status()
        return response.json()

    # -- steps -------------------------------------------------------------- #

    def check_server(self) -> bool:
        try:
            response = self.node.get("/health")
        except httpx.TransportError as exc:
            self._add(
                "server",
                False,
                f"not reachable at {self.node.url} ({type(exc).__name__})",
                "start it: see docs/pitch/video-script.md, 'Before you record'",
            )
            return False
        health = response.json()
        self._add(
            "server",
            True,
            f"{health.get('model_provider')} / {health.get('model_id')}, "
            f"{health.get('reports_remaining_today', 'unmetered')} reports left today",
        )
        if health.get("live_filing"):
            self._add(
                "live filing off",
                False,
                "live_filing is true: the on-camera confirm will refuse rather than write "
                "to the sandbox outbox",
                "restart the server with VAYUDOOT_LIVE_FILING=false",
            )
        else:
            self._add("live filing off", True, "confirming writes to the sandbox outbox only")
        return True

    def seed(self) -> None:
        spots = self._hotspots()
        wanted = [(site, True) for site in BURNING_SITES] + [(CITIZEN_SITE, False)]
        missing = [(s, c) for s, c in wanted if _near(spots, s[1], s[2], c) is None]
        if not missing:
            self._add("demo hotspots", True, f"all {len(wanted)} present ({len(spots)} on the map)")
            return
        names = ", ".join(site[0] for site, _ in missing)
        if self.data_dir is None:
            self._add(
                "demo hotspots",
                False,
                f"missing: {names}; no --data-dir to seed into",
                self._rerun("seed") + " --data-dir /tmp/vd-demo",
            )
            return
        signals_dir = self.data_dir / "signals"
        if self.dry_run:
            self._add("demo hotspots", False, f"missing: {names}; would seed into {signals_dir}")
            return

        signals_dir.mkdir(parents=True, exist_ok=True)
        written = 0
        for site, corroborated in missing:
            batch = seeded_signals([site]) if corroborated else citizen_signals(site)
            for index, signal in enumerate(batch):
                # Named by site and position, so seeding again replaces rather
                # than adds: a second copy would read as a second satellite pass.
                path = signals_dir / f"demo-{_slug(site[0])}-{index}.json"
                path.write_text(json.dumps(signal), encoding="utf-8")
                written += 1

        spots = self._hotspots()
        still = [s[0] for s, c in missing if _near(spots, s[1], s[2], c) is None]
        if still:
            self._add(
                "demo hotspots",
                False,
                f"wrote {written} signals to {signals_dir} but the node does not show "
                f"{', '.join(still)}: is it reading that store (DATABASE_URL empty, "
                "VAYUDOOT_CASE_DIR beside it)?",
                "restart the server with DATABASE_URL= and "
                f"VAYUDOOT_CASE_DIR={self.data_dir / 'cases'}",
            )
        else:
            self._add("demo hotspots", True, f"seeded {names} ({written} signals)")

    def demo_hotspot(self) -> dict | None:
        spots = self._hotspots()
        if self.hotspot_id:
            found = next((s for s in spots if s["hotspot_id"] == self.hotspot_id), None)
        else:
            found = _near(spots, DEMO_SITE[1], DEMO_SITE[2], corroborated=True)
        if found is None:
            wanted = self.hotspot_id or f"a corroborated hotspot near {DEMO_SITE[0]}"
            self._add("demo hotspot", False, f"{wanted} is not on the map", self._rerun("seed"))
            return None
        self._add(
            "demo hotspot",
            True,
            f"{found['hotspot_id']} near {DEMO_SITE[0] if not self.hotspot_id else 'the given id'}"
            f", confidence {found['confidence']:.2f}, corroborated {found['corroborated']}",
        )
        return found

    def imagery(self, hotspot_id: str) -> None:
        path = f"/hotspots/{hotspot_id}/imagery"

        def cached():
            response = self.node.get(path)
            return response.json() if response.status_code == 200 else None

        if (reading := cached()) is not None:
            self._add("satellite imagery", True, self._describe_reading(reading, "cached"))
            return
        if self.dry_run:
            self._add(
                "satellite imagery", False, "no cached reading; would read it (1 primary call)"
            )
            return
        print(f"  reading the satellite image for {hotspot_id} (one primary-tier call)...")
        response, found, note = self._retry(lambda: self.node.post(path), landed=cached)
        if found is not None:
            self._add("satellite imagery", True, self._describe_reading(found, note))
        elif response is not None and response.status_code == 200:
            self._add(
                "satellite imagery", True, self._describe_reading(response.json(), "read now")
            )
        else:
            reason = note or f"{response.status_code}: {_detail(response)}"
            self._add("satellite imagery", False, reason, self._rerun("imagery"))

    @staticmethod
    def _describe_reading(reading: dict, how: str) -> str:
        return (
            f"{how}; image {reading.get('image_date')}, plume visible "
            f"{reading.get('plume_visible')}, cloud {reading.get('cloud_obscured')}"
        )

    def alert(self, hotspot_id: str) -> None:
        def pending():
            response = self.node.get("/alerts", hotspot_id=hotspot_id)
            if response.status_code != 200:
                return None
            return next(
                (a for a in response.json() if a.get("status") == "awaiting_confirmation"), None
            )

        if (found := pending()) is not None:
            self._add("alert draft", True, self._describe_alert(found, "already drafted"))
            return
        if self.dry_run:
            self._add("alert draft", False, "none awaiting confirmation; would draft (1 fast call)")
            return
        print(f"  drafting the alert for {hotspot_id} (one fast-tier call)...")
        path = f"/hotspots/{hotspot_id}/alert"
        response, found, note = self._retry(lambda: self.node.post(path), landed=pending)
        if found is not None:
            self._add("alert draft", True, self._describe_alert(found, note))
        elif response is not None and response.status_code == 200:
            self._add("alert draft", True, self._describe_alert(response.json(), "drafted now"))
        else:
            reason = note or f"{response.status_code}: {_detail(response)}"
            self._add("alert draft", False, reason, self._rerun("alert"))

    @staticmethod
    def _describe_alert(alert: dict, how: str) -> str:
        authority = (alert.get("jurisdiction") or {}).get("authority_name", "?")
        cited = "cites" if alert.get("imagery") else "does not cite"
        return (
            f"{how}; {alert.get('alert_id')} to {authority}, awaiting your confirmation on "
            f"camera; {cited} the satellite reading"
        )

    def forecast(self) -> None:
        if self.dry_run:
            self._add(
                "Delhi forecast",
                False,
                "not asked in a dry run (a cached one is free, a cold one is a model call)",
                self._rerun("forecast"),
            )
            return
        print("  forecasting Delhi (fast tier, free if already cached)...")
        lat, lon = DELHI
        response, _, note = self._retry(
            lambda: self.node.get("/forecast", lat=lat, lon=lon, place="Delhi")
        )
        if response is not None and response.status_code == 200:
            body = response.json()
            self._add(
                "Delhi forecast",
                True,
                f"risk {body.get('risk')}, confidence {body.get('confidence')}; "
                f"{self._cached_until()}",
            )
        else:
            reason = note or f"{response.status_code}: {_detail(response)}"
            self._add("Delhi forecast", False, reason, self._rerun("forecast"))

    def corridor_forecasts(self) -> None:
        listed = self.node.get("/corridors").json()
        waypoints = {c["corridor_id"]: len(c.get("waypoints", [])) for c in listed}
        chosen = self.corridors or list(waypoints)
        if self.dry_run:
            self._add(
                "corridor forecasts",
                False,
                f"not asked in a dry run: {', '.join(chosen)}",
                self._rerun("corridors"),
            )
            return
        for index, corridor_id in enumerate(chosen):
            name = f"corridor {corridor_id}"
            if corridor_id not in waypoints:
                self._add(name, False, "no such corridor on this node")
                continue
            print(f"  forecasting {corridor_id} ({waypoints[corridor_id]} waypoints, fast tier)...")
            started = time.monotonic()
            response, _, note = self._retry(
                lambda cid=corridor_id: self.node.get(f"/corridors/{cid}/forecast")
            )
            spent = time.monotonic() - started > 2.0
            again = f"{self._rerun('corridors')} --corridor {corridor_id}"
            if response is None or response.status_code != 200:
                reason = note or f"{response.status_code}: {_detail(response)}"
                self._add(name, False, reason, again)
            else:
                body = response.json()
                got, want = len(body.get("waypoint_forecasts", [])), waypoints[corridor_id]
                if got < want:
                    # The server does not cache a corridor with a waypoint missing,
                    # so this one would be recomputed on camera.
                    self._add(name, False, f"{got} of {want} waypoints answered; not cached", again)
                else:
                    self._add(name, True, f"risk {body.get('risk')}; {self._cached_until()}")
            # Pace the fast tier (15 requests a minute on flash-lite): a corridor
            # is two calls per waypoint, all at once. A cache hit spent nothing.
            if spent and index < len(chosen) - 1:
                self.sleep(self.corridor_pause)

    def _cached_until(self) -> str:
        until = datetime.now().astimezone() + timedelta(minutes=self.cache_minutes)
        return (
            f"cached until about {until:%H:%M} if the server runs with a "
            f"{self.cache_minutes}-min cache"
        )

    # -- run ---------------------------------------------------------------- #

    def run(self) -> int:
        mode = " (dry run: no writes, no model calls)" if self.dry_run else ""
        print(f"Preparing {self.node.url}{mode}\n")
        if not self.check_server():
            return self.report()
        if "seed" in self.steps:
            self.seed()
        if {"imagery", "alert"} & set(self.steps):
            spot = self.demo_hotspot()
            if spot is not None:
                # Imagery first, so the alert drafted after it cites the reading.
                if "imagery" in self.steps:
                    self.imagery(spot["hotspot_id"])
                if "alert" in self.steps:
                    self.alert(spot["hotspot_id"])
        # Forecasts last: they live in memory and the clock starts when they land.
        if "forecast" in self.steps:
            self.forecast()
        if "corridors" in self.steps:
            self.corridor_forecasts()
        return self.report()

    def report(self) -> int:
        print("\n" + "─" * 72 + "\nChecklist\n" + "─" * 72)
        for item in self.items:
            print(f"  [{'x' if item.warm else ' '}] {item.name}: {item.detail}")
            if not item.warm and item.next_command:
                print(f"        next: {item.next_command}")
        print(
            f"\nForecasts are held in the server's memory for VAYUDOOT_FORECAST_CACHE_MINUTES "
            f"(assumed {self.cache_minutes}). For a recording, start the server with "
            f"VAYUDOOT_FORECAST_CACHE_MINUTES={RECOMMENDED_CACHE_MINUTES} before running this, "
            "because a restart empties that cache.\n"
            "Confirming the alert is yours to do on camera. This script never confirms or "
            "files anything."
        )
        cold = [item for item in self.items if not item.warm]
        print(f"\n{'All warm.' if not cold else f'{len(cold)} item(s) cold.'}")
        return 0 if not cold else 1


def _default_data_dir() -> Path:
    from vayudoot.config import settings

    return settings.vayudoot_case_dir.parent


def main(
    argv: list[str] | None = None, client: httpx.Client | None = None, sleep=time.sleep
) -> int:
    from vayudoot.config import settings

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=DEFAULT_URL, help=f"Node URL (default {DEFAULT_URL})")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="The node's store root, the parent of its VAYUDOOT_CASE_DIR, where signals "
        "are seeded (default: from this shell's VAYUDOOT_CASE_DIR, else ./data)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report only: no writes, no model calls"
    )
    parser.add_argument("--only", nargs="+", choices=STEPS, default=list(STEPS))
    parser.add_argument("--corridor", action="append", help="Warm only this corridor (repeatable)")
    parser.add_argument("--hotspot", default="", help="Use this hotspot id instead of Ludhiana's")
    parser.add_argument("--attempts", type=int, default=4, help="Tries per call on 503 (default 4)")
    parser.add_argument("--backoff", type=float, default=20.0, help="First wait in seconds")
    parser.add_argument(
        "--corridor-pause", type=float, default=45.0, help="Seconds between corridors that spent"
    )
    parser.add_argument(
        "--cache-minutes",
        type=int,
        default=settings.vayudoot_forecast_cache_minutes,
        help="The server's forecast cache, for the checklist (default: this shell's setting)",
    )
    args = parser.parse_args(argv)

    node = Node(args.url, client=client)
    prep = Prep(
        node,
        data_dir=args.data_dir or _default_data_dir(),
        dry_run=args.dry_run,
        steps=tuple(args.only),
        corridors=args.corridor,
        hotspot_id=args.hotspot,
        attempts=max(args.attempts, 1),
        backoff=args.backoff,
        corridor_pause=args.corridor_pause,
        cache_minutes=args.cache_minutes,
        sleep=sleep,
    )
    return prep.run()


if __name__ == "__main__":
    raise SystemExit(main())
