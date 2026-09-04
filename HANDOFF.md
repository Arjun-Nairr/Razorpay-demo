# Cross-Agent Handoff — current-state index

Last updated: 2026-09-04 (Asia/Dubai), Iteration 17. Branch
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

- Apply two small Codex-reviewed corrections to the Razorpay Test Mode HYBRID
  slice, offline only (this iteration). **No live Razorpay or Gemini call, no
  new Neon case, no public tunnel.** ONE live hybrid test remains authorized
  only after Codex reviews this correction.
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

## Razorpay Test Mode — HYBRID slice (Iterations 15–17, offline-tested only)

Per [`RAZORPAY_TEST_SLICE.md`](RAZORPAY_TEST_SLICE.md). The simulated SaaS
obligation, its 3/12-month history, and the accelerated failure/retry sequence
are **unchanged**. Only authorized recovery-link creation and payment
confirmation go through genuine Razorpay Test Mode calls when the
`hybrid_test_mode` provider is selected (`RAZORPAY_PROVIDER=hybrid_test_mode`,
independent of Hermes/Gemini mode; default remains `fake`, zero behavior
change). Native subscription-retry signals and historical-data retrieval are
**not** implemented - retry eligibility always stays simulated. Iteration 15's
first cut and Iteration 16's five-defect correction are archived (independent
payment-to-link verification, no silent evidence fallback, request-scoped
single verification, safe uncertain-outcome persistence, authorization ≠
delivery). Iteration 17 closed two more small gaps in that correction:

1. **Malformed/truncated raw POST responses now reach the same safe path.**
   `_live_post` caught timeout/`OSError`, but not a truncated response body
   (`http.client.IncompleteRead`), invalid byte encoding, or malformed JSON
   after the request was sent - those propagated uncaught instead of
   becoming `ProviderActionUncertain`. Every failure from "request sent"
   onward - transport, read, or decode - now funnels into the same
   `_AmbiguousCompletion` → `ProviderActionUncertain` → `uncertain`/
   `escalated` path as an ambiguous timeout. Verified against REAL bytes over
   a real local socket (a `Content-Length`-truncated response, invalid UTF-8,
   and syntactically-broken JSON), not an injected decoded dict.
2. **Signed-envelope agreement, not just internal consistency.**
   `handle_payment_link_paid_webhook` now requires the envelope's own claimed
   `payment_link.status == "paid"` and `payment.status == "captured"`
   (previously only checked by the provider readback, not the envelope
   itself), and requires the envelope's (mutually-agreeing) amount/currency
   to also match the **persisted case obligation** - two entities that agree
   with each other on the wrong number are now rejected before any provider
   call, not just entities that disagree with each other. The independent
   provider readback (`verify_link_payment`) still re-confirms all of this
   against the provider's own records; this is an earlier, cheaper reject,
   not a replacement for it.

**Fixture-vs-provider verification**: the Payment Link entity's `payments`
array field names used in the test fixtures (`payment_id`, `amount`,
`status`) were checked against Razorpay's own documented Create-Standard-Link
response description (fetched live via `WebFetch` this iteration) - confirmed
matching. This confirms the fixture *shape* agrees with the documented
contract; it is not a substitute for the one still-pending live Test Mode
call, which alone proves actual API behavior.

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
  **296 passed, 3 skipped** (was 284; `tests/test_razorpay_test_mode.py` grew
  from 46 to 58 tests). Real-Hermes harness
  `python -m pytest -q tests/test_hermes_agent.py` -> **33 passed**
  (unaffected - this iteration touched only `razorpay_test_mode.py` and its
  tests). `compileall` + `git diff --check` clean; diff confined to those two
  files.
- New coverage this iteration: (1) a local `http.server` fixture producing
  REAL truncated/invalid-encoding/malformed-JSON response bytes over a real
  socket, tested both directly against `_live_post` and end-to-end through
  `engine.run()` to the durable `escalated`/`uncertain` outcome, plus a
  well-formed-bytes sanity check; (2) missing/wrong `payment_link.status` and
  `payment.status` in the signed envelope, an envelope whose link/payment
  entities agree with each other on an amount or currency that disagrees with
  the persisted case (rejected before any provider call), and a preserved
  fully-agreeing valid-event path.
- Ledger/persistence code was **not touched** this iteration (only the
  Razorpay adapter/webhook module and its tests) - `case-11` and the
  snapshot schema are structurally unaffected; no fresh readback was needed
  to confirm that. No new Neon case; no live Razorpay/Gemini call; no public
  tunnel.

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

Codex review of the Iteration 17 corrections (offline evidence above). Then,
per the backlog and per this prompt's own closing instruction: webhook/tunnel
setup and ONE manual Test Mode checkout - not another feature phase. The
three deferred exemplars (on-time / late / mixed-history) still wait until
after that one verified hybrid flow. Keep future `HANDOFF.md` updates under
300 lines.

## Working-document links

- History: [`docs/archive/HANDOFF_full_2026-09-04.md`](docs/archive/HANDOFF_full_2026-09-04.md)
- Plan map: [`IMPLEMENTATION_BACKLOG.md`](IMPLEMENTATION_BACKLOG.md)
- Build contract: [`IMPLEMENTATION_SPEC.md`](IMPLEMENTATION_SPEC.md)
- Policy: [`POLICY_SPEC.md`](POLICY_SPEC.md)
- Razorpay Test Mode contract: [`RAZORPAY_TEST_SLICE.md`](RAZORPAY_TEST_SLICE.md)
- Neon queries: [`sql/neon_demo_inspect.sql`](sql/neon_demo_inspect.sql)
- Isolated-Hermes research: [`HERMES_ISOLATED_AGENT_RESEARCH.md`](HERMES_ISOLATED_AGENT_RESEARCH.md)

<!-- latest verified commit: see `git log -1` on feat/isolated-hermes-agent -->
