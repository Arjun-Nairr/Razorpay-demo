# Cross-Agent Handoff — current-state index

Last updated: 2026-09-05 (Asia/Dubai), Iteration 24. Branch
`feat/isolated-hermes-agent`, latest commit at bottom. This file stays
**under 240 lines**: it is an index, not a log. Detail lives in the linked
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
implemented - retry eligibility always stays simulated. Mechanics
(`HybridPaymentProvider` composition, the separately-secured
`POST /webhooks/razorpay-test` route) and Iterations 15-17 (first cut,
five-defect correction, two small gap fixes) are archived. User-only setup
(Test Mode key pair, webhook, `.env` flags) is DONE; manual Test Mode
checkout was deliberately not completed (see Iteration 18 below).

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

Condensed; full detail archived. Separated Hermes's executable `action`
from a new non-executable `RecommendedIntervention` advisory (6 values, no
discount/access/suspension/freeze value exists); `StrategyProposal` gained
`recommended_intervention`/`human_review_recommended`/`human_review_reason`
(safe defaults, existing proposals unaffected); `engine._validate_proposal`
fails closed on the full combination rule. New `MessageStatus` lifecycle
(`NOT_REQUESTED`/`SUPPRESSED`/`AUTHORIZED`/`DRAFTED`/`SENT`-reserved) staged
via a new `MESSAGE_DRAFTED` audit event. Neon's `hermes_decisions`/
`recovery_actions` views extended (historical rows read `NOT_RECORDED`/
`LEGACY_NOT_STAGED`, never a false positive). See
[`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md)
for the full narrative.

## Iteration 24 — correction-only: fabricated-delivery + instruction fixes

Three review findings closed; no new fixture/case, no live call.

- **Removed the last fabricated-delivery path** (`engine.py`): Iteration 23
  made `message_sent` default `False` only for a provider *missing*
  `message_delivery_capable`; a provider that SET it `True` would still have
  been read. That lookup is now removed entirely - `message_sent` is always
  `False` here, unconditionally, until a real (Telegram) adapter owns a
  verified `DRAFTED -> SENT` transition. New regression
  (`test_a_capability_flag_is_not_evidence_of_delivery`) proves a provider
  claiming `message_delivery_capable=True` still yields `message_sent=False`,
  `message_status=DRAFTED`, and an unchanged contact counter.
- **Fixed a real instruction contradiction** (`SKILL.md`): removed the
  "unless an independent unresolved risk genuinely requires review"
  exception, which contradicted the `NONE`/`UPDATE_PAYMENT_METHOD` rule
  `engine._validate_proposal` actually enforces. The rule is now exactly:
  `NONE`/`UPDATE_PAYMENT_METHOD` require `human_review_recommended=false`
  and `reason=null`; every other value requires `true` + a nonblank reason
  - no exception, matching the code precisely.
- **Aligned repair-boundary validation**: both `child_main._validate()`
  (isolated Hermes) and `hermes_strategist.parse_proposal()` (direct
  Gemini) now reject an unsafe `human_review_reason` (URL, currency/amount
  marker, or a payment/provider/customer/event/subscription/link/case
  identifier-shaped token) themselves, inside their own one-repair
  boundary - not only later, once, in `engine._validate_proposal` (kept as
  canonical defense-in-depth). New tests prove an unsafe first reply enters
  the existing repair path and is either fixed or bounded-fails - it can
  never reach the engine unsafe.

## Verified evidence

Pre-Iteration-21 evidence is archived - see
[`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md).

- **Iteration 21**: focused **41 passed**; full offline **373 passed, 3 skipped**.
- **Iteration 22**: no source change; live Neon readback (archived above).
- **Iteration 23**: focused **60 passed**; full offline **404 passed, 3 skipped**.
- **Iteration 24**: focused `tests/test_hermes_agent.py` -> **67 passed**
  (+7). Full offline (`--ignore=tests/test_hermes_agent.py`) -> **410
  passed, 3 skipped** (+6). `compileall` + `git diff --check` clean; diff
  and secret scan reviewed. No Gemini/Razorpay/Telegram/webhook/tunnel/
  new-case activity.

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

These corrections are complete; the branch is ready for the **Telegram
delivery adapter** (owning the real, verified `DRAFTED -> SENT` transition -
see Iteration 24), followed by one golden reliable-customer end-to-end case
through that adapter. The chronically-late and mixed-history exemplars
remain deferred until after that. The dashboard stays the final
presentation layer, updated last. No further live action planned against
`case-18`/`case-25`. Keep future `HANDOFF.md` updates under 240 lines.

## Working-document links

- History: [`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md)
- Plan map: [`IMPLEMENTATION_BACKLOG.md`](IMPLEMENTATION_BACKLOG.md)
- Build contract: [`IMPLEMENTATION_SPEC.md`](IMPLEMENTATION_SPEC.md)
- Policy: [`POLICY_SPEC.md`](POLICY_SPEC.md)
- Razorpay Test Mode contract: [`RAZORPAY_TEST_SLICE.md`](RAZORPAY_TEST_SLICE.md)
- Neon queries: [`sql/neon_demo_inspect.sql`](sql/neon_demo_inspect.sql)
- Isolated-Hermes research: [`HERMES_ISOLATED_AGENT_RESEARCH.md`](HERMES_ISOLATED_AGENT_RESEARCH.md)

<!-- latest verified commit: see `git log -1` on feat/isolated-hermes-agent -->
