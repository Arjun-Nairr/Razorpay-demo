# Cross-Agent Handoff — current-state index

Last updated: 2026-09-05 (Asia/Dubai), Iteration 26. Branch
`feat/isolated-hermes-agent`, latest commit at bottom. This file stays
**under 240 lines**: it is an index, not a log. Detail lives in the linked
docs; iteration-by-iteration history is in
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

## Iterations 18-24 — case-18, Neon views, SOUL wiring, advisory + corrections

Fully condensed; full narrative archived, see
[`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md).
In order: one live HYBRID attempt stopped before payment (**case-18**);
`/health` provider-mode flags + five read-only Neon views
(`case_summary`/`hermes_decisions`/`recovery_actions`/`hermes_evidence`/
`audit_timeline`); `webhook_relay.py` hardening; Codex's
`config/hermes_agent/SOUL.md` wired beside `SKILL.md` into the isolated
child's prompt; one live consistent-history case (**case-25**,
`WAIT_FOR_PROVIDER_RETRY`/`ALLOW`/`waiting`); the non-executable
`RecommendedIntervention` advisory contract + `MessageStatus`
(`NOT_REQUESTED`/`SUPPRESSED`/`AUTHORIZED`/`DRAFTED`/`SENT`-reserved)
lifecycle added, with a `MESSAGE_DRAFTED` audit event; then correction-only
fixes (a fabricated-delivery gap in `engine.py`, a `SKILL.md` instruction
contradiction, repair-boundary validation alignment).

## Iteration 25 — product scope lock + narrowed advisory + Telegram foundation

Condensed; full detail archived. Locked the product to insufficient-funds
recovery at the webhook boundary; narrowed the advisory contract to
`NONE`/`PAYMENT_PLAN_REVIEW`; built the Telegram delivery foundation
(`telegram_delivery.py`, `MessageDeliveryAdapter` protocol,
`engine.deliver_drafted_message`). Two gaps found in review - no
claim-before-send atomicity, no deterministic payment-plan eligibility
check - were closed in Iteration 26 below. See
[`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md)
for the full narrative.

## Iteration 26 — claim-before-send + deterministic eligibility + LIVE golden case

**The golden reliable-customer case ran live and succeeded - see below.**

- **Claim-before-send** (`types.py`/`adapters.py`/`engine.py`): a new
  `claim_message_delivery` ledger call durably marks an attempt
  `in_progress` BEFORE Telegram is ever called - a concurrent/second
  claimant gets `claimed=False` and never calls the adapter. After ANY
  outcome (`sent`/`failed`/`uncertain`) the claim gate is permanently
  closed - never automatically eligible again. `reconcile_uncertain_intents`
  (already run at every startup) now also sweeps a crashed `in_progress`
  claim to a safe, non-retryable `uncertain`. `sanitize_delivery_receipt`
  (checked at both the orchestration and ledger boundaries) forces an
  unknown outcome, or `sent` without a nonblank/bounded/digit-only message
  id, to `uncertain` - never `SENT`; a non-`sent` outcome never carries a
  message id. New regressions: concurrent claim, replay after
  failure/uncertainty, crash recovery, forged-`sent` receipts.
- **Deterministic `PAYMENT_PLAN_REVIEW` eligibility**
  (`hermes_agent_strategist.py`): a new `_payment_plan_eligibility` fact,
  computed from the SAME synthetic records actually disclosed for the
  decision (never model text) - requires >= 2 PRIOR (never the current
  failure) completed late/failed obligations; the 12-month window counts
  only if `get_payment_history` was actually called. A live proposal of
  `PAYMENT_PLAN_REVIEW` while ineligible fails closed
  (`payment_plan_ineligible`) before persistence as an accepted advisory.
  The sanitized eligibility + prior-difficulty count are persisted on every
  decision regardless of outcome. New hostile-model regression proves a
  convincing rationale cannot override this on the reliable-customer
  fixture (eligibility is always `false` there - no chronic/mixed fixture
  was added).
- **Minimal Neon visibility**: `hermes_decisions` gained
  `payment_plan_eligible`/`payment_plan_prior_difficulty_count`;
  `recovery_actions` gained `delivery_channel`/`delivery_status`/
  `delivery_message_id`/`delivery_attempted_time` (never a URL/token/chat
  id). `POST /demo/step {"step":"deliver_message"}` (new) claims+sends via
  `app.state.delivery` (a real `TelegramAdapter` when configured,
  `NullTelegramAdapter` otherwise); `/health` reports a sanitized
  `message_delivery_channel` flag.

**LIVE golden case (`case-29`)**, run via new
`scripts/run_golden_reliable_case.py --confirm-live`: preflighted
`GEMINI_API_KEY`/`DATABASE_URL`/Razorpay Test Mode creds/`TELEGRAM_*`/the
pinned Hermes revision (no value printed) and `/health`
(`hermes-runtime`/`hybrid_test_mode`/`message_delivery_channel=telegram`).
Decision 1: `WAIT_FOR_PROVIDER_RETRY`, `recommended_intervention=NONE`,
confidence 0.55. Decision 2 (after the simulated failed retry):
`CREATE_RECOVERY_LINK`, `recommended_intervention=NONE`, confidence 0.88 -
one real Razorpay Test Mode link (`plink_TYIV2xy5wOT55x`). The approved
template staged `DRAFTED`, then claimed and sent through the real Telegram
adapter - **verified `SENT`** (real `delivery_message_id`). Never opened
checkout, never marked money recovered, no tunnel. Neon read back
read-only and confirmed: one case, both decisions' evidence/confidence
correct, no 12-month expansion, `recommended_intervention=NONE` both times,
`message_status=SENT`, `recovered_amount_minor=0`, no human review/payment
plan triggered. All local processes stopped after readback.

## Verified evidence

Pre-Iteration-21 evidence is archived - see
[`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md).
Iterations 21/23/24/25 focused/full counts: 41/373, 60/404, 67/410,
71/442 (all passed, 3 skipped where applicable; 22 made no source change).

- **Iteration 26**: focused `tests/test_hermes_agent.py` -> **76 passed**
  (+5). Full offline (`--ignore=tests/test_hermes_agent.py`) -> **460
  passed, 3 skipped** (+18: claim-before-send, eligibility, Neon columns,
  delivery-step API). `compileall` + `git diff --check` clean; diff and
  secret scan reviewed; `.env` untouched. Live: one golden case (`case-29`)
  - real Gemini x2, one real Razorpay Test Mode link, one verified Telegram
  send - Neon read back read-only, confirmed above.

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

The golden reliable-customer case is done and verified (`case-29`). Next:
author and run the chronically-late exemplar (a new synthetic fixture with
>= 2 prior late/failed obligations, so `PAYMENT_PLAN_REVIEW` can genuinely
trigger), then the mixed-history exemplar (12-month expansion path). The
dashboard remains the final presentation layer, built last. No further live
action planned against `case-18`/`case-25`/`case-29`. Keep future updates
under 240 lines.

## Working-document links

- History: [`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md)
- Plan map: [`IMPLEMENTATION_BACKLOG.md`](IMPLEMENTATION_BACKLOG.md)
- Build contract: [`IMPLEMENTATION_SPEC.md`](IMPLEMENTATION_SPEC.md)
- Policy: [`POLICY_SPEC.md`](POLICY_SPEC.md)
- Razorpay Test Mode contract: [`RAZORPAY_TEST_SLICE.md`](RAZORPAY_TEST_SLICE.md)
- Neon queries: [`sql/neon_demo_inspect.sql`](sql/neon_demo_inspect.sql)
- Isolated-Hermes research: [`HERMES_ISOLATED_AGENT_RESEARCH.md`](HERMES_ISOLATED_AGENT_RESEARCH.md)

<!-- latest verified commit: see `git log -1` on feat/isolated-hermes-agent -->
