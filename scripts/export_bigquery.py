"""Export this node's detections for BigQuery, and load them if BigQuery is set up.

    .venv/bin/python scripts/export_bigquery.py
    .venv/bin/python scripts/export_bigquery.py --out data/exports/today --no-neighbours
    .venv/bin/python scripts/export_bigquery.py --project my-sandbox-project

Always writes the export: newline-delimited JSON and a BigQuery schema per table,
a manifest, and the view definitions. What happens next depends on what is
installed and configured:

* `google-cloud-bigquery` installed (`uv pip install -e ".[bigquery]"`),
  application default credentials present, and a project id given — the files
  are loaded into the dataset with load jobs, creating it if it is missing.
* anything missing — nothing is uploaded; the exact `bq` commands and the
  one-time setup steps are printed instead.

Reads the store the same way the server does, so run it with the server's
environment (`DATABASE_URL`, `VAYUDOOT_CASE_DIR`, and so on). It only reads.
See `docs/bigquery.md` for the tables and the queries.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from vayudoot import export

SETUP_STEPS = """\
One-time setup for the BigQuery sandbox (free, no billing account, no card):

  1. Open https://console.cloud.google.com/ with your Google account and create
     a project. When asked about billing, skip it: a project with no billing
     account is what puts BigQuery in sandbox mode.
  2. Enable the BigQuery API for that project:
       https://console.cloud.google.com/apis/library/bigquery.googleapis.com
  3. Give this machine credentials:
       gcloud auth application-default login
       gcloud auth application-default set-quota-project YOUR_PROJECT_ID
  4. Install the client library:
       uv pip install -e ".[bigquery]"
  5. Run this script again with --project YOUR_PROJECT_ID
     (or set GOOGLE_CLOUD_PROJECT).

Sandbox limits: 10 GiB of storage, 1 TiB of queries a month, and every table,
view and partition is deleted 60 days after it is created. Keep the export
directories: loading them again is how history comes back.
"""


def _default_out() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path("data/exports/bigquery") / stamp


def _can_upload(project: str) -> tuple[bool, str]:
    """Whether a load can be attempted, and if not, the first thing missing."""
    if not project:
        return False, "no project id (pass --project or set GOOGLE_CLOUD_PROJECT)"
    try:
        import google.auth
        from google.cloud import bigquery  # noqa: F401
    except ImportError:
        return False, 'google-cloud-bigquery is not installed (uv pip install -e ".[bigquery]")'
    try:
        google.auth.default()
    except Exception as exc:  # noqa: BLE001 - any failure means "not configured"
        return False, f"no application default credentials ({type(exc).__name__})"
    return True, ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=None, help="Export directory")
    parser.add_argument(
        "--project",
        default=os.environ.get("VAYUDOOT_BIGQUERY_PROJECT")
        or os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
        help="Google Cloud project id (default: $VAYUDOOT_BIGQUERY_PROJECT, "
        "then $GOOGLE_CLOUD_PROJECT)",
    )
    parser.add_argument("--dataset", default=export.DEFAULT_DATASET)
    parser.add_argument(
        "--location",
        default=export.DEFAULT_LOCATION,
        help="Dataset location, e.g. US, EU or asia-south1. Fixed once the dataset exists.",
    )
    parser.add_argument(
        "--no-neighbours", action="store_true", help="Do not read neighbours' feeds"
    )
    parser.add_argument(
        "--no-upload", action="store_true", help="Write the files and print commands only"
    )
    args = parser.parse_args(argv)

    out = args.out or _default_out()
    manifest = export.export(out, include_neighbours=not args.no_neighbours)
    export.write_view_files(manifest, args.project, args.dataset)

    print(f"Export {manifest.export_id} written to {manifest.directory}")
    for entry in manifest.tables:
        print(f"  {entry['name']:20} {entry['rows']:6} rows")
    for error in manifest.neighbour_errors:
        print(f"  neighbour not read: {error}")

    ready, missing = (False, "--no-upload") if args.no_upload else _can_upload(args.project)
    if ready:
        from google.api_core.exceptions import Forbidden

        try:
            result = export.upload(manifest, args.project, args.dataset, args.location)
        except Forbidden as exc:
            # Credentials exist but cannot write to BigQuery: most often a
            # Firebase service-account key, which has Firestore rights only.
            # The export is on disk either way, so say what to fix, not a trace.
            print(f"\nNot loaded: BigQuery refused these credentials.\n  {exc.message}\n")
            print(
                "Sign in as a project owner instead:\n"
                "  gcloud auth application-default login\n"
                f"  gcloud auth application-default set-quota-project {args.project}\n"
                "and unset GOOGLE_APPLICATION_CREDENTIALS, or grant the account the\n"
                "BigQuery Data Editor and BigQuery Job User roles."
            )
            return 1
        if result["skipped"]:
            print(f"\nNot loaded: {result['reason']} ({result['target']}).")
        else:
            print(f"\nLoaded into {result['target']} with load jobs; views refreshed.")
        return 0

    print(f"\nNot uploading: {missing}.\n")
    if not args.no_upload:
        print(SETUP_STEPS)
    print("To load this export with the bq command-line tool:\n")
    for line in export.bq_commands(manifest, args.project, args.dataset, args.location):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
