"""Genuine Razorpay Test Mode integration - HYBRID slice.

Scope (see ``RAZORPAY_TEST_SLICE.md``): the simulated SaaS obligation, history,
and accelerated failure/retry sequence are UNCHANGED. Only authorized recovery-
link creation and payment confirmation become real Razorpay Test Mode API
calls. Native subscription-retry signals and historical-data retrieval are NOT
implemented here - :class:`RazorpayTestModeAdapter.retry_eligibility` always
raises, and the composite :class:`HybridPaymentProvider` never routes that
call to it (retry eligibility stays simulated). No messaging adapter exists
either: ``message_delivery_capable`` is ``False`` so the engine never reports
an authorized message as actually sent (see ``engine.run``).

Every event this module ever produces is stamped ``evidence_mode=
"REAL_TEST_MODE"``. Signature verification here (:func:`_signature_ok`) is a
SEPARATE function over a SEPARATE secret from the simulated ingress's own
HMAC check in ``api.py`` - a locally signed simulated fixture can never verify
against the real Razorpay webhook secret, and vice versa.

Capture verification (:func:`RazorpayTestModeAdapter.verify_link_payment`) is
a single, immutable, request-scoped operation: it takes an explicit
:class:`LinkPaymentClaim`, fetches BOTH the payment and its claimed owning
Payment Link independently, and returns evidence built ONLY from what those
two fetches say - never from shared per-instance state keyed by obligation id
(the earlier design's ``record_capture``/``verify_capture`` pair could let a
second, concurrent webhook delivery for the same obligation overwrite the
first's pending claim before it was read back - see ``test_razorpay_test_mode.py``'s
concurrency regressions). ``record_capture``/``verify_capture`` remain on this
adapter only to satisfy the ``PaymentProvider`` protocol shape; they now raise
- the real webhook path never calls them (``RazorpayWebhook.pre_verified_capture``
carries the already-confirmed evidence straight to ``engine.receive``, so there
is exactly ONE provider fetch per webhook, not two).

No fastapi import here: this module is the verification/business logic only;
``api.py`` (or a future minimal webhook-only app) wires it to an HTTP route.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from .engine import RecoveryEngine
from .types import CaptureInfo, CaseQuery, ProviderActionUncertain, RazorpayWebhook, WebhookType

_TEST_KEY_PREFIX = "rzp_test_"
_HEX_SHA256 = re.compile(r"\A[0-9a-fA-F]{64}\Z")
_ISO_CURRENCY = re.compile(r"\A[A-Z]{3}\Z")
_REFERENCE_PREFIX = "hermes-"
_MAX_REFERENCE_LEN = 40  # Razorpay's own documented reference_id limit
_PAID_EVENT = "payment_link.paid"
_CAPTURED = "captured"
_PAID = "paid"


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
    reset after the request was sent). Internal only - :meth:`create_recovery_link`
    always converts this to :class:`~hermes.types.ProviderActionUncertain`."""


def _live_post(url: str, *, auth: tuple[str, str], json_body: dict) -> dict:
    body = json.dumps(json_body).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                  headers={"Content-Type": "application/json"})
    _basic_auth(req, auth)
    # The request may have reached Razorpay even if reading/decoding the
    # response then fails - a truncated body, invalid encoding, or malformed
    # JSON is exactly as ambiguous as a timeout: we still cannot tell whether
    # a live link was created. Every failure from "sent" onward funnels into
    # the SAME _AmbiguousCompletion -> ProviderActionUncertain path.
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
    except TimeoutError as exc:
        raise _AmbiguousCompletion(str(type(exc).__name__)) from exc
    except OSError as exc:  # connection reset, broken pipe, etc.
        raise _AmbiguousCompletion(str(type(exc).__name__)) from exc
    except http.client.HTTPException as exc:  # e.g. IncompleteRead: truncated body
        raise _AmbiguousCompletion(str(type(exc).__name__)) from exc
    try:
        return json.loads(raw)
    except ValueError as exc:  # JSONDecodeError or UnicodeDecodeError (bad encoding)
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


@dataclass(frozen=True)
class LinkPaymentClaim:
    """Everything needed to independently verify ONE payment against ONE
    Payment Link - built fresh per webhook delivery from OUR OWN trusted case
    data plus the two ids the signed envelope names, never shared or mutated
    across calls. ``expected_*`` fields come from the caller's own persisted
    case, never from the webhook body - they are what the fetched provider
    records must match, not what they are assumed to already say."""

    link_id: str
    payment_id: str
    expected_reference_id: str
    expected_amount_minor: int
    expected_currency: str
    obligation_id: str


class RazorpayTestModeAdapter:
    """Real Razorpay Test Mode calls behind the ``PaymentProvider`` seam.

    Disabled by default (``enabled=False``): every method that would make a
    network call raises instead. A non-``rzp_test_`` key id is rejected at
    construction, before any request is possible - live credentials can never
    reach this adapter even if ``enabled`` is mistakenly set.
    """

    message_delivery_capable = False  # no messaging adapter exists; see engine.run

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
        self._links: dict[str, dict] = {}      # case_id -> link record (local cache only)

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise RuntimeError(
                "Razorpay Test Mode integration is disabled; set enabled=True "
                "(RAZORPAY_TEST_MODE_ENABLED=1) to allow real API calls"
            )

    @property
    def enabled(self) -> bool:
        """Non-secret capability flag - never a credential - safe to surface
        on ``/health`` so a caller (e.g. ``scripts/run_one_hybrid_case.py``)
        can fail closed before attempting a real action."""
        return self._enabled

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
            # live links (duplicate collection). The caller (engine.run)
            # persists an explicit, safe "uncertain" stop for this case's
            # already-recorded action intent - no automatic retry, no
            # replacement link, never marked recovered.
            raise ProviderActionUncertain(
                f"recovery_link_creation_ambiguous:{type(exc).__name__}"
            ) from exc
        link_id = resp.get("id") if isinstance(resp, dict) else None
        if not isinstance(link_id, str) or not link_id:
            # A malformed/incomplete response is exactly as uncertain as a
            # network failure - we cannot tell whether a live link exists.
            raise ProviderActionUncertain("recovery_link_creation_malformed_response")
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
        raise NotImplementedError(
            "superseded by verify_link_payment (one immutable, request-scoped "
            "readback of both the payment and its link) - the real webhook "
            "path never calls this"
        )

    def verify_capture(self, obligation_id: str) -> CaptureInfo | None:
        raise NotImplementedError(
            "superseded by verify_link_payment (one immutable, request-scoped "
            "readback of both the payment and its link) - the real webhook "
            "path never calls this"
        )

    def verify_link_payment(self, claim: LinkPaymentClaim) -> CaptureInfo | None:
        """Independent, single-shot readback for ONE claim: fetches the
        payment AND its claimed owning Payment Link, and accepts only if
        EVERY one of the following holds - any failure rejects (returns
        ``None``), never guesses:

        - both fetches succeed and return the expected top-level shape;
        - the link's own fetched ``id`` == ``claim.link_id`` (not merely the
          id we asked for - a defensive echo check);
        - the link's own fetched ``reference_id`` == ``claim.expected_reference_id``
          (the case correlation, confirmed from the PROVIDER's record, not
          just the signed webhook body);
        - the link's own ``status`` == ``"paid"``, its ``amount``/``currency``
          match exactly;
        - the payment's own fetched ``id`` == ``claim.payment_id``, its
          ``status`` == ``"captured"``, its ``amount``/``currency`` match
          exactly;
        - the link's own ``payments`` list (Razorpay's documented per-link
          payment history) contains an entry for THIS payment id, itself
          ``captured`` at the expected amount - the actual evidence that this
          payment belongs to this link, not merely two separately-plausible
          records.

        Every currency is required and compared as an exact string - a
        missing or wrong-typed currency fails the match, it is never treated
        as "no evidence" and quietly waved through.
        """
        self._require_enabled()
        try:
            link = self._get(
                f"https://api.razorpay.com/v1/payment_links/{claim.link_id}",
                auth=(self._key_id, self._key_secret),
            )
            payment = self._get(
                f"https://api.razorpay.com/v1/payments/{claim.payment_id}",
                auth=(self._key_id, self._key_secret),
            )
        except Exception:  # noqa: BLE001 - unverified -> reject, never invent
            return None
        if not isinstance(link, dict) or not isinstance(payment, dict):
            return None

        if not self._link_matches(link, claim):
            return None
        if not self._payment_matches(payment, claim):
            return None
        if not self._payment_is_on_link(link, claim):
            return None

        return CaptureInfo(
            obligation_id=claim.obligation_id, payment_id=claim.payment_id,
            amount_minor=claim.expected_amount_minor, currency=claim.expected_currency,
            link_id=claim.link_id,
        )

    @staticmethod
    def _link_matches(link: dict, claim: LinkPaymentClaim) -> bool:
        return (
            link.get("id") == claim.link_id
            and link.get("reference_id") == claim.expected_reference_id
            and link.get("status") == _PAID
            and link.get("amount") == claim.expected_amount_minor
            and link.get("currency") == claim.expected_currency
        )

    @staticmethod
    def _payment_matches(payment: dict, claim: LinkPaymentClaim) -> bool:
        return (
            payment.get("id") == claim.payment_id
            and payment.get("status") == _CAPTURED
            and payment.get("amount") == claim.expected_amount_minor
            and payment.get("currency") == claim.expected_currency
        )

    @staticmethod
    def _payment_is_on_link(link: dict, claim: LinkPaymentClaim) -> bool:
        """The actual "this payment belongs to this link" evidence: the
        link's own ``payments`` array must list this payment id, itself
        captured at the expected amount. A matching payment id alone (with a
        mismatched status/amount in the link's own record of it) is NOT
        sufficient - the link's bookkeeping must agree too."""
        entries = link.get("payments")
        if not isinstance(entries, list):
            return False
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("payment_id") != claim.payment_id:
                continue
            return (
                entry.get("status") == _CAPTURED
                and entry.get("amount") == claim.expected_amount_minor
            )
        return False


class HybridPaymentProvider:
    """Composite ``PaymentProvider``: retry eligibility stays SIMULATED
    (``simulated``); recovery-link creation and payment confirmation are
    genuine Razorpay Test Mode calls (``real``). Provider selection is
    independent of which Hermes/Gemini strategist mode is running."""

    def __init__(self, simulated: Any, real: RazorpayTestModeAdapter) -> None:
        self._simulated = simulated
        self._real = real
        self.message_delivery_capable = real.message_delivery_capable
        self.test_mode_enabled = real.enabled  # non-secret capability flag

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

    def verify_link_payment(self, claim: LinkPaymentClaim) -> CaptureInfo | None:
        return self._real.verify_link_payment(claim)


class RealWebhookError(Exception):
    """Carries an HTTP status code + a fixed, non-sensitive detail string. The
    HTTP layer (``api.py``) translates this to ``HTTPException`` - never any
    caller-supplied value is echoed."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _entity_str(d: dict, key: str) -> str | None:
    v = d.get(key)
    return v if isinstance(v, str) and v else None


def _entity_amount(d: dict, key: str) -> int | None:
    v = d.get(key)
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        return None
    return v


def _entity_currency(d: dict, key: str) -> str | None:
    v = d.get(key)
    return v if isinstance(v, str) and _ISO_CURRENCY.match(v) else None


def handle_payment_link_paid_webhook(
    *, engine: RecoveryEngine, provider: Any, webhook_secret: str,
    raw: bytes, signature: str | None, event_id: str | None,
) -> dict:
    """Verify + process ONE genuine ``payment_link.paid`` webhook.

    Order: signature over the UNTOUCHED raw bytes first (before any JSON
    parsing), then the event id, then full envelope shape/type validation
    (every required id/status/amount/currency present and correctly typed -
    a malformed envelope raises a controlled :class:`RealWebhookError`, never
    an uncaught exception), then the envelope's OWN claimed statuses (link
    ``paid``, payment ``captured``), then a same-envelope cross-check (the
    link's own claimed amount/currency must agree with the payment's -
    contradictory signed facts are rejected before any provider call), then
    - once the case is resolved - that the envelope's amount/currency also
    agree with the PERSISTED obligation (agreeing with each other on the
    wrong number is not enough), then this case's own persisted link
    correlation, then ONE independent provider readback
    (:meth:`RazorpayTestModeAdapter.verify_link_payment`, which re-confirms
    status/amount/currency against the SAME persisted obligation from the
    provider's own records), and only then ``engine.receive`` - the one path
    that can mark a case ``recovered``, still running every ledger validation
    (dedup, terminal-state, version, atomic finalization) unchanged. Rejects
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
    if not isinstance(link_entity, dict) or not isinstance(payment_entity, dict):
        raise RealWebhookError(422, "malformed payment_link.paid envelope")

    reference_id = _entity_str(link_entity, "reference_id")
    link_id = _entity_str(link_entity, "id")
    link_status = _entity_str(link_entity, "status")
    link_amount = _entity_amount(link_entity, "amount")
    link_currency = _entity_currency(link_entity, "currency")
    payment_id = _entity_str(payment_entity, "id")
    payment_status = _entity_str(payment_entity, "status")
    payment_amount = _entity_amount(payment_entity, "amount")
    payment_currency = _entity_currency(payment_entity, "currency")
    required = (reference_id, link_id, link_status, link_amount, link_currency,
                payment_id, payment_status, payment_amount, payment_currency)
    if any(v is None for v in required):
        raise RealWebhookError(422, "malformed payment_link.paid envelope")

    # The signed envelope must itself claim the paid/captured statuses this
    # route exists to handle - a missing or different status is rejected
    # here, not left for the provider readback to catch alone.
    if link_status != _PAID or payment_status != _CAPTURED:
        raise RealWebhookError(422, "signed envelope status is not paid/captured")

    # Contradictory signed facts, rejected BEFORE any provider call: the
    # link's own claimed amount/currency must agree with the payment's.
    if link_amount != payment_amount or link_currency != payment_currency:
        raise RealWebhookError(
            422, "contradictory link/payment amount or currency in the signed envelope"
        )

    case_id = case_id_from_reference(reference_id)
    if case_id is None:
        raise RealWebhookError(422, "unrecognised reference_id")

    try:
        case = engine.inspect(CaseQuery(case_id=case_id))
    except KeyError:
        raise RealWebhookError(404, "unknown case")

    # The envelope's own (mutually-agreeing) amount/currency must ALSO agree
    # with the persisted obligation - internal agreement alone is not enough
    # if both entities simply agree on the WRONG number. This still isn't
    # the source of truth (the independent provider readback below is) but a
    # webhook that already contradicts our own case data is rejected without
    # spending a provider round trip on it.
    if link_amount != case.amount_minor or link_currency != case.currency:
        raise RealWebhookError(
            409, "signed envelope amount/currency does not match this case's obligation"
        )

    stored_ref = next(
        (i.reference for i in case.action_intents
         if i.action == "CREATE_RECOVERY_LINK" and i.reference), None,
    )
    if stored_ref is None or stored_ref != link_id:
        # The link this webhook claims to be about is not the one WE created
        # and persisted for this case - reject rather than trust the claim.
        raise RealWebhookError(409, "link does not match this case's authorized recovery link")

    claim = LinkPaymentClaim(
        link_id=link_id, payment_id=payment_id,
        expected_reference_id=reference_id_for(case_id),
        expected_amount_minor=case.amount_minor, expected_currency=case.currency,
        obligation_id=case.obligation_id,
    )
    capture = provider.verify_link_payment(claim)
    if capture is None:
        raise RealWebhookError(
            409, "payment could not be independently verified against the provider"
        )

    webhook = RazorpayWebhook(
        event_id=event_id, type=WebhookType.PAYMENT_CAPTURED,
        obligation_id=case.obligation_id, amount_minor=capture.amount_minor,
        currency=capture.currency, payment_id=capture.payment_id,
        evidence_mode="REAL_TEST_MODE", link_id=capture.link_id,
        pre_verified_capture=capture,
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
