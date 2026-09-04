"""ASGI entrypoint for uvicorn:  uvicorn hermes.asgi:app --host 127.0.0.1

Mode comes from the ``HERMES_MODE`` env var: ``offline`` (default) or ``live``.
Live mode requires ``GEMINI_API_KEY`` and ``DATABASE_URL`` and will refuse to
start without them (it never silently uses scripted proposals).
"""

from __future__ import annotations

import os

from .runtime import Settings, build_app

_settings = Settings.load(mode=os.environ.get("HERMES_MODE", "offline").strip() or "offline")
app = build_app(_settings)
