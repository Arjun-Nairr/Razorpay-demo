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

# ONE bounded budget for the whole hermes/live startup DB phase: connect +
# advisory-lock probe + the initial snapshot read. The dominant historical cost
# was an IPv6 black hole - ``getaddrinfo`` returns AAAA records first and each
# dead IPv6 SYN cost ~21s before libpq fell through to IPv4 (which connects in
# ~0.1s). We now hand libpq an IPv4 ``hostaddr`` (TLS still verifies the cert
# against ``host``; ``sslmode``/``channel_binding`` from the DSN are untouched),
# so a genuine Neon pooler resume is the only remaining variable and it is
# small. 30s covers that with margin; override with HERMES_DB_CONNECT_TIMEOUT_S.
# The launcher waits this budget + a fixed margin, so its ceiling is always the
# looser one (see scripts/run_demo.ps1).
_DEFAULT_STARTUP_BUDGET_S = 30.0
_DEFAULT_CONNECT_ATTEMPTS = 2
_RETRY_BACKOFF_S = 2.0


def _startup_budget_s() -> float:
    try:
        return float(os.environ.get("HERMES_DB_CONNECT_TIMEOUT_S",
                                    _DEFAULT_STARTUP_BUDGET_S))
    except (TypeError, ValueError):
        return _DEFAULT_STARTUP_BUDGET_S


def _ipv4_hostaddr(dsn: str) -> str | None:
    """First IPv4 address for the DSN host, or None. Used as libpq ``hostaddr``
    so a black-holed IPv6 route cannot stall the connect. Best-effort: any
    failure just falls back to name resolution (dual-stack)."""
    try:
        import socket  # noqa: PLC0415
        import urllib.parse as up  # noqa: PLC0415

        host = up.urlparse(dsn).hostname
        if not host:
            return None
        for info in socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM):
            return info[4][0]
    except Exception:  # noqa: BLE001 - diagnostics only
        return None
    return None


def _bounded_best_effort(fn: Callable[[], Any], seconds: float) -> Any:
    """Run ``fn()`` on a daemon thread; return its result, or ``None`` on
    timeout/exception. Used for best-effort steps (DNS pre-resolution) that
    must never block past their share of the startup budget - a stall here
    just falls back to letting the next bounded step resolve it."""
    box: dict[str, Any] = {}

    def _w() -> None:
        try:
            box["v"] = fn()
        except Exception:  # noqa: BLE001
            pass

    th = threading.Thread(target=_w, name="pg-bestfx", daemon=True)
    th.start()
    th.join(max(0.0, seconds))
    return box.get("v")


def _connect_once(psycopg: Any, dsn: str, per_attempt_s: float, hostaddr: str | None):
    """One bounded ``psycopg.connect`` on a daemon thread. If the join times
    out, a late-successful connection on the orphan thread is closed rather than
    leaked.

    The connection's fate is decided under one lock shared by both threads, not
    by re-checking ``Event``/``is_alive`` independently: the worker and the
    joiner each try to *claim* the result, and whichever claims it first wins.
    That closes the boundary race where the worker sees "not abandoned yet",
    then the joiner times out and stops looking, and the worker's connection is
    never returned to anyone and never closed.
    """
    box: dict[str, Any] = {}
    lock = threading.Lock()
    state = {"claimed": False}

    def _work() -> None:
        try:
            kw = {"connect_timeout": max(5, int(per_attempt_s))}
            if hostaddr:
                kw["hostaddr"] = hostaddr  # cert still verified against host
            conn = psycopg.connect(dsn, **kw)
        except BaseException as exc:  # noqa: BLE001 - reported by type only
            with lock:
                if state["claimed"]:
                    return  # joiner already gave up and moved on; nothing to do
                box["err"] = exc
                state["claimed"] = True
            return
        with lock:
            if state["claimed"]:
                # joiner already gave up: close now, this thread is the only
                # remaining owner of the connection.
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
                box["late_closed"] = True
                return
            box["conn"] = conn
            state["claimed"] = True

    th = threading.Thread(target=_work, name="pg-connect", daemon=True)
    th.start()
    th.join(per_attempt_s)
    with lock:
        if state["claimed"]:
            # The worker delivered before/at the moment we looked, regardless
            # of th.is_alive() timing - we own the result now.
            if "conn" in box:
                return box["conn"], None
            return None, type(box["err"]).__name__
        state["claimed"] = True  # too late for the worker to hand us anything;
        # it will see this and close the connection itself.
    return None, "timeout"


def _connect_bounded(psycopg: Any, dsn: str, total_timeout_s: float,
                     attempts: int | None = None):
    """Open the connection within ``total_timeout_s`` total (a couple of bounded
    attempts). Raises ``RuntimeError`` - never the DSN - so the ASGI entrypoint
    reports a sanitised startup failure instead of stalling."""
    if attempts is None:
        try:
            attempts = int(os.environ.get("HERMES_DB_CONNECT_ATTEMPTS",
                                          _DEFAULT_CONNECT_ATTEMPTS))
        except (TypeError, ValueError):
            attempts = _DEFAULT_CONNECT_ATTEMPTS
    attempts = max(1, attempts)
    deadline = time.monotonic() + total_timeout_s
    # DNS pre-resolution is best-effort and must not itself stall past the
    # budget (a hung resolver used to block here with no timeout at all).
    # Give it a modest slice of the total budget; whatever remains still
    # goes to the connect attempt(s) below.
    dns_budget = max(0.5, min(5.0, total_timeout_s / 4, deadline - time.monotonic()))
    hostaddr = _bounded_best_effort(lambda: _ipv4_hostaddr(dsn), dns_budget)
    last = "timeout"
    for i in range(attempts):
        remaining = deadline - time.monotonic()
        if remaining <= 1:
            break
        conn, err = _connect_once(psycopg, dsn, remaining, hostaddr)
        if conn is not None:
            return conn
        last = err or "unknown"
        if i + 1 < attempts and deadline - time.monotonic() > _RETRY_BACKOFF_S + 1:
            time.sleep(_RETRY_BACKOFF_S)
    raise RuntimeError(
        f"database connection did not succeed within the {int(total_timeout_s)}s "
        f"startup budget across {attempts} attempt(s) (last: {last}). Check "
        "network/DNS to the DB host; raise HERMES_DB_CONNECT_TIMEOUT_S only if a "
        "genuine cold resume needs longer."
    )


class _BoundedTimeout(RuntimeError):
    """Raised by :func:`_run_bounded` when ``fn`` did not finish in time. A
    distinct type (not a bare ``RuntimeError``) so callers can tell "the
    background thread is still busy on the connection" apart from "the
    operation ran to completion and raised" - the two need different cleanup:
    a still-busy connection must not be touched synchronously (see
    ``PostgresSnapshotStore.__init__``)."""


def _run_bounded(fn, seconds: float, on_timeout_msg: str):
    """Run ``fn()`` on a daemon thread; raise ``_BoundedTimeout(on_timeout_msg)``
    if it does not finish within ``seconds`` (keeps post-connect init inside the
    same startup budget). Propagates ``fn``'s own exception, with its own type,
    if it raises before the deadline."""
    box: dict[str, Any] = {}

    def _w() -> None:
        try:
            box["v"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["e"] = exc

    th = threading.Thread(target=_w, name="pg-init", daemon=True)
    th.start()
    th.join(seconds)
    if th.is_alive():
        raise _BoundedTimeout(on_timeout_msg)
    if "e" in box:
        raise box["e"]
    return box.get("v")


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
        budget = connect_timeout_s if connect_timeout_s is not None else _startup_budget_s()

        start = time.monotonic()
        self._conn = _connect_bounded(psycopg, dsn, budget)
        # The advisory-lock probe AND the first read run inside the SAME
        # budget as the connect, so a hung post-connect query cannot blow
        # past the one startup deadline the caller was promised.

        def _deadline_msg(what: str) -> str:
            return (f"database did not respond to the {what} within the "
                    f"{int(budget)}s startup budget")

        def _remaining() -> float:
            # No fresh grace period: once connect has spent the whole startup
            # budget, the lock probe / first read get whatever is left -
            # including ~0 - never a re-granted multi-second window.
            return max(0.0, budget - (time.monotonic() - start))

        def _take_lock() -> bool:
            with self._conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s)", (self._key,))
                v = bool(cur.fetchone()[0])
            self._conn.commit()
            return v

        try:
            got = _run_bounded(_take_lock, _remaining(), _deadline_msg("writer-lock probe"))
        except _BoundedTimeout:
            self._close_after_busy_timeout()  # the probe thread may still own the
            raise                             # connection; do not touch it here
        except Exception:
            self._safe_close_after_completed_error()
            raise
        if not got:
            self._conn.close()
            raise RuntimeError(
                f"another process holds the demo writer lock for schema "
                f"'{self._schema}'. Stop the other app, or use a different "
                "HERMES_DEMO_SCHEMA."
            )

        # First read, still inside the same startup budget (fix: this used to
        # be unbounded, so a hung query here silently reintroduced the stall
        # the connect/lock bounding was meant to close).
        try:
            self._initial_read: dict[str, Any] | None = _run_bounded(
                self._do_read, _remaining(), _deadline_msg("initial read"),
            )
        except _BoundedTimeout:
            self._close_after_busy_timeout()
            raise
        except Exception:
            self._safe_close_after_completed_error()
            raise
        self._initial_read_pending = True

    # -- timeout cleanup ---------------------------------------------------
    # Two different failure shapes need two different cleanups. When a bounded
    # step (``_run_bounded``) actually completes and raises, the background
    # thread is done and ``self._conn`` is idle: rollback+close on THIS thread
    # is safe. When it times out, the background thread may still be inside
    # ``cur.execute`` on the SAME connection - psycopg serialises access to a
    # connection with its own internal lock, so calling rollback()/close() from
    # this thread would block on that lock until the stuck query returns,
    # reintroducing the exact silent stall this budget exists to prevent. So on
    # a genuine timeout we never touch the connection synchronously; a
    # best-effort close runs on its own daemon thread instead.

    def _safe_close_after_completed_error(self) -> None:
        try:
            self._conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        self._conn.close()

    def _close_after_busy_timeout(self) -> None:
        threading.Thread(target=self._best_effort_close, name="pg-close", daemon=True).start()

    def _best_effort_close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001
            pass

    def _do_read(self) -> dict[str, Any] | None:
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

    def read(self) -> dict[str, Any] | None:
        if self._initial_read_pending:
            self._initial_read_pending = False
            return self._initial_read
        return self._do_read()

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
        "apply_action_intent_uncertain", "apply_message_delivery",
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
