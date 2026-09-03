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
- Every event this app ingests is stamped ``evidence_mode="SIMULATED"`` - this
  slice accepts only locally signed simulated fixtures. The real Test Mode
  hybrid is a later slice.
- Errors are generic. Raw bodies, signatures, secrets, and payment identifiers
  are never logged or echoed in error responses.

``fastapi`` / ``httpx`` are the optional ``[api]`` extra; importing this module
requires ``fastapi`` installed.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from .engine import RecoveryEngine
from .types import CaseQuery, RazorpayWebhook, WebhookType

_SUPPORTED_EVENTS: dict[str, WebhookType] = {
    "payment.failed": WebhookType.PAYMENT_FAILED,
    "payment.captured": WebhookType.PAYMENT_CAPTURED,
}


@dataclass(frozen=True)
class ApiConfig:
    """Injected configuration. ``webhook_secret`` is supplied by the caller
    (a process env var, a secret manager, a test literal) - never read from a
    file or from a module global here."""

    webhook_secret: str
    evidence_mode: str = "SIMULATED"  # label stamped on every ingested event


class _UnsupportedEvent(Exception):
    """Payload is well-formed JSON but not a supported Razorpay-shaped
    failure/capture fixture."""


def _signature_ok(secret: str, raw: bytes, provided: str | None) -> bool:
    """Constant-time HMAC-SHA256 check over the *exact* raw request bytes."""
    if not provided:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided)


def _entity(payload: dict, group: str) -> dict:
    node = payload.get(group)
    if not isinstance(node, dict):
        raise _UnsupportedEvent(f"payload.{group} missing")
    entity = node.get("entity")
    if not isinstance(entity, dict):
        raise _UnsupportedEvent(f"payload.{group}.entity missing")
    return entity


def normalize_event(body: dict, event_id: str, config: ApiConfig) -> RazorpayWebhook:
    """Razorpay-shaped envelope -> typed webhook. Raises :class:`_UnsupportedEvent`
    for anything outside the supported failure/capture fixture shapes."""
    if not isinstance(body, dict):
        raise _UnsupportedEvent("top-level payload is not an object")
    event = body.get("event")
    kind = _SUPPORTED_EVENTS.get(event) if isinstance(event, str) else None
    if kind is None:
        raise _UnsupportedEvent(f"unsupported event type: {event!r}")

    payload = body.get("payload")
    if not isinstance(payload, dict):
        raise _UnsupportedEvent("payload missing")

    payment = _entity(payload, "payment")
    subscription = _entity(payload, "subscription")

    obligation_id = subscription.get("id")
    if not isinstance(obligation_id, str) or not obligation_id.strip():
        raise _UnsupportedEvent("payload.subscription.entity.id missing")

    amount = payment.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise _UnsupportedEvent("payload.payment.entity.amount must be a non-negative integer")

    currency = payment.get("currency") if isinstance(payment.get("currency"), str) else "INR"
    payment_id = payment.get("id") if isinstance(payment.get("id"), str) else None
    reason_code = None
    for key in ("error_description", "error_reason", "error_code"):
        value = payment.get(key)
        if isinstance(value, str) and value.strip():
            reason_code = value
            break

    return RazorpayWebhook(
        event_id=event_id,
        type=kind,
        obligation_id=obligation_id,
        amount_minor=amount,
        currency=currency,
        reason_code=reason_code if kind is WebhookType.PAYMENT_FAILED else None,
        payment_id=payment_id,
        evidence_mode=config.evidence_mode,  # always "SIMULATED" this slice
    )


def _case_json(projection: Any) -> dict:
    return dataclasses.asdict(projection)


def create_app(*, engine: RecoveryEngine, config: ApiConfig) -> FastAPI:
    """Build the ingress app around an injected engine and config."""
    app = FastAPI(title="Hermes simulated ingress", docs_url=None, redoc_url=None)
    app.state.engine = engine
    app.state.config = config

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "evidence_mode": config.evidence_mode}

    @app.post("/webhooks/razorpay")
    async def razorpay_webhook(request: Request) -> dict:
        raw = await request.body()  # exact raw bytes, before any decode
        signature = request.headers.get("x-razorpay-signature")
        event_id = request.headers.get("x-razorpay-event-id")

        # Signature first: an invalid/absent signature is rejected without the
        # body ever being parsed.
        if not _signature_ok(config.webhook_secret, raw, signature):
            raise HTTPException(status_code=401, detail="invalid signature")
        if not event_id or not event_id.strip():
            raise HTTPException(status_code=400, detail="missing X-Razorpay-Event-Id")

        try:
            body = json.loads(raw)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="malformed JSON body")
        try:
            webhook = normalize_event(body, event_id, config)
        except _UnsupportedEvent as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        result = engine.receive(webhook)  # durable intake only - no recovery loop
        return {
            "accepted": result.accepted,
            "duplicate": result.duplicate,
            "case_id": result.case_id,
            "event_id": event_id,
            "evidence_mode": webhook.evidence_mode,
        }

    @app.post("/demo/run")
    async def demo_run(request: Request) -> dict:
        try:
            body = json.loads(await request.body() or b"{}")
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="malformed JSON body")
        until = body.get("until")
        if isinstance(until, bool) or not isinstance(until, int):
            raise HTTPException(status_code=400, detail="'until' must be an integer logical hour")
        try:
            report = engine.run(until=until)
        except ValueError:
            raise HTTPException(status_code=409, detail="logical time cannot move backward")
        return {
            "logical_time": report.logical_time,
            "steps": report.steps,
            "proposals": report.proposals,
            "strategist_failures": report.strategist_failures,
            "scheduled": report.scheduled,
            "blocked": report.blocked,
            "stale_claims": report.stale_claims,
        }

    @app.get("/cases/{case_id}")
    def get_case(case_id: str) -> dict:
        try:
            projection = engine.inspect(CaseQuery(case_id=case_id))
        except KeyError:
            raise HTTPException(status_code=404, detail="case not found")
        return _case_json(projection)

    return app
