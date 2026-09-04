"""Isolated real Nous Hermes agent integration for one Case 3 decision.

The *parent* side (``hermes.hermes_agent_strategist.HermesAgentStrategist``,
imported from the project venv) prepares a bounded, immutable evidence bundle and
spawns :mod:`hermes.hermes_agent.child_main` as a subprocess **run by the
installed Hermes interpreter**, in a project-local, gitignored ``HERMES_HOME``.

Nothing in this package is imported by the project's own interpreter except the
path constants below - ``child_main`` imports the Hermes runtime and must only
ever run under that runtime's venv.
"""

from __future__ import annotations

import os.path

# Path to the child entrypoint, passed to ``subprocess`` by the parent.
CHILD_MAIN = os.path.join(os.path.dirname(__file__), "child_main.py")

# The exact installed Hermes revision this integration was built and proven
# against. The parent refuses to launch if ``git -C <checkout> rev-parse HEAD``
# does not match (desktop auto-update is a reproducibility risk).
EXPECTED_HERMES_REVISION = "e02d1e41fc6104187e20af9eac8b2820566e3508"

# Sentinel the child prints immediately before its one-line JSON result, so the
# parent can find it past any Hermes stdout banner noise.
RESULT_SENTINEL = "HERMES_CHILD_RESULT "

TOOL_NAMES = (
    "get_payment_retry_facts",
    "get_payment_history",
    "get_recovery_actions",
)

MAX_TOOL_CALLS = 6
MAX_MODEL_ITERATIONS = 8
SUBPROCESS_DEADLINE_S = 90.0
MAX_HISTORY_REQUESTS = 2
