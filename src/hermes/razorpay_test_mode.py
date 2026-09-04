"""Genuine Razorpay Test Mode integration - HYBRID slice.

Scope (see ``RAZORPAY_TEST_SLICE.md``): the simulated SaaS obligation, history,
and accelerated failure/retry sequence are UNCHANGED. Only authorized recovery-
link creation and payment confirmation become real Razorpay Test Mode API
calls. Native subscription-retry signals and historical-data retrieval are NOT
implemented here - :class:`RazorpayTestModeAdapter.retry_eligibility` always
raises, and the composite :class:`HybridPaymentProvider` never routes that
call to it (retry eligibility stays simulated).

Every event this module ever produces is stamped ``evidence_mode=
"REAL_TEST_MODE"``. Signature verification here (:func:`_signature_ok`) is a
SEPARATE function over a SEPARATE secret from the simulated ingress's own
HMAC check in ``api.py`` - a locally signed simulated fixture can never verify
against the real Razorpay webhook secret, and vice versa.

No fastapi import here: this module is the verification/business logic only;
``api.py`` (or a future minimal webhook-only app) wires it to an HTTP route.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from .engine import RecoveryEngine
from .types import CaptureInfo, CaseQuery, RazorpayWebhook, WebhookType

_TEST_KEY_PREFIX = "rzp_test_"
_HEX_SHA256 = re.compile(r"\A[0-9a-fA-F]{64}\Z")
_REFERENCE_PREFIX = "hermes-"
_MAX_REFERENCE_LEN = 40  # Razorpay's own documented reference_id limit
_PAID_EVENT = "payment_link.paid"


def _looks_like_test_key(key_id: str) -> bool:
    return isinstance(key_id, str) and key_id.startswith(_TEST_KEY_PREFIX)


def reference_id_for(case_id: str) -> str:
    """Deterministic, stable ``reference_id`` for this case's ONE recovery
    link. Raises rather than silently truncating if it would exceed
    Razorpay's documented 40-character limit."""
    ref = f"{_REFERENCE_PREFIX}{case_id}"
    if len(ref) > _MAX_REFERENCE_LEN:
        raise ValueError(f"reference_id would exceed the {_MAX_REFERENCE_LEN}-char limit: {ref!r}")
    return ref


def case_id_from_reference(reference_id: str) -> str | None:
    if not isinstance(reference_id, str) or not reference_id.startswith(_REFERENCE_PREFIX):
        return None
    return reference_id[len(_REFERENCE_PREFIX):]


def _signature_ok(secret: str, raw: bytes, provided: str | None) -> bool:
    """Constant-time HMAC-SHA256 check over the exact raw request bytes -
    Razorpay's documented webhook validation algorithm. Deliberately NOT
    shared code with ``api.py``'s simulated-ingress check: two independent
    implementations over two independent secrets, so neither can be confused
    for the other even by a future refactor."""
    if not isinstance(provided, str) or not _HEX_SHA256.match(provided):
        return False
    expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided)


class _AmbiguousCompletion(Exception):
    """The POST may or may not have reached Razorpay (e.g. a timeout/connection
    reset after the request was sent). Never safe to assume success OR to
    blindly retry with a fresh reference - the caller must reconcile or stop."""


def _live_post(url: str, *, auth: tuple[str, str], json_body: dict) -> dict:
    body = json.dumps(json_body).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                  headers={"Content-Type": "application/json"})
    _basic_auth(req, auth)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except TimeoutError as exc:
        raise _AmbiguousCompletion(str(type(exc).__name__)) from exc
    except OSError as exc:  # connection reset, broken pipe, etc. - ambiguous
        raise _AmbiguousCompletion(str(type(exc).__name__)) from exc


def _live_get(url: str, *, auth: tuple[str, str]) -> dict:
    req = urllib.request.Request(url, method="GET")
    _basic_auth(req, auth)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _basic_auth(req: urllib.request.Request, auth: tuple[str, str]) -> None:
    import base64

    token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode("utf-8")).decode("ascii")
    req.add_header("Authorization", f"Basic {token}")


class RazorpayTestModeAdapter:
    """Real Razorpay Test Mode calls behind the ``PaymentProvider`` seam.

    Disabled by default (``enabled=False``): every method that would make a
    network call raises instead. A non-``rzp_test_`` key id is rejected at
    construction, before any request is possible - live credentials can never
    reach this adapter even if ``enabled`` is mistakenly set.
    """

    def __init__(
        self, key_id: str, key_secret: str, *, enabled: bool = False,
        http_post: "Callable[..., dict] | None" = None,
        http_get: "Callable[..., dict] | None" = None,
    ) -> None:
        if not _looks_like_test_key(key_id):
            raise ValueError(
                "RazorpayTestModeAdapter requires a Test Mode key id "
                f"(starting with {_TEST_KEY_PREFIX!r}); refusing non-test credentials"
            )
        self._key_id = key_id
        self._key_secret = key_secret
        self._enabled = bool(enabled)
        self._post = http_post or _live_post
        self._get = http_get or _live_get
        self._links: dict[str, dict] = {}      # case_id -> link record
        self._pending: dict[str, dict] = {}     # obligation_id -> claimed capture

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise RuntimeError(
                "Razorpay Test Mode integration is disabled; set enabled=True "
                "(RAZORPAY_TEST_MODE_ENABLED=1) to allow real API calls"
            )

    # -- PaymentProvider protocol -----------------------------------------

    def retry_eligibility(self, obligation_id: str):
        raise NotImplementedError(
            "native Razorpay subscription-retry signals are not implemented in "
            "this hybrid slice; retry eligibility stays simulated - the "
            "HybridPaymentProvider must never route this call here"
        )

    def create_recovery_link(
        self, case_id: str, idempotency_key: str,
        *, amount_minor: int | None = None, currency: str | None = None,
    ) -> str:
        self._require_enabled()
        if amount_minor is None or currency is None:
            raise ValueError("create_recovery_link requires amount_minor and currency")
        existing = self._links.get(case_id)
        if existing is not None:
            return existing["link_id"]  # idempotent within this process's lifetime
        reference_id = reference_id_for(case_id)
        body = {
            "reference_id": reference_id,
            "amount": amount_minor,
            "currency": currency,
            "accept_partial": False,
            "description": f"Recovery link for {case_id}",
            "notify": {"sms": False, "email": False},
            "reminder_enable": False,
        }
        try:
            resp = self._post(
                "https://api.razorpay.com/v1/payment_links",
                auth=(self._key_id, self._key_secret), json_body=body,
            )
        except _AmbiguousCompletion as exc:
            # Never mint a second reference_id and re-POST: that risks two
            # live links (duplicate collection). Stop with a clear, actionable
            # message; an operator reconciles via the Razorpay dashboard using
            # THIS reference_id before any retry.
            raise RuntimeError(
                f"payment link creation for reference_id={reference_id!r} did "
                "not confirm completion (ambiguous network failure); reconcile "
                "manually via the Razorpay Test Mode dashboard - do not retry "
                "with a new reference"
            ) from exc
        link_id = resp.get("id")
        if not isinstance(link_id, str) or not link_id:
            raise RuntimeError("payment link creation response missing an id")
        self._links[case_id] = {
            "link_id": link_id, "reference_id": reference_id,
            "url": resp.get("short_url"),
            "amount_minor": amount_minor, "currency": currency,
        }
        return link_id

    def link_url(self, case_id: str) -> str | None:
        """Not part of the ``PaymentProvider`` protocol - the engine reads it
        via ``getattr`` when present. Kept distinct from ``create_recovery_link``'s
        return value (the provider's own link id), never conflated."""
        entry = self._links.get(case_id)
        return entry["url"] if entry else None

    def record_capture(
        self, obligation_id: str, payment_id: str, amount_minor: int,
        *, link_id: str | None = None,
    ) -> None:
        self._require_enabled()
        self._pending[obligation_id] = {
            "payment_id": payment_id, "amount_minor": amount_minor, "link_id": link_id,
        }

    def verify_capture(self, obligation_id: str) -> CaptureInfo | None:
        """Independent Razorpay readback - never trusts the caller's claimed
        amount, only what THIS fetch returns. Any fetch failure or a status
        other than ``captured`` rejects (returns ``None``), never guesses."""
        self._require_enabled()
        pending = self._pending.get(obligation_id)
        if pending is None:
            return None
        try:
            payment = self._get(
                f"https://api.razorpay.com/v1/payments/{pending['payment_id']}",
                auth=(self._key_id, self._key_secret),
            )
        except Exception:  # noqa: BLE001 - unverified -> reject, never invent
            return None
        if payment.get("status") != "captured":
            return None
        amount = payment.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, int):
            return None
        currency = payment.get("currency")
        return CaptureInfo(
            obligation_id=obligation_id, payment_id=pending["payment_id"],
            amount_minor=amount, currency=currency if isinstance(currency, str) else None,
            link_id=pending.get("link_id"),
        )


class HybridPaymentProvider:
    """Composite ``PaymentProvider``: retry eligibility stays SIMULATED
    (``simulated``); recovery-link creation and payment confirmation are
    genuine Razorpay Test Mode calls (``real``). Provider selection is
    independent of which Hermes/Gemini strategist mode is running."""

    def __init__(self, simulated: Any, real: RazorpayTestModeAdapter) -> None:
        self._simulated = simulated
        self._real = real

    def retry_eligibility(self, obligation_id: str):
        return self._simulated.retry_eligibility(obligation_id)

    def set_retry_eligibility(self, obligation_id: str, eligible: bool) -> None:
        """Not a protocol method - forwarded so the demo bootstrap / restart
        reconstruction (which only knows about the simulated half) still
        works unchanged against a hybrid-wired app."""
        self._simulated.set_retry_eligibility(obligation_id, eligible)

    def create_recovery_link(
        self, case_id: str, idempotency_key: str,
        *, amount_minor: int | None = None, currency: str | None = None,
    ) -> str:
        return self._real.create_recovery_link(
            case_id, idempotency_key, amount_minor=amount_minor, currency=currency,
        )

    def link_url(self, case_id: str) -> str | None:
        return self._real.link_url(case_id)

    def record_capture(
        self, obligation_id: str, payment_id: str, amount_minor: int,
        *, link_id: str | None = None,
    ) -> None:
        return self._real.record_capture(obligation_id, payment_id, amount_minor, link_id=link_id)

    def verify_capture(self, obligation_id: str) -> CaptureInfo | None:
        return self._real.verify_capture(obligation_id)


class RealWebhookError(Exception):
    """Carries an HTTP status code + a fixed, non-sensitive detail string. The
    HTTP layer (``api.py``) translates this to ``HTTPException`` - never any
    caller-supplied value is echoed."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def handle_payment_link_paid_webhook(
    *, engine: RecoveryEngine, provider: Any, webhook_secret: str,
    raw: bytes, signature: str | None, event_id: str | None,
) -> dict:
    """Verify + process ONE genuine ``payment_link.paid`` webhook.

    Order matches the simulated ingress's own discipline: signature over the
    UNTOUCHED raw bytes first (before any JSON parsing), then the event id,
    then shape validation, then case correlation, then an independent
    provider readback, and only then ``engine.receive`` - the one path that
    can mark a case ``recovered``. Rejects (raises :class:`RealWebhookError`)
    on any unverified, mismatched, unrelated, or partial payment.
    """
    if not _signature_ok(webhook_secret, raw, signature):
        raise RealWebhookError(401, "invalid signature")
    if not event_id or not event_id.strip():
        raise RealWebhookError(400, "missing X-Razorpay-Event-Id")
    try:
        body = json.loads(raw)
    except (ValueError, TypeError):
        raise RealWebhookError(400, "malformed JSON body")
    if not isinstance(body, dict) or body.get("event") != _PAID_EVENT:
        raise RealWebhookError(422, f"only {_PAID_EVENT!r} is handled here")

    try:
        payload = body["payload"]
        link_entity = payload["payment_link"]["entity"]
        payment_entity = payload["payment"]["entity"]
    except (KeyError, TypeError):
        raise RealWebhookError(422, "malformed payment_link.paid envelope")

    reference_id = link_entity.get("reference_id")
    link_id = link_entity.get("id")
    payment_id = payment_entity.get("id")
    claimed_amount = payment_entity.get("amount")
    if (
        not isinstance(reference_id, str) or not isinstance(link_id, str)
        or not isinstance(payment_id, str)
        or isinstance(claimed_amount, bool) or not isinstance(claimed_amount, int)
    ):
        raise RealWebhookError(422, "malformed payment_link.paid envelope")

    case_id = case_id_from_reference(reference_id)
    if case_id is None:
        raise RealWebhookError(422, "unrecognised reference_id")

    try:
        case = engine.inspect(CaseQuery(case_id=case_id))
    except KeyError:
        raise RealWebhookError(404, "unknown case")

    stored_ref = next(
        (i.reference for i in case.action_intents
         if i.action == "CREATE_RECOVERY_LINK" and i.reference), None,
    )
    if stored_ref is None or stored_ref != link_id:
        # The link this webhook claims to be about is not the one WE created
        # and persisted for this case - reject rather than trust the claim.
        raise RealWebhookError(409, "link does not match this case's authorized recovery link")

    provider.record_capture(case.obligation_id, payment_id, claimed_amount, link_id=link_id)
    capture = provider.verify_capture(case.obligation_id)
    if capture is None:
        raise RealWebhookError(409, "payment could not be independently verified with the provider")
    if capture.amount_minor != case.amount_minor or (
        capture.currency is not None and capture.currency != case.currency
    ):
        raise RealWebhookError(409, "payment amount/currency does not match this case's obligation")

    webhook = RazorpayWebhook(
        event_id=event_id, type=WebhookType.PAYMENT_CAPTURED,
        obligation_id=case.obligation_id, amount_minor=capture.amount_minor,
        currency=capture.currency or case.currency, payment_id=capture.payment_id,
        evidence_mode="REAL_TEST_MODE", link_id=capture.link_id,
        consent=False, reachable_channel=False, customer_notify=False,
    )
    result = engine.receive(webhook)
    return {
        "accepted": result.accepted, "duplicate": result.duplicate,
        "case_id": result.case_id, "event_id": event_id,
        "evidence_mode": "REAL_TEST_MODE",
    }


@dataclass(frozen=True)
class RazorpayCredentials:
    key_id: str
    key_secret: str
    webhook_secret: str
    enabled: bool = False


def load_credentials(env: dict) -> RazorpayCredentials | None:
    """Read Test Mode credentials from an env mapping (the caller supplies
    ``os.environ`` after ``.env`` is loaded) - never from a file read here,
    never printed. Returns ``None`` if any of the three secrets is absent
    (hybrid mode then cannot be built). Raises ``ValueError`` for a present but
    non-Test-Mode key id - rejected before any adapter is constructed."""
    key_id = env.get("RAZORPAY_KEY_ID", "").strip()
    key_secret = env.get("RAZORPAY_KEY_SECRET", "").strip()
    webhook_secret = env.get("RAZORPAY_WEBHOOK_SECRET", "").strip()
    if not key_id and not key_secret and not webhook_secret:
        return None
    missing = [
        name for name, val in
        (("RAZORPAY_KEY_ID", key_id), ("RAZORPAY_KEY_SECRET", key_secret),
         ("RAZORPAY_WEBHOOK_SECRET", webhook_secret))
        if not val
    ]
    if missing:
        raise ValueError(
            "hybrid_test_mode provider requires " + ", ".join(missing)
            + " in the environment or root .env (values are never printed)"
        )
    if not _looks_like_test_key(key_id):
        raise ValueError(
            f"RAZORPAY_KEY_ID must be a Test Mode key (starting with {_TEST_KEY_PREFIX!r}); "
            "refusing non-test credentials"
        )
    enabled = env.get("RAZORPAY_TEST_MODE_ENABLED", "").strip().lower() in ("1", "true", "yes")
    return RazorpayCredentials(key_id, key_secret, webhook_secret, enabled=enabled)
