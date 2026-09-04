"""Offline tests for the durable ledger: dump/hydrate round-trip, restart
recovery through an in-memory snapshot store (no real Postgres), write-failure
rollback, and clock persistence. Opt-in real-Postgres checks are in
tests/integration/ and skip unless HERMES_PG_TEST_DSN is set.
"""

from __future__ import annotations

import pytest

from hermes.adapters import FakeRazorpayAdapter, InMemoryLedger, ScriptedStrategist
from hermes.engine import RecoveryEngine
from hermes.pg_ledger import (
    InMemorySnapshotStore,
    PgLedger,
    dump_ledger,
    load_ledger,
)
from hermes.types import AuditQuery, BatchQuery, CaseQuery, RazorpayWebhook, WebhookType

AMOUNT = 1_000_000
OBL = "sub_pg_0001"


def _failed(event_id, obl=OBL, reason="insufficient_funds"):
    return RazorpayWebhook(event_id, WebhookType.PAYMENT_FAILED, obl, AMOUNT,
                           reason_code=reason, consent=True, reachable_channel=True)


def _captured(event_id, payment_id, obl=OBL):
    return RazorpayWebhook(event_id, WebhookType.PAYMENT_CAPTURED, obl, AMOUNT,
                           payment_id=payment_id)


def _drive_case3(engine, razorpay, obl=OBL):
    """failure -> eligible wait -> failed retry -> recovery link -> capture."""
    razorpay.set_retry_eligibility(obl, True)
    r = engine.receive(_failed("e_f0", obl))
    engine.run(until=1)                       # WAIT authorized
    engine.receive(_failed("e_r1", obl))     # failed retry outcome
    razorpay.set_retry_eligibility(obl, False)
    engine.run(until=2)                       # -> CREATE_RECOVERY_LINK executed
    cv = engine.inspect(CaseQuery(case_id=r.case_id))
    link_ref = cv.action_intents[0].reference
    engine.receive(_captured("e_cap", link_ref, obl))
    return r.case_id, link_ref


# --- dump / hydrate round-trip -----------------------------------------


def test_dump_hydrate_round_trips_a_full_case3_ledger():
    mem = InMemoryLedger()
    rp = FakeRazorpayAdapter()
    engine = RecoveryEngine(mem, ScriptedStrategist(), rp)
    case_id, link_ref = _drive_case3(engine, rp)

    restored = load_ledger(dump_ledger(mem))

    # projections identical
    assert restored.case_projection(case_id=case_id) == mem.case_projection(case_id=case_id)
    assert restored.batch_projection() == mem.batch_projection()
    assert restored.audit_projection(case_id).records == mem.audit_projection(case_id).records
    assert restored.logical_clock() == mem.logical_clock() == 2
    assert restored.has_seen_event("e_cap") is True
    # the recovered case is terminal + hermes_assisted
    cv = restored.case_projection(case_id=case_id)
    assert cv.state == "recovered" and cv.attribution == "hermes_assisted"
    assert cv.recovered_minor == AMOUNT and link_ref == cv.linked_payment_id


def test_hydrate_of_empty_is_a_fresh_ledger():
    mem = load_ledger(None)
    assert mem.logical_clock() == 0 and mem.batch_projection().cases == 0
    assert load_ledger({}).batch_projection().cases == 0


# --- restart through the snapshot store -------------------------------


def test_pgledger_survives_a_simulated_restart():
    store = InMemorySnapshotStore()
    rp = FakeRazorpayAdapter()

    led1 = PgLedger(store)
    eng1 = RecoveryEngine(led1, ScriptedStrategist(), rp)
    rp.set_retry_eligibility(OBL, True)
    r = eng1.receive(_failed("e_f0"))
    eng1.run(until=1)  # case is now WAITING with pending work at hour 25
    assert eng1.inspect(CaseQuery(case_id=r.case_id)).state == "waiting"
    assert eng1.logical_time == 1
    led1.close()

    # fresh process: new ledger over the SAME store, new engine
    led2 = PgLedger(store)
    eng2 = RecoveryEngine(led2, ScriptedStrategist(), rp)
    assert eng2.logical_time == 1  # clock resumed, not reset
    cv = eng2.inspect(CaseQuery(case_id=r.case_id))
    assert cv.state == "waiting" and cv.pending_work == 1  # pending work preserved
    assert eng2.inspect(BatchQuery()).cases == 1

    # continue where we left off: failed retry -> link -> capture -> recovered
    eng2.receive(_failed("e_r1"))
    rp.set_retry_eligibility(OBL, False)
    eng2.run(until=2)
    link_ref = eng2.inspect(CaseQuery(case_id=r.case_id)).action_intents[0].reference
    eng2.receive(_captured("e_cap", link_ref))
    final = eng2.inspect(CaseQuery(case_id=r.case_id))
    assert final.state == "recovered" and final.attribution == "hermes_assisted"

    # and it is still durable for a third restart
    led3 = PgLedger(store)
    assert led3.case_projection(case_id=r.case_id).state == "recovered"


def test_starting_a_second_case_does_not_erase_the_first():
    store = InMemorySnapshotStore()
    rp = FakeRazorpayAdapter()
    led = PgLedger(store)
    eng = RecoveryEngine(led, ScriptedStrategist(), rp)
    rp.set_retry_eligibility("sub_A", True)
    rp.set_retry_eligibility("sub_B", True)
    a = eng.receive(_failed("a0", "sub_A"))
    b = eng.receive(_failed("b0", "sub_B"))
    eng.run(until=1)
    assert eng.inspect(BatchQuery()).cases == 2

    led2 = PgLedger(store)
    assert led2.case_projection(case_id=a.case_id).obligation_id == "sub_A"
    assert led2.case_projection(case_id=b.case_id).obligation_id == "sub_B"


# --- write-failure rollback ----------------------------------------


class _FailOnNthWrite(InMemorySnapshotStore):
    def __init__(self, fail_on: int):
        super().__init__()
        self._n = 0
        self._fail_on = fail_on

    def write(self, data):
        self._n += 1
        if self._n == self._fail_on:
            raise RuntimeError("snapshot store write failed")
        super().write(data)


def test_write_failure_rolls_the_in_memory_state_back():
    store = _FailOnNthWrite(fail_on=2)
    rp = FakeRazorpayAdapter()
    led = PgLedger(store)
    eng = RecoveryEngine(led, ScriptedStrategist(), rp)
    rp.set_retry_eligibility(OBL, True)
    eng.receive(_failed("e_f0"))          # write 1 ok
    before_clock = led.logical_clock()

    with pytest.raises(RuntimeError):
        led.advance_clock(before_clock + 5)  # write 2 -> fails

    # the failed op left NO trace: clock unchanged, matches the last snapshot
    assert led.logical_clock() == before_clock
    reloaded = PgLedger(store)
    assert reloaded.logical_clock() == before_clock


# --- clock monotonicity ------------------------------------------


def test_advance_clock_is_monotonic():
    led = PgLedger(InMemorySnapshotStore())
    led.advance_clock(10)
    with pytest.raises(ValueError):
        led.advance_clock(4)
    assert led.logical_clock() == 10


# --- correction 4: PostgresSnapshotStore rollback + single writer -------
#     (fully offline via a fake psycopg module; real DB checks are opt-in
#      in tests/test_pg_integration.py)


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._conn.calls.append(sql.strip().split()[0].upper())
        if self._conn.fail_next:
            self._conn.fail_next = False
            self._conn.aborted = True
            raise RuntimeError("simulated SQL error")
        if self._conn.aborted:
            raise RuntimeError("current transaction is aborted")
        self._sql = sql

    def fetchone(self):
        if "pg_try_advisory_lock" in getattr(self, "_sql", ""):
            return (self._conn.lock_grants.pop(0) if self._conn.lock_grants else True,)
        if "SELECT data" in getattr(self, "_sql", ""):
            return (self._conn.row,)  # (None,) or (dict,)
        return (None,)

    @property
    def rowcount(self):
        return self._conn.rowcount


class _FakeConn:
    def __init__(self, *, row=None, rowcount=1, lock_grants=None):
        self.row = row
        self.rowcount = rowcount
        self.lock_grants = list(lock_grants) if lock_grants is not None else [True]
        self.calls: list[str] = []
        self.fail_next = False
        self.aborted = False
        self.closed = False

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        pass

    def rollback(self):
        self.aborted = False
        self.calls.append("ROLLBACK")

    def close(self):
        self.closed = True


class _FakePsycopg:
    def __init__(self, conn):
        self._conn = conn

    def connect(self, dsn):
        return self._conn


def _empty_dump():
    from hermes.pg_ledger import dump_ledger

    return dump_ledger(InMemoryLedger())


def _store(conn):
    from hermes.pg_ledger import PostgresSnapshotStore

    return PostgresSnapshotStore("postgresql://x", "hermes_demo_t", _psycopg=_FakePsycopg(conn))


def test_postgres_store_rolls_back_and_stays_usable_after_a_write_error():
    conn = _FakeConn(row=_empty_dump(), rowcount=1)
    store = _store(conn)
    conn.fail_next = True

    with pytest.raises(RuntimeError):
        store.write({"clock": 1})

    assert "ROLLBACK" in conn.calls and conn.aborted is False  # connection restored
    conn.calls.clear()
    store.write({"clock": 2})  # a subsequent write now succeeds
    assert "ROLLBACK" not in conn.calls


def test_second_writer_is_refused_the_advisory_lock():
    _store(_FakeConn(row=_empty_dump(), lock_grants=[True]))  # first holder: ok
    denied_conn = _FakeConn(row=_empty_dump(), lock_grants=[False])
    with pytest.raises(RuntimeError, match="writer lock"):
        _store(denied_conn)
    assert denied_conn.closed is True  # the refused connection is released


def test_close_releases_the_advisory_lock():
    conn = _FakeConn(row=_empty_dump(), lock_grants=[True])
    store = _store(conn)
    store.close()
    assert "SELECT" in conn.calls  # pg_advisory_unlock issued
    assert conn.closed is True
