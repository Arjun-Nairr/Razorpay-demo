# Cross-Agent Handoff — current-state index

Last updated: 2026-09-05 (Asia/Dubai), Iteration 29. Branch
`feat/isolated-hermes-agent`, latest commit at bottom. **At or below 230
lines** - an index, not a log. Iteration-by-iteration history is in
[`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md).

## What this is

**An agentic recovery orchestrator for SaaS subscription payments declined
for insufficient funds** - not a general payment-failure engine (locked in
Iteration 25; see below). One deep `RecoveryEngine` (`receive` / `run` /
`inspect`); the AI *proposes* a typed strategy, deterministic policy
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
[`HERMES_ISOLATED_AGENT_RESEARCH.md`](HERMES_ISOLATED_AGENT_RESEARCH.md) (external-runtime constraints),
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
transcripts. Startup/connectivity fixes (Iterations 13-15: IPv6/TLS/encoding
root causes, bounded startup budget) are archived, also unchanged.

## Razorpay Test Mode — HYBRID slice

Per [`RAZORPAY_TEST_SLICE.md`](RAZORPAY_TEST_SLICE.md). The simulated SaaS
obligation, its 3/12-month history, and the accelerated failure/retry sequence
are **unchanged**. Only authorized recovery-link creation and payment
confirmation go through genuine Razorpay Test Mode calls when the
`hybrid_test_mode` provider is selected (`RAZORPAY_PROVIDER=hybrid_test_mode`,
independent of Hermes/Gemini mode; default remains `fake`). Native
subscription-retry signals and historical-data retrieval are **not**
implemented - retry eligibility always stays simulated. Mechanics
(`HybridPaymentProvider` composition, the separately-secured
`POST /webhooks/razorpay-test` route) and Iterations 15-17 (first cut,
five-defect correction, two small gap fixes) are archived. User-only setup
(Test Mode key pair, webhook, `.env` flags) is DONE; manual Test Mode
checkout was deliberately not completed (see Iteration 18 below).

## Iterations 18-25 — case-18, Neon views, SOUL wiring, advisory + Telegram

Fully condensed; full narrative archived, see
[`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md).
In order: one live HYBRID attempt stopped before payment (**case-18**);
`/health` provider-mode flags + five read-only Neon views
(`case_summary`/`hermes_decisions`/`recovery_actions`/`hermes_evidence`/
`audit_timeline`); `webhook_relay.py` hardening; SOUL/SKILL wiring; one live
consistent-history case (**case-25**); the non-executable
`RecommendedIntervention`/`MessageStatus` advisory + draft lifecycle;
correction-only fixes (fabricated-delivery gap, `SKILL.md` contradiction,
repair-boundary alignment); product scope locked to insufficient-funds
recovery; advisory narrowed to `NONE`/`PAYMENT_PLAN_REVIEW`; Telegram
delivery foundation built (two gaps - claim atomicity, deterministic
eligibility - closed in Iteration 26).

## Iteration 26 — claim-before-send + deterministic eligibility + LIVE golden case

Condensed; full detail archived, see
[`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md).
Added atomic claim-before-send (`claim_message_delivery`, permanently-closed
claim gate after any outcome, `sanitize_delivery_receipt` fail-closed) and
deterministic `PAYMENT_PLAN_REVIEW` eligibility (>= 2 prior late/failed
obligations, 12-month window only if actually requested; a live proposal
while ineligible fails closed). Minimal Neon visibility added to
`hermes_decisions`/`recovery_actions`. **The golden reliable-customer case
ran live and succeeded (`case-29`)**: `WAIT_FOR_PROVIDER_RETRY` (conf 0.55)
then, after the simulated failed retry, `CREATE_RECOVERY_LINK` (conf 0.88,
real Test Mode link `plink_TYIV2xy5wOT55x`); both `recommended_intervention
=NONE`; message staged `DRAFTED` then delivered - **verified `SENT`** via
real Telegram. Never opened checkout, never marked recovered. Neon read
back read-only, confirmed.

## Iteration 27 — demo-visibility Neon view (presentation only, no engine change)

Condensed; full detail archived, see
[`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md).
New read-only view `hermes_demo.demo_case_story`: one row per MEANINGFUL
business step, chronologically, `step_number` via `ROW_NUMBER()` (never
hardcoded); implementation noise excluded; five existing views unchanged.
Corrected in Iteration 28 - see there for the current truthful shape.

## Iteration 28 — demo_case_story truthfulness correction + reliable-customer-only template

Condensed; full detail archived, see
[`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md).
Corrected three `demo_case_story` truthfulness gaps (retry actor now
derives from `evidence_mode`, never a bare `Razorpay`; Hermes-decision
evidence now shows real tool/source/coverage; Telegram stage name matches
the true outcome). Locked the approved customer template to one fixed
reliable-customer reminder; the isolated Hermes runtime now offers/accepts
it only when the disclosed 3-month evidence itself proves a reliable
customer, else rejects fail-closed. Corrected a stale `POLICY_SPEC.md`
claim. Applied live; `case-29` re-read read-only, confirmed corrected.

## Iteration 29 — final reliable-customer showcase case (case-40)

One fresh live run of `scripts/run_golden_reliable_case.py --confirm-live`
against the corrected Iteration 28 view/template - the showcase recording
case (**case-40**, distinct from `case-29`). Decision 1:
`WAIT_FOR_PROVIDER_RETRY`/`NONE`, confidence 0.55, reliable 3-month history
only (no 12-month lookup). Decision 2 (after the explicitly `SIMULATED`
failed retry): `CREATE_RECOVERY_LINK`/`NONE` - one real Test Mode link
(`REAL_TEST_MODE`). Staged draft matched the approved template
byte-for-byte; URL appended only at the delivery boundary, never by
Hermes. Telegram **verified `SENT`**. Neon `demo_case_story` returned the
complete 10-step story with truthful actors/evidence/reasoning/duration;
`recovered_amount_minor=0`, `counted=false` - no payment-success claim.
Never opened checkout, no tunnel; API started/stopped by this iteration
only.

## Verified evidence

Pre-Iteration-21 evidence is archived - see
[`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md).
Iterations 21/23/24/25 focused/full counts: 41/373, 60/404, 67/410,
71/442 (all passed, 3 skipped where applicable; 22 made no source change).
Iterations 26-28 counts/evidence archived, see the same file.

- **Iteration 29**: no source change (live run only). Preflight/`/health`
  confirmed `hermes-runtime`/`hybrid_test_mode`/`telegram` before running;
  script's own success assertions passed at every step; Neon read back
  read-only, confirmed above.

## Inspecting the persisted proof

- Neon SQL editor, schema `hermes_demo`: query the six views directly (e.g.
  `SELECT * FROM hermes_demo.demo_case_story WHERE case_id = 'case-40'
  ORDER BY step_number`) - see
  [`sql/neon_demo_inspect.sql`](sql/neon_demo_inspect.sql) for ready-made
  all-cases and one-case queries (swap in `'case-18'`). User-run flow:
  [`scripts/neon_proof.py`](scripts/neon_proof.py).

## Repeatable launch

```
.\scripts\run_demo.ps1 -Mode hermes
```

Payment provider defaults to `fake` (unchanged). Hybrid Test Mode + Telegram
credentials are configured (`.env`, gitignored); `/health` reports
`payment_provider`/`payment_provider_test_mode_enabled`/
`message_delivery_channel` so `run_one_hybrid_case.py`/
`run_golden_reliable_case.py` fail closed if not actually wired up. No API/
relay/tunnel is currently running.

## Blockers

- None technical. `case-18` intentionally sits `active`/awaiting payment
  (Codex/user decision, see archive). `hermes` mode stays manual-control only.

## Next action

The final reliable-customer showcase case is done and verified
(**case-40**, superseding `case-29` as the recording reference). Next:
author and run ONLY the mixed-history exemplar (a justified optional
12-month `get_payment_history` lookup, proving the history-expansion
path). Dashboard remains last. No further live action planned against
`case-18`/`case-25`/`case-29`/`case-40`. Keep future updates at or below
230 lines.

## Working-document links

- History: [`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md)
- Plan map: [`IMPLEMENTATION_BACKLOG.md`](IMPLEMENTATION_BACKLOG.md)
- Build contract: [`IMPLEMENTATION_SPEC.md`](IMPLEMENTATION_SPEC.md)
- Policy: [`POLICY_SPEC.md`](POLICY_SPEC.md)
- Razorpay Test Mode contract: [`RAZORPAY_TEST_SLICE.md`](RAZORPAY_TEST_SLICE.md)
- Neon queries: [`sql/neon_demo_inspect.sql`](sql/neon_demo_inspect.sql)
- Isolated-Hermes research: [`HERMES_ISOLATED_AGENT_RESEARCH.md`](HERMES_ISOLATED_AGENT_RESEARCH.md)

<!-- latest verified commit: see `git log -1` on feat/isolated-hermes-agent -->
