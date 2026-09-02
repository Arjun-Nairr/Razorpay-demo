"""Narrow structural interfaces the RecoveryEngine depends on.

The engine imports only these Protocols - never ``InMemoryLedger``,
``FakeRazorpayAdapter``, or ``ScriptedStrategist``. A future Neon ledger or real
Razorpay adapter just has to satisfy the same shape.
"""

from __future__ import annotations

from typing import Protocol, Sequence

from .types import (
    ApplyResult,
    AuditProjection,
    BatchProjection,
    CaptureCommand,
    CaptureInfo,
    CaseProjection,
    CaseSnapshot,
    DiscardWorkCommand,
    EvaluationCommand,
    IntakeCommand,
    IntakeResult,
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
        self, obligation_id: str, payment_id: str, amount_minor: int
    ) -> None: ...

    def verify_capture(self, obligation_id: str) -> CaptureInfo | None: ...


class Ledger(Protocol):
    # -- reads --------------------------------------------------------------
    def has_seen_event(self, event_id: str) -> bool: ...

    def case_id_for_obligation(self, obligation_id: str) -> str | None: ...

    def case_snapshot(self, case_id: str) -> CaseSnapshot: ...

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

    def discard_work(self, cmd: DiscardWorkCommand) -> ApplyResult: ...

    # -- ledger-owned projections ----------------------------------------
    def case_projection(
        self, *, case_id: str | None = None, obligation_id: str | None = None
    ) -> CaseProjection: ...

    def batch_projection(self) -> BatchProjection: ...

    def audit_projection(self, case_id: str | None) -> AuditProjection: ...
