"""Fix 3: a startup failure is reported as a controlled line - never the
original exception message or a chained traceback (either could carry a DSN,
host, or key fragment). The process still exits nonzero.

The child process patches ``hermes.runtime.build_app`` to raise an exception
whose message contains a synthetic secret marker, then imports ``hermes.asgi``
(which runs its startup try/except at import time).
"""

from __future__ import annotations

import os
import subprocess
import sys

MARKER = "S3KRIT_MARKER_a1b2c3d4"

_CHILD = f"""
import hermes.runtime as rt
def _boom(*a, **k):
    raise RuntimeError({MARKER!r} + " postgresql://u:pw@host/db")
rt.build_app = _boom
import hermes.asgi  # noqa: F401 - triggers the guarded startup
"""


def test_startup_failure_is_sanitised_no_secret_no_traceback():
    env = dict(os.environ)
    env["HERMES_MODE"] = "offline"
    env["PYTHONPATH"] = os.pathsep.join(
        [os.path.join(os.getcwd(), "src"), env.get("PYTHONPATH", "")]
    )
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD],
        capture_output=True, text=True, env=env, timeout=60,
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, "startup must fail with a nonzero exit"
    assert MARKER not in combined, "the original exception message leaked"
    assert "postgresql://" not in combined, "a DSN fragment leaked"
    assert "Traceback (most recent call last)" not in combined, "a traceback leaked"
    # still actionable: names the mode and the config fields to check
    assert "mode=offline" in proc.stderr
    assert "GEMINI_API_KEY" in proc.stderr and "DATABASE_URL" in proc.stderr
