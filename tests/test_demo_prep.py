"""scripts/demo_prep.py against a fake node: what it asks, what it spends, what it never does.

The fake node answers over `httpx.MockTransport`, so no server, network or
model is involved. Its `/hotspots` is the real detector run over the real JSON
signal store (redirected into `tmp_path` by the conftest), which is what makes
the seeding tests honest: a seeded site counts only if `hotspots.current()`
really turns it into a hotspot of the right kind.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import httpx
import pytest

from vayudoot import hotspots

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("demo_prep", ROOT / "scripts" / "demo_prep.py")
    module = importlib.util.module_from_spec(spec)
    # Registered before running, because a dataclass looks its module up by name.
    sys.modules["demo_prep"] = module
    spec.loader.exec_module(module)
    return module


demo_prep = _load()

CORRIDORS = [
    {"corridor_id": "ncr", "name": "NCR", "waypoints": [[28.6, 77.2], [28.4, 77.3]]},
    {"corridor_id": "mumbai-pune", "name": "M-P", "waypoints": [[19.0, 72.8], [18.5, 73.8]]},
]


class FakeNode:
    """A node that records every request and answers from scripted queues.

    `imagery_posts` and `alert_posts` are lists of status codes to answer POSTs
    with, in order; 200 stores the result so the free GET finds it afterwards.
    `lands_anyway` makes a POST store its result and then answer 503, as a
    request that timed out on the client after the server finished would.
    """

    def __init__(self, imagery_posts=(200,), alert_posts=(200,), forecast=(200,), corridor=None):
        self.requests: list[tuple[str, str, dict]] = []
        self.imagery: dict[str, dict] = {}
        self.alerts: list[dict] = []
        self.imagery_posts = list(imagery_posts)
        self.alert_posts = list(alert_posts)
        self.forecast = list(forecast)
        self.corridor = corridor or {}
        self.lands_anyway = False
        self.busy_detail = "model busy"

    def calls(self, method: str, prefix: str = "") -> list[str]:
        return [p for m, p, _ in self.requests if m == method and p.startswith(prefix)]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, params = request.url.path, dict(request.url.params)
        self.requests.append((request.method, path, params))
        if request.method == "GET":
            return self._get(path, params)
        return self._post(path)

    def _get(self, path, params):
        if path == "/health":
            return httpx.Response(
                200,
                json={"model_provider": "gemini", "model_id": "flash", "live_filing": False},
            )
        if path == "/hotspots":
            spots = [h.model_dump(mode="json") for h in hotspots.current()]
            return httpx.Response(200, json=spots)
        if path.endswith("/imagery"):
            hotspot_id = path.split("/")[2]
            if hotspot_id in self.imagery:
                return httpx.Response(200, json=self.imagery[hotspot_id])
            return httpx.Response(404, json={"detail": "No satellite image has been read"})
        if path == "/alerts":
            found = [a for a in self.alerts if a["hotspot_id"] == params.get("hotspot_id")]
            return httpx.Response(200, json=found)
        if path == "/forecast":
            status = self.forecast.pop(0) if self.forecast else 200
            return httpx.Response(status, json={"risk": "high", "confidence": 0.6})
        if path == "/corridors":
            return httpx.Response(200, json=CORRIDORS)
        if path.startswith("/corridors/"):
            corridor_id = path.split("/")[2]
            answered = self.corridor.get(corridor_id, 2)
            body = {"risk": "elevated", "waypoint_forecasts": [{}] * answered}
            return httpx.Response(200, json=body)
        return httpx.Response(404)

    def _post(self, path):
        hotspot_id = path.split("/")[2]
        if path.endswith("/imagery"):
            status = self.imagery_posts.pop(0) if self.imagery_posts else 503
            if status == 200 or self.lands_anyway:
                self.imagery[hotspot_id] = {
                    "image_date": "2026-09-28",
                    "plume_visible": True,
                    "cloud_obscured": False,
                }
            if status == 200:
                return httpx.Response(200, json=self.imagery[hotspot_id])
            return httpx.Response(status, json={"detail": self.busy_detail})
        if path.endswith("/alert"):
            status = self.alert_posts.pop(0) if self.alert_posts else 503
            if status == 200:
                alert = {
                    "alert_id": "alert-1",
                    "hotspot_id": hotspot_id,
                    "status": "awaiting_confirmation",
                    "jurisdiction": {"authority_name": "Punjab Pollution Control Board"},
                    "imagery": self.imagery.get(hotspot_id),
                }
                self.alerts.append(alert)
                return httpx.Response(200, json=alert)
            return httpx.Response(status, json={"detail": "refused or busy"})
        return httpx.Response(404)


def _prep(node: FakeNode, data_dir: Path, **kwargs):
    client = httpx.Client(transport=httpx.MockTransport(node), base_url="http://node.test")
    waits: list[float] = []
    kwargs.setdefault("corridor_pause", 0.0)
    prep = demo_prep.Prep(
        demo_prep.Node("http://node.test", client=client),
        data_dir=data_dir,
        backoff=1.0,
        sleep=waits.append,
        **kwargs,
    )
    return prep, waits


def _seed_all(data_dir: Path) -> None:
    prep, _ = _prep(FakeNode(), data_dir, steps=("seed",))
    prep.run()


def _demo_hotspot_id() -> str:
    lat, lon = demo_prep.DEMO_SITE[1], demo_prep.DEMO_SITE[2]
    spots = [h.model_dump(mode="json") for h in hotspots.current()]
    return demo_prep._near(spots, lat, lon, corroborated=True)["hotspot_id"]


def test_a_dry_run_posts_nothing_forecasts_nothing_and_writes_nothing(isolated_storage):
    node = FakeNode()
    prep, _ = _prep(node, isolated_storage, dry_run=True)

    code = prep.run()

    assert code == 1  # nothing is warm yet
    assert node.calls("POST") == []
    assert node.calls("GET", "/forecast") == []
    assert [p for p in node.calls("GET", "/corridors/") if p.endswith("/forecast")] == []
    assert not (isolated_storage / "signals").exists() or not any(
        (isolated_storage / "signals").iterdir()
    )


def test_seeding_makes_corroborated_stubble_hotspots_and_one_citizen_only_area(isolated_storage):
    """The demo needs both kinds on the map: one an instrument backs, one only the public does."""
    node = FakeNode()
    prep, _ = _prep(node, isolated_storage, steps=("seed",))

    prep.run()

    spots = [h.model_dump(mode="json") for h in hotspots.current()]
    for _, lat, lon in demo_prep.BURNING_SITES:
        assert demo_prep._near(spots, lat, lon, corroborated=True) is not None
    _, lat, lon = demo_prep.CITIZEN_SITE
    citizen = demo_prep._near(spots, lat, lon, corroborated=False)
    assert citizen is not None
    assert citizen["source_counts"] == {"citizen_sensor": 2}
    assert next(i for i in prep.items if i.name == "demo hotspots").warm


def test_seeding_twice_writes_nothing_the_second_time(isolated_storage):
    """Rewriting a present site would give its hotspot a new id and orphan its cached reading."""
    _seed_all(isolated_storage)
    before = {p.name: p.read_text() for p in (isolated_storage / "signals").iterdir()}
    ids_before = {h.hotspot_id for h in hotspots.current()}

    _seed_all(isolated_storage)

    after = {p.name: p.read_text() for p in (isolated_storage / "signals").iterdir()}
    assert after == before
    assert {h.hotspot_id for h in hotspots.current()} == ids_before


def test_a_cached_reading_and_a_pending_alert_mean_no_model_calls(isolated_storage):
    _seed_all(isolated_storage)
    hotspot_id = _demo_hotspot_id()
    node = FakeNode()
    node.imagery[hotspot_id] = {"image_date": "2026-09-28", "plume_visible": True}
    node.alerts.append(
        {"alert_id": "a-0", "hotspot_id": hotspot_id, "status": "awaiting_confirmation"}
    )
    prep, _ = _prep(node, isolated_storage, steps=("imagery", "alert"))

    assert prep.run() == 0
    assert node.calls("POST") == []


def test_a_sent_alert_does_not_count_as_warm(isolated_storage):
    """Once confirmed on camera the draft is gone; the next prep drafts a fresh one."""
    _seed_all(isolated_storage)
    hotspot_id = _demo_hotspot_id()
    node = FakeNode()
    node.alerts.append({"alert_id": "a-0", "hotspot_id": hotspot_id, "status": "sent"})
    prep, _ = _prep(node, isolated_storage, steps=("alert",))

    prep.run()

    assert node.calls("POST") == [f"/hotspots/{hotspot_id}/alert"]


def test_503s_are_retried_with_growing_waits_and_the_imagery_comes_first(isolated_storage):
    _seed_all(isolated_storage)
    hotspot_id = _demo_hotspot_id()
    node = FakeNode(imagery_posts=(503, 503, 200), alert_posts=(503, 200))
    prep, waits = _prep(node, isolated_storage, steps=("imagery", "alert"), attempts=4)

    assert prep.run() == 0
    assert (
        node.calls("POST")
        == [f"/hotspots/{hotspot_id}/imagery"] * 3 + [f"/hotspots/{hotspot_id}/alert"] * 2
    )
    assert waits == [1.0, 2.0, 1.0]
    # Drafted after the reading, so the alert cites it.
    assert node.alerts[0]["imagery"] is not None


def test_503_forever_gives_up_cold_with_the_command_to_try_again(isolated_storage, capsys):
    _seed_all(isolated_storage)
    node = FakeNode(imagery_posts=(503,) * 10)
    prep, _ = _prep(node, isolated_storage, steps=("imagery",), attempts=3)

    assert prep.run() == 1
    assert len(node.calls("POST")) == 3
    printed = capsys.readouterr().out
    assert "still unavailable after 3 attempts" in printed
    assert "demo_prep.py --url http://node.test --only imagery" in printed


def test_a_spent_daily_quota_stops_the_run_asking(isolated_storage, capsys):
    """Retrying a daily quota with backoff only collects more rejections, one per step."""
    _seed_all(isolated_storage)
    node = FakeNode(imagery_posts=(503,) * 10)
    node.busy_detail = (
        "gemini-3.8-flash (Gemini) has hit its free-tier request quota. "
        f"{demo_prep.DAILY_QUOTA_SPENT}; it resets at midnight Pacific time."
    )
    prep, waits = _prep(node, isolated_storage, steps=("imagery", "alert", "forecast"), attempts=4)

    assert prep.run() == 1
    assert len(node.calls("POST")) == 1
    assert node.calls("GET", "/forecast") == []
    assert waits == []
    assert "already spent" in capsys.readouterr().out


def test_a_call_that_landed_despite_the_error_is_not_paid_for_again(isolated_storage):
    """A POST that timed out here may have finished there; the free GET is asked first."""
    _seed_all(isolated_storage)
    node = FakeNode(imagery_posts=(503,))
    node.lands_anyway = True
    prep, _ = _prep(node, isolated_storage, steps=("imagery",), attempts=4)

    assert prep.run() == 0
    assert len(node.calls("POST")) == 1


def test_the_alert_waits_for_a_cold_reading_instead_of_being_drafted_without_it(isolated_storage):
    """A draft made now is the one the server keeps returning; it would never cite the image."""
    _seed_all(isolated_storage)
    hotspot_id = _demo_hotspot_id()
    node = FakeNode(imagery_posts=(503,) * 10)
    prep, _ = _prep(node, isolated_storage, steps=("imagery", "alert"), attempts=2)

    assert prep.run() == 1
    assert node.calls("POST") == [f"/hotspots/{hotspot_id}/imagery"] * 2
    held = next(i for i in prep.items if i.name == "alert draft")
    assert not held.warm and "--only imagery alert" in held.next_command


def test_a_refusal_is_an_answer_and_is_not_retried(isolated_storage):
    _seed_all(isolated_storage)
    node = FakeNode(alert_posts=(409,))
    prep, waits = _prep(node, isolated_storage, steps=("alert",), attempts=4)

    assert prep.run() == 1
    assert len(node.calls("POST")) == 1
    assert waits == []


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/alerts/alert-1/confirm", {}),
        ("/cases/case-1/confirm", {}),
        ("/cases/case-1/escalate", {}),
        ("/reports", {}),
        ("/sensors/readings", {}),
        ("/hotspots/h-1/imagery", {"reread": "true"}),
        ("/hotspots/h-1/alert", {"redraft": "true"}),
    ],
)
def test_the_script_cannot_confirm_file_send_or_spend_twice(path, params):
    """Hard constraint 2: confirming is the human's action on camera, never the prep's."""
    node = FakeNode()
    client = httpx.Client(transport=httpx.MockTransport(node), base_url="http://node.test")
    guarded = demo_prep.Node("http://node.test", client=client)

    with pytest.raises(demo_prep.Refused):
        guarded.post(path, **params)
    assert node.requests == []


def test_a_partial_corridor_is_cold_and_not_asked_again(isolated_storage):
    """The server does not cache a corridor with a waypoint missing, and a retry re-spends all."""
    node = FakeNode(corridor={"ncr": 1})
    prep, _ = _prep(node, isolated_storage, steps=("forecast", "corridors"))

    assert prep.run() == 1
    assert node.calls("GET", "/corridors/ncr/forecast") == ["/corridors/ncr/forecast"]
    ncr = next(i for i in prep.items if i.name == "corridor ncr")
    assert not ncr.warm and "--corridor ncr" in ncr.next_command
    assert next(i for i in prep.items if i.name == "corridor mumbai-pune").warm
    assert next(i for i in prep.items if i.name == "Delhi forecast").warm


def test_main_parses_arguments_and_runs_the_dry_run(isolated_storage, capsys):
    node = FakeNode()
    client = httpx.Client(transport=httpx.MockTransport(node), base_url="http://node.test")

    code = demo_prep.main(
        ["--url", "http://node.test", "--dry-run", "--data-dir", str(isolated_storage)],
        client=client,
        sleep=lambda _: None,
    )

    assert code == 1
    assert node.calls("POST") == []
    printed = capsys.readouterr().out
    assert "VAYUDOOT_FORECAST_CACHE_MINUTES=240" in printed
    assert "never confirms" in printed
