# Cross-Agent Handoff — current-state index

Last updated: 2026-09-05 (Asia/Dubai), Iteration 25. Branch
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

Fully condensed; full narrative archived - see
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

No live case run; no Gemini/Razorpay/Telegram/Neon call.

- **Product scope locked** (`api.py`): only the normalized reason
  `insufficient_funds` may create a case. Any other/missing
  `PAYMENT_FAILED` reason is acknowledged (2xx, so the provider never
  retry-storms) but never reaches `engine.receive` - no case, retry, link,
  recommendation, or message - returning `outcome:
  "ignored_unsupported_failure_reason"`. Signature verification and
  event-id idempotency are unaffected; a redelivered ignored event is still
  safely acknowledged (nothing to duplicate, since nothing ever happened).
- **Advisory narrowed to `NONE`/`PAYMENT_PLAN_REVIEW`** (`types.py`,
  `child_main.py`, `hermes_strategist.py`, `SKILL.md`): the other four
  values are removed from the live typed/model contract (never
  reconstructed from persisted JSONB, so historical Neon rows stay exactly
  as recorded - just no longer producible going forward).
  `PAYMENT_PLAN_REVIEW` requires repeated payment-history evidence of a
  recurring affordability/timing difficulty not explained by a technical/
  provider cause; a single failure never justifies it alone.
- **Telegram delivery foundation** (`telegram_delivery.py`, new
  `MessageDeliveryAdapter` protocol, `engine.deliver_drafted_message` free
  function - `RecoveryEngine`'s own surface stays `receive`/`run`/
  `inspect`): disabled by default, config read only from `TELEGRAM_ENABLED`/
  `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` (`.env.example` updated, `.env`
  untouched). Delivers only an already-authorized, already-`DRAFTED`
  message for an executed `CREATE_RECOVERY_LINK` with a CONFIRMED
  `REAL_TEST_MODE` checkout URL (never a `SIMULATED` link); the URL is
  appended to the approved template only at this boundary - Hermes never
  sees or generates it, and it never enters the stored draft/audit trail.
  `message_status` advances `DRAFTED -> SENT` only on a verified success
  with a message id; `failed`/`uncertain` are recorded (new append-only
  `MESSAGE_DELIVERY_ATTEMPTED` audit event, sanitized fields only) but
  never auto-retried and never claim `SENT`. Idempotent: an intent already
  `SENT` is filtered out before the adapter is ever called again - a replay
  can never send a second message. `scripts/telegram_setup.py` verifies the
  bot (`getMe`) and lists chat-id candidates (`getUpdates`) without ever
  printing a secret value or writing `.env`; no test makes a real network
  call.

## Verified evidence

Pre-Iteration-21 evidence is archived - see
[`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md).
Iterations 21/23/24 focused/full counts: 41/373, 60/404, 67/410 (all
passed, 3 skipped where applicable; 22 made no source change).

- **Iteration 25**: focused `tests/test_hermes_agent.py` -> **71 passed**
  (+4). Full offline (`--ignore=tests/test_hermes_agent.py`) -> **442
  passed, 3 skipped** (+32: scope-lock, Telegram, advisory-narrowing).
  `compileall` + `git diff --check` clean; diff and secret scan reviewed.
  No Gemini/Razorpay/Telegram/Neon call; no case created.

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

The Telegram adapter is built but **not yet live-verified**. Exact next
step: the user completes Telegram setup (BotFather token + chat id in
`.env`; see chat for the numbered guide), then Claude Code verifies it
(`scripts/telegram_setup.py`) - no case run yet. After that: one golden
reliable-customer end-to-end case, live, through Telegram. Chronically-late
and mixed-history exemplars remain deferred until after that; the dashboard
stays the final presentation layer, built last. No further live action
planned against `case-18`/`case-25`. Keep future updates under 240 lines.

## Working-document links

- History: [`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md)
- Plan map: [`IMPLEMENTATION_BACKLOG.md`](IMPLEMENTATION_BACKLOG.md)
- Build contract: [`IMPLEMENTATION_SPEC.md`](IMPLEMENTATION_SPEC.md)
- Policy: [`POLICY_SPEC.md`](POLICY_SPEC.md)
- Razorpay Test Mode contract: [`RAZORPAY_TEST_SLICE.md`](RAZORPAY_TEST_SLICE.md)
- Neon queries: [`sql/neon_demo_inspect.sql`](sql/neon_demo_inspect.sql)
- Isolated-Hermes research: [`HERMES_ISOLATED_AGENT_RESEARCH.md`](HERMES_ISOLATED_AGENT_RESEARCH.md)

<!-- latest verified commit: see `git log -1` on feat/isolated-hermes-agent -->
