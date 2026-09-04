"""ASGI entrypoint for uvicorn:  uvicorn hermes.asgi:app --host 127.0.0.1

Mode comes from ``HERMES_MODE``: ``offline`` (default) or ``live``. Live mode
requires ``GEMINI_API_KEY`` and ``DATABASE_URL`` and an initialised schema
(``python scripts/init_neon.py``); if any is missing, or another process holds
the demo writer lock, this module fails to import with a clear one-line reason
and uvicorn exits without serving - so the UI never opens against a dead API.
"""

from __future__ import annotations

import os
import sys

from .runtime import Settings, build_app

_MODE = os.environ.get("HERMES_MODE", "offline").strip() or "offline"

try:
    _settings = Settings.load(mode=_MODE)
    app = build_app(_settings)
except (RuntimeError, ValueError) as exc:
    # Our own startup errors carry safe, actionable messages (no secrets).
    print(f"hermes API startup failed (mode={_MODE}): {exc}", file=sys.stderr)
    raise
except Exception as exc:  # noqa: BLE001
    # Anything else (e.g. a driver connection error) may carry host details -
    # print only the type, not the message.
    print(
        f"hermes API startup failed (mode={_MODE}): {type(exc).__name__} "
        "(check DATABASE_URL / network / that scripts/init_neon.py has run)",
        file=sys.stderr,
    )
    raise
