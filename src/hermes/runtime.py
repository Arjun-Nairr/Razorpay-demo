r"""Local composition root for the runnable Case 3 demo.

Loads the gitignored root ``.env`` (shell env wins), validates the
configuration *without ever printing a value*, and wires:

  FastAPI  <-  RecoveryEngine  ->  Ledger (Postgres-persisted, snapshot store)
                              \->  Strategist (live Gemini or scripted)
                              \->  simulated payment provider

Two modes:

- ``offline`` (default): the ledger is a ``PgLedger`` over an in-process
  ``InMemorySnapshotStore`` (so restart-within-tests still works and the same
  per-op lock applies) + ``ScriptedStrategist``. No credentials, no network.
- ``live``: ``PgLedger`` over ``DATABASE_URL`` + ``HermesStrategist`` over
  ``GEMINI_API_KEY``. Missing credentials FAIL startup - a live run never
  silently falls back to scripted proposals.

On startup the demo/provider state (trusted synthetic merchant context, the
provider's current retry eligibility per obligation, and the next case serial)
is deterministically reconstructed from the persisted ledger, so restarting the
app over the same durable store keeps every existing case usable and makes a
fresh case genuinely new.

The Razorpay webhook secret is intentionally NOT used (blank / deferred).
Simulated ingress is signed with ``HERMES_DEMO_SIGNING_SECRET`` - a separate,
locally generated demo secret, never presented as Razorpay's.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .adapters import FakeRazorpayAdapter, ScriptedStrategist
from .api import ApiConfig, create_app
from .demo_fixtures import DEMO_SIGNING_SECRET_ENV, case3_merchant_context, demo_serial_of, new_demo_signing_secret
from .engine import RecoveryEngine
from .types import CaseQuery


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
    ``describe()`` is safe to log: it reports *presence*, not content."""

    mode: str  # "offline" | "live"
    demo_signing_secret: str  # generated if unset; used only for SIMULATED ingress
    demo_schema: str = "hermes_demo"
    has_gemini_key: bool = False
    has_database_url: bool = False
    gemini_model: str = "gemini-3.7-flash"
    _database_url: str | None = field(default=None, repr=False)

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
        schema = os.environ.get("HERMES_DEMO_SCHEMA", "").strip() or "hermes_demo"
        if not re.match(r"\A[a-z_][a-z0-9_]{0,62}\Z", schema):
            raise ValueError("HERMES_DEMO_SCHEMA must be a simple lowercase identifier")

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
            demo_schema=schema,
            has_gemini_key=bool(gemini_key),
            has_database_url=bool(database_url),
            gemini_model=model,
            _database_url=database_url or None,
        )

    def describe(self) -> dict:
        """Redacted, log-safe view."""
        return {
            "mode": self.mode,
            "gemini_key_present": self.has_gemini_key,
            "database_url_present": self.has_database_url,
            "gemini_model": self.gemini_model,
            "demo_schema": self.demo_schema,
            "demo_signing_secret_present": bool(self.demo_signing_secret),
        }


def build_ledger(settings: Settings):
    from .pg_ledger import InMemorySnapshotStore, PgLedger, PostgresSnapshotStore

    if settings.mode == "live":
        return PgLedger(PostgresSnapshotStore(settings._database_url or "",
                                              settings.demo_schema))
    return PgLedger(InMemorySnapshotStore())


def build_strategist(settings: Settings):
    if settings.mode == "live":
        # Real Gemini. The client is built now so a bad key surfaces at startup;
        # the HTTP call is still lazy.
        from .hermes_strategist import HermesStrategist

        return HermesStrategist(model=settings.gemini_model, max_in_flight=2)
    return ScriptedStrategist()


def build_engine(
    settings: Settings, *, ledger=None, razorpay: FakeRazorpayAdapter | None = None
) -> RecoveryEngine:
    return RecoveryEngine(
        ledger or build_ledger(settings),
        build_strategist(settings),
        razorpay or FakeRazorpayAdapter(),
    )


def _bootstrap_demo_state(engine: RecoveryEngine, ledger, razorpay: FakeRazorpayAdapter):
    """From the persisted ledger, rebuild: the trusted synthetic merchant-context
    registry (every demo case is a Case 3 fixture), the simulated provider's
    current retry eligibility per obligation, and the next serial."""
    merchant_context: dict = {}
    max_serial = 0
    for case_id in ledger.case_ids():
        proj = engine.inspect(CaseQuery(case_id=case_id))
        obl = proj.obligation_id
        merchant_context[obl] = case3_merchant_context(obl)
        # deterministic: before a recorded failed retry the provider is
        # currently eligible; after one it currently reports no further retry.
        razorpay.set_retry_eligibility(obl, not proj.retry_outcome_recorded)
        serial = demo_serial_of(obl)
        if serial is not None:
            max_serial = max(max_serial, serial)
    return merchant_context, max_serial + 1


def build_app(settings: Settings):
    """Compose the FastAPI app around a persistent ledger + reconstructed demo
    state. The simulated provider is shared with ``create_app`` so ``/demo/*``
    can drive it. The ledger is closed on app shutdown."""
    razorpay = FakeRazorpayAdapter()
    ledger = build_ledger(settings)
    engine = build_engine(settings, ledger=ledger, razorpay=razorpay)
    merchant_context, next_serial = _bootstrap_demo_state(engine, ledger, razorpay)
    config = ApiConfig(webhook_secret=settings.demo_signing_secret)  # SIMULATED only
    return create_app(
        engine=engine, config=config, razorpay=razorpay,
        merchant_context=merchant_context, demo_serial_start=next_serial,
        mode_label=("live-gemini" if settings.mode == "live" else "scripted-offline"),
        on_shutdown=ledger.close,
    )
