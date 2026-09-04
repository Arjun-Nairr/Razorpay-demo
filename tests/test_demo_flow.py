"""Full API -> engine Case 3 workflow with a STUBBED Gemini strategist.

Offline: no real model, no network, no DB, no credentials. Drives the
higher-level ``/demo/*`` controls the local UI uses and asserts the whole
insufficient-funds path: failure -> eligible wait -> failed retry -> recovery
link -> uniquely correlated simulated payment -> ``hermes_assisted`` recovered.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from hermes.adapters import FakeRazorpayAdapter, InMemoryLedger, ScriptedStrategist  # noqa: E402
from hermes.api import ApiConfig, create_app, normalize_event  # noqa: E402
from hermes.engine import RecoveryEngine  # noqa: E402
from hermes.hermes_strategist import StrategistRunMeta  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

DEMO_SECRET = "demosig_offline_test_only"


class StubGeminiStrategist:
    """A ``Strategist`` that returns the Case-3 scripted proposals but ALSO
    exposes ``last_run_meta`` like the real Gemini adapter, so the engine's
    decision-linked ``AI_MODEL_RUN`` audit is exercised."""

    def __init__(self, fail: bool = False):
        self._inner = ScriptedStrategist()
        self._fail = fail
        self.last_run_meta: StrategistRunMeta | None = None

    def propose(self, snapshot):
        if self._fail:
            self.last_run_meta = StrategistRunMeta(
                model="gemini-3.7-flash-STUB", prompt_version="stub/1", latency_ms=2.0,
                repair_used=False, validation_result="timeout", raw_response="", usage=None,
            )
            raise TimeoutError("stub timeout")
        proposal = self._inner.propose(snapshot)
        self.last_run_meta = StrategistRunMeta(
            model="gemini-3.7-flash-STUB", prompt_version="stub/1", latency_ms=3.0,
            repair_used=False, validation_result="valid",
            raw_response='{"action": "..."}', usage={"total_tokens": 42},
        )
        return proposal


def make_demo(fail_strategist: bool = False):
    rp = FakeRazorpayAdapter()
    engine = RecoveryEngine(InMemoryLedger(), StubGeminiStrategist(fail_strategist), rp)
    app = create_app(engine=engine, config=ApiConfig(webhook_secret=DEMO_SECRET), razorpay=rp)
    return TestClient(app), engine


def _kinds(timeline):
    return [r["kind"] for r in timeline]


# --- the happy path --------------------------------------------------


def test_case3_end_to_end_hermes_assisted_recovery():
    tc, _ = make_demo()

    opened = tc.post("/demo/case").json()
    cid = opened["case_id"]
    assert opened["evidence_mode"] == "SIMULATED"
    assert opened["merchant_context"]["source"].startswith("SYNTHETIC_DEMO_FIXTURE")

    r1 = tc.post("/demo/step", json={"case_id": cid, "step": "advance"}).json()
    assert r1["run"]["proposals"] == 1
    assert tc.get(f"/demo/case/{cid}").json()["case"]["state"] == "waiting"

    r2 = tc.post("/demo/step", json={"case_id": cid, "step": "retry_failed"}).json()
    assert r2["run"]["proposals"] == 1

    view = tc.get(f"/demo/case/{cid}").json()
    case, timeline = view["case"], view["timeline"]
    assert case["state"] in ("active", "waiting")  # link authorized, not yet captured
    assert case["links_created"] == 1
    assert case["messages_sent"] == 1  # merchant owns comms + consent -> authorized

    cap = tc.post("/demo/step", json={"case_id": cid, "step": "capture"}).json()
    assert cap["capture"]["accepted"] is True and cap["capture"]["evidence_mode"] == "SIMULATED"

    final = tc.get(f"/demo/case/{cid}").json()["case"]
    assert final["state"] == "recovered"
    assert final["attribution"] == "hermes_assisted"
    assert final["recovered_minor"] == 1_000_000
    assert final["counted"] is True

    kinds = _kinds(tc.get(f"/demo/case/{cid}").json()["timeline"])
    for required in ("INPUT_EVENT", "AI_MODEL_RUN", "AI_PROPOSAL", "POLICY_DECISION",
                     "SCHEDULED_ACTION", "RETRY_OUTCOME_RECORDED", "ACTION_INTENT",
                     "ACTION_OUTCOME", "PAYMENT_CONFIRMATION", "TERMINAL_TRANSITION"):
        assert required in kinds, f"missing audit kind {required}"
    assert kinds.index("ACTION_INTENT") < kinds.index("ACTION_OUTCOME")


def test_model_run_metadata_is_decision_linked_and_redacted():
    tc, _ = make_demo()
    cid = tc.post("/demo/case").json()["case_id"]
    tc.post("/demo/step", json={"case_id": cid, "step": "advance"})
    runs = [r for r in tc.get(f"/demo/case/{cid}").json()["timeline"]
            if r["kind"] == "AI_MODEL_RUN"]
    assert runs, "no AI_MODEL_RUN audit record"
    d = runs[-1]["detail"]
    assert set(d) >= {"model", "prompt_version", "latency_ms", "validation_result", "usage"}
    assert "prompt" not in d and "api_key" not in d and "raw_response" not in d


# --- idempotency / isolation --------------------------------------


def test_duplicate_capture_step_does_not_double_count():
    tc, engine = make_demo()
    cid = tc.post("/demo/case").json()["case_id"]
    tc.post("/demo/step", json={"case_id": cid, "step": "advance"})
    tc.post("/demo/step", json={"case_id": cid, "step": "retry_failed"})
    tc.post("/demo/step", json={"case_id": cid, "step": "capture"})
    first = tc.get(f"/demo/case/{cid}").json()["case"]["recovered_minor"]

    tc.post("/demo/step", json={"case_id": cid, "step": "capture"})  # replay
    again = tc.get(f"/demo/case/{cid}").json()["case"]["recovered_minor"]

    assert first == again == 1_000_000
    from hermes.types import BatchQuery
    assert engine.inspect(BatchQuery()).recovered_minor == 1_000_000


def test_second_fresh_case_does_not_erase_the_first():
    tc, _ = make_demo()
    a = tc.post("/demo/case").json()["case_id"]
    tc.post("/demo/step", json={"case_id": a, "step": "advance"})
    b = tc.post("/demo/case").json()["case_id"]
    assert a != b
    assert tc.get(f"/demo/case/{a}").json()["case"]["state"] == "waiting"  # untouched
    assert tc.get(f"/demo/case/{b}").json()["case"]["state"] == "active"


# --- honest model failure --------------------------------------


def test_strategist_failure_is_shown_not_papered_over():
    tc, _ = make_demo(fail_strategist=True)
    cid = tc.post("/demo/case").json()["case_id"]
    # first advance: strategist times out -> bounded retry scheduled
    tc.post("/demo/step", json={"case_id": cid, "step": "advance"})
    # advance again (backoff is 1h, step is 24h) -> second failure -> escalate
    tc.post("/demo/step", json={"case_id": cid, "step": "advance"})
    view = tc.get(f"/demo/case/{cid}").json()
    kinds = _kinds(view["timeline"])
    assert "STRATEGIST_FAILURE" in kinds
    assert "AI_PROPOSAL" not in kinds  # nothing was proposed / substituted
    assert view["case"]["state"] == "escalated"
    assert view["case"]["attribution"] == "unrecovered"
    model_runs = [r for r in view["timeline"] if r["kind"] == "AI_MODEL_RUN"]
    assert model_runs and model_runs[-1]["detail"]["validation_result"] == "timeout"


# --- absent merchant context: contact stays denied ----------


def test_normalize_event_denies_contact_without_trusted_context():
    cfg = ApiConfig(webhook_secret="x")
    body = {
        "event": "payment.failed",
        "payload": {
            "payment": {"entity": {"id": "pay_1", "amount": 100, "currency": "INR",
                                   "consent": True, "reachable_channel": True}},
            "subscription": {"entity": {"id": "sub_x"}},
        },
    }
    wh = normalize_event(body, "evt_x", cfg, merchant_context=None)
    assert wh.consent is False and wh.reachable_channel is False
    assert wh.customer_notify is False


def test_normalize_event_uses_trusted_context_when_present():
    from hermes.demo_fixtures import case3_merchant_context

    cfg = ApiConfig(webhook_secret="x")
    ctx = case3_merchant_context("sub_x")
    body = {
        "event": "payment.failed",
        "payload": {
            "payment": {"entity": {"id": "pay_1", "amount": 100, "currency": "INR"}},
            "subscription": {"entity": {"id": "sub_x"}},
        },
    }
    wh = normalize_event(body, "evt_x", cfg, merchant_context=ctx)
    assert wh.consent is True and wh.reachable_channel is True
    # mismatched obligation id -> not applied
    wh2 = normalize_event(body, "evt_y", cfg, merchant_context=case3_merchant_context("other"))
    assert wh2.consent is False
