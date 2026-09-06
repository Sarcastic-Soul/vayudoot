"""The prompt evaluation harness.

The pipeline's own test suite replaces the four agent stages with fakes, which
is what makes it fast and offline — and also what makes it blind to the only
question that matters when a prompt is edited: did the model get better or
worse? Both corroboration bugs this project has shipped passed every test.

This package is the other half. It runs the real agents against a fixture set
described as data in `evals/`, scores the answers on the axes that have actually
gone wrong (classification, calibration, corroboration honesty, refusal), and
writes a run record that can be diffed against an earlier one.

The code lives under `scripts/` rather than `src/vayudoot/` on purpose: it is
development tooling, not something the deployed service imports. `evals/` holds
fixtures only, so adding a case never means writing Python.
"""

from __future__ import annotations

__all__ = ["guards", "manifest", "replay", "report", "runner", "scoring"]
