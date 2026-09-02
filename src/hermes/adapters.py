"""In-memory test doubles for the three external seams.

Real Razorpay / Gemini / Neon adapters land in a later iteration behind these
same shapes. The ledger deliberately exposes *cohesive* operations (open a case,
apply an evaluation, apply a verified capture, record a strategist failure) that
each map to a single transaction. The engine never pokes ledger state field by
field, so the future Neon adapter can wrap each operation in BEGIN/COMMIT.

No method here performs an external call.
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import (
    AUDIT_AI_PROPOSAL,
    AUDIT_INPUT_EVENT,
    AUDIT_PAYMENT_CONFIRMATION,
    AUDIT_PENDING_WORK_CANCELLED,
    AUDIT_POLICY_DECISION,
    AUDIT_SCHEDULED_ACTION,
    AUDIT_STRATEGIST_FAILURE,
    AUDIT_TERMINAL_TRANSITION,
    AuditEvent,
    Case,
    CaseState,
    PolicyDecision,
    PolicyOutcome,
    ProposalAction,
    ProviderRetryFact,
    RazorpayWebhook,
    ScheduledWork,
    StrategyProposal,
)

MAX_WORK_ATTEMPTS = 3  # initial try + 2 bounded strategist retries
RETRY_BACKOFF_HOURS = 1


# --- Razorpay --------------------------------------------------------------


@dataclass(frozen=True)
class CaptureInfo:
    obligation_id: str
    payment_id: str
    amount_minor: int


class FakeRazorpayAdapter:
    """Holds captured payments and per-obligation retry eligibility, and
    'verifies' captures. A captured webhook is trusted in this slice, so
    verification only confirms the recorded amount/obligation are consistent.
    """

    def __init__(self) -> None:
        self._captures: dict[str, CaptureInfo] = {}
        self._retry_eligible: dict[str, bool] = {}

    # retry eligibility (provider-derived fact)
    def set_retry_eligibility(self, obligation_id: str, eligible: bool) -> None:
        self._retry_eligible[obligation_id] = eligible

    def retry_eligibility(self, obligation_id: str) -> ProviderRetryFact:
        # Default: eligible. Case 1's temporary bank failure is retryable.
        return ProviderRetryFact(
            obligation_id=obligation_id,
            retry_eligible=self._retry_eligible.get(obligation_id, True),
        )

    # capture verification
    def record_capture(self, obligation_id: str, payment_id: str, amount_minor: int) -> None:
        self._captures.setdefault(
            obligation_id, CaptureInfo(obligation_id, payment_id, amount_minor)
        )

    def verify_capture(self, obligation_id: str) -> CaptureInfo | None:
        return self._captures.get(obligation_id)


# --- AI strategist ------------------------------------------------------


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

    def propose(self, snapshot: dict) -> StrategyProposal:
        reason = snapshot.get("failure_reason") or ""
        try:
            return self.script[reason]
        except KeyError:
            raise KeyError(f"ScriptedStrategist has no proposal for reason {reason!r}")


# --- Recovery ledger --------------------------------------------------


class InMemoryLedger:
    """Authoritative in-memory state plus cohesive, single-transaction writes."""

    def __init__(self) -> None:
        self.cases: dict[str, Case] = {}
        self._by_obligation: dict[str, str] = {}
        self.work: list[ScheduledWork] = []
        self.audit: list[AuditEvent] = []
        self.seen_events: set[str] = set()
        self.recovered_payment_ids: set[str] = set()
        self.recovered_minor: int = 0
        self._seq = 0
        self._id_seq = 0

    # -- reads (no transaction) -------------------------------------------

    def has_seen_event(self, event_id: str) -> bool:
        return event_id in self.seen_events

    def get_case(self, case_id: str) -> Case:
        return self.cases[case_id]

    def case_for_obligation(self, obligation_id: str) -> Case | None:
        case_id = self._by_obligation.get(obligation_id)
        return self.cases.get(case_id) if case_id else None

    def pending_work(self, case_id: str) -> list[ScheduledWork]:
        return [
            w
            for w in self.work
            if w.case_id == case_id and not w.cancelled and not w.consumed
        ]

    def claim_due_work(self, at: int) -> list[ScheduledWork]:
        """Due, live work in a stable order. Left durable: nothing is mutated
        here, so a strategist call that fails afterwards loses no work.
        """
        return sorted(
            (
                w
                for w in self.work
                if not w.cancelled and not w.consumed and w.due_time <= at
            ),
            key=lambda w: (w.due_time, w.work_id),
        )

    def audit_records(self, case_id: str | None) -> list[AuditEvent]:
        return [e for e in self.audit if case_id in (None, e.case_id)]

    # -- transactions ---------------------------------------------------

    def note_event(
        self, now: int, event_id: str | None, case: Case, kind: str, detail: dict
    ) -> None:
        """Mark an event seen and append exactly one audit record. Used for
        events that produce no state transition (duplicates on a fresh id,
        captures on a terminal case, capture mismatches).
        """
        if event_id is not None:
            self.seen_events.add(event_id)
        self._append(now, case.case_id, kind, detail)

    def note_orphan_event(self, event_id: str | None) -> None:
        if event_id is not None:
            self.seen_events.add(event_id)

    def discard_work(
        self, work: ScheduledWork, now: int, case: Case, reason: str
    ) -> None:
        """Consume a live work item that no longer applies (its case went
        terminal by another path). Recorded so the trail explains the gap.
        """
        work.consumed = True
        self._append(
            now,
            case.case_id,
            AUDIT_SCHEDULED_ACTION,
            {"kind": "discarded", "reason": reason, "work_id": work.work_id},
        )

    def open_case(self, webhook: RazorpayWebhook, now: int) -> Case:
        """One transaction: create the case, mark the event seen, record the
        input-event audit, and enqueue an immediate re-evaluation.
        """
        case = Case(
            case_id=self._next_id("case"),
            obligation_id=webhook.obligation_id,
            amount_minor=webhook.amount_minor,
            currency=webhook.currency,
            created_time=now,
            failure_reason=webhook.reason_code,
        )
        self.cases[case.case_id] = case
        self._by_obligation[case.obligation_id] = case.case_id
        self.seen_events.add(webhook.event_id)
        self._append(
            now,
            case.case_id,
            AUDIT_INPUT_EVENT,
            {
                "event_id": webhook.event_id,
                "type": webhook.type.value,
                "obligation_id": webhook.obligation_id,
                "amount_minor": webhook.amount_minor,
                "reason_code": webhook.reason_code,
            },
        )
        self.work.append(
            ScheduledWork(
                work_id=self._next_id("work"), case_id=case.case_id, due_time=now
            )
        )
        return case

    def apply_evaluation(
        self,
        work: ScheduledWork,
        case: Case,
        proposal: StrategyProposal,
        decision: PolicyDecision,
        now: int,
    ) -> None:
        """One transaction: consume the claimed work, record the proposal and
        the policy decision, and (only on ALLOW of a wait) transition the case
        and schedule the next re-evaluation.
        """
        work.consumed = True
        self._append(
            now,
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
            now,
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
            due = decision.scheduled_time if decision.scheduled_time is not None else now
            self.work.append(
                ScheduledWork(
                    work_id=self._next_id("work"),
                    case_id=case.case_id,
                    due_time=due,
                    attempts=0,
                )
            )
            self._append(
                now,
                case.case_id,
                AUDIT_SCHEDULED_ACTION,
                {"kind": "evaluate", "due_time": due},
            )

    def apply_strategist_failure(
        self, work: ScheduledWork, case: Case, error: str, now: int
    ) -> bool:
        """One transaction: consume the claimed work, audit the failure, and
        (within a bounded budget) schedule one retry. No recovery action runs.
        Returns True if a retry was scheduled.
        """
        work.consumed = True
        next_attempt = work.attempts + 1
        rescheduled = next_attempt < MAX_WORK_ATTEMPTS
        self._append(
            now,
            case.case_id,
            AUDIT_STRATEGIST_FAILURE,
            {
                "error": error,
                "attempt": work.attempts,
                "rescheduled": rescheduled,
                "exhausted": not rescheduled,
            },
        )
        if rescheduled:
            self.work.append(
                ScheduledWork(
                    work_id=self._next_id("work"),
                    case_id=case.case_id,
                    due_time=now + RETRY_BACKOFF_HOURS,
                    kind="evaluate_retry",
                    attempts=next_attempt,
                )
            )
            self._append(
                now,
                case.case_id,
                AUDIT_SCHEDULED_ACTION,
                {
                    "kind": "evaluate_retry",
                    "due_time": now + RETRY_BACKOFF_HOURS,
                    "attempt": next_attempt,
                },
            )
        return rescheduled

    def apply_capture(
        self,
        event_id: str | None,
        case: Case,
        payment_id: str,
        amount_minor: int,
        now: int,
    ) -> bool:
        """One transaction: record the input event, enforce global payment-id
        exact-once, confirm the payment, cancel pending work, add recovered
        value once, and mark the case recovered. Returns True if the case was
        recovered by this call.
        """
        if event_id is not None:
            self.seen_events.add(event_id)
        self._append(
            now,
            case.case_id,
            AUDIT_INPUT_EVENT,
            {"event_id": event_id, "type": "payment.captured", "payment_id": payment_id,
             "amount_minor": amount_minor},
        )

        if payment_id in self.recovered_payment_ids:
            # Same payment already counted (possibly for another obligation).
            self._append(
                now,
                case.case_id,
                AUDIT_POLICY_DECISION,
                {"outcome": PolicyOutcome.ESCALATE.value,
                 "reason_code": "payment_id_already_recovered",
                 "payment_id": payment_id},
            )
            return False

        self._append(
            now,
            case.case_id,
            AUDIT_PAYMENT_CONFIRMATION,
            {"payment_id": payment_id, "amount_minor": amount_minor},
        )
        cancelled = self.pending_work(case.case_id)
        for w in cancelled:
            w.cancelled = True
        if cancelled:
            self._append(
                now,
                case.case_id,
                AUDIT_PENDING_WORK_CANCELLED,
                {"count": len(cancelled), "reason": "payment_captured"},
            )

        self.recovered_payment_ids.add(payment_id)
        if not case.counted:
            self.recovered_minor += amount_minor
            case.counted = True
        case.state = CaseState.RECOVERED
        case.linked_payment_id = payment_id
        case.version += 1
        self._append(
            now,
            case.case_id,
            AUDIT_TERMINAL_TRANSITION,
            {"state": CaseState.RECOVERED.value, "recovered_minor": amount_minor},
        )
        return True

    # -- internals ----------------------------------------------------

    def _append(self, now: int, case_id: str, kind: str, detail: dict) -> None:
        self._seq += 1
        self.audit.append(AuditEvent(self._seq, now, case_id, kind, dict(detail)))

    def _next_id(self, prefix: str) -> str:
        self._id_seq += 1
        return f"{prefix}-{self._id_seq}"
