"""Cross-origin access, for the web UI when Firebase Hosting serves it.

The middleware is added when `api.py` is imported, from settings read then, so
each case runs in a fresh interpreter with the environment it needs rather than
reloading the module under the rest of the suite.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

PROBE = """
import json
from fastapi.testclient import TestClient
from vayudoot.api import app

client = TestClient(app)
out = {}
for origin in ("https://vayudoot.web.app", "https://elsewhere.example"):
    r = client.options(
        "/health",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    out[origin] = r.headers.get("access-control-allow-origin")
r = client.get("/health", headers={"Origin": "https://vayudoot.web.app"})
out["simple"] = r.headers.get("access-control-allow-origin")
print(json.dumps(out))
"""


def _probe(origins: str) -> dict:
    env = {
        **os.environ,
        "VAYUDOOT_CORS_ORIGINS": origins,
        "DATABASE_URL": "",
        "FIREBASE_SERVICE_ACCOUNT": "",
        "VAYUDOOT_SCAN_ENABLED": "false",
    }
    done = subprocess.run(
        [sys.executable, "-c", PROBE],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_a_listed_origin_may_call_the_api_and_no_other_may():
    seen = _probe("https://vayudoot.web.app, https://vayudoot.firebaseapp.com")
    assert seen["https://vayudoot.web.app"] == "https://vayudoot.web.app"
    assert seen["simple"] == "https://vayudoot.web.app"
    assert seen["https://elsewhere.example"] is None


def test_no_origin_is_allowed_by_default():
    """The UI served by the API itself is same-origin and needs nothing."""
    seen = _probe("")
    assert seen["https://vayudoot.web.app"] is None
    assert seen["simple"] is None
