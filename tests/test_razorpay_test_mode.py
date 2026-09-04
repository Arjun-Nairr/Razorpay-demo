"""Offline tests for the Razorpay Test Mode HYBRID slice: real link creation
+ real payment confirmation behind the ``PaymentProvider`` seam, with the
existing simulated SaaS obligation/retry sequence unchanged. All HTTP is
faked (``http_post``/``http_get`` injection) - no live Razorpay call, no live
Gemini call, no new Neon case (in-memory ledger only).

Iteration 16 fully replaces the mutable ``_pending``/``record_capture``/
``verify_capture`` verification path with a single immutable, request-scoped
``verify_link_payment(LinkPaymentClaim)`` call that independently fetches BOTH
the payment and its claimed owning Payment Link. Tests below are grouped by
the five reviewed defects they regress.
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from hermes.adapters import FakeRazorpayAdapter, ScriptedStrategist
from hermes.engine import RecoveryEngine
from hermes.pg_ledger import InMemorySnapshotStore, PgLedger
from hermes.razorpay_test_mode import (
    HybridPaymentProvider,
    LinkPaymentClaim,
    RazorpayTestModeAdapter,
    RealWebhookError,
    _AmbiguousCompletion,
    case_id_from_reference,
    handle_payment_link_paid_webhook,
    load_credentials,
    reference_id_for,
)
from hermes.runtime import Settings
from hermes.types import ProviderActionUncertain, RazorpayWebhook, WebhookType

TEST_KEY_ID = "rzp_test_abc123"
LIVE_KEY_ID = "rzp_live_abc123"
WEBHOOK_SECRET = "razorpay_webhook_secret_for_tests"
AMOUNT = 1_000_000
OBL = "sub_hybrid_0001"


def _demo_sign(raw: bytes) -> str:
    import hashlib
    import hmac

    return hmac.new(WEBHOOK_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def _link_resp(*, link_id, reference_id, amount=AMOUNT, currency="INR",
               status="paid", payments=None):
    d = {"id": link_id, "reference_id": reference_id, "amount": amount,
         "currency": currency, "status": status}
    if payments is not None:
        d["payments"] = payments
    return d


def _payment_resp(*, payment_id, amount=AMOUNT, currency="INR", status="captured"):
    return {"id": payment_id, "amount": amount, "currency": currency, "status": status}


def _pay_entry(payment_id, amount=AMOUNT, status="captured"):
    return {"payment_id": payment_id, "amount": amount, "status": status}


def _get_dispatch(link_resp, payment_resp):
    def fake_get(url, *, auth):
        if "/payment_links/" in url:
            return link_resp
        if "/payments/" in url:
            return payment_resp
        raise AssertionError(f"unexpected GET url: {url}")
    return fake_get


def _paid_envelope(*, link_id, reference_id, payment_id,
                    amount=AMOUNT, currency="INR") -> dict:
    return {
        "entity": "event",
        "event": "payment_link.paid",
        "contains": ["payment_link", "payment"],
        "payload": {
            "payment_link": {"entity": {
                "id": link_id, "reference_id": reference_id,
                "amount": amount, "currency": currency, "status": "paid",
            }},
            "payment": {"entity": {
                "id": payment_id, "amount": amount, "currency": currency,
                "status": "captured",
            }},
        },
    }


def _claim(link_id="plink_x", payment_id="pay_x", reference_id="hermes-case-1",
           amount=AMOUNT, currency="INR", obligation_id=OBL) -> LinkPaymentClaim:
    return LinkPaymentClaim(
        link_id=link_id, payment_id=payment_id, expected_reference_id=reference_id,
        expected_amount_minor=amount, expected_currency=currency, obligation_id=obligation_id,
    )


# === credential / key-id rejection (unchanged behaviour, kept) ===========


def test_adapter_rejects_a_live_key_id():
    with pytest.raises(ValueError, match="Test Mode"):
        RazorpayTestModeAdapter(LIVE_KEY_ID, "secret", enabled=True)


def test_settings_reject_live_key_for_hybrid_provider(monkeypatch):
    monkeypatch.setenv("RAZORPAY_PROVIDER", "hybrid_test_mode")
    monkeypatch.setenv("RAZORPAY_KEY_ID", LIVE_KEY_ID)
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "s")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "w")
    with pytest.raises(RuntimeError, match="Test Mode"):
        Settings.load(mode="offline", load_env=False)


def test_load_credentials_none_when_all_absent():
    assert load_credentials({}) is None


def test_settings_default_provider_is_fake_no_credentials_needed(monkeypatch):
    for k in ("RAZORPAY_PROVIDER", "RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET"):
        monkeypatch.delenv(k, raising=False)
    s = Settings.load(mode="offline", load_env=False)
    assert s.razorpay_provider == "fake" and s.has_razorpay_test_credentials is False


# === disabled by default ==================================================


def test_disabled_adapter_refuses_every_network_call():
    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=False)
    with pytest.raises(RuntimeError, match="disabled"):
        adapter.create_recovery_link("case-1", "k", amount_minor=AMOUNT, currency="INR")
    with pytest.raises(RuntimeError, match="disabled"):
        adapter.verify_link_payment(_claim())


def test_retry_eligibility_is_never_implemented_on_the_real_adapter():
    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True)
    with pytest.raises(NotImplementedError, match="simulated"):
        adapter.retry_eligibility(OBL)


def test_record_capture_and_verify_capture_are_superseded():
    """These protocol methods must never be reachable from the real webhook
    path any more - they now raise, so an accidental call surfaces loudly."""
    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True)
    with pytest.raises(NotImplementedError, match="verify_link_payment"):
        adapter.record_capture(OBL, "pay_x", AMOUNT)
    with pytest.raises(NotImplementedError, match="verify_link_payment"):
        adapter.verify_capture(OBL)


# === notify/reminder/partial disabled, stable + idempotent reference =====


def test_create_recovery_link_disables_notify_reminder_partial_and_is_idempotent():
    calls = []

    def fake_post(url, *, auth, json_body):
        calls.append(json_body)
        return {"id": "plink_abc", "short_url": "https://rzp.io/l/abc"}

    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True, http_post=fake_post)
    link_id = adapter.create_recovery_link("case-42", "k", amount_minor=AMOUNT, currency="INR")
    assert link_id == "plink_abc"
    assert adapter.link_url("case-42") == "https://rzp.io/l/abc"
    body = calls[0]
    assert body["notify"] == {"sms": False, "email": False}
    assert body["reminder_enable"] is False
    assert body["accept_partial"] is False
    assert body["reference_id"] == reference_id_for("case-42")

    link_id_2 = adapter.create_recovery_link("case-42", "k", amount_minor=AMOUNT, currency="INR")
    assert link_id_2 == "plink_abc" and len(calls) == 1  # idempotent, no re-POST


def test_reference_id_over_limit_is_rejected():
    with pytest.raises(ValueError, match="40-char"):
        reference_id_for("case-" + "x" * 40)


# === defect 1: independently verify payment-to-link association ==========


def test_valid_linked_capture_is_confirmed():
    get = _get_dispatch(
        _link_resp(link_id="plink_1", reference_id="hermes-case-1",
                  payments=[_pay_entry("pay_1")]),
        _payment_resp(payment_id="pay_1"),
    )
    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True, http_get=get)
    capture = adapter.verify_link_payment(_claim(link_id="plink_1", payment_id="pay_1",
                                                 reference_id="hermes-case-1"))
    assert capture is not None
    assert capture.payment_id == "pay_1" and capture.link_id == "plink_1"
    assert capture.amount_minor == AMOUNT and capture.currency == "INR"


def test_unrelated_payment_not_listed_on_the_link_is_rejected():
    """A genuinely captured payment that simply never happened via THIS link -
    the old code accepted it because it only fetched the payment and copied
    the caller's claimed link id. Must now be rejected."""
    get = _get_dispatch(
        _link_resp(link_id="plink_2", reference_id="hermes-case-2",
                  payments=[_pay_entry("pay_other")]),  # pay_2 is NOT here
        _payment_resp(payment_id="pay_2"),
    )
    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True, http_get=get)
    capture = adapter.verify_link_payment(_claim(link_id="plink_2", payment_id="pay_2",
                                                 reference_id="hermes-case-2"))
    assert capture is None


def test_a_claimed_link_id_that_does_not_echo_back_is_rejected():
    """The fetched link's OWN id must equal the requested id - defends
    against a provider (or fake) returning the wrong record."""
    get = _get_dispatch(
        _link_resp(link_id="plink_DIFFERENT", reference_id="hermes-case-3",
                  payments=[_pay_entry("pay_3")]),
        _payment_resp(payment_id="pay_3"),
    )
    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True, http_get=get)
    capture = adapter.verify_link_payment(_claim(link_id="plink_3", payment_id="pay_3",
                                                 reference_id="hermes-case-3"))
    assert capture is None


def test_reference_id_mismatch_between_fetched_link_and_case_is_rejected():
    get = _get_dispatch(
        _link_resp(link_id="plink_4", reference_id="hermes-case-WRONG",
                  payments=[_pay_entry("pay_4")]),
        _payment_resp(payment_id="pay_4"),
    )
    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True, http_get=get)
    capture = adapter.verify_link_payment(_claim(link_id="plink_4", payment_id="pay_4",
                                                 reference_id="hermes-case-4"))
    assert capture is None


def test_payment_listed_on_link_but_with_wrong_status_there_is_rejected():
    """The link's OWN bookkeeping of the payment must also show captured -
    a matching payment_id alone is not "evidence this payment belongs to
    this link" if the link's own record disagrees."""
    get = _get_dispatch(
        _link_resp(link_id="plink_5", reference_id="hermes-case-5",
                  payments=[_pay_entry("pay_5", status="failed")]),
        _payment_resp(payment_id="pay_5"),
    )
    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True, http_get=get)
    capture = adapter.verify_link_payment(_claim(link_id="plink_5", payment_id="pay_5",
                                                 reference_id="hermes-case-5"))
    assert capture is None


# === defect 2: reject incomplete or conflicting evidence ==================


def test_missing_currency_on_the_payment_fails_not_falls_back():
    link = _link_resp(link_id="plink_6", reference_id="hermes-case-6",
                      payments=[_pay_entry("pay_6")])
    payment = {"id": "pay_6", "amount": AMOUNT, "status": "captured"}  # no "currency"
    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True,
                                      http_get=_get_dispatch(link, payment))
    capture = adapter.verify_link_payment(_claim(link_id="plink_6", payment_id="pay_6",
                                                 reference_id="hermes-case-6"))
    assert capture is None


def test_missing_currency_on_the_link_fails_not_falls_back():
    link = {"id": "plink_7", "reference_id": "hermes-case-7", "amount": AMOUNT,
            "status": "paid", "payments": [_pay_entry("pay_7")]}  # no "currency"
    payment = _payment_resp(payment_id="pay_7")
    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True,
                                      http_get=_get_dispatch(link, payment))
    capture = adapter.verify_link_payment(_claim(link_id="plink_7", payment_id="pay_7",
                                                 reference_id="hermes-case-7"))
    assert capture is None


def test_mismatched_amount_is_rejected():
    get = _get_dispatch(
        _link_resp(link_id="plink_8", reference_id="hermes-case-8",
                  payments=[_pay_entry("pay_8", amount=AMOUNT - 1)]),
        _payment_resp(payment_id="pay_8", amount=AMOUNT - 1),
    )
    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True, http_get=get)
    capture = adapter.verify_link_payment(_claim(link_id="plink_8", payment_id="pay_8",
                                                 reference_id="hermes-case-8"))
    assert capture is None


def test_mismatched_currency_is_rejected():
    get = _get_dispatch(
        _link_resp(link_id="plink_9", reference_id="hermes-case-9", currency="USD",
                  payments=[_pay_entry("pay_9")]),
        _payment_resp(payment_id="pay_9", currency="USD"),
    )
    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True, http_get=get)
    capture = adapter.verify_link_payment(_claim(link_id="plink_9", payment_id="pay_9",
                                                 reference_id="hermes-case-9", currency="INR"))
    assert capture is None


def test_mismatched_payment_status_is_rejected():
    get = _get_dispatch(
        _link_resp(link_id="plink_10", reference_id="hermes-case-10",
                  payments=[_pay_entry("pay_10")]),
        _payment_resp(payment_id="pay_10", status="authorized"),  # not captured
    )
    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True, http_get=get)
    capture = adapter.verify_link_payment(_claim(link_id="plink_10", payment_id="pay_10",
                                                 reference_id="hermes-case-10"))
    assert capture is None


def test_mismatched_link_status_is_rejected():
    get = _get_dispatch(
        _link_resp(link_id="plink_11", reference_id="hermes-case-11x", status="created",
                  payments=[_pay_entry("pay_11")]),
        _payment_resp(payment_id="pay_11"),
    )
    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True, http_get=get)
    capture = adapter.verify_link_payment(_claim(link_id="plink_11", payment_id="pay_11",
                                                 reference_id="hermes-case-11x"))
    assert capture is None


def test_malformed_readback_responses_do_not_crash():
    """A non-dict GET response (any provider hiccup) must reject, never raise."""
    def bad_get(url, *, auth):
        return ["not", "a", "dict"]

    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True, http_get=bad_get)
    assert adapter.verify_link_payment(_claim()) is None


def test_fetch_failure_rejects_not_raises():
    def boom(url, *, auth):
        raise OSError("connection reset")

    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True, http_get=boom)
    assert adapter.verify_link_payment(_claim()) is None


def test_missing_payments_list_on_link_is_rejected():
    link = {"id": "plink_12", "reference_id": "hermes-case-12", "amount": AMOUNT,
            "currency": "INR", "status": "paid"}  # no "payments" key at all
    payment = _payment_resp(payment_id="pay_12")
    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True,
                                      http_get=_get_dispatch(link, payment))
    capture = adapter.verify_link_payment(_claim(link_id="plink_12", payment_id="pay_12",
                                                 reference_id="hermes-case-12"))
    assert capture is None


# === defect 2 (webhook envelope layer): malformed entities, contradictions


def test_webhook_rejects_malformed_nested_entity_types_without_crashing():
    envelope = {
        "event": "payment_link.paid",
        "payload": {"payment_link": {"entity": "not-a-dict"}, "payment": {"entity": {}}},
    }
    raw = json.dumps(envelope).encode("utf-8")
    engine, provider, _ = _hybrid_engine()
    with pytest.raises(RealWebhookError) as ei:
        handle_payment_link_paid_webhook(
            engine=engine, provider=provider, webhook_secret=WEBHOOK_SECRET,
            raw=raw, signature=_demo_sign(raw), event_id="evt_bad_entity",
        )
    assert ei.value.status_code == 422


def test_webhook_rejects_missing_required_fields():
    envelope = {
        "event": "payment_link.paid",
        "payload": {
            "payment_link": {"entity": {"id": "plink_x"}},  # no reference_id/amount/currency/status
            "payment": {"entity": {"id": "pay_x", "amount": AMOUNT, "currency": "INR"}},
        },
    }
    raw = json.dumps(envelope).encode("utf-8")
    engine, provider, _ = _hybrid_engine()
    with pytest.raises(RealWebhookError) as ei:
        handle_payment_link_paid_webhook(
            engine=engine, provider=provider, webhook_secret=WEBHOOK_SECRET,
            raw=raw, signature=_demo_sign(raw), event_id="evt_missing",
        )
    assert ei.value.status_code == 422


def test_webhook_rejects_contradictory_signed_amount_before_any_provider_call():
    calls = []
    get = lambda url, **k: calls.append(url) or {}
    envelope = _paid_envelope(link_id="plink_x", reference_id="hermes-case-1", payment_id="pay_x")
    # tamper: payment_link claims a different amount than payment
    envelope["payload"]["payment_link"]["entity"]["amount"] = AMOUNT + 1
    raw = json.dumps(envelope).encode("utf-8")
    engine, provider, _ = _hybrid_engine(http_get=get)
    with pytest.raises(RealWebhookError) as ei:
        handle_payment_link_paid_webhook(
            engine=engine, provider=provider, webhook_secret=WEBHOOK_SECRET,
            raw=raw, signature=_demo_sign(raw), event_id="evt_contradict",
        )
    assert ei.value.status_code == 422
    assert calls == []  # rejected before any provider fetch


def test_webhook_rejects_contradictory_signed_currency():
    envelope = _paid_envelope(link_id="plink_x", reference_id="hermes-case-1", payment_id="pay_x")
    envelope["payload"]["payment_link"]["entity"]["currency"] = "USD"
    raw = json.dumps(envelope).encode("utf-8")
    engine, provider, _ = _hybrid_engine()
    with pytest.raises(RealWebhookError) as ei:
        handle_payment_link_paid_webhook(
            engine=engine, provider=provider, webhook_secret=WEBHOOK_SECRET,
            raw=raw, signature=_demo_sign(raw), event_id="evt_contradict_ccy",
        )
    assert ei.value.status_code == 422


# === defect 3: request-specific verification, performed once =============


def test_verify_link_payment_makes_exactly_one_fetch_pair_per_call():
    calls = []

    def counting_get(url, *, auth):
        calls.append(url)
        if "/payment_links/" in url:
            return _link_resp(link_id="plink_13", reference_id="hermes-case-13",
                              payments=[_pay_entry("pay_13")])
        return _payment_resp(payment_id="pay_13")

    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True, http_get=counting_get)
    adapter.verify_link_payment(_claim(link_id="plink_13", payment_id="pay_13",
                                       reference_id="hermes-case-13"))
    assert len(calls) == 2  # one link GET + one payment GET, no more


def test_concurrent_same_case_deliveries_never_mix_evidence():
    """Event A never acquires payment B's evidence: a SHARED adapter instance
    verifies two different payments for the SAME link concurrently, on real
    threads, with A's fetches deliberately delayed so B's complete first (and
    could clobber shared state if any existed). Each call's result must match
    ONLY its own claim."""
    link_id, reference_id = "plink_race", "hermes-case-race"
    both_payments = [_pay_entry("pay_A"), _pay_entry("pay_B")]

    def shared_get(url, *, auth):
        if "/payment_links/" in url:
            if "pay_A" in threading.current_thread().name:
                time.sleep(0.08)  # A's fetch is slower - B finishes first
            return _link_resp(link_id=link_id, reference_id=reference_id,
                              payments=both_payments)
        if "pay_A" in threading.current_thread().name:
            time.sleep(0.08)
            return _payment_resp(payment_id="pay_A")
        return _payment_resp(payment_id="pay_B")

    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True, http_get=shared_get)
    claim_a = _claim(link_id=link_id, payment_id="pay_A", reference_id=reference_id, obligation_id="obl-A")
    claim_b = _claim(link_id=link_id, payment_id="pay_B", reference_id=reference_id, obligation_id="obl-B")
    results: dict = {}

    def run_a():
        results["a"] = adapter.verify_link_payment(claim_a)

    def run_b():
        results["b"] = adapter.verify_link_payment(claim_b)

    ta = threading.Thread(target=run_a, name="worker-pay_A")
    tb = threading.Thread(target=run_b, name="worker-pay_B")
    tb.start(); ta.start()
    ta.join(timeout=5); tb.join(timeout=5)

    assert results["a"] is not None and results["a"].payment_id == "pay_A"
    assert results["a"].obligation_id == "obl-A"
    assert results["b"] is not None and results["b"].payment_id == "pay_B"
    assert results["b"].obligation_id == "obl-B"


def test_handler_makes_exactly_one_verification_call_no_engine_duplicate():
    """Regression for the old handler+engine double-fetch: the engine must
    use the webhook's pre-verified evidence and never call the provider
    again for a REAL_TEST_MODE capture."""
    post = lambda url, **k: {"id": "plink_14", "short_url": "https://rzp.io/l/14"}
    get_calls = []

    def counting_get(url, *, auth):
        get_calls.append(url)
        if "/payment_links/" in url:
            return _link_resp(link_id="plink_14", reference_id=reference_id_for("__CASE__"),
                              payments=[_pay_entry("pay_14")])
        return _payment_resp(payment_id="pay_14")

    engine, provider, led = _hybrid_engine(http_post=post, http_get=counting_get)
    case_id = _drive_to_link(engine, provider)
    reference_id = reference_id_for(case_id)
    # rebuild the link response now that we know the real case_id
    get_calls.clear()

    def counting_get2(url, *, auth):
        get_calls.append(url)
        if "/payment_links/" in url:
            return _link_resp(link_id="plink_14", reference_id=reference_id,
                              payments=[_pay_entry("pay_14")])
        return _payment_resp(payment_id="pay_14")

    provider._real._get = counting_get2  # swap in the case-aware fake for this call only
    envelope = _paid_envelope(link_id="plink_14", reference_id=reference_id, payment_id="pay_14")
    raw = json.dumps(envelope).encode("utf-8")
    handle_payment_link_paid_webhook(
        engine=engine, provider=provider, webhook_secret=WEBHOOK_SECRET,
        raw=raw, signature=_demo_sign(raw), event_id="evt_once",
    )
    assert len(get_calls) == 2  # exactly one link + one payment GET for the whole webhook


# === defect 4: safe outcome for uncertain link creation ===================


def _drive_to_wait_then_retry_failed(engine, provider, obl=OBL):
    provider.set_retry_eligibility(obl, True)
    r = engine.receive(RazorpayWebhook("e_f0", WebhookType.PAYMENT_FAILED, obl, AMOUNT,
                                       reason_code="insufficient_funds"))
    engine.run(until=1)
    engine.receive(RazorpayWebhook("e_r1", WebhookType.PAYMENT_FAILED, obl, AMOUNT,
                                   reason_code="insufficient_funds"))
    provider.set_retry_eligibility(obl, False)
    return r.case_id


def test_ambiguous_creation_persists_a_safe_uncertain_state():
    calls = []

    def flaky_post(url, *, auth, json_body):
        calls.append(1)
        raise _AmbiguousCompletion("TimeoutError")

    engine, provider, led = _hybrid_engine(http_post=flaky_post)
    case_id = _drive_to_wait_then_retry_failed(engine, provider)
    engine.run(until=2)  # triggers create_recovery_link -> ProviderActionUncertain, caught

    proj = led.case_projection(case_id=case_id)
    assert proj.state == "escalated" and proj.attribution == "unrecovered"
    assert proj.linked_payment_id is None  # never recovered
    intent = proj.action_intents[0]
    assert intent.action == "CREATE_RECOVERY_LINK" and intent.status == "uncertain"

    # a further run() never retries automatically - no due work is left, no new POST
    engine.run(until=3)
    assert len(calls) == 1


def test_malformed_creation_response_also_persists_a_safe_uncertain_state():
    engine, provider, led = _hybrid_engine(http_post=lambda url, **k: {"short_url": "x"})  # no "id"
    case_id = _drive_to_wait_then_retry_failed(engine, provider)
    engine.run(until=2)
    proj = led.case_projection(case_id=case_id)
    assert proj.state == "escalated"
    assert proj.action_intents[0].status == "uncertain"


def test_restart_after_a_crash_mid_creation_reconciles_the_pending_intent():
    """A hard crash (not a caught ProviderActionUncertain) leaves the action
    intent "pending" with nothing left to revisit it. A fresh engine over the
    SAME durable store must find and safely resolve it on startup - never
    guess, never silently stay stuck, never auto-retry."""

    def crashing_post(url, *, auth, json_body):
        raise RuntimeError("simulated hard crash mid-POST")  # NOT _AmbiguousCompletion

    store = InMemorySnapshotStore()
    engine1, provider1, led1 = _hybrid_engine(store, http_post=crashing_post)
    case_id = _drive_to_wait_then_retry_failed(engine1, provider1)
    with pytest.raises(RuntimeError):
        engine1.run(until=2)  # "crashes" - uncaught, simulates process death
    led1.close()

    led2 = PgLedger(store)
    engine2 = RecoveryEngine(led2, ScriptedStrategist(), FakeRazorpayAdapter())
    n = engine2.reconcile_uncertain_intents()
    assert n == 1
    proj = led2.case_projection(case_id=case_id)
    assert proj.state == "escalated" and proj.attribution == "unrecovered"
    assert proj.action_intents[0].status == "uncertain"

    # idempotent: a second sweep finds nothing left
    assert engine2.reconcile_uncertain_intents() == 0


def test_provider_success_before_local_persistence_is_still_safe_on_crash():
    """Even if the provider's POST actually succeeded before a crash
    prevented us from recording the outcome, the restart sweep still marks
    the intent uncertain rather than assuming/inventing success - the demo
    never marks a case recovered without a later independently-verified
    payment."""

    def secretly_succeeds_then_crashes(url, *, auth, json_body):
        # simulates: Razorpay received and processed the POST, but the
        # process died before the response was read/handled locally.
        raise RuntimeError("process died after the provider's own success")

    store = InMemorySnapshotStore()
    engine1, provider1, led1 = _hybrid_engine(store, http_post=secretly_succeeds_then_crashes)
    case_id = _drive_to_wait_then_retry_failed(engine1, provider1)
    with pytest.raises(RuntimeError):
        engine1.run(until=2)
    led1.close()

    led2 = PgLedger(store)
    engine2 = RecoveryEngine(led2, ScriptedStrategist(), FakeRazorpayAdapter())
    engine2.reconcile_uncertain_intents()
    proj = led2.case_projection(case_id=case_id)
    assert proj.state == "escalated"  # not recovered - uncertainty, not invented success


# === defect 5: message authorization vs actual delivery ===================


def test_real_provider_never_reports_a_message_as_sent():
    post = lambda url, **k: {"id": "plink_15", "short_url": "https://rzp.io/l/15"}
    engine, provider, led = _hybrid_engine(http_post=post)
    case_id = _drive_to_link(engine, provider)
    proj = led.case_projection(case_id=case_id)
    intent = proj.action_intents[0]
    assert intent.status == "executed"
    assert intent.message_sent is False  # even though the scripted proposal's
    # message_intent WAS authorized by policy (consent/reachable_channel default true)
    assert proj.messages_sent == 0  # the contact counter must not have moved


def test_simulated_flow_message_sent_behaviour_is_unchanged():
    """The existing FakeRazorpayAdapter path has no ``message_delivery_capable``
    attribute and keeps its original, tested behaviour."""
    from hermes.adapters import FakeRazorpayAdapter as Fake

    rp = Fake()
    engine = RecoveryEngine(PgLedger(InMemorySnapshotStore()), ScriptedStrategist(), rp)
    rp.set_retry_eligibility(OBL, True)
    r = engine.receive(RazorpayWebhook("e_f0", WebhookType.PAYMENT_FAILED, OBL, AMOUNT,
                                       reason_code="insufficient_funds"))
    engine.run(until=1)
    engine.receive(RazorpayWebhook("e_r1", WebhookType.PAYMENT_FAILED, OBL, AMOUNT,
                                   reason_code="insufficient_funds"))
    rp.set_retry_eligibility(OBL, False)
    engine.run(until=2)
    proj = engine.inspect(__import__("hermes.types", fromlist=["CaseQuery"]).CaseQuery(case_id=r.case_id))
    assert proj.action_intents[0].message_sent is True  # unchanged simulated behaviour
    assert proj.messages_sent == 1


# === full hybrid engine harness ============================================


def _hybrid_engine(store=None, *, http_post=None, http_get=None):
    real = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True,
                                   http_post=http_post, http_get=http_get)
    provider = HybridPaymentProvider(FakeRazorpayAdapter(), real)
    led = PgLedger(store or InMemorySnapshotStore())
    engine = RecoveryEngine(led, ScriptedStrategist(), provider)
    return engine, provider, led


def _drive_to_link(engine, provider, obl=OBL):
    """failure -> eligible wait -> failed retry -> CREATE_RECOVERY_LINK (real)."""
    return _drive_to_wait_then_retry_failed_and_run(engine, provider, obl)


def _drive_to_wait_then_retry_failed_and_run(engine, provider, obl):
    case_id = _drive_to_wait_then_retry_failed(engine, provider, obl)
    engine.run(until=2)
    return case_id


# === webhook: signature / envelope / correlation / mismatch / dedup ======


def test_webhook_rejects_bad_signature_before_touching_the_body():
    envelope = _paid_envelope(link_id="plink_x", reference_id="hermes-case-1", payment_id="pay_x")
    raw = json.dumps(envelope).encode("utf-8")
    engine, provider, _ = _hybrid_engine()
    with pytest.raises(RealWebhookError) as ei:
        handle_payment_link_paid_webhook(
            engine=engine, provider=provider, webhook_secret=WEBHOOK_SECRET,
            raw=raw, signature="0" * 64, event_id="evt_1",
        )
    assert ei.value.status_code == 401


def test_webhook_rejects_missing_event_id():
    envelope = _paid_envelope(link_id="plink_x", reference_id="hermes-case-1", payment_id="pay_x")
    raw = json.dumps(envelope).encode("utf-8")
    engine, provider, _ = _hybrid_engine()
    with pytest.raises(RealWebhookError) as ei:
        handle_payment_link_paid_webhook(
            engine=engine, provider=provider, webhook_secret=WEBHOOK_SECRET,
            raw=raw, signature=_demo_sign(raw), event_id=None,
        )
    assert ei.value.status_code == 400


def test_webhook_full_happy_path_confirms_and_recovers():
    post = lambda url, **k: {"id": "plink_case2", "short_url": "https://rzp.io/l/case2"}
    engine, provider, led = _hybrid_engine(http_post=post)
    case_id = _drive_to_link(engine, provider)
    reference_id = reference_id_for(case_id)

    def get(url, *, auth):
        if "/payment_links/" in url:
            return _link_resp(link_id="plink_case2", reference_id=reference_id,
                              payments=[_pay_entry("pay_real1")])
        return _payment_resp(payment_id="pay_real1")

    provider._real._get = get
    envelope = _paid_envelope(link_id="plink_case2", reference_id=reference_id, payment_id="pay_real1")
    raw = json.dumps(envelope).encode("utf-8")
    result = handle_payment_link_paid_webhook(
        engine=engine, provider=provider, webhook_secret=WEBHOOK_SECRET,
        raw=raw, signature=_demo_sign(raw), event_id="evt_real_1",
    )
    assert result["accepted"] is True and result["evidence_mode"] == "REAL_TEST_MODE"
    proj = led.case_projection(case_id=case_id)
    assert proj.state == "recovered" and proj.attribution == "hermes_assisted"
    assert proj.linked_payment_id == "pay_real1"


def test_webhook_rejects_a_link_that_does_not_match_this_case():
    post = lambda url, **k: {"id": "plink_case4", "short_url": "https://rzp.io/l/case4"}
    engine, provider, led = _hybrid_engine(http_post=post)
    case_id = _drive_to_link(engine, provider)
    reference_id = reference_id_for(case_id)
    envelope = _paid_envelope(link_id="plink_forged", reference_id=reference_id, payment_id="pay_x")
    raw = json.dumps(envelope).encode("utf-8")
    with pytest.raises(RealWebhookError) as ei:
        handle_payment_link_paid_webhook(
            engine=engine, provider=provider, webhook_secret=WEBHOOK_SECRET,
            raw=raw, signature=_demo_sign(raw), event_id="evt_forged",
        )
    assert ei.value.status_code == 409
    assert led.case_projection(case_id=case_id).state != "recovered"


def test_webhook_rejects_unrecognised_reference_id():
    envelope = _paid_envelope(link_id="plink_x", reference_id="not-hermes-shaped", payment_id="pay_x")
    raw = json.dumps(envelope).encode("utf-8")
    engine, provider, _ = _hybrid_engine()
    with pytest.raises(RealWebhookError) as ei:
        handle_payment_link_paid_webhook(
            engine=engine, provider=provider, webhook_secret=WEBHOOK_SECRET,
            raw=raw, signature=_demo_sign(raw), event_id="evt_unknown",
        )
    assert ei.value.status_code == 422


def test_webhook_rejects_unknown_case():
    envelope = _paid_envelope(link_id="plink_x", reference_id="hermes-case-999", payment_id="pay_x")
    raw = json.dumps(envelope).encode("utf-8")
    engine, provider, _ = _hybrid_engine()
    with pytest.raises(RealWebhookError) as ei:
        handle_payment_link_paid_webhook(
            engine=engine, provider=provider, webhook_secret=WEBHOOK_SECRET,
            raw=raw, signature=_demo_sign(raw), event_id="evt_unknown_case",
        )
    assert ei.value.status_code == 404


def test_webhook_duplicate_event_id_counts_once():
    post = lambda url, **k: {"id": "plink_case5", "short_url": "https://rzp.io/l/case5"}
    engine, provider, led = _hybrid_engine(http_post=post)
    case_id = _drive_to_link(engine, provider)
    reference_id = reference_id_for(case_id)

    def get(url, *, auth):
        if "/payment_links/" in url:
            return _link_resp(link_id="plink_case5", reference_id=reference_id,
                              payments=[_pay_entry("pay_dup")])
        return _payment_resp(payment_id="pay_dup")

    provider._real._get = get
    envelope = _paid_envelope(link_id="plink_case5", reference_id=reference_id, payment_id="pay_dup")
    raw = json.dumps(envelope).encode("utf-8")
    r1 = handle_payment_link_paid_webhook(
        engine=engine, provider=provider, webhook_secret=WEBHOOK_SECRET,
        raw=raw, signature=_demo_sign(raw), event_id="evt_dup_1",
    )
    before = led.batch_projection().recovered_minor
    r2 = handle_payment_link_paid_webhook(
        engine=engine, provider=provider, webhook_secret=WEBHOOK_SECRET,
        raw=raw, signature=_demo_sign(raw), event_id="evt_dup_1",
    )
    assert r1["accepted"] is True
    assert led.batch_projection().recovered_minor == before


def test_out_of_order_delivery_on_a_terminal_case_is_a_safe_no_op():
    post = lambda url, **k: {"id": "plink_case7", "short_url": "https://rzp.io/l/case7"}
    engine, provider, led = _hybrid_engine(http_post=post)
    case_id = _drive_to_link(engine, provider)
    reference_id = reference_id_for(case_id)

    def get(url, *, auth):
        if "/payment_links/" in url:
            return _link_resp(link_id="plink_case7", reference_id=reference_id,
                              payments=[_pay_entry("pay_x7")])
        return _payment_resp(payment_id="pay_x7")

    provider._real._get = get
    envelope = _paid_envelope(link_id="plink_case7", reference_id=reference_id, payment_id="pay_x7")
    raw = json.dumps(envelope).encode("utf-8")
    handle_payment_link_paid_webhook(
        engine=engine, provider=provider, webhook_secret=WEBHOOK_SECRET,
        raw=raw, signature=_demo_sign(raw), event_id="evt_x7_first",
    )
    assert led.case_projection(case_id=case_id).state == "recovered"

    def get_late(url, *, auth):
        if "/payment_links/" in url:
            return _link_resp(link_id="plink_case7", reference_id=reference_id,
                              payments=[_pay_entry("pay_x7"), _pay_entry("pay_x7_late")])
        return _payment_resp(payment_id="pay_x7_late")

    provider._real._get = get_late
    late = _paid_envelope(link_id="plink_case7", reference_id=reference_id, payment_id="pay_x7_late")
    raw_late = json.dumps(late).encode("utf-8")
    result = handle_payment_link_paid_webhook(
        engine=engine, provider=provider, webhook_secret=WEBHOOK_SECRET,
        raw=raw_late, signature=_demo_sign(raw_late), event_id="evt_x7_late",
    )
    assert result["accepted"] is True
    proj = led.case_projection(case_id=case_id)
    assert proj.state == "recovered" and proj.linked_payment_id == "pay_x7"  # unchanged


def test_restart_correlation_survives_a_fresh_engine_over_the_same_store():
    post = lambda url, **k: {"id": "plink_case8", "short_url": "https://rzp.io/l/case8"}
    store = InMemorySnapshotStore()
    engine1, provider1, led1 = _hybrid_engine(store, http_post=post)
    case_id = _drive_to_link(engine1, provider1)
    led1.close()

    real2 = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True)
    provider2 = HybridPaymentProvider(FakeRazorpayAdapter(), real2)
    led2 = PgLedger(store)
    engine2 = RecoveryEngine(led2, ScriptedStrategist(), provider2)

    reference_id = reference_id_for(case_id)

    def get(url, *, auth):
        if "/payment_links/" in url:
            return _link_resp(link_id="plink_case8", reference_id=reference_id,
                              payments=[_pay_entry("pay_x8")])
        return _payment_resp(payment_id="pay_x8")

    real2._get = get
    envelope = _paid_envelope(link_id="plink_case8", reference_id=reference_id, payment_id="pay_x8")
    raw = json.dumps(envelope).encode("utf-8")
    result = handle_payment_link_paid_webhook(
        engine=engine2, provider=provider2, webhook_secret=WEBHOOK_SECRET,
        raw=raw, signature=_demo_sign(raw), event_id="evt_x8",
    )
    assert result["accepted"] is True
    proj = led2.case_projection(case_id=case_id)
    assert proj.state == "recovered" and proj.attribution == "hermes_assisted"


def test_case_id_from_reference_round_trips():
    assert case_id_from_reference(reference_id_for("case-77")) == "case-77"
    assert case_id_from_reference("not-hermes-shaped") is None
