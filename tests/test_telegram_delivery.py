"""Offline tests for the Telegram delivery seam: the adapter itself
(``hermes.telegram_delivery``) and the engine-side orchestration
(``hermes.engine.deliver_drafted_message``).

No network call happens anywhere in this file - every HTTP call is injected.
Real credentials are never read: ``TelegramConfig`` is always constructed
from an explicit in-memory dict, never ``os.environ``.
"""

from __future__ import annotations

import pytest

from hermes.adapters import FakeRazorpayAdapter, ScriptedStrategist
from hermes.engine import RecoveryEngine, deliver_drafted_message
from hermes.pg_ledger import InMemorySnapshotStore, PgLedger
from hermes.razorpay_test_mode import HybridPaymentProvider, RazorpayTestModeAdapter
from hermes.telegram_delivery import (
    NullTelegramAdapter,
    TelegramAdapter,
    TelegramConfig,
    build_delivery_adapter,
    fetch_chat_id_candidates,
    verify_bot,
)
from hermes.types import (
    ClaimMessageDeliveryCommand,
    DeliveryReceipt,
    RazorpayWebhook,
    WebhookType,
)

TEST_KEY_ID = "rzp_test_abc123"
AMOUNT = 1_000_000
OBL = "sub_hybrid_0001"

READY_ENV = {"TELEGRAM_ENABLED": "1", "TELEGRAM_BOT_TOKEN": "111:abc", "TELEGRAM_CHAT_ID": "42"}


# === TelegramConfig ========================================================


def test_config_from_env_never_reads_real_os_environ(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ENABLED", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "should-not-be-read")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "should-not-be-read")
    config = TelegramConfig.from_env({})  # explicit empty dict, not os.environ
    assert config.enabled is False and config.bot_token is None and config.chat_id is None


def test_describe_never_exposes_secret_values():
    config = TelegramConfig.from_env(READY_ENV)
    d = config.describe()
    assert "111:abc" not in str(d) and "42" not in str(d)
    assert d == {"enabled": True, "bot_token_present": True, "chat_id_present": True, "ready": True}


@pytest.mark.parametrize("env", [
    {},
    {"TELEGRAM_ENABLED": "0", "TELEGRAM_BOT_TOKEN": "x", "TELEGRAM_CHAT_ID": "y"},
    {"TELEGRAM_ENABLED": "1", "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": "y"},
    {"TELEGRAM_ENABLED": "1", "TELEGRAM_BOT_TOKEN": "x", "TELEGRAM_CHAT_ID": ""},
])
def test_not_ready_configurations(env):
    assert TelegramConfig.from_env(env).ready is False


# === TelegramAdapter.deliver - disabled / missing / success / failure =====


def test_disabled_configuration_never_claims_delivery():
    calls = []
    config = TelegramConfig.from_env({"TELEGRAM_ENABLED": "0"})
    adapter = TelegramAdapter(config, http_post=lambda *a: calls.append(1))
    receipt = adapter.deliver(text="hello")
    assert receipt.outcome == "failed" and receipt.reason == "telegram_disabled_or_unconfigured"
    assert receipt.message_id is None
    assert calls == []  # no network call attempted at all


def test_missing_credentials_never_claims_delivery():
    calls = []
    config = TelegramConfig.from_env({"TELEGRAM_ENABLED": "1"})  # no token/chat id
    adapter = TelegramAdapter(config, http_post=lambda *a: calls.append(1))
    receipt = adapter.deliver(text="hello")
    assert receipt.outcome == "failed" and receipt.reason == "telegram_disabled_or_unconfigured"
    assert calls == []


def test_build_delivery_adapter_returns_null_adapter_when_not_ready():
    adapter = build_delivery_adapter({})
    assert isinstance(adapter, NullTelegramAdapter)
    receipt = adapter.deliver(text="hello")
    assert receipt.outcome == "failed"


def test_successful_verified_delivery_becomes_sent():
    config = TelegramConfig.from_env(READY_ENV)
    calls = []

    def http_post(url, payload, timeout_s):
        calls.append((url, payload))
        return {"ok": True, "result": {"message_id": 99}}

    adapter = TelegramAdapter(config, http_post=http_post)
    receipt = adapter.deliver(text="Please pay: https://rzp.io/l/abc")
    assert receipt.outcome == "sent" and receipt.message_id == "99"
    assert len(calls) == 1
    url, payload = calls[0]
    assert "111:abc" in url  # the token IS in the outbound URL (required by the API)...
    assert payload == {"chat_id": "42", "text": "Please pay: https://rzp.io/l/abc"}
    # ...but the RECEIPT itself never carries the token or chat id:
    assert "111:abc" not in str(receipt) and "42" != receipt.message_id


def test_telegram_api_rejection_is_failed_not_uncertain():
    config = TelegramConfig.from_env(READY_ENV)
    adapter = TelegramAdapter(
        config, http_post=lambda *a: {"ok": False, "description": "Forbidden: bot was blocked"}
    )
    receipt = adapter.deliver(text="hi")
    assert receipt.outcome == "failed" and receipt.reason == "telegram_api_rejected"
    assert receipt.reason and "blocked" not in receipt.reason  # provider text never surfaced


def test_timeout_is_recorded_as_uncertain():
    config = TelegramConfig.from_env(READY_ENV)

    def http_post(*a):
        raise TimeoutError("slow")

    adapter = TelegramAdapter(config, http_post=http_post)
    receipt = adapter.deliver(text="hi")
    assert receipt.outcome == "uncertain" and receipt.reason == "timeout"


def test_network_error_is_recorded_as_uncertain():
    import urllib.error

    config = TelegramConfig.from_env(READY_ENV)

    def http_post(*a):
        raise urllib.error.URLError("dns failure")

    adapter = TelegramAdapter(config, http_post=http_post)
    receipt = adapter.deliver(text="hi")
    assert receipt.outcome == "uncertain" and receipt.reason == "network_error"


@pytest.mark.parametrize("bad_response", [
    "not a dict",
    {"ok": True, "result": {}},               # missing message_id
    {"ok": True, "result": {"message_id": "not-an-int"}},
    {"ok": True},                              # missing result entirely
])
def test_malformed_or_incomplete_success_is_uncertain_never_sent(bad_response):
    config = TelegramConfig.from_env(READY_ENV)
    adapter = TelegramAdapter(config, http_post=lambda *a: bad_response)
    receipt = adapter.deliver(text="hi")
    assert receipt.outcome == "uncertain"
    assert receipt.message_id is None


# === setup helper functions (verify_bot / fetch_chat_id_candidates) =======


def test_verify_bot_success():
    result = verify_bot(
        TelegramConfig.from_env(READY_ENV),
        http_get=lambda url, t: {"ok": True, "result": {"username": "my_bot", "id": 5}},
    )
    assert result == {"ok": True, "username": "my_bot", "bot_id": 5}


def test_verify_bot_rejection():
    result = verify_bot(
        TelegramConfig.from_env(READY_ENV), http_get=lambda url, t: {"ok": False},
    )
    assert result == {"ok": False, "reason": "telegram_api_rejected"}


def test_fetch_chat_id_candidates_extracts_sanitized_fields():
    resp = {"ok": True, "result": [
        {"message": {"chat": {"id": 555, "first_name": "Ari", "type": "private"},
                     "text": "should never be surfaced"}},
        {"message": {"chat": {"id": 555, "first_name": "Ari", "type": "private"}}},  # dedup
        {"message": {"chat": {"id": -100, "type": "group"}}},
    ]}
    result = fetch_chat_id_candidates(
        TelegramConfig.from_env(READY_ENV), http_get=lambda url, t: resp,
    )
    assert result["ok"] is True
    ids = {c["chat_id"] for c in result["candidates"]}
    assert ids == {555, -100}
    assert len(result["candidates"]) == 2  # deduplicated
    assert "should never be surfaced" not in str(result)


# === engine-side orchestration: deliver_drafted_message ====================


def _hybrid_engine(*, http_post=None):
    real = RazorpayTestModeAdapter(TEST_KEY_ID, "secret", enabled=True, http_post=http_post)
    provider = HybridPaymentProvider(FakeRazorpayAdapter(), real)
    led = PgLedger(InMemorySnapshotStore())
    engine = RecoveryEngine(led, ScriptedStrategist(), provider)
    return engine, provider, led


def _drive_to_drafted_link(engine, provider, obl=OBL):
    """failure -> eligible wait -> failed retry -> CREATE_RECOVERY_LINK
    (real, with a confirmed checkout URL) -> DRAFTED message."""
    provider.set_retry_eligibility(obl, True)
    r = engine.receive(RazorpayWebhook("e_f0", WebhookType.PAYMENT_FAILED, obl, AMOUNT,
                                       reason_code="insufficient_funds"))
    engine.run(until=1)
    engine.receive(RazorpayWebhook("e_r1", WebhookType.PAYMENT_FAILED, obl, AMOUNT,
                                   reason_code="insufficient_funds"))
    provider.set_retry_eligibility(obl, False)
    engine.run(until=2)
    return r.case_id


class _StubDelivery:
    def __init__(self, receipt: DeliveryReceipt):
        self._receipt = receipt
        self.calls = 0

    def deliver(self, *, text: str) -> DeliveryReceipt:
        self.calls += 1
        self._last_text = text
        return self._receipt


def test_no_delivery_before_drafted_status():
    """A case that never reached CREATE_RECOVERY_LINK has nothing eligible -
    the adapter is never even called."""
    engine, provider, led = _hybrid_engine(http_post=lambda url, **k: {"id": "plink_x"})
    provider.set_retry_eligibility(OBL, True)
    r = engine.receive(RazorpayWebhook("e_f0", WebhookType.PAYMENT_FAILED, OBL, AMOUNT,
                                       reason_code="insufficient_funds"))
    engine.run(until=1)  # only WAIT_FOR_PROVIDER_RETRY happened - still waiting

    delivery = _StubDelivery(DeliveryReceipt(outcome="sent", message_id="1"))
    result = deliver_drafted_message(led, r.case_id, delivery, now=2)
    assert result is None
    assert delivery.calls == 0


def test_no_delivery_without_a_confirmed_checkout_url():
    """The SIMULATED fake-provider path stages a DRAFTED message but has no
    REAL_TEST_MODE checkout URL - it must never be delivered."""
    led = PgLedger(InMemorySnapshotStore())
    fake = FakeRazorpayAdapter()
    engine = RecoveryEngine(led, ScriptedStrategist(), fake)
    fake.set_retry_eligibility(OBL, True)
    r = engine.receive(RazorpayWebhook("e_f0", WebhookType.PAYMENT_FAILED, OBL, AMOUNT,
                                       reason_code="insufficient_funds"))
    engine.run(until=1)
    engine.receive(RazorpayWebhook("e_r1", WebhookType.PAYMENT_FAILED, OBL, AMOUNT,
                                   reason_code="insufficient_funds"))
    fake.set_retry_eligibility(OBL, False)
    engine.run(until=2)  # authorizes + executes the simulated link -> DRAFTED, no url

    proj = led.case_projection(case_id=r.case_id)
    intent = proj.action_intents[0]
    assert intent.message_status == "DRAFTED" and not intent.url

    delivery = _StubDelivery(DeliveryReceipt(outcome="sent", message_id="1"))
    result = deliver_drafted_message(led, r.case_id, delivery, now=2)
    assert result is None
    assert delivery.calls == 0


def test_no_delivery_without_policy_authorization():
    """Provider-owned communication suppresses the message (never DRAFTED) -
    delivery must never be attempted."""
    engine, provider, led = _hybrid_engine(http_post=lambda url, **k: {"id": "plink_x",
                                                                        "short_url": "https://rzp.io/l/x"})
    provider.set_retry_eligibility(OBL, True)
    r = engine.receive(RazorpayWebhook("e_f0", WebhookType.PAYMENT_FAILED, OBL, AMOUNT,
                                       reason_code="insufficient_funds", customer_notify=True))
    engine.run(until=1)
    engine.receive(RazorpayWebhook("e_r1", WebhookType.PAYMENT_FAILED, OBL, AMOUNT,
                                   reason_code="insufficient_funds", customer_notify=True))
    provider.set_retry_eligibility(OBL, False)
    engine.run(until=2)

    proj = led.case_projection(case_id=r.case_id)
    intent = proj.action_intents[0]
    assert intent.message_status == "SUPPRESSED"

    delivery = _StubDelivery(DeliveryReceipt(outcome="sent", message_id="1"))
    result = deliver_drafted_message(led, r.case_id, delivery, now=2)
    assert result is None
    assert delivery.calls == 0


def test_successful_delivery_marks_sent_and_increments_contact_counter():
    engine, provider, led = _hybrid_engine(
        http_post=lambda url, **k: {"id": "plink_15", "short_url": "https://rzp.io/l/15"}
    )
    case_id = _drive_to_drafted_link(engine, provider)
    intent_before = led.case_projection(case_id=case_id).action_intents[0]
    assert intent_before.message_status == "DRAFTED" and intent_before.url

    delivery = _StubDelivery(DeliveryReceipt(outcome="sent", message_id="777"))
    result = deliver_drafted_message(led, case_id, delivery, now=3)
    assert result.ok is True and delivery.calls == 1
    assert "https://rzp.io/l/15" in delivery._last_text  # url added ONLY at the boundary

    proj = led.case_projection(case_id=case_id)
    intent = proj.action_intents[0]
    assert intent.message_status == "SENT"
    assert intent.message_sent is True
    assert intent.delivery_outcome == "sent"
    assert intent.delivery_message_id == "777"
    assert proj.messages_sent == 1


def test_replay_after_sent_never_calls_the_adapter_again():
    engine, provider, led = _hybrid_engine(
        http_post=lambda url, **k: {"id": "plink_16", "short_url": "https://rzp.io/l/16"}
    )
    case_id = _drive_to_drafted_link(engine, provider)
    delivery = _StubDelivery(DeliveryReceipt(outcome="sent", message_id="1"))
    deliver_drafted_message(led, case_id, delivery, now=3)
    assert delivery.calls == 1

    result = deliver_drafted_message(led, case_id, delivery, now=4)
    assert result is None  # no eligible (DRAFTED) intent left - never called again
    assert delivery.calls == 1

    proj = led.case_projection(case_id=case_id)
    assert proj.messages_sent == 1  # never double-counted


@pytest.mark.parametrize("outcome", ["failed", "uncertain"])
def test_failed_or_uncertain_delivery_never_claims_sent(outcome):
    engine, provider, led = _hybrid_engine(
        http_post=lambda url, **k: {"id": "plink_17", "short_url": "https://rzp.io/l/17"}
    )
    case_id = _drive_to_drafted_link(engine, provider)
    delivery = _StubDelivery(DeliveryReceipt(outcome=outcome, reason="network_error"))
    result = deliver_drafted_message(led, case_id, delivery, now=3)
    assert result.ok is True

    proj = led.case_projection(case_id=case_id)
    intent = proj.action_intents[0]
    assert intent.message_status == "DRAFTED"  # never advanced to SENT
    assert intent.message_sent is False
    assert proj.messages_sent == 0  # counter never moved


def test_message_delivery_audit_event_never_exposes_url_or_token():
    engine, provider, led = _hybrid_engine(
        http_post=lambda url, **k: {"id": "plink_18", "short_url": "https://rzp.io/l/18"}
    )
    case_id = _drive_to_drafted_link(engine, provider)
    delivery = _StubDelivery(DeliveryReceipt(outcome="sent", message_id="42"))
    deliver_drafted_message(led, case_id, delivery, now=3)

    from hermes.types import AuditQuery
    events = [r for r in engine.inspect(AuditQuery(case_id=case_id)).records
              if r.kind == "MESSAGE_DELIVERY_ATTEMPTED"]
    assert len(events) == 2  # the durable claim, then the final outcome
    assert [e.detail["outcome"] for e in events] == ["in_progress", "sent"]
    for e in events:
        detail = e.detail
        assert set(detail) == {"intent_id", "case_id", "channel", "outcome", "message_id", "attempted_time"}
        assert "https://rzp.io/l/18" not in str(detail)
        assert "rzp_test_abc123" not in str(detail)
        assert detail["channel"] == "telegram"


def test_concurrent_claim_only_one_caller_gets_work():
    """Two callers racing on the SAME eligible intent: only the first
    ledger-level claim succeeds - the second must never be told to call
    the adapter."""
    engine, provider, led = _hybrid_engine(
        http_post=lambda url, **k: {"id": "plink_20", "short_url": "https://rzp.io/l/20"}
    )
    case_id = _drive_to_drafted_link(engine, provider)
    intent_id = led.case_projection(case_id=case_id).action_intents[0].intent_id

    first = led.claim_message_delivery(
        ClaimMessageDeliveryCommand(intent_id=intent_id, case_id=case_id, now=3, channel="telegram")
    )
    second = led.claim_message_delivery(
        ClaimMessageDeliveryCommand(intent_id=intent_id, case_id=case_id, now=3, channel="telegram")
    )
    assert first.claimed is True
    assert second.claimed is False


def test_deliver_drafted_message_never_calls_adapter_when_pre_claimed():
    """If the intent is already claimed (by another process/thread), the
    engine-level orchestration must not call the adapter either."""
    engine, provider, led = _hybrid_engine(
        http_post=lambda url, **k: {"id": "plink_21", "short_url": "https://rzp.io/l/21"}
    )
    case_id = _drive_to_drafted_link(engine, provider)
    intent_id = led.case_projection(case_id=case_id).action_intents[0].intent_id
    led.claim_message_delivery(
        ClaimMessageDeliveryCommand(intent_id=intent_id, case_id=case_id, now=3, channel="telegram")
    )

    delivery = _StubDelivery(DeliveryReceipt(outcome="sent", message_id="1"))
    result = deliver_drafted_message(led, case_id, delivery, now=4)
    assert result is None  # already in_progress - not even eligible to attempt a claim
    assert delivery.calls == 0


@pytest.mark.parametrize("outcome", ["failed", "uncertain"])
def test_replay_after_failed_or_uncertain_never_becomes_eligible_again(outcome):
    engine, provider, led = _hybrid_engine(
        http_post=lambda url, **k: {"id": "plink_22", "short_url": "https://rzp.io/l/22"}
    )
    case_id = _drive_to_drafted_link(engine, provider)
    first = _StubDelivery(DeliveryReceipt(outcome=outcome))
    deliver_drafted_message(led, case_id, first, now=3)
    assert first.calls == 1

    second = _StubDelivery(DeliveryReceipt(outcome="sent", message_id="1"))
    result = deliver_drafted_message(led, case_id, second, now=4)
    assert result is None  # no eligible (delivery_outcome is None) intent left
    assert second.calls == 0  # never called - the claim gate is permanently closed

    proj = led.case_projection(case_id=case_id)
    assert proj.action_intents[0].message_status == "DRAFTED"
    assert proj.messages_sent == 0


def test_crash_after_claim_is_reconciled_to_uncertain_not_retried():
    """A claim with no recorded outcome (the process died mid-call) must be
    swept to a safe, non-retryable 'uncertain' - never left claimable, never
    silently resolved as sent."""
    engine, provider, led = _hybrid_engine(
        http_post=lambda url, **k: {"id": "plink_23", "short_url": "https://rzp.io/l/23"}
    )
    case_id = _drive_to_drafted_link(engine, provider)
    intent_id = led.case_projection(case_id=case_id).action_intents[0].intent_id
    claim = led.claim_message_delivery(
        ClaimMessageDeliveryCommand(intent_id=intent_id, case_id=case_id, now=3, channel="telegram")
    )
    assert claim.claimed is True
    assert led.case_projection(case_id=case_id).action_intents[0].delivery_outcome == "in_progress"

    n = engine.reconcile_uncertain_intents()
    assert n == 1
    proj = led.case_projection(case_id=case_id)
    intent = proj.action_intents[0]
    assert intent.delivery_outcome == "uncertain"
    assert intent.message_status == "DRAFTED"
    assert proj.messages_sent == 0

    delivery = _StubDelivery(DeliveryReceipt(outcome="sent", message_id="1"))
    result = deliver_drafted_message(led, case_id, delivery, now=5)
    assert result is None and delivery.calls == 0  # still never automatically retried


@pytest.mark.parametrize("bad_message_id", [None, "", "   ", "not-digits", "1" * 40])
def test_forged_sent_without_a_valid_message_id_becomes_uncertain(bad_message_id):
    engine, provider, led = _hybrid_engine(
        http_post=lambda url, **k: {"id": "plink_24", "short_url": "https://rzp.io/l/24"}
    )
    case_id = _drive_to_drafted_link(engine, provider)
    delivery = _StubDelivery(DeliveryReceipt(outcome="sent", message_id=bad_message_id))
    deliver_drafted_message(led, case_id, delivery, now=3)

    proj = led.case_projection(case_id=case_id)
    intent = proj.action_intents[0]
    assert intent.message_status == "DRAFTED"  # never SENT on a forged/malformed receipt
    assert intent.delivery_outcome == "uncertain"
    assert intent.delivery_message_id is None
    assert proj.messages_sent == 0


def test_forged_failed_receipt_carrying_a_message_id_drops_it():
    engine, provider, led = _hybrid_engine(
        http_post=lambda url, **k: {"id": "plink_25", "short_url": "https://rzp.io/l/25"}
    )
    case_id = _drive_to_drafted_link(engine, provider)
    delivery = _StubDelivery(DeliveryReceipt(outcome="failed", message_id="999"))
    deliver_drafted_message(led, case_id, delivery, now=3)

    proj = led.case_projection(case_id=case_id)
    intent = proj.action_intents[0]
    assert intent.delivery_outcome == "failed"
    assert intent.delivery_message_id is None  # a failed outcome never carries an id
    assert intent.message_status == "DRAFTED"


def test_unknown_outcome_value_is_sanitized_to_uncertain():
    engine, provider, led = _hybrid_engine(
        http_post=lambda url, **k: {"id": "plink_26", "short_url": "https://rzp.io/l/26"}
    )
    case_id = _drive_to_drafted_link(engine, provider)
    delivery = _StubDelivery(DeliveryReceipt(outcome="delivered!", message_id="1"))
    deliver_drafted_message(led, case_id, delivery, now=3)

    proj = led.case_projection(case_id=case_id)
    intent = proj.action_intents[0]
    assert intent.delivery_outcome == "uncertain"
    assert intent.message_status == "DRAFTED"


def test_ledger_apply_message_delivery_rejects_unclaimed_intent():
    """apply_message_delivery is never accepted without a matching prior
    claim - the ledger's own boundary check, independent of the engine's
    orchestration."""
    from hermes.types import MessageDeliveryCommand

    engine, provider, led = _hybrid_engine(
        http_post=lambda url, **k: {"id": "plink_27", "short_url": "https://rzp.io/l/27"}
    )
    case_id = _drive_to_drafted_link(engine, provider)
    intent_id = led.case_projection(case_id=case_id).action_intents[0].intent_id

    result = led.apply_message_delivery(MessageDeliveryCommand(
        intent_id=intent_id, case_id=case_id, now=3, channel="telegram",
        outcome="sent", message_id="1",
    ))
    assert result.reason == "not_claimed"
    proj = led.case_projection(case_id=case_id)
    assert proj.action_intents[0].message_status == "DRAFTED"  # untouched


# === product scope: a single failure alone cannot recommend a payment plan =


def test_soul_skill_document_the_single_failure_constraint():
    from pathlib import Path

    skill = Path(__file__).parent.parent / "config" / "hermes_agent" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert "PAYMENT_PLAN_REVIEW" in text
    assert "never justifies this recommendation by itself" in text


def test_scripted_single_failure_default_advisory_is_none():
    """The demo's own single-insufficient-funds-failure default proposal
    never recommends a payment plan - only a repeated-failure signal could."""
    from hermes.types import RecommendedIntervention

    proposal = ScriptedStrategist().script[("insufficient_funds", False)]
    assert proposal.recommended_intervention is RecommendedIntervention.NONE
