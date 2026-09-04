"""Correction 1: restarting the WHOLE app over the same durable store keeps
every existing case usable, reconstructs the trusted synthetic context and the
simulated provider's retry facts, mints genuinely-new fresh cases, and still
cannot double-count a duplicate payment. Offline (in-memory snapshot store).
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import json  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from hermes.adapters import FakeRazorpayAdapter  # noqa: E402
from hermes.api import ApiConfig, create_app  # noqa: E402
from hermes.demo_fixtures import demo_sign, failure_envelope  # noqa: E402
from hermes.pg_ledger import InMemorySnapshotStore, PgLedger  # noqa: E402
from hermes.runtime import Settings, _bootstrap_demo_state, build_engine  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")
SECRET = "demosig_restart_test"


def app_over(store: InMemorySnapshotStore) -> TestClient:
    """A fresh app process sharing the given durable store."""
    settings = Settings.load(mode="offline", load_env=False)
    razorpay = FakeRazorpayAdapter()
    ledger = PgLedger(store)
    engine = build_engine(settings, ledger=ledger, razorpay=razorpay)
    mctx, next_serial = _bootstrap_demo_state(engine, ledger, razorpay)
    app = create_app(
        engine=engine, config=ApiConfig(webhook_secret=SECRET), razorpay=razorpay,
        merchant_context=mctx, demo_serial_start=next_serial, on_shutdown=ledger.close,
        ledger=ledger,
    )
    return TestClient(app)


def _post_signed_webhook(tc: TestClient, envelope: dict, event_id: str):
    raw = json.dumps(envelope).encode("utf-8")
    return tc.post("/webhooks/razorpay", content=raw,
                   headers={"x-razorpay-signature": demo_sign(SECRET, raw),
                            "x-razorpay-event-id": event_id})


def test_existing_case_retains_its_facts_and_can_finish_after_full_restart():
    store = InMemorySnapshotStore()

    c1 = app_over(store)
    opened = c1.post("/demo/case").json()
    cid, obl = opened["case_id"], opened["obligation_id"]
    c1.post("/demo/step", json={"case_id": cid, "step": "advance"})
    assert c1.get(f"/demo/case/{cid}").json()["case"]["state"] == "waiting"

    # --- restart: brand-new app over the SAME store ---
    c2 = app_over(store)
    view = c2.get(f"/demo/case/{cid}").json()["case"]
    assert view["state"] == "waiting"  # case + pending work survived
    assert view["obligation_id"] == obl
    assert view["communication_owner"] == "merchant"  # merchant facts persisted on the case

    # the provider's retry eligibility was reconstructed -> the case can finish
    c2.post("/demo/step", json={"case_id": cid, "step": "retry_failed"})
    link = c2.get(f"/demo/case/{cid}").json()["case"]
    assert link["links_created"] == 1
    cap = c2.post("/demo/step", json={"case_id": cid, "step": "capture"}).json()
    assert cap["capture"]["accepted"] is True
    final = c2.get(f"/demo/case/{cid}").json()["case"]
    assert final["state"] == "recovered" and final["attribution"] == "hermes_assisted"
    assert final["recovered_minor"] == 1_000_000


def test_fresh_case_after_restart_is_genuinely_new():
    store = InMemorySnapshotStore()
    c1 = app_over(store)
    a = c1.post("/demo/case").json()

    c2 = app_over(store)  # demo_serial was reset in this process
    b = c2.post("/demo/case").json()

    assert b["case_id"] != a["case_id"]
    assert b["obligation_id"] != a["obligation_id"]
    # the first case is untouched
    assert c2.get(f"/demo/case/{a['case_id']}").json()["case"]["state"] == "active"
    from hermes.types import BatchQuery
    assert c2.app.state.engine.inspect(BatchQuery()).cases == 2


def test_duplicate_payment_delivery_still_cannot_double_count_after_restart():
    store = InMemorySnapshotStore()
    c1 = app_over(store)
    opened = c1.post("/demo/case").json()
    cid = opened["case_id"]
    c1.post("/demo/step", json={"case_id": cid, "step": "advance"})
    c1.post("/demo/step", json={"case_id": cid, "step": "retry_failed"})
    c1.post("/demo/step", json={"case_id": cid, "step": "capture"})

    c2 = app_over(store)  # restart
    before = c2.get(f"/demo/case/{cid}").json()["case"]["recovered_minor"]
    dup = c2.post("/demo/step", json={"case_id": cid, "step": "capture"}).json()
    after = c2.get(f"/demo/case/{cid}").json()["case"]["recovered_minor"]

    assert dup["capture"]["duplicate"] is True
    assert before == after == 1_000_000
    from hermes.types import BatchQuery
    assert c2.app.state.engine.inspect(BatchQuery()).recovered_minor == 1_000_000


def test_unknown_case_stays_contact_denied_with_no_fabricated_retry_after_restart():
    """An externally ingested obligation - even one whose id mimics the demo
    prefix - carries no DEMO_CASE_PROVENANCE, so restart must not invent consent,
    reachability, or provider retry eligibility for it."""
    store = InMemorySnapshotStore()

    c1 = app_over(store)
    ext_obl = "sub_demo_4242_spoofed"  # deliberately demo-looking; still untrusted
    r = _post_signed_webhook(
        c1, failure_envelope(ext_obl, payment_id=f"pay_{ext_obl}_0"),
        event_id=f"evt_{ext_obl}_0",
    )
    assert r.status_code == 200
    cid = r.json()["case_id"]
    snap1 = c1.app.state.ledger.case_snapshot(cid)
    assert snap1.consent is False and snap1.reachable_channel is False

    # --- restart over the same store, then ingest another event for it ---
    c2 = app_over(store)
    assert ext_obl not in c2.app.state.merchant_context  # not reconstructed
    r2 = _post_signed_webhook(
        c2, failure_envelope(ext_obl, payment_id=f"pay_{ext_obl}_1"),
        event_id=f"evt_{ext_obl}_1",
    )
    assert r2.status_code == 200

    snap2 = c2.app.state.ledger.case_snapshot(cid)
    assert snap2.consent is False and snap2.reachable_channel is False
    # provider retry eligibility was never fabricated -> fail-closed
    fact = c2.app.state.razorpay.retry_eligibility(ext_obl)
    assert fact.retry_eligible is False and fact.evidence is None
