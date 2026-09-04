# Cross-Agent Handoff — current-state index

Last updated: 2026-09-05 (Asia/Dubai), Iteration 23. Branch
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

## Iterations 21-22 — SOUL wiring + one live consistent-history exemplar

Condensed; full detail archived. Iteration 21: wired Codex's
`config/hermes_agent/SOUL.md` beside `SKILL.md` Rule 1 into the isolated
child's ephemeral prompt (SOUL -> SKILL -> case context -> tool/output
contract); `__init__` fails closed if either file is missing/unreadable/not
UTF-8; fresh `last_run_meta` assigned before re-reading them so a load
failure can't inherit a prior run's metadata. Iteration 22: one real
consistent-history case (**case-25**) run through live Gemini via the
existing `/demo/case` + `/demo/step advance` path, stopped after one
decision - `WAIT_FOR_PROVIDER_RETRY`/`ALLOW`/`waiting`, confidence 0.55
medium, one `get_payment_retry_facts` call, zero links/messages, persisted
to and read back from all five Neon views. See
[`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md)
for the full narrative.

## Iteration 23 — advisory-intervention + staged-message foundation

Separated Hermes's executable `action` from a new **non-executable
advisory**, and replaced the fake-provider bug that equated policy
authorization with actual message delivery with a real staged-draft
lifecycle. No new fixture/case run; no Gemini/Razorpay call.

- **Typed advisory** (`types.py`): `RecommendedIntervention` enum - `NONE`,
  `UPDATE_PAYMENT_METHOD`, `MANDATE_REAUTH_REVIEW`, `PAYMENT_PLAN_REVIEW`,
  `BILLING_SUPPORT_REVIEW`, `HUMAN_FOLLOW_UP` (no value for a discount,
  access change, suspension, or freeze - those stay structurally
  impossible). `StrategyProposal` gains `recommended_intervention`
  (default `NONE`), `human_review_recommended` (default `False`),
  `human_review_reason` (default `None`) - existing scripted/offline
  proposals are unaffected. `engine._validate_proposal` (canonical, all
  strategists) fails closed: unknown enum, non-boolean
  `human_review_recommended`, a reason that is blank/>300 chars/contains a
  URL or a payment-provider-id-shaped token, or a NONE/UPDATE_PAYMENT_METHOD
  proposal carrying a review flag/reason (or the reverse for the other four
  values) all raise `InvalidProposal`. The advisory never reaches
  `authorize()`'s decision logic - it cannot change authorization, execute
  an effect, change case state/pricing/access, spend a budget, or count as
  recovered. Live Hermes (`child_main.py`) and direct-Gemini
  (`hermes_strategist.py`) JSON contracts now require all three fields
  explicitly (`REQUIRED_KEYS` grew from 6 to 9 keys each); both prompt
  versions bumped.
- **Audit persistence** (`adapters.py`): every `AI_PROPOSAL` event now
  carries `recommended_intervention`/`human_review_recommended`/
  `human_review_reason` alongside the existing fields. Kept fully separate
  from the deterministic case-level `human_review_required`. A historical
  row lacking the keys reads back as `NOT_RECORDED`/`null`, never a
  rewritten `NONE`.
- **Message staging**: new `MessageStatus` lifecycle -`NOT_REQUESTED` /
  `SUPPRESSED` / `AUTHORIZED` / `DRAFTED` / `SENT` (reserved, never set this
  milestone) - computed once at `ACTION_INTENT` time
  (`compute_message_status`) and advanced to `DRAFTED` only in
  `apply_action_outcome`, only after a CONFIRMED `create_recovery_link`
  success (never on `ProviderActionUncertain`), with a new append-only
  `MESSAGE_DRAFTED` audit event (case/intent correlation + the exact
  approved template + status - never a checkout URL). The draft is the
  approved template verbatim - deterministic code, never the model, does
  the "rendering" (identity, since the templates already carry no
  URL/amount/id). Idempotent: a replayed `apply_action_outcome` returns
  before the drafting logic ever runs twice.
- **Fixed defect**: `engine.run()`'s `message_delivery_capable` lookup
  defaulted to `True` for any provider without the attribute, so the
  DEFAULT `fake` provider reported `message_sent=True` with no delivery
  adapter behind it. Now defaults to `False` like every other provider.
  `test_case3.py`/`test_demo_flow.py`/`test_razorpay_test_mode.py` updated
  honestly (previously asserted the bug as "unchanged behaviour").
- **Neon** (`init_neon.py`, `sql/neon_demo_inspect.sql`): `hermes_decisions`
  gained `recommended_intervention`/`model_human_review_recommended`/
  `model_human_review_reason` (appended at the end - `CREATE OR REPLACE
  VIEW` cannot reposition existing columns); `recovery_actions` gained
  `message_intent`/`message_draft`/`message_status`. Missing historical
  values read `NOT_RECORDED` / `null` / `LEGACY_NOT_STAGED` - never `NONE`/
  `DRAFTED`/`SENT`. No checkout URL exposed by either new column set.
- **Hardening** (carried forward): blank/whitespace-only SOUL/SKILL now
  fails closed like missing/unreadable; the system-prompt ordering test now
  asserts SOUL -> SKILL -> case context -> tool descriptions -> output
  contract.

Ran `python scripts/init_neon.py` once (idempotent `CREATE OR REPLACE VIEW`
only) and read all five views back for **case-18** and **case-25**: state
(`active`/`waiting`), `links_created` (1/0), `actions_taken` (1/0) all
byte-identical to before the view update; new columns show
`recommended_intervention=NOT_RECORDED` on both, `message_status=
LEGACY_NOT_STAGED` on case-18's pre-milestone recovery action.

## Verified evidence

Pre-Iteration-21 evidence is archived - see
[`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md).

- **Iteration 21**: focused `tests/test_hermes_agent.py` -> **41 passed**;
  full offline -> **373 passed, 3 skipped**.
- **Iteration 22**: no source change; evidence is the live Neon readback
  (archived above).
- **Iteration 23**: focused `tests/test_hermes_agent.py` -> **60 passed**
  (+19: blank-file rejection, full ordering, `child_main._validate` advisory
  coverage). Full offline (`--ignore=tests/test_hermes_agent.py`) -> **404
  passed, 3 skipped** (+31 advisory/message-lifecycle/Neon-view tests).
  `compileall` + `git diff --check` clean; diff and secret scan reviewed,
  confined to the files listed above. Live: `init_neon.py` view update +
  case-18/case-25 readback (above) - no Gemini/Razorpay/Telegram/webhook/
  tunnel/new-case activity.

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

Codex authors Rule 2 for chronically-late payment behavior in `SKILL.md`;
Claude Code then implements the wiring (if any) and runs that exemplar
through the same live path `case-25` used. No further live action planned
against `case-18`/`case-25`. Keep future `HANDOFF.md` updates under 280 lines.

## Working-document links

- History: [`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md)
- Plan map: [`IMPLEMENTATION_BACKLOG.md`](IMPLEMENTATION_BACKLOG.md)
- Build contract: [`IMPLEMENTATION_SPEC.md`](IMPLEMENTATION_SPEC.md)
- Policy: [`POLICY_SPEC.md`](POLICY_SPEC.md)
- Razorpay Test Mode contract: [`RAZORPAY_TEST_SLICE.md`](RAZORPAY_TEST_SLICE.md)
- Neon queries: [`sql/neon_demo_inspect.sql`](sql/neon_demo_inspect.sql)
- Isolated-Hermes research: [`HERMES_ISOLATED_AGENT_RESEARCH.md`](HERMES_ISOLATED_AGENT_RESEARCH.md)

<!-- latest verified commit: see `git log -1` on feat/isolated-hermes-agent -->
