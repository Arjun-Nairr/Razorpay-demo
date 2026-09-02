"""RecoveryEngine: the one deep module that owns the recovery workflow.

Public surface is exactly three methods: ``receive``, ``run``, ``inspect``.

Boundary: the AI strategist *proposes*; deterministic policy *authorizes*.
Hermes never changes plans, prices, discounts, billing dates, payment methods,
or account access.

The engine depends only on the ``Ledger`` / ``Strategist`` / ``PaymentProvider``
protocols. It never holds a mutable stored record: it reads frozen snapshots and
leased ``WorkClaim`` tokens, and every write is an immutable command. External
calls (strategist, provider) run outside every ledger transaction; a claim that
another runner has since won is rejected as stale with no effect.
"""

from __future__ import annotations

from .protocols import Ledger, PaymentProvider, Strategist
from .types import (
    AUDIT_INPUT_EVENT,
    AUDIT_POLICY_DECISION,
    AuditQuery,
    BatchQuery,
    CaptureCommand,
    CaseQuery,
    CaseSnapshot,
    DiscardWorkCommand,
    EvaluationCommand,
    IntakeCommand,
    InvalidProposal,
    NoteEventCommand,
    PolicyDecision,
    PolicyOutcome,
    ProposalAction,
    ProviderRetryFact,
    RazorpayWebhook,
    ReceiveResult,
    RecoveryQuery,
    RecoveryView,
    RunReport,
    StrategistFailureCommand,
    StrategyProposal,
    StrategySnapshot,
    TERMINAL_STATES,
    WebhookType,
    WorkClaim,
    valid_payment_id,
)

WORK_LOOP_LIMIT = 50  # steps per run() call
MAX_WAIT_HOURS = 72


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
    case: CaseSnapshot,
    now: int,
    retry_fact: ProviderRetryFact,
) -> PolicyDecision:
    """Deterministic policy for the Case 1 path.

    Provider-truth (a captured payment) is handled in ``receive``. Here we cover
    terminal-state protection and WAIT_FOR_PROVIDER_RETRY authorization, which
    is fail-closed: it needs an explicit provider-derived eligible fact *with*
    evidence. The AI proposal cannot set or override that fact.

    ponytail: partial policy. The full 10-step order (cooldowns, attempt/message
    limits, consent, commercial safety, reconciliation) arrives with cases 2-5.
    """
    if case.state in TERMINAL_STATES:
        return PolicyDecision(PolicyOutcome.BLOCK, "terminal_case")
    if proposal.action is ProposalAction.WAIT_FOR_PROVIDER_RETRY:
        if not retry_fact.retry_eligible or retry_fact.evidence is None:
            return PolicyDecision(PolicyOutcome.BLOCK, "provider_retry_ineligible")
        wait = max(0, min(proposal.proposed_wait_hours, MAX_WAIT_HOURS))
        return PolicyDecision(
            PolicyOutcome.ALLOW, "provider_retry_permitted", scheduled_time=now + wait
        )
    return PolicyDecision(PolicyOutcome.BLOCK, "action_not_supported_in_slice")


class RecoveryEngine:
    def __init__(
        self,
        ledger: Ledger,
        strategist: Strategist,
        razorpay: PaymentProvider,
    ) -> None:
        self._ledger = ledger
        self._strategist = strategist
        self._razorpay = razorpay
        self._clock = 0  # monotonic logical hour

    # -- receive ---------------------------------------------------------

    def receive(self, webhook: RazorpayWebhook) -> ReceiveResult:
        """Durable intake. Every branch resolves to exactly one atomic ledger
        command - no engine-level check-then-write. Never calls the strategist
        and never runs the work loop.
        """
        led = self._ledger
        if webhook.type is WebhookType.PAYMENT_FAILED:
            result = led.apply_intake(
                IntakeCommand(
                    event_id=webhook.event_id,
                    obligation_id=webhook.obligation_id,
                    amount_minor=webhook.amount_minor,
                    currency=webhook.currency,
                    reason_code=webhook.reason_code,
                    now=self._clock,
                )
            )
            return ReceiveResult(True, result.duplicate, result.case_id)
        if webhook.type is WebhookType.PAYMENT_CAPTURED:
            return self._on_captured(webhook)
        led.mark_event_seen(webhook.event_id)  # unsupported type: ignored
        return ReceiveResult(True, False, None)

    def _on_captured(self, webhook: RazorpayWebhook) -> ReceiveResult:
        led = self._ledger
        case_id = led.case_id_for_obligation(webhook.obligation_id)
        if case_id is None:
            led.mark_event_seen(webhook.event_id)  # nothing to attribute to
            return ReceiveResult(True, False, None)

        # Fast-path reads; apply_capture re-validates dedup + version + terminal
        # state atomically, so these never gate correctness on their own.
        if led.has_seen_event(webhook.event_id):
            return ReceiveResult(True, True, case_id)

        snap = led.case_snapshot(case_id)
        if snap.state in TERMINAL_STATES:
            led.note_event(
                NoteEventCommand(
                    case_id=case_id,
                    event_id=webhook.event_id,
                    kind=AUDIT_INPUT_EVENT,
                    detail={
                        "event_id": webhook.event_id,
                        "type": webhook.type.value,
                        "payment_id": webhook.payment_id,
                        "note": "terminal case; no transition",
                    },
                    now=self._clock,
                )
            )
            return ReceiveResult(True, False, case_id)

        # Payment-identity validation happens BEFORE any provider recording or
        # verification. A missing/blank id can never move money or a case.
        if not valid_payment_id(webhook.payment_id):
            led.note_event(
                NoteEventCommand(
                    case_id=case_id,
                    event_id=webhook.event_id,
                    kind=AUDIT_POLICY_DECISION,
                    detail={
                        "outcome": PolicyOutcome.BLOCK.value,
                        "reason_code": "invalid_payment_id",
                        "payment_id": webhook.payment_id,
                    },
                    now=self._clock,
                )
            )
            return ReceiveResult(True, False, case_id)

        payment_id = webhook.payment_id.strip()  # type: ignore[union-attr]
        # External verification, outside any ledger transaction.
        self._razorpay.record_capture(
            webhook.obligation_id, payment_id, webhook.amount_minor
        )
        capture = self._razorpay.verify_capture(webhook.obligation_id)
        if capture is None or capture.amount_minor != snap.amount_minor:
            led.note_event(
                NoteEventCommand(
                    case_id=case_id,
                    event_id=webhook.event_id,
                    kind=AUDIT_POLICY_DECISION,
                    detail={
                        "outcome": PolicyOutcome.ESCALATE.value,
                        "reason_code": "capture_mismatch",
                    },
                    now=self._clock,
                )
            )
            return ReceiveResult(True, False, case_id)

        # expected_version / expected_state pin the case as observed *before*
        # the external verification above; apply_capture rejects atomically if
        # the case moved on (e.g. a racing captured event already finalized it).
        result = led.apply_capture(
            CaptureCommand(
                case_id=case_id,
                event_id=webhook.event_id,
                payment_id=capture.payment_id,
                amount_minor=capture.amount_minor,
                now=self._clock,
                expected_version=snap.version,
                expected_state=snap.state,
            )
        )
        return ReceiveResult(True, result.reason == "duplicate_event", case_id)

    # -- run ---------------------------------------------------------

    def run(self, until: int) -> RunReport:
        """Advance the logical clock to ``until`` and process due work."""
        if until < self._clock:
            raise ValueError(
                f"logical time cannot move backward: {until} < {self._clock}"
            )
        self._clock = until
        led = self._ledger
        steps = proposals = failures = scheduled = blocked = stale = 0

        # claim_due_work leases at most one item and never returns work another
        # runner holds a live lease on, so the loop drains only what this runner
        # exclusively owns; WORK_LOOP_LIMIT is the hard backstop.
        while steps < WORK_LOOP_LIMIT:
            claims = led.claim_due_work(self._clock)
            if not claims:
                break
            claim = claims[0]
            steps += 1

            snap = led.case_snapshot(claim.case_id)
            if snap.state in TERMINAL_STATES:
                led.discard_work(self._discard_cmd(claim, "terminal_case"))
                continue

            retry_fact = self._razorpay.retry_eligibility(snap.obligation_id)

            # External strategist call: outside the transaction, work still durable.
            try:
                proposal = _validate_proposal(
                    self._strategist.propose(self._snapshot(snap, retry_fact))
                )
            except Exception as exc:  # raised / timed out / invalid output
                result = led.apply_strategist_failure(
                    self._failure_cmd(claim, type(exc).__name__)
                )
                if not result.ok:
                    stale += 1
                    continue
                failures += 1
                scheduled += int(result.scheduled)
                continue

            decision = authorize(proposal, snap, self._clock, retry_fact)
            result = led.apply_evaluation(
                EvaluationCommand(
                    work_id=claim.work_id,
                    claim_token=claim.claim_token,
                    claim_version=claim.claim_version,
                    case_id=claim.case_id,
                    proposal=proposal,
                    decision=decision,
                    now=self._clock,
                )
            )
            if not result.ok:
                stale += 1
                continue
            proposals += 1
            scheduled += int(result.scheduled)
            blocked += int(result.blocked)

        return RunReport(
            logical_time=self._clock,
            steps=steps,
            proposals=proposals,
            strategist_failures=failures,
            scheduled=scheduled,
            blocked=blocked,
            stale_claims=stale,
        )

    # -- inspect -------------------------------------------------

    def inspect(self, query: RecoveryQuery) -> RecoveryView:
        """Typed read-only projections, all built by the ledger."""
        led = self._ledger
        if isinstance(query, CaseQuery):
            return led.case_projection(
                case_id=query.case_id, obligation_id=query.obligation_id
            )
        if isinstance(query, BatchQuery):
            return led.batch_projection()
        if isinstance(query, AuditQuery):
            return led.audit_projection(query.case_id)
        raise TypeError(f"unsupported query type: {type(query).__name__}")

    # -- internals ---------------------------------------------

    def _snapshot(
        self, snap: CaseSnapshot, retry_fact: ProviderRetryFact
    ) -> StrategySnapshot:
        return StrategySnapshot(
            case_id=snap.case_id,
            obligation_id=snap.obligation_id,
            amount_minor=snap.amount_minor,
            currency=snap.currency,
            failure_reason=snap.failure_reason,
            state=snap.state,
            provider_retry_eligible=retry_fact.retry_eligible,
            provider_retry_evidence=retry_fact.evidence,
        )

    def _discard_cmd(self, claim: WorkClaim, reason: str) -> DiscardWorkCommand:
        return DiscardWorkCommand(
            work_id=claim.work_id,
            claim_token=claim.claim_token,
            claim_version=claim.claim_version,
            case_id=claim.case_id,
            reason=reason,
            now=self._clock,
        )

    def _failure_cmd(self, claim: WorkClaim, error: str) -> StrategistFailureCommand:
        return StrategistFailureCommand(
            work_id=claim.work_id,
            claim_token=claim.claim_token,
            claim_version=claim.claim_version,
            case_id=claim.case_id,
            error=error,
            now=self._clock,
        )
