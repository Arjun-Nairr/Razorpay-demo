"""Correction 6: the API stays responsive during a slow model call, webhook
intake never waits for Gemini, only one recovery runner runs at a time, and
signature verification precedes any JSON parsing. Offline, delayed stub.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from hermes.adapters import FakeRazorpayAdapter, InMemoryLedger  # noqa: E402
from hermes.api import ApiConfig, create_app  # noqa: E402
from hermes.engine import RecoveryEngine  # noqa: E402
from hermes.hermes_strategist import StrategistRunMeta  # noqa: E402
from hermes.types import ProposalAction, StrategyProposal  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")
SECRET = "demosig_concurrency_test"


class DelayedStrategist:
    """Sleeps inside propose() to simulate a slow Gemini call, then returns a
    valid WAIT proposal."""

    def __init__(self, delay_s: float = 1.5):
        self.delay_s = delay_s
        self.started = threading.Event()
        self.last_run_meta = None

    def propose(self, snapshot):
        self.started.set()
        time.sleep(self.delay_s)
        self.last_run_meta = StrategistRunMeta(
            model="delayed-stub", prompt_version="t", latency_ms=self.delay_s * 1000,
            repair_used=False, validation_result="valid", raw_response="{}", usage=None,
        )
        return StrategyProposal(
            action=ProposalAction.WAIT_FOR_PROVIDER_RETRY, diagnosis="d", rationale="r",
            confidence=0.6, proposed_wait_hours=24,
        )


def _client(delay=1.5):
    rp = FakeRazorpayAdapter()
    strat = DelayedStrategist(delay)
    engine = RecoveryEngine(InMemoryLedger(), strat, rp)
    app = create_app(engine=engine, config=ApiConfig(webhook_secret=SECRET), razorpay=rp)
    return TestClient(app), strat


def _sign(raw: bytes) -> str:
    return hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()


def _failed_webhook(tc, obligation, event_id):
    body = {
        "event": "payment.failed",
        "payload": {
            "payment": {"entity": {"id": f"pay_{event_id}", "amount": 1_000_000,
                                   "currency": "INR", "error_description": "insufficient_funds"}},
            "subscription": {"entity": {"id": obligation}},
        },
    }
    raw = json.dumps(body).encode()
    return tc.post("/webhooks/razorpay", content=raw,
                   headers={"x-razorpay-signature": _sign(raw),
                            "x-razorpay-event-id": event_id})


def _advance(tc, cid):
    return tc.post("/demo/step", json={"case_id": cid, "step": "advance"})


def test_health_stays_responsive_during_a_slow_model_call():
    tc, strat = _client(delay=1.5)
    cid = tc.post("/demo/case").json()["case_id"]

    pool = ThreadPoolExecutor(max_workers=2)
    slow = pool.submit(_advance, tc, cid)
    assert strat.started.wait(2.0), "model call never started"

    t0 = time.monotonic()
    for _ in range(5):
        assert tc.get("/health").status_code == 200
    assert time.monotonic() - t0 < 1.0  # not blocked by the 1.5s call

    assert slow.result(timeout=5).status_code == 200
    pool.shutdown()


def test_second_run_attempt_is_rejected_while_one_is_in_progress():
    tc, strat = _client(delay=1.2)
    cid = tc.post("/demo/case").json()["case_id"]

    pool = ThreadPoolExecutor(max_workers=2)
    first = pool.submit(_advance, tc, cid)
    assert strat.started.wait(2.0)
    second = _advance(tc, cid)
    assert second.status_code == 409  # one recovery runner only

    assert first.result(timeout=5).status_code == 200
    pool.shutdown()


def test_webhook_intake_does_not_wait_for_gemini():
    tc, strat = _client(delay=2.0)
    cid = tc.post("/demo/case").json()["case_id"]

    pool = ThreadPoolExecutor(max_workers=2)
    slow = pool.submit(_advance, tc, cid)
    assert strat.started.wait(3.0)

    t0 = time.monotonic()
    r1 = _failed_webhook(tc, "sub_ext_1", "ext_evt_1")
    r2 = _failed_webhook(tc, "sub_ext_1", "ext_evt_1")  # duplicate delivery
    elapsed = time.monotonic() - t0

    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["duplicate"] is False and r2.json()["duplicate"] is True
    assert elapsed < 1.0, f"webhook intake waited {elapsed:.2f}s for the model call"

    assert slow.result(timeout=6).status_code == 200
    pool.shutdown()


def test_invalid_signature_never_triggers_json_parsing(monkeypatch):
    tc, _ = _client(delay=0.0)
    import hermes.api as api_mod

    def _boom(*a, **k):
        raise AssertionError("json.loads must not run for an unverified request")

    monkeypatch.setattr(api_mod.json, "loads", _boom)
    raw = b'{"event": "payment.failed"'  # malformed on purpose
    r = tc.post("/webhooks/razorpay", content=raw,
                headers={"x-razorpay-signature": "0" * 64, "x-razorpay-event-id": "e"})
    assert r.status_code == 401  # rejected on signature, before any parse
