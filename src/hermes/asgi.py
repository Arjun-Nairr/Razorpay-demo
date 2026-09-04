"""ASGI entrypoint for uvicorn:  uvicorn hermes.asgi:app --host 127.0.0.1

Mode comes from ``HERMES_MODE``: ``offline`` (default) or ``live``. Live mode
requires ``GEMINI_API_KEY`` and ``DATABASE_URL`` and an initialised schema
(``python scripts/init_neon.py``); if any is missing, or another process holds
the demo writer lock, this module fails to import with a clear one-line reason
and uvicorn exits without serving - so the UI never opens against a dead API.

A startup failure is reported as a single controlled line naming the mode, the
exception *type*, and the configuration fields worth checking - never the
original exception message or its traceback, which can carry a DSN, host, or
key fragment. The process still exits nonzero.
"""

from __future__ import annotations

import os
import sys

from .runtime import Settings, build_app

_MODE = os.environ.get("HERMES_MODE", "offline").strip() or "offline"

try:
    _settings = Settings.load(mode=_MODE)
    app = build_app(_settings)
except BaseException as exc:  # noqa: BLE001 - re-raised as a sanitised SystemExit
    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
        raise
    # Do NOT interpolate ``exc``: even our own Runtime/ValueError messages are
    # not guaranteed secret-free once field values get folded in. The type name
    # is a class identifier and safe; the hint names fields, not values.
    print(
        f"hermes API startup failed (mode={_MODE}): {type(exc).__name__} while "
        "loading configuration or opening the ledger. Check GEMINI_API_KEY, "
        "DATABASE_URL, and HERMES_DEMO_SCHEMA in the environment or root .env, "
        "and that `python scripts/init_neon.py` has run. (error detail suppressed)",
        file=sys.stderr,
    )
    raise SystemExit(1) from None  # no chained traceback, nonzero exit
