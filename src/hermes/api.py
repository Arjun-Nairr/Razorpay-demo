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
  slice accepts only locally signed simulated fixtures. Any other configured
  ``evidence_mode`` (including ``REAL_TEST_MODE``) is rejected at construction;
  there is no real/Test Mode path here.
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
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from .engine import RecoveryEngine
from .types import CaseQuery, RazorpayWebhook, WebhookType

_SUPPORTED_EVENTS: dict[str, WebhookType] = {
    "payment.failed": WebhookType.PAYMENT_FAILED,
    "payment.captured": WebhookType.PAYMENT_CAPTURED,
}
_ALLOWED_EVIDENCE_MODE = "SIMULATED"
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


def normalize_event(body: dict, event_id: str, config: ApiConfig) -> RazorpayWebhook:
    """Razorpay-shaped envelope -> typed webhook. Raises :class:`_UnsupportedEvent`
    for anything outside the supported failure/capture fixture shapes.

    Merchant-communication facts are NOT taken from the payload: with no
    verified merchant-context source this slice sets ``consent=False`` and
    ``reachable_channel=False`` so no customer contact can be authorized. A
    ``consent``/``reachable_channel``/``merchant_context`` field in the payment
    payload is ignored.
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

    return RazorpayWebhook(
        event_id=event_id,
        type=kind,
        obligation_id=obligation_id,
        amount_minor=amount,
        currency=currency,
        reason_code=reason_code if kind is WebhookType.PAYMENT_FAILED else None,
        payment_id=payment_id,
        evidence_mode=config.evidence_mode,  # validated == "SIMULATED"
        # No verified merchant context at ingress: never inherit the permissive
        # RazorpayWebhook defaults, never read consent from the payload.
        consent=False,
        reachable_channel=False,
    )


def _case_json(projection: Any) -> dict:
    return dataclasses.asdict(projection)


def create_app(*, engine: RecoveryEngine, config: ApiConfig) -> FastAPI:
    """Build the ingress app around an injected engine and config.

    Re-validates ``config`` before wiring routes: a blank ``webhook_secret`` or
    a non-``SIMULATED`` ``evidence_mode`` raises ``ValueError`` here, so a
    misconfigured app never starts serving requests.
    """
    _validate_config(config)
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

        # Signature first: an invalid/absent/malformed signature is rejected
        # without the body ever being parsed.
        if not _signature_ok(config.webhook_secret, raw, signature):
            raise HTTPException(status_code=401, detail=_ERR_BAD_SIGNATURE)
        if not event_id or not event_id.strip():
            raise HTTPException(status_code=400, detail=_ERR_MISSING_EVENT_ID)

        try:
            body = json.loads(raw)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail=_ERR_MALFORMED_JSON)
        try:
            webhook = normalize_event(body, event_id, config)
        except _UnsupportedEvent:
            raise HTTPException(status_code=422, detail=_ERR_UNSUPPORTED_EVENT)

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
            raise HTTPException(status_code=400, detail=_ERR_MALFORMED_JSON)
        if not isinstance(body, dict):  # arrays / null / strings / numbers
            raise HTTPException(status_code=400, detail=_ERR_BODY_NOT_OBJECT)
        until = body.get("until")
        if isinstance(until, bool) or not isinstance(until, int):
            raise HTTPException(status_code=400, detail=_ERR_UNTIL_NOT_INT)
        try:
            report = engine.run(until=until)
        except ValueError:
            raise HTTPException(status_code=409, detail=_ERR_TIME_BACKWARD)
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
            raise HTTPException(status_code=404, detail=_ERR_CASE_NOT_FOUND)
        return _case_json(projection)

    return app
