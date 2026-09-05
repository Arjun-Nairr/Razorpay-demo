"""FastAPI signed simulated Razorpay ingress - tracer-bullet slice 3.

Delivery adapter only. This module owns raw-body HMAC-SHA256 signature
verification, the ``X-Razorpay-Event-Id`` deduplication identity, and turning a
supported Razorpay-shaped fixture into a typed :class:`~hermes.types.RazorpayWebhook`.
Every recovery decision still happens behind ``RecoveryEngine.receive`` /
``run`` / ``inspect``.

Invariants:

- The webhook route never runs the recovery loop; only ``POST /demo/run`` does.
- No module-level secret and no global engine: both are injected into
  :func:`create_app` and held on ``app.state``.
- Every event ``/webhooks/razorpay`` and the ``/demo/*`` controls ingest is
  stamped ``evidence_mode="SIMULATED"`` - ``ApiConfig`` accepts only that
  value; a differently configured ``evidence_mode`` is rejected at
  construction. The ONE real path, ``/webhooks/razorpay-test`` (genuine
  Razorpay Test Mode ``payment_link.paid`` events, ``evidence_mode=
  "REAL_TEST_MODE"``), is a separate opt-in route with its own secret and its
  own verification code in ``razorpay_test_mode.py`` - it is mounted only when
  ``create_app(real_webhook_secret=...)`` is supplied, never through this
  module's ``ApiConfig``/``_ingest`` path.
- No verified merchant-context source exists yet, so normalization sets
  ``consent=False`` and ``reachable_channel=False`` unconditionally. Payment
  payload fields can never grant communication consent. Authorized customer
  communication will require a future trusted merchant-context source
  (contract/consent records from the merchant's own system), out of scope here.
- Errors are fixed strings. Caller-supplied event values, raw payloads,
  signatures, identifiers, and exception messages are never echoed or logged.

``fastapi`` / ``httpx`` are the optional ``[api]`` extra; importing this module
requires ``fastapi`` installed.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import re
import secrets
import threading
from dataclasses import dataclass
from typing import Any, Callable

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from .demo_fixtures import (
    CASE3_REASON,
    CASE3_STEP_HOURS,
    DEMO_PROVENANCE_KIND,
    MerchantContext,
    capture_envelope,
    case3_merchant_context,
    demo_sign,
    failure_envelope,
    mint_demo_ids,
)
from .engine import RecoveryEngine, deliver_drafted_message
from .razorpay_test_mode import RealWebhookError, handle_payment_link_paid_webhook
from .telegram_delivery import NullTelegramAdapter
from .types import AuditQuery, CaseQuery, NoteEventCommand, RazorpayWebhook, WebhookType

_SUPPORTED_EVENTS: dict[str, WebhookType] = {
    "payment.failed": WebhookType.PAYMENT_FAILED,
    "payment.captured": WebhookType.PAYMENT_CAPTURED,
}
_ALLOWED_EVIDENCE_MODE = "SIMULATED"
# Product scope lock: an agentic recovery orchestrator for SaaS subscription
# payments declined for insufficient funds - not a general payment-failure
# engine. Any other (or missing) normalized failure reason is acknowledged
# safely (2xx, so the provider never retry-storms) but never reaches
# engine.receive - no case, no Hermes run, no effect of any kind.
_OUTCOME_UNSUPPORTED_REASON = "ignored_unsupported_failure_reason"
_HEX_SHA256 = re.compile(r"\A[0-9a-fA-F]{64}\Z")
_ISO_CURRENCY = re.compile(r"\A[A-Z]{3}\Z")

# Fixed client-facing error strings - never interpolate caller data.
_ERR_BAD_SIGNATURE = "invalid signature"
_ERR_MISSING_EVENT_ID = "missing X-Razorpay-Event-Id"
_ERR_MALFORMED_JSON = "malformed JSON body"
_ERR_UNSUPPORTED_EVENT = "unsupported or malformed event payload"
_ERR_BODY_NOT_OBJECT = "request body must be a JSON object"
_ERR_UNTIL_NOT_INT = "'until' must be an integer logical hour"
_ERR_TIME_BACKWARD = "logical time cannot move backward"
_ERR_CASE_NOT_FOUND = "case not found"


def _validate_config(config: "ApiConfig") -> None:
    if not isinstance(config.webhook_secret, str) or not config.webhook_secret.strip():
        raise ValueError("webhook_secret must be a non-empty, non-whitespace string")
    if config.evidence_mode != _ALLOWED_EVIDENCE_MODE:
        raise ValueError("this adapter only serves evidence_mode='SIMULATED'")


@dataclass(frozen=True)
class ApiConfig:
    """Injected configuration. ``webhook_secret`` is supplied by the caller
    (a process env var, a secret manager, a test literal) - never read from a
    file or from a module global here. Validated on construction: a blank
    secret or any ``evidence_mode`` other than ``SIMULATED`` is rejected."""

    webhook_secret: str
    evidence_mode: str = _ALLOWED_EVIDENCE_MODE

    def __post_init__(self) -> None:
        _validate_config(self)


class _UnsupportedEvent(Exception):
    """Payload is well-formed JSON but not a supported Razorpay-shaped
    failure/capture fixture. Its message is internal only - the HTTP layer
    always returns the fixed ``_ERR_UNSUPPORTED_EVENT`` string."""


def _signature_ok(secret: str, raw: bytes, provided: str | None) -> bool:
    """Constant-time HMAC-SHA256 check over the *exact* raw request bytes.

    The provided header is format-checked first (exactly 64 hex characters);
    anything else - missing, non-ASCII, wrong length - returns ``False`` rather
    than reaching (and possibly raising from) :func:`hmac.compare_digest`.
    """
    if not isinstance(provided, str) or not _HEX_SHA256.match(provided):
        return False
    expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided)


def _entity(payload: dict, group: str) -> dict:
    node = payload.get(group)
    if not isinstance(node, dict):
        raise _UnsupportedEvent(f"payload.{group} not an object")
    entity = node.get("entity")
    if not isinstance(entity, dict):
        raise _UnsupportedEvent(f"payload.{group}.entity not an object")
    return entity


def normalize_event(
    body: dict,
    event_id: str,
    config: ApiConfig,
    merchant_context: MerchantContext | None = None,
) -> RazorpayWebhook:
    """Razorpay-shaped envelope -> typed webhook. Raises :class:`_UnsupportedEvent`
    for anything outside the supported failure/capture fixture shapes.

    Merchant-communication facts are NEVER taken from the payload. If a trusted
    :class:`MerchantContext` fixture is supplied for this obligation, its
    ``consent`` / ``reachable_channel`` / ``customer_notify`` are used; otherwise
    contact stays denied (``consent=False``, ``reachable_channel=False``). A
    ``consent`` / ``reachable_channel`` / ``merchant_context`` field inside the
    payment payload is always ignored.
    """
    if not isinstance(body, dict):
        raise _UnsupportedEvent("top-level payload not an object")
    event = body.get("event")
    kind = _SUPPORTED_EVENTS.get(event) if isinstance(event, str) else None
    if kind is None:
        raise _UnsupportedEvent("event type not supported")

    payload = body.get("payload")
    if not isinstance(payload, dict):
        raise _UnsupportedEvent("payload not an object")

    payment = _entity(payload, "payment")
    subscription = _entity(payload, "subscription")

    obligation_id = subscription.get("id")
    if not isinstance(obligation_id, str) or not obligation_id.strip():
        raise _UnsupportedEvent("subscription id missing")

    amount = payment.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise _UnsupportedEvent("amount not a non-negative integer")

    currency = payment.get("currency")
    if not isinstance(currency, str) or not _ISO_CURRENCY.match(currency):
        raise _UnsupportedEvent("currency not a 3-letter uppercase code")

    payment_id = payment.get("id") if isinstance(payment.get("id"), str) else None
    reason_code = None
    for key in ("error_description", "error_reason", "error_code"):
        value = payment.get(key)
        if isinstance(value, str) and value.strip():
            reason_code = value
            break

    if merchant_context is not None and merchant_context.obligation_id == obligation_id:
        consent = bool(merchant_context.consent)
        reachable_channel = bool(merchant_context.reachable_channel)
        customer_notify = bool(merchant_context.customer_notify)
    else:  # no trusted merchant context -> contact denied, merchant-owned
        consent = False
        reachable_channel = False
        customer_notify = False

    return RazorpayWebhook(
        event_id=event_id,
        type=kind,
        obligation_id=obligation_id,
        amount_minor=amount,
        currency=currency,
        reason_code=reason_code if kind is WebhookType.PAYMENT_FAILED else None,
        payment_id=payment_id,
        evidence_mode=config.evidence_mode,  # validated == "SIMULATED"
        consent=consent,
        reachable_channel=reachable_channel,
        customer_notify=customer_notify,
    )


def _case_json(projection: Any) -> dict:
    return dataclasses.asdict(projection)


def _safe_obligation(body: Any) -> str | None:
    """Read ``payload.subscription.entity.id`` from an ALREADY-parsed body for
    merchant-context lookup. Runs only after HMAC verification and after
    ``json.loads``; ``normalize_event`` re-validates the shape."""
    try:
        obl = body["payload"]["subscription"]["entity"]["id"]
        return obl if isinstance(obl, str) else None
    except (KeyError, TypeError):
        return None


def _ingest(
    engine: RecoveryEngine,
    config: ApiConfig,
    mctx_lookup: "Callable[[str], MerchantContext | None] | None",
    raw: bytes,
    signature: str | None,
    event_id: str | None,
) -> dict:
    """Verify signature over raw bytes FIRST, then require the event id, decode,
    resolve trusted merchant context, normalize, and hand the event to
    ``engine.receive``. Never runs the recovery loop. Raises
    :class:`HTTPException` on any failure. Shared by the public webhook route
    and the server-side demo steps (which sign with the demo secret).

    An invalid or missing signature returns 401 *before* the body is parsed -
    no JSON decode, no merchant-context lookup, no engine call.
    """
    if not _signature_ok(config.webhook_secret, raw, signature):
        raise HTTPException(status_code=401, detail=_ERR_BAD_SIGNATURE)
    if not event_id or not event_id.strip():
        raise HTTPException(status_code=400, detail=_ERR_MISSING_EVENT_ID)
    try:
        body = json.loads(raw)  # only reached once the signature is verified
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=_ERR_MALFORMED_JSON)
    obligation_id = _safe_obligation(body)
    mctx = mctx_lookup(obligation_id) if (mctx_lookup and obligation_id) else None
    try:
        webhook = normalize_event(body, event_id, config, mctx)
    except _UnsupportedEvent:
        raise HTTPException(status_code=422, detail=_ERR_UNSUPPORTED_EVENT)
    if webhook.type is WebhookType.PAYMENT_FAILED and webhook.reason_code != CASE3_REASON:
        # Fail closed BEFORE Hermes ever runs: any other or missing reason
        # (including None) creates no case, retry, link, recommendation, or
        # message. Still a normal 2xx so the provider does not retry-storm -
        # signature verification and event-id handling above are unaffected.
        return {
            "accepted": True,
            "duplicate": False,
            "case_id": None,
            "event_id": event_id,
            "evidence_mode": webhook.evidence_mode,
            "outcome": _OUTCOME_UNSUPPORTED_REASON,
        }
    result = engine.receive(webhook)  # durable intake only
    return {
        "accepted": result.accepted,
        "duplicate": result.duplicate,
        "case_id": result.case_id,
        "event_id": event_id,
        "evidence_mode": webhook.evidence_mode,
    }


_DEMO_ERR_UNAVAILABLE = "demo controls require the simulated provider"
_DEMO_ERR_UNKNOWN_CASE = "unknown demo case"
_DEMO_ERR_BAD_STEP = "step must be one of: advance, retry_failed, capture"
_DEMO_ERR_RUN_BUSY = "a recovery run is already in progress; retry shortly"
_DEMO_ERR_NO_LINK = "no authorized recovery link to pay"
_DEMO_ERR_NO_LEDGER = "message delivery requires a persisted ledger"
_DEMO_STEPS = ("advance", "retry_failed", "capture", "deliver_message")


def _run_json(report: Any) -> dict:
    return {
        "logical_time": report.logical_time, "steps": report.steps,
        "proposals": report.proposals, "strategist_failures": report.strategist_failures,
        "scheduled": report.scheduled, "blocked": report.blocked,
        "stale_claims": report.stale_claims,
    }


def create_app(
    *,
    engine: RecoveryEngine,
    config: ApiConfig,
    razorpay: Any | None = None,
    merchant_context: dict | None = None,
    demo_serial_start: int = 1,
    mode_label: str = "scripted-offline",
    on_shutdown: "Callable[[], None] | None" = None,
    ledger: Any | None = None,
    real_webhook_secret: str | None = None,
    delivery: Any | None = None,
) -> FastAPI:
    """Build the ingress app around an injected engine and config.

    Re-validates ``config`` before wiring routes: a blank ``webhook_secret`` or
    a non-``SIMULATED`` ``evidence_mode`` raises ``ValueError`` here.

    ``razorpay`` (the simulated payment provider) enables the ``/demo/*``
    controls. ``merchant_context`` / ``demo_serial_start`` carry state
    reconstructed from a persisted ledger so a restarted app keeps existing
    cases usable and mints genuinely-new ones. ``mode_label`` is reported by
    ``/health`` so the UI can show live-Gemini vs scripted honestly.
    ``on_shutdown`` (e.g. ``ledger.close``) is called when the app stops.
    ``ledger`` (when supplied) lets ``/demo/case`` stamp a trusted
    ``DEMO_CASE_PROVENANCE`` audit record that restart reconstruction keys on;
    without it a demo case still works for this process but is not
    reconstructable after a restart.

    ``real_webhook_secret`` (when supplied) mounts ONE additional route,
    ``POST /webhooks/razorpay-test`` - genuine Razorpay Test Mode
    ``payment_link.paid`` events, verified against this SEPARATE secret via a
    SEPARATE code path (``razorpay_test_mode.py``); the simulated
    ``/webhooks/razorpay`` route is completely untouched. A public tunnel MUST
    be configured to forward ONLY this one path - never the whole app (see
    HANDOFF.md for a concrete ingress-rule example). Omit to leave this route
    unmounted entirely (the default, offline-safe state).

    ``delivery`` (a ``MessageDeliveryAdapter``, e.g. a real
    ``TelegramAdapter``) backs ``POST /demo/step {"step": "deliver_message"}``
    - entirely separate from ``razorpay``. Omitted or ``None`` defaults to
    ``NullTelegramAdapter``, which never claims delivery.

    Concurrency: the ledger serialises its own operations; a slow model call in
    ``engine.run`` happens between ledger ops and holds no lock, so webhook
    intake never waits for Gemini. A single non-blocking ``run_lock`` enforces
    one recovery runner at a time. Blocking work runs in a threadpool so
    ``/health`` stays responsive.
    """
    _validate_config(config)

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        yield
        if on_shutdown is not None:
            try:
                on_shutdown()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass

    app = FastAPI(title="Hermes simulated ingress", docs_url=None, redoc_url=None,
                  lifespan=_lifespan)
    app.state.engine = engine
    app.state.config = config
    app.state.razorpay = razorpay
    app.state.ledger = ledger
    app.state.delivery = delivery or NullTelegramAdapter()
    app.state.mode_label = mode_label
    app.state.merchant_context = dict(merchant_context or {})
    app.state.demo_serial = max(1, int(demo_serial_start)) - 1
    app.state.run_lock = threading.Lock()  # one recovery runner at a time

    def _mctx_lookup(obligation_id: str) -> "MerchantContext | None":
        return app.state.merchant_context.get(obligation_id)

    def _signed_ingest(envelope: dict, event_id: str) -> dict:
        raw = json.dumps(envelope).encode("utf-8")
        sig = demo_sign(config.webhook_secret, raw)
        return _ingest(engine, config, _mctx_lookup, raw, sig, event_id)

    def _need_provider():
        rp = app.state.razorpay
        if rp is None:
            raise HTTPException(status_code=503, detail=_DEMO_ERR_UNAVAILABLE)
        return rp

    def _next_serial() -> int:
        app.state.demo_serial += 1
        return app.state.demo_serial

    # -- health (never touches the engine; stays fast) -------------------

    @app.get("/health")
    def health() -> dict:
        # Non-secret provider CAPABILITY flags only - never a key, secret, or
        # DSN. ``HybridPaymentProvider`` is duck-typed (has verify_link_payment);
        # the fake simulated adapter does not, so callers can fail closed
        # before attempting a real action (see scripts/run_one_hybrid_case.py).
        provider = app.state.razorpay
        payment_provider = "hybrid_test_mode" if hasattr(provider, "verify_link_payment") else "fake"
        return {
            "status": "ok",
            "evidence_mode": config.evidence_mode,
            "mode": app.state.mode_label,
            "payment_provider": payment_provider,
            "payment_provider_test_mode_enabled": bool(getattr(provider, "test_mode_enabled", False)),
            # Non-secret capability flag only - never the token/chat id.
            "message_delivery_channel": (
                "none" if isinstance(app.state.delivery, NullTelegramAdapter) else "telegram"
            ),
        }

    # -- public webhook: signature over raw bytes BEFORE any parsing ----

    @app.post("/webhooks/razorpay")
    async def razorpay_webhook(request: Request) -> dict:
        raw = await request.body()
        signature = request.headers.get("x-razorpay-signature")
        event_id = request.headers.get("x-razorpay-event-id")
        # Off the event loop; the ledger serialises intake, so this does not
        # wait for any in-progress model call.
        return await run_in_threadpool(
            _ingest, engine, config, _mctx_lookup, raw, signature, event_id
        )

    # -- REAL Razorpay Test Mode webhook: separate secret, separate code path,
    #    only mounted when a secret is actually configured. Never reachable
    #    from the simulated /webhooks/razorpay route or its secret.
    if real_webhook_secret is not None:

        @app.post("/webhooks/razorpay-test")
        async def razorpay_test_webhook(request: Request) -> dict:
            raw = await request.body()
            signature = request.headers.get("x-razorpay-signature")
            event_id = request.headers.get("x-razorpay-event-id")

            def _sync() -> dict:
                try:
                    return handle_payment_link_paid_webhook(
                        engine=engine, provider=app.state.razorpay,
                        webhook_secret=real_webhook_secret,
                        raw=raw, signature=signature, event_id=event_id,
                    )
                except RealWebhookError as exc:
                    raise HTTPException(status_code=exc.status_code, detail=exc.detail)

            return await run_in_threadpool(_sync)

    # -- demo controls -------------------------------------------------

    @app.post("/demo/case")
    async def demo_start_case() -> dict:
        rp = _need_provider()

        def _sync() -> dict:
            serial = _next_serial()
            obligation_id, _tok = mint_demo_ids(serial)
            ctx = case3_merchant_context(obligation_id)
            app.state.merchant_context[obligation_id] = ctx
            rp.set_retry_eligibility(obligation_id, True)
            body = _signed_ingest(
                failure_envelope(obligation_id, payment_id=f"pay_{obligation_id}_f0"),
                event_id=f"evt_{obligation_id}_f0",
            )
            if ledger is not None:
                # Trusted provenance + the facts needed to rebuild this case's
                # merchant context and provider retry eligibility after a full
                # app restart. Only cases with this record are reconstructed.
                ledger.note_event(NoteEventCommand(
                    case_id=body["case_id"], event_id=None,
                    kind=DEMO_PROVENANCE_KIND,
                    detail={
                        "obligation_id": obligation_id,
                        "consent": ctx.consent,
                        "reachable_channel": ctx.reachable_channel,
                        "customer_notify": ctx.customer_notify,
                        "source": ctx.source,
                        "payment_history": ctx.payment_history,
                        "provider_retry_eligible_at_open": True,
                    },
                    now=engine.logical_time,
                ))
            return {
                "case_id": body["case_id"],
                "obligation_id": obligation_id,
                "merchant_context": dataclasses.asdict(ctx),
                "evidence_mode": body["evidence_mode"],
                "mode": app.state.mode_label,
            }

        return await run_in_threadpool(_sync)

    @app.post("/demo/step")
    async def demo_step(request: Request) -> dict:
        rp = _need_provider()
        try:
            payload = json.loads(await request.body() or b"{}")
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail=_ERR_MALFORMED_JSON)
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail=_ERR_BODY_NOT_OBJECT)
        case_id = payload.get("case_id")
        step = payload.get("step")
        if step not in _DEMO_STEPS:
            raise HTTPException(status_code=400, detail=_DEMO_ERR_BAD_STEP)

        def _resolve_obl() -> str:
            try:
                return engine.inspect(CaseQuery(case_id=case_id)).obligation_id
            except KeyError:
                raise HTTPException(status_code=404, detail=_DEMO_ERR_UNKNOWN_CASE)

        if step == "capture":
            def _sync_capture() -> dict:
                obligation_id = _resolve_obl()
                proj = engine.inspect(CaseQuery(case_id=case_id))
                link_ref = next(
                    (i.reference for i in proj.action_intents
                     if i.action == "CREATE_RECOVERY_LINK" and i.reference), None,
                )
                if link_ref is None:
                    raise HTTPException(status_code=409, detail=_DEMO_ERR_NO_LINK)
                body = _signed_ingest(
                    capture_envelope(obligation_id, payment_id=link_ref),
                    event_id=f"evt_{obligation_id}_cap",  # stable: replays dedupe
                )
                return {"step": step, "capture": body}

            return await run_in_threadpool(_sync_capture)

        if step == "deliver_message":
            def _sync_deliver() -> dict:
                _resolve_obl()  # 404 if the case is unknown
                if app.state.ledger is None:
                    raise HTTPException(status_code=503, detail=_DEMO_ERR_NO_LEDGER)
                result = deliver_drafted_message(
                    app.state.ledger, case_id, app.state.delivery, now=engine.logical_time,
                )
                if result is None or not result.claimed and result.reason == "not_eligible":
                    # Nothing eligible, or lost the race to claim it - the
                    # adapter was never called either way.
                    return {"step": step, "delivery": {"attempted": False}}
                # A claim WAS taken and the adapter WAS called. The caller
                # reads the recorded outcome back via GET /demo/case/{id}
                # (action_intents[].message_status / delivery_outcome) -
                # never repeated here beyond a bare success/fail signal, and
                # never the checkout URL, template text, or a credential.
                return {"step": step, "delivery": {"attempted": True, "ok": result.ok}}

            return await run_in_threadpool(_sync_deliver)

        # advance / retry_failed both drive engine.run -> one runner at a time.
        if not app.state.run_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail=_DEMO_ERR_RUN_BUSY)

        def _sync_run() -> dict:
            try:
                obligation_id = _resolve_obl()
                if step == "retry_failed":
                    # Provider now reports no further retry currently scheduled
                    # (legitimate; NOT "retries exhausted"). History is recorded
                    # by intake as retry_outcome_recorded.
                    rp.set_retry_eligibility(obligation_id, False)
                    _signed_ingest(
                        failure_envelope(
                            obligation_id, payment_id=f"pay_{obligation_id}_r1"),
                        event_id=f"evt_{obligation_id}_r1_{secrets.token_hex(3)}",
                    )
                report = engine.run(until=engine.logical_time + CASE3_STEP_HOURS)
                return {"step": step, "run": _run_json(report)}
            finally:
                app.state.run_lock.release()

        return await run_in_threadpool(_sync_run)

    @app.get("/demo/case/{case_id}")
    async def demo_case_view(case_id: str) -> dict:
        def _sync() -> dict:
            try:
                proj = engine.inspect(CaseQuery(case_id=case_id))
            except KeyError:
                raise HTTPException(status_code=404, detail=_DEMO_ERR_UNKNOWN_CASE)
            audit = engine.inspect(AuditQuery(case_id=case_id))
            return {
                "case": _case_json(proj),
                "mode": app.state.mode_label,
                "timeline": [
                    {"seq": r.seq, "logical_time": r.logical_time, "kind": r.kind,
                     "detail": r.detail}
                    for r in audit.records
                ],
            }

        return await run_in_threadpool(_sync)

    @app.post("/demo/run")
    async def demo_run(request: Request) -> dict:
        try:
            body = json.loads(await request.body() or b"{}")
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail=_ERR_MALFORMED_JSON)
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail=_ERR_BODY_NOT_OBJECT)
        until = body.get("until")
        if isinstance(until, bool) or not isinstance(until, int):
            raise HTTPException(status_code=400, detail=_ERR_UNTIL_NOT_INT)
        if not app.state.run_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail=_DEMO_ERR_RUN_BUSY)

        def _sync() -> dict:
            try:
                return _run_json(engine.run(until=until))
            finally:
                app.state.run_lock.release()

        try:
            return await run_in_threadpool(_sync)
        except ValueError:
            raise HTTPException(status_code=409, detail=_ERR_TIME_BACKWARD)

    @app.get("/cases/{case_id}")
    async def get_case(case_id: str) -> dict:
        def _sync() -> dict:
            try:
                return _case_json(engine.inspect(CaseQuery(case_id=case_id)))
            except KeyError:
                raise HTTPException(status_code=404, detail=_ERR_CASE_NOT_FOUND)

        return await run_in_threadpool(_sync)

    return app
