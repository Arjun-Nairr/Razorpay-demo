"""Offline tests for the durable ledger: dump/hydrate round-trip, restart
recovery through an in-memory snapshot store (no real Postgres), write-failure
rollback, and clock persistence. Opt-in real-Postgres checks are in
tests/integration/ and skip unless HERMES_PG_TEST_DSN is set.
"""

from __future__ import annotations

import threading
import time

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


# --- fix 1: a callable bound before a rollback must act on the CURRENT ledger --


def test_callable_bound_before_rollback_operates_on_the_replaced_ledger():
    """``_delegate`` must resolve ``getattr(self._mem, name)`` inside the locked
    call, not when the callable is handed out: a rollback swaps ``self._mem`` for
    a fresh object, and a stale binding would read from / mutate the discarded
    one."""
    store = _FailOnNthWrite(fail_on=2)
    led = PgLedger(store)

    led.advance_clock(2)                       # write 1: committed, clock == 2
    queued_read = getattr(led, "logical_clock")   # bound BEFORE the rollback
    queued_write = getattr(led, "advance_clock")

    with pytest.raises(RuntimeError):
        led.advance_clock(5)                   # write 2 fails -> in-memory rollback

    # the discarded object reached clock 5; the live one is back at 2
    assert led.logical_clock() == 2
    assert queued_read() == 2                  # reads the CURRENT ledger, not the discard

    queued_write(7)                            # write 3: mutates the CURRENT ledger
    assert led.logical_clock() == 7
    assert PgLedger(store).logical_clock() == 7   # and it was the state that got persisted


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
    def __init__(self, conn, *, delay_s: float = 0.0, raises: BaseException | None = None):
        self._conn = conn
        self._delay_s = delay_s
        self._raises = raises
        self.connect_kwargs = None

    def connect(self, dsn, **kwargs):
        self.connect_kwargs = kwargs
        if self._delay_s:
            time.sleep(self._delay_s)
        if self._raises is not None:
            raise self._raises
        return self._conn


def _empty_dump():
    from hermes.pg_ledger import dump_ledger

    return dump_ledger(InMemoryLedger())


def _store(conn):
    from hermes.pg_ledger import PostgresSnapshotStore

    return PostgresSnapshotStore("postgresql://localhost/x", "hermes_demo_t", _psycopg=_FakePsycopg(conn))


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


# --- bounded, IPv4-preferring startup (Iteration 13) ---------------------
#   Real cause of the "silent stall": an IPv6 black hole - getaddrinfo returns
#   AAAA first and each dead IPv6 SYN cost ~21s before libpq fell through to
#   IPv4. Fix: hand libpq an IPv4 hostaddr, and bound connect + the
#   post-connect writer-lock probe within ONE startup budget.


def test_connect_that_hangs_is_bounded_not_infinite():
    from hermes.pg_ledger import PostgresSnapshotStore

    slow = _FakePsycopg(_FakeConn(row=_empty_dump()), delay_s=20)
    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match=r"within the 3s startup budget"):
        PostgresSnapshotStore("postgresql://localhost/x", "hermes_demo_t",
                              _psycopg=slow, connect_timeout_s=3)
    assert time.monotonic() - t0 < 6  # returned promptly, did not wait 20s


def test_connect_failure_is_sanitised_no_dsn_and_total_bounded():
    from hermes.pg_ledger import PostgresSnapshotStore

    boom = _FakePsycopg(_FakeConn(), raises=OSError("connection refused to secret-host:5432"))
    t0 = time.monotonic()
    with pytest.raises(RuntimeError) as ei:
        PostgresSnapshotStore("postgresql://user:pw@localhost/db", "hermes_demo_t",
                              _psycopg=boom, connect_timeout_s=8)
    msg = str(ei.value)
    assert "OSError" in msg and "startup budget" in msg  # type + budget only
    assert "secret-host" not in msg and "pw@" not in msg and "postgresql://" not in msg
    assert time.monotonic() - t0 < 10  # total-bounded, not attempts x per-attempt


def test_transient_failure_then_success_on_retry():
    from hermes.pg_ledger import PostgresSnapshotStore

    class _Flaky(_FakePsycopg):
        def __init__(self):
            super().__init__(_FakeConn(row=_empty_dump(), lock_grants=[True]))
            self.n = 0

        def connect(self, dsn, **kw):
            self.connect_kwargs = kw
            self.n += 1
            if self.n == 1:
                raise OSError("cold start")
            return self._conn

    fp = _Flaky()
    store = PostgresSnapshotStore("postgresql://localhost/x", "hermes_demo_t",
                                  _psycopg=fp, connect_timeout_s=30)
    assert fp.n == 2 and store.read() == _empty_dump()
    store.close()


def test_fast_connect_still_works_and_forwards_libpq_timeout():
    fp = _FakePsycopg(_FakeConn(row=_empty_dump(), lock_grants=[True]))
    from hermes.pg_ledger import PostgresSnapshotStore

    store = PostgresSnapshotStore("postgresql://localhost/x", "hermes_demo_t",
                                  _psycopg=fp, connect_timeout_s=30)
    assert store.read() == _empty_dump()
    assert fp.connect_kwargs.get("connect_timeout")  # per-address TCP bound forwarded
    store.close()


def test_env_var_sets_the_single_startup_budget(monkeypatch):
    from hermes.pg_ledger import PostgresSnapshotStore, _startup_budget_s

    monkeypatch.setenv("HERMES_DB_CONNECT_TIMEOUT_S", "3")
    monkeypatch.setenv("HERMES_DB_CONNECT_ATTEMPTS", "1")
    assert _startup_budget_s() == 3.0
    slow = _FakePsycopg(_FakeConn(row=_empty_dump()), delay_s=20)
    with pytest.raises(RuntimeError, match=r"within the 3s startup budget across 1 attempt"):
        PostgresSnapshotStore("postgresql://localhost/x", "hermes_demo_t", _psycopg=slow)


def test_ipv4_hostaddr_is_used_when_resolvable(monkeypatch):
    import hermes.pg_ledger as pg
    from hermes.pg_ledger import PostgresSnapshotStore

    monkeypatch.setattr(pg, "_ipv4_hostaddr", lambda dsn: "203.0.113.7")
    fp = _FakePsycopg(_FakeConn(row=_empty_dump(), lock_grants=[True]))
    store = PostgresSnapshotStore("postgresql://localhost/x", "hermes_demo_t",
                                  _psycopg=fp, connect_timeout_s=10)
    assert fp.connect_kwargs.get("hostaddr") == "203.0.113.7"  # cert still verified vs host
    store.close()


def test_post_connect_lock_probe_is_inside_the_budget():
    """A connection that opens fast but then never answers the writer-lock probe
    must still fail within the startup budget, not hang."""
    from hermes.pg_ledger import PostgresSnapshotStore

    class _SlowCursor(_FakeCursor):
        def execute(self, sql, params=None):
            if "pg_try_advisory_lock" in sql:
                time.sleep(20)
            return super().execute(sql, params)

    class _SlowConn(_FakeConn):
        def cursor(self):
            return _SlowCursor(self)

    fp = _FakePsycopg(_SlowConn(row=_empty_dump(), lock_grants=[True]))
    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match=r"writer-lock probe within the 3s startup budget"):
        PostgresSnapshotStore("postgresql://localhost/x", "hermes_demo_t",
                              _psycopg=fp, connect_timeout_s=3)
    assert time.monotonic() - t0 < 8


def test_no_fresh_grace_period_after_connect_exhausts_the_budget():
    """Regression: the lock-probe/read budget must be whatever time is LEFT
    after connect, never a re-granted minimum window. A connect that eats
    almost the whole budget must not buy the probe a fresh few seconds."""
    from hermes.pg_ledger import PostgresSnapshotStore

    class _HangingCursor(_FakeCursor):
        def execute(self, sql, params=None):
            if "pg_try_advisory_lock" in sql:
                time.sleep(20)
            return super().execute(sql, params)

    class _HangingConn(_FakeConn):
        def cursor(self):
            return _HangingCursor(self)

    fp = _FakePsycopg(_HangingConn(row=_empty_dump(), lock_grants=[True]), delay_s=1.8)
    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match=r"writer-lock probe within the 2s startup budget"):
        PostgresSnapshotStore("postgresql://localhost/x", "hermes_demo_t",
                              _psycopg=fp, connect_timeout_s=2)
    elapsed = time.monotonic() - t0
    # connect spent ~1.8s of the 2s budget; the probe must fail almost right
    # after (~0.2s more), not after a fresh multi-second window (the old bug:
    # a `max(2.0, ...)` floor re-granted 2 more seconds regardless).
    assert elapsed < 3.0


def test_stalled_dns_is_bounded_not_infinite(monkeypatch):
    """DNS pre-resolution used to run before the deadline clock started, so a
    hung resolver stalled forever. It must now consume its own bounded slice
    of the SAME startup budget and fall back (no pre-resolved hostaddr) rather
    than block the connect attempt behind it."""
    import hermes.pg_ledger as pg
    from hermes.pg_ledger import PostgresSnapshotStore

    def _hang(dsn):
        time.sleep(20)
        return "203.0.113.9"

    monkeypatch.setattr(pg, "_ipv4_hostaddr", _hang)
    fp = _FakePsycopg(_FakeConn(row=_empty_dump(), lock_grants=[True]))
    t0 = time.monotonic()
    store = PostgresSnapshotStore("postgresql://localhost/x", "hermes_demo_t",
                                  _psycopg=fp, connect_timeout_s=6)
    assert fp.connect_kwargs.get("hostaddr") is None  # DNS was abandoned, not awaited
    assert time.monotonic() - t0 < 6
    store.close()


def test_initial_read_is_bounded_not_infinite():
    """The first snapshot read used to run after all bounding was over. A
    hung initial read must fail within the same startup budget as connect and
    the lock probe, not block indefinitely."""
    from hermes.pg_ledger import PostgresSnapshotStore

    class _SlowReadCursor(_FakeCursor):
        def execute(self, sql, params=None):
            if "SELECT data" in sql:
                time.sleep(20)
                return
            return super().execute(sql, params)

    class _SlowReadConn(_FakeConn):
        def cursor(self):
            return _SlowReadCursor(self)

    fp = _FakePsycopg(_SlowReadConn(row=_empty_dump(), lock_grants=[True]))
    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match=r"initial read within the 3s startup budget"):
        PostgresSnapshotStore("postgresql://localhost/x", "hermes_demo_t",
                              _psycopg=fp, connect_timeout_s=3)
    assert time.monotonic() - t0 < 8


def test_timeout_cleanup_does_not_block_on_a_busy_connection():
    """Regression: after a writer-lock-probe timeout, cleanup used to call
    ``rollback()``/``close()`` synchronously on the SAME connection the probe
    thread might still be using. psycopg serialises access to a connection
    with its own internal lock, so that synchronous call would block until the
    stuck query returned - reintroducing the exact silent stall the startup
    budget exists to prevent. Simulate that lock with a real threading.Lock
    the stuck query holds throughout its "hang"."""
    from hermes.pg_ledger import PostgresSnapshotStore

    conn_lock = threading.Lock()

    class _BusyCursor(_FakeCursor):
        def execute(self, sql, params=None):
            if "pg_try_advisory_lock" in sql:
                with conn_lock:
                    time.sleep(20)  # simulates a query stuck on the wire
                return
            return super().execute(sql, params)

    class _BusyConn(_FakeConn):
        def cursor(self):
            return _BusyCursor(self)

        def rollback(self):
            with conn_lock:  # would block for ~20s if called synchronously
                super().rollback()

        def close(self):
            with conn_lock:  # same
                super().close()

    fp = _FakePsycopg(_BusyConn(row=_empty_dump(), lock_grants=[True]))
    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match=r"writer-lock probe within the 2s startup budget"):
        PostgresSnapshotStore("postgresql://localhost/x", "hermes_demo_t",
                              _psycopg=fp, connect_timeout_s=2)
    # returned promptly - cleanup did not wait on the busy connection's lock
    assert time.monotonic() - t0 < 5


def test_late_connection_race_at_the_timeout_boundary_is_never_leaked_or_double_delivered():
    """Force the exact boundary: the worker's ``connect()`` returns at
    (approximately) the same wall-clock instant the caller's join times out.
    Whichever side gets there first must win outright - the connection must
    end up EITHER returned to the caller open, OR closed by the worker -
    never dropped-and-open (leaked) and never claimed by both. Run many
    trials to actually land on the race window."""
    from hermes.pg_ledger import _connect_once

    per_attempt_s = 0.02
    for _ in range(50):
        conn = _FakeConn(row=_empty_dump())
        release = threading.Event()

        class _GatedPsycopg:
            def connect(self, dsn, **kw):
                release.wait(1.0)
                return conn

        threading.Timer(per_attempt_s, release.set).start()  # fires ~at the deadline
        got, err = _connect_once(_GatedPsycopg(), "postgresql://localhost/x",
                                 per_attempt_s=per_attempt_s, hostaddr=None)
        if got is not None:
            assert err is None and conn.closed is False
        else:
            assert err == "timeout"
            time.sleep(0.05)  # let a possibly-still-running worker close it
            assert conn.closed is True


def test_late_successful_connection_after_timeout_is_closed_not_leaked():
    """If a bounded attempt times out but the connection lands afterwards, the
    orphan thread closes it rather than leaking a Neon session."""
    from hermes.pg_ledger import _connect_once

    conn = _FakeConn(row=_empty_dump())
    fp = _FakePsycopg(conn, delay_s=1.5)
    got, err = _connect_once(fp, "postgresql://localhost/x", per_attempt_s=0.3, hostaddr=None)
    assert got is None and err == "timeout"
    time.sleep(2.0)  # let the orphan thread finish and self-close
    assert conn.closed is True
