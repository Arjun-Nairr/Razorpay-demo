"""Correction 1: restarting the WHOLE app over the same durable store keeps
every existing case usable, reconstructs the trusted synthetic context and the
simulated provider's retry facts, mints genuinely-new fresh cases, and still
cannot double-count a duplicate payment. Offline (in-memory snapshot store).
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from hermes.adapters import FakeRazorpayAdapter  # noqa: E402
from hermes.api import ApiConfig, create_app  # noqa: E402
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
    )
    return TestClient(app)


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
