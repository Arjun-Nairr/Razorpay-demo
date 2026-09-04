"""Idempotent, non-destructive initialisation of the demo ledger schema.

    python -m pip install ".[db]"
    # DATABASE_URL must be set (in the gitignored root .env or the environment)
    python scripts/init_neon.py

Creates only:
    CREATE SCHEMA IF NOT EXISTS hermes_demo
    CREATE TABLE  IF NOT EXISTS hermes_demo.ledger_state (id, data JSONB, updated_at)
    INSERT the single id=1 row with an empty ledger snapshot, ON CONFLICT DO NOTHING

It never issues DROP / TRUNCATE / DELETE and never touches anything outside the
`hermes_demo` schema. Safe to run repeatedly. The connection string is read from
the environment and is never printed.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hermes.adapters import InMemoryLedger  # noqa: E402
from hermes.pg_ledger import _DEFAULT_SCHEMA, _validate_schema, dump_ledger  # noqa: E402

SCHEMA = _validate_schema(os.environ.get("HERMES_DEMO_SCHEMA", _DEFAULT_SCHEMA))


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    load_dotenv(os.path.join(root, ".env"), override=False)


def main() -> int:
    _load_dotenv()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn or not dsn.strip():
        print("DATABASE_URL is not set. Put the Neon Postgres URL in .env, then re-run.",
              file=sys.stderr)
        return 2
    try:
        import psycopg
    except ImportError:
        print('psycopg is not installed. Run:  python -m pip install ".[db]"', file=sys.stderr)
        return 3

    empty_snapshot = json.dumps(dump_ledger(InMemoryLedger()))
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
            cur.execute(
                f"CREATE TABLE IF NOT EXISTS {SCHEMA}.ledger_state ("
                "  id integer PRIMARY KEY,"
                "  data jsonb NOT NULL,"
                "  updated_at timestamptz NOT NULL DEFAULT now()"
                ")"
            )
            cur.execute(
                f"INSERT INTO {SCHEMA}.ledger_state (id, data) VALUES (1, %s::jsonb) "
                "ON CONFLICT (id) DO NOTHING",
                (empty_snapshot,),
            )
        conn.commit()

    print(f"OK: schema '{SCHEMA}' ready; ledger_state row present. No data was dropped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
