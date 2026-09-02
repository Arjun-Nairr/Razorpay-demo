"""RecoveryEngine: the one deep module that owns the recovery workflow.

Public surface is exactly three methods: ``receive``, ``run``, ``inspect``.
Everything else is internal. Tests exercise only the public surface.

Boundary: the AI strategist *proposes*; deterministic policy *authorizes*.
Hermes never changes plans, prices, discounts, billing dates, payment methods,
or account access.
"""

from __future__ import annotations

from .adapters import FakeRazorpayAdapter, InMemoryLedger, ScriptedStrategist
from .types import (
    AUDIT_AI_PROPOSAL,
    AUDIT_INPUT_EVENT,
    AUDIT_PAYMENT_CONFIRMATION,
    AUDIT_PENDING_WORK_CANCELLED,
    AUDIT_POLICY_DECISION,
    AUDIT_SCHEDULED_ACTION,
    AUDIT_TERMINAL_TRANSITION,
    Case,
    CaseState,
    PolicyDecision,
    PolicyOutcome,
    ProposalAction,
    RazorpayWebhook,
    ReceiveResult,
    RunReport,
    ScheduledWork,
    StrategyProposal,
    WebhookType,
)

WORK_LOOP_LIMIT = 50  # steps per run() call
MAX_WAIT_HOURS = 72
_TERMINAL = {"recovered", "stopped", "escalated", "exhausted"}


def authorize(proposal: StrategyProposal, case: Case, now: int) -> PolicyDecision:
    """Deterministic policy for the Case 1 path.

    Only the rules the vertical slice needs are implemented: provider-truth is
    handled in ``receive`` (a captured event marks recovered), and here we cover
    terminal-state protection plus the WAIT_FOR_PROVIDER_RETRY authorization.

    ponytail: partial policy. The full 10-step evaluation order (cooldowns,
    attempt limits, consent, commercial safety, ...) is added with cases 2-5.
    """
    if case.state.value in _TERMINAL:
        return PolicyDecision(PolicyOutcome.BLOCK, "terminal_case")
    if proposal.action is ProposalAction.WAIT_FOR_PROVIDER_RETRY:
        wait = max(0, min(proposal.proposed_wait_hours, MAX_WAIT_HOURS))
        return PolicyDecision(
            PolicyOutcome.ALLOW, "provider_retry_permitted", scheduled_time=now + wait
        )
    return PolicyDecision(PolicyOutcome.BLOCK, "action_not_supported_in_slice")


class RecoveryEngine:
    def __init__(
        self,
        ledger: InMemoryLedger | None = None,
        strategist: ScriptedStrategist | None = None,
        razorpay: FakeRazorpayAdapter | None = None,
    ) -> None:
        self._ledger = ledger or InMemoryLedger()
        self._strategist = strategist or ScriptedStrategist()
        self._razorpay = razorpay or FakeRazorpayAdapter()
        self._clock = 0  # monotonic logical hour

    def _audit(self, case: Case, kind: str, detail: dict) -> None:
        self._ledger.append_audit(self._clock, case.case_id, kind, detail)

    # -- receive --------------------------------------------------------------

    def receive(self, webhook: RazorpayWebhook) -> ReceiveResult:
        """Durable intake. Deduplicates the provider event, then updates state.

        Never calls the strategist and never runs the work loop.
        """
        led = self._ledger
        if webhook.event_id in led.seen_events:
            existing = led.case_for_obligation(webhook.obligation_id)
            return ReceiveResult(True, True, existing.case_id if existing else None)
        led.seen_events.add(webhook.event_id)

        if webhook.type is WebhookType.PAYMENT_FAILED:
            return self._on_failed(webhook)
        if webhook.type is WebhookType.PAYMENT_CAPTURED:
            return self._on_captured(webhook)
        return ReceiveResult(True, False, None)  # unsupported: ignored

    def _on_failed(self, webhook: RazorpayWebhook) -> ReceiveResult:
        led = self._ledger
        case = led.case_for_obligation(webhook.obligation_id)
        if case is not None:
            # One active case per obligation; a later failure never reopens a
            # terminal case or forks a second case.
            self._audit(
                case,
                AUDIT_INPUT_EVENT,
                {
                    "event_id": webhook.event_id,
                    "type": webhook.type.value,
                    "note": "existing case; no transition",
                    "case_state": case.state.value,
                },
            )
            return ReceiveResult(True, False, case.case_id)

        case = Case(
            case_id=led.next_id("case"),
            obligation_id=webhook.obligation_id,
            amount_minor=webhook.amount_minor,
            currency=webhook.currency,
            created_time=self._clock,
        )
        led.add_case(case)
        self._audit(
            case,
            AUDIT_INPUT_EVENT,
            {
                "event_id": webhook.event_id,
                "type": webhook.type.value,
                "obligation_id": webhook.obligation_id,
                "amount_minor": webhook.amount_minor,
                "reason_code": webhook.reason_code,
            },
        )
        # Enqueue an immediate re-evaluation; run() will consult the strategist.
        led.add_work(
            ScheduledWork(
                work_id=led.next_id("work"),
                case_id=case.case_id,
                due_time=self._clock,
            )
        )
        return ReceiveResult(True, False, case.case_id)

    def _on_captured(self, webhook: RazorpayWebhook) -> ReceiveResult:
        led = self._ledger
        case = led.case_for_obligation(webhook.obligation_id)
        if case is None:
            return ReceiveResult(True, False, None)  # no case to attribute to

        self._audit(
            case,
            AUDIT_INPUT_EVENT,
            {
                "event_id": webhook.event_id,
                "type": webhook.type.value,
                "payment_id": webhook.payment_id,
                "amount_minor": webhook.amount_minor,
            },
        )
        if case.state is CaseState.RECOVERED:
            return ReceiveResult(True, False, case.case_id)  # already counted

        # External verification runs outside the state mutation below so a real
        # ledger can keep the same call ordering between commits.
        self._razorpay.record_capture(
            webhook.obligation_id, webhook.payment_id or "", webhook.amount_minor
        )
        capture = self._razorpay.verify_capture(webhook.obligation_id)
        if capture is None or capture.amount_minor != case.amount_minor:
            self._audit(
                case,
                AUDIT_POLICY_DECISION,
                {"outcome": PolicyOutcome.ESCALATE.value, "reason_code": "capture_mismatch"},
            )
            return ReceiveResult(True, False, case.case_id)

        # -- one atomic transition: confirmation + cancellation + terminal --
        self._audit(
            case,
            AUDIT_PAYMENT_CONFIRMATION,
            {"payment_id": capture.payment_id, "amount_minor": capture.amount_minor},
        )
        self._cancel_pending_work(case, reason="payment_captured")
        if not case.counted:
            led.recovered_minor += case.amount_minor
            case.counted = True
        case.state = CaseState.RECOVERED
        case.linked_payment_id = capture.payment_id
        case.version += 1
        self._audit(
            case,
            AUDIT_TERMINAL_TRANSITION,
            {"state": CaseState.RECOVERED.value, "recovered_minor": case.amount_minor},
        )
        return ReceiveResult(True, False, case.case_id)

    # -- run -----------------------------------------------------------------

    def run(self, until: int) -> RunReport:
        """Advance the logical clock to ``until`` and process due work."""
        if until < self._clock:
            raise ValueError(
                f"logical time cannot move backward: {until} < {self._clock}"
            )
        self._clock = until
        led = self._ledger
        steps = proposals = 0

        while steps < WORK_LOOP_LIMIT:
            due = led.due_work(self._clock)
            if not due:
                break
            work = due[0]
            work.cancelled = True  # claimed
            steps += 1
            case = led.cases[work.case_id]
            if case.state.value in _TERMINAL:
                continue  # terminal cases schedule no work and consume none

            snapshot = self._snapshot(case)
            # Strategist call sits outside the state mutation that follows.
            proposal = self._strategist.propose(snapshot)
            proposals += 1
            self._audit(
                case,
                AUDIT_AI_PROPOSAL,
                {
                    "action": proposal.action.value,
                    "diagnosis": proposal.diagnosis,
                    "rationale": proposal.rationale,
                    "confidence": proposal.confidence,
                    "proposed_wait_hours": proposal.proposed_wait_hours,
                },
            )
            decision = authorize(proposal, case, self._clock)
            self._audit(
                case,
                AUDIT_POLICY_DECISION,
                {
                    "outcome": decision.outcome.value,
                    "reason_code": decision.reason_code,
                    "scheduled_time": decision.scheduled_time,
                },
            )
            if decision.outcome is PolicyOutcome.ALLOW and (
                proposal.action is ProposalAction.WAIT_FOR_PROVIDER_RETRY
            ):
                case.state = CaseState.WAITING
                case.version += 1
                led.add_work(
                    ScheduledWork(
                        work_id=led.next_id("work"),
                        case_id=case.case_id,
                        due_time=decision.scheduled_time,
                    )
                )
                self._audit(
                    case,
                    AUDIT_SCHEDULED_ACTION,
                    {"kind": "evaluate", "due_time": decision.scheduled_time},
                )

        return RunReport(logical_time=self._clock, steps=steps, proposals=proposals)

    # -- inspect -----------------------------------------------------------

    def inspect(self, query: dict) -> dict:
        """Read-only projections. ``query['kind']`` is 'case', 'batch', or 'audit'.

        ponytail: dict in / dict out for the slice; swap for a typed
        RecoveryQuery/RecoveryView once a second caller (Streamlit) exists.
        """
        led = self._ledger
        kind = query["kind"]
        if kind == "case":
            case = self._resolve_case(query)
            return {
                "case_id": case.case_id,
                "obligation_id": case.obligation_id,
                "state": case.state.value,
                "amount_minor": case.amount_minor,
                "currency": case.currency,
                "counted": case.counted,
                "linked_payment_id": case.linked_payment_id,
                "pending_work": len(led.pending_work(case.case_id)),
                "version": case.version,
            }
        if kind == "batch":
            cases = led.cases.values()
            return {
                "cases": len(led.cases),
                "recovered_cases": sum(1 for c in cases if c.state is CaseState.RECOVERED),
                "recovered_minor": led.recovered_minor,
            }
        if kind == "audit":
            wanted = query.get("case_id")
            events = [e for e in led.audit if wanted in (None, e.case_id)]
            return {
                "events": [
                    {
                        "seq": e.seq,
                        "logical_time": e.logical_time,
                        "case_id": e.case_id,
                        "kind": e.kind,
                        "detail": dict(e.detail),
                    }
                    for e in events
                ]
            }
        raise ValueError(f"unknown inspect kind: {kind!r}")

    # -- internals -------------------------------------------------------

    def _resolve_case(self, query: dict) -> Case:
        led = self._ledger
        if "case_id" in query:
            return led.cases[query["case_id"]]
        if "obligation_id" in query:
            case = led.case_for_obligation(query["obligation_id"])
            if case is None:
                raise KeyError(query["obligation_id"])
            return case
        raise ValueError("case query needs 'case_id' or 'obligation_id'")

    def _snapshot(self, case: Case) -> dict:
        # Source-labelled case snapshot for the strategist. In this slice the
        # only decision-driving fact is the failure reason from the last input
        # event's audit entry.
        reason = None
        for event in reversed(self._ledger.audit):
            if event.case_id == case.case_id and event.kind == AUDIT_INPUT_EVENT:
                reason = event.detail.get("reason_code")
                if reason:
                    break
        return {
            "case_id": case.case_id,
            "obligation_id": case.obligation_id,
            "amount_minor": case.amount_minor,
            "reason_code": reason,
            "state": case.state.value,
        }

    def _cancel_pending_work(self, case: Case, reason: str) -> None:
        pending = self._ledger.pending_work(case.case_id)
        for work in pending:
            work.cancelled = True
        if pending:
            self._audit(
                case,
                AUDIT_PENDING_WORK_CANCELLED,
                {"count": len(pending), "reason": reason},
            )
