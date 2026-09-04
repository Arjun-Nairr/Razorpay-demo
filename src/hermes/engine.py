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

from .message_templates import is_approved_message_intent
from .protocols import Ledger, PaymentProvider, Strategist
from .types import (
    AUDIT_AI_MODEL_RUN,
    AUDIT_INPUT_EVENT,
    AUDIT_POLICY_DECISION,
    ActionIntentOutcomeCommand,
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
MAX_WAIT_HOURS = 72  # ceiling on a SINGLE proposed wait

# POLICY_SPEC.md default deterministic limits (configuration, not prompt text).
MAX_ACTIONS_PER_CASE = 3
MAX_MESSAGES_PER_CASE = 2
MESSAGE_COOLDOWN_HOURS = 24
MAX_LINKS_PER_CASE = 1
# Deterministic ceiling on the CUMULATIVE wait a single case may accrue across
# every authorized WAIT_FOR_PROVIDER_RETRY. Current provider retry eligibility
# stays the primary gate; a recorded prior failed retry does NOT by itself mean
# retries are exhausted (see POLICY_SPEC.md "Wait for provider retry"). This
# bound is what stops an endless wait loop if the model keeps proposing waits
# while the provider keeps reporting eligible.
MAX_TOTAL_WAIT_HOURS = 72
# Substrings a strategist must never put in message_intent - it may propose
# reminder copy, never a URL, amount, provider id, discount, or commercial term.
_MESSAGE_INTENT_FORBIDDEN = ("http://", "https://", "₹", "$")


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
    if obj.action is ProposalAction.WAIT_FOR_PROVIDER_RETRY and obj.proposed_wait_hours < 1:
        # A wait "for the next provider retry" must be a real future interval.
        # Zero-hour waits spend no budget and reschedule immediately - an
        # endless-loop hole. Treat as invalid output -> bounded failure path.
        raise InvalidProposal("WAIT_FOR_PROVIDER_RETRY requires proposed_wait_hours >= 1")
    if obj.message_intent is not None:
        if not obj.message_intent.strip():
            raise InvalidProposal("blank message_intent")
        lowered = obj.message_intent.lower()
        if any(bad in lowered for bad in _MESSAGE_INTENT_FORBIDDEN):
            raise InvalidProposal(
                "message_intent must not contain a URL, amount, or provider "
                f"identifier: {obj.message_intent!r}"
            )
        # Real model output may only reuse a deterministic approved template -
        # never free-form customer copy. (The scripted strategist's own message
        # is on the allowlist, so offline behaviour is unchanged.)
        if not is_approved_message_intent(obj.message_intent):
            raise InvalidProposal("message_intent is not an approved template")
    return obj


def authorize(
    proposal: StrategyProposal,
    case: CaseSnapshot,
    now: int,
    retry_fact: ProviderRetryFact,
) -> PolicyDecision:
    """Deterministic policy for the Case 1 + Case 3 paths.

    Provider-truth (a captured payment) is handled in ``receive``. Here we
    cover terminal-state protection, WAIT_FOR_PROVIDER_RETRY authorization
    (fail-closed: needs an explicit provider-derived eligible fact *with*
    evidence - the AI proposal cannot set or override that fact), and
    CREATE_RECOVERY_LINK authorization (retry-outcome precondition, one-link/
    action-count limits, and an independent gate on any bundled message
    intent - communication ownership, consent, reachable channel, message
    count, and cooldown).

    ponytail: partial policy. The full 10-step order (dispute, commercial
    safety, reconciliation) arrives with cases 2/4/5.
    """
    if case.state in TERMINAL_STATES:
        return PolicyDecision(PolicyOutcome.BLOCK, "terminal_case")
    if proposal.action is ProposalAction.WAIT_FOR_PROVIDER_RETRY:
        if not retry_fact.retry_eligible or retry_fact.evidence is None:
            return PolicyDecision(PolicyOutcome.BLOCK, "provider_retry_ineligible")
        remaining = MAX_TOTAL_WAIT_HOURS - case.total_wait_hours
        if remaining <= 0:
            return PolicyDecision(PolicyOutcome.BLOCK, "total_wait_bound_reached")
        wait = min(proposal.proposed_wait_hours, MAX_WAIT_HOURS, remaining)
        if wait < 1:  # never authorize a zero/negative-hour "wait"
            return PolicyDecision(PolicyOutcome.BLOCK, "wait_must_be_positive")
        return PolicyDecision(
            PolicyOutcome.ALLOW, "provider_retry_permitted", scheduled_time=now + wait
        )
    if proposal.action is ProposalAction.CREATE_RECOVERY_LINK:
        return _authorize_recovery_link(proposal, case, now)
    if proposal.action is ProposalAction.ESCALATE:
        # The explicit safe path when evidence is inadequate or no other action
        # is authorized: a deterministic terminal transition to `escalated`
        # (unrecovered). Never advertised as "recovered" and never faked -
        # `apply_evaluation` performs the real transition.
        return PolicyDecision(PolicyOutcome.ESCALATE, "manual_escalation_authorized")
    return PolicyDecision(PolicyOutcome.BLOCK, "action_not_supported_in_slice")


def _authorize_recovery_link(
    proposal: StrategyProposal, case: CaseSnapshot, now: int
) -> PolicyDecision:
    """POLICY_SPEC.md "Create recovery link": allow at most once, only after a
    recorded failed retry outcome, within the action-count limit. The
    optional bundled message intent is authorized independently - consent,
    reachable channel, communication ownership, message-count, and cooldown -
    so a suppressed message never blocks the link itself.
    """
    if not case.retry_outcome_recorded:
        return PolicyDecision(PolicyOutcome.BLOCK, "retry_outcome_not_recorded")
    if case.links_created >= MAX_LINKS_PER_CASE:
        return PolicyDecision(PolicyOutcome.BLOCK, "recovery_link_limit_reached")
    if case.actions_taken >= MAX_ACTIONS_PER_CASE:
        return PolicyDecision(PolicyOutcome.BLOCK, "action_limit_reached")

    if not proposal.message_intent:
        return PolicyDecision(PolicyOutcome.ALLOW, "recovery_link_authorized")

    suppress_reason = _suppress_message_reason(case, now)
    if suppress_reason is None:
        return PolicyDecision(
            PolicyOutcome.ALLOW, "recovery_link_authorized_message_authorized",
            message_authorized=True,
        )
    return PolicyDecision(
        PolicyOutcome.ALLOW, f"recovery_link_authorized_message_suppressed_{suppress_reason}",
        message_authorized=False,
    )


def _suppress_message_reason(case: CaseSnapshot, now: int) -> str | None:
    """The reason a bundled/standalone message must be suppressed, or ``None``
    when every precondition clears. Order matches POLICY_SPEC.md's dispute-
    and-consent-before-attempt-limits-before-cooldown evaluation order.
    """
    if case.communication_owner != "merchant":
        return "provider_owned"
    if not case.consent:
        return "no_consent"
    if not case.reachable_channel:
        return "unreachable_channel"
    if case.messages_sent >= MAX_MESSAGES_PER_CASE:
        return "message_limit"
    if case.last_contact_time is not None and now - case.last_contact_time < MESSAGE_COOLDOWN_HOURS:
        return "cooldown"
    return None


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
        # Resume the persisted logical clock so a restarted demo does not lose time.
        self._clock = ledger.logical_clock()

    @property
    def logical_time(self) -> int:
        """The current logical hour (resumed from the ledger, advanced by run)."""
        return self._clock

    # -- receive ---------------------------------------------------------

    def receive(self, webhook: RazorpayWebhook) -> ReceiveResult:
        """Durable intake. Every branch resolves to exactly one atomic ledger
        command - no engine-level check-then-write. Never calls the strategist
        and never runs the work loop.
        """
        led = self._ledger
        # Refresh the logical clock from the persisted ledger so a payment that
        # arrives while another runner is mid-decision is stamped at current
        # demo time (and so a restarted engine intakes at the resumed clock).
        self._clock = led.logical_clock()
        if webhook.type is WebhookType.PAYMENT_FAILED:
            result = led.apply_intake(
                IntakeCommand(
                    event_id=webhook.event_id,
                    obligation_id=webhook.obligation_id,
                    amount_minor=webhook.amount_minor,
                    currency=webhook.currency,
                    reason_code=webhook.reason_code,
                    now=self._clock,
                    customer_notify=webhook.customer_notify,
                    consent=webhook.consent,
                    reachable_channel=webhook.reachable_channel,
                    evidence_mode=webhook.evidence_mode,
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
        # External verification, outside any ledger transaction. For a REAL_TEST_MODE
        # webhook, ``verify_capture`` performs an independent Razorpay readback
        # (never trusts the webhook body alone) and returns confirmed figures;
        # for SIMULATED it is the same record/read round-trip as before.
        self._razorpay.record_capture(
            webhook.obligation_id, payment_id, webhook.amount_minor,
            link_id=webhook.link_id,
        )
        capture = self._razorpay.verify_capture(webhook.obligation_id)
        currency_mismatch = (
            capture is not None and capture.currency is not None
            and capture.currency != snap.currency
        )
        if capture is None or capture.amount_minor != snap.amount_minor or currency_mismatch:
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
                evidence_mode=webhook.evidence_mode,
                link_id=capture.link_id,
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
        led.advance_clock(until)  # persist the advanced clock before any work
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
                self._note_model_run(claim.case_id, error=type(exc).__name__)
                result = led.apply_strategist_failure(
                    self._failure_cmd(claim, type(exc).__name__)
                )
                if not result.ok:
                    stale += 1
                    continue
                failures += 1
                scheduled += int(result.scheduled)
                continue

            self._note_model_run(claim.case_id)
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

            # A freshly persisted, durable action intent (never a duplicate
            # replay) is executed only now, OUTSIDE the transaction that
            # created it - the strategist never creates or runs the effect
            # itself; the fake executor is deterministic and idempotent, so
            # a lost/duplicated outcome write can never re-run it.
            if result.should_execute and result.action_intent_id is not None:
                reference = self._razorpay.create_recovery_link(
                    claim.case_id, result.idempotency_key or "",
                    amount_minor=snap.amount_minor, currency=snap.currency,
                )
                # Optional: a real adapter exposes the checkout URL separately
                # from its own correlation id (``reference``, e.g. a Payment
                # Link id) - never conflate the two. The fake adapter has no
                # such method, so this stays None for the simulated path.
                link_url = getattr(self._razorpay, "link_url", None)
                url = link_url(claim.case_id) if callable(link_url) else None
                led.apply_action_outcome(
                    ActionIntentOutcomeCommand(
                        intent_id=result.action_intent_id,
                        case_id=claim.case_id,
                        now=self._clock,
                        reference=reference,
                        message_sent=result.message_authorized,
                        url=url,
                    )
                )

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
            retry_outcome_recorded=snap.retry_outcome_recorded,
            communication_owner=snap.communication_owner,
            consent=snap.consent,
            reachable_channel=snap.reachable_channel,
            messages_sent=snap.messages_sent,
            links_created=snap.links_created,
            actions_taken=snap.actions_taken,
            last_contact_time=snap.last_contact_time,
            messages_remaining=max(0, MAX_MESSAGES_PER_CASE - snap.messages_sent),
            links_remaining=max(0, MAX_LINKS_PER_CASE - snap.links_created),
            actions_remaining=max(0, MAX_ACTIONS_PER_CASE - snap.actions_taken),
            wait_hours_remaining=max(0, MAX_TOTAL_WAIT_HOURS - snap.total_wait_hours),
            prior_action=snap.prior_action,
            prior_policy_outcome=snap.prior_policy_outcome,
            is_demo_case=self._is_demo_case(snap.case_id),
            case_history=self._case_history_projection(snap.case_id),
        )

    # Audit kinds that describe a prior ACTION / POLICY DECISION / OUTCOME for a
    # case - the material get_recovery_actions surfaces (not raw model text).
    _HISTORY_KINDS = (
        "AI_PROPOSAL", "POLICY_DECISION", "ACTION_INTENT", "ACTION_OUTCOME",
        "RETRY_OUTCOME_RECORDED", "SCHEDULED_ACTION", "STRATEGIST_FAILURE",
        "TERMINAL_TRANSITION",
    )
    _HISTORY_DETAIL_KEYS = (
        "action", "outcome", "reason_code", "kind", "state", "due_time",
        "attempt", "rescheduled", "exhausted", "message_authorized", "reason",
        "message_sent",
    )

    def _is_demo_case(self, case_id: str) -> bool:
        try:
            recs = self._ledger.audit_projection(case_id).records
        except Exception:  # pragma: no cover - defensive
            return False
        return any(r.kind == "DEMO_CASE_PROVENANCE" for r in recs)

    def _case_history_projection(self, case_id: str) -> tuple:
        """A bounded, redacted chronological projection of this case's prior
        actions / decisions / outcomes, via the public audit projection. No free
        text (diagnosis / rationale) - only stable typed fields."""
        try:
            recs = self._ledger.audit_projection(case_id).records
        except Exception:  # pragma: no cover - defensive
            return ()
        out = []
        for r in recs:
            if r.kind not in self._HISTORY_KINDS:
                continue
            d = r.detail if isinstance(r.detail, dict) else {}
            out.append({
                "t": r.logical_time, "kind": r.kind,
                **{k: d[k] for k in self._HISTORY_DETAIL_KEYS if k in d},
            })
        return tuple(out[-25:])

    def _note_model_run(self, case_id: str, *, error: str | None = None) -> None:
        """Append decision-linked model-run metadata to the audit trail when the
        strategist exposes a ``last_run_meta`` attribute (a live LLM strategist
        does; a scripted one does not - then this is a no-op). Only safe fields
        are recorded - model id, prompt version, latency, repair flag,
        validation result, token usage - never the prompt, raw customer data,
        or any credential. The engine still imports no concrete strategist.
        """
        meta = getattr(self._strategist, "last_run_meta", None)
        if meta is None:
            return
        detail = {
            "model": meta.model,
            "prompt_version": meta.prompt_version,
            "latency_ms": meta.latency_ms,
            "repair_used": meta.repair_used,
            "validation_result": meta.validation_result,
            "usage": meta.usage,
        }
        # A real-Hermes strategist attaches bounded, redacted agent-decision
        # metadata (runtime revision, evidence requests + reasons, returned
        # source/coverage, confidence band, unresolved uncertainty, stop
        # reason, duration, tokens) - short explanations and tool evidence,
        # never raw transcripts or chain-of-thought.
        extra = getattr(meta, "extra", None)
        if isinstance(extra, dict) and extra:
            detail["hermes"] = extra
        if error is not None:
            detail["engine_error"] = error
        self._ledger.note_event(
            NoteEventCommand(
                case_id=case_id, event_id=None, kind=AUDIT_AI_MODEL_RUN,
                detail=detail, now=self._clock,
            )
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
