"""Durable ledger: the tested in-memory recovery logic + a Postgres snapshot.

Design (demo-grade, deliberately simple):

- ``InMemoryLedger`` remains the single implementation of every ledger
  guarantee - atomicity, event dedup, case version/state guards, action-intent
  ordering, deterministic attribution, unique-payment accounting, the persisted
  logical clock, and pending work. ``PgLedger`` does not re-implement any of it.
- After every mutating call, ``PgLedger`` serialises the whole ledger state to
  one JSON document and writes it through a :class:`SnapshotStore` in a single
  committed transaction. Reads go straight to the in-memory state.
- Each committed snapshot is a consistent whole-ledger state, so a crash loses
  at most the last un-persisted operation; a restarted process reloads the last
  snapshot and the redelivered webhook replays. If the write fails, the
  in-memory state is rolled back to the last committed snapshot and the error
  is raised to the caller (who retries / the provider redelivers).

The Postgres store uses a dedicated schema and a single ``ledger_state`` row.
Initialisation is ``CREATE SCHEMA IF NOT EXISTS`` / ``CREATE TABLE IF NOT
EXISTS`` only - it never drops or resets anything.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import threading
import time
from typing import Any, Callable, Protocol

from .adapters import InMemoryLedger
from .types import (
    ActionIntent,
    AuditEvent,
    Case,
    CaseState,
    ScheduledWork,
)

_SNAPSHOT_VERSION = 1
_DEFAULT_SCHEMA = "hermes_demo"
_SCHEMA_RE = re.compile(r"\A[a-z_][a-z0-9_]{0,62}\Z")

# Bounds on opening the database connection. Neon serverless holds the
# connection open while it *resumes* suspended compute; measured resume latency
# on this project's endpoint was ~25s warm-ish and 45s to >75s from fully cold,
# and it is variable (one attempt can stall past the ceiling while the next
# succeeds once resume has kicked in). libpq's ``connect_timeout`` only covers
# the pure-TCP phase, so an unbounded ``psycopg.connect`` hangs the whole app
# import (uvicorn never prints its banner). We therefore bound EACH attempt and
# retry a few times within a finite total. Once connected Neon stays warm for
# minutes, so this cost is paid at most once per demo session. Both knobs are
# overridable (HERMES_DB_CONNECT_TIMEOUT_S = total; HERMES_DB_CONNECT_ATTEMPTS).
_DEFAULT_CONNECT_TIMEOUT_S = 150.0
_DEFAULT_CONNECT_ATTEMPTS = 3
_PER_ATTEMPT_CEILING_S = 55.0
_RETRY_BACKOFF_S = 2.0


def _connect_once(psycopg: Any, dsn: str, per_attempt_s: float):
    box: dict[str, Any] = {}

    def _work() -> None:
        try:
            box["conn"] = psycopg.connect(dsn, connect_timeout=max(5, int(per_attempt_s)))
        except BaseException as exc:  # noqa: BLE001 - reported by type only
            box["err"] = exc

    th = threading.Thread(target=_work, name="pg-connect", daemon=True)
    th.start()
    th.join(per_attempt_s)
    if th.is_alive():
        # Orphaned daemon thread; it dies with the process (which exits via a
        # sanitised SystemExit on the failure path).
        return None, "timeout"
    if "err" in box:
        return None, type(box["err"]).__name__
    return box["conn"], None


def _connect_bounded(psycopg: Any, dsn: str, total_timeout_s: float,
                     attempts: int | None = None):
    """``psycopg.connect`` with a bounded per-attempt timeout, retried within a
    finite total. Raises ``RuntimeError`` (never the DSN) so the ASGI
    entrypoint reports a sanitised startup failure instead of stalling."""
    if attempts is None:
        try:
            attempts = int(os.environ.get("HERMES_DB_CONNECT_ATTEMPTS",
                                          _DEFAULT_CONNECT_ATTEMPTS))
        except (TypeError, ValueError):
            attempts = _DEFAULT_CONNECT_ATTEMPTS
    attempts = max(1, attempts)
    deadline = time.monotonic() + total_timeout_s
    last = "timeout"
    for i in range(attempts):
        remaining = deadline - time.monotonic()
        if remaining <= 1:
            break
        conn, err = _connect_once(psycopg, dsn, min(remaining, _PER_ATTEMPT_CEILING_S))
        if conn is not None:
            return conn
        last = err or "unknown"
        if i + 1 < attempts and deadline - time.monotonic() > _RETRY_BACKOFF_S + 1:
            time.sleep(_RETRY_BACKOFF_S)
    raise RuntimeError(
        f"database connection did not succeed in {int(total_timeout_s)}s "
        f"across {attempts} attempt(s) (last: {last}). Neon compute may be "
        "resuming - retry, or raise HERMES_DB_CONNECT_TIMEOUT_S / "
        "HERMES_DB_CONNECT_ATTEMPTS."
    )


# --- (de)serialisation of the whole in-memory ledger ----------------------


def dump_ledger(mem: InMemoryLedger) -> dict[str, Any]:
    """Serialise every private field of an ``InMemoryLedger`` to a JSON-safe
    dict. Uses ``dataclasses.asdict`` for records, then fixes the two
    non-JSON-native field types (``CaseState`` enum, ``frozenset``)."""

    def _case(c: Case) -> dict:
        d = dataclasses.asdict(c)
        d["state"] = c.state.value
        d["link_references"] = sorted(c.link_references)
        return d

    return {
        "snapshot_version": _SNAPSHOT_VERSION,
        "clock": mem._clock,
        "seq": mem._seq,
        "id_seq": mem._id_seq,
        "recovered_minor": mem._recovered_minor,
        "seen_events": sorted(mem._seen_events),
        "recovered_payment_ids": sorted(mem._recovered_payment_ids),
        "by_obligation": dict(mem._by_obligation),
        "cases": {k: _case(v) for k, v in mem._cases.items()},
        "work": {k: dataclasses.asdict(v) for k, v in mem._work.items()},
        "audit": [dataclasses.asdict(e) for e in mem._audit],
        "action_intents": {k: dataclasses.asdict(v) for k, v in mem._action_intents.items()},
        "intents_by_key": [[a, b, c] for (a, b), c in mem._intents_by_key.items()],
    }


def load_ledger(data: dict[str, Any] | None) -> InMemoryLedger:
    """Rebuild an ``InMemoryLedger`` from :func:`dump_ledger` output. An empty
    / missing document yields a fresh ledger."""
    mem = InMemoryLedger()
    if not data:
        return mem
    mem._clock = int(data["clock"])
    mem._seq = int(data["seq"])
    mem._id_seq = int(data["id_seq"])
    mem._recovered_minor = int(data["recovered_minor"])
    mem._seen_events = set(data["seen_events"])
    mem._recovered_payment_ids = set(data["recovered_payment_ids"])
    mem._by_obligation = dict(data["by_obligation"])
    mem._cases = {
        k: Case(**{**v, "state": CaseState(v["state"]),
                   "link_references": frozenset(v["link_references"])})
        for k, v in data["cases"].items()
    }
    mem._work = {k: ScheduledWork(**v) for k, v in data["work"].items()}
    mem._audit = [AuditEvent(**e) for e in data["audit"]]
    mem._action_intents = {k: ActionIntent(**v) for k, v in data["action_intents"].items()}
    mem._intents_by_key = {(a, b): c for a, b, c in data["intents_by_key"]}
    return mem


# --- snapshot store seam -----------------------------------------------


class SnapshotStore(Protocol):
    def read(self) -> dict[str, Any] | None: ...
    def write(self, data: dict[str, Any]) -> None: ...  # one committed transaction
    def close(self) -> None: ...


class InMemorySnapshotStore:
    """Non-durable store for tests: keeps the last written snapshot in a Python
    object so a new ``PgLedger`` over the same store simulates a restart."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self._data = data

    def read(self) -> dict[str, Any] | None:
        return json.loads(json.dumps(self._data)) if self._data is not None else None

    def write(self, data: dict[str, Any]) -> None:
        self._data = json.loads(json.dumps(data))  # force JSON round-trip like the real store

    def close(self) -> None:  # nothing to release
        pass


def _validate_schema(schema: str) -> str:
    if not _SCHEMA_RE.match(schema):
        raise ValueError(f"invalid schema name: {schema!r}")
    return schema


def _advisory_key(schema: str) -> int:
    """A stable signed 64-bit key for ``pg_advisory_lock`` derived from the
    schema name."""
    return int.from_bytes(hashlib.sha256(schema.encode("utf-8")).digest()[:8],
                          "big", signed=True)


class PostgresSnapshotStore:
    """The real durable store: one JSONB row in ``<schema>.ledger_state``.
    Requires ``psycopg`` (the optional ``[db]`` extra) - imported lazily.

    Single writer: on connect it takes a session-scoped ``pg_advisory_lock`` on
    a key derived from the schema name. A second process opening the same
    schema fails fast with a clear message instead of clobbering committed
    state. The lock is released on :meth:`close` and, failing that, when the
    session ends.

    Every statement runs in a transaction that is rolled back on any error so
    the connection stays usable (psycopg leaves a failed transaction aborted).
    """

    def __init__(self, dsn: str, schema: str = _DEFAULT_SCHEMA,
                 *, _psycopg: Any | None = None,
                 connect_timeout_s: float | None = None) -> None:
        psycopg = _psycopg
        if psycopg is None:
            import psycopg  # noqa: PLC0415 - optional dependency, lazy

        self._schema = _validate_schema(schema)
        self._key = _advisory_key(self._schema)
        if connect_timeout_s is None:
            try:
                connect_timeout_s = float(os.environ.get(
                    "HERMES_DB_CONNECT_TIMEOUT_S", _DEFAULT_CONNECT_TIMEOUT_S))
            except (TypeError, ValueError):
                connect_timeout_s = _DEFAULT_CONNECT_TIMEOUT_S
        self._conn = _connect_bounded(psycopg, dsn, connect_timeout_s)
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s)", (self._key,))
                got = bool(cur.fetchone()[0])
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            self._conn.close()
            raise
        if not got:
            self._conn.close()
            raise RuntimeError(
                f"another process holds the demo writer lock for schema "
                f"'{self._schema}'. Stop the other app, or use a different "
                "HERMES_DEMO_SCHEMA."
            )

    def read(self) -> dict[str, Any] | None:
        try:
            with self._conn.cursor() as cur:
                cur.execute(f"SELECT data FROM {self._schema}.ledger_state WHERE id = 1")
                row = cur.fetchone()
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        if row is None:
            raise RuntimeError(
                f"{self._schema}.ledger_state is not initialised - run "
                "`python scripts/init_neon.py` against DATABASE_URL first"
            )
        return row[0] or None

    def write(self, data: dict[str, Any]) -> None:
        payload = json.dumps(data)
        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {self._schema}.ledger_state "
                    f"SET data = %s::jsonb, updated_at = now() WHERE id = 1",
                    (payload,),
                )
                if cur.rowcount != 1:  # pragma: no cover - init guarantees the row
                    raise RuntimeError("ledger_state row missing; run init first")
            self._conn.commit()
        except Exception:
            self._conn.rollback()  # keep the connection usable for a retry
            raise

    def close(self) -> None:
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (self._key,))
            self._conn.commit()
        except Exception:
            pass
        self._conn.close()


# --- the durable ledger -----------------------------------------------


class PgLedger:
    """A :class:`~hermes.protocols.Ledger` that persists after every write.

    Reads delegate straight to the in-memory state; mutations run in memory and
    are then written through the store in one committed transaction. A write
    failure rolls the in-memory state back to the last committed snapshot.
    """

    _READS = frozenset({
        "logical_clock", "has_seen_event", "case_id_for_obligation", "case_ids",
        "case_snapshot", "case_projection", "batch_projection", "audit_projection",
    })
    _WRITES = frozenset({
        "advance_clock", "claim_due_work", "apply_intake", "mark_event_seen",
        "note_event", "apply_evaluation", "apply_strategist_failure",
        "apply_capture", "apply_action_outcome", "discard_work",
    })

    def __init__(self, store: SnapshotStore) -> None:
        self._store = store
        self._mem = load_ledger(store.read())
        self._last_json = json.dumps(dump_ledger(self._mem))
        self._lock = threading.RLock()  # serialises each op; NOT held across an
        # engine's strategist call (that happens between ledger ops)

    def close(self) -> None:
        with self._lock:
            self._store.close()

    # -- delegation --------------------------------------------------

    def _delegate(self, name: str) -> Callable[..., Any]:
        # The bound method is resolved INSIDE the lock, not here: a rollback in
        # another operation replaces ``self._mem`` wholesale, so a call that
        # bound ``getattr(self._mem, name)`` before waiting on the lock would
        # otherwise read from / mutate the discarded object.
        if name in self._READS:
            def _read(*args: Any, **kwargs: Any) -> Any:
                with self._lock:
                    return getattr(self._mem, name)(*args, **kwargs)
            return _read
        if name in self._WRITES:
            def _committed(*args: Any, **kwargs: Any) -> Any:
                with self._lock:
                    try:
                        result = getattr(self._mem, name)(*args, **kwargs)
                        new_json = json.dumps(dump_ledger(self._mem))
                        self._store.write(json.loads(new_json))
                        self._last_json = new_json
                        return result
                    except BaseException:
                        # restore the in-memory state to the last committed snapshot
                        self._mem = load_ledger(json.loads(self._last_json))
                        raise
            return _committed
        raise AttributeError(name)

    def __getattr__(self, name: str) -> Any:
        # Only called for attributes not found normally.
        if name in self._READS or name in self._WRITES:
            return self._delegate(name)
        raise AttributeError(name)
