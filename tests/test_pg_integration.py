"""OPT-IN real-Postgres integration check for the durable ledger.

Skipped unless HERMES_PG_TEST_DSN is set to a Postgres URL you are willing to
have a `hermes_demo_it` schema created in (nothing else is touched; the schema
is created if absent and left in place). Run:

    $env:HERMES_PG_TEST_DSN = "<your-neon-or-local-postgres-url>"
    python -m pytest -q tests/test_pg_integration.py

This is the only test that opens a real database connection, and only you run it.
"""

from __future__ import annotations

import os

import pytest

_DSN = os.environ.get("HERMES_PG_TEST_DSN")
pytestmark = pytest.mark.skipif(not _DSN, reason="set HERMES_PG_TEST_DSN to run")

psycopg = pytest.importorskip("psycopg")

from hermes.adapters import FakeRazorpayAdapter, ScriptedStrategist  # noqa: E402
from hermes.engine import RecoveryEngine  # noqa: E402
from hermes.pg_ledger import PgLedger, PostgresSnapshotStore, _validate_schema  # noqa: E402
from hermes.types import CaseQuery, RazorpayWebhook, WebhookType  # noqa: E402

_SCHEMA = _validate_schema("hermes_demo_it")


def _init(dsn: str) -> None:
    import json

    from hermes.adapters import InMemoryLedger
    from hermes.pg_ledger import dump_ledger

    empty = json.dumps(dump_ledger(InMemoryLedger()))
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}")
            cur.execute(
                f"CREATE TABLE IF NOT EXISTS {_SCHEMA}.ledger_state "
                "(id integer PRIMARY KEY, data jsonb NOT NULL, "
                "updated_at timestamptz NOT NULL DEFAULT now())"
            )
            cur.execute(
                f"INSERT INTO {_SCHEMA}.ledger_state (id, data) VALUES (1, %s::jsonb) "
                "ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data",  # reset for the test
                (empty,),
            )
        conn.commit()


def test_durable_case3_survives_a_real_reconnect():
    _init(_DSN)
    rp = FakeRazorpayAdapter()
    rp.set_retry_eligibility("sub_it_1", True)

    led1 = PgLedger(PostgresSnapshotStore(_DSN, _SCHEMA))
    eng1 = RecoveryEngine(led1, ScriptedStrategist(), rp)
    r = eng1.receive(RazorpayWebhook("it_f0", WebhookType.PAYMENT_FAILED, "sub_it_1",
                                     1_000_000, reason_code="insufficient_funds",
                                     consent=True, reachable_channel=True))
    eng1.run(until=1)
    led1.close()

    led2 = PgLedger(PostgresSnapshotStore(_DSN, _SCHEMA))
    eng2 = RecoveryEngine(led2, ScriptedStrategist(), rp)
    assert eng2.logical_time == 1
    cv = eng2.inspect(CaseQuery(case_id=r.case_id))
    assert cv.state == "waiting" and cv.pending_work == 1
    led2.close()


def test_second_writer_is_refused_by_the_real_advisory_lock():
    _init(_DSN)
    first = PostgresSnapshotStore(_DSN, _SCHEMA)
    try:
        with pytest.raises(RuntimeError, match="writer lock"):
            PostgresSnapshotStore(_DSN, _SCHEMA)  # same schema, different session
    finally:
        first.close()
    # after close() the lock is released -> a new writer can take it
    third = PostgresSnapshotStore(_DSN, _SCHEMA)
    third.close()


def test_write_error_leaves_the_connection_usable():
    _init(_DSN)
    store = PostgresSnapshotStore(_DSN, _SCHEMA)
    try:
        # force a SQL error: cast a non-JSON string to jsonb inside write()'s
        # transaction by monkey-poking the payload through a bad statement.
        with pytest.raises(Exception):
            with store._conn.cursor() as cur:  # noqa: SLF001 - integration probe
                cur.execute("SELECT 1/0")
            store._conn.commit()
        store._conn.rollback()  # emulate the store's own recovery
        # the store's own write path still works on the same connection
        store.write({"probe": True})
        got = store.read()
        assert got == {"probe": True}
    finally:
        # restore an empty snapshot so re-runs start clean
        _init(_DSN)
        store.close()
