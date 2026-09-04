"""Explicitly-labelled synthetic fixtures for the runnable Case 3 demo.

Nothing here is real. Merchant consent / channel / history come from these
trusted synthetic fixtures - never from a Razorpay payload field. Payment and
provider effects are simulated and labelled ``SIMULATED``. The webhook envelopes
are signed with a locally generated *demo* secret, never Razorpay's real one.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass

DEMO_SIGNING_SECRET_ENV = "HERMES_DEMO_SIGNING_SECRET"
CASE3_STEP_HOURS = 24  # logical hours each "advance time" step moves the clock

# Audit kind stamped once, server-side, when ``/demo/case`` opens a demo case.
# It is the ONLY proof that a persisted case was created by the trusted demo
# path: restart reconstruction rebuilds merchant context / provider retry facts
# only for cases carrying this record. An obligation-name prefix is never
# trusted - an external payload can invent ``sub_demo_...`` identifiers.
DEMO_PROVENANCE_KIND = "DEMO_CASE_PROVENANCE"


def new_demo_signing_secret() -> str:
    """A fresh local secret for signing *simulated* ingress. Explicitly not the
    Razorpay webhook secret (which stays blank / deferred)."""
    return "demosig_" + secrets.token_hex(16)


def demo_sign(secret: str, raw: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def mint_demo_ids(serial: int) -> tuple[str, str]:
    """Collision-safe ``(obligation_id, run_token)`` for a fresh demo case.

    The obligation id keeps a zero-padded serial prefix (so a restart can
    reconstruct "next serial" from existing ids) plus a random suffix, so even
    a serial counter that was reset in a new process cannot reuse an id.
    """
    token = secrets.token_hex(4)
    return f"sub_demo_{serial:04d}_{token}", token


def demo_serial_of(obligation_id: str) -> int | None:
    """Extract the serial prefix from an obligation id minted by
    :func:`mint_demo_ids` (or the legacy ``sub_demo_NNNN`` form)."""
    m = re.match(r"\Asub_demo_(\d{1,9})(?:_|\Z)", obligation_id)
    return int(m.group(1)) if m else None


@dataclass(frozen=True)
class MerchantContext:
    """A trusted synthetic merchant-context record. ``source`` labels it so it
    can never be confused with provider data. Absent -> contact stays denied."""

    obligation_id: str
    consent: bool
    reachable_channel: bool
    customer_notify: bool  # True => Razorpay owns customer communication
    source: str = "SYNTHETIC_DEMO_FIXTURE"
    payment_history: str = "ordinary"


def case3_merchant_context(obligation_id: str) -> MerchantContext:
    """Case 3: merchant owns communication, customer consented, reachable, with
    an ordinary (non-outlier) payment history."""
    return MerchantContext(
        obligation_id=obligation_id,
        consent=True,
        reachable_channel=True,
        customer_notify=False,
        source="SYNTHETIC_DEMO_FIXTURE:case3-insufficient-funds",
        payment_history="ordinary - two prior on-time payments, first failure",
    )


CASE3_AMOUNT_MINOR = 1_000_000  # INR 10,000
CASE3_CURRENCY = "INR"
CASE3_REASON = "insufficient_funds"


def failure_envelope(
    obligation_id: str, *, payment_id: str, amount_minor: int = CASE3_AMOUNT_MINOR,
    currency: str = CASE3_CURRENCY, reason: str = CASE3_REASON,
) -> dict:
    return {
        "event": "payment.failed",
        "payload": {
            "payment": {"entity": {"id": payment_id, "amount": amount_minor,
                                   "currency": currency, "error_description": reason}},
            "subscription": {"entity": {"id": obligation_id}},
        },
    }


def capture_envelope(
    obligation_id: str, *, payment_id: str, amount_minor: int = CASE3_AMOUNT_MINOR,
    currency: str = CASE3_CURRENCY,
) -> dict:
    return {
        "event": "payment.captured",
        "payload": {
            "payment": {"entity": {"id": payment_id, "amount": amount_minor,
                                   "currency": currency}},
            "subscription": {"entity": {"id": obligation_id}},
        },
    }
