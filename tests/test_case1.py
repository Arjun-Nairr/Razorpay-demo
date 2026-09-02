"""Case 1 - temporary bank failure, permitted wait, verified capture, exact-once
recovery accounting - plus the corrective-iteration guarantees.

Every test drives only the public RecoveryEngine surface: ``receive`` results,
``run`` reports, ``inspect`` projections, and public exceptions. No test touches
a private attribute.
"""

import pathlib

import pytest

from hermes.adapters import FakeRazorpayAdapter, InMemoryLedger, ScriptedStrategist
from hermes.engine import RecoveryEngine
from hermes.types import AuditQuery, BatchQuery, CaseQuery, RazorpayWebhook, WebhookType

RUPEES_10K_MINOR = 10_000 * 100  # paise
OBLIGATION = "sub_INV_0001"
OBLIGATION_2 = "sub_INV_0002"


def failed_event(event_id="evt_fail_1", obligation=OBLIGATION,
                 reason="bank_temporary_error", amount=RUPEES_10K_MINOR):
    return RazorpayWebhook(
        event_id, WebhookType.PAYMENT_FAILED, obligation, amount, reason_code=reason
    )


def captured_event(event_id="evt_cap_1", obligation=OBLIGATION,
                   payment_id="pay_TEST_1", amount=RUPEES_10K_MINOR):
    return RazorpayWebhook(
        event_id, WebhookType.PAYMENT_CAPTURED, obligation, amount, payment_id=payment_id
    )


class BoomStrategist:
    """Strategist that always fails (stands in for raise / timeout / junk)."""

    def __init__(self, exc=TimeoutError("gemini timeout")):
        self._exc = exc

    def propose(self, snapshot):
        raise self._exc


@pytest.fixture
def razorpay():
    return FakeRazorpayAdapter()


@pytest.fixture
def engine(razorpay):
    return RecoveryEngine(
        ledger=InMemoryLedger(), strategist=ScriptedStrategist(), razorpay=razorpay
    )


def case_view(engine, **kw):
    return engine.inspect(CaseQuery(**kw))


def batch(engine):
    return engine.inspect(BatchQuery())


def audit_kinds(engine, case_id=None):
    return engine.inspect(AuditQuery(case_id=case_id)).kinds()


# --- regression: existing Case 1 behaviour ---------------------------------


def test_failed_event_creates_one_case(engine):
    result = engine.receive(failed_event())
    assert result.accepted and not result.duplicate and result.case_id
    assert batch(engine).cases == 1
    assert case_view(engine, obligation_id=OBLIGATION).state == "active"


def test_duplicate_event_creates_no_duplicate_transition(engine):
    engine.receive(failed_event())
    before = engine.inspect(AuditQuery()).records

    dup = engine.receive(failed_event())  # same event_id

    assert dup.duplicate is True
    assert batch(engine).cases == 1
    assert engine.inspect(AuditQuery()).records == before


def test_logical_time_remains_monotonic(engine):
    engine.receive(failed_event())
    engine.run(until=5)
    with pytest.raises(ValueError):
        engine.run(until=4)


def test_verified_capture_recovers_the_correct_case(engine):
    engine.receive(failed_event(event_id="f1", obligation=OBLIGATION))
    engine.receive(failed_event(event_id="f2", obligation=OBLIGATION_2))
    engine.run(until=1)

    engine.receive(captured_event(obligation=OBLIGATION, payment_id="pay_A"))

    assert case_view(engine, obligation_id=OBLIGATION).state == "recovered"
    assert case_view(engine, obligation_id=OBLIGATION).linked_payment_id == "pay_A"
    assert case_view(engine, obligation_id=OBLIGATION_2).state != "recovered"


def test_capture_atomically_cancels_work_and_updates_metrics(engine):
    engine.receive(failed_event())
    engine.run(until=1)  # schedules a re-evaluation
    cid = case_view(engine, obligation_id=OBLIGATION).case_id
    assert case_view(engine, case_id=cid).pending_work == 1

    engine.receive(captured_event())

    cv = case_view(engine, case_id=cid)
    assert cv.pending_work == 0 and cv.counted is True
    b = batch(engine)
    assert b.recovered_minor == RUPEES_10K_MINOR and b.recovered_cases == 1
    kinds = audit_kinds(engine, cid)
    for part in ("PAYMENT_CONFIRMATION", "PENDING_WORK_CANCELLED", "TERMINAL_TRANSITION"):
        assert part in kinds


def test_out_of_order_failure_cannot_reopen_recovery(engine):
    engine.receive(failed_event())
    engine.run(until=1)
    engine.receive(captured_event())

    engine.receive(failed_event(event_id="evt_fail_late"))

    assert case_view(engine, obligation_id=OBLIGATION).state == "recovered"
    assert batch(engine).cases == 1
    assert engine.run(until=100).steps == 0


def test_terminal_cases_schedule_no_further_work(engine):
    engine.receive(failed_event())
    engine.run(until=1)
    engine.receive(captured_event())
    cid = case_view(engine, obligation_id=OBLIGATION).case_id
    before = engine.inspect(AuditQuery(case_id=cid)).records

    report = engine.run(until=1000)

    assert (report.steps, report.proposals, report.scheduled) == (0, 0, 0)
    # no strategist call, no new audit rows
    assert engine.inspect(AuditQuery(case_id=cid)).records == before
    assert case_view(engine, case_id=cid).pending_work == 0


def test_batch_recovered_value_remains_correct(engine):
    engine.receive(failed_event())
    engine.run(until=1)
    engine.receive(captured_event())
    engine.receive(captured_event())  # duplicate

    b = batch(engine)
    assert b.recovered_minor == RUPEES_10K_MINOR
    assert b.recovered_cases == 1


# --- correction 1: provider retry eligibility ----------------------------


def test_retry_eligible_state_allows_wait(engine, razorpay):
    razorpay.set_retry_eligibility(OBLIGATION, True)
    engine.receive(failed_event())

    report = engine.run(until=1)

    assert report.scheduled == 1 and report.blocked == 0
    cv = case_view(engine, obligation_id=OBLIGATION)
    assert cv.state == "waiting" and cv.pending_work == 1


def test_retry_ineligible_state_blocks_wait(engine, razorpay):
    razorpay.set_retry_eligibility(OBLIGATION, False)
    engine.receive(failed_event())

    report = engine.run(until=1)

    assert report.blocked == 1 and report.scheduled == 0
    cv = case_view(engine, obligation_id=OBLIGATION)
    assert cv.state == "active" and cv.pending_work == 0
    records = engine.inspect(AuditQuery(case_id=cv.case_id)).records
    policy = next(r for r in records if r.kind == "POLICY_DECISION")
    assert policy.detail["outcome"] == "BLOCK"
    assert policy.detail["reason_code"] == "provider_retry_ineligible"


# --- correction 2: safe strategist failure -----------------------------


def test_strategist_failure_loses_no_work_and_executes_no_action(razorpay):
    engine = RecoveryEngine(
        ledger=InMemoryLedger(), strategist=BoomStrategist(), razorpay=razorpay
    )
    engine.receive(failed_event())

    report = engine.run(until=1)

    assert report.strategist_failures == 1 and report.proposals == 0
    cv = case_view(engine, obligation_id=OBLIGATION)
    assert cv.state == "active" and cv.counted is False
    assert cv.pending_work == 1  # retryable work preserved, not lost
    kinds = audit_kinds(engine, cv.case_id)
    assert "STRATEGIST_FAILURE" in kinds and "AI_PROPOSAL" not in kinds
    assert batch(engine).recovered_minor == 0


def test_strategist_failure_retry_is_bounded(razorpay):
    engine = RecoveryEngine(
        ledger=InMemoryLedger(), strategist=BoomStrategist(), razorpay=razorpay
    )
    engine.receive(failed_event())

    failures = sum(engine.run(until=t).strategist_failures for t in range(1, 12))

    assert failures == 3  # initial attempt + 2 bounded retries, then it stops
    cv = case_view(engine, obligation_id=OBLIGATION)
    assert cv.pending_work == 0
    assert "AI_PROPOSAL" not in audit_kinds(engine, cv.case_id)
    assert engine.run(until=50).steps == 0  # no infinite retry loop


def test_strategist_invalid_output_is_treated_as_failure(razorpay):
    class JunkStrategist:
        def propose(self, snapshot):
            return {"action": "WAIT_FOR_PROVIDER_RETRY"}  # not a typed proposal

    engine = RecoveryEngine(
        ledger=InMemoryLedger(), strategist=JunkStrategist(), razorpay=razorpay
    )
    engine.receive(failed_event())

    report = engine.run(until=1)

    assert report.strategist_failures == 1 and report.proposals == 0
    assert "AI_PROPOSAL" not in audit_kinds(engine, case_view(engine, obligation_id=OBLIGATION).case_id)


# --- correction 4: global payment-id deduplication --------------------


def test_duplicate_payment_id_never_double_counts(engine):
    engine.receive(failed_event())
    engine.run(until=1)
    engine.receive(captured_event())  # counts once
    engine.receive(captured_event())  # same event_id -> duplicate
    engine.receive(captured_event(event_id="evt_cap_dup"))  # new event_id, same payment_id

    assert batch(engine).recovered_minor == RUPEES_10K_MINOR
    assert batch(engine).recovered_payments == 1


def test_one_payment_id_cannot_recover_two_obligations(engine):
    engine.receive(failed_event(event_id="f1", obligation=OBLIGATION))
    engine.receive(failed_event(event_id="f2", obligation=OBLIGATION_2))
    engine.run(until=1)

    engine.receive(captured_event(event_id="c1", obligation=OBLIGATION, payment_id="pay_SHARED"))
    engine.receive(captured_event(event_id="c2", obligation=OBLIGATION_2, payment_id="pay_SHARED"))

    b = batch(engine)
    assert b.recovered_minor == RUPEES_10K_MINOR
    assert b.recovered_cases == 1
    assert b.recovered_payments == 1
    cv2 = case_view(engine, obligation_id=OBLIGATION_2)
    assert cv2.state != "recovered"
    reasons = [
        r.detail.get("reason_code")
        for r in engine.inspect(AuditQuery(case_id=cv2.case_id)).records
        if r.kind == "POLICY_DECISION"
    ]
    assert "payment_id_already_recovered" in reasons


# --- correction 5: typed inspect interface ---------------------------


def test_inspect_returns_typed_projections(engine):
    from hermes.types import AuditProjection, BatchProjection, CaseProjection

    engine.receive(failed_event())
    engine.run(until=1)

    assert isinstance(case_view(engine, obligation_id=OBLIGATION), CaseProjection)
    assert isinstance(batch(engine), BatchProjection)
    assert isinstance(engine.inspect(AuditQuery()), AuditProjection)


def test_inspect_rejects_unknown_query_type(engine):
    with pytest.raises(TypeError):
        engine.inspect({"kind": "case"})  # legacy dict query no longer supported


# --- correction 6: public-seam-only tests ---------------------------


def test_tests_use_only_public_recovery_engine_interface():
    source = pathlib.Path(__file__).read_text()
    dot = "."
    for attr in ("_ledger", "_strategist", "_razorpay", "_clock", "_snapshot", "_cases"):
        needle = "engine" + dot + attr
        assert needle not in source, f"test file reaches into {needle}"


# --- full Case 1 path ----------------------------------------------


def test_full_case_1_path_integration(engine, razorpay):
    razorpay.set_retry_eligibility(OBLIGATION, True)

    r1 = engine.receive(failed_event())
    cid = r1.case_id
    assert case_view(engine, case_id=cid).state == "active"

    rep1 = engine.run(until=1)
    assert rep1.proposals == 1 and rep1.scheduled == 1 and rep1.strategist_failures == 0
    assert case_view(engine, case_id=cid).state == "waiting"
    assert case_view(engine, case_id=cid).pending_work == 1

    engine.run(until=25)  # second eligible re-evaluation, still no capture
    assert case_view(engine, case_id=cid).state == "waiting"

    engine.receive(captured_event())
    cv = case_view(engine, case_id=cid)
    assert cv.state == "recovered" and cv.counted is True and cv.pending_work == 0

    engine.run(until=1000)  # nothing left to do

    b = batch(engine)
    assert (b.cases, b.recovered_cases, b.recovered_minor, b.recovered_payments) == (
        1, 1, RUPEES_10K_MINOR, 1,
    )

    kinds = audit_kinds(engine, cid)
    for required in (
        "INPUT_EVENT", "AI_PROPOSAL", "POLICY_DECISION", "SCHEDULED_ACTION",
        "PAYMENT_CONFIRMATION", "PENDING_WORK_CANCELLED", "TERMINAL_TRANSITION",
    ):
        assert required in kinds, f"missing audit event: {required}"

    seqs = [r.seq for r in engine.inspect(AuditQuery(case_id=cid)).records]
    assert seqs == sorted(seqs)  # append-only, ordered
