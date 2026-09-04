# Cross-Agent Handoff — current-state index

Last updated: 2026-09-04 (Asia/Dubai), Iteration 14. Branch `feat/isolated-hermes-agent`,
latest commit at bottom. This file stays **under 300 lines**: it is an index,
not a log. Detail lives in the linked docs; iteration-by-iteration history is in
[`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md).

## What this is

A selection-quality **AI Revenue Recovery Agent** demo (SaaS subscription
payment recovery, above Razorpay). One deep `RecoveryEngine` (`receive` / `run`
/ `inspect`); the AI *proposes* a typed strategy, deterministic policy
*authorizes* every effect, Neon stores current projections + an append-only
audit ledger. Build target: five golden cases; Case 3 (insufficient funds) is
the proven vertical slice.

## Context loading (see `CLAUDE.md`)

Read `HANDOFF.md` first, then only the files the current task names. Contracts:
[`IMPLEMENTATION_SPEC.md`](IMPLEMENTATION_SPEC.md) (build),
[`POLICY_SPEC.md`](POLICY_SPEC.md) (deterministic rules),
[`HERMES_RAZORPAY_RESEARCH.md`](HERMES_RAZORPAY_RESEARCH.md) +
[`HERMES_ISOLATED_AGENT_RESEARCH.md`](HERMES_ISOLATED_AGENT_RESEARCH.md)
(external-runtime constraints),
[`FOUNDATION_ARCHITECTURE.md`](FOUNDATION_ARCHITECTURE.md) (module contract),
[`SCENARIO_MATRIX.md`](SCENARIO_MATRIX.md) (the five cases).
Planning map: [`IMPLEMENTATION_BACKLOG.md`](IMPLEMENTATION_BACKLOG.md) — Codex's
index; it does **not** authorize implementation. History on demand: the archive.

## Authorization (current)

- Local startup debugging/fixes and **ONE** real Gemini-backed Hermes demo case
  writing to the **existing** `hermes_demo` Neon schema (do not recreate/reset
  storage). Existing private `.env` credentials, used privately.
- **Never** print/commit secrets, connection strings, raw secret-bearing errors,
  or `.env`. No Razorpay API calls, real payments, external messages, Docker
  migration, DB redesign, security-setting changes, or edits to other Hermes
  installations.

## Architecture & safety decisions (retained)

- **AI proposes; deterministic policy authorizes.** The `Strategist` seam is
  fixed; the engine's `_validate_proposal` + `authorize` are the final
  authority. Model output never sets money, terms, access, or provider retry
  eligibility.
- **Two strategist modes**, never a silent fallback between them:
  `hermes` = the actual isolated Nous Hermes runtime (see below);
  `live` = direct google-genai (kept for comparison/tests);
  `offline` = `ScriptedStrategist`.
- **Attribution is deterministic**: `hermes_assisted` only for a payment
  uniquely correlated to a Hermes-authorized recovery link; a provider-owned
  retry is never attributed to Hermes. A Payment Link never implies the
  original subscription auto-settled/reactivated.
- **Simulated vs real** is always labelled (`evidence_mode`); this build makes
  no real Razorpay call and sends no real message.
- **Durable ledger**: `PgLedger` wraps the tested `InMemoryLedger` and writes
  one whole-state JSON snapshot per mutation via `PostgresSnapshotStore`
  (`hermes_demo.ledger_state`, one row). Persisted logical clock; single writer
  via a session-scoped `pg_advisory_lock`. Storage architecture is frozen (no
  redesign, no migration).
- **Accelerated logical clock** applies only to Hermes waits / cooldowns /
  simulated outcomes — never to Razorpay's real retry calendar.
- Escalation is real: a deterministic terminal `ESCALATE` transition
  (`escalated` / `unrecovered`) exists as the safe path when evidence is
  inadequate — never a blocked no-op dressed up as escalation.

## Isolated real Hermes runtime (`hermes` mode)

- One `propose` == one throwaway `run_agent.AIAgent` decision in a **subprocess
  run by the installed Hermes interpreter**
  (`C:\Users\dwish\AppData\Local\hermes\hermes-agent`, pinned revision
  `e02d1e41fc6104187e20af9eac8b2820566e3508`; the parent refuses to launch on a
  mismatch — no auto-upgrade, no edits to that install).
- Isolation (state, not an OS sandbox): project-local gitignored `HERMES_HOME`;
  `skip_context_files` / `skip_memory` / `skip_background_review`; tool-search
  bridge off; positive one-toolset allowlist; no terminal/browser/file/
  delegation/cron/code-exec tools; MCP + plugins + skill discovery inert.
- Exactly **three case-scoped read tools** over a bounded immutable evidence
  bundle: `get_payment_retry_facts()`, `get_recovery_actions()` (this case's
  real prior actions/decisions/outcomes from the audit projection + a
  separately-labelled catalog of only policy-executable actions),
  `get_payment_history(reason)` (ONE optional expansion straight to 12 months,
  >=8-char reason, at most once incl. during repair, reports *actual* coverage,
  synthetic only for a trusted `DEMO_CASE_PROVENANCE` case).
- **Budgets** (preserved): 6 tool executions, 8 model iterations **shared**
  across the initial reasoning + the single schema repair, one 90 s subprocess
  deadline (timed-out child reaped; a late connection from a timed-out attempt
  is closed, not leaked), one in-flight decision.
- Strategist-facing action set: `WAIT_FOR_PROVIDER_RETRY`,
  `CREATE_RECOVERY_LINK` (+ optional approved `message_intent` template),
  `ESCALATE`. `SEND_REMINDER` and `STOP` are **not** advertised — policy only
  BLOCKs them; reminder copy attaches to a link, not standalone.
- Audit is bounded + allowlisted (`AI_MODEL_RUN.detail.hermes`): runtime
  revision, provider/model, timing, shared budgets used, evidence
  requests+reasons, returned source/coverage, uncalibrated confidence band +
  basis, decision action, failure category/stage, child exit code. No raw
  messages, stderr slices, or transcripts. `confidence` never grants a
  permission and is never required to rise after more evidence.

## Startup & connectivity (Iteration 13, refined in 14)

The `run_demo.ps1 -Mode hermes` "silent stall" had **two local causes**, fixed
in Iteration 13; the earlier "Neon outage" claim is **superseded/unproven**.
Iteration 14 closed three edge cases the review found in that fix (see
[the archive](docs/archive/HANDOFF_full_2026-09-04.md) for full narrative).

1. **IPv6 black hole.** `getaddrinfo` returned AAAA first; each dead IPv6 SYN
   cost ~21 s before libpq fell to IPv4 (~0.1 s). Fix: `pg_ledger` resolves an
   IPv4 and passes it as libpq `hostaddr` (TLS still verifies the cert against
   `host`; `sslmode`/`channel_binding` from the DSN untouched). Real Neon now
   connects in ~3 s. **Iteration 14:** the resolution itself is now bounded
   (a hung resolver used to block before the deadline clock even started; it
   now shares the same startup budget and falls back to unresolved on stall).
2. **TLS interception.** Avast "Web/Mail Shield" re-signs
   `generativelanguage.googleapis.com` with a local root absent from the child
   venv's `certifi`, so the Gemini call failed verification. Fix: the parent
   writes a CA bundle (`certifi` + the OS trust store) into the gitignored
   isolated home and hands it to the child via `SSL_CERT_FILE` /
   `REQUESTS_CA_BUNDLE` / `CURL_CA_BUNDLE` / `GRPC_DEFAULT_SSL_ROOTS_FILE_PATH`.
   **Iteration 14:** the bundle now imports only OS-store certs that carry
   `x509_asn` encoding AND are trusted for TLS server-auth (`1.3.6.1.5.5.7.3.1`)
   — the first cut imported every OS root regardless of purpose/encoding. The
   on-disk cache is versioned (`_CA_BUNDLE_VERSION`) so any previously-written
   broad bundle is discarded and rebuilt immediately, not reused for the rest
   of its 24h window. Still does **not** weaken verification — full chain
   verification, just scoped to what the OS actually trusts for this purpose.
   Override with `HERMES_CA_BUNDLE`.
3. **Encoding.** The parent decodes the child's streams as UTF-8
   (`errors="replace"`); Windows cp1252 was dropping the result line
   (spurious `no_result_line`).
4. **One bounded startup budget**, now covering DNS too. `HERMES_DB_CONNECT_TIMEOUT_S`
   (default 30 s) bounds DNS pre-resolution + connect + the advisory-lock probe
   **+ the first snapshot read** together (the first read used to run after all
   bounding was over — unbounded); `run_demo.ps1` waits that budget + 30 s fixed
   margin, so the launcher ceiling is always the looser one. The launcher uses
   `.venv\Scripts\python.exe` explicitly for uvicorn **and** Streamlit.
5. **Timeout cleanup no longer risks blocking on a busy connection.** After a
   writer-lock-probe (or first-read) timeout, the probe's own thread may still
   be mid-query on that connection; psycopg serialises access to a connection
   with its own lock, so a synchronous `rollback()`/`close()` from the main
   thread would wait for that stuck query — reintroducing the same stall. A
   genuine timeout (`_BoundedTimeout`) now only schedules a best-effort close
   on its own daemon thread; a real completed error (thread already finished)
   still gets a synchronous rollback+close as before.
6. **Late-connection race closed.** `_connect_once`'s worker and the timed-out
   caller now decide the connection's fate under one lock (`state["claimed"]`)
   instead of an independent `Event` check on one side and `is_alive()` on the
   other — the connection is always either returned to the caller or closed by
   the worker, never dropped unclosed.
7. Startup failures still exit fast with one sanitised stderr line + nonzero
   code (never the DSN); only positively-identified project processes were ever
   stopped.

## Verified evidence

- **Offline:** `python -m pytest -q --ignore=tests/test_hermes_agent.py` ->
  **237 passed, 3 skipped**. Real-Hermes harness
  `python -m pytest -q tests/test_hermes_agent.py` -> **33 passed (~5 min)** (real
  `AIAgent` + tool loop against a stubbed OpenAI-compat transport; parent-shape/
  bundle/CA-trust tests need no runtime). `compileall` + `git diff --check`
  clean. Iteration 14 added `+4` `test_pg_ledger.py` regressions (bounded DNS,
  bounded first read, timeout cleanup does not touch a busy connection,
  late-connection race at the exact boundary — 50-trial deterministic
  interleaving) and `+4` `test_hermes_agent.py` regressions (CA bundle:
  server-auth-trusted cert included, restricted-purpose cert excluded,
  unsupported encoding skipped, previously-generated broad bundle rebuilt).
- **LIVE, end-to-end (actual Hermes -> Gemini -> deterministic policy ->
  simulated payments -> Neon), Iteration 13, re-verified read-only in 14:**
  case **`case-11`** / obligation `sub_demo_0003_9bc1578f`. Two real
  `gemini-3.7-flash` decisions (`validation_result=valid`, 2 evidence tool
  calls each, ~16 s each): `WAIT_FOR_PROVIDER_RETRY` -> policy `ALLOW`
  (`provider_retry_permitted`); then after a simulated failed retry,
  `CREATE_RECOVERY_LINK` -> policy `ALLOW`
  (`recovery_link_authorized_message_authorized`) -> action intent + outcome.
  Simulated capture on the uniquely-correlated link -> `TERMINAL_TRANSITION`.
  Iteration 14 re-read this SAME case, read-only, direct `psycopg`, one bounded
  query, no writes, no advisory lock taken: `state=recovered`,
  `attribution=hermes_assisted`, `counted=true`, both `AI_MODEL_RUN` records
  `validation_result=valid`, both `POLICY_DECISION` records `outcome=ALLOW`,
  `linked_payment_id=rlnk_case-11:CREATE_RECOVERY_LINK`. Case's own
  contribution `recovered_minor=1,000,000` (== its `amount_minor`, this is a
  per-case field) vs the ledger-wide aggregate `recovered_minor=1,000,000`
  across `cases=3`/`recovered_cases=1` — same number here only because exactly
  one case has recovered so far; they are different fields. **This read-only
  re-check is not a new live Gemini/Hermes proof** — no new case was run this
  iteration, per scope (local fixes only).
- Two earlier cases from Iteration 13 (`case-1`, `case-6`) are honest failures
  from the two defects fixed there (UTF-8 decode; Avast TLS) and were left
  `escalated` / `unrecovered` — **not drained or retried**; only `case-11` ever
  reached `recovered`.

## Inspecting the persisted proof

- Neon SQL editor, schema `hermes_demo`:
  [`sql/neon_demo_inspect.sql`](sql/neon_demo_inspect.sql) — block 1 (all
  cases), block 2 (audit timeline for a case id), block 3 (Hermes tool evidence
  / proposal / policy result), block 5 (one-line summary). Replace
  `REPLACE_WITH_CASE_ID` with e.g. `case-11`. All read-only; safe while the app
  holds the writer lock.
- User-run flow: [`scripts/neon_proof.py`](scripts/neon_proof.py) (stdlib only,
  existing endpoints only; `--yes` non-interactive, `--no-hermes` to skip the
  model step). Isolated one-shot: [`scripts/hermes_agent_smoke.py`](scripts/hermes_agent_smoke.py).

## Repeatable launch

```
.\scripts\run_demo.ps1 -Mode hermes
```

(or, without Streamlit: `.\.venv\Scripts\python.exe -m uvicorn hermes.asgi:app
--host 127.0.0.1 --port 8000`). `/health` reports `mode=hermes-runtime`. Then
`python scripts\neon_proof.py`. Raise `HERMES_DB_CONNECT_TIMEOUT_S` only if a
genuine cold resume ever needs > 30 s.

## Blockers

- None blocking. Note: the demo host has Avast HTTPS scanning; the CA-bundle
  shim handles it. If Avast is later disabled the shim is harmless (the OS
  store still contains public roots).
- `hermes` mode is manual-control only. Automatic queue wake-ups, periodic
  sweeps, and broader batch evaluation remain deferred (see the backlog).

## Next action

Codex verification of the Iteration 14 corrections (bounded DNS/first-read,
non-blocking timeout cleanup, closed late-connection race, restricted-purpose
CA trust), then the Razorpay Test Mode integration into the existing working
`case-11` slice (see `IMPLEMENTATION_BACKLOG.md` §2) — not yet started. The
three deferred exemplars (on-time / late / mixed-history) come after that;
they supersede the earlier five-case plan. Keep future `HANDOFF.md` updates
under 300 lines — archive completed detail into `docs/archive/`.

## Working-document links

- History: [`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md)
- Plan map: [`IMPLEMENTATION_BACKLOG.md`](IMPLEMENTATION_BACKLOG.md)
- Build contract: [`IMPLEMENTATION_SPEC.md`](IMPLEMENTATION_SPEC.md)
- Policy: [`POLICY_SPEC.md`](POLICY_SPEC.md)
- Neon queries: [`sql/neon_demo_inspect.sql`](sql/neon_demo_inspect.sql)
- Isolated-Hermes research: [`HERMES_ISOLATED_AGENT_RESEARCH.md`](HERMES_ISOLATED_AGENT_RESEARCH.md)

<!-- latest verified commit: see `git log -1` on feat/isolated-hermes-agent -->
