# Cross-Agent Handoff — current-state index

Last updated: 2026-09-04 (Asia/Dubai), Iteration 15. Branch
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

- Implement + offline-test the Razorpay Test Mode HYBRID slice (this
  iteration). **No live Razorpay or Gemini call, no new Neon case, this
  iteration.** ONE live hybrid test is authorized only after Codex review.
- Earlier authorization (still valid, unchanged): local startup fixes and the
  ONE already-completed real Gemini-backed Hermes case against the existing
  `hermes_demo` Neon schema (`case-11` - preserved, re-verified unchanged).
- **Never** print/commit secrets, connection strings, raw secret-bearing
  errors, or `.env`. No real payments, external customer messages, Docker
  migration, DB redesign, security-setting changes, or edits to other Hermes
  installations. No public tunnel started this iteration.

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

## Razorpay Test Mode — HYBRID slice (Iteration 15, offline-tested only)

Per [`RAZORPAY_TEST_SLICE.md`](RAZORPAY_TEST_SLICE.md). The simulated SaaS
obligation, its 3/12-month history, and the accelerated failure/retry sequence
are **unchanged**. Only authorized recovery-link creation and payment
confirmation now go through genuine Razorpay Test Mode calls when the
`hybrid_test_mode` provider is selected (`RAZORPAY_PROVIDER=hybrid_test_mode`,
independent of Hermes/Gemini mode; default remains `fake`, zero behavior
change). Native subscription-retry signals and historical-data retrieval are
**not** implemented - retry eligibility always stays simulated.

- **`RazorpayTestModeAdapter`** (`src/hermes/razorpay_test_mode.py`): disabled
  by default (`enabled=False`; set via `RAZORPAY_TEST_MODE_ENABLED=1`) - every
  method that would call the network raises instead. Rejects any key id not
  starting with `rzp_test_` at construction, before any request is possible.
  `create_recovery_link` calls `POST /v1/payment_links` with the CASE's
  trusted `amount_minor`/`currency` (never the model's), `accept_partial:
  false`, `notify: {sms:false, email:false}`, `reminder_enable: false`, and a
  stable `reference_id` (`hermes-<case_id>`, ≤40 chars, checked). On an
  ambiguous POST outcome (timeout/connection reset) it never mints a second
  reference and re-posts - it raises a clear "reconcile via the dashboard"
  error instead. `verify_capture` does an **independent** `GET
  /v1/payments/{id}` readback - never trusts the caller's claimed
  amount/currency/status; any fetch failure or non-`captured` status rejects.
- **`HybridPaymentProvider`**: composes the existing `FakeRazorpayAdapter`
  (retry eligibility only) with the real adapter (link creation + capture
  confirmation). `/demo/*`'s `set_retry_eligibility` is forwarded unchanged.
- **Attribution correlation fix**: a real payment's own id (`pay_...`) never
  equals the link id (`plink_...`) it was paid through, unlike the simulated
  fake's reference-equals-payment-id shortcut. `CaptureInfo`/`CaptureCommand`
  gained an optional `link_id`; `apply_capture`'s attribution check now
  accepts either the old direct match (simulated, unchanged) or a `link_id`
  match (real) - zero behavior change for every existing test/case.
- **New webhook route**: `POST /webhooks/razorpay-test` (mounted only when
  `real_webhook_secret` is configured) verifies a genuine `payment_link.paid`
  envelope against a **separate** secret via **separate** code
  (`razorpay_test_mode.handle_payment_link_paid_webhook`) - signature over the
  untouched raw body first, then event id, envelope shape, this case's own
  persisted link-id correlation, the independent provider readback, and only
  then `engine.receive`. The simulated `/webhooks/razorpay` route and its
  secret are completely untouched. `ActionIntent`/audit gained an optional
  `url` field (the checkout link, distinct from its `reference` id).
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
  **269 passed, 3 skipped** (was 237; +31 new
  `tests/test_razorpay_test_mode.py` + 1 startup-grace regression). Real-Hermes
  harness `python -m pytest -q tests/test_hermes_agent.py` -> **33 passed**
  (unaffected by this iteration; confirms the protocol/type additions above
  are backward compatible). `compileall` + `git diff --check` clean.
- New coverage: live-key rejection, disabled-by-default, disabled
  notifications/reminders/partial payments, stable/idempotent reference id,
  ambiguous-POST no-retry, independent-readback confirm/reject (status,
  amount, currency), signature rejection, malformed envelope, unrecognised
  reference, unknown case, link-mismatch rejection, duplicate event id,
  duplicate payment across event ids, out-of-order delivery on a terminal
  case, and restart correlation (fresh engine + fresh adapter over the same
  durable store).
- **`case-11` preserved**: re-read read-only this iteration (direct `psycopg`,
  no writes) to confirm it still loads cleanly under the new optional
  dataclass fields - `state=recovered`, `attribution=hermes_assisted`,
  `recovered_minor=1,000,000`, unchanged. No new Neon case; no live
  Razorpay/Gemini call.

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

Codex review of the Iteration 15 Razorpay HYBRID slice (offline evidence
above). Then, per the backlog: ONE authorized live hybrid test (real Test
Mode link -> manual checkout -> real webhook -> Neon evidence), followed by
the three deferred exemplars (on-time / late / mixed-history) - not before.
Keep future `HANDOFF.md` updates under 300 lines.

## Working-document links

- History: [`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md)
- Plan map: [`IMPLEMENTATION_BACKLOG.md`](IMPLEMENTATION_BACKLOG.md)
- Build contract: [`IMPLEMENTATION_SPEC.md`](IMPLEMENTATION_SPEC.md)
- Policy: [`POLICY_SPEC.md`](POLICY_SPEC.md)
- Razorpay Test Mode contract: [`RAZORPAY_TEST_SLICE.md`](RAZORPAY_TEST_SLICE.md)
- Neon queries: [`sql/neon_demo_inspect.sql`](sql/neon_demo_inspect.sql)
- Isolated-Hermes research: [`HERMES_ISOLATED_AGENT_RESEARCH.md`](HERMES_ISOLATED_AGENT_RESEARCH.md)

<!-- latest verified commit: see `git log -1` on feat/isolated-hermes-agent -->
