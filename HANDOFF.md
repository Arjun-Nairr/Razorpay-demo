# Cross-Agent Handoff — current-state index

Last updated: 2026-09-04 (Asia/Dubai), Iteration 20. Branch
`feat/isolated-hermes-agent`, latest commit at bottom. This file stays
**under 280 lines**: it is an index, not a log. Detail lives in the linked
docs; iteration-by-iteration history is in
[`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md).

## What this is

A selection-quality **AI Revenue Recovery Agent** demo (SaaS subscription
payment recovery, above Razorpay). One deep `RecoveryEngine` (`receive` / `run`
/ `inspect`); the AI *proposes* a typed strategy, deterministic policy
*authorizes* every effect, Neon stores current projections + an append-only
audit ledger. Case 3 (insufficient funds) is the proven vertical slice, now
HYBRID: real Razorpay Test Mode behind the same seam (see below).

## Context loading (see `CLAUDE.md`)

Read `HANDOFF.md` first, then only the files the current task names. Contracts:
[`IMPLEMENTATION_SPEC.md`](IMPLEMENTATION_SPEC.md) (build),
[`POLICY_SPEC.md`](POLICY_SPEC.md) (deterministic rules),
[`RAZORPAY_TEST_SLICE.md`](RAZORPAY_TEST_SLICE.md) (this slice's verified
provider facts + contract),
[`HERMES_RAZORPAY_RESEARCH.md`](HERMES_RAZORPAY_RESEARCH.md) +
[`HERMES_ISOLATED_AGENT_RESEARCH.md`](HERMES_ISOLATED_AGENT_RESEARCH.md)
(external-runtime constraints),
[`FOUNDATION_ARCHITECTURE.md`](FOUNDATION_ARCHITECTURE.md) (module contract),
[`SCENARIO_MATRIX.md`](SCENARIO_MATRIX.md) (scenarios; three deferred
exemplars now supersede the earlier five-case plan - see backlog §5).
Planning map: [`IMPLEMENTATION_BACKLOG.md`](IMPLEMENTATION_BACKLOG.md) — Codex's
index; it does **not** authorize implementation. History on demand: the archive.

## Authorization (current)

- Iteration 18: ONE live HYBRID attempt - webhook-only tunnel, real Hermes +
  Gemini decisions, at most one real Razorpay Test Mode link, Neon writes.
  **Explicitly stopped before payment** on a later Codex/user scope change:
  the demo does not require a completed checkout - see below.
- Earlier authorization (still valid, unchanged): local startup fixes and the
  ONE already-completed real Gemini-backed Hermes case against the existing
  `hermes_demo` Neon schema (`case-11` - preserved, re-verified unchanged).
- **Never** print/commit secrets, connection strings, raw secret-bearing
  errors, or `.env`. No real payments, external customer messages, Docker
  migration, DB redesign, security-setting changes, or edits to other Hermes
  installations.

## Architecture & safety decisions (retained)

- **AI proposes; deterministic policy authorizes.** Model output never sets
  money, terms, access, or provider retry eligibility.
- **Three strategist modes** (`hermes` / `live` / `offline`) and, orthogonally,
  **two payment-provider modes** (`fake` / `hybrid_test_mode` - see below):
  provider choice is picked independently of strategist choice, never a
  silent fallback either way.
- **Attribution is deterministic**: `hermes_assisted` only for a payment
  uniquely correlated to a Hermes-authorized recovery link; a provider-owned
  retry is never attributed to Hermes. A Payment Link never implies the
  original subscription auto-settled/reactivated.
- **Simulated vs real** is always labelled (`evidence_mode`:
  `SIMULATED` | `REAL_TEST_MODE`).
- **Durable ledger**: `PgLedger`/`PostgresSnapshotStore`, one JSONB snapshot
  row, single writer via `pg_advisory_lock`. Storage architecture is frozen.
- Escalation is real: a deterministic terminal `ESCALATE` transition exists as
  the safe path when evidence is inadequate.

## Isolated real Hermes runtime (`hermes` mode)

Unchanged this iteration - full detail in the archive. Summary: one `propose`
== one throwaway `run_agent.AIAgent` decision in an isolated subprocess run by
the pinned installed Hermes interpreter; three case-scoped read tools; budgets
(6 tool calls, 8 model iterations shared with repair, 90s subprocess deadline,
one in-flight decision); bounded/allowlisted audit metadata, no raw
transcripts.

## Startup & connectivity (Iterations 13–15)

Unchanged - full narrative in the archive (IPv6/TLS/encoding root causes,
bounded startup budget incl. DNS + first read, no fresh grace period after
the budget is spent).

## Razorpay Test Mode — HYBRID slice

Per [`RAZORPAY_TEST_SLICE.md`](RAZORPAY_TEST_SLICE.md). The simulated SaaS
obligation, its 3/12-month history, and the accelerated failure/retry sequence
are **unchanged**. Only authorized recovery-link creation and payment
confirmation go through genuine Razorpay Test Mode calls when the
`hybrid_test_mode` provider is selected (`RAZORPAY_PROVIDER=hybrid_test_mode`,
independent of Hermes/Gemini mode; default remains `fake`). Native
subscription-retry signals and historical-data retrieval are **not**
implemented - retry eligibility always stays simulated. Iterations 15-17
(first cut, five-defect correction, two small gap fixes) are archived.

- **`HybridPaymentProvider`** composes `FakeRazorpayAdapter` (retry eligibility
  only) with the real adapter (link creation + capture confirmation).
- **`POST /webhooks/razorpay-test`** (mounted only when `real_webhook_secret`
  is configured) verifies a genuine `payment_link.paid` envelope against a
  **separate** secret via separate code - signature first, then envelope/
  contradiction checks, then this case's persisted link correlation, then one
  independent provider readback, then `engine.receive`. The simulated
  `/webhooks/razorpay` route is untouched.
- **User-only setup**: DONE - Test Mode key pair, webhook (`payment_link.paid`
  only), `.env` flags. Manual Test Mode checkout was **deliberately not
  completed** (see Iteration 18 below).

## Iteration 18 — one live attempt, stopped before payment (case-18)

`scripts/webhook_relay.py` (new) is a loopback-only reverse proxy serving
**only** `POST /webhooks/razorpay-test` - every other path/method rejected
before touching the main app; no engine/DB/credentials of its own, so even an
unrestricted tunnel pointed at it can never expose `/demo/*`/`/cases/*`/docs.
An SSH reverse tunnel (`ssh -p 443 -R0:127.0.0.1:8100 free.pinggy.io`, no new
binary/no pip) exposed it publicly; verified end-to-end that unrelated paths
404, the wrong method 405s, an unsigned `POST` gets a genuine `401`. One
tunnel domain (`lhr.life`/`localhost.run`) was connection-reset by local Avast
Web Shield (confirmed: unrelated HTTPS sites worked, that domain didn't) - not
touched/excluded, just switched to a working provider (`pinggy.io`).

`scripts/run_one_hybrid_case.py` (new) drove ONE case through real Hermes +
Gemini decisions only (never simulated capture). Result: **case-18**
(obligation `sub_demo_0004_8e781337`) - decision 1: `WAIT_FOR_PROVIDER_RETRY`
authorized; after the simulated failed-retry input, decision 2:
`CREATE_RECOVERY_LINK` authorized -> ONE real Payment Link created (reference
`plink_TY2urjqVCjkjvB`; checkout URL persisted in Neon, not reproduced here).

**Scope change mid-task: do not complete the checkout.** The demo doesn't
require a paid live checkout; recording uses this saved evidence instead.
Case-18 left exactly as-is - no simulated capture, no forged webhook, no state
edit. All three processes were stopped by exact PID/port match; verified ports
8000/8100 free, the tunnel URL no longer resolves, Neon re-read shows case-18
unchanged.

## Iteration 19 — review findings closed + read-only Neon views

**Phase A** (offline only): `/health` now reports non-secret
`payment_provider` / `payment_provider_test_mode_enabled` flags;
`run_one_hybrid_case.py` fails closed (refuses `POST /demo/case`) unless both
are the expected real values - `evidence_mode=SIMULATED` on the case's own
synthetic intake is preserved, never relabelled. `webhook_relay.py` hardened:
a documented 64 KiB body ceiling, `Content-Length` validated (missing/
malformed/negative/oversized all rejected, 411/400/400/413, before any read),
a bounded body-read deadline (408 on a stall), and logging reduced to method +
a fixed route category + status only - never the raw path/query/headers/body.

**Phase B**: five read-only views added to `scripts/init_neon.py`
(`CREATE OR REPLACE VIEW` only; same single `ledger_state` JSONB row, nothing
duplicated or made mutable): `case_summary` (authoritative `state` plus a
derived, presentation-only `display_status`), `hermes_decisions` (one row per
`AI_PROPOSAL`, joined to its own cycle's nearest `AI_MODEL_RUN`/
`POLICY_DECISION` - never a global first/last), `recovery_actions`
(`checkout_url_present` boolean, never the URL; `message_authorized` kept
separate from `message_sent`), `hermes_evidence`, `audit_timeline`. Also fixed
a real bug found running this: `init_neon.py`'s bare `psycopg.connect(dsn)`
had no timeout and no IPv4 preference, so it hung indefinitely on this host's
known IPv6 black hole - now reuses the app's own `_connect_bounded`.

Ran `init_neon.py` once against the existing `.env` (DDL only, `hermes_demo`
schema) and read all five views back directly: **case-18** - `state=active`
(authoritative, unchanged), `display_status=RECOVERY_IN_PROGRESS`,
`recovery_actions` shows the real link with `checkout_url_present=true`,
`action_evidence_mode=REAL_TEST_MODE`, `message_authorized=true` /
`message_sent=false` (kept separate); `hermes_decisions` shows both real
decisions correctly paired (`WAIT_FOR_PROVIDER_RETRY` then
`CREATE_RECOVERY_LINK`, ~19.2s/~19.4s execution, confidence 0.95/`high`).
**case-11** unchanged: `state=recovered`, `display_status=RECOVERED`,
`attribution=hermes_assisted`, `counted=true`.

## Iteration 20 — relay corrections (offline only, no live activity)

Three defects closed in `scripts/webhook_relay.py`, none of them touching a
live API/Gemini/Razorpay/Neon call or the relay/tunnel (neither was started):

1. **Absolute deadline, not inactivity-only.** The old `_read_body` set one
   socket timeout, then called `self.rfile.read(length)` - which loops
   internally over MULTIPLE `recv()` calls, each getting its OWN fresh
   timeout, so a sender drip-feeding bytes just inside each gap could extend
   the read forever. Now an incremental loop recalculates `remaining =
   deadline - now()` before every read and uses `rfile.read1(want)` (at most
   ONE underlying `recv()` per call, so the recalculated timeout genuinely
   bounds just that step) - a continuously-active drip-feeder is still cut
   off (408) once the absolute deadline passes, never forwarded partial.
2. **Premature EOF.** A connection closing before exactly `Content-Length`
   bytes arrive is now a distinct, fixed `400` rejection (was previously
   indistinguishable from a timeout) - never forwarded upstream.
3. **Normalized log method.** `log_request` printed `self.command` - the
   client's raw, unvalidated method token - directly. Now mapped through a
   fixed allowlist (`GET`/`HEAD`/`POST`/`PUT`/`DELETE`/`PATCH`/`OPTIONS`);
   anything else, however crafted, logs as the fixed label `"OTHER"`.

+4 tests in `tests/test_webhook_relay.py`: a continuously drip-feeding sender
(never quiet long enough for a naive per-call timer to fire) is still
rejected well inside the budget; a real premature EOF via `shutdown(SHUT_WR)`
rejects 400 and never reaches the upstream stub; an attacker-controlled
method string never appears in captured log output, only `"OTHER"`.

`IMPLEMENTATION_BACKLOG.md` corrected: removed the stale "still uses
FakeRazorpayAdapter" / "live pending" language (case-18 already proved the
hybrid path live in Iteration 18) and trimmed one repeated historical-dataset
sentence.

## Verified evidence

- **Offline**: `python -m pytest -q --ignore=tests/test_hermes_agent.py` ->
  **296 passed, 3 skipped** (was 284; `tests/test_razorpay_test_mode.py` grew
  from 46 to 58 tests). Real-Hermes harness
  `python -m pytest -q tests/test_hermes_agent.py` -> **33 passed**
  (unaffected - this iteration touched only `razorpay_test_mode.py` and its
  tests). `compileall` + `git diff --check` clean; diff confined to those two
  files.
- **Iteration 18**: `python -m pytest -q --ignore=tests/test_hermes_agent.py`
  -> **308 passed, 3 skipped** (was 296; +12 `tests/test_webhook_relay.py`).
  This iteration DID make live calls: real Hermes/Gemini decisions, one real
  Razorpay Test Mode link, real Neon writes for `case-18`.
- **Iteration 19**: `python -m pytest -q --ignore=tests/test_hermes_agent.py`
  -> **369 passed, 3 skipped** (+16 `test_run_one_hybrid_case.py`, +3
  `test_api.py` `/health` fields, +9 `test_webhook_relay.py` hardening,
  +33 `test_neon_views.py`). Live: `scripts/init_neon.py` ran once (DDL only)
  and the five views were read back directly - see Iteration 19 section above.
- **Iteration 20**: `python -m pytest -q --ignore=tests/test_hermes_agent.py`
  -> **373 passed, 3 skipped** (+4 `test_webhook_relay.py`). `compileall` +
  `git diff --check` clean; secret scan clean. No API/relay/tunnel started, no
  live Gemini/Razorpay/Neon call - offline only, as authorized.

## Inspecting the persisted proof

- Neon SQL editor, schema `hermes_demo`: query the five views directly (e.g.
  `SELECT * FROM hermes_demo.case_summary`) - see
  [`sql/neon_demo_inspect.sql`](sql/neon_demo_inspect.sql) for ready-made
  all-cases and one-case queries (swap in `'case-18'`). User-run flow:
  [`scripts/neon_proof.py`](scripts/neon_proof.py).

## Repeatable launch

```
.\scripts\run_demo.ps1 -Mode hermes
```

Payment provider defaults to `fake` (unchanged). Hybrid Test Mode setup
(credentials, webhook, `.env` flags) was **completed** for the Iteration 18
run against `case-18` - see that section above. The API, relay, and tunnel
from that run are **stopped**; no further live run is currently authorized.
`/health` now reports `payment_provider` / `payment_provider_test_mode_enabled`
so `scripts/run_one_hybrid_case.py` fails closed if a future run isn't
actually wired to `hermes-runtime` + `hybrid_test_mode` + enabled.

## Blockers

- None technical. `case-18` intentionally sits `active`/awaiting payment by
  explicit Codex/user decision - the recorded demo will use this saved
  evidence rather than depend on a live checkout. Completing that checkout
  later, if ever wanted, needs a fresh tunnel (the pinggy.io one from this
  iteration was stopped and its URL no longer resolves) but NOT a new case.
- `hermes` mode remains manual-control only (see backlog).

## Next action

Codex/user will author the Hermes SOUL and judgment drafts against the
existing Neon evidence contract (the five views + `ledger_state`) - not
Claude Code in this task. No further live action planned against `case-18`.
The three deferred exemplars (on-time / late / mixed-history) remain deferred
per the backlog. Keep future `HANDOFF.md` updates under 280 lines.

## Working-document links

- History: [`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md)
- Plan map: [`IMPLEMENTATION_BACKLOG.md`](IMPLEMENTATION_BACKLOG.md)
- Build contract: [`IMPLEMENTATION_SPEC.md`](IMPLEMENTATION_SPEC.md)
- Policy: [`POLICY_SPEC.md`](POLICY_SPEC.md)
- Razorpay Test Mode contract: [`RAZORPAY_TEST_SLICE.md`](RAZORPAY_TEST_SLICE.md)
- Neon queries: [`sql/neon_demo_inspect.sql`](sql/neon_demo_inspect.sql)
- Isolated-Hermes research: [`HERMES_ISOLATED_AGENT_RESEARCH.md`](HERMES_ISOLATED_AGENT_RESEARCH.md)

<!-- latest verified commit: see `git log -1` on feat/isolated-hermes-agent -->
