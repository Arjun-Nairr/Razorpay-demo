# Cross-Agent Handoff — current-state index

Last updated: 2026-09-04 (Asia/Dubai), Iteration 16. Branch
`feat/isolated-hermes-agent`, latest commit at bottom. This file stays
**under 300 lines**: it is an index, not a log. Detail lives in the linked
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

- Fix five Codex-reviewed defects in the Razorpay Test Mode HYBRID slice,
  offline only (this iteration). **No live Razorpay or Gemini call, no new
  Neon case, no public tunnel.** ONE live hybrid test remains authorized only
  after Codex reviews this correction.
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

Full narrative in the archive. Iteration 15 closed one leftover gap: the
lock-probe/first-read remaining-time calculation had a `max(2.0, …)` floor, so
a connect that had already spent the whole startup budget still handed the
next bounded step a **fresh** ~2s grace window. Fixed to `max(0.0, …)` - once
the budget is spent, what's left (including ~0) is what the next step gets,
never a re-granted window. Regression:
`test_no_fresh_grace_period_after_connect_exhausts_the_budget`.

## Razorpay Test Mode — HYBRID slice (Iterations 15–16, offline-tested only)

Per [`RAZORPAY_TEST_SLICE.md`](RAZORPAY_TEST_SLICE.md). The simulated SaaS
obligation, its 3/12-month history, and the accelerated failure/retry sequence
are **unchanged**. Only authorized recovery-link creation and payment
confirmation go through genuine Razorpay Test Mode calls when the
`hybrid_test_mode` provider is selected (`RAZORPAY_PROVIDER=hybrid_test_mode`,
independent of Hermes/Gemini mode; default remains `fake`, zero behavior
change). Native subscription-retry signals and historical-data retrieval are
**not** implemented - retry eligibility always stays simulated. Iteration 15's
first cut is archived; Iteration 16 fixed five Codex-reviewed defects in it:

1. **Independent payment-to-link verification.** The old `verify_capture`
   fetched only the payment and copied the webhook's *claimed* link id
   straight into "verified" evidence. `RazorpayTestModeAdapter.verify_link_payment`
   now fetches BOTH the Payment Link and the payment, requires the link's own
   fetched `id`/`reference_id`/`status`/`amount`/`currency` to match, the
   payment's own fetched `id`/`status`/`amount`/`currency` to match, **and**
   the link's own `payments` list (Razorpay's documented per-link payment
   history) to contain this payment id, itself `captured` at the expected
   amount - the actual evidence one belongs to the other, not two
   separately-plausible records.
2. **No silent fallback on incomplete evidence.** A missing/wrong-typed
   currency (or any other required id/status/amount) now fails the match
   outright - it is never treated as "no evidence" and waved through with a
   `capture.currency or case.currency` fallback (removed). The webhook
   envelope's own required fields are validated by type before use, and a
   link/payment amount or currency that contradicts each other within the
   SAME signed envelope is rejected before any provider call.
3. **Request-scoped verification, once.** The mutable `_pending[obligation_id]`
   dict is gone. `verify_link_payment(claim: LinkPaymentClaim)` takes an
   immutable, per-call claim and returns fresh evidence from its own two
   fetches only - concurrent deliveries for the same obligation cannot mix.
   `RazorpayWebhook.pre_verified_capture` carries that evidence straight into
   `engine.receive`, so `_on_captured` skips its own `record_capture`/
   `verify_capture` round trip for `REAL_TEST_MODE` (one provider fetch pair
   per webhook, not two) while every ledger validation (dedup, terminal-state,
   version, atomic finalization) still runs unchanged.
4. **Safe stop for uncertain link creation.** `create_recovery_link` now
   raises `ProviderActionUncertain` (not a bare `RuntimeError`) on an
   ambiguous POST or a malformed response; `engine.run()` catches it and
   persists an explicit `apply_action_intent_uncertain` transition - intent
   status `uncertain`, case `escalated`/`unrecovered` - never recovered, never
   a replacement link, never a silent automatic retry. A NEW
   `RecoveryEngine.reconcile_uncertain_intents()` sweep (wired into
   `runtime.build_app`) finds any intent still `pending` after a genuine crash
   (not just a caught exception) and applies the same safe stop on startup.
5. **Authorization ≠ delivery.** `message_sent` is no longer
   `result.message_authorized` verbatim. The real/hybrid provider exposes
   `message_delivery_capable = False` (no messaging adapter exists in this
   slice); the engine now sends `message_sent = message_authorized AND
   capable`, so a real/hybrid case never reports a message as sent (and its
   contact counters never move) regardless of what policy authorized. The
   simulated `FakeRazorpayAdapter` has no such attribute (defaults `True`) -
   its existing, tested "simulated sending" behavior is unchanged.

- **`HybridPaymentProvider`**: composes the existing `FakeRazorpayAdapter`
  (retry eligibility only) with the real adapter (link creation + capture
  confirmation). `/demo/*`'s `set_retry_eligibility` is forwarded unchanged.
- **New webhook route**: `POST /webhooks/razorpay-test` (mounted only when
  `real_webhook_secret` is configured) verifies a genuine `payment_link.paid`
  envelope against a **separate** secret via **separate** code
  (`razorpay_test_mode.handle_payment_link_paid_webhook`) - signature over the
  untouched raw body first, then event-id/envelope/contradiction checks, then
  this case's own persisted link-id correlation, then the ONE independent
  provider readback above, and only then `engine.receive`. The simulated
  `/webhooks/razorpay` route and its secret are completely untouched.
- **Tunnel guidance (not started this iteration)**: expose **only**
  `POST https://<tunnel>/webhooks/razorpay-test` - never the whole app (no
  `/demo/*`, no `/cases/*`, no docs). Example `cloudflared` ingress rule:
  ```yaml
  ingress:
    - hostname: <your-tunnel-host>
      path: ^/webhooks/razorpay-test$
      service: http://localhost:8000
    - service: http_status:404
  ```
  A raw `ngrok http 8000` forwards the whole port - do not use that alone;
  pair it with a reverse proxy that 404s everything else, or use a tool with
  native path-restricted ingress.
- **User-only setup, still pending**: create a Razorpay **Test Mode** account/
  key pair (`rzp_test_...`); set `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` in
  `.env`; add a webhook in the Razorpay Test Mode dashboard pointing at the
  tunnel URL above, subscribed to **`payment_link.paid`** only, and set its
  secret as `RAZORPAY_WEBHOOK_SECRET` in `.env`; set
  `RAZORPAY_PROVIDER=hybrid_test_mode` and, only when ready to allow real
  calls, `RAZORPAY_TEST_MODE_ENABLED=1`. Manual Test Mode checkout (opening
  the link and paying with a Razorpay test card) remains a user step.

## Verified evidence

- **Offline**: `python -m pytest -q --ignore=tests/test_hermes_agent.py` ->
  **284 passed, 3 skipped** (was 269; `tests/test_razorpay_test_mode.py`
  rewritten to 46 tests - the old 31 plus new coverage for all five defects,
  net +15). Real-Hermes harness `python -m pytest -q tests/test_hermes_agent.py`
  -> **33 passed** (unaffected; confirms the type/protocol additions stay
  backward compatible). `compileall` + `git diff --check` clean.
- New coverage per defect: (1) unrelated-payment rejection (valid payment,
  absent from the link's own `payments` list), link-id echo mismatch,
  reference-id mismatch, wrong-status-on-link rejection; (2) missing currency
  on either fetched record, mismatched amount/currency/status, malformed
  (non-dict) readback responses, malformed webhook entity types, contradictory
  same-envelope amount/currency; (3) exactly-one-fetch-pair-per-call, a
  50ms-skewed two-thread concurrent-delivery test proving evidence never
  mixes, and a handler+engine single-fetch regression; (4) ambiguous POST and
  malformed-response uncertain-state persistence, no-auto-retry, restart
  reconciliation after both a caught exception and a raw crash, and a
  provider-success-before-local-persistence crash case; (5) real/hybrid
  `message_sent` always `False` with contact counters unmoved even when
  policy authorized a message, vs. the simulated path's unchanged behavior.
  Plus the retained defect-independent coverage: signature rejection,
  duplicate event id, duplicate payment across deliveries, out-of-order
  delivery on a terminal case, and restart correlation.
- **`case-11` preserved**: re-read read-only this iteration (direct `psycopg`,
  no writes) to confirm it still loads cleanly under the new optional
  dataclass fields - `state=recovered`, `attribution=hermes_assisted`,
  `recovered_minor=1,000,000`, unchanged. No new Neon case; no live
  Razorpay/Gemini call; no public tunnel.

## Inspecting the persisted proof

- Neon SQL editor, schema `hermes_demo`:
  [`sql/neon_demo_inspect.sql`](sql/neon_demo_inspect.sql). User-run flow:
  [`scripts/neon_proof.py`](scripts/neon_proof.py).

## Repeatable launch

```
.\scripts\run_demo.ps1 -Mode hermes
```

Payment provider defaults to `fake` (unchanged). To wire the hybrid provider
once credentials + one live test are authorized, set `RAZORPAY_PROVIDER=
hybrid_test_mode` (+ the three `RAZORPAY_*` secrets) before launch; leave
`RAZORPAY_TEST_MODE_ENABLED` unset/`0` until Codex has reviewed this slice.

## Blockers

- None blocking further offline work. Live hybrid verification is blocked on:
  (1) Codex review of this slice, (2) the user provisioning a Razorpay Test
  Mode key pair + webhook, (3) a path-restricted tunnel actually being started
  (deliberately not done this iteration).
- `hermes` mode remains manual-control only (see backlog).

## Next action

Codex review of the Iteration 16 corrections (offline evidence above). Then,
per the backlog: ONE authorized live hybrid test (real Test Mode link ->
manual checkout -> real webhook -> Neon evidence), followed by the three
deferred exemplars (on-time / late / mixed-history) - not before. Keep future
`HANDOFF.md` updates under 300 lines.

## Working-document links

- History: [`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md)
- Plan map: [`IMPLEMENTATION_BACKLOG.md`](IMPLEMENTATION_BACKLOG.md)
- Build contract: [`IMPLEMENTATION_SPEC.md`](IMPLEMENTATION_SPEC.md)
- Policy: [`POLICY_SPEC.md`](POLICY_SPEC.md)
- Razorpay Test Mode contract: [`RAZORPAY_TEST_SLICE.md`](RAZORPAY_TEST_SLICE.md)
- Neon queries: [`sql/neon_demo_inspect.sql`](sql/neon_demo_inspect.sql)
- Isolated-Hermes research: [`HERMES_ISOLATED_AGENT_RESEARCH.md`](HERMES_ISOLATED_AGENT_RESEARCH.md)

<!-- latest verified commit: see `git log -1` on feat/isolated-hermes-agent -->
