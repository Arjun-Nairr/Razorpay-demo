# Cross-Agent Handoff

Last updated: 2026-09-02 (Asia/Dubai)

## Goal and scope

Prepare and build a selection-quality AI Revenue Recovery Agent demo using the
requirements in `PROJECT_BRIEF.md`.

## Current state

- Shared workspace initialized.
- Original brief and official challenge image normalized into
  `PROJECT_BRIEF.md`.
- No tool research, architecture, dependencies, repository scaffolding, or
  implementation has begun.
- No repository exists yet.
- Current primary-source tooling research is saved in
  `TOOLING_RESEARCH.md`.
- Foundation architecture is saved in `FOUNDATION_ARCHITECTURE.md`.
- Case 1 is locked as a temporary subscription failure followed by a permitted
  wait, successful Razorpay test charge, verified webhook, and exact-once
  recovery accounting.
- The five-case batch is defined in `SCENARIO_MATRIX.md`: three common cases,
  one normally always-on-time customer, and one chronically late customer.
- Exact actions and deterministic rules are defined in `POLICY_SPEC.md`.
- Hermes cannot change commercial terms or account access. It can recommend an
  access hold only after deterministic conditions; real enforcement is outside
  the first demo.
- Claude's standing workflow is defined in `CLAUDE.md`: read this handoff first,
  load only relevant referenced context, update the handoff after each
  iteration, commit verified milestones, and push only when a remote exists.
- Claude Code Prompt 01 is delivered directly in the Codex chat rather than
  stored as a project file.
- Graphify was evaluated and deferred until a meaningful codebase exists; it
  maps code structure but does not replace product-decision handoffs.
- Status: Iteration 02 (corrective) complete. Case 1 foundation hardened for
  future Neon/Gemini/Razorpay adapters; see the iteration records below.

## Iteration 02 — Corrective: adapter-safe Case 1 foundation

- Branch: `feat/case-1-recovery-slice` (unchanged).
- Commit: `a7b7d6660625c9e8fd86e1e6bf35f640ab473861`
  (`fix(engine): harden Case 1 foundation for future real adapters`).
- No Git remote exists: `REMOTE_NOT_CONFIGURED` (nothing pushed).
- No new product features; no new dependencies; project documents unchanged
  except this file.

### Changed files

- `src/hermes/types.py` — added `ProviderRetryFact`, `InvalidProposal`,
  `Case.failure_reason`, `ScheduledWork.attempts/consumed`; widened `RunReport`
  (`strategist_failures`, `scheduled`, `blocked`); added typed inspect
  queries/projections (`CaseQuery`/`BatchQuery`/`AuditQuery`,
  `CaseProjection`/`BatchProjection`/`AuditProjection`, `AuditRecord`),
  `RecoveryQuery`/`RecoveryView` unions, `AUDIT_STRATEGIST_FAILURE`.
- `src/hermes/adapters.py` — `FakeRazorpayAdapter.retry_eligibility()` /
  `set_retry_eligibility()`; `InMemoryLedger` rewritten around cohesive
  single-transaction operations: `open_case`, `apply_evaluation`,
  `apply_strategist_failure`, `apply_capture`, `discard_work`, `note_event`,
  `note_orphan_event`, plus `claim_due_work` (durable read) and
  `recovered_payment_ids`. `MAX_WORK_ATTEMPTS = 3`, `RETRY_BACKOFF_HOURS = 1`.
- `src/hermes/engine.py` — `authorize()` takes a `ProviderRetryFact` and blocks
  `WAIT_FOR_PROVIDER_RETRY` when `retry_eligible` is false; `_validate_proposal`
  rejects non-typed / out-of-range strategist output; `run()` wraps the
  strategist call in try/except (raise, timeout, invalid output ->
  `apply_strategist_failure`, no action, bounded retry); all state changes go
  through ledger transactions; `inspect()` dispatches on typed query objects and
  returns typed projections, `TypeError` on anything else.
- `tests/test_case1.py` — rewritten to the public seam only (no
  `engine._…`); 19 tests incl. retry-eligible/ineligible, failing strategist,
  bounded-retry, invalid-output, global payment-id dedup, cross-obligation
  payment-id, typed-projection, and the full Case 1 integration path. Includes a
  guard test asserting the file contains no private-attribute access.

### Corrections applied

1. Provider retry eligibility is a typed provider fact in the snapshot; policy
   blocks the wait when ineligible; the proposal cannot influence it.
2. Strategist failure: work stays durable during the call; on failure no action
   runs, `STRATEGIST_FAILURE` is audited, and a bounded retry (<=3 attempts) is
   scheduled — no infinite loop.
3. Ledger operations are cohesive and atomic (one transaction each); the engine
   no longer performs unrelated public mutations; external calls stay outside
   transactions.
4. Exact-once recovery is enforced globally by payment id, not just
   `Case.counted`: repeated event ids, distinct event ids with the same payment
   id, and one payment id across two obligations cannot double-count.
5. `inspect` uses typed query and projection objects; the public surface is
   still exactly `receive` / `run` / `inspect`.
6. Tests observe only `receive` results, `RunReport`, `inspect` projections, and
   public exceptions.

### Verification

- `cd C:\Users\dwish\Documents\Codex\2026-09-02\fors\outputs\ai-revenue-recovery`
- `python -m pytest -q` → `19 passed in ~0.2s`.
- `python -m compileall -q src tests` → clean.
- No lint/type tooling is configured, so none was run.

### Remaining limitations (in scope for later prompts)

- `authorize()` still implements only the terminal guard + the
  `WAIT_FOR_PROVIDER_RETRY` path (now with eligibility); the full 10-step policy
  order is not implemented (`ponytail:` comment in `engine.py`).
- A retry-ineligible failure leaves the case `active` with no pending work
  (audit-only outcome), matching how `capture_mismatch` is handled; a real
  policy would `ESCALATE`.
- Cross-obligation payment-id conflict audits `ESCALATE` but does not change the
  second case's state.
- No HMAC, no real Razorpay/Gemini/Neon/FastAPI/Streamlit, no real outbox
  (single-threaded in-memory; transaction boundaries are documented, not
  enforced).
- A zero-hour wait could re-queue within one `run`; `WORK_LOOP_LIMIT` is the
  backstop (Case 1's minimum wait is 24h, so it never churns).
- `inspect` `CaseProjection`/`BatchProjection`/`AuditProjection` shapes are
  Case-1 sized; Cases 2–5 will extend them.

### Exact recommended next action

Codex reviews commit `a7b7d66` (diff `main..feat/case-1-recovery-slice`), then
issues Prompt 03 for Case 3 (insufficient funds with adaptation): a scripted
`WAIT_FOR_PROVIDER_RETRY` that, after a failed provider retry event, is followed
by `SEND_REMINDER` / `CREATE_RECOVERY_LINK`, exercising message
cooldown/count limits and the re-evaluation-after-failed-retry path through the
same `receive` / `run` / `inspect` surface.

## Iteration 01 — Case 1 in-memory vertical slice

- Branch: `feat/case-1-recovery-slice` (off `main`).
- Slice commit: `1a9dcc692d8fbbb8cc74dd9e11a5a62560fd27f4`
  (`feat(engine): in-memory Case 1 recovery vertical slice`).
- Baseline commit on `main`: `d8f9eb9`
  (`chore: initialize repository with project documents and Python .gitignore`).
- Repository was absent; initialized here. No Git remote exists:
  `REMOTE_NOT_CONFIGURED` (nothing pushed).

### Files added

- `.gitignore` — Python + tooling caches + `.env` (keeps `.env.example`).
- `pyproject.toml` — `hermes-recovery`, Python >=3.11, no runtime deps,
  `dev = [pytest]`, `pytest pythonpath = ["src"]` (no install step needed).
- `src/hermes/__init__.py`
- `src/hermes/types.py` — typed data across the engine seam: `RazorpayWebhook`
  /`WebhookType`, `ProposalAction`/`StrategyProposal`,
  `PolicyOutcome`/`PolicyDecision`, `ReceiveResult`/`RunReport`,
  `Case`/`CaseState`/`ScheduledWork`/`AuditEvent`, audit-kind constants.
- `src/hermes/adapters.py` — `FakeRazorpayAdapter` (records + verifies captures),
  `ScriptedStrategist` (reason-code -> canned typed proposal, `.calls` counter),
  `InMemoryLedger` (cases, scheduled work, append-only audit, event dedup set,
  `recovered_minor` accumulator, monotonic id/seq counters).
- `src/hermes/engine.py` — `RecoveryEngine` with only `receive` / `run` /
  `inspect`, plus the module-level deterministic `authorize()` policy function.
- `tests/test_case1.py` — 11 behaviours, all through the public engine surface.

Existing project documents were not modified (this file excepted).

### Implemented behaviour (Case 1)

- Logical time is an integer monotonic clock in logical hours; `run(until)`
  raises `ValueError` if `until` < current clock.
- `receive(payment.failed)`: dedups `event_id`; first failure for an obligation
  creates exactly one `active` case, audits `INPUT_EVENT`, enqueues an immediate
  re-evaluation. A later failure for the same obligation neither forks a case nor
  reopens a terminal one.
- `run(until)`: claims due work in `(due_time, work_id)` order; builds a
  source-labelled snapshot; calls the scripted strategist (outside the state
  mutation); audits `AI_PROPOSAL`; applies `authorize()`; audits
  `POLICY_DECISION`; on `ALLOW` of `WAIT_FOR_PROVIDER_RETRY` sets the case
  `waiting`, schedules re-evaluation at `now + min(wait, 72)`, audits
  `SCHEDULED_ACTION`. Work-loop cap 50 steps/call.
- `receive(payment.captured)`: audits `INPUT_EVENT`; verifies via
  `FakeRazorpayAdapter`; on amount match audits `PAYMENT_CONFIRMATION`, cancels
  pending work (`PENDING_WORK_CANCELLED`), adds `amount_minor` to
  `recovered_minor` once (guarded by `Case.counted`), sets state `recovered`,
  links the payment id, audits `TERMINAL_TRANSITION`. Duplicate provider event
  id, or any capture for an already-`recovered` case, is a no-op for money.
- `inspect({"kind": ...})` returns dict projections for `case` (by `case_id` or
  `obligation_id`), `batch` (`cases`, `recovered_cases`, `recovered_minor`), and
  `audit` (ordered append-only events, optionally filtered by `case_id`).
- ₹10,000 is represented as `1_000_000` integer minor units (paise).

### Verification

- `cd C:\Users\dwish\Documents\Codex\2026-09-02\fors\outputs\ai-revenue-recovery`
- `python -m pytest -q` → `11 passed in ~0.1s`.
- `python -m compileall -q src tests` → clean.
- No lint/type tooling is configured in `pyproject.toml`, so none was run.

### Limitations (intentional, in scope for later prompts)

- `authorize()` implements only the terminal-state guard and the
  `WAIT_FOR_PROVIDER_RETRY` path; the full 10-step policy order (cooldowns,
  attempt/message limits, consent, dispute, commercial safety, reconciliation)
  is not implemented. Marked with a `ponytail:` comment.
- No HMAC verification — webhooks are trusted fakes.
- No real Razorpay / Gemini / Neon / FastAPI / Streamlit; no transactional
  outbox (in-memory dict, single-threaded — ordering documented via comments so a
  real ledger can keep external calls between commits).
- Only `ProposalAction.WAIT_FOR_PROVIDER_RETRY` is authorizable; other actions
  return `BLOCK` `action_not_supported_in_slice`.
- `inspect` takes/returns dicts, not typed `RecoveryQuery`/`RecoveryView`.
- Cases 2–5 not implemented.

### Exact recommended next action

Codex reviews commit `1a9dcc6` (diff `main..feat/case-1-recovery-slice`), then
issues Prompt 02 for Case 3 (insufficient funds with strategy adaptation) to
force `SEND_REMINDER` / `CREATE_RECOVERY_LINK` proposals, the message
cooldown/limit rules, and the re-evaluation-after-failed-retry path through the
same `receive` / `run` / `inspect` surface.

## Decisions and invariants

- AI proposes recovery strategies; deterministic code enforces permissions and
  safety constraints.
- Optimize for deep behavior across 5–8 designed scenarios, not batch scale.
- Treat the 5–8 rich scenarios as an evaluation batch and show aggregate money
  recovered, satisfying the official judging bar.
- Razorpay test mode is the intended payment integration.
- Use free or meaningfully usable free-tier tooling where feasible.
- Keep the build selection-demo sized; avoid production overengineering.
- Do not treat any candidate action or technology as approved until discovery
  and research are complete.
- Internal delivery target is September 4 evening (Asia/Dubai assumed until
  confirmed); official September 5 cutoff time is unknown.
- The expected submission artifact includes a five-minute recorded demo.
- Razorpay test mode needs to be set up.
- Available model resources: ChatGPT Plus, OpenCode Go, and up to USD 22 in
  Gemini API credits if needed. Subscriptions must not be assumed to provide
  programmatic API access; research must verify usable runtime options.
- Synthetic customer history is allowed only where Razorpay does not expose the
  required context.
- Messaging is deferred until the core pipeline is defined; Telegram and email
  are candidates, not approved requirements.
- First-demo wedge: SaaS subscription-payment recovery, not B2B receivables.
- Product identity should be fictional but preferably adjacent to Razorpay's
  payment/SaaS domain.
- Start with one end-to-end case, then expand to at most five variable cases.
- Use an accelerated logical clock; do not make the demo wait through real
  recovery intervals.
- Recovery should be fully automated on normal paths. Policy-triggered stopping
  or human escalation must still exist because compliant escalation is part of
  the official judging bar.
- Synthetic enrichment is limited to useful data that a real SaaS/payment
  company could possess; no impossible or decorative omniscient fields.
- Core demo runs locally. A dashboard alone may be deployed and may communicate
  through a hosted database such as Neon, but Neon is not approved until
  research compares it against alternatives.

## Collaboration contract

- Claude Code owns 100% of implementation, without exception.
- Codex owns orchestration, current-tool research, planning, discussion with the
  user, architecture/specification, performance analysis, and critical review.
- Codex is the sole prompt provider to Claude Code.
- Codex must use `matt-skills-curated:writing-for-agents` when authoring or
  revising every Claude Code prompt. Prompts must use progressive disclosure,
  narrow scope, and observable completion criteria.
- Claude Code creates/retrieves implementation artifacts and evidence for Codex
  to assess. Codex must not duplicate implementation work.

## Open decisions

- Exact official deadline time; September 5, 2026 is assumed from current
  context but should be confirmed if the organizer publishes a year/time
- Judging rubric and selection criteria
- Whether outbound messaging is real or simulated
- Exact fictional SaaS identity and UI style

## Research recommendation (not yet an approved architecture)

- Local Python/FastAPI with the official Google GenAI SDK and Pydantic
- Gemini 3.7 Flash as the initial configurable runtime model
- Neon Postgres as shared state and business audit ledger
- Persisted accelerated logical clock; no external scheduler/job queue
- Streamlit locally for the dashboard
- zrok solely to expose the Razorpay webhook endpoint
- pytest and five hand-authored golden cases
- Provider-neutral message outbox; Telegram only as a stretch adapter
- See `TOOLING_RESEARCH.md` for facts, citations, limits, and rejected tools

## Architecture foundation

- Local modular monolith
- One deep `RecoveryEngine` module with `receive`, `run`, and `inspect`
- Webhook intake persists first and never waits on Gemini
- AI returns a typed proposal; deterministic policy authorizes all effects
- Neon stores current projections plus append-only audit history
- External effects use a transactional outbox and stable idempotency keys
- See `FOUNDATION_ARCHITECTURE.md` for the full contract

## Suggested skills

- `matt-skills-curated:research` for current, primary-source tool research
- `matt-skills-curated:grill-me` if requirements remain ambiguous
- `matt-skills-curated:to-spec` after decisions are settled
- `matt-skills-curated:to-tickets` for Claude Code implementation tasks
- `matt-skills-curated:code-review` when reviewing Claude Code output

## Secrets policy

Never write API keys, Razorpay secrets, webhook secrets, credentials, or private
authentication headers into this folder. Use environment variables and provide
only a redacted `.env.example` when implementation begins.

## Exact next action

Codex reviews commit `a7b7d66` on `feat/case-1-recovery-slice`
(diff `main..feat/case-1-recovery-slice`; run `python -m pytest -q` to
reproduce the 19 passing behaviours), then issues Prompt 03 as described in
"Iteration 02 -> Exact recommended next action" above. No Git remote exists, so
nothing has been pushed (`REMOTE_NOT_CONFIGURED`).
