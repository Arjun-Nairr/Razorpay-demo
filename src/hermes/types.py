"""Typed data passed across the RecoveryEngine seam.

Logical time is an integer count of logical hours on a monotonic clock. It is
never wall-clock time in this slice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# --- Provider input -------------------------------------------------------------

# Trusted fake webhooks only: no HMAC verification in this slice (out of scope).


class WebhookType(StrEnum):
    PAYMENT_FAILED = "payment.failed"
    PAYMENT_CAPTURED = "payment.captured"


@dataclass(frozen=True)
class RazorpayWebhook:
    """A trusted, already-verified provider event."""

    event_id: str  # provider event id; processed at most once
    type: WebhookType
    obligation_id: str  # the subscription/invoice payment obligation
    amount_minor: int  # integer minor units (paise); e.g. 1_000_000 == INR 10,000
    currency: str = "INR"
    reason_code: str | None = None  # failure class, e.g. "bank_temporary_error"
    payment_id: str | None = None  # set on captured events


# --- AI proposal contract -----------------------------------------------------


class ProposalAction(StrEnum):
    WAIT_FOR_PROVIDER_RETRY = "WAIT_FOR_PROVIDER_RETRY"
    SEND_REMINDER = "SEND_REMINDER"
    REQUEST_PAYMENT_METHOD_UPDATE = "REQUEST_PAYMENT_METHOD_UPDATE"
    CREATE_RECOVERY_LINK = "CREATE_RECOVERY_LINK"
    RECOMMEND_STRUCTURAL_CHANGE = "RECOMMEND_STRUCTURAL_CHANGE"
    TAKE_NO_ACTION = "TAKE_NO_ACTION"
    STOP = "STOP"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class StrategyProposal:
    """One typed strategy proposal from the AI strategist.

    The strategist may not supply amounts, identifiers, URLs, or limits.
    """

    action: ProposalAction
    diagnosis: str
    rationale: str
    confidence: float
    proposed_wait_hours: int = 0  # relative, only meaningful for WAIT_FOR_PROVIDER_RETRY


# --- Deterministic policy ----------------------------------------------------


class PolicyOutcome(StrEnum):
    ALLOW = "ALLOW"
    REPLACE = "REPLACE"
    BLOCK = "BLOCK"
    STOP = "STOP"
    ESCALATE = "ESCALATE"
    EXHAUST = "EXHAUST"


@dataclass(frozen=True)
class PolicyDecision:
    outcome: PolicyOutcome
    reason_code: str
    scheduled_time: int | None = None  # logical hour to re-evaluate, when ALLOW


# --- Engine results ----------------------------------------------------------


@dataclass(frozen=True)
class ReceiveResult:
    accepted: bool
    duplicate: bool
    case_id: str | None


@dataclass(frozen=True)
class RunReport:
    logical_time: int
    steps: int
    proposals: int


# --- Case states -----------------------------------------------------------

TERMINAL_STATES: frozenset[str] = frozenset(
    {"recovered", "stopped", "escalated", "exhausted"}
)


class CaseState(StrEnum):
    ACTIVE = "active"
    WAITING = "waiting"
    RECOVERED = "recovered"
    STOPPED = "stopped"
    ESCALATED = "escalated"
    EXHAUSTED = "exhausted"


@dataclass
class Case:
    case_id: str
    obligation_id: str
    amount_minor: int
    currency: str
    created_time: int
    state: CaseState = CaseState.ACTIVE
    counted: bool = False  # recovered value contributed exactly once
    linked_payment_id: str | None = None
    version: int = 0


@dataclass
class ScheduledWork:
    work_id: str
    case_id: str
    due_time: int
    kind: str = "evaluate"
    cancelled: bool = False


@dataclass(frozen=True)
class AuditEvent:
    seq: int
    logical_time: int
    case_id: str
    kind: str
    detail: dict = field(default_factory=dict)


# Audit event kinds (append-only trail).
AUDIT_INPUT_EVENT = "INPUT_EVENT"
AUDIT_AI_PROPOSAL = "AI_PROPOSAL"
AUDIT_POLICY_DECISION = "POLICY_DECISION"
AUDIT_SCHEDULED_ACTION = "SCHEDULED_ACTION"
AUDIT_PAYMENT_CONFIRMATION = "PAYMENT_CONFIRMATION"
AUDIT_PENDING_WORK_CANCELLED = "PENDING_WORK_CANCELLED"
AUDIT_TERMINAL_TRANSITION = "TERMINAL_TRANSITION"
