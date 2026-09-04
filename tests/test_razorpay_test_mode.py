"""Offline tests for the Razorpay Test Mode HYBRID slice: real link creation
+ real payment confirmation behind the ``PaymentProvider`` seam, with the
existing simulated SaaS obligation/retry sequence unchanged. All HTTP is
faked (``http_post``/``http_get`` injection) - no live Razorpay call, no live
Gemini call, no new Neon case (in-memory ledger only).
"""

from __future__ import annotations

import json

import pytest

from hermes.adapters import FakeRazorpayAdapter, InMemoryLedger, ScriptedStrategist
from hermes.engine import RecoveryEngine
from hermes.pg_ledger import InMemorySnapshotStore, PgLedger
from hermes.razorpay_test_mode import (
    HybridPaymentProvider,
    RazorpayTestModeAdapter,
    RealWebhookError,
    _AmbiguousCompletion,
    case_id_from_reference,
    handle_payment_link_paid_webhook,
    load_credentials,
    reference_id_for,
)
from hermes.runtime import Settings
from hermes.types import RazorpayWebhook, WebhookType

TEST_KEY_ID = "rzp_test_abc123"
LIVE_KEY_ID = "rzp_live_abc123"
WEBHOOK_SECRET = "razorpay_webhook_secret_for_tests"
AMOUNT = 1_000_000
OBL = "sub_hybrid_0001"


def _demo_sign(raw: bytes) -> str:
    import hashlib
    import hmac

    return hmac.new(WEBHOOK_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def _paid_envelope(*, link_id: str, reference_id: str, payment_id: str,
                    amount: int = AMOUNT, currency: str = "INR", status: str = "captured") -> dict:
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
                "status": status,
            }},
        },
    }


# --- credential / key-id rejection --------------------------------------


def test_adapter_rejects_a_live_key_id():
    with pytest.raises(ValueError, match="Test Mode"):
        RazorpayTestModeAdapter(LIVE_KEY_ID, "secret", enabled=True)


def test_adapter_rejects_blank_key_id():
    with pytest.raises(ValueError):
        RazorpayTestModeAdapter("", "secret", enabled=True)


def test_settings_reject_live_key_for_hybrid_provider(monkeypatch):
    monkeypatch.setenv("RAZORPAY_PROVIDER", "hybrid_test_mode")
    monkeypatch.setenv("RAZORPAY_KEY_ID", LIVE_KEY_ID)
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "s")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "w")
    with pytest.raises(RuntimeError, match="Test Mode"):
        Settings.load(mode="offline", load_env=False)


def test_settings_require_all_three_hybrid_credentials(monkeypatch):
    monkeypatch.setenv("RAZORPAY_PROVIDER", "hybrid_test_mode")
    monkeypatch.setenv("RAZORPAY_KEY_ID", TEST_KEY_ID)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    monkeypatch.delenv("RAZORPAY_WEBHOOK_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="RAZORPAY_KEY_SECRET"):
        Settings.load(mode="offline", load_env=False)


def test_load_credentials_none_when_all_absent(monkeypatch):
    for k in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET"):
        monkeypatch.delenv(k, raising=False)
    assert load_credentials({}) is None


def test_settings_default_provider_is_fake_no_credentials_needed(monkeypatch):
    for k in ("RAZORPAY_PROVIDER", "RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET"):
        monkeypatch.delenv(k, raising=False)
    s = Settings.load(mode="offline", load_env=False)
    assert s.razorpay_provider == "fake" and s.has_razorpay_test_credentials is False


# --- disabled by default --------------------------------------------------


def test_disabled_adapter_refuses_every_network_call():
    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=False)
    with pytest.raises(RuntimeError, match="disabled"):
        adapter.create_recovery_link("case-1", "k", amount_minor=AMOUNT, currency="INR")
    with pytest.raises(RuntimeError, match="disabled"):
        adapter.record_capture(OBL, "pay_x", AMOUNT)
    with pytest.raises(RuntimeError, match="disabled"):
        adapter.verify_capture(OBL)


def test_retry_eligibility_is_never_implemented_on_the_real_adapter():
    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True)
    with pytest.raises(NotImplementedError, match="simulated"):
        adapter.retry_eligibility(OBL)


def test_hybrid_provider_routes_retry_eligibility_to_the_simulated_half():
    simulated = FakeRazorpayAdapter()
    simulated.set_retry_eligibility(OBL, True)
    real = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True)
    hybrid = HybridPaymentProvider(simulated, real)
    fact = hybrid.retry_eligibility(OBL)
    assert fact.retry_eligible is True  # never reaches the real adapter's NotImplementedError


# --- create_recovery_link: disabled notifications, stable reference, idempotent


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
    assert len(body["reference_id"]) <= 40

    # second call for the SAME case does not re-POST - idempotent within the process
    link_id_2 = adapter.create_recovery_link("case-42", "k", amount_minor=AMOUNT, currency="INR")
    assert link_id_2 == "plink_abc" and len(calls) == 1


def test_create_recovery_link_requires_amount_and_currency():
    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True,
                                      http_post=lambda *a, **k: {"id": "plink_x"})
    with pytest.raises(ValueError):
        adapter.create_recovery_link("case-1", "k")


def test_ambiguous_post_completion_never_retries_with_a_new_reference():
    calls = []

    def flaky_post(url, *, auth, json_body):
        calls.append(json_body["reference_id"])
        raise _AmbiguousCompletion("TimeoutError")

    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True, http_post=flaky_post)
    with pytest.raises(RuntimeError, match="reconcile"):
        adapter.create_recovery_link("case-9", "k", amount_minor=AMOUNT, currency="INR")
    # a second attempt (e.g. an operator retry after manual reconciliation)
    # would use the SAME reference_id, never a fresh one that could double-collect
    with pytest.raises(RuntimeError, match="reconcile"):
        adapter.create_recovery_link("case-9", "k", amount_minor=AMOUNT, currency="INR")
    assert len(set(calls)) == 1


def test_reference_id_over_limit_is_rejected():
    with pytest.raises(ValueError, match="40-char"):
        reference_id_for("case-" + "x" * 40)


# --- verify_capture: real provider readback, never trusts the claim ------


def test_verify_capture_confirms_via_independent_get():
    def fake_get(url, *, auth):
        assert url.endswith("/pay_real123")
        return {"status": "captured", "amount": AMOUNT, "currency": "INR"}

    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True, http_get=fake_get)
    adapter.record_capture(OBL, "pay_real123", AMOUNT, link_id="plink_abc")
    capture = adapter.verify_capture(OBL)
    assert capture is not None
    assert capture.payment_id == "pay_real123" and capture.amount_minor == AMOUNT
    assert capture.currency == "INR" and capture.link_id == "plink_abc"


def test_verify_capture_rejects_a_non_captured_status():
    """Partial payments / authorized-but-not-captured must be rejected."""
    adapter = RazorpayTestModeAdapter(
        TEST_KEY_ID, "secret", enabled=True,
        http_get=lambda url, **k: {"status": "authorized", "amount": AMOUNT, "currency": "INR"},
    )
    adapter.record_capture(OBL, "pay_x", AMOUNT)
    assert adapter.verify_capture(OBL) is None


def test_verify_capture_rejects_when_fetch_fails():
    def boom(url, *, auth):
        raise OSError("connection reset")

    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True, http_get=boom)
    adapter.record_capture(OBL, "pay_x", AMOUNT)
    assert adapter.verify_capture(OBL) is None  # unverified -> reject, never guess


def test_verify_capture_with_nothing_pending_is_none():
    adapter = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True)
    assert adapter.verify_capture("unknown-obl") is None


# --- full hybrid engine harness: drive to an authorized recovery link -----


def _fake_post_factory(link_id: str, url: str):
    def fake_post(url_, *, auth, json_body):
        return {"id": link_id, "short_url": url}
    return fake_post


def _fake_get_factory(*, status: str, amount: int, currency: str):
    def fake_get(url, *, auth):
        return {"status": status, "amount": amount, "currency": currency}
    return fake_get


def _hybrid_engine(store=None, *, http_post=None, http_get=None):
    real = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True,
                                   http_post=http_post, http_get=http_get)
    provider = HybridPaymentProvider(FakeRazorpayAdapter(), real)
    led = PgLedger(store or InMemorySnapshotStore())
    engine = RecoveryEngine(led, ScriptedStrategist(), provider)
    return engine, provider, led


def _drive_to_link(engine, provider, obl=OBL):
    """failure -> eligible wait -> failed retry -> CREATE_RECOVERY_LINK (real)."""
    provider.set_retry_eligibility(obl, True)
    r = engine.receive(RazorpayWebhook("e_f0", WebhookType.PAYMENT_FAILED, obl, AMOUNT,
                                       reason_code="insufficient_funds"))
    engine.run(until=1)
    engine.receive(RazorpayWebhook("e_r1", WebhookType.PAYMENT_FAILED, obl, AMOUNT,
                                   reason_code="insufficient_funds"))
    provider.set_retry_eligibility(obl, False)
    engine.run(until=2)
    return r.case_id


def test_real_link_creation_persists_reference_and_url_before_success():
    post = _fake_post_factory("plink_case1", "https://rzp.io/l/case1")
    engine, provider, led = _hybrid_engine(http_post=post)
    case_id = _drive_to_link(engine, provider)
    proj = led.case_projection(case_id=case_id)
    intent = proj.action_intents[0]
    assert intent.action == "CREATE_RECOVERY_LINK" and intent.status == "executed"
    assert intent.reference == "plink_case1"
    assert intent.url == "https://rzp.io/l/case1"


# --- webhook: signature, envelope, correlation, mismatch, dedup, restart --


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
    post = _fake_post_factory("plink_case2", "https://rzp.io/l/case2")
    get = _fake_get_factory(status="captured", amount=AMOUNT, currency="INR")
    engine, provider, led = _hybrid_engine(http_post=post, http_get=get)
    case_id = _drive_to_link(engine, provider)
    reference_id = reference_id_for(case_id)
    envelope = _paid_envelope(link_id="plink_case2", reference_id=reference_id, payment_id="pay_real1")
    raw = json.dumps(envelope).encode("utf-8")
    result = handle_payment_link_paid_webhook(
        engine=engine, provider=provider, webhook_secret=WEBHOOK_SECRET,
        raw=raw, signature=_demo_sign(raw), event_id="evt_real_1",
    )
    assert result["accepted"] is True and result["evidence_mode"] == "REAL_TEST_MODE"
    proj = led.case_projection(case_id=case_id)
    assert proj.state == "recovered" and proj.attribution == "hermes_assisted"
    assert proj.linked_payment_id == "pay_real1"  # payment id, distinct from the link id


def test_webhook_rejects_amount_mismatch():
    post = _fake_post_factory("plink_case3", "https://rzp.io/l/case3")
    get = _fake_get_factory(status="captured", amount=AMOUNT - 1, currency="INR")  # partial
    engine, provider, led = _hybrid_engine(http_post=post, http_get=get)
    case_id = _drive_to_link(engine, provider)
    reference_id = reference_id_for(case_id)
    envelope = _paid_envelope(link_id="plink_case3", reference_id=reference_id,
                              payment_id="pay_partial", amount=AMOUNT - 1)
    raw = json.dumps(envelope).encode("utf-8")
    with pytest.raises(RealWebhookError) as ei:
        handle_payment_link_paid_webhook(
            engine=engine, provider=provider, webhook_secret=WEBHOOK_SECRET,
            raw=raw, signature=_demo_sign(raw), event_id="evt_partial",
        )
    assert ei.value.status_code == 409
    assert led.case_projection(case_id=case_id).state != "recovered"


def test_webhook_rejects_currency_mismatch():
    post = _fake_post_factory("plink_case3b", "https://rzp.io/l/case3b")
    get = _fake_get_factory(status="captured", amount=AMOUNT, currency="USD")
    engine, provider, led = _hybrid_engine(http_post=post, http_get=get)
    case_id = _drive_to_link(engine, provider)
    reference_id = reference_id_for(case_id)
    envelope = _paid_envelope(link_id="plink_case3b", reference_id=reference_id,
                              payment_id="pay_usd", currency="USD")
    raw = json.dumps(envelope).encode("utf-8")
    with pytest.raises(RealWebhookError) as ei:
        handle_payment_link_paid_webhook(
            engine=engine, provider=provider, webhook_secret=WEBHOOK_SECRET,
            raw=raw, signature=_demo_sign(raw), event_id="evt_usd",
        )
    assert ei.value.status_code == 409
    assert led.case_projection(case_id=case_id).state != "recovered"


def test_webhook_rejects_a_link_that_does_not_match_this_case():
    post = _fake_post_factory("plink_case4", "https://rzp.io/l/case4")
    get = _fake_get_factory(status="captured", amount=AMOUNT, currency="INR")
    engine, provider, led = _hybrid_engine(http_post=post, http_get=get)
    case_id = _drive_to_link(engine, provider)
    reference_id = reference_id_for(case_id)
    # a DIFFERENT link id than the one actually created/persisted for this case
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
    post = _fake_post_factory("plink_case5", "https://rzp.io/l/case5")
    get = _fake_get_factory(status="captured", amount=AMOUNT, currency="INR")
    engine, provider, led = _hybrid_engine(http_post=post, http_get=get)
    case_id = _drive_to_link(engine, provider)
    reference_id = reference_id_for(case_id)
    envelope = _paid_envelope(link_id="plink_case5", reference_id=reference_id, payment_id="pay_dup")
    raw = json.dumps(envelope).encode("utf-8")
    r1 = handle_payment_link_paid_webhook(
        engine=engine, provider=provider, webhook_secret=WEBHOOK_SECRET,
        raw=raw, signature=_demo_sign(raw), event_id="evt_dup_1",
    )
    before = led.batch_projection().recovered_minor
    # same event id replayed (provider redelivery) - a silent no-op, never a
    # second confirmation
    r2 = handle_payment_link_paid_webhook(
        engine=engine, provider=provider, webhook_secret=WEBHOOK_SECRET,
        raw=raw, signature=_demo_sign(raw), event_id="evt_dup_1",
    )
    assert r1["accepted"] is True
    assert led.batch_projection().recovered_minor == before  # unchanged


def test_webhook_duplicate_across_event_types_counts_once():
    """The SAME payment confirmed once via the real payment_link.paid webhook,
    then again via a (hypothetical) differently-event-id'd delivery, must not
    double-count - dedup is by payment id, not just event id."""
    post = _fake_post_factory("plink_case6", "https://rzp.io/l/case6")
    get = _fake_get_factory(status="captured", amount=AMOUNT, currency="INR")
    engine, provider, led = _hybrid_engine(http_post=post, http_get=get)
    case_id = _drive_to_link(engine, provider)
    reference_id = reference_id_for(case_id)
    envelope = _paid_envelope(link_id="plink_case6", reference_id=reference_id, payment_id="pay_x6")
    raw = json.dumps(envelope).encode("utf-8")
    handle_payment_link_paid_webhook(
        engine=engine, provider=provider, webhook_secret=WEBHOOK_SECRET,
        raw=raw, signature=_demo_sign(raw), event_id="evt_x6_a",
    )
    recovered_after_first = led.batch_projection().recovered_minor
    # different event_id but the case is already terminal (recovered) - the
    # engine's own terminal-state guard rejects any further transition
    result2 = handle_payment_link_paid_webhook(
        engine=engine, provider=provider, webhook_secret=WEBHOOK_SECRET,
        raw=raw, signature=_demo_sign(raw), event_id="evt_x6_b",
    )
    assert result2["accepted"] is True  # a benign no-op, not an error
    assert led.batch_projection().recovered_minor == recovered_after_first


def test_out_of_order_delivery_on_a_terminal_case_is_a_safe_no_op():
    post = _fake_post_factory("plink_case7", "https://rzp.io/l/case7")
    get = _fake_get_factory(status="captured", amount=AMOUNT, currency="INR")
    engine, provider, led = _hybrid_engine(http_post=post, http_get=get)
    case_id = _drive_to_link(engine, provider)
    reference_id = reference_id_for(case_id)
    envelope = _paid_envelope(link_id="plink_case7", reference_id=reference_id, payment_id="pay_x7")
    raw = json.dumps(envelope).encode("utf-8")
    handle_payment_link_paid_webhook(
        engine=engine, provider=provider, webhook_secret=WEBHOOK_SECRET,
        raw=raw, signature=_demo_sign(raw), event_id="evt_x7_first",
    )
    assert led.case_projection(case_id=case_id).state == "recovered"
    # an "earlier" event somehow arriving late, after the case already
    # finalised, must never re-open or double-count it
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
    post = _fake_post_factory("plink_case8", "https://rzp.io/l/case8")
    get = _fake_get_factory(status="captured", amount=AMOUNT, currency="INR")
    store = InMemorySnapshotStore()
    engine1, provider1, led1 = _hybrid_engine(store, http_post=post, http_get=get)
    case_id = _drive_to_link(engine1, provider1)
    led1.close()

    # "restart": a fresh engine + a fresh real-adapter instance (no in-process
    # memory of the link) over the SAME durable store
    real2 = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True, http_get=get)
    provider2 = HybridPaymentProvider(FakeRazorpayAdapter(), real2)
    led2 = PgLedger(store)
    engine2 = RecoveryEngine(led2, ScriptedStrategist(), provider2)

    reference_id = reference_id_for(case_id)
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
