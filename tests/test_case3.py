"""Case 3 - insufficient funds with adaptation and attribution.

Wait once for a provider-eligible retry; when a subsequent, distinct failed
event for the same obligation records that retry's failed outcome, the
scripted strategist changes strategy to CREATE_RECOVERY_LINK (with an
optional reminder intent policy may still suppress); a uniquely correlated
captured payment against that link is attributed ``hermes_assisted``.

Every test drives the public ``RecoveryEngine`` surface (``receive`` results,
``run`` reports, ``inspect`` projections) plus direct calls to the
``InMemoryLedger``/``authorize`` public seams already exercised the same way
in ``test_case1.py`` (e.g. ``ledger.claim_due_work``) - never a private
``engine.`` attribute.
"""

import pytest

from hermes.adapters import FakeRazorpayAdapter, InMemoryLedger, ScriptedStrategist
from hermes.engine import (
    MAX_ACTIONS_PER_CASE,
    MAX_LINKS_PER_CASE,
    MAX_MESSAGES_PER_CASE,
    MESSAGE_COOLDOWN_HOURS,
    RecoveryEngine,
    authorize,
)
from hermes.types import (
    AuditQuery,
    BatchQuery,
    CaptureCommand,
    CaseQuery,
    CaseSnapshot,
    ProposalAction,
    ProviderRetryFact,
    RazorpayWebhook,
    StrategyProposal,
    WebhookType,
)

RUPEES_10K_MINOR = 10_000 * 100
OBLIGATION = "sub_INV_IF_0001"


def failed_event(event_id, obligation=OBLIGATION, reason="insufficient_funds",
                 amount=RUPEES_10K_MINOR, customer_notify=False, consent=True,
                 reachable_channel=True):
    return RazorpayWebhook(
        event_id, WebhookType.PAYMENT_FAILED, obligation, amount, reason_code=reason,
        customer_notify=customer_notify, consent=consent, reachable_channel=reachable_channel,
    )


def captured_event(event_id, obligation=OBLIGATION, payment_id="pay_TEST",
                   amount=RUPEES_10K_MINOR):
    return RazorpayWebhook(
        event_id, WebhookType.PAYMENT_CAPTURED, obligation, amount, payment_id=payment_id
    )


@pytest.fixture
def razorpay():
    return FakeRazorpayAdapter()


@pytest.fixture
def engine(razorpay):
    return RecoveryEngine(
        ledger=InMemoryLedger(), strategist=ScriptedStrategist(), razorpay=razorpay
    )


def eligible(razorpay, obligation=OBLIGATION):
    razorpay.set_retry_eligibility(obligation, True)


def case_view(engine, **kw):
    return engine.inspect(CaseQuery(**kw))


def batch(engine):
    return engine.inspect(BatchQuery())


def audit_kinds(engine, case_id):
    return engine.inspect(AuditQuery(case_id=case_id)).kinds()


def policy_reasons(engine, case_id):
    return [
        r.detail.get("reason_code")
        for r in engine.inspect(AuditQuery(case_id=case_id)).records
        if r.kind == "POLICY_DECISION"
    ]


def wait_then_fail_retry(engine, razorpay, *, customer_notify=False, consent=True,
                         reachable_channel=True):
    """Drives the case through: first failure -> permitted wait -> a distinct
    failed-retry event -> the case woken. Returns (case_id,).
    """
    eligible(razorpay)
    r = engine.receive(failed_event(
        "evt_if_1", customer_notify=customer_notify, consent=consent,
        reachable_channel=reachable_channel,
    ))
    engine.run(until=1)
    assert case_view(engine, case_id=r.case_id).state == "waiting"

    engine.receive(failed_event("evt_if_2_retry_failed"))  # the retry's outcome
    return r.case_id


# --- requirement 1: capture guard closes the expected_state gap ------------


def test_expected_state_mismatch_rejects_capture_before_counting():
    """A captured event pinned to a stale ``expected_state`` (even with a
    correct ``expected_version``) must be rejected before any money is
    counted - the exact gap IMPLEMENTATION_SPEC.md names."""
    ledger = InMemoryLedger()
    razorpay = FakeRazorpayAdapter()
    eligible(razorpay)
    engine = RecoveryEngine(ledger, ScriptedStrategist(), razorpay)
    engine.receive(failed_event("evt_a", reason="bank_temporary_error"))
    engine.run(until=1)
    snap = ledger.case_snapshot(case_view(engine, obligation_id=OBLIGATION).case_id)
    assert snap.state == "waiting"  # sanity: the real current state

    result = ledger.apply_capture(
        CaptureCommand(
            case_id=snap.case_id, event_id="evt_stale_state", payment_id="pay_X",
            amount_minor=RUPEES_10K_MINOR, now=1,
            expected_version=snap.version,  # correct version...
            expected_state="active",  # ...but a stale/wrong expected state
        )
    )

    assert result.ok is False and result.reason == "stale_case_state"
    cv = case_view(engine, obligation_id=OBLIGATION)
    assert cv.state == "waiting" and cv.counted is False
    assert batch(engine).recovered_minor == 0
    assert "stale_case_state" in policy_reasons(engine, cv.case_id)


# --- requirement 2: Case 3 initial decision ---------------------------------


def test_insufficient_funds_first_failure_permits_one_wait(engine, razorpay):
    eligible(razorpay)
    r = engine.receive(failed_event("evt_if_1"))

    report = engine.run(until=1)

    assert report.proposals == 1 and report.scheduled == 1 and report.blocked == 0
    cv = case_view(engine, case_id=r.case_id)
    assert cv.state == "waiting" and cv.pending_work == 1
    # WAIT_FOR_PROVIDER_RETRY is provider-side and free; it does not spend any
    # of the merchant-authorized-action budget CREATE_RECOVERY_LINK draws on.
    assert cv.actions_taken == 0
    assert cv.retry_outcome_recorded is False
    assert "AI_PROPOSAL" in audit_kinds(engine, cv.case_id)
    assert "provider_retry_permitted" in policy_reasons(engine, cv.case_id)


# --- requirement 3: failed retry causes adaptation --------------------------


def test_failed_retry_wakes_same_case_and_changes_strategy(engine, razorpay):
    cid = wait_then_fail_retry(engine, razorpay)

    cv = case_view(engine, case_id=cid)
    assert cv.state == "active"  # woken, not still waiting
    assert cv.retry_outcome_recorded is True
    assert cv.pending_work == 1  # exactly one due-now item, not two
    assert batch(engine).cases == 1  # no second case
    assert "RETRY_OUTCOME_RECORDED" in audit_kinds(engine, cid)

    report = engine.run(until=1)

    assert report.proposals == 1
    proposals = [
        r.detail for r in engine.inspect(AuditQuery(case_id=cid)).records
        if r.kind == "AI_PROPOSAL"
    ]
    assert proposals[-1]["action"] == "CREATE_RECOVERY_LINK"  # strategy changed
    assert proposals[0]["action"] == "WAIT_FOR_PROVIDER_RETRY"  # prior evidence preserved


def test_repeated_retry_failure_event_does_not_duplicate_case_or_work(engine, razorpay):
    eligible(razorpay)
    r = engine.receive(failed_event("evt_if_1"))
    engine.run(until=1)
    engine.receive(failed_event("evt_if_2_retry_failed"))

    dup = engine.receive(failed_event("evt_if_2_retry_failed"))  # identical event id

    assert dup.duplicate is True
    assert batch(engine).cases == 1
    assert case_view(engine, case_id=r.case_id).pending_work == 1


# --- requirement 4/5: recovery-link strategy + durable action intent -------


def test_action_intent_is_persisted_before_the_fake_effect_and_link_created(engine, razorpay):
    cid = wait_then_fail_retry(engine, razorpay)

    report = engine.run(until=1)

    assert report.proposals == 1 and report.blocked == 0
    cv = case_view(engine, case_id=cid)
    assert cv.links_created == 1
    assert len(cv.action_intents) == 1
    intent = cv.action_intents[0]
    assert intent.action == "CREATE_RECOVERY_LINK"
    assert intent.status == "executed"
    assert intent.reference is not None and intent.reference != ""
    kinds = audit_kinds(engine, cid)
    # persisted (ACTION_INTENT) strictly before the outcome (ACTION_OUTCOME)
    assert kinds.index("ACTION_INTENT") < kinds.index("ACTION_OUTCOME")


def test_message_intent_authorized_when_merchant_owns_communication(engine, razorpay):
    cid = wait_then_fail_retry(engine, razorpay, customer_notify=False)

    engine.run(until=1)

    cv = case_view(engine, case_id=cid)
    assert cv.communication_owner == "merchant"
    assert cv.messages_sent == 1
    reasons = policy_reasons(engine, cid)
    assert "recovery_link_authorized_message_authorized" in reasons


def test_razorpay_owned_communication_suppresses_merchant_contact(engine, razorpay):
    cid = wait_then_fail_retry(engine, razorpay, customer_notify=True)

    engine.run(until=1)

    cv = case_view(engine, case_id=cid)
    assert cv.communication_owner == "razorpay"
    assert cv.links_created == 1  # the link itself is still authorized
    assert cv.messages_sent == 0  # but the merchant message path is suppressed
    reasons = policy_reasons(engine, cid)
    assert "recovery_link_authorized_message_suppressed_provider_owned" in reasons


def test_duplicate_run_does_not_duplicate_link_or_message(razorpay):
    ledger = InMemoryLedger()
    eligible(razorpay)
    engine = RecoveryEngine(ledger, ScriptedStrategist(), razorpay)
    cid = wait_then_fail_retry(engine, razorpay)
    engine.run(until=1)  # authorizes + executes the one link
    first = case_view(engine, case_id=cid)
    assert first.links_created == 1 and len(first.action_intents) == 1

    # Nothing left due; running again drains no further work for this cycle,
    # so re-authorization can't even be attempted - confirming the one-link
    # limit's own defense (exercised directly below) is real, not merely
    # untested because no second attempt was ever possible.
    again_report = engine.run(until=2)
    assert again_report.steps == 0

    snap = ledger.case_snapshot(cid)
    decision = authorize(
        StrategyProposal(
            action=ProposalAction.CREATE_RECOVERY_LINK,
            diagnosis="d", rationale="r", confidence=0.5,
        ),
        snap, now=2, retry_fact=ProviderRetryFact(OBLIGATION, True, "provider_retry_signal"),
    )
    assert decision.outcome.value == "BLOCK" and decision.reason_code == "recovery_link_limit_reached"

    cv = case_view(engine, case_id=cid)
    assert cv.links_created == 1 and len(cv.action_intents) == 1  # never duplicated


# --- requirement 6: attribution ---------------------------------------------


def test_provider_owned_retry_capture_is_provider_self_recovered(engine, razorpay):
    eligible(razorpay)
    r = engine.receive(failed_event("evt_if_1"))
    engine.run(until=1)  # waiting on the eligible provider retry

    engine.receive(captured_event("evt_cap_ok", payment_id="pay_PROVIDER"))

    cv = case_view(engine, case_id=r.case_id)
    assert cv.state == "recovered"
    assert cv.attribution == "provider_self_recovered"


def test_correlated_alternate_capture_is_hermes_assisted(engine, razorpay):
    cid = wait_then_fail_retry(engine, razorpay)
    engine.run(until=1)  # authorizes + executes the recovery link
    reference = case_view(engine, case_id=cid).action_intents[0].reference

    engine.receive(captured_event("evt_cap_link", payment_id=reference))

    cv = case_view(engine, case_id=cid)
    assert cv.state == "recovered"
    assert cv.attribution == "hermes_assisted"
    assert batch(engine).recovered_minor == RUPEES_10K_MINOR
    assert batch(engine).recovered_cases == 1


def test_recovered_money_remains_exact_once_on_the_case_3_path(engine, razorpay):
    cid = wait_then_fail_retry(engine, razorpay)
    engine.run(until=1)
    reference = case_view(engine, case_id=cid).action_intents[0].reference

    engine.receive(captured_event("evt_cap_link", payment_id=reference))
    engine.receive(captured_event("evt_cap_link", payment_id=reference))  # duplicate event id
    engine.receive(captured_event("evt_cap_link_2", payment_id=reference))  # new event, same payment

    b = batch(engine)
    assert b.recovered_minor == RUPEES_10K_MINOR
    assert b.recovered_payments == 1
    assert b.recovered_cases == 1


# --- direct authorize() unit tests: limits hard to reach organically -------
# (``authorize`` is a public, exported function - not private engine state -
# and CaseSnapshot/StrategyProposal/ProviderRetryFact are public dataclasses.)


def _snap(**overrides) -> CaseSnapshot:
    base = dict(
        case_id="c1", obligation_id=OBLIGATION, amount_minor=RUPEES_10K_MINOR,
        currency="INR", state="active", failure_reason="insufficient_funds", version=1,
        retry_outcome_recorded=True, communication_owner="merchant", consent=True,
        reachable_channel=True, messages_sent=0, links_created=0, actions_taken=0,
        last_contact_time=None,
    )
    base.update(overrides)
    return CaseSnapshot(**base)


def _link_proposal(message_intent="Friendly reminder to complete your payment."):
    return StrategyProposal(
        action=ProposalAction.CREATE_RECOVERY_LINK, diagnosis="d", rationale="r",
        confidence=0.5, message_intent=message_intent,
    )


_RETRY_FACT = ProviderRetryFact(OBLIGATION, True, "provider_retry_signal")


def test_recovery_link_blocked_before_retry_outcome_recorded():
    decision = authorize(_link_proposal(), _snap(retry_outcome_recorded=False), 10, _RETRY_FACT)
    assert decision.outcome.value == "BLOCK" and decision.reason_code == "retry_outcome_not_recorded"


def test_recovery_link_blocked_at_link_limit():
    decision = authorize(_link_proposal(), _snap(links_created=MAX_LINKS_PER_CASE), 10, _RETRY_FACT)
    assert decision.outcome.value == "BLOCK" and decision.reason_code == "recovery_link_limit_reached"


def test_recovery_link_blocked_at_action_limit():
    decision = authorize(_link_proposal(), _snap(actions_taken=MAX_ACTIONS_PER_CASE), 10, _RETRY_FACT)
    assert decision.outcome.value == "BLOCK" and decision.reason_code == "action_limit_reached"


def test_message_suppressed_without_consent():
    decision = authorize(_link_proposal(), _snap(consent=False), 10, _RETRY_FACT)
    assert decision.outcome.value == "ALLOW" and decision.message_authorized is False
    assert decision.reason_code.endswith("no_consent")


def test_message_suppressed_without_reachable_channel():
    decision = authorize(_link_proposal(), _snap(reachable_channel=False), 10, _RETRY_FACT)
    assert decision.outcome.value == "ALLOW" and decision.message_authorized is False
    assert decision.reason_code.endswith("unreachable_channel")


def test_message_suppressed_at_message_count_limit():
    decision = authorize(
        _link_proposal(), _snap(messages_sent=MAX_MESSAGES_PER_CASE), 10, _RETRY_FACT
    )
    assert decision.outcome.value == "ALLOW" and decision.message_authorized is False
    assert decision.reason_code.endswith("message_limit")


def test_message_suppressed_during_cooldown():
    decision = authorize(
        _link_proposal(), _snap(last_contact_time=5), 5 + MESSAGE_COOLDOWN_HOURS - 1, _RETRY_FACT
    )
    assert decision.outcome.value == "ALLOW" and decision.message_authorized is False
    assert decision.reason_code.endswith("cooldown")


def test_message_authorized_after_cooldown_expires():
    decision = authorize(
        _link_proposal(), _snap(last_contact_time=5), 5 + MESSAGE_COOLDOWN_HOURS, _RETRY_FACT
    )
    assert decision.outcome.value == "ALLOW" and decision.message_authorized is True


def test_recovery_link_with_no_message_intent_never_touches_message_policy():
    decision = authorize(_link_proposal(message_intent=None), _snap(consent=False), 10, _RETRY_FACT)
    assert decision.outcome.value == "ALLOW" and decision.message_authorized is False
    assert decision.reason_code == "recovery_link_authorized"


def test_invalid_message_intent_with_url_executes_no_action(razorpay):
    """A strategist proposing a URL in message_intent must never authorize or
    execute anything - the engine treats it as invalid output, exactly like a
    malformed/raised proposal, through the public ``run`` seam."""

    class UrlStrategist:
        def propose(self, snapshot):
            return StrategyProposal(
                action=ProposalAction.CREATE_RECOVERY_LINK, diagnosis="d", rationale="r",
                confidence=0.5, message_intent="Pay now at https://evil.example/pay",
            )

    ledger = InMemoryLedger()
    eligible(razorpay)
    engine = RecoveryEngine(ledger, UrlStrategist(), razorpay)
    r = engine.receive(failed_event("evt_bad_url"))

    report = engine.run(until=1)

    assert report.strategist_failures == 1 and report.proposals == 0
    cv = case_view(engine, case_id=r.case_id)
    assert cv.links_created == 0 and len(cv.action_intents) == 0
    assert "AI_PROPOSAL" not in audit_kinds(engine, cv.case_id)
