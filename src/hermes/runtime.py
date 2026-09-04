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
from .demo_fixtures import (
    DEMO_PROVENANCE_KIND,
    DEMO_SIGNING_SECRET_ENV,
    MerchantContext,
    demo_serial_of,
    new_demo_signing_secret,
)
from .engine import RecoveryEngine
from .types import AuditQuery, CaseQuery


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
    # Provider selection is INDEPENDENT of Hermes/Gemini `mode` above -
    # "offline"/"live"/"hermes" pick the strategist; this picks the payment
    # provider. Default "fake": zero behavior change, no credentials needed.
    razorpay_provider: str = "fake"  # "fake" | "hybrid_test_mode"
    razorpay_test_mode_enabled: bool = False
    has_razorpay_test_credentials: bool = False
    _database_url: str | None = field(default=None, repr=False)
    _razorpay_key_id: str | None = field(default=None, repr=False)
    _razorpay_key_secret: str | None = field(default=None, repr=False)
    _razorpay_webhook_secret: str | None = field(default=None, repr=False)

    @classmethod
    def load(cls, *, mode: str = "offline", load_env: bool = True) -> "Settings":
        if mode not in ("offline", "live", "hermes"):
            raise ValueError("mode must be 'offline', 'live', or 'hermes'")
        if load_env:
            _load_dotenv()
        gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
        database_url = os.environ.get("DATABASE_URL", "").strip()
        demo_secret = os.environ.get(DEMO_SIGNING_SECRET_ENV, "").strip() or new_demo_signing_secret()
        model = os.environ.get("HERMES_STRATEGIST_MODEL", "").strip() or "gemini-3.7-flash"
        schema = os.environ.get("HERMES_DEMO_SCHEMA", "").strip() or "hermes_demo"
        if not re.match(r"\A[a-z_][a-z0-9_]{0,62}\Z", schema):
            raise ValueError("HERMES_DEMO_SCHEMA must be a simple lowercase identifier")

        if mode in ("live", "hermes"):
            missing = [
                name for name, val in
                (("GEMINI_API_KEY", gemini_key), ("DATABASE_URL", database_url))
                if not val
            ]
            if missing:
                raise RuntimeError(
                    f"{mode} mode requires " + ", ".join(missing)
                    + " in the environment or root .env (values are never printed)"
                )

        razorpay_provider = os.environ.get("RAZORPAY_PROVIDER", "").strip() or "fake"
        if razorpay_provider not in ("fake", "hybrid_test_mode"):
            raise ValueError("RAZORPAY_PROVIDER must be 'fake' or 'hybrid_test_mode'")
        key_id = key_secret = webhook_secret = None
        test_mode_enabled = False
        if razorpay_provider == "hybrid_test_mode":
            from .razorpay_test_mode import load_credentials

            try:
                creds = load_credentials(os.environ)  # raises on non-test key
            except ValueError as exc:
                raise RuntimeError(str(exc)) from exc
            if creds is None:
                raise RuntimeError(
                    "hybrid_test_mode provider requires RAZORPAY_KEY_ID, "
                    "RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET in the "
                    "environment or root .env (values are never printed)"
                )
            key_id, key_secret, webhook_secret = creds.key_id, creds.key_secret, creds.webhook_secret
            test_mode_enabled = creds.enabled

        return cls(
            mode=mode,
            demo_signing_secret=demo_secret,
            demo_schema=schema,
            has_gemini_key=bool(gemini_key),
            has_database_url=bool(database_url),
            gemini_model=model,
            razorpay_provider=razorpay_provider,
            razorpay_test_mode_enabled=test_mode_enabled,
            has_razorpay_test_credentials=key_id is not None,
            _database_url=database_url or None,
            _razorpay_key_id=key_id,
            _razorpay_key_secret=key_secret,
            _razorpay_webhook_secret=webhook_secret,
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
            "razorpay_provider": self.razorpay_provider,
            "razorpay_test_credentials_present": self.has_razorpay_test_credentials,
            "razorpay_test_mode_enabled": self.razorpay_test_mode_enabled,
        }


def build_ledger(settings: Settings):
    from .pg_ledger import InMemorySnapshotStore, PgLedger, PostgresSnapshotStore

    if settings.mode in ("live", "hermes"):
        return PgLedger(PostgresSnapshotStore(settings._database_url or "",
                                              settings.demo_schema))
    return PgLedger(InMemorySnapshotStore())


def build_strategist(settings: Settings):
    if settings.mode == "hermes":
        # The ACTUAL Nous Hermes runtime, isolated subprocess. Verifies the
        # installed revision on construction; raises HermesRuntimeUnavailable
        # (a RuntimeError) if the runtime is missing / wrong - never a silent
        # fall back to the direct-Gemini adapter.
        from .hermes_agent_strategist import HermesAgentStrategist

        return HermesAgentStrategist(gemini_model=settings.gemini_model)
    if settings.mode == "live":
        # Direct google-genai (kept for comparison / tests only).
        from .hermes_strategist import HermesStrategist

        return HermesStrategist(model=settings.gemini_model, max_in_flight=2)
    return ScriptedStrategist()


def build_provider(settings: Settings):
    """The payment provider - independent of ``build_strategist``'s Hermes/
    Gemini mode. Default ``"fake"``: unchanged simulated adapter. Only
    ``"hybrid_test_mode"`` builds a real Razorpay Test Mode adapter (retry
    eligibility stays simulated; see ``razorpay_test_mode.py``)."""
    if settings.razorpay_provider != "hybrid_test_mode":
        return FakeRazorpayAdapter()
    from .razorpay_test_mode import HybridPaymentProvider, RazorpayTestModeAdapter

    real = RazorpayTestModeAdapter(
        settings._razorpay_key_id or "", settings._razorpay_key_secret or "",
        enabled=settings.razorpay_test_mode_enabled,
    )
    return HybridPaymentProvider(FakeRazorpayAdapter(), real)


def build_engine(
    settings: Settings, *, ledger=None, razorpay=None
) -> RecoveryEngine:
    return RecoveryEngine(
        ledger or build_ledger(settings),
        build_strategist(settings),
        razorpay if razorpay is not None else build_provider(settings),
    )


def _demo_provenance(engine: RecoveryEngine, case_id: str) -> dict | None:
    """The trusted ``DEMO_CASE_PROVENANCE`` detail for a case, or ``None`` if the
    case was not opened by ``/demo/case`` (e.g. an externally ingested webhook)."""
    for rec in engine.inspect(AuditQuery(case_id=case_id)).records:
        if rec.kind == DEMO_PROVENANCE_KIND:
            return rec.detail
    return None


def _bootstrap_demo_state(engine: RecoveryEngine, ledger, razorpay):
    """From the persisted ledger, rebuild - ONLY for cases carrying trusted demo
    provenance - the synthetic merchant-context registry and the simulated
    provider's current retry eligibility, plus the next serial.

    A case with no ``DEMO_CASE_PROVENANCE`` record (any externally ingested
    obligation, whatever its id looks like) is left alone: no merchant context,
    so contact stays denied, and no provider retry signal is invented (the
    adapter is fail-closed). Existing cases and payment accounting are untouched;
    the database is not reset.
    """
    merchant_context: dict = {}
    max_serial = 0
    for case_id in ledger.case_ids():
        prov = _demo_provenance(engine, case_id)
        if prov is None:
            continue  # not a trusted demo case - do not fabricate any facts
        proj = engine.inspect(CaseQuery(case_id=case_id))
        obl = proj.obligation_id
        merchant_context[obl] = MerchantContext(
            obligation_id=obl,
            consent=bool(prov.get("consent")),
            reachable_channel=bool(prov.get("reachable_channel")),
            customer_notify=bool(prov.get("customer_notify")),
            source=str(prov.get("source", "SYNTHETIC_DEMO_FIXTURE:restored")),
            payment_history=str(prov.get("payment_history", "ordinary")),
        )
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
    razorpay = build_provider(settings)
    ledger = build_ledger(settings)
    engine = build_engine(settings, ledger=ledger, razorpay=razorpay)
    merchant_context, next_serial = _bootstrap_demo_state(engine, ledger, razorpay)
    config = ApiConfig(webhook_secret=settings.demo_signing_secret)  # SIMULATED only
    real_secret = (
        settings._razorpay_webhook_secret
        if settings.razorpay_provider == "hybrid_test_mode" else None
    )
    return create_app(
        engine=engine, config=config, razorpay=razorpay,
        merchant_context=merchant_context, demo_serial_start=next_serial,
        mode_label={"hermes": "hermes-runtime", "live": "live-gemini"}.get(
            settings.mode, "scripted-offline"),
        on_shutdown=ledger.close, ledger=ledger,
        real_webhook_secret=real_secret,
    )
