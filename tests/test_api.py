"""Offline tests for the FastAPI simulated Razorpay ingress (slice 3).

No network, no Gemini, no Razorpay, no Neon, no real credentials. The webhook
secret is a test literal; every fixture is locally signed. ``fastapi`` /
``httpx`` come from the optional ``[api]`` extra - these tests skip when it is
not installed, so the default suite is unaffected.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from hermes.adapters import FakeRazorpayAdapter, InMemoryLedger, ScriptedStrategist  # noqa: E402
from hermes.api import ApiConfig, create_app, normalize_event  # noqa: E402
from hermes.engine import RecoveryEngine  # noqa: E402
from hermes.types import AuditQuery, BatchQuery, CaseQuery  # noqa: E402

# The starlette TestClient warns about httpx vs httpx2 on current versions; not
# our code and not relevant to these assertions.
pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

SECRET = "whsec_simulated_test_only"


def make_engine() -> RecoveryEngine:
    return RecoveryEngine(InMemoryLedger(), ScriptedStrategist(), FakeRazorpayAdapter())


def make_client(secret: str = SECRET, engine: RecoveryEngine | None = None):
    eng = engine or make_engine()
    app = create_app(engine=eng, config=ApiConfig(webhook_secret=secret))
    return TestClient(app), eng


def sign(raw: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def failure_envelope(*, event="payment.failed", sub="sub_SIM_0001", pay="pay_SIM_1",
                     amount=1_000_000, currency="INR", reason="bank_temporary_error"):
    return {
        "event": event,
        "payload": {
            "payment": {"entity": {"id": pay, "amount": amount, "currency": currency,
                                   "error_description": reason}},
            "subscription": {"entity": {"id": sub}},
        },
    }


def capture_envelope(*, sub="sub_SIM_0001", pay="pay_SIM_1", amount=1_000_000):
    return {
        "event": "payment.captured",
        "payload": {
            "payment": {"entity": {"id": pay, "amount": amount, "currency": "INR"}},
            "subscription": {"entity": {"id": sub}},
        },
    }


_AUTO_SIGN = object()


def post_webhook(tc, body_obj, *, event_id="evt_1", secret=SECRET,
                 signature=_AUTO_SIGN, extra_bytes=b"", omit_event_id=False):
    raw = json.dumps(body_obj).encode() if not isinstance(body_obj, (bytes, bytearray)) else bytes(body_obj)
    headers = {}
    if signature is _AUTO_SIGN:
        headers["x-razorpay-signature"] = sign(raw, secret)
    elif signature is not None:
        headers["x-razorpay-signature"] = signature  # explicit wrong value
    # signature is None -> header omitted entirely
    if not omit_event_id:
        headers["x-razorpay-event-id"] = event_id
    return tc.post("/webhooks/razorpay", content=raw + extra_bytes, headers=headers)


# --- health --------------------------------------------------------------


def test_health():
    tc, _ = make_client()
    r = tc.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "evidence_mode": "SIMULATED"}


# --- valid signed payload ---------------------------------------------


def test_valid_signed_failure_creates_one_case():
    tc, eng = make_client()
    r = post_webhook(tc, failure_envelope(), event_id="evt_f1")
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is True and body["duplicate"] is False
    assert body["case_id"] and body["evidence_mode"] == "SIMULATED"
    assert eng.inspect(BatchQuery()).cases == 1

    proj = tc.get(f"/cases/{body['case_id']}").json()
    assert proj["obligation_id"] == "sub_SIM_0001"
    assert proj["amount_minor"] == 1_000_000
    assert proj["currency"] == "INR"
    assert proj["state"] == "active"


# --- signature rejection ------------------------------------------


def test_invalid_signature_rejected_without_processing():
    tc, eng = make_client()
    r = post_webhook(tc, failure_envelope(), signature="deadbeef" * 8)
    assert r.status_code == 401
    assert eng.inspect(BatchQuery()).cases == 0
    assert "deadbeef" not in r.text  # the provided signature is not echoed back


def test_missing_signature_header_rejected():
    tc, eng = make_client()
    r = post_webhook(tc, failure_envelope(), signature=None)
    assert r.status_code == 401
    assert eng.inspect(BatchQuery()).cases == 0


def test_raw_body_mutation_invalidates_signature():
    tc, eng = make_client()
    # signature computed over the original bytes; one extra byte is appended
    r = post_webhook(tc, failure_envelope(), extra_bytes=b" ")
    assert r.status_code == 401
    assert eng.inspect(BatchQuery()).cases == 0


# --- event id + json ------------------------------------------


def test_missing_event_id_rejected():
    tc, eng = make_client()
    r = post_webhook(tc, failure_envelope(), omit_event_id=True)
    assert r.status_code == 400
    assert eng.inspect(BatchQuery()).cases == 0


def test_malformed_json_with_valid_signature_rejected():
    tc, eng = make_client()
    raw = b'{"event": "payment.failed", '  # truncated
    r = tc.post(
        "/webhooks/razorpay",
        content=raw,
        headers={"x-razorpay-signature": sign(raw), "x-razorpay-event-id": "evt_bad"},
    )
    assert r.status_code == 400
    assert eng.inspect(BatchQuery()).cases == 0


# --- dedup ----------------------------------------------------


def test_duplicate_event_acknowledged_without_duplicate_work():
    tc, eng = make_client()
    first = post_webhook(tc, failure_envelope(), event_id="evt_dup")
    second = post_webhook(tc, failure_envelope(), event_id="evt_dup")
    assert first.status_code == second.status_code == 200
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    assert first.json()["case_id"] == second.json()["case_id"]
    batch = eng.inspect(BatchQuery())
    assert batch.cases == 1 and batch.recovered_minor == 0


# --- normalization -------------------------------------------


def test_supported_failure_normalization_reflects_payload():
    tc, _ = make_client()
    r = post_webhook(
        tc,
        failure_envelope(sub="sub_SIM_9", amount=250_000, currency="INR",
                         reason="insufficient_funds"),
        event_id="evt_norm",
    )
    assert r.status_code == 200
    proj = tc.get(f"/cases/{r.json()['case_id']}").json()
    assert proj["obligation_id"] == "sub_SIM_9"
    assert proj["amount_minor"] == 250_000


def test_supported_capture_normalization_recovers_the_case():
    tc, eng = make_client()
    f = post_webhook(tc, failure_envelope(sub="sub_CAP", pay="pay_CAP_1"),
                     event_id="evt_cf")
    cid = f.json()["case_id"]
    c = post_webhook(
        tc, capture_envelope(sub="sub_CAP", pay="pay_CAP_1", amount=1_000_000),
        event_id="evt_cc",
    )
    assert c.status_code == 200
    proj = tc.get(f"/cases/{cid}").json()
    assert proj["state"] == "recovered"
    assert proj["counted"] is True
    assert proj["recovered_minor"] == 1_000_000
    assert eng.inspect(BatchQuery()).recovered_minor == 1_000_000


def test_normalize_event_helper_stamps_simulated():
    cfg = ApiConfig(webhook_secret="x")  # evidence_mode defaults to SIMULATED
    wh = normalize_event(failure_envelope(), "evt_x", cfg)
    assert wh.evidence_mode == "SIMULATED"
    assert wh.obligation_id == "sub_SIM_0001"


def test_simulated_evidence_label_on_response():
    tc, _ = make_client()
    r = post_webhook(tc, failure_envelope(), event_id="evt_sim")
    assert r.json()["evidence_mode"] == "SIMULATED"
    assert tc.get("/health").json()["evidence_mode"] == "SIMULATED"


# --- unsupported shapes -------------------------------------


@pytest.mark.parametrize("event", ["payment.refunded", "subscription.charged", "", "nope"])
def test_unsupported_event_type_rejected(event):
    tc, eng = make_client()
    r = post_webhook(tc, failure_envelope(event=event), event_id="evt_unsup")
    assert r.status_code == 422
    assert eng.inspect(BatchQuery()).cases == 0


def test_unsupported_shape_missing_subscription_rejected():
    tc, eng = make_client()
    body = {"event": "payment.failed",
            "payload": {"payment": {"entity": {"id": "pay_1", "amount": 100}}}}
    r = post_webhook(tc, body, event_id="evt_noshape")
    assert r.status_code == 422
    assert eng.inspect(BatchQuery()).cases == 0


# --- demo run (logical-time control) ----------------------


def test_demo_run_controls_logical_time():
    tc, _ = make_client()
    post_webhook(tc, failure_envelope(), event_id="evt_run")

    r1 = tc.post("/demo/run", json={"until": 3})
    assert r1.status_code == 200 and r1.json()["logical_time"] == 3

    back = tc.post("/demo/run", json={"until": 1})
    assert back.status_code == 409  # logical time cannot move backward

    r2 = tc.post("/demo/run", json={"until": 5})
    assert r2.status_code == 200 and r2.json()["logical_time"] == 5


@pytest.mark.parametrize("bad", ["soon", True, 1.5, None])
def test_demo_run_rejects_non_integer_until(bad):
    tc, _ = make_client()
    r = tc.post("/demo/run", json={"until": bad})
    assert r.status_code == 400


def test_webhook_ingestion_does_not_run_the_recovery_loop():
    tc, eng = make_client()
    r = post_webhook(tc, failure_envelope(), event_id="evt_noloop")
    cid = r.json()["case_id"]
    kinds = eng.inspect(AuditQuery(case_id=cid)).kinds()
    assert "AI_PROPOSAL" not in kinds  # no strategist call during ingest
    assert "SCHEDULED_ACTION" not in kinds
    assert eng.inspect(CaseQuery(case_id=cid)).state == "active"


# --- projection endpoint ------------------------------------


def test_get_case_projection_shape_and_404():
    tc, _ = make_client()
    r = post_webhook(tc, failure_envelope(), event_id="evt_proj")
    proj = tc.get(f"/cases/{r.json()['case_id']}").json()
    for key in ("case_id", "obligation_id", "state", "amount_minor", "currency",
                "counted", "linked_payment_id", "pending_work", "version",
                "attribution", "recovered_minor", "action_intents"):
        assert key in proj
    assert isinstance(proj["action_intents"], list)

    assert tc.get("/cases/case-does-not-exist").status_code == 404


# --- no module-level secret / no global engine -----------


def test_no_module_level_secret_or_global_engine():
    import hermes.api as api_mod

    assert not hasattr(api_mod, "webhook_secret")
    assert not any(isinstance(v, RecoveryEngine) for v in vars(api_mod).values())
    assert SECRET not in getattr(api_mod, "__doc__", "")


def test_two_apps_have_independent_engines():
    tc1, e1 = make_client()
    tc2, e2 = make_client()
    post_webhook(tc1, failure_envelope(sub="sub_A"), event_id="evt_a")
    assert e1.inspect(BatchQuery()).cases == 1
    assert e2.inspect(BatchQuery()).cases == 0  # no shared global state
