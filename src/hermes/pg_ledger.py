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
import json
import re
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


class PostgresSnapshotStore:
    """The real durable store: one JSONB row in ``<schema>.ledger_state``.
    Requires ``psycopg`` (the optional ``[db]`` extra) - imported lazily."""

    def __init__(self, dsn: str, schema: str = _DEFAULT_SCHEMA) -> None:
        import psycopg  # noqa: PLC0415 - optional dependency, lazy

        self._schema = _validate_schema(schema)
        self._conn = psycopg.connect(dsn)  # sslmode etc. carried in the DSN

    def read(self) -> dict[str, Any] | None:
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT data FROM {self._schema}.ledger_state WHERE id = 1")
            row = cur.fetchone()
        self._conn.commit()
        if row is None:
            raise RuntimeError(
                f"{self._schema}.ledger_state is not initialised - run "
                "`python scripts/init_neon.py` against DATABASE_URL first"
            )
        return row[0] or None

    def write(self, data: dict[str, Any]) -> None:
        payload = json.dumps(data)
        with self._conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self._schema}.ledger_state "
                f"SET data = %s::jsonb, updated_at = now() WHERE id = 1",
                (payload,),
            )
            if cur.rowcount != 1:  # pragma: no cover - init guarantees the row
                raise RuntimeError("ledger_state row missing; run init first")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


# --- the durable ledger -----------------------------------------------


class PgLedger:
    """A :class:`~hermes.protocols.Ledger` that persists after every write.

    Reads delegate straight to the in-memory state; mutations run in memory and
    are then written through the store in one committed transaction. A write
    failure rolls the in-memory state back to the last committed snapshot.
    """

    _READS = frozenset({
        "logical_clock", "has_seen_event", "case_id_for_obligation",
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

    def close(self) -> None:
        self._store.close()

    # -- delegation --------------------------------------------------

    def _delegate(self, name: str) -> Callable[..., Any]:
        method = getattr(self._mem, name)
        if name in self._READS:
            return method
        if name in self._WRITES:
            def _committed(*args: Any, **kwargs: Any) -> Any:
                try:
                    result = method(*args, **kwargs)
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
