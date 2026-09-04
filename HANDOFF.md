# Cross-Agent Handoff — current-state index

Last updated: 2026-09-04 (Asia/Dubai), Iteration 21. Branch
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

## Iterations 18-20 — live case-18, Neon views, relay hardening

Condensed; full detail archived. Iteration 18: one live HYBRID attempt via a
loopback-only relay + SSH tunnel - real Hermes/Gemini decisions, one real
Razorpay Test Mode link (**case-18**), **stopped before payment** on a
Codex/user scope change (demo doesn't need a completed checkout). Iteration
19: `/health` reports provider-mode flags, `run_one_hybrid_case.py` fails
closed unless real; five read-only Neon views added to `init_neon.py`
(`case_summary`, `hermes_decisions`, `recovery_actions`, `hermes_evidence`,
`audit_timeline`); views read back and confirmed correct for case-18/case-11.
Iteration 20: three `webhook_relay.py` hardening defects closed (absolute
read deadline vs. drip-feed, premature-EOF rejection, log-method allowlist),
offline only. See
[`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md)
for full narrative.

## Iteration 21 — Hermes SOUL wiring + offline verification

Codex authored `config/hermes_agent/SOUL.md` (agent identity/scope/limits)
and the first exemplar rule in `config/hermes_agent/SKILL.md` (consistent
recent payment behavior); both preserved verbatim, unchanged by this
iteration. Wired both into the isolated child's ephemeral system prompt.

- **Parent** (`hermes_agent_strategist.py`): added `_SOUL_PATH` beside
  `_SKILL_PATH` and a `soul_path` constructor parameter; `__init__` now
  fails closed (`HermesRuntimeUnavailable`) if either file is missing or
  unreadable. Both are read as UTF-8 and sent to the child as two distinct
  `job` keys (`soul_text`, `skill_text` - never concatenated on the parent
  side). `PROMPT_VERSION` bumped (`...2026-09-05.2`) since the child's
  prompt contract changed.
- **Child** (`hermes_agent/child_main.py`): `_system_prompt()` now takes
  `soul_text` first and prepends it, so the ephemeral prompt order is SOUL
  identity/scope -> SKILL judgment rules -> case context -> tool
  descriptions/approved messages/output contract. No other child behavior
  (tool budgets, repair limit, schema validation, audit allowlist) touched.
- Everything else (isolation, subprocess deadline, tool budgets, one
  in-flight decision, policy authority, audit sanitization, Neon, Razorpay,
  FastAPI, fixtures, dashboard) is unchanged - this iteration only added the
  SOUL file path/param/prompt-ordering wiring above.

New offline tests in `tests/test_hermes_agent.py`: missing SOUL and missing
SKILL each fail closed independently; a faked `subprocess.run` captures the
literal `job` JSON and proves `soul_text`/`skill_text` are the real files'
exact contents as two distinct fields; `child_main._system_prompt()` is
called directly with marker strings to prove SOUL precedes SKILL precedes
case context. The existing `@requires_runtime` real-Hermes/offline-stub tests
(local OpenAI-compat stub, no live Gemini) still return a schema-valid
proposal after the wiring change - this proves wiring and contract behavior
only, not the quality of Hermes's judgment against the new SOUL/SKILL text.

**Iteration 21 corrections** (4 review findings closed, same iteration):

1. Invalid-UTF-8 SOUL/SKILL content now fails closed too, not just missing/
   unreadable: a shared `_read_utf8()` helper catches `(OSError, UnicodeError)`
   in both `__init__` and `_propose_locked` and raises `HermesRuntimeUnavailable`
   with a fixed, sanitized message (label + exception type only - never the
   path or file content). New regression tests for SOUL and SKILL separately.
2. `_propose_locked` now creates `HermesRunMeta` and assigns `last_run_meta`
   **before** re-reading the instruction files; a load failure marks that
   fresh metadata with `failure_category=instruction_load_failed` /
   `failure_stage=instruction_load` and raises - a prior successful run's
   confidence/tool/result metadata can no longer leak onto a later failure.
   New regression: a successful decision, then a removed SOUL file, then
   `last_run_meta` on the second (failing) call carries only the new failure.
3. A direct test now builds the final `_system_prompt()` from the REAL
   `SOUL.md`/`SKILL.md` file contents (not marker strings) and asserts both
   exact texts appear, in order SOUL -> SKILL -> case context -> tool/output
   contract.
4. This section.

No isolation, deadline, tool-budget, repair-limit, audit-allowlist, policy,
dependency, provider, fixture, or dashboard change. No live service called.

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
- **Iteration 21** (SOUL wiring + corrections), using the project
  `.venv\Scripts\python.exe` (3.12.5): focused
  `python -m pytest -q tests/test_hermes_agent.py` -> **41 passed** (was 33
  pre-wiring, 37 after wiring, +4 correction regressions: invalid-UTF-8 SOUL,
  invalid-UTF-8 SKILL, stale-metadata-not-leaked, real-file prompt-order
  proof). Full offline `python -m pytest -q --ignore=tests/test_hermes_agent.py`
  -> **373 passed, 3 skipped** (unchanged - this iteration touched only
  `hermes_agent_strategist.py`/`child_main.py`/`test_hermes_agent.py`/
  `HANDOFF.md`). `compileall` + `git diff --check` clean; diff inspected,
  confined to those files plus this section; no secrets. Offline-stub tests
  prove wiring/contract behavior only, never Hermes's judgment quality.

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

Run one real consistent-history Hermes/Gemini exemplar (the SOUL + Rule 1
judgment now wired in), persist it to Neon, and read it back through the five
presentation views (`case_summary`, `hermes_decisions`, `recovery_actions`,
`hermes_evidence`, `audit_timeline`). No further live action planned against
`case-18`. The two remaining deferred exemplars (inconsistent / mixed-history
rules + cases) stay deferred per the backlog. Keep future `HANDOFF.md`
updates under 280 lines.

## Working-document links

- History: [`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md)
- Plan map: [`IMPLEMENTATION_BACKLOG.md`](IMPLEMENTATION_BACKLOG.md)
- Build contract: [`IMPLEMENTATION_SPEC.md`](IMPLEMENTATION_SPEC.md)
- Policy: [`POLICY_SPEC.md`](POLICY_SPEC.md)
- Razorpay Test Mode contract: [`RAZORPAY_TEST_SLICE.md`](RAZORPAY_TEST_SLICE.md)
- Neon queries: [`sql/neon_demo_inspect.sql`](sql/neon_demo_inspect.sql)
- Isolated-Hermes research: [`HERMES_ISOLATED_AGENT_RESEARCH.md`](HERMES_ISOLATED_AGENT_RESEARCH.md)

<!-- latest verified commit: see `git log -1` on feat/isolated-hermes-agent -->
