# Cross-Agent Handoff

Last updated: 2026-09-03 (Asia/Dubai)

## Goal and scope

Prepare and build a selection-quality AI Revenue Recovery Agent demo using the
requirements in `PROJECT_BRIEF.md`.

## Current state

- Shared workspace and GitHub repository initialized.
- Original brief and official challenge image normalized into
  `PROJECT_BRIEF.md`.
- Case 1 in-memory foundation is implemented, tested, committed, and pushed on
  `feat/case-1-recovery-slice`.
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
- The imported 2026-09-03 architecture discussion has been reconciled into
  `IMPLEMENTATION_SPEC.md` and `HERMES_RAZORPAY_RESEARCH.md`.
- Case 3 (insufficient-funds adaptation and attribution) in-memory slice is
  implemented, tested, committed, and pushed on `feat/case-3-adaptation`: the
  expected-state capture guard is closed, the wait -> failed-retry -> changed-
  strategy -> recovery-link -> `hermes_assisted` path is proven end to end
  through `receive`/`run`/`inspect`, and Case 1's 36-test suite remains green.
- Status: Runtime spike (`IMPLEMENTATION_SPEC.md` slice 2) complete on
  `feat/hermes-runtime-spike`. **Fallback path shipped**: a direct
  google-genai (Gemini 3.7 Flash) `HermesStrategist` behind the existing
  `Strategist` protocol, offline-tested; the Hermes-Agent library path was
  not taken (Windows `pip`/`git` long-path failure on the pinned commit).
  Next: the user runs `scripts/hermes_smoke.py` with a real key, then Codex
  reviews, then slice 3 (FastAPI signed simulated ingress).

## Iteration 06 — Runtime spike: isolated Gemini strategist (fallback path)

- Branch: `feat/hermes-runtime-spike` off `feat/case-3-adaptation` HEAD
  `c6a4f23`. Pushed with upstream set. Never force-pushed.
- **Path shipped: FALLBACK (direct google-genai).** The primary Hermes-Agent
  path was triggered out within its ~55-min budget (~15 min in):
  `pip install "hermes-agent @ git+https://github.com/NousResearch/hermes-agent@<SHA>"`
  fails on this Windows machine - pip's internal `git clone` cannot pass
  `core.longpaths=true`, and the repo's `website/i18n/...` docs tree exceeds
  `MAX_PATH` (checkout aborts with "Filename too long"). A command-scoped
  `git -c core.longpaths=true clone --depth 1 --branch v2026.8.31` *does*
  work, but a plain `pip install` (what the pinned-URL contract needs) does
  not, and forcing it needs a persistent global `git config` change plus
  OS-level long-path support. Per the slice-2 prompt's sanctioned fallback,
  shipped the smallest direct google-genai adapter instead, inheriting the
  full contract (schema validation, timeout, <=1 repair, same raised types).
- Pinned SHA recorded for a future Hermes-Agent retry: tag `v2026.8.31`
  **commit** `29112bef099274229cadff79cdff7bf7b99c4b77` (the annotated-tag
  object is `6e8f8418e6378eb2617e4de074e13dedd091b8af`, which is *not* a
  commit - do not put that in a `git+...@` URL). `hermes-agent` version at
  that tag is `0.21.0`, `requires-python >=3.11,<3.14`.
- No dependency added to default/`dev`. New optional extra `[gemini]`
  (`google-genai>=1,<3`) - named `gemini`, not `hermes`, since the Hermes
  path did not ship; deviation from deliverable 1's `hermes` key, recorded
  here.

### Changed files (exactly these + this handoff)

- `pyproject.toml` - new `[project.optional-dependencies] gemini` extra;
  comment block records the Hermes-Agent pin + Windows caveat for a retry.
- `src/hermes/hermes_strategist.py` - **new**, additive. `HermesStrategist`
  implements `Strategist.propose`. `google.genai` is imported lazily inside
  `_build_real_transport`, so offline tests need no SDK. `parse_proposal`
  does strict *structural* JSON validation (shape/keys/types/enum/range);
  content rules (URL/currency/provider-id) stay with the engine's
  `_validate_proposal`. `_call` runs each model call in a one-worker
  `ThreadPoolExecutor` under `timeout_s` (default 60, configurable) and
  raises `TimeoutError`. Invalid first reply -> exactly one repair call
  (carrying the validation error) -> still invalid -> `InvalidProposal`.
  `StrategistRunMeta` (contained; not wired to the ledger) holds model,
  `prompt_version`, `latency_ms`, `repair_used`, `validation_result`,
  bounded `raw_response`, `usage`; `cost_usd` is `None` (Gemini API returns
  no per-call cost). `ISOLATION_PROFILE` records the switch settings a
  real-Hermes swap must reproduce. Model default `gemini-3.7-flash`.
- `tests/test_hermes_strategist.py` - **new**, 17 offline tests, stub
  transport, zero network / zero key: valid JSON -> typed proposal;
  6 structural-invalid inputs rejected; malformed -> exactly one repair
  then `InvalidProposal`; repair-succeeds -> typed proposal; zero repair
  budget -> raises on first; blank `message_intent` -> `None`; over-budget
  call -> `TimeoutError`; `ISOLATION_PROFILE` asserted; prompt excludes
  case/obligation id + amount; offline path needs no SDK; not wired into
  `engine.py`; real transport with no `GEMINI_API_KEY` -> `RuntimeError`.
- `scripts/hermes_smoke.py` - **new**. Builds a Case 3 insufficient-funds
  snapshot, runs one real `HermesStrategist` decision, prints run metadata
  + proposal as JSON. Reads `GEMINI_API_KEY` from env, never prints it.
  Exit 0 valid / 1 failed (type printed) / 2 no key.
- `.env.example` - **new**. Redacted `GEMINI_API_KEY=` only.
- `.gitignore` - adds `.hermes_profile/`, `.hermes_home/`.

### Deviations from `HERMES_RAZORPAY_RESEARCH.md` / the prompt

- **Library not used.** Direct google-genai instead of the Hermes `AIAgent`
  harness (environment blocker above). The research doc explicitly sanctions
  this: "If the spike fails within its timebox, retain the `Strategist` seam
  and use the smallest verified Gemini adapter necessary."
- **Validation is stdlib, not Pydantic.** Kept the offline suite installable
  with zero packages in any environment and consistent with the engine's
  hand-rolled `_validate_proposal`. Structural coverage is equivalent.
- **Isolation is a declared contract, not live config.** There is no
  `AIAgent` to pass `skip_memory` / `enabled_toolsets` to; a bare
  google-genai client has none of those capabilities. `ISOLATION_PROFILE`
  + its test is the checklist a real-Hermes swap must honour.
- **Metadata contained.** `StrategistRunMeta` is exposed on the strategist,
  not written into `AI_PROPOSAL` audit rows - `types.py` / `engine.py` /
  `adapters.py` / the ledger are untouched, as required.
- Optional-extra key is `gemini`, not `hermes` (see above).

### Verification

- `python -m pytest -q` -> **74 passed** (57 unchanged: 36 Case 1 + 21
  Case 3, both suites byte-for-byte untouched; + 17 new offline spike tests).
- `python -m compileall -q src tests scripts` -> clean.
- `git diff --check` -> clean (only CRLF-on-checkout warnings).
- Staged diff scanned: exactly the six files above + `HANDOFF.md`; no
  `types/engine/adapters/protocols.py`, no doc except this file; no secret
  literals (`grep` for `AIza…` / key / secret / PEM patterns - none).
- Real Gemini round-trip: **NOT run here** (no key in this environment, by
  design). Pending: user runs `pip install ".[gemini]"`, sets
  `GEMINI_API_KEY`, runs `python scripts/hermes_smoke.py`, pastes the JSON
  output below.

  ```
  (paste hermes_smoke.py output here)
  ```

### Remaining limitations

- The one real model call is unproven until the user runs the smoke script;
  the real-transport shape (`client.models.generate_content`, `resp.text`,
  `resp.usage_metadata`) was verified against `google-genai 2.22.0` in an
  isolated venv but not exercised end to end.
- The timeout worker thread cannot be force-killed; on timeout it finishes
  in the background and its result is discarded (fine for one short call).
- `HermesStrategist` is not wired into `RecoveryEngine`; wiring + threading
  `StrategistRunMeta` into `AI_PROPOSAL` audit rows is a later task.
- If Hermes-Agent is still wanted, its Windows install needs
  `git config --global core.longpaths true` (+ OS long-path support) or a
  pre-clone-then-`pip install ./dir` flow; revisit only if the library's
  skills/curator features are actually needed for the demo.

### Exact next action

1. User: `pip install ".[gemini]"`, set `GEMINI_API_KEY`, run
   `python scripts/hermes_smoke.py`, paste output into the block above.
2. Codex: review this iteration (diff `feat/case-3-adaptation..feat/hermes-runtime-spike`)
   and the smoke output; decide whether the fallback Gemini adapter is
   sufficient for the demo or a Hermes-Agent retry is warranted.
3. Then: slice 3 - FastAPI signed simulated ingress (locally signed
   Razorpay-shaped fixtures, raw-body verification, dedup, engine
   projections / demo controls).

## Architecture reconciliation — 2026-09-03

### Adopted

- Position Hermes as the merchant-side recovery operator above Razorpay, not a
  replacement for provider retries, notifications, or payment truth.
- Keep Case 1 as plumbing proof and make Case 3 insufficient-funds adaptation
  the next intelligence slice.
- Keep all five golden scenarios; require only one real/hybrid Test Mode path.
- Use Hermes Agent behind the existing `Strategist` protocol with Gemini 3.7
  Flash, a fresh isolated agent per decision, no tools for v1, strict local
  schema validation, and deterministic policy authority.
- Separate `provider_self_recovered`, `hermes_assisted`, `merchant_manual`, and
  `unrecovered` attribution.
- FastAPI owns raw-body signature verification; Streamlit reads stable API
  projections; Neon is the target shared ledger with SQLite as deadline
  fallback.
- Treat Payment Links as separately correlated alternate collections, not as
  automatic subscription-invoice settlement.

### Corrections to the imported handoff

- Embedded Hermes `AIAgent` does not document provider-enforced output schemas;
  parse/validate JSON locally and fail closed with at most one repair attempt.
- `skip_memory=True` alone is insufficient isolation; use a dedicated profile,
  no tools/context/skills/curator behavior, and a pinned tested Hermes commit.
- Real Razorpay card retries occur over calendar days and cannot be accelerated;
  accelerated outcomes are explicitly simulated.
- Do not replace the completed Case 1 slice or reduce the five agreed scenarios.
- Do not mechanically edit every repository file; only affected contracts,
  implementation, tests, and documentation should change.

### Updated documents

- `PROJECT_BRIEF.md`
- `FOUNDATION_ARCHITECTURE.md`
- `POLICY_SPEC.md`
- `SCENARIO_MATRIX.md`
- `TOOLING_RESEARCH.md`
- `RAZORPAY_DEVTOOLS_RESEARCH.md`
- `HERMES_RAZORPAY_RESEARCH.md` (new)
- `IMPLEMENTATION_SPEC.md` (new)
- `README.md`
- `CLAUDE.md`
- `HANDOFF.md`

No source code, tests, or dependencies were changed during architecture
reconciliation. Claude Code remains the sole implementation agent.

### Exact next action

Codex issues the first reconciled Claude prompt: implement the Case 3
adaptation-and-attribution slice through the existing `receive` / `run` /
`inspect` public seam, including action intents/outcomes, communication
ownership, policy limits, attribution, the outstanding expected-state capture
guard, and golden tests. The Hermes runtime
spike follows as the next isolated slice so dependency risk cannot destabilize
the domain foundation.

## Iteration 05 — Case 3: adaptation and attribution slice

- Branch: `feat/case-3-adaptation` (new, off `feat/case-1-recovery-slice`
  HEAD `d546f7e`).
- Docs commit: `d9ae884` (`docs: reconcile Hermes recovery architecture` -
  the working-tree documentation reconciliation already present when this
  iteration started; reviewed, preserved verbatim, committed first).
- Implementation commit: `adc69ff`
  (`feat(engine): Case 3 insufficient-funds adaptation and attribution slice`,
  includes this handoff). Handoff commit: `this commit`.
- `origin` unchanged; branch pushed with upstream set
  (`git push -u origin feat/case-3-adaptation`).
- No dependencies added. `RULES.md`/schema/dashboard/FastAPI/Neon/Hermes/
  Gemini untouched - purely the in-memory domain module and its tests.

### Changed files

- `src/hermes/types.py` - `Attribution` StrEnum (`provider_self_recovered`,
  `hermes_assisted`, `merchant_manual`, `unrecovered`); `RazorpayWebhook`
  gains `customer_notify`/`consent`/`reachable_channel`/`evidence_mode`
  (all defaulted, Case 1 call sites unaffected); `StrategyProposal` gains
  `message_intent`; `StrategySnapshot` gains retry-outcome, communication,
  limit-remaining, and prior-proposal/-policy evidence fields;
  `PolicyDecision` gains `message_authorized`; `Case`/`CaseSnapshot` gain
  communication ownership/consent/channel, `retry_outcome_recorded`,
  message/link/action counters, `last_contact_time`, `link_references`,
  `attribution`, and last-proposal/-policy evidence; new `ActionIntent`
  ledger record and `ActionIntentOutcomeCommand`; `IntakeCommand` gains the
  merchant-fact and `evidence_mode` fields; `CaptureCommand` gains
  `expected_state` enforcement wiring (`apply_capture` now uses it - see
  below) and `evidence_mode`; `ApplyResult` gains action-intent/idempotency/
  execute/message fields; new `ActionIntentProjection`; `CaseProjection`
  extended with strategy/action state, communication ownership, attribution,
  per-case recovered amount, and action intents.
- `src/hermes/protocols.py` - `PaymentProvider.create_recovery_link`;
  `Ledger.apply_action_outcome`.
- `src/hermes/adapters.py` - `FakeRazorpayAdapter.create_recovery_link`
  (deterministic, idempotency-key-keyed simulated Payment Link reference);
  `ScriptedStrategist`'s script re-keyed to `(reason, retry_outcome_recorded)`
  so the SAME reason code produces a DIFFERENT proposal once a failed retry
  is recorded (`insufficient_funds` -> `WAIT_FOR_PROVIDER_RETRY` then
  `CREATE_RECOVERY_LINK`); `InMemoryLedger.apply_intake` now wakes a
  `waiting` case immediately on a distinct subsequent failed event (records
  `RETRY_OUTCOME_RECORDED`, cancels the stale pending re-evaluation,
  enqueues exactly one due-now item - never a second case, never doubled
  pending work) and seeds merchant facts only at case creation;
  `apply_evaluation` now also authorizes `CREATE_RECOVERY_LINK` (persists a
  durable, idempotency-keyed `ActionIntent` with status `pending` BEFORE any
  effect runs; a replayed idempotency key returns the existing intent and
  signals no re-execution) and preserves `last_proposal_action`/
  `last_policy_outcome` on every cycle; new `apply_action_outcome`
  (idempotent - an already-`executed` intent replayed is a no-op) records the
  fake executor's reference, adds it to the case's `link_references`, and
  updates message counters/cooldown only when policy actually authorized the
  message; `apply_capture` **now compares `expected_state` in addition to
  `expected_version`**, rejecting `stale_case_state` before any money is
  counted (the gap `IMPLEMENTATION_SPEC.md` named), and computes
  `Attribution` deterministically (`payment_id` correlated to the case's
  `link_references` -> `hermes_assisted`; otherwise ->
  `provider_self_recovered`); `apply_strategist_failure`'s terminal
  escalation now also records `Attribution.UNRECOVERED`.
- `src/hermes/engine.py` - `MAX_ACTIONS_PER_CASE=3`,
  `MAX_MESSAGES_PER_CASE=2`, `MESSAGE_COOLDOWN_HOURS=24`,
  `MAX_LINKS_PER_CASE=1` (POLICY_SPEC.md defaults, configuration not prompt
  text); `_validate_proposal` rejects a blank `message_intent` or one
  containing a URL/currency symbol before policy ever sees it;
  `authorize()` gains `_authorize_recovery_link` (retry-outcome
  precondition, one-link/action-count limits) and `_suppress_message_reason`
  (communication ownership, consent, reachable channel, message-count,
  cooldown - independent of the link's own authorization, so a suppressed
  message never blocks the link); `receive()` threads the new webhook
  fields into `IntakeCommand`/`CaptureCommand`; `run()` executes the fake
  recovery-link effect and records its outcome ONLY when
  `ApplyResult.should_execute` is true (a duplicate/idempotent evaluation
  never re-executes); `_snapshot()` carries all new context-contract fields
  through to the strategist.
- `tests/test_case3.py` - new, 21 tests, all through `receive`/`run`/
  `inspect` plus direct `InMemoryLedger`/`authorize()` calls (both public,
  non-underscore seams already used the same way in `test_case1.py`, e.g.
  `ledger.claim_due_work`) - never a private `engine.` attribute.

### Behavior demonstrated (each has an automated test)

1. **Capture guard closes the expected-state gap** -
   `test_expected_state_mismatch_rejects_capture_before_counting`: a
   `CaptureCommand` with a correct `expected_version` but a stale
   `expected_state` is rejected (`stale_case_state`) before any money is
   counted.
2. **Case 3 initial decision** -
   `test_insufficient_funds_first_failure_permits_one_wait`: an
   insufficient-funds failure with one eligible provider retry proposes and
   authorizes exactly one bounded `WAIT_FOR_PROVIDER_RETRY`.
3. **Failed retry wakes the case and changes strategy** -
   `test_failed_retry_wakes_same_case_and_changes_strategy`,
   `test_repeated_retry_failure_event_does_not_duplicate_case_or_work`: a
   distinct subsequent failed event for the same obligation, while
   `waiting`, is recorded atomically, wakes the case (one case, one pending
   work item), and the next proposal is `CREATE_RECOVERY_LINK` - the prior
   `WAIT_FOR_PROVIDER_RETRY` proposal remains in the same case's audit
   trail as preserved evidence.
4. **Recovery-link strategy + durable action intent** -
   `test_action_intent_is_persisted_before_the_fake_effect_and_link_created`
   (audit shows `ACTION_INTENT` strictly before `ACTION_OUTCOME`),
   `test_message_intent_authorized_when_merchant_owns_communication`,
   `test_razorpay_owned_communication_suppresses_merchant_contact` (link
   still created; message suppressed), `test_duplicate_run_does_not_
   duplicate_link_or_message`, plus direct `authorize()` tests for the
   retry-outcome precondition, link/action-count limits, and message
   consent/channel/count/cooldown suppression - all independent of link
   authorization.
5. **Attribution** -
   `test_provider_owned_retry_capture_is_provider_self_recovered`,
   `test_correlated_alternate_capture_is_hermes_assisted` (payment_id equal
   to the executed intent's own reference), `test_recovered_money_remains_
   exact_once_on_the_case_3_path` (duplicate event id + a second event id
   carrying the same payment id both stay a no-op).
6. **Invalid model output executes nothing** -
   `test_invalid_message_intent_with_url_executes_no_action`: a
   URL-carrying `message_intent` is treated as invalid strategist output,
   identically to a raised/malformed proposal - no link, no intent, no
   `AI_PROPOSAL` audit entry.

### Design decisions worth flagging for review

- `actions_taken` counts only merchant-authorized interventions
  (`CREATE_RECOVERY_LINK`); `WAIT_FOR_PROVIDER_RETRY` does not spend the
  3-action budget, since it is provider-side and already separately bounded
  by retry eligibility and the 72-hour wait cap. Revisit if a future case
  needs WAIT to count.
- Merchant facts (`customer_notify`/`consent`/`reachable_channel`) travel on
  `RazorpayWebhook` itself rather than a separate ingress, since this slice
  has no other intake path yet (FastAPI/merchant-context ingestion is a
  later tracer-bullet slice per `IMPLEMENTATION_SPEC.md`). Revisit once
  that slice exists.
- A recovery link's alternate-collection payment is correlated to the case
  by `payment_id == ActionIntent.reference` (the fake executor's own
  deterministic id) - a real Razorpay Payment Link's captured-payment
  webhook would need the equivalent real correlation field wired the same
  way behind the `PaymentProvider` protocol.
- `SEND_REMINDER` as a standalone top-level proposal was deliberately NOT
  implemented; only `CREATE_RECOVERY_LINK`'s bundled optional
  `message_intent` exercises the message-authorization path, per this
  prompt's exact scope ("Recovery-link strategy... with an optional
  reminder/message intent").
- `message_intent` validation is a substring check (URL/currency-symbol),
  not a schema/NLP classifier - sufficient for a scripted strategist;
  revisit once a real Hermes/Gemini strategist can produce more varied
  invalid output.

### Verification

- `cd C:\Users\dwish\Documents\Codex\2026-09-02\fors\outputs\ai-revenue-recovery`
- `python -m pytest -q` -> `57 passed in ~0.35s` (36 Case 1 + 21 Case 3;
  Case 1 suite unmodified and green).
- `python -m compileall -q src tests` -> clean.
- No lint/type tooling is configured in `pyproject.toml`; none run
  (consistent with every prior iteration).
- `git diff --check` -> clean, no whitespace errors.
- `git diff --cached --stat` reviewed: exactly
  `src/hermes/{types,protocols,adapters,engine}.py` and
  `tests/test_case3.py`; no doc, pyproject, schema, or unrelated file
  changed; no secrets (`grep`-scanned for API-key/secret/password/token
  patterns - none found beyond internal `claim_token`/`event_id`/
  `payment_id` identifiers, which are not credentials).

### Remaining limitations (in scope for later prompts)

- `SEND_REMINDER` and `REQUEST_PAYMENT_METHOD_UPDATE` remain unimplemented
  standalone proposals (`action_not_supported_in_slice`); Cases 2/4/5 need
  them.
- `STOP`/`ESCALATE`/`RECOMMEND_STRUCTURAL_CHANGE`/`TAKE_NO_ACTION` are not
  yet authorizable actions; `merchant_manual` attribution has no reachable
  path in this slice (the constant exists; nothing sets it yet).
- No dispute handling, commercial-safety replacement, or access-hold
  recommendation (policy-evaluation-order steps 5 and 9 partially
  implemented, matching Case 1's existing `ponytail:` note).
- Concurrency, lease, and transaction-boundary limitations are unchanged
  from Iteration 04 (single-process cooperative; documented there).
- No HMAC / real Razorpay / Gemini / Neon / FastAPI / Streamlit / real
  messaging - all explicitly out of scope for this milestone.
- Payment-history classification (normally-on-time / chronically-late) is
  not implemented; Cases 4/5 need it.

### Exact recommended next action

Codex reviews this iteration's commit (diff `main..feat/case-3-adaptation`),
then issues the timeboxed Hermes runtime spike prompt: pin one Hermes
commit, prove isolated Gemini invocation behind the existing `Strategist`
protocol, strict local schema validation, and timeout/repair behavior,
using `HERMES_RAZORPAY_RESEARCH.md`'s verified constraints - before
building the FastAPI ingress or Neon persistence slices.

## Iteration 04 — Corrective: exclusive leases + atomic intake/capture

- Branch: `feat/case-1-recovery-slice` (unchanged).
- Implementation commit: `95fe631cdd1fcaa4db857e1b9d1ce6d639407d1d`
  (`fix(engine): exclusive work leases, atomic webhook intake, atomic capture`).
- Handoff commit: `this commit`.
- `origin` = https://github.com/Arjun-Nairr/Razorpay-demo.git; branch pushed
  with upstream set.
- Correction-only: no scenarios, integrations, UI, dependencies, or product
  policy changes. Documents unchanged except this file.

### Changed files

- `src/hermes/types.py` — `valid_payment_id()` helper; `CaseSnapshot.version`;
  `ScheduledWork.claimed_at`; `IntakeCommand` / `IntakeResult` (replace
  `OpenCaseCommand`); `CaptureCommand.expected_version` + `.expected_state`.
- `src/hermes/protocols.py` — `Ledger.open_case` -> `Ledger.apply_intake`; notes
  that `claim_due_work` leases at most one item and never yields a live lease.
- `src/hermes/adapters.py` — `LEASE_TTL_HOURS = 6`; `claim_due_work` now leases
  exactly one due item and skips any item whose lease is still live
  (`now - claimed_at < LEASE_TTL_HOURS`), reclaiming only expired/abandoned
  leases; `apply_intake` is the single atomic failed-intake transaction;
  `apply_capture` now: dedups the provider event, then rejects
  `stale_case_version` (version != expected) and `capture_on_terminal_case` and
  `invalid_payment_id` **before** counting, then the existing global
  payment-id dedup, then confirms.
- `src/hermes/engine.py` — `receive` FAILED path is one `apply_intake` call
  (no `_on_failed`, no engine check-then-write); `_on_captured` records the
  pre-verification `snap.version` / `snap.state` into `CaptureCommand` and maps
  a `duplicate_event` result to `ReceiveResult.duplicate`; `run` loop drops the
  `seen_ids` guard (single-lease + live-lease skip make it unnecessary;
  `WORK_LOOP_LIMIT` remains the hard cap); uses `types.valid_payment_id`.
- `tests/test_case1.py` — 36 tests (was 28).

### Corrections applied (each has an automated test)

1. **Exclusive work claims** — `claim_due_work` leases one item and never
   returns a live-leased item; finalization still checks token+version; an
   abandoned lease is reclaimable after `LEASE_TTL_HOURS`.
   `test_losing_runner_makes_zero_strategist_calls` (loser: 0 strategist calls,
   0 steps, 0 stale_claims), `test_expired_lease_can_be_reclaimed`,
   `test_claim_due_work_leases_one_item_per_call`,
   `test_run_drains_all_work_this_runner_exclusively_owns`,
   `test_stale_claim_after_capture_does_not_retransition` (retained).
2. **Atomic webhook intake** — `apply_intake` does dedup + one-case-per-
   obligation + INPUT_EVENT audit + initial-work enqueue in one transaction;
   the engine no longer branches check-then-write.
   `test_repeated_failed_delivery_creates_one_case_and_one_work` (repeated /
   same-obligation deliveries -> one case, one initial work item),
   `test_intake_is_a_single_ledger_command_not_check_then_write`.
3. **Atomic capture finalization** — `CaptureCommand` carries
   `expected_version` / `expected_state`; `apply_capture` atomically rejects a
   stale or terminal case before counting; provider event + global payment-id
   dedup preserved; invalid-id rejected.
   `test_two_captured_events_racing_produce_one_recovery`,
   `test_interleaved_capture_finalization_is_atomic` (competing capture bumps
   the version mid-flight -> loser rejected `stale_case_version`, one recovery),
   `test_repeated_captured_event_is_a_silent_noop`.

### Verification

- `cd C:\Users\dwish\Documents\Codex\2026-09-02\fors\outputs\ai-revenue-recovery`
- `python -m pytest -q` → `36 passed in ~0.3s`.
- `python -m compileall -q src tests` → clean.
- No lint/type tooling configured; none run.
- `git diff` reviewed: only the five source/test files; no docs, pyproject, or
  unrelated changes; no secrets.

### Remaining limitations (in scope for later prompts)

- Concurrency is single-process cooperative. `claim_due_work` leasing +
  `claimed_at` TTL model a DB row visibility/lock timeout; `apply_*` methods
  model single transactions. There is no real thread/row locking, and lease
  expiry is in logical hours advanced only by `run(until=...)`.
- `apply_capture`'s `stale_case_version` / `capture_on_terminal_case` guards are
  both defended; in this slice a competing capture always drives the case
  terminal, so the version guard is what fires in the interleaved test and the
  terminal guard is defense-in-depth.
- `authorize()` remains the partial Case-1 policy (terminal guard +
  eligibility-gated wait); full 10-step order still pending.
- Cross-obligation payment-id conflict and capture-amount mismatch audit
  `ESCALATE`/`BLOCK` without transitioning the affected case's state.
- No HMAC / real Razorpay / Gemini / Neon / FastAPI / Streamlit; projection
  shapes are Case-1 sized.

### Exact recommended next action

Codex reviews commit `95fe631cdd1fcaa4db857e1b9d1ce6d639407d1d` (diff `main..feat/case-1-recovery-slice`),
then issues Prompt 05 for Case 3 (insufficient funds with adaptation): a
scripted `WAIT_FOR_PROVIDER_RETRY` followed, after a failed provider-retry
event, by `SEND_REMINDER` / `CREATE_RECOVERY_LINK`, exercising message
cooldown/count limits and the re-evaluation-after-failed-retry path through the
same `receive` / `run` / `inspect` surface.

## Iteration 03 — Corrective: atomic claims + adapter-neutral seam

- Branch: `feat/case-1-recovery-slice` (unchanged).
- Commit: `3ac73f3c2d9c80dfe270de832cefbe402962248b`
  (`fix(engine): atomic claims, protocol seam, fail-closed eligibility,
  payment-id validation`); handoff commit `f31f8be`.
- Remote `origin` = https://github.com/Arjun-Nairr/Razorpay-demo.git (added
  after iteration 03). `main` and `feat/case-1-recovery-slice` pushed and
  tracking. Earlier iterations' `REMOTE_NOT_CONFIGURED` notes are now historical.
- Correction-only: no product features, no real integrations, no new
  dependencies, no UI, no messaging. Project documents unchanged except this
  file.

### Changed files

- `src/hermes/protocols.py` — **new**. `Ledger`, `Strategist`,
  `PaymentProvider` `typing.Protocol` interfaces. The engine imports only these.
- `src/hermes/types.py` — added `CaseSnapshot`, `WorkClaim`, `ApplyResult`,
  immutable command objects (`OpenCaseCommand`, `NoteEventCommand`,
  `EvaluationCommand`, `StrategistFailureCommand`, `DiscardWorkCommand`,
  `CaptureCommand`), `StrategySnapshot`; `ProviderRetryFact.evidence`;
  `ScheduledWork.claim_token/claim_version`; `RunReport.stale_claims`.
- `src/hermes/adapters.py` — `InMemoryLedger` storage made private
  (`_cases`/`_recovered_minor`/`_recovered_payment_ids`/…); `claim_due_work`
  leases work (fresh token + `claim_version += 1`); transaction methods take
  commands and validate the lease via `_live_claim`; added ledger-owned
  `case_projection` / `batch_projection` / `audit_projection`.
  `FakeRazorpayAdapter.retry_eligibility` is fail-closed (no signal ->
  `retry_eligible=False, evidence=None`). `MAX_WORK_ATTEMPTS = 2`.
- `src/hermes/engine.py` — constructor takes `Ledger`/`Strategist`/
  `PaymentProvider` (no defaults, no concrete import); `receive`/`run` build
  immutable commands and pass claim tokens; `run` rejects stale finalizations
  (counts `stale_claims`) and stops if a work id re-leases without progress;
  `_valid_payment_id` gate before capture; `authorize` requires an explicit
  eligible fact *with* evidence; `inspect` returns ledger projections only.
- `tests/test_case1.py` — rewritten to the public seam; 28 tests.

### Corrections applied (each has an automated test)

1. **Atomic work claiming** — `claim_due_work` leases with token + version; only
   the live lease can finalize. `test_overlapping_claims_do_not_double_finalize`
   (reentrant second runner wins; first runner's finalize is stale — one
   transition, one follow-up), `test_stale_claim_after_capture_does_not_retransition`.
2. **Adapter-neutral seam** — Protocols added; engine depends only on them;
   immutable commands; no mutable stored objects into writes; `inspect` uses
   ledger projections. `test_engine_depends_only_on_protocol_seam`,
   `test_inspect_returns_typed_projections`, `test_inspect_rejects_unknown_query_type`.
3. **Payment identity validation** — missing/empty/whitespace payment ids
   rejected before `record_capture`/`verify_capture`, audited `invalid_payment_id`,
   no revenue, no recovery. `test_invalid_payment_id_is_rejected_before_capture`
   (parametrized), `test_valid_payment_id_after_rejection_still_recovers`.
4. **Fail-closed retry eligibility** — missing evidence -> ineligible/blocked;
   authorize needs an explicit eligible fact with evidence.
   `test_retry_eligibility_{true_allows,false_blocks,missing_evidence_blocks}_wait`.
5. **Retry budget = one retry (two total attempts)** — on exhaustion the case
   goes to an explicit `escalated` terminal state, not idle-active.
   `test_strategist_retry_budget_is_one_then_escalates`,
   `test_strategist_failure_loses_no_work_and_executes_no_action`.

### Verification

- `cd C:\Users\dwish\Documents\Codex\2026-09-02\fors\outputs\ai-revenue-recovery`
- `python -m pytest -q` → `28 passed in ~0.3s`.
- `python -m compileall -q src tests` → clean.
- No lint/type tooling is configured in the repo, so none was run.
- `git diff` reviewed: only the four source files + new `protocols.py`; no doc,
  pyproject, or unrelated changes; no secrets.

### Remaining limitations (in scope for later prompts)

- `authorize()` still implements only the terminal guard + the eligibility-gated
  `WAIT_FOR_PROVIDER_RETRY` path; the full 10-step policy order is pending.
- Concurrency is single-process cooperative: `claim_due_work` leasing +
  `claim_version` model the contention a real Neon `SELECT … FOR UPDATE` /
  optimistic-version check would enforce; there is no real thread/row locking.
- Cross-obligation payment-id conflict and capture-amount mismatch audit
  `ESCALATE` but do not change the second/again case's state.
- No HMAC, no real Razorpay/Gemini/Neon/FastAPI/Streamlit; `InMemoryLedger`
  transaction boundaries are documented, not enforced by a DB.
- A zero-hour wait could re-queue within one `run`; `WORK_LOOP_LIMIT` plus the
  re-lease guard are the backstop (Case 1's minimum wait is 24h).
- Projection shapes are Case-1 sized; Cases 2–5 will extend them.

### Exact recommended next action

Codex reviews commit `3ac73f3` (diff `main..feat/case-1-recovery-slice`), then
issues Prompt 04 for Case 3 (insufficient funds with adaptation): a scripted
`WAIT_FOR_PROVIDER_RETRY` that, after a failed provider-retry event, is followed
by `SEND_REMINDER` / `CREATE_RECOVERY_LINK`, exercising message cooldown/count
limits and the re-evaluation-after-failed-retry path through the same
`receive` / `run` / `inspect` surface.

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
- Optimize for deep behavior across exactly five designed scenarios, not batch
  scale.
- Treat the five rich scenarios as an evaluation batch and show aggregate money
  recovered, satisfying the official judging bar.
- Razorpay test mode is the intended payment integration.
- Use free or meaningfully usable free-tier tooling where feasible.
- Keep the build selection-demo sized; avoid production overengineering.
- Hermes Agent, Gemini 3.7 Flash, FastAPI, Neon, Streamlit, zrok, pytest, and the
  provider-neutral action outbox are approved targets subject to the timeboxed
  runtime/integration gates in `IMPLEMENTATION_SPEC.md`.
- Internal delivery target is September 4 evening (Asia/Dubai assumed until
  confirmed); official September 5 cutoff time is unknown.
- The expected submission artifact includes a five-minute recorded demo.
- Razorpay test mode needs to be set up.
- Available model resources: ChatGPT Plus, OpenCode Go, and up to USD 22 in
  Gemini API credits if needed. Subscriptions must not be assumed to provide
  programmatic API access; research must verify usable runtime options.
- Synthetic customer history is allowed only where Razorpay does not expose the
  required context.
- Messaging is represented by an auditable action intent in the core demo;
  Telegram and email remain optional provider integrations.
- First-demo wedge: SaaS subscription-payment recovery, not B2B receivables.
- Product identity should be fictional but preferably adjacent to Razorpay's
  payment/SaaS domain.
- Start with one end-to-end case, then expand to at most five variable cases.
- Use an accelerated logical clock only for Hermes waits, cooldowns, and
  simulated outcomes; never claim to accelerate Razorpay's calendar retries.
- Recovery should be fully automated on normal paths. Policy-triggered stopping
  or human escalation must still exist because compliant escalation is part of
  the official judging bar.
- Synthetic enrichment is limited to useful data that a real SaaS/payment
  company could possess; no impossible or decorative omniscient fields.
- Core demo runs locally. Neon is the target shared ledger; SQLite is the
  deadline fallback. Public dashboard deployment is optional.

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
- Exact fictional SaaS identity and UI style

## Approved implementation stack

- Local Python/FastAPI with Hermes Agent behind `Strategist`
- Gemini 3.7 Flash through Hermes's native provider; local Pydantic validation
- Neon Postgres as shared state and business audit ledger
- Persisted accelerated logical clock; no external scheduler/job queue
- Streamlit locally for the dashboard
- zrok solely to expose the Razorpay webhook endpoint
- pytest and five hand-authored golden cases
- Provider-neutral message outbox; Telegram only as a stretch adapter
- See `TOOLING_RESEARCH.md` and `HERMES_RAZORPAY_RESEARCH.md` for verified
  facts, limits, and rejected assumptions

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

Case 3 is done (see Iteration 05 below). Codex reviews commit `adc69ff` on
`feat/case-3-adaptation` (diff `main..feat/case-3-adaptation`), then issues
the timeboxed Hermes runtime spike prompt (`IMPLEMENTATION_SPEC.md` slice 2):
pin one Hermes commit, prove an isolated Gemini invocation behind the
existing `Strategist` protocol, strict local schema validation, and
timeout/repair behavior, using `HERMES_RAZORPAY_RESEARCH.md`'s verified
constraints. Do not let a Hermes/Gemini setup problem destabilize the
in-memory domain foundation this and the Case 1 slice already proved.
