"""Focused tests for the deterministic bounds added this iteration:
the cumulative wait ceiling, the approved-message-template allowlist, the
persisted-clock resume, and model-failure audit linkage. Offline, in-memory.
"""

from __future__ import annotations

import pytest

from hermes.adapters import FakeRazorpayAdapter, InMemoryLedger, ScriptedStrategist
from hermes.engine import MAX_TOTAL_WAIT_HOURS, RecoveryEngine, authorize
from hermes.message_templates import APPROVED_MESSAGE_INTENTS
from hermes.types import (
    AuditQuery,
    CaseQuery,
    ProposalAction,
    ProviderRetryFact,
    RazorpayWebhook,
    StrategyProposal,
    WebhookType,
)

OBL = "sub_bounds_0001"
AMOUNT = 1_000_000


def _failed(eid, obl=OBL):
    return RazorpayWebhook(eid, WebhookType.PAYMENT_FAILED, obl, AMOUNT,
                           reason_code="insufficient_funds", consent=True,
                           reachable_channel=True)


def _kinds(engine, cid):
    return [r.kind for r in engine.inspect(AuditQuery(case_id=cid)).records]


# --- cumulative wait bound -------------------------------------


class AlwaysWait:
    """Proposes a fresh 24h wait every cycle - a model that never adapts."""

    last_run_meta = None

    def propose(self, snapshot):
        return StrategyProposal(
            action=ProposalAction.WAIT_FOR_PROVIDER_RETRY,
            diagnosis="d", rationale="r", confidence=0.5, proposed_wait_hours=24,
        )


def test_authorize_blocks_wait_once_the_total_bound_is_reached():
    fact = ProviderRetryFact(OBL, True, "provider_retry_signal")
    from hermes.types import CaseSnapshot

    def snap(total):
        return CaseSnapshot(
            case_id="c", obligation_id=OBL, amount_minor=AMOUNT, currency="INR",
            state="waiting", failure_reason="insufficient_funds", version=1,
            total_wait_hours=total,
        )

    p = AlwaysWait().propose(None)
    assert authorize(p, snap(0), 0, fact).outcome.value == "ALLOW"
    assert authorize(p, snap(MAX_TOTAL_WAIT_HOURS - 1), 0, fact).outcome.value == "ALLOW"
    d = authorize(p, snap(MAX_TOTAL_WAIT_HOURS), 0, fact)
    assert d.outcome.value == "BLOCK" and d.reason_code == "total_wait_bound_reached"


def test_endless_wait_loop_is_bounded_through_the_engine():
    rp = FakeRazorpayAdapter()
    rp.set_retry_eligibility(OBL, True)  # provider ALWAYS reports eligible
    engine = RecoveryEngine(InMemoryLedger(), AlwaysWait(), rp)
    r = engine.receive(_failed("e0"))

    # advance far past the bound in one-day steps; each authorized wait spends 24h
    now = 0
    for _ in range(10):
        now += 24
        engine.run(until=now)

    cv = engine.inspect(CaseQuery(case_id=r.case_id))
    assert cv.total_wait_hours <= MAX_TOTAL_WAIT_HOURS
    reasons = [
        d.detail.get("reason_code")
        for d in engine.inspect(AuditQuery(case_id=r.case_id)).records
        if d.kind == "POLICY_DECISION"
    ]
    assert "total_wait_bound_reached" in reasons
    # after the bound, no further pending re-evaluation work exists
    assert cv.pending_work == 0


# --- approved message-template allowlist --------------------


class OffAllowlistMessage:
    last_run_meta = None

    def propose(self, snapshot):
        return StrategyProposal(
            action=ProposalAction.CREATE_RECOVERY_LINK, diagnosis="d", rationale="r",
            confidence=0.5,
            message_intent="Hey! Totally casual made-up reminder, click here maybe.",
        )


def test_off_allowlist_message_intent_is_rejected_as_invalid_output():
    rp = FakeRazorpayAdapter()
    rp.set_retry_eligibility(OBL, True)
    engine = RecoveryEngine(InMemoryLedger(), OffAllowlistMessage(), rp)
    r = engine.receive(_failed("e0"))

    report = engine.run(until=1)

    assert report.strategist_failures == 1 and report.proposals == 0
    cv = engine.inspect(CaseQuery(case_id=r.case_id))
    assert cv.links_created == 0 and len(cv.action_intents) == 0
    assert "AI_PROPOSAL" not in _kinds(engine, cv.case_id)


def test_scripted_message_is_on_the_allowlist():
    # the one string ScriptedStrategist emits must stay approved
    scripted_msg = ScriptedStrategist().script[("insufficient_funds", True)].message_intent
    assert scripted_msg in APPROVED_MESSAGE_INTENTS


# --- persisted clock resume ---------------------------------


def test_engine_resumes_the_persisted_clock_from_the_ledger():
    ledger = InMemoryLedger()
    rp = FakeRazorpayAdapter()
    rp.set_retry_eligibility(OBL, True)
    e1 = RecoveryEngine(ledger, ScriptedStrategist(), rp)
    e1.receive(_failed("e0"))
    e1.run(until=30)
    assert ledger.logical_clock() == 30

    # a new engine over the SAME ledger picks up at 30, not 0
    e2 = RecoveryEngine(ledger, ScriptedStrategist(), rp)
    assert e2.logical_time == 30
    with pytest.raises(ValueError):
        e2.run(until=10)  # cannot move backward past the resumed clock


# --- correction 2: zero-hour wait loophole ------------------


class AlwaysZeroWait:
    """A model that keeps proposing WAIT_FOR_PROVIDER_RETRY with 0 hours."""

    last_run_meta = None

    def propose(self, snapshot):
        return StrategyProposal(
            action=ProposalAction.WAIT_FOR_PROVIDER_RETRY,
            diagnosis="d", rationale="r", confidence=0.5, proposed_wait_hours=0,
        )


def test_zero_hour_wait_is_a_bounded_failure_not_a_reschedule_loop():
    from hermes.pg_ledger import InMemorySnapshotStore, PgLedger

    store = InMemorySnapshotStore()
    rp = FakeRazorpayAdapter()
    rp.set_retry_eligibility(OBL, True)  # provider ALWAYS eligible
    engine = RecoveryEngine(PgLedger(store), AlwaysZeroWait(), rp)
    r = engine.receive(_failed("e0"))

    total_failures = 0
    now = 0
    for _ in range(6):  # repeated runs must NOT loop calling the model forever
        now += 6
        total_failures += engine.run(until=now).strategist_failures

    cv = engine.inspect(CaseQuery(case_id=r.case_id))
    assert total_failures >= 1  # invalid output -> bounded failure path
    assert "AI_PROPOSAL" not in _kinds(engine, cv.case_id)  # never rewritten to success
    assert cv.state == "escalated"  # retry budget exhausted -> deterministic terminal
    assert cv.total_wait_hours == 0  # a zero-hour "wait" spent no budget and was never authorized
    assert cv.pending_work == 0

    # persisted: a fresh engine over the same store sees the same terminal state
    engine2 = RecoveryEngine(PgLedger(store), AlwaysZeroWait(), rp)
    assert engine2.inspect(CaseQuery(case_id=r.case_id)).state == "escalated"


def test_positive_wait_within_remaining_budget_is_clamped_and_bounded():
    from hermes.types import CaseSnapshot

    fact = ProviderRetryFact(OBL, True, "provider_retry_signal")
    p = StrategyProposal(action=ProposalAction.WAIT_FOR_PROVIDER_RETRY, diagnosis="d",
                         rationale="r", confidence=0.5, proposed_wait_hours=24)

    def snap(total):
        return CaseSnapshot(case_id="c", obligation_id=OBL, amount_minor=AMOUNT,
                            currency="INR", state="waiting",
                            failure_reason="insufficient_funds", version=1,
                            total_wait_hours=total)

    # 24h proposed, only 3h of budget left -> clamped to 3 (still positive)
    d = authorize(p, snap(MAX_TOTAL_WAIT_HOURS - 3), 100, fact)
    assert d.outcome.value == "ALLOW" and d.scheduled_time == 103
    # 0h of budget left -> blocked, not a zero-hour wait
    d0 = authorize(p, snap(MAX_TOTAL_WAIT_HOURS), 100, fact)
    assert d0.outcome.value == "BLOCK" and d0.reason_code == "total_wait_bound_reached"
