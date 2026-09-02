"""Case 1 - temporary bank failure, permitted wait, verified capture, exact-once
recovery accounting. Tested only through RecoveryEngine.receive / run / inspect.
"""

import pytest

from hermes.adapters import FakeRazorpayAdapter, InMemoryLedger, ScriptedStrategist
from hermes.engine import RecoveryEngine
from hermes.types import RazorpayWebhook, WebhookType

RUPEES_10K_MINOR = 10_000 * 100  # paise
OBLIGATION = "sub_INV_0001"


def failed_event(event_id="evt_fail_1", reason="bank_temporary_error"):
    return RazorpayWebhook(
        event_id=event_id,
        type=WebhookType.PAYMENT_FAILED,
        obligation_id=OBLIGATION,
        amount_minor=RUPEES_10K_MINOR,
        reason_code=reason,
    )


def captured_event(event_id="evt_cap_1", payment_id="pay_TEST_1"):
    return RazorpayWebhook(
        event_id=event_id,
        type=WebhookType.PAYMENT_CAPTURED,
        obligation_id=OBLIGATION,
        amount_minor=RUPEES_10K_MINOR,
        payment_id=payment_id,
    )


@pytest.fixture
def engine():
    return RecoveryEngine(
        ledger=InMemoryLedger(),
        strategist=ScriptedStrategist(),
        razorpay=FakeRazorpayAdapter(),
    )


def audit_kinds(engine, case_id=None):
    return [e["kind"] for e in engine.inspect({"kind": "audit", "case_id": case_id})["events"]]


# --- individual behaviours --------------------------------------------------


def test_failed_event_creates_exactly_one_case(engine):
    result = engine.receive(failed_event())
    assert result.accepted and not result.duplicate and result.case_id
    assert engine.inspect({"kind": "batch"})["cases"] == 1
    assert engine.inspect({"kind": "case", "obligation_id": OBLIGATION})["state"] == "active"


def test_duplicate_failed_event_creates_no_duplicate_case_or_transition(engine):
    engine.receive(failed_event())
    before = engine.inspect({"kind": "audit"})["events"]

    dup = engine.receive(failed_event())  # same event_id

    assert dup.duplicate is True
    assert engine.inspect({"kind": "batch"})["cases"] == 1
    assert engine.inspect({"kind": "audit"})["events"] == before  # no new audit rows


def test_run_audits_scripted_proposal_and_policy_authorization(engine):
    engine.receive(failed_event())
    report = engine.run(until=1)

    assert report.proposals == 1
    kinds = audit_kinds(engine)
    assert "AI_PROPOSAL" in kinds
    assert "POLICY_DECISION" in kinds
    assert "SCHEDULED_ACTION" in kinds
    events = engine.inspect({"kind": "audit"})["events"]
    proposal = next(e for e in events if e["kind"] == "AI_PROPOSAL")
    policy = next(e for e in events if e["kind"] == "POLICY_DECISION")
    assert proposal["detail"]["action"] == "WAIT_FOR_PROVIDER_RETRY"
    assert policy["detail"]["outcome"] == "ALLOW"


def test_logical_time_cannot_move_backward(engine):
    engine.receive(failed_event())
    engine.run(until=5)
    with pytest.raises(ValueError):
        engine.run(until=3)


def test_captured_event_recovers_the_linked_case(engine):
    engine.receive(failed_event())
    engine.run(until=1)
    engine.receive(captured_event())

    case = engine.inspect({"kind": "case", "obligation_id": OBLIGATION})
    assert case["state"] == "recovered"
    assert case["linked_payment_id"] == "pay_TEST_1"
    assert "TERMINAL_TRANSITION" in audit_kinds(engine)


def test_captured_event_cancels_pending_work(engine):
    engine.receive(failed_event())
    engine.run(until=1)  # schedules a re-evaluation at hour 24
    case_id = engine.inspect({"kind": "case", "obligation_id": OBLIGATION})["case_id"]
    assert engine.inspect({"kind": "case", "case_id": case_id})["pending_work"] == 1

    engine.receive(captured_event())

    assert engine.inspect({"kind": "case", "case_id": case_id})["pending_work"] == 0
    assert "PENDING_WORK_CANCELLED" in audit_kinds(engine)


def test_duplicate_captured_event_does_not_double_count(engine):
    engine.receive(failed_event())
    engine.run(until=1)
    engine.receive(captured_event())
    engine.receive(captured_event())  # exact duplicate event_id
    engine.receive(captured_event(event_id="evt_cap_2", payment_id="pay_TEST_2"))  # new id, same obligation

    assert engine.inspect({"kind": "batch"})["recovered_minor"] == RUPEES_10K_MINOR


def test_out_of_order_failure_after_capture_does_not_reopen(engine):
    engine.receive(failed_event())
    engine.run(until=1)
    engine.receive(captured_event())

    engine.receive(failed_event(event_id="evt_fail_late", reason="bank_temporary_error"))

    case = engine.inspect({"kind": "case", "obligation_id": OBLIGATION})
    assert case["state"] == "recovered"
    assert engine.inspect({"kind": "batch"})["cases"] == 1


def test_recovered_case_schedules_no_further_work(engine):
    engine.receive(failed_event())
    engine.run(until=1)
    engine.receive(captured_event())
    calls_after_recovery = engine._strategist.calls

    report = engine.run(until=500)  # long jump past any retry window

    assert report.steps == 0 and report.proposals == 0
    assert engine._strategist.calls == calls_after_recovery
    case_id = engine.inspect({"kind": "case", "obligation_id": OBLIGATION})["case_id"]
    assert engine.inspect({"kind": "case", "case_id": case_id})["pending_work"] == 0


def test_batch_recovered_value_equals_unique_captured_amount(engine):
    engine.receive(failed_event())
    engine.run(until=1)
    engine.receive(captured_event())
    engine.receive(captured_event())  # duplicate

    batch = engine.inspect({"kind": "batch"})
    assert batch["recovered_minor"] == RUPEES_10K_MINOR
    assert batch["recovered_cases"] == 1


# --- full path -----------------------------------------------------------


def test_full_case_1_path_integration(engine):
    # 1. trusted failed-subscription event -> one case
    r1 = engine.receive(failed_event())
    case_id = r1.case_id
    assert engine.inspect({"kind": "case", "case_id": case_id})["state"] == "active"

    # 2. run -> scripted WAIT proposal, policy ALLOW, scheduled re-evaluation
    engine.run(until=1)
    assert engine.inspect({"kind": "case", "case_id": case_id})["state"] == "waiting"
    assert engine.inspect({"kind": "case", "case_id": case_id})["pending_work"] == 1

    # 3. clock advances, still no capture -> strategist consulted again, still waiting
    engine.run(until=24)
    assert engine.inspect({"kind": "case", "case_id": case_id})["state"] == "waiting"

    # 4. trusted captured-payment event -> recovered, work cancelled, counted once
    engine.receive(captured_event())
    case = engine.inspect({"kind": "case", "case_id": case_id})
    assert case["state"] == "recovered"
    assert case["counted"] is True
    assert case["pending_work"] == 0

    # 5. further runs change nothing
    engine.run(until=1000)

    # 6. projections
    batch = engine.inspect({"kind": "batch"})
    assert batch == {"cases": 1, "recovered_cases": 1, "recovered_minor": RUPEES_10K_MINOR}

    kinds = audit_kinds(engine, case_id)
    for required in (
        "INPUT_EVENT",
        "AI_PROPOSAL",
        "POLICY_DECISION",
        "SCHEDULED_ACTION",
        "PAYMENT_CONFIRMATION",
        "PENDING_WORK_CANCELLED",
        "TERMINAL_TRANSITION",
    ):
        assert required in kinds, f"missing audit event: {required}"

    # audit trail is append-only and ordered
    seqs = [e["seq"] for e in engine.inspect({"kind": "audit", "case_id": case_id})["events"]]
    assert seqs == sorted(seqs)
