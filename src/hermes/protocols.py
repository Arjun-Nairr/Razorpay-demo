"""Narrow structural interfaces the RecoveryEngine depends on.

The engine imports only these Protocols - never ``InMemoryLedger``,
``FakeRazorpayAdapter``, or ``ScriptedStrategist``. A future Neon ledger or real
Razorpay adapter just has to satisfy the same shape.
"""

from __future__ import annotations

from typing import Protocol, Sequence

from .types import (
    ActionIntentOutcomeCommand,
    ActionIntentUncertainCommand,
    ApplyResult,
    AuditProjection,
    BatchProjection,
    CaptureCommand,
    CaptureInfo,
    CaseProjection,
    CaseSnapshot,
    DeliveryReceipt,
    DiscardWorkCommand,
    EvaluationCommand,
    IntakeCommand,
    IntakeResult,
    MessageDeliveryCommand,
    NoteEventCommand,
    ProviderRetryFact,
    StrategistFailureCommand,
    StrategyProposal,
    StrategySnapshot,
    WorkClaim,
)


class Strategist(Protocol):
    def propose(self, snapshot: StrategySnapshot) -> StrategyProposal: ...


class PaymentProvider(Protocol):
    def retry_eligibility(self, obligation_id: str) -> ProviderRetryFact: ...

    def record_capture(
        self, obligation_id: str, payment_id: str, amount_minor: int,
        *, link_id: str | None = None,
    ) -> None: ...

    def verify_capture(self, obligation_id: str) -> CaptureInfo | None: ...

    def create_recovery_link(
        self, case_id: str, idempotency_key: str,
        *, amount_minor: int | None = None, currency: str | None = None,
    ) -> str: ...
    # Deterministic fake executor: the SAME idempotency_key always returns the
    # SAME simulated, uniquely correlated reference - never a real Razorpay call
    # by default. ``amount_minor``/``currency`` come from the engine's trusted
    # case snapshot (never the model); a real adapter needs them to create an
    # actual Payment Link and requires both. Returns the provider's own
    # correlation id (a real adapter returns its Payment Link id, e.g.
    # "plink_..." - never a payment id).


class MessageDeliveryAdapter(Protocol):
    """Real customer-message delivery - a seam entirely separate from
    ``PaymentProvider``. Telegram is the first (and, this milestone, only)
    implementation. ``text`` is already fully constructed by deterministic
    code (approved template + confirmed checkout URL, added only at the
    delivery boundary) - an adapter never sees or builds the URL itself, and
    never receives Hermes's raw proposal. Disabled/unconfigured
    implementations must return a ``DeliveryReceipt`` with outcome
    ``"failed"`` - never silently claim delivery."""

    def deliver(self, *, text: str) -> DeliveryReceipt: ...


class Ledger(Protocol):
    # -- persisted logical clock -----------------------------------------
    def logical_clock(self) -> int: ...
    # The last advanced logical hour. Survives process restart for a durable
    # ledger; the engine reads this at construction so demo time is not lost.

    def advance_clock(self, now: int) -> None: ...
    # Monotonic: `now` must be >= the current value. Persisted atomically.

    # -- reads --------------------------------------------------------------
    def has_seen_event(self, event_id: str) -> bool: ...

    def case_id_for_obligation(self, obligation_id: str) -> str | None: ...

    def case_snapshot(self, case_id: str) -> CaseSnapshot: ...

    def case_ids(self) -> Sequence[str]: ...
    # Every case id currently in the ledger. Used only to reconstruct demo /
    # provider state after a restart; not part of the recovery workflow.

    def claim_due_work(self, now: int) -> Sequence[WorkClaim]: ...
    # Claims at most one due item per call; a live lease is never stolen.

    # -- transactions (immutable commands in, results out) -----------------
    def apply_intake(self, cmd: IntakeCommand) -> IntakeResult: ...
    # Atomic: dedup + one-case-per-obligation + event record + audit + initial
    # work enqueue, all in one transaction.

    def mark_event_seen(self, event_id: str) -> None: ...

    def note_event(self, cmd: NoteEventCommand) -> None: ...

    def apply_evaluation(self, cmd: EvaluationCommand) -> ApplyResult: ...

    def apply_strategist_failure(self, cmd: StrategistFailureCommand) -> ApplyResult: ...

    def apply_capture(self, cmd: CaptureCommand) -> ApplyResult: ...

    def apply_action_outcome(self, cmd: ActionIntentOutcomeCommand) -> ApplyResult: ...
    # Idempotent: replaying an already-``executed`` intent_id is a no-op.

    def apply_action_intent_uncertain(self, cmd: ActionIntentUncertainCommand) -> ApplyResult: ...
    # Safe stop for a ``ProviderActionUncertain`` (or a still-``pending``
    # intent found at startup): marks the intent ``uncertain`` and the case
    # ``escalated`` - idempotent, never recovered, never retried automatically.

    def apply_message_delivery(self, cmd: MessageDeliveryCommand) -> ApplyResult: ...
    # Records one real delivery attempt (any outcome). Idempotent: a replay
    # against an intent already ``sent`` is a no-op - never a second message.

    def discard_work(self, cmd: DiscardWorkCommand) -> ApplyResult: ...

    # -- ledger-owned projections ----------------------------------------
    def case_projection(
        self, *, case_id: str | None = None, obligation_id: str | None = None
    ) -> CaseProjection: ...

    def batch_projection(self) -> BatchProjection: ...

    def audit_projection(self, case_id: str | None) -> AuditProjection: ...
