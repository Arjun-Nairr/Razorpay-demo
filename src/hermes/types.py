"""Typed data passed across the RecoveryEngine seam.

Logical time is an integer count of logical hours on a monotonic clock. It is
never wall-clock time in this slice.

Everything the engine hands to a ledger write is an immutable command built from
IDs, claim tokens, and frozen value objects - never a mutable stored ``Case`` or
``ScheduledWork``. Ledger reads return frozen snapshots and projections.
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
    """A trusted, already-verified provider event.

    ``customer_notify``/``consent``/``reachable_channel`` are merchant/account
    facts established at case creation (the first ``payment.failed`` event for
    an obligation) - a real integration would source them from the merchant's
    own system, not the Razorpay payload itself; they travel alongside the
    webhook only because this slice has no separate merchant-context ingress
    yet (out of scope - see IMPLEMENTATION_SPEC.md's FastAPI slice).
    ``evidence_mode`` labels every event ``SIMULATED`` or ``REAL_TEST_MODE`` so
    the two can never be conflated in audit output or metrics.
    """

    event_id: str  # provider event id; processed at most once
    type: WebhookType
    obligation_id: str  # the subscription/invoice payment obligation
    amount_minor: int  # integer minor units (paise); e.g. 1_000_000 == INR 10,000
    currency: str = "INR"
    reason_code: str | None = None  # failure class, e.g. "bank_temporary_error"
    payment_id: str | None = None  # set on captured events
    customer_notify: bool = False  # True: Razorpay owns customer communication
    consent: bool = True  # merchant-recorded contact consent
    reachable_channel: bool = True  # merchant has a reachable contact channel
    evidence_mode: str = "SIMULATED"  # "SIMULATED" | "REAL_TEST_MODE"


@dataclass(frozen=True)
class ProviderRetryFact:
    """Provider-derived retry eligibility.

    Fail-closed: absent evidence resolves to ``retry_eligible=False`` with
    ``evidence=None``. A wait may be authorized only when the provider gives an
    explicit eligible fact *with* evidence. Neither the AI proposal nor the
    engine may synthesise or override this.
    """

    obligation_id: str
    retry_eligible: bool
    evidence: str | None = None  # provenance of the eligible signal, or None


@dataclass(frozen=True)
class CaptureInfo:
    obligation_id: str
    payment_id: str
    amount_minor: int


def valid_payment_id(value: str | None) -> bool:
    """A usable provider payment id: a non-empty, non-whitespace string."""
    return isinstance(value, str) and value.strip() != ""


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
class StrategySnapshot:
    """Immutable, source-labelled case view handed to the strategist.

    Case 3 additions carry forward prior proposal/policy/outcome evidence and
    remaining communication/action capacity, per IMPLEMENTATION_SPEC.md's
    context contract - never amounts, identifiers, or URLs the strategist
    could echo back.
    """

    case_id: str
    obligation_id: str
    amount_minor: int
    currency: str
    failure_reason: str | None
    state: str
    provider_retry_eligible: bool
    provider_retry_evidence: str | None
    retry_outcome_recorded: bool = False
    communication_owner: str = "merchant"  # "merchant" | "razorpay"
    consent: bool = True
    reachable_channel: bool = True
    messages_sent: int = 0
    links_created: int = 0
    actions_taken: int = 0
    last_contact_time: int | None = None
    messages_remaining: int = 0
    links_remaining: int = 0
    actions_remaining: int = 0
    prior_action: str | None = None  # last proposal's action, across cycles
    prior_policy_outcome: str | None = None  # last policy decision's outcome


@dataclass(frozen=True)
class StrategyProposal:
    """One typed strategy proposal from the AI strategist.

    The strategist may not supply amounts, identifiers, URLs, limits, or
    provider retry eligibility. ``message_intent`` is optional short reminder
    copy only - never a URL, amount, provider identifier, discount, or
    commercial term; policy validates and may still suppress it.
    """

    action: ProposalAction
    diagnosis: str
    rationale: str
    confidence: float
    proposed_wait_hours: int = 0  # relative, only meaningful for WAIT_FOR_PROVIDER_RETRY
    message_intent: str | None = None  # optional reminder copy, CREATE_RECOVERY_LINK/SEND_REMINDER only


class InvalidProposal(Exception):
    """Raised when strategist output is not a usable typed proposal."""


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
    message_authorized: bool = False  # the bundled message_intent specifically cleared policy


# --- Recovery attribution ----------------------------------------------------


class Attribution(StrEnum):
    """Exactly the four outcomes POLICY_SPEC.md defines. Attribution never
    changes payment truth - it only records *why* a case recovered (or did
    not), computed deterministically, never by the strategist.
    """

    PROVIDER_SELF_RECOVERED = "provider_self_recovered"
    HERMES_ASSISTED = "hermes_assisted"
    MERCHANT_MANUAL = "merchant_manual"
    UNRECOVERED = "unrecovered"


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


# --- ledger-internal records (never handed to a ledger write) ---------------


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
    failure_reason: str | None = None
    version: int = 0
    # --- Case 3: adaptation and attribution -----------------------------
    communication_owner: str = "merchant"  # "merchant" | "razorpay"; set at creation
    consent: bool = True
    reachable_channel: bool = True
    evidence_mode: str = "SIMULATED"
    retry_outcome_recorded: bool = False  # a distinct failed retry outcome arrived
    messages_sent: int = 0
    links_created: int = 0
    actions_taken: int = 0
    last_contact_time: int | None = None  # logical hour of the last authorized message
    link_references: frozenset[str] = field(default_factory=frozenset)
    attribution: str | None = None  # one Attribution value, set at termination
    last_proposal_action: str | None = None  # prior-cycle evidence for the next snapshot
    last_policy_outcome: str | None = None


@dataclass
class ScheduledWork:
    work_id: str
    case_id: str
    due_time: int
    kind: str = "evaluate"
    attempts: int = 0  # strategist attempts already spent on this work lineage
    cancelled: bool = False
    consumed: bool = False
    claim_token: str | None = None  # current lease holder
    claim_version: int = 0  # bumped on every (re)lease; stale tokens lose
    claimed_at: int | None = None  # logical hour the current lease was taken


@dataclass(frozen=True)
class AuditEvent:
    seq: int
    logical_time: int
    case_id: str
    kind: str
    detail: dict = field(default_factory=dict)


@dataclass
class ActionIntent:
    """A durable, idempotent record of one authorized effect. Persisted with
    status ``pending`` BEFORE the fake executor runs; ``execute()`` results
    are recorded back onto this same record so a duplicate attempt can never
    create or run the effect twice - see ``idempotency_key``.
    """

    intent_id: str
    case_id: str
    action: str  # ProposalAction value, e.g. "CREATE_RECOVERY_LINK"
    idempotency_key: str
    created_time: int
    status: str = "pending"  # "pending" | "executed"
    reference: str | None = None  # the fake executor's simulated correlation id
    message_sent: bool = False


# Audit event kinds (append-only trail).
AUDIT_INPUT_EVENT = "INPUT_EVENT"
AUDIT_AI_PROPOSAL = "AI_PROPOSAL"
AUDIT_STRATEGIST_FAILURE = "STRATEGIST_FAILURE"
AUDIT_POLICY_DECISION = "POLICY_DECISION"
AUDIT_SCHEDULED_ACTION = "SCHEDULED_ACTION"
AUDIT_PAYMENT_CONFIRMATION = "PAYMENT_CONFIRMATION"
AUDIT_PENDING_WORK_CANCELLED = "PENDING_WORK_CANCELLED"
AUDIT_TERMINAL_TRANSITION = "TERMINAL_TRANSITION"
AUDIT_RETRY_OUTCOME = "RETRY_OUTCOME_RECORDED"  # a failed provider-retry outcome woke the case
AUDIT_ACTION_INTENT = "ACTION_INTENT"  # a durable action intent was persisted, pre-effect
AUDIT_ACTION_OUTCOME = "ACTION_OUTCOME"  # the fake effect executed; intent marked complete


# --- ledger reads: frozen snapshots ---------------------------------------


@dataclass(frozen=True)
class CaseSnapshot:
    case_id: str
    obligation_id: str
    amount_minor: int
    currency: str
    state: str
    failure_reason: str | None
    version: int
    communication_owner: str = "merchant"
    consent: bool = True
    reachable_channel: bool = True
    retry_outcome_recorded: bool = False
    messages_sent: int = 0
    links_created: int = 0
    actions_taken: int = 0
    last_contact_time: int | None = None
    attribution: str | None = None
    prior_action: str | None = None
    prior_policy_outcome: str | None = None


@dataclass(frozen=True)
class WorkClaim:
    """A leased unit of work. The claim is valid only while the ledger's stored
    work still carries this exact ``claim_token`` and ``claim_version``.
    """

    work_id: str
    case_id: str
    kind: str
    due_time: int
    attempts: int
    claim_token: str
    claim_version: int


@dataclass(frozen=True)
class ApplyResult:
    ok: bool  # False when the claim was stale / already finalized
    reason: str = ""
    scheduled: bool = False  # a follow-up work item was created
    blocked: bool = False  # the policy blocked the proposal
    terminal: bool = False  # the case reached a terminal state
    action_intent_id: str | None = None  # set when an intent was created or already existed
    idempotency_key: str | None = None
    should_execute: bool = False  # a FRESH pending intent needs its fake effect run
    message_authorized: bool = False  # the bundled message_intent specifically cleared policy


# --- ledger writes: immutable commands ----------------------------------


@dataclass(frozen=True)
class IntakeCommand:
    """Everything a ``payment.failed`` webhook needs to be admitted atomically:
    dedup, one-case-per-obligation, event recording, audit, and initial-work
    enqueue happen inside a single ledger transaction.

    ``customer_notify``/``consent``/``reachable_channel`` seed the case ONLY
    when this call creates it; a later delivery for an existing case does not
    revise them (merchant facts are established once, at intake).

    A distinct event for a case already ``waiting`` on a provider retry IS
    that retry's failed outcome: the transaction records it and wakes the
    case immediately - see ``Ledger.apply_intake``.
    """

    event_id: str
    obligation_id: str
    amount_minor: int
    currency: str
    reason_code: str | None
    now: int
    customer_notify: bool = False
    consent: bool = True
    reachable_channel: bool = True
    evidence_mode: str = "SIMULATED"


@dataclass(frozen=True)
class IntakeResult:
    case_id: str | None
    duplicate: bool  # the same provider event id was already admitted
    created: bool  # a new case + initial work item was opened by this call
    outcome: str  # "case_opened" | "existing_case" | "retry_outcome_recorded" | "duplicate_event"


@dataclass(frozen=True)
class NoteEventCommand:
    case_id: str
    event_id: str | None
    kind: str
    detail: dict
    now: int


@dataclass(frozen=True)
class EvaluationCommand:
    work_id: str
    claim_token: str
    claim_version: int
    case_id: str
    proposal: StrategyProposal
    decision: PolicyDecision
    now: int


@dataclass(frozen=True)
class StrategistFailureCommand:
    work_id: str
    claim_token: str
    claim_version: int
    case_id: str
    error: str
    now: int


@dataclass(frozen=True)
class DiscardWorkCommand:
    work_id: str
    claim_token: str
    claim_version: int
    case_id: str
    reason: str
    now: int


@dataclass(frozen=True)
class CaptureCommand:
    case_id: str
    event_id: str | None
    payment_id: str
    amount_minor: int
    now: int
    expected_version: int  # case version observed before provider verification
    expected_state: str  # case state observed before provider verification
    evidence_mode: str = "SIMULATED"  # "SIMULATED" | "REAL_TEST_MODE"


@dataclass(frozen=True)
class ActionIntentOutcomeCommand:
    """Records the fake executor's result for an already-persisted, pending
    action intent. Idempotent: replaying the same ``intent_id`` after it is
    already ``executed`` is a no-op - the effect and its counters never
    apply twice.
    """

    intent_id: str
    case_id: str
    now: int
    reference: str  # the fake executor's deterministic, uniquely correlated id
    message_sent: bool


# --- engine results ------------------------------------------------------


@dataclass(frozen=True)
class ReceiveResult:
    accepted: bool
    duplicate: bool
    case_id: str | None


@dataclass(frozen=True)
class RunReport:
    logical_time: int
    steps: int  # work items consumed
    proposals: int  # strategist proposals accepted
    strategist_failures: int = 0  # strategist raised / timed out / returned junk
    scheduled: int = 0  # follow-up work items scheduled
    blocked: int = 0  # proposals the policy blocked
    stale_claims: int = 0  # finalizations rejected because another runner won


# --- inspect: typed queries and projections --------------------------------


@dataclass(frozen=True)
class CaseQuery:
    case_id: str | None = None
    obligation_id: str | None = None


@dataclass(frozen=True)
class BatchQuery:
    pass


@dataclass(frozen=True)
class AuditQuery:
    case_id: str | None = None  # None -> every case


RecoveryQuery = CaseQuery | BatchQuery | AuditQuery


@dataclass(frozen=True)
class ActionIntentProjection:
    intent_id: str
    action: str
    status: str  # "pending" | "executed"
    reference: str | None
    message_sent: bool


@dataclass(frozen=True)
class CaseProjection:
    case_id: str
    obligation_id: str
    state: str
    amount_minor: int
    currency: str
    counted: bool
    linked_payment_id: str | None
    pending_work: int
    version: int
    # --- Case 3: strategy/action state, communication, attribution -----
    retry_outcome_recorded: bool = False
    communication_owner: str = "merchant"
    messages_sent: int = 0
    links_created: int = 0
    actions_taken: int = 0
    attribution: str | None = None
    recovered_minor: int = 0  # this case's own contribution; amount_minor iff counted
    action_intents: tuple[ActionIntentProjection, ...] = ()


@dataclass(frozen=True)
class AuditRecord:
    seq: int
    logical_time: int
    case_id: str
    kind: str
    detail: dict


@dataclass(frozen=True)
class AuditProjection:
    records: tuple[AuditRecord, ...]

    def kinds(self) -> list[str]:
        return [r.kind for r in self.records]


@dataclass(frozen=True)
class BatchProjection:
    cases: int
    recovered_cases: int
    recovered_minor: int
    recovered_payments: int


RecoveryView = CaseProjection | BatchProjection | AuditProjection
