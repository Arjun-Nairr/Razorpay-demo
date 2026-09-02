"""RecoveryEngine: the one deep module that owns the recovery workflow.

Public surface is exactly three methods: ``receive``, ``run``, ``inspect``.
Everything else is internal. Tests exercise only the public surface.

Boundary: the AI strategist *proposes*; deterministic policy *authorizes*.
Hermes never changes plans, prices, discounts, billing dates, payment methods,
or account access.

Transaction discipline: external calls (strategist, Razorpay) run *outside* any
ledger transaction. Each ledger ``open_case`` / ``apply_*`` call is one atomic
unit, so a future Neon adapter wraps each in BEGIN/COMMIT and a mid-flight
strategist failure can never lose scheduled work.
"""

from __future__ import annotations

from .adapters import FakeRazorpayAdapter, InMemoryLedger, ScriptedStrategist
from .types import (
    AUDIT_INPUT_EVENT,
    AUDIT_POLICY_DECISION,
    Case,
    CaseProjection,
    CaseQuery,
    CaseState,
    AuditProjection,
    AuditQuery,
    AuditRecord,
    BatchProjection,
    BatchQuery,
    InvalidProposal,
    PolicyDecision,
    PolicyOutcome,
    ProposalAction,
    ProviderRetryFact,
    RazorpayWebhook,
    ReceiveResult,
    RecoveryQuery,
    RecoveryView,
    RunReport,
    StrategyProposal,
    TERMINAL_STATES,
    WebhookType,
)

WORK_LOOP_LIMIT = 50  # steps per run() call
MAX_WAIT_HOURS = 72
_TERMINAL = TERMINAL_STATES


def _validate_proposal(obj: object) -> StrategyProposal:
    """Reject strategist output that is not a usable typed proposal."""
    if not isinstance(obj, StrategyProposal):
        raise InvalidProposal(f"not a StrategyProposal: {type(obj).__name__}")
    if not isinstance(obj.action, ProposalAction):
        raise InvalidProposal(f"unknown action: {obj.action!r}")
    if not (0.0 <= obj.confidence <= 1.0):
        raise InvalidProposal(f"confidence out of range: {obj.confidence}")
    if obj.proposed_wait_hours < 0:
        raise InvalidProposal(f"negative wait: {obj.proposed_wait_hours}")
    return obj


def authorize(
    proposal: StrategyProposal,
    case: Case,
    now: int,
    retry_fact: ProviderRetryFact,
) -> PolicyDecision:
    """Deterministic policy for the Case 1 path.

    Provider-truth (a captured payment) is handled in ``receive``. Here we cover
    terminal-state protection and WAIT_FOR_PROVIDER_RETRY authorization, which
    now requires a provider-derived retry-eligible fact. The AI proposal cannot
    set or override that fact.

    ponytail: partial policy. The full 10-step order (cooldowns, attempt/message
    limits, consent, commercial safety, reconciliation) arrives with cases 2-5.
    """
    if case.state.value in _TERMINAL:
        return PolicyDecision(PolicyOutcome.BLOCK, "terminal_case")
    if proposal.action is ProposalAction.WAIT_FOR_PROVIDER_RETRY:
        if not retry_fact.retry_eligible:
            return PolicyDecision(PolicyOutcome.BLOCK, "provider_retry_ineligible")
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

    # -- receive -----------------------------------------------------------

    def receive(self, webhook: RazorpayWebhook) -> ReceiveResult:
        """Durable intake. Deduplicates the provider event, then updates state
        through a single ledger transaction. Never calls the strategist and
        never runs the work loop.
        """
        led = self._ledger
        if led.has_seen_event(webhook.event_id):
            existing = led.case_for_obligation(webhook.obligation_id)
            return ReceiveResult(True, True, existing.case_id if existing else None)

        if webhook.type is WebhookType.PAYMENT_FAILED:
            return self._on_failed(webhook)
        if webhook.type is WebhookType.PAYMENT_CAPTURED:
            return self._on_captured(webhook)
        led.note_orphan_event(webhook.event_id)  # unsupported type: ignored
        return ReceiveResult(True, False, None)

    def _on_failed(self, webhook: RazorpayWebhook) -> ReceiveResult:
        led = self._ledger
        case = led.case_for_obligation(webhook.obligation_id)
        if case is not None:
            # One case per obligation; a later failure never forks a case or
            # reopens a terminal one.
            led.note_event(
                self._clock,
                webhook.event_id,
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

        case = led.open_case(webhook, self._clock)
        return ReceiveResult(True, False, case.case_id)

    def _on_captured(self, webhook: RazorpayWebhook) -> ReceiveResult:
        led = self._ledger
        case = led.case_for_obligation(webhook.obligation_id)
        if case is None:
            led.note_orphan_event(webhook.event_id)  # no case to attribute to
            return ReceiveResult(True, False, None)

        if case.state.value in _TERMINAL:
            led.note_event(
                self._clock,
                webhook.event_id,
                case,
                AUDIT_INPUT_EVENT,
                {
                    "event_id": webhook.event_id,
                    "type": webhook.type.value,
                    "payment_id": webhook.payment_id,
                    "note": "terminal case; no transition",
                },
            )
            return ReceiveResult(True, False, case.case_id)

        # External verification, outside any ledger transaction.
        self._razorpay.record_capture(
            webhook.obligation_id, webhook.payment_id or "", webhook.amount_minor
        )
        capture = self._razorpay.verify_capture(webhook.obligation_id)
        if capture is None or capture.amount_minor != case.amount_minor:
            led.note_event(
                self._clock,
                webhook.event_id,
                case,
                AUDIT_POLICY_DECISION,
                {
                    "outcome": PolicyOutcome.ESCALATE.value,
                    "reason_code": "capture_mismatch",
                },
            )
            return ReceiveResult(True, False, case.case_id)

        led.apply_capture(
            webhook.event_id,
            case,
            capture.payment_id,
            capture.amount_minor,
            self._clock,
        )
        return ReceiveResult(True, False, case.case_id)

    # -- run -------------------------------------------------------------

    def run(self, until: int) -> RunReport:
        """Advance the logical clock to ``until`` and process due work."""
        if until < self._clock:
            raise ValueError(
                f"logical time cannot move backward: {until} < {self._clock}"
            )
        self._clock = until
        led = self._ledger
        steps = proposals = failures = scheduled = blocked = 0

        # ponytail: a zero-hour wait could re-queue same tick; WORK_LOOP_LIMIT is
        # the backstop. Case 1's minimum wait is 24h, so it never churns.
        while steps < WORK_LOOP_LIMIT:
            due = led.claim_due_work(self._clock)
            if not due:
                break
            work = due[0]
            case = led.get_case(work.case_id)

            if case.state.value in _TERMINAL:
                led.discard_work(work, self._clock, case, reason="terminal_case")
                steps += 1
                continue

            retry_fact = self._razorpay.retry_eligibility(case.obligation_id)
            snapshot = self._snapshot(case, retry_fact)

            # External strategist call: outside the transaction, work still durable.
            try:
                proposal = _validate_proposal(self._strategist.propose(snapshot))
            except Exception as exc:  # raised / timed out / invalid output
                rescheduled = led.apply_strategist_failure(
                    work, case, type(exc).__name__, self._clock
                )
                failures += 1
                scheduled += int(rescheduled)
                steps += 1
                continue

            decision = authorize(proposal, case, self._clock, retry_fact)
            led.apply_evaluation(work, case, proposal, decision, self._clock)
            proposals += 1
            steps += 1
            if decision.outcome is PolicyOutcome.ALLOW and (
                proposal.action is ProposalAction.WAIT_FOR_PROVIDER_RETRY
            ):
                scheduled += 1
            elif decision.outcome is PolicyOutcome.BLOCK:
                blocked += 1

        return RunReport(
            logical_time=self._clock,
            steps=steps,
            proposals=proposals,
            strategist_failures=failures,
            scheduled=scheduled,
            blocked=blocked,
        )

    # -- inspect --------------------------------------------------------

    def inspect(self, query: RecoveryQuery) -> RecoveryView:
        """Typed read-only projections."""
        led = self._ledger
        if isinstance(query, CaseQuery):
            case = self._resolve_case(query)
            return CaseProjection(
                case_id=case.case_id,
                obligation_id=case.obligation_id,
                state=case.state.value,
                amount_minor=case.amount_minor,
                currency=case.currency,
                counted=case.counted,
                linked_payment_id=case.linked_payment_id,
                pending_work=len(led.pending_work(case.case_id)),
                version=case.version,
            )
        if isinstance(query, BatchQuery):
            cases = led.cases.values()
            return BatchProjection(
                cases=len(led.cases),
                recovered_cases=sum(1 for c in cases if c.state is CaseState.RECOVERED),
                recovered_minor=led.recovered_minor,
                recovered_payments=len(led.recovered_payment_ids),
            )
        if isinstance(query, AuditQuery):
            return AuditProjection(
                records=tuple(
                    AuditRecord(e.seq, e.logical_time, e.case_id, e.kind, dict(e.detail))
                    for e in led.audit_records(query.case_id)
                )
            )
        raise TypeError(f"unsupported query type: {type(query).__name__}")

    # -- internals ---------------------------------------------------

    def _resolve_case(self, query: CaseQuery) -> Case:
        led = self._ledger
        if query.case_id is not None:
            return led.get_case(query.case_id)
        if query.obligation_id is not None:
            case = led.case_for_obligation(query.obligation_id)
            if case is None:
                raise KeyError(query.obligation_id)
            return case
        raise ValueError("CaseQuery needs case_id or obligation_id")

    def _snapshot(self, case: Case, retry_fact: ProviderRetryFact) -> dict:
        # Source-labelled case snapshot for the strategist. The strategist may
        # read provider_retry but policy checks the fact independently, so it
        # cannot influence eligibility.
        return {
            "case_id": case.case_id,
            "obligation_id": case.obligation_id,
            "amount_minor": case.amount_minor,
            "failure_reason": case.failure_reason,
            "state": case.state.value,
            "provider_retry": retry_fact,
            "provider_retry_eligible": retry_fact.retry_eligible,
        }
