r"""Local composition root for the runnable Case 3 demo.

Loads the gitignored root ``.env`` (shell env wins), validates the
configuration *without ever printing a value*, and wires:

  FastAPI  <-  RecoveryEngine  ->  Ledger (Postgres-persisted or in-memory)
                              \->  Strategist (live Gemini or scripted)
                              \->  simulated payment provider

Two modes:

- ``offline`` (default): ``InMemoryLedger`` + ``ScriptedStrategist``. No
  credentials, no network. Used by tests and by ``--offline`` local runs.
- ``live``: ``PgLedger`` over ``DATABASE_URL`` + ``HermesStrategist`` over
  ``GEMINI_API_KEY``. If either credential is missing or the strategist cannot
  be built, startup FAILS - a live run never silently falls back to scripted
  proposals.

The Razorpay webhook secret is intentionally NOT used here (it is blank /
deferred). Simulated ingress is signed with ``HERMES_DEMO_SIGNING_SECRET`` -
a separate, locally generated demo secret, never presented as Razorpay's.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .adapters import FakeRazorpayAdapter, InMemoryLedger, ScriptedStrategist
from .api import ApiConfig, create_app
from .demo_fixtures import DEMO_SIGNING_SECRET_ENV, new_demo_signing_secret
from .engine import RecoveryEngine

_MISSING = object()


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    load_dotenv(os.path.join(root, ".env"), override=False)  # shell env wins


@dataclass(frozen=True)
class Settings:
    """Resolved configuration. Booleans/lengths only - never the secret values.

    ``describe()`` is safe to log: it reports *presence*, not content.
    """

    mode: str  # "offline" | "live"
    demo_signing_secret: str  # generated if unset; used only for SIMULATED ingress
    has_gemini_key: bool = False
    has_database_url: bool = False
    gemini_model: str = "gemini-3.7-flash"
    _database_url: str | None = field(default=None, repr=False)
    _gemini_key_present: bool = field(default=False, repr=False)

    @classmethod
    def load(cls, *, mode: str = "offline", load_env: bool = True) -> "Settings":
        if mode not in ("offline", "live"):
            raise ValueError("mode must be 'offline' or 'live'")
        if load_env:
            _load_dotenv()
        gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
        database_url = os.environ.get("DATABASE_URL", "").strip()
        demo_secret = os.environ.get(DEMO_SIGNING_SECRET_ENV, "").strip() or new_demo_signing_secret()
        model = os.environ.get("HERMES_STRATEGIST_MODEL", "").strip() or "gemini-3.7-flash"

        if mode == "live":
            missing = [
                name for name, val in
                (("GEMINI_API_KEY", gemini_key), ("DATABASE_URL", database_url))
                if not val
            ]
            if missing:
                raise RuntimeError(
                    "live mode requires " + ", ".join(missing)
                    + " in the environment or root .env (values are never printed)"
                )

        return cls(
            mode=mode,
            demo_signing_secret=demo_secret,
            has_gemini_key=bool(gemini_key),
            has_database_url=bool(database_url),
            gemini_model=model,
            _database_url=database_url or None,
            _gemini_key_present=bool(gemini_key),
        )

    def describe(self) -> dict:
        """Redacted, log-safe view."""
        return {
            "mode": self.mode,
            "gemini_key_present": self.has_gemini_key,
            "database_url_present": self.has_database_url,
            "gemini_model": self.gemini_model,
            "demo_signing_secret_present": bool(self.demo_signing_secret),
        }


def build_ledger(settings: Settings):
    if settings.mode == "live":
        from .pg_ledger import PgLedger, PostgresSnapshotStore

        return PgLedger(PostgresSnapshotStore(settings._database_url or ""))
    return InMemoryLedger()


def build_strategist(settings: Settings):
    if settings.mode == "live":
        # Real Gemini. Constructed eagerly enough to surface a bad key at
        # startup rather than mid-demo; the actual HTTP call is still lazy.
        from .hermes_strategist import HermesStrategist

        return HermesStrategist(model=settings.gemini_model, max_in_flight=2)
    return ScriptedStrategist()


def build_engine(
    settings: Settings, *, razorpay: FakeRazorpayAdapter | None = None
) -> RecoveryEngine:
    return RecoveryEngine(
        build_ledger(settings),
        build_strategist(settings),
        razorpay or FakeRazorpayAdapter(),
    )


def build_app(settings: Settings):
    """Compose the FastAPI app. The simulated provider is shared with
    ``create_app`` so the ``/demo/*`` controls can drive it."""
    razorpay = FakeRazorpayAdapter()
    engine = build_engine(settings, razorpay=razorpay)
    config = ApiConfig(webhook_secret=settings.demo_signing_secret)  # SIMULATED only
    return create_app(engine=engine, config=config, razorpay=razorpay)
