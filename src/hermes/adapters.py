"""Deterministic in-memory implementations of the engine's three seams.

These are permanent test infrastructure: the fake payment adapter and scripted
strategist stay even after real Razorpay / Gemini adapters exist. The ledger
exposes cohesive single-transaction operations plus ledger-owned projections;
callers pass immutable commands and claim tokens, never mutable stored objects.

No method here performs an external network call.
"""

from __future__ import annotations

from .types import (
    AUDIT_AI_PROPOSAL,
    AUDIT_INPUT_EVENT,
    AUDIT_PAYMENT_CONFIRMATION,
    AUDIT_PENDING_WORK_CANCELLED,
    AUDIT_POLICY_DECISION,
    AUDIT_SCHEDULED_ACTION,
    AUDIT_STRATEGIST_FAILURE,
    AUDIT_TERMINAL_TRANSITION,
    ApplyResult,
    AuditEvent,
    AuditProjection,
    AuditRecord,
    BatchProjection,
    CaptureCommand,
    CaptureInfo,
    Case,
    CaseProjection,
    CaseSnapshot,
    CaseState,
    DiscardWorkCommand,
    EvaluationCommand,
    IntakeCommand,
    IntakeResult,
    NoteEventCommand,
    PolicyOutcome,
    ProposalAction,
    ProviderRetryFact,
    ScheduledWork,
    StrategistFailureCommand,
    StrategyProposal,
    StrategySnapshot,
    TERMINAL_STATES,
    WorkClaim,
    valid_payment_id,
)

# POLICY_SPEC: one retry after the initial attempt -> two total strategist attempts.
MAX_WORK_ATTEMPTS = 2
RETRY_BACKOFF_HOURS = 1
# A claimed work item whose holder never finalizes becomes reclaimable after
# this many logical hours. Models a DB visibility/lock timeout, not a real lock.
LEASE_TTL_HOURS = 6


# --- Payment provider ---------------------------------------------------


class FakeRazorpayAdapter:
    """Holds captured payments and per-obligation retry eligibility.

    Retry eligibility is fail-closed: an obligation with no recorded provider
    signal returns ``retry_eligible=False, evidence=None``.
    """

    def __init__(self) -> None:
        self._captures: dict[str, CaptureInfo] = {}
        self._retry_signal: dict[str, bool] = {}

    def set_retry_eligibility(self, obligation_id: str, eligible: bool) -> None:
        """Record an explicit provider signal for this obligation."""
        self._retry_signal[obligation_id] = eligible

    def retry_eligibility(self, obligation_id: str) -> ProviderRetryFact:
        if obligation_id not in self._retry_signal:
            return ProviderRetryFact(obligation_id, retry_eligible=False, evidence=None)
        return ProviderRetryFact(
            obligation_id,
            retry_eligible=self._retry_signal[obligation_id],
            evidence="provider_retry_signal",
        )

    def record_capture(
        self, obligation_id: str, payment_id: str, amount_minor: int
    ) -> None:
        self._captures.setdefault(
            obligation_id, CaptureInfo(obligation_id, payment_id, amount_minor)
        )

    def verify_capture(self, obligation_id: str) -> CaptureInfo | None:
        return self._captures.get(obligation_id)


# --- AI strategist ---------------------------------------------------


class ScriptedStrategist:
    """Returns a canned typed proposal keyed by failure reason code."""

    _DEFAULT_SCRIPT: dict[str, StrategyProposal] = {
        "bank_temporary_error": StrategyProposal(
            action=ProposalAction.WAIT_FOR_PROVIDER_RETRY,
            diagnosis="Temporary bank-side decline; provider retry is eligible.",
            rationale="Normal payment history and a transient error: wait for the "
            "next Razorpay-managed retry before any customer contact.",
            confidence=0.82,
            proposed_wait_hours=24,
        ),
    }

    def __init__(self, script: dict[str, StrategyProposal] | None = None) -> None:
        self.script = script or dict(self._DEFAULT_SCRIPT)

    def propose(self, snapshot: StrategySnapshot) -> StrategyProposal:
        reason = snapshot.failure_reason or ""
        try:
            return self.script[reason]
        except KeyError:
            raise KeyError(f"ScriptedStrategist has no proposal for reason {reason!r}")


# --- Recovery ledger ------------------------------------------------


class InMemoryLedger:
    """Authoritative in-memory state. All storage is private; callers touch it
    only through the transaction methods and projections below.
    """

    def __init__(self) -> None:
        self._cases: dict[str, Case] = {}
        self._by_obligation: dict[str, str] = {}
        self._work: dict[str, ScheduledWork] = {}
        self._audit: list[AuditEvent] = []
        self._seen_events: set[str] = set()
        self._recovered_payment_ids: set[str] = set()
        self._recovered_minor: int = 0
        self._seq = 0
        self._id_seq = 0

    # -- reads ---------------------------------------------------------

    def has_seen_event(self, event_id: str) -> bool:
        return event_id in self._seen_events

    def case_id_for_obligation(self, obligation_id: str) -> str | None:
        return self._by_obligation.get(obligation_id)

    def case_snapshot(self, case_id: str) -> CaseSnapshot:
        c = self._cases[case_id]
        return CaseSnapshot(
            c.case_id, c.obligation_id, c.amount_minor, c.currency, c.state.value,
            c.failure_reason, c.version,
        )

    def claim_due_work(self, now: int) -> list[WorkClaim]:
        """Exclusively lease **one** due work item.

        A work item is available only if it is unclaimed or its lease has
        expired (``now - claimed_at >= LEASE_TTL_HOURS``). Taking the lease
        bumps ``claim_version`` and issues a fresh ``claim_token``. A second
        runner calling this while the lease is live gets nothing back - so it
        never even sees the work, let alone calls the strategist for it. The
        work stays durable until a finalize consumes it, and an abandoned lease
        is safely reclaimable once it expires.
        """
        for w in sorted(self._work.values(), key=lambda w: (w.due_time, w.work_id)):
            if w.consumed or w.cancelled or w.due_time > now:
                continue
            if w.claimed_at is not None and now - w.claimed_at < LEASE_TTL_HOURS:
                continue  # a live lease is held by another runner
            w.claim_version += 1
            w.claim_token = self._next_id("claim")
            w.claimed_at = now
            return [
                WorkClaim(
                    work_id=w.work_id,
                    case_id=w.case_id,
                    kind=w.kind,
                    due_time=w.due_time,
                    attempts=w.attempts,
                    claim_token=w.claim_token,
                    claim_version=w.claim_version,
                )
            ]
        return []

    # -- projections (ledger-owned) --------------------------------

    def case_projection(
        self, *, case_id: str | None = None, obligation_id: str | None = None
    ) -> CaseProjection:
        if case_id is None and obligation_id is not None:
            case_id = self._by_obligation.get(obligation_id)
        if case_id is None or case_id not in self._cases:
            raise KeyError(obligation_id if case_id is None else case_id)
        c = self._cases[case_id]
        return CaseProjection(
            case_id=c.case_id,
            obligation_id=c.obligation_id,
            state=c.state.value,
            amount_minor=c.amount_minor,
            currency=c.currency,
            counted=c.counted,
            linked_payment_id=c.linked_payment_id,
            pending_work=len(self._pending_work(c.case_id)),
            version=c.version,
        )

    def batch_projection(self) -> BatchProjection:
        return BatchProjection(
            cases=len(self._cases),
            recovered_cases=sum(
                1 for c in self._cases.values() if c.state is CaseState.RECOVERED
            ),
            recovered_minor=self._recovered_minor,
            recovered_payments=len(self._recovered_payment_ids),
        )

    def audit_projection(self, case_id: str | None) -> AuditProjection:
        return AuditProjection(
            records=tuple(
                AuditRecord(e.seq, e.logical_time, e.case_id, e.kind, dict(e.detail))
                for e in self._audit
                if case_id in (None, e.case_id)
            )
        )

    # -- transactions ---------------------------------------------

    def mark_event_seen(self, event_id: str) -> None:
        self._seen_events.add(event_id)

    def note_event(self, cmd: NoteEventCommand) -> None:
        if cmd.event_id is not None:
            self._seen_events.add(cmd.event_id)
        self._append(cmd.now, cmd.case_id, cmd.kind, cmd.detail)

    def apply_intake(self, cmd: IntakeCommand) -> IntakeResult:
        """One transaction for a ``payment.failed`` webhook: deduplicate the
        provider event, enforce one case per obligation, record the input event
        and audit, and enqueue the initial re-evaluation work item.
        """
        if cmd.event_id in self._seen_events:
            existing = self._by_obligation.get(cmd.obligation_id)
            return IntakeResult(existing, duplicate=True, created=False,
                                outcome="duplicate_event")
        self._seen_events.add(cmd.event_id)

        existing = self._by_obligation.get(cmd.obligation_id)
        if existing is not None:
            self._append(
                cmd.now,
                existing,
                AUDIT_INPUT_EVENT,
                {
                    "event_id": cmd.event_id,
                    "type": "payment.failed",
                    "note": "existing case; no transition",
                    "case_state": self._cases[existing].state.value,
                },
            )
            return IntakeResult(existing, duplicate=False, created=False,
                                outcome="existing_case")

        case = Case(
            case_id=self._next_id("case"),
            obligation_id=cmd.obligation_id,
            amount_minor=cmd.amount_minor,
            currency=cmd.currency,
            created_time=cmd.now,
            failure_reason=cmd.reason_code,
        )
        self._cases[case.case_id] = case
        self._by_obligation[case.obligation_id] = case.case_id
        self._append(
            cmd.now,
            case.case_id,
            AUDIT_INPUT_EVENT,
            {
                "event_id": cmd.event_id,
                "type": "payment.failed",
                "obligation_id": cmd.obligation_id,
                "amount_minor": cmd.amount_minor,
                "reason_code": cmd.reason_code,
            },
        )
        wid = self._next_id("work")
        self._work[wid] = ScheduledWork(work_id=wid, case_id=case.case_id, due_time=cmd.now)
        return IntakeResult(case.case_id, duplicate=False, created=True,
                            outcome="case_opened")

    def discard_work(self, cmd: DiscardWorkCommand) -> ApplyResult:
        work = self._live_claim(cmd.work_id, cmd.claim_token, cmd.claim_version)
        if work is None:
            return ApplyResult(ok=False, reason="stale_claim")
        work.consumed = True
        self._append(
            cmd.now,
            cmd.case_id,
            AUDIT_SCHEDULED_ACTION,
            {"kind": "discarded", "reason": cmd.reason, "work_id": cmd.work_id},
        )
        return ApplyResult(ok=True, reason="discarded")

    def apply_evaluation(self, cmd: EvaluationCommand) -> ApplyResult:
        work = self._live_claim(cmd.work_id, cmd.claim_token, cmd.claim_version)
        if work is None:
            return ApplyResult(ok=False, reason="stale_claim")
        work.consumed = True
        case = self._cases[cmd.case_id]
        proposal, decision = cmd.proposal, cmd.decision
        self._append(
            cmd.now,
            case.case_id,
            AUDIT_AI_PROPOSAL,
            {
                "action": proposal.action.value,
                "diagnosis": proposal.diagnosis,
                "rationale": proposal.rationale,
                "confidence": proposal.confidence,
                "proposed_wait_hours": proposal.proposed_wait_hours,
            },
        )
        self._append(
            cmd.now,
            case.case_id,
            AUDIT_POLICY_DECISION,
            {
                "outcome": decision.outcome.value,
                "reason_code": decision.reason_code,
                "scheduled_time": decision.scheduled_time,
            },
        )
        if (
            decision.outcome is PolicyOutcome.ALLOW
            and proposal.action is ProposalAction.WAIT_FOR_PROVIDER_RETRY
        ):
            case.state = CaseState.WAITING
            case.version += 1
            due = decision.scheduled_time if decision.scheduled_time is not None else cmd.now
            wid = self._next_id("work")
            self._work[wid] = ScheduledWork(
                work_id=wid, case_id=case.case_id, due_time=due, attempts=0
            )
            self._append(
                cmd.now,
                case.case_id,
                AUDIT_SCHEDULED_ACTION,
                {"kind": "evaluate", "due_time": due},
            )
            return ApplyResult(ok=True, scheduled=True)
        return ApplyResult(ok=True, blocked=decision.outcome is PolicyOutcome.BLOCK)

    def apply_strategist_failure(self, cmd: StrategistFailureCommand) -> ApplyResult:
        work = self._live_claim(cmd.work_id, cmd.claim_token, cmd.claim_version)
        if work is None:
            return ApplyResult(ok=False, reason="stale_claim")
        work.consumed = True
        next_attempt = work.attempts + 1
        rescheduled = next_attempt < MAX_WORK_ATTEMPTS
        self._append(
            cmd.now,
            cmd.case_id,
            AUDIT_STRATEGIST_FAILURE,
            {
                "error": cmd.error,
                "attempt": work.attempts,
                "rescheduled": rescheduled,
                "exhausted": not rescheduled,
            },
        )
        if rescheduled:
            wid = self._next_id("work")
            self._work[wid] = ScheduledWork(
                work_id=wid,
                case_id=cmd.case_id,
                due_time=cmd.now + RETRY_BACKOFF_HOURS,
                kind="evaluate_retry",
                attempts=next_attempt,
            )
            self._append(
                cmd.now,
                cmd.case_id,
                AUDIT_SCHEDULED_ACTION,
                {
                    "kind": "evaluate_retry",
                    "due_time": cmd.now + RETRY_BACKOFF_HOURS,
                    "attempt": next_attempt,
                },
            )
            return ApplyResult(ok=True, scheduled=True)
        # retry budget exhausted -> deterministic terminal escalation
        case = self._cases[cmd.case_id]
        case.state = CaseState.ESCALATED
        case.version += 1
        self._append(
            cmd.now,
            cmd.case_id,
            AUDIT_TERMINAL_TRANSITION,
            {"state": CaseState.ESCALATED.value, "reason": "strategist_retry_exhausted"},
        )
        return ApplyResult(ok=True, reason="escalated", terminal=True)

    def apply_capture(self, cmd: CaptureCommand) -> ApplyResult:
        # Deduplicate this exact provider event first: a repeated delivery is a
        # silent no-op, never a second confirmation.
        if cmd.event_id is not None and cmd.event_id in self._seen_events:
            return ApplyResult(ok=False, reason="duplicate_event")
        if cmd.event_id is not None:
            self._seen_events.add(cmd.event_id)
        case = self._cases[cmd.case_id]
        self._append(
            cmd.now,
            case.case_id,
            AUDIT_INPUT_EVENT,
            {
                "event_id": cmd.event_id,
                "type": "payment.captured",
                "payment_id": cmd.payment_id,
                "amount_minor": cmd.amount_minor,
            },
        )
        # Atomically reject a case that moved on or went terminal since the
        # engine observed it, BEFORE any recovery is counted. Version first: a
        # racing captured event that already finalized bumped it.
        if case.version != cmd.expected_version:
            self._append(
                cmd.now,
                case.case_id,
                AUDIT_POLICY_DECISION,
                {"outcome": PolicyOutcome.BLOCK.value,
                 "reason_code": "stale_case_version",
                 "expected_version": cmd.expected_version,
                 "actual_version": case.version},
            )
            return ApplyResult(ok=False, reason="stale_case_version")
        if case.state.value in TERMINAL_STATES:
            self._append(
                cmd.now,
                case.case_id,
                AUDIT_POLICY_DECISION,
                {"outcome": PolicyOutcome.BLOCK.value,
                 "reason_code": "capture_on_terminal_case",
                 "case_state": case.state.value},
            )
            return ApplyResult(ok=False, reason="capture_on_terminal_case", terminal=True)
        if not valid_payment_id(cmd.payment_id):
            self._append(
                cmd.now,
                case.case_id,
                AUDIT_POLICY_DECISION,
                {"outcome": PolicyOutcome.BLOCK.value,
                 "reason_code": "invalid_payment_id",
                 "payment_id": cmd.payment_id},
            )
            return ApplyResult(ok=False, reason="invalid_payment_id")
        if cmd.payment_id in self._recovered_payment_ids:
            self._append(
                cmd.now,
                case.case_id,
                AUDIT_POLICY_DECISION,
                {
                    "outcome": PolicyOutcome.ESCALATE.value,
                    "reason_code": "payment_id_already_recovered",
                    "payment_id": cmd.payment_id,
                },
            )
            return ApplyResult(ok=True, reason="payment_id_already_recovered")

        self._append(
            cmd.now,
            case.case_id,
            AUDIT_PAYMENT_CONFIRMATION,
            {"payment_id": cmd.payment_id, "amount_minor": cmd.amount_minor},
        )
        cancelled = self._pending_work(case.case_id)
        for w in cancelled:
            w.cancelled = True
        if cancelled:
            self._append(
                cmd.now,
                case.case_id,
                AUDIT_PENDING_WORK_CANCELLED,
                {"count": len(cancelled), "reason": "payment_captured"},
            )
        self._recovered_payment_ids.add(cmd.payment_id)
        if not case.counted:
            self._recovered_minor += cmd.amount_minor
            case.counted = True
        case.state = CaseState.RECOVERED
        case.linked_payment_id = cmd.payment_id
        case.version += 1
        self._append(
            cmd.now,
            case.case_id,
            AUDIT_TERMINAL_TRANSITION,
            {"state": CaseState.RECOVERED.value, "recovered_minor": cmd.amount_minor},
        )
        return ApplyResult(ok=True, scheduled=False, terminal=True)

    # -- internals -------------------------------------------------

    def _pending_work(self, case_id: str) -> list[ScheduledWork]:
        return [
            w
            for w in self._work.values()
            if w.case_id == case_id and not w.cancelled and not w.consumed
        ]

    def _live_claim(
        self, work_id: str, token: str, version: int
    ) -> ScheduledWork | None:
        w = self._work.get(work_id)
        if w is None or w.consumed or w.cancelled:
            return None
        if w.claim_token != token or w.claim_version != version:
            return None
        return w

    def _append(self, now: int, case_id: str, kind: str, detail: dict) -> None:
        self._seq += 1
        self._audit.append(AuditEvent(self._seq, now, case_id, kind, dict(detail)))

    def _next_id(self, prefix: str) -> str:
        self._id_seq += 1
        return f"{prefix}-{self._id_seq}"
