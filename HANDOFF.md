# Cross-Agent Handoff — current-state index

Last updated: 2026-09-05 (Asia/Dubai), Iteration 22. Branch
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

Condensed; full detail archived. Wired Codex's `config/hermes_agent/SOUL.md`
(agent identity/scope) beside the existing `SKILL.md` Rule 1 (consistent
recent payment behavior) into the isolated child's ephemeral system prompt,
order SOUL -> SKILL -> case context -> tool/output contract; both files
preserved verbatim. `__init__` fails closed (`HermesRuntimeUnavailable`) if
either is missing, unreadable, or not valid UTF-8; `_propose_locked` assigns
fresh `last_run_meta` before re-reading them so a load failure can never
inherit a prior successful run's metadata. Offline
`python -m pytest -q tests/test_hermes_agent.py` went 33 -> 37 (wiring) -> 41
(4 correction regressions) passed; full offline suite steady at 373 passed,
3 skipped throughout. See
[`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md)
for the full narrative.

## Iteration 22 — one live consistent-history exemplar, persisted to Neon

**First real run of the SOUL + Rule 1 wiring against live Gemini.** One new
trusted demo case (`case-25`, obligation `sub_demo_0005_e2c073a9`) created via
the existing `POST /demo/case` -> `POST /demo/step {"step":"advance"}` path,
advanced exactly once, then stopped - no retry-failed, no recovery link, no
capture, no second case. Local FastAPI only (`hermes.asgi:app`,
`127.0.0.1:8000`, `HERMES_MODE=hermes`); no Streamlit, tunnel, relay, or
Docker. Preflight: clean tree at `c43234c`, installed Hermes revision matched
`EXPECTED_HERMES_REVISION`, `GEMINI_API_KEY`/`DATABASE_URL` present via
`.env` (values never printed), all five Neon views present. `.env` still
carries `RAZORPAY_PROVIDER=hybrid_test_mode` from Iteration 18 - overridden
to `fake` via a process-only shell env var (`.env` untouched; `load_dotenv`
uses `override=False`) so `/health` reported `payment_provider=fake` /
`payment_provider_test_mode_enabled=false` before the case was created.

**Result - every expected condition passed, verified, none forced:**
`action=WAIT_FOR_PROVIDER_RETRY`, `policy_outcome=ALLOW`
(`provider_retry_permitted`), `state=waiting`, `confidence=0.55` (medium
band), one tool call (`get_payment_retry_facts` only, no
`get_payment_history`, `history_expansion_requested=false`), zero recovery
links/messages/Razorpay calls, `human_review_required=false`. Rationale cited
the 3-month on-time pattern, its limited coverage, verified provider-retry
eligibility, and the remaining uncertainty - unedited model output.

**Neon readback** (`hermes_demo`, scoped to `case-25`): `case_summary` 1 row
(`display_status=WAITING_FOR_PROVIDER_RETRY`); `hermes_decisions` 1 row
(`gemini-3.7-flash`, `prompt_version=hermes-agent/2026-09-05.2`, revision
`e02d1e41f...`, 1 tool call/6 budget, 2 model iterations/8 budget, ~17.1s);
`recovery_actions` 0 rows (correct - WAIT creates no link); `hermes_evidence`
1 row (`get_payment_retry_facts`/`SIMULATED_PROVIDER`); `audit_timeline` 6
rows (`INPUT_EVENT`, `DEMO_CASE_PROVENANCE`, `AI_MODEL_RUN`, `AI_PROPOSAL`,
`POLICY_DECISION`, `SCHEDULED_ACTION`). No source code changed; no code-change
rule invoked. API process stopped and port confirmed free after readback.

## Verified evidence

Pre-Iteration-21 evidence (the generic offline baseline and Iterations 18-20)
is archived - see
[`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md).

- **Iteration 21**: focused `tests/test_hermes_agent.py` -> **41 passed**;
  full offline (`--ignore=tests/test_hermes_agent.py`) -> **373 passed, 3
  skipped**. `compileall` + `git diff --check` clean.
- **Iteration 22**: no source change, so no test suite re-run was required;
  this iteration's evidence is the live Neon readback above. No API/relay/
  tunnel left running; no Razorpay/payment/link/message/public-service call.

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

Codex reviews the consistent-history result (`case-25`, above), then authors
the inconsistent-history judgment rule for `SKILL.md`. No further live action
planned against `case-18`/`case-25`. The mixed-history exemplar stays
deferred per the backlog. Keep future `HANDOFF.md` updates under 280 lines.

## Working-document links

- History: [`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md)
- Plan map: [`IMPLEMENTATION_BACKLOG.md`](IMPLEMENTATION_BACKLOG.md)
- Build contract: [`IMPLEMENTATION_SPEC.md`](IMPLEMENTATION_SPEC.md)
- Policy: [`POLICY_SPEC.md`](POLICY_SPEC.md)
- Razorpay Test Mode contract: [`RAZORPAY_TEST_SLICE.md`](RAZORPAY_TEST_SLICE.md)
- Neon queries: [`sql/neon_demo_inspect.sql`](sql/neon_demo_inspect.sql)
- Isolated-Hermes research: [`HERMES_ISOLATED_AGENT_RESEARCH.md`](HERMES_ISOLATED_AGENT_RESEARCH.md)

<!-- latest verified commit: see `git log -1` on feat/isolated-hermes-agent -->
