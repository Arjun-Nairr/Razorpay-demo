# Remaining implementation and discussion map

Updated 2026-09-04 (Iteration 14). Codex's compact planning index, not a new
implementation authorization. Read HANDOFF.md for execution evidence and
IMPLEMENTATION_SPEC.md for the build contract. Update this checklist when
evidence changes; do not mark planned work complete merely because a prompt
was delivered.

## Ownership and deadline

- Codex: discussion, research, architecture, Claude prompts, independent review.
- Claude Code: implementation and tests; read/update HANDOFF.md each iteration,
  commit and push verified milestones, preserve unrelated work.
- User now authorizes Claude to fix startup and run ONE real Gemini-backed
  Hermes demo case writing to existing Neon storage. Existing .env stays private.
  This does not authorize real payments, customer messages, or other app changes.
- Target: five-minute recorded demo, preferably September 4 evening; deadline
  September 5, exact cutoff unconfirmed. Working evidence before extra features.

## Current checkpoint

- Built: deterministic recovery engine, signed simulated ingress, Case 1/3
  foundations, Neon snapshot persistence, basic UI, actual isolated Hermes path.
- Existing Hermes skill: config/hermes_agent/SKILL.md. Refine it, don't assume
  skills are absent or add many files without a need.
- User confirmed init_neon.py succeeded. This proves storage initialization only.
- 2026-09-04 (Iteration 13): actual Hermes + Gemini + Neon case is now
  LIVE-VERIFIED. Case `case-11` (`sub_demo_0003_9bc1578f`) recovered via two
  real gemini-3.7-flash decisions (WAIT_FOR_PROVIDER_RETRY, then
  CREATE_RECOVERY_LINK), deterministic policy authorized, simulated capture,
  read back independently from Neon: `state=recovered`,
  `attribution=hermes_assisted`, `recovered_minor=1000000`. Root cause of the
  earlier "silent stall" CONFIRMED and fixed: (a) IPv6 black hole on the host
  (libpq now gets an IPv4 hostaddr); (b) Avast "Web/Mail Shield" TLS
  interception root missing from the child venv's certifi (parent now supplies
  an OS-trust CA bundle to the child). The Iteration-12 "Neon outage" claim was
  wrong. See HANDOFF.md.
- Razorpay runtime still uses FakeRazorpayAdapter. Keys present is NOT integration.
- Neon currently stores cases/audit inside one ledger_state JSON snapshot row;
  one decision does not create a separate SQL row. Existing inspection SQL exposes
  these records. No schema redesign required merely for visible proof.
- 2026-09-04 (Iteration 14): reviewed-blocker corrections to the Iteration 13
  startup fix, no new live case. (1) DNS pre-resolution and the initial
  snapshot read now share the ONE startup deadline (both were previously
  outside it). (2) A writer-lock/read timeout no longer risks a synchronous
  rollback/close blocking on a busy connection (psycopg's own connection lock)
  — a genuine timeout now only schedules a best-effort background close.
  (3) The late-connection race (worker delivers just as the caller gives up)
  is now decided under one lock shared by both threads, so a connection is
  always either returned or closed, never dropped unclosed. (4) The CA-bundle
  fix now only imports OS-store certs with `x509_asn` encoding trusted for
  TLS server-auth (was: every OS root regardless of purpose/encoding); the
  on-disk bundle is versioned so a previously-generated broad bundle is
  discarded immediately. Existing `case-11` re-read read-only (no new case);
  same state/attribution/decisions confirmed. See HANDOFF.md.
- 2026-09-04 (Iteration 15): Razorpay Test Mode HYBRID slice IMPLEMENTED +
  OFFLINE-TESTED only (no live Razorpay/Gemini call, no new Neon case this
  iteration - see HANDOFF.md). Simulated obligation/history/retry sequence
  UNCHANGED; authorized recovery-link creation + payment confirmation now go
  through a real `RazorpayTestModeAdapter` (disabled by default; rejects any
  non-`rzp_test_` key id before any request). `HybridPaymentProvider` composes
  it with the existing simulated adapter (retry eligibility only) - provider
  choice is independent of the Hermes/Gemini strategist mode. One new webhook
  route, `/webhooks/razorpay-test`, verifies genuine `payment_link.paid`
  events against a separate secret via a separate code path
  (`razorpay_test_mode.py`) - the simulated `/webhooks/razorpay` route is
  untouched. Also fixed a leftover startup bug: the lock-probe/first-read
  budget could re-grant itself a fresh ~2s window after connect had already
  exhausted the deadline. `case-11` re-read read-only; unchanged.
- 2026-09-04 (Iteration 16): fixed five Codex-reviewed defects in the
  Iteration 15 slice, OFFLINE only (no live call, no new case, no tunnel -
  see HANDOFF.md). (1) Payment-to-link verification is now independent: both
  the Payment Link and the payment are fetched, and the link's own `payments`
  list must show this payment captured - the old code trusted the webhook's
  claimed link id unverified. (2) Missing/wrong currency (or any required
  field) now fails closed, never falls back to `case.currency`; contradictory
  same-envelope facts are rejected before any provider call. (3) The mutable
  `_pending[obligation_id]` dict is gone - `verify_link_payment` takes an
  immutable per-call claim, so concurrent webhook deliveries can never mix
  evidence; the handler+engine duplicate provider fetch is gone too (one
  fetch pair per webhook). (4) An ambiguous/malformed link-creation outcome
  now persists an explicit `uncertain`/`escalated` safe stop (never guesses,
  never auto-retries, never fakes recovery); a new startup sweep
  (`reconcile_uncertain_intents`) catches the same case after a raw crash.
  (5) `message_sent` is now real capability AND authorization, not
  authorization alone - a real/hybrid case never reports a message as sent.
  46 tests in `tests/test_razorpay_test_mode.py` (was 31).
- 2026-09-04 (Iteration 17): two small corrections, offline only, diff
  confined to `razorpay_test_mode.py` + its tests. (1) `_live_post` now
  catches truncated/malformed/invalid-encoding response bytes too (was:
  timeout/OSError only) and funnels them into the same
  `ProviderActionUncertain` safe stop - verified against real bytes over a
  real local socket. (2) `handle_payment_link_paid_webhook` now requires the
  signed envelope's own `payment_link.status=="paid"` and
  `payment.status=="captured"`, and requires its amount/currency to agree
  with the persisted case (not just with each other). 58 tests (was 46).
- 2026-09-04 (Iteration 18): ONE live HYBRID attempt. Webhook-only loopback
  relay (`scripts/webhook_relay.py`) + an SSH reverse tunnel (`pinggy.io`;
  `localhost.run`'s tunnel domain was connection-reset by local Avast Web
  Shield - switched providers, nothing disabled/excluded) exposed publicly;
  verified end-to-end that only `POST /webhooks/razorpay-test` is reachable.
  `scripts/run_one_hybrid_case.py` drove ONE case through real Hermes+Gemini
  decisions -> **case-18** (`sub_demo_0004_8e781337`): `WAIT_FOR_PROVIDER_RETRY`
  then `CREATE_RECOVERY_LINK` authorized -> one real Razorpay Test Mode
  Payment Link created (`plink_TY2urjqVCjkjvB`). Per a mid-task Codex/user
  scope change, checkout was **intentionally not completed** - the demo does
  not require a paid live checkout; case-18 stays `active`/`counted=false`,
  awaiting payment, unedited. All three started processes were stopped by
  exact PID/port match; verified down.
- 2026-09-04 (Iteration 19, Phase A): closed the Iteration 18 review findings,
  offline only. `/health` now reports non-secret `payment_provider` /
  `payment_provider_test_mode_enabled` flags; `run_one_hybrid_case.py` fails
  closed (refuses `POST /demo/case`) unless both are the expected real values.
  `webhook_relay.py` hardened: a documented 64 KiB body ceiling, Content-Length
  validated (missing/malformed/negative/oversized all rejected before any
  read), a bounded body-read deadline, and logging reduced to method + fixed
  route category + status only - never the raw path/query/headers/body.
- 2026-09-04 (Iteration 19, Phase B): five read-only Neon views added via
  `scripts/init_neon.py` (`CREATE OR REPLACE VIEW` only, same single
  `ledger_state` JSONB row, no duplicated mutable data) - see HANDOFF.md for
  the exact view names and the live read-back evidence for case-18/case-11.
- **Production history note** (recorded per Codex, not implemented): Razorpay
  Test Mode supplies NO preloaded historical customer dataset. A real
  historical-payment view would require (1) a merchant-side mapping from
  SaaS user/subscription to the corresponding Razorpay customer/subscription
  ID, (2) a one-time backfill of past invoices/payments from Razorpay's API
  for that mapping, and (3) ongoing webhooks to keep it current - none of
  this exists yet; do not assume Test Mode alone provides it.
- **No freeze/suspension**: recording or recommending an account/access
  freeze or suspension is out of scope entirely - not "recommendation allowed
  under policy" as an earlier note implied. Plans/discounts stay suggestions
  only; no unilateral billing/plan/access change of any kind.
  Next: Codex review, then the three deferred exemplars - not another
  feature phase.

## Ordered next work

### 1. Prove one running case (Iteration 13 — DONE)

- [x] Resolve startup with bounded waits and sanitized diagnostics; regression test.
- [x] Verify actual Hermes mode, no scripted/direct-Gemini fallback.
- [x] Run one case, independently read case and decision evidence back from Neon.
- [x] Report actual final state, timing and attribution; safe failure is not recovery.
- [x] Supply repeatable launch command; preserve other Hermes installations.

### 2. Razorpay Test Mode: HYBRID slice (Iteration 16 — offline-tested; live pending)

- [x] Codex's verified fields/endpoints/limitations: `RAZORPAY_TEST_SLICE.md`.
- [x] Real recovery-link creation (Standard Payment Link, notify/reminders/
  partial disabled, stable `reference_id`) + real payment confirmation via a
  GENUINELY independent, request-scoped, both-records readback (Iteration 16
  fixed the earlier link-id-trusted-unverified defect), behind the existing
  `PaymentProvider` seam.
- [x] One genuine signed webhook route (`/webhooks/razorpay-test`), separate
  secret + code path from the simulated ingress; signature/dedup/correlation/
  mismatch/concurrency/uncertain-outcome rejection all offline-tested (46 tests).
- [x] Verify test credentials and enabled account features through an
  authorized bounded live test (Iteration 18): real key pair accepted, real
  link creation succeeded.
- [x] Tunnel the webhook route (webhook-only loopback relay, path-restricted
  by construction) - done (Iteration 18). Checkout itself intentionally NOT
  completed (Codex/user scope change); case-18 stays awaiting payment.
- [x] Provider Test Mode vs local simulation labelled (`evidence_mode`); a
  Payment Link never implies the original subscription settled/reactivated;
  native subscription-retry signals and historical-data retrieval remain
  explicitly NOT implemented (retry eligibility stays simulated).
- No real-money operations. Test Mode does not supply a ready-made historical
  customer dataset. Synthetic data only models plausible useful merchant/provider
  records, with explicit provenance; never invent unavailable bank/customer facts.

### 3. Hermes judgment skills and evidence (partly built; refine and prove)

- [ ] Review existing skill against these decisions; version changes and test them.
- Actual isolated Nous Hermes with Gemini as model, not merely renamed Gemini.
  Preserve pinned runtime, project-only home/skills, restricted tools and budgets.
- Show tool selection: current payment facts, prior recovery actions, optional
  additional history; explain why more evidence is needed and adapt after outcomes.
- Initial history: three months for this monthly-payment demo, not a universal
  optimum. ONE optional expansion to twelve months, not six then twelve. Report
  actual coverage/missing records; do not request expansion automatically.
- Confidence: uncalibrated judgment supported by completeness, freshness,
  consistency and relevance; explicitly note sparse/conflicting evidence.
  More history does not automatically improve confidence or prevent overfitting.
- Low-confidence/insufficient evidence: bounded expansion, then safe escalation
  if unresolved. Confidence never grants extra action permissions.
- Preserve deterministic authorization, consent/contact ownership, no duplicate
  actions, stopping rules, and strict output validation. Remove unsupported action
  advertisements rather than adding permissions just to satisfy model output.
- Plans/discounts are suggestions only; no unilateral billing/plan/access changes.
  No freeze/suspension action OR recommendation, under any policy - fully out
  of scope, not merely gated (corrects an earlier note that implied a
  policy-gated recommendation was allowed).
- Self-learning stays OFF. Logged improvement suggestions do not rewrite policy,
  prompts, skills or future customer treatment automatically.
- [ ] Document a defensible Hermes choice based on demonstrated tool use/isolation;
  do not claim these are unique to Hermes or that OpenClaw cannot do them.

### 4. Neon evidence contract (partly built; gap-check, not wholesale rewrite)

Iteration 19 added five read-only views (`case_summary`, `hermes_decisions`,
`recovery_actions`, `hermes_evidence`, `audit_timeline` - see HANDOFF.md) that
make most of the bullets below directly readable in Neon's browser instead of
raw JSON; the underlying data (still one JSONB snapshot) is unchanged. Not yet
covered: messaging evidence (no messaging adapter exists) and "next due time"
as its own column (derivable from `ScheduledWork`, not yet surfaced).

Application persists structured results, not unrestricted agent-written SQL.
Store/retrieve enough to reconstruct each case:

- [ ] Case/customer reference, event IDs/timestamps, source and simulation label.
- [ ] Concise decision rationale; evidence references, relevant facts, provenance,
  history coverage, requested expansion/reason, unavailable/conflicting evidence.
- [ ] Confidence band/value and basis, unresolved uncertainty, tool calls/results
  in bounded redacted form, model/runtime/skill version, latency and usage if known.
- [ ] Proposed action vs policy-authorized action vs actually executed action;
  policy reason, current state, escalation level/status, stop reason and next due time.
- [ ] Suggested plan/discount if present, approval needed and approval status;
  never confuse recommendation with application.
- [ ] When messaging exists: exact approved text actually sent, channel, time,
  delivery outcome/provider ID and response if available. Draft is not sent;
  sent is not delivered/read. Keep recipient details minimal and protected.
- [ ] Outcome, verified payment reference/amount, attribution, errors and safe stops;
  prevent duplicate recovery accounting. No secrets or hidden chain-of-thought.

### 5. Demo breadth and customer-facing output

- SUPERSEDED (2026-09-04, Iteration 14 prompt): the five-case plan below is
  replaced by THREE deferred exemplars — consistently on-time, consistently
  late, and mixed history with a justified optional history lookup. Sequence
  is strictly: startup corrections (done) -> Codex verification -> Razorpay
  Test Mode integration into the existing working case (`case-11`'s slice)
  -> these three exemplars. Do not implement new scenarios before that order.
- [ ] (deferred until after Razorpay) Build the three exemplars above per
  SCENARIO_MATRIX.md as it is updated for this narrower scope. History informs
  judgment; it is not a moral label or reason to bypass policy.
- [ ] Add Telegram test-chat output if time permits, after core/provider flow.
  Explicitly authorize recipient and external sends first; email is alternative,
  WhatsApp deferred. Log communication evidence as above.
- [ ] Save reproducible completed runs for recording rather than betting the
  five-minute video on unpredictable live latency. Show actual duration honestly.
- No dashboard polish required. Repo, isolated skills, Neon evidence and optional
  Telegram are sufficient showcase surfaces; existing UI remains optional.

### 6. Queue scheduling (proposed, not yet proven/implemented)

- [ ] Separate quick event intake from queued processing; one bounded worker for
  demo, sequential cases, due-work checks and safe restart/no duplicates.
- User proposed waking every three hours. Exact cadence is NOT locked; don't
  delay all new failures three hours by default. Preserve provider retry windows.
- Implement only after one reliable case and if time allows; don't claim a manual
  advance button is an automatic scheduler. No scale infrastructure for the demo.

### 7. Obsidian, then production/latency recommendations

- [ ] After working demo, set up a small Obsidian knowledge view: architecture,
  decisions, data provenance, policies/skills, case evidence, runbook and backlog.
  Repo documents remain canonical; avoid competing copies and secret ingestion.
- [ ] AFTER Obsidian, discuss/document latency and production-readiness suggestions
  only: timing breakdown, bounded model/tool calls, targeted data retrieval,
  queue/backpressure, rate limits, retries/idempotency, concurrency, durable audit,
  monitoring, privacy and failure recovery. Measure before proposing optimization.
- Graphify remains deferred; it does not replace decision handoffs. Do not install
  plugins, add dashboards or migrate to Docker solely for context management.

## Completion rule

For every item distinguish implemented, offline-tested, live-verified and deferred.
Codex reviews evidence before advancing the checkpoint. This file consolidates
discussion, not permission to implement the whole backlog in one Claude run.
