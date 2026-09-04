# Cross-Agent Handoff

Last updated: 2026-09-04 (Asia/Dubai)

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
- Status: **Iteration 09 - reviewed-demo-blocker corrections + first user-run
  end-to-end test prep** on `fix/runnable-demo-boundaries` (branched from
  `d2e6572`). Six review blockers fixed: (1) full demo state survives an
  app restart by deterministic reconstruction from the durable ledger
  (merchant context, provider retry eligibility, next serial) plus
  collision-safe case/event IDs - the DB is never reset; (2) zero-hour waits
  are a bounded failure, not a reschedule loop - `WAIT_FOR_PROVIDER_RETRY`
  requires `proposed_wait_hours >= 1` within the remaining 72h budget;
  (3) the Gemini prompt now carries the approved message templates verbatim
  and `wait_hours_remaining`, validated inside the at-most-one-repair
  boundary with deterministic engine validation still the final guard
  (`PROMPT_VERSION` bumped); (4) `PostgresSnapshotStore` rolls back and stays
  usable after a SQL error, and a session-scoped `pg_try_advisory_lock`
  enforces a single DB writer per schema; (5) webhook HMAC verification runs
  on the raw bytes before any `json.loads`; (6) blocking `engine.run` /
  Gemini / Postgres work runs off the event loop via `run_in_threadpool`
  with one non-blocking recovery-runner lock (409 if busy) and a per-op
  ledger `RLock`. A follow-up commit adds four more review fixes (ledger
  callable resolved post-rollback; restart no longer fabricates permissions
  for externally ingested cases - trusted `DEMO_CASE_PROVENANCE` gates
  reconstruction; sanitised startup-failure exit with no original message or
  traceback; a same-case in-flight-decision/capture regression). **223 tests
  pass, 3 skipped** (opt-in real-Postgres).
  Offline launch verified locally: FastAPI `/health` ok
  (`mode: scripted-offline`), full Case 3 flow to
  `state=recovered attribution=hermes_assisted`, Streamlit headless serves
  200, and `scripts/run_demo.ps1 -Mode offline` both aborts cleanly on a
  forced API-startup failure (no UI opened) and runs the happy path with no
  leftover listeners after shutdown. **Still NOT live-verified** - the user
  runs Neon init + the live Gemini/Neon demo; nothing here connected to Neon
  or called Gemini. See "Iteration 09" below for the exact user commands.
- Prior status: **Iteration 08 - the first runnable end-to-end Case 3 demo -
  implemented and offline-tested** on `feat/fastapi-simulated-ingress`.
  Postgres/Neon-persisted ledger (survives restart, persisted clock + pending
  work), the direct Gemini strategist wired behind the engine in *live* mode
  (never silently scripted), a deterministic cumulative-wait bound (72 logical
  hours), approved message templates, and a Streamlit-through-FastAPI local UI
  driving one insufficient-funds case: failure -> eligible wait -> failed retry
  -> recovery link -> uniquely correlated simulated payment -> `hermes_assisted`
  recovered. **201 tests pass, 1 skipped** (opt-in real-Postgres). New optional
  extras `[db]`, `[ui]` (+ `uvicorn` in `[api]`). **NOT yet live-verified** -
  the user runs Neon init + the live Gemini/Neon demo; nothing here connected
  to Neon or called Gemini. Next: user runs it, then Codex review, then
  Razorpay Test Mode hybrid slice.
- Prior: Runtime spike (`IMPLEMENTATION_SPEC.md` slice 2) complete on
  `feat/hermes-runtime-spike`, plus two corrections passes. **Fallback path
  shipped**: a direct google-genai (Gemini 3.7 Flash) `HermesStrategist`
  behind the existing `Strategist` protocol, offline-tested; the Hermes-Agent
  library path was not taken (Windows `pip`/`git` long-path failure on the
  pinned commit). Corrections hardened the wall-clock timeout (daemon thread,
  returns near budget), made the offline suite SDK-independent (green with and
  without `google-genai==2.22.0`), enforced an exact six-key JSON contract,
  clamped the repair budget to at most one, and made every failure path -
  including transport-*construction* failures (raising factory, lazy SDK
  import, `Client(...)` init, missing key) - record safe redacted metadata
  instead of escaping with `last_run_meta=None`. A later local-only task added
  `.env` support for the smoke script (`python-dotenv` in the `[gemini]` extra;
  loader merges a gitignored project-root `.env` without overriding the
  environment; redacted failure output). 107 tests pass; Case 1/3 untouched. The user-run Gemini smoke test reached the live model and returned
  schema-valid JSON, **proving live connectivity, the fallback transport, the
  model name, strict parsing, and the metadata path**. The live proposal was
  `WAIT_FOR_PROVIDER_RETRY` again; this is **not** a proven semantic failure -
  the smoke fixture still sets `provider_retry_eligible=True` and only
  `retry_outcome_recorded=True` (one prior retry failed). A failed retry is not
  retry exhaustion: Razorpay's card-retry schedule (T+1/T+2/T+3) can still hold
  a further eligible attempt. The earlier "semantic adaptation FAILS" verdict
  was too strong and there is no recovery-rule change to make here. Before
  runtime integration, the context contract should distinguish *current* retry
  eligibility from *prior* failure count and define what bounded further
  waiting is allowed - as a spec clarification, not code, in the next task.
  For the smoke script the user now keeps a **replacement** `GEMINI_API_KEY` in
  a local gitignored `.env` (the previously used key was disclosed in chat and
  must stay revoked); the key is never requested in or pasted into chat.

## Iteration 09 — Reviewed-demo-blocker corrections + user-run test prep

Branch `fix/runnable-demo-boundaries` from `d2e6572`. No new features, no new
scenarios. Six review blockers fixed; existing tests were not weakened.

### Fixes (each with a regression test)

1. **Demo survives a full app restart.** `runtime._bootstrap_demo_state`
   rebuilds the trusted synthetic context and simulated-provider state from
   the durable ledger on startup: for every persisted case it re-derives the
   Case 3 merchant context, sets provider retry eligibility from
   `not retry_outcome_recorded`, and computes the next demo serial from the
   max `sub_demo_NNNN_*` serial already stored. New case/event IDs are
   collision-safe (`mint_demo_ids` -> `sub_demo_{serial:04d}_{token_hex(4)}`;
   stable `evt_*` ids for the deterministic steps, random suffix only on the
   injected failed retry). The database is **not** reset on boot.
   Tests: `tests/test_demo_restart.py` - existing case keeps its facts and can
   still finish; a fresh case is genuinely new; duplicate payment delivery
   still cannot double-count, all across a shared snapshot store.
2. **Zero-hour wait loophole closed.** `_validate_proposal` rejects
   `WAIT_FOR_PROVIDER_RETRY` with `proposed_wait_hours < 1`; `authorize`
   clamps the wait to `min(proposed, MAX_WAIT_HOURS, remaining_budget)` and
   BLOCKs `wait_must_be_positive` / `total_wait_bound_reached` instead of
   scheduling a zero-hour reschedule. Invalid model output follows the
   bounded strategist-failure path (never silently rewritten to success).
   Test: `tests/test_recovery_bounds.py::test_zero_hour_wait_is_a_bounded_failure_not_a_reschedule_loop`
   (repeated runs + a fresh engine over the same store).
3. **Gemini prompt/validation contract aligned.** `_SYSTEM_PROMPT` now lists
   the approved message templates verbatim and the model must copy one
   exactly or use `null`; `_context_facts` includes `wait_hours_remaining`;
   `parse_proposal` validates the message choice and the `>= 1` wait inside
   the at-most-one-repair boundary; `_validate_proposal` in the engine stays
   the deterministic final guard. `PROMPT_VERSION = hermes-strategist/2026-09-04.1`.
   Tests: `tests/test_hermes_strategist.py` - real `HermesStrategist` with an
   injected transport: approved proposal reaches policy; an unapproved
   message gets exactly one repair then succeeds; repeated invalid output
   takes the safe failure path; the wait budget and approved list are present
   in the model context.
4. **Persisted state protected.** `PostgresSnapshotStore.read/write` wrap the
   statement in try/except with `rollback()` so the connection stays usable
   after a SQL error (in-memory `PgLedger` rollback retained). A
   session-scoped `pg_try_advisory_lock` on a key derived from
   `sha256(schema)` enforces a single writer per schema - a second app
   raises `RuntimeError("...writer lock...")` instead of overwriting; the
   lock is released on `close()`, wired through the FastAPI `lifespan`
   shutdown (`on_shutdown=ledger.close`).
   Tests: offline `tests/test_pg_ledger.py` (fake psycopg - rollback keeps the
   store usable, second writer refused, close releases the lock); opt-in
   `tests/test_pg_integration.py` against a real DSN.
5. **Signature before parsing.** `_ingest` verifies the HMAC on the raw
   request bytes first (401), then checks the event id, then `json.loads`,
   then resolves trusted merchant context from the parsed id.
   Test: `tests/test_api_concurrency.py::test_invalid_signature_never_triggers_json_parsing`
   (monkeypatched `json.loads` raises if reached).
6. **API stays responsive.** `/webhooks/razorpay` and the `/demo/*` runners
   call `engine`/ledger work via `run_in_threadpool`; a single non-blocking
   `threading.Lock` (`app.state.run_lock`, 409 when held) keeps one recovery
   runner; `PgLedger` takes a per-op `RLock` (never across the strategist
   call) so a slow model call does not block webhook intake.
   Tests: `tests/test_api_concurrency.py` with a `DelayedStrategist` - health
   stays < 1s under a 1.5s model call, a second run attempt gets 409, webhook
   intake (incl. duplicate) returns in < 1s during a 2s model call.

### Changed / new files

- `src/hermes/runtime.py` - `_bootstrap_demo_state`, `demo_schema` setting,
  `build_app` wires reconstruction + `on_shutdown=ledger.close`.
- `src/hermes/api.py` - signature-first `_ingest`, `run_in_threadpool` on
  blocking paths, `run_lock`, `lifespan` shutdown hook, `mode_label` /
  `merchant_context` / `demo_serial_start` params, `mint_demo_ids` for
  `/demo/case`.
- `src/hermes/engine.py` - `proposed_wait_hours >= 1` guard, budget-clamped
  `authorize` WAIT branch, persisted-clock resume on `receive`.
- `src/hermes/hermes_strategist.py` - approved-template prompt block,
  `wait_hours_remaining` in context, message + wait validation in
  `parse_proposal`, `PROMPT_VERSION` bump, `max_in_flight` bounded semaphore.
- `src/hermes/pg_ledger.py` - transactional `read/write` recovery, advisory
  single-writer lock, per-op `RLock`, `case_ids` read.
- `src/hermes/pg_ledger.py` / `adapters.py` / `protocols.py` - `case_ids()`
  on the `Ledger` protocol and both implementations.
- `src/hermes/demo_fixtures.py` - `mint_demo_ids`, `demo_serial_of`.
- `src/hermes/asgi.py` - startup failure prints a clear stderr line
  (mode + our own error text; generic hint for non-ours) and re-raises so
  the launcher's health check aborts before opening the UI.
- `scripts/run_demo.ps1` - `-Mode live|offline`, health-poll abort (no UI on
  failure, prints the job's startup output), `PYTHONPATH=src` fallback,
  `finally` job cleanup.
- `scripts/demo_ui.py` - sidebar shows the execution `mode`
  (`live-gemini` / `scripted-offline`); the proposal panel is titled
  "actual Gemini output" only in live mode, "scripted offline reasoning,
  no model call" otherwise; SIMULATED note on payments/links in both.
- New: `tests/test_demo_restart.py`, `tests/test_api_concurrency.py`.
- Modified tests: `test_recovery_bounds.py`, `test_hermes_strategist.py`,
  `test_pg_ledger.py`, `test_pg_integration.py`, `test_api.py`.

### Verification (offline, this machine)

- `python -m pytest -q` -> **219 passed, 3 skipped** at first commit;
  **223 passed, 3 skipped** after the follow-up corrections below. All 3 skips
  are the opt-in real-Postgres tests in `test_pg_integration.py`, gated on
  `HERMES_PG_TEST_DSN`.
- `python -m compileall -q src tests scripts` -> clean.
- `git diff --check` -> clean (only LF->CRLF advisories).
- Secret scan of the full diff + new files -> no keys, DSNs, or `.env`
  contents. `.env` is untracked and gitignored.
- Real uvicorn (`python -m uvicorn hermes.asgi:app`, offline): `/health` ->
  `{"status":"ok","evidence_mode":"SIMULATED","mode":"scripted-offline"}`;
  full Case 3 via `/demo/*` -> `state=recovered attribution=hermes_assisted
  recovered_minor=1000000 messages_sent=1 links_created=1`; timeline ends
  `... ACTION_OUTCOME, INPUT_EVENT, PAYMENT_CONFIRMATION, TERMINAL_TRANSITION`.
- Streamlit headless (`python -m streamlit run scripts/demo_ui.py
  --server.headless true`) -> serves 200, `/_stcore/health` 200.
- `scripts/run_demo.ps1 -Mode offline`: forced startup failure
  (`HERMES_DEMO_SCHEMA` invalid) -> prints "API did not become healthy" +
  the job's startup error, does **not** start Streamlit; happy path ->
  API healthy (`/health` mode `scripted-offline`), Streamlit serves on the
  UI port, no listeners left on the API/UI ports after the process exits.

### Not verified live (the user runs these)

Nothing in this iteration connected to Neon or called Gemini. Live
Neon persistence, the real advisory-lock single-writer behaviour against
Neon, and live Gemini proposal/repair/validation remain user-run.

### Exact user commands (PowerShell, one at a time)

```
cd C:\Users\dwish\Documents\Codex\2026-09-02\fors\outputs\ai-revenue-recovery
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[api,db,gemini,ui]"
Remove-Item Env:GEMINI_API_KEY -ErrorAction SilentlyContinue
```
Put `GEMINI_API_KEY` (your replacement key) and `DATABASE_URL` (Neon
Connect-panel URL incl. `?sslmode=require`) in `.\.env`, then:
```
python scripts\init_neon.py
.\scripts\run_demo.ps1
```
In the Streamlit URL it prints (127.0.0.1:8501): "Start a fresh Case 3",
"Advance time" (eligible wait), "Inject failed retry", "Advance time"
(recovery link), "Simulate recovery payment". Confirm the header shows
**live-gemini** and every payment/intervention is labelled **SIMULATED**.
Restart check: Ctrl+C in the launcher window, run `.\scripts\run_demo.ps1`
again, reopen the UI - the finished case is still there with its facts, and
"Start a fresh Case 3" makes a genuinely new `sub_demo_*` id.
Offline (no credentials): `.\scripts\run_demo.ps1 -Mode offline`.
Opt-in real-Neon tests:
`$env:HERMES_PG_TEST_DSN = "<url>"; python -m pytest -q tests/test_pg_integration.py`.

### Limitations / exact next action

- Snapshot-per-write ledger stays demo-grade (durable + correct, single
  writer only). Migrating to normalized per-entity tables behind the same
  `Ledger` protocol is a later real-Neon slice.
- `merchant_manual` attribution still has no reachable path; Cases 2/4/5 and
  real Razorpay Test Mode / real messaging untouched.
- `RecoveryEngine._clock` is refreshed from the ledger on `receive`; a
  concurrent `receive` during an in-flight `run` could read a slightly stale
  in-process clock. The persisted clock and the non-blocking run lock keep
  this cosmetic (no double-count, no backward time write - `run` raises
  `ValueError` -> 409). Documented, not fixed.
- **Next action: the user runs the live demo above** (Neon init + live
  Gemini), then Codex review of Iteration 09, then actual Nous Hermes
  integration (the current runtime remains **direct Gemini**), then the
  Razorpay Test Mode hybrid slice.

### Follow-up corrections (second commit on `fix/runnable-demo-boundaries`)

Four review items on the Iteration 09 code. Offline only; no Gemini/Neon/
Razorpay calls; the unrelated `HERMES_ISOLATED_AGENT_RESEARCH.md` note was
left untracked and unstaged.

1. **Queued ledger op after a rollback.** `PgLedger._delegate` bound
   `getattr(self._mem, name)` when the callable was handed out; a rollback
   replaces `self._mem`, so a call still waiting on the lock would read/mutate
   the discarded object. Now the method is resolved *inside* the locked
   invocation for both reads and writes.
   Test: `tests/test_pg_ledger.py::test_callable_bound_before_rollback_operates_on_the_replaced_ledger`
   - bind a read + a write callable, fail the next write to force a rollback,
     then invoke them: the read sees the live state and the write lands in it
     and survives reload.
2. **Unknown merchant permissions on restart.** `/demo/case` now stamps one
   trusted `DEMO_CASE_PROVENANCE` audit record (consent / reachable_channel /
   customer_notify / source / history) when it opens a case;
   `runtime._bootstrap_demo_state` reconstructs merchant context and provider
   retry eligibility **only** for cases carrying that record. An externally
   ingested obligation - even one whose id mimics `sub_demo_*` - gets nothing:
   contact stays denied, no provider eligibility is invented. Existing cases
   and payment accounting are untouched; the DB is not reset.
   Test: `tests/test_demo_restart.py::test_unknown_case_stays_contact_denied_with_no_fabricated_retry_after_restart`
   plus the existing demo-restart tests still pass.
3. **Startup-failure sanitisation.** `asgi.py` no longer re-raises the original
   exception (its traceback could carry a DSN/host/key). It prints one
   controlled line - mode, exception *type*, and the config field names to
   check - then `raise SystemExit(1) from None`: no original message, no
   chained traceback, nonzero exit.
   Test: `tests/test_asgi_startup.py` - a child process makes `build_app` raise
   `RuntimeError` containing a synthetic secret marker + a fake DSN; neither
   the marker, `postgresql://`, nor `Traceback` appears in stdout/stderr, and
   the exit code is nonzero.
4. **Same-case concurrency regression.**
   `tests/test_api_concurrency.py::test_same_case_capture_during_in_flight_decision`
   - runtime `PgLedger` over an offline snapshot store + a 2s `DelayedStrategist`.
   While `/demo/step advance` is inside the model call, a valid capture for the
   **same** case is delivered: intake returns in < 1s, the case becomes
   `recovered`, the resumed model result is rejected as a stale claim
   (`proposals == 0`, `stale_claims >= 1`, no `AI_PROPOSAL` / `ACTION_INTENT`),
   a duplicate capture does not double-count, and a fresh `PgLedger` over the
   same store still reads `recovered` / 1,000,000 with no action intents. No
   engine change was needed - the existing claim-token / expected-version
   guards already covered it.

Verification: `python -m pytest -q` -> **223 passed, 3 skipped**;
`python -m compileall -q src tests scripts` clean; `git diff --check` clean.
Remaining limitations unchanged from Iteration 09 (demo-grade snapshot ledger;
`merchant_manual` unreachable; Cases 2/4/5 and real Test Mode untouched;
cosmetic `_clock` refresh race). Actual Nous Hermes integration is the next
planned task; the runtime still uses direct Gemini.

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
- No dependency added to default/`dev`. New optional extra `[gemini]` -
  named `gemini`, not `hermes`, since the Hermes path did not ship;
  deviation from deliverable 1's `hermes` key, recorded here.

### Corrections pass — 2026-09-03 (second commit on `feat/hermes-runtime-spike`)

Correction-only follow-up to Iteration 06. Only `pyproject.toml`,
`src/hermes/hermes_strategist.py`, and `tests/test_hermes_strategist.py`
changed; `types.py` / `engine.py` / `adapters.py` / `protocols.py` /
`scripts/hermes_smoke.py` / Case 1 & 3 tests untouched.

1. **Real wall-clock timeout.** `_call` no longer uses a
   `ThreadPoolExecutor` context manager (whose `__exit__` ->
   `shutdown(wait=True)` blocked `propose()` until the slow transport
   finished). It now runs the transport on a `daemon` `threading.Thread`
   and `join(timeout_s)`; if still alive it raises `TimeoutError`
   immediately, abandons the worker (daemon -> never blocks interpreter
   exit), and discards its eventual result/exception. No executor, so no
   `atexit` join either. Regression test
   `test_propose_returns_near_timeout_not_transport_completion`: a 1.5 s
   transport with a 0.05 s budget returns in well under 0.6 s (tolerant
   ceiling for CI).
2. **SDK-independent offline tests.** Removed the "`google.genai` is
   absent" assertion. New `test_real_google_import_never_happens_on_the_stub_path`
   monkeypatches `builtins.__import__` to raise on any `google` /
   `google.*` import, then runs a full stub-transport `propose()` -
   proving the lazy import while the offline path succeeds. Suite verified
   green **both** without the SDK and with `google-genai==2.22.0`
   installed (fresh venv). Still zero network, zero key.
3. **Strict six-key JSON shape.** `parse_proposal` now requires exactly
   `action`, `diagnosis`, `rationale`, `confidence`, `proposed_wait_hours`,
   `message_intent` (module constant `REQUIRED_KEYS`). Missing -> reject;
   any unknown/extra key -> reject. Type / enum / range / blank-message
   normalization / repair behaviour unchanged. New tests:
   `test_missing_any_required_key_is_rejected` (parametrized over all six),
   `test_unknown_extra_key_is_rejected`, and
   `test_type_enum_and_range_faults_still_rejected` re-cast as full
   six-key payloads with exactly one bad field so those paths still fire.
4. **Max one repair, structurally.** Constructor clamps
   `max_repair_attempts` explicitly to `{0, 1}` (`1 if int(x) >= 1 else 0`).
   `test_repair_budget_cannot_exceed_one` (parametrized 2/5/99) proves an
   always-invalid model still yields exactly two transport calls (first +
   one repair), never more.
5. **Failure metadata.** `propose()` now wraps every model call:
   `TimeoutError` -> `last_run_meta.validation_result = "timeout"`;
   any other transport/SDK exception ->
   `"transport_error:<ExceptionType>"` (type name only - the exception
   message/content is never recorded). Metadata is populated **before**
   the exception is re-raised and carries model, `prompt_version`,
   elapsed `latency_ms`, `repair_used` (whether the repair call had
   started), bounded `raw_response` (the first reply when a repair call
   fails, else `""`), and `usage` (the first reply's usage when
   available, else `None`). Tests: `test_initial_call_timeout_records_safe_metadata`,
   `test_initial_transport_failure_records_safe_metadata` (asserts a
   synthetic sensitive marker in the exception does NOT reach the
   metadata), `test_repair_call_failure_records_metadata_with_first_reply_evidence`,
   `test_repair_call_timeout_records_metadata`.
6. **Reproducible SDK version.** `[gemini]` extra pinned exactly to
   `google-genai==2.22.0` (still optional; not in default or `dev`).

### Corrections pass 2 — 2026-09-03 (implementation commit `51868f4`)

Single fix to `HermesStrategist.propose`: transport construction (a
raising `transport_factory`, the lazy SDK import, `genai.Client(...)`
init, or a missing `GEMINI_API_KEY`) previously ran *before* the timer
and outside any handler, so those failures escaped with
`last_run_meta = None` (or stale from a prior call).

Now `propose` (a) clears `self._last_run_meta` first, (b) starts the
timer before construction, (c) wraps construction in `except Exception`
(never `BaseException`), (d) records safe metadata before re-raising the
original error - `validation_result = "transport_error:<ExceptionType>"`
(type name only, never the message / credentials / SDK detail),
`repair_used = False`, `raw_response = ""`, `usage = None`, with model,
prompt version, and elapsed latency retained. The timeout implementation,
runtime wiring, and audit-ledger wiring are unchanged.

New/extended tests:
`test_transport_factory_setup_failure_is_audited_and_redacted` (an
injected factory raising `RuntimeError("sensitive-setup-marker-xyz")`
re-raises the error but records non-null metadata; the marker is in
neither `validation_result` nor `raw_response`),
`test_setup_failure_does_not_leak_prior_run_metadata` (a run that
succeeds then a run whose factory fails -> metadata is the new
`transport_error:RuntimeError`, not the stale `"valid"`), and the
existing `test_real_transport_build_requires_key` now also asserts the
missing-key failure records redacted metadata. Timeout, repair,
strict-schema, and lazy-import tests are unchanged and green.

Files changed: `src/hermes/hermes_strategist.py`,
`tests/test_hermes_strategist.py`, `HANDOFF.md`.

### `.env` support for the smoke script — 2026-09-03 (local commit on `feat/hermes-runtime-spike`, not pushed)

Local-config convenience so the user can keep the (revoked-and-replaced)
Gemini key out of the shell history. Strategist / engine / ledger / Case 1
& 3 tests untouched.

- `pyproject.toml` - `[gemini]` extra gains `python-dotenv==1.0.1` (verified
  on Python 3.12; `load_dotenv` defaults to `override=False`). Default
  `dependencies` and `dev` unchanged.
- `scripts/hermes_smoke.py` - new `_load_project_env(dotenv_path=None)` merges
  `<project root>/.env` into `os.environ` **without overriding** anything
  already set; missing file or missing `python-dotenv` is a silent no-op.
  `main()` calls it before the key check. On failure the script now prints
  only `error_type` + the already-redacted `run_meta` - the `str(exc)` field
  is removed (an SDK/auth message can carry a key fragment). Not loaded inside
  `HermesStrategist` or at module import.
- `.env` - a blank `GEMINI_API_KEY=` file was created at the project root
  **only because none existed**; it is gitignored (`.gitignore:20`), untracked,
  and never read/printed/overwritten by this task. `.env.example` stays the
  committed blank template.
- `tests/test_hermes_smoke.py` - **new**, 6 offline tests, loaded via
  `importlib` (no `scripts/__init__.py`), using a recording `dotenv` stub +
  temp files + synthetic values: explicit-path load sets the var and requests
  `override=False`; an existing env var wins over the file; a missing file and
  a missing `python-dotenv` are both silent no-ops; `main()` returns 2 with no
  key (loader monkeypatched off so the real `.env` is never read); a failing
  strategist's output contains `error_type`/`run_meta` but not the raw
  exception message and has no `error` field. No test reads a real key or
  calls Gemini.

Verification: `python -m pytest -q` -> **107 passed** (101 unchanged + 6 new);
same in a fresh venv with `google-genai==2.22.0` **and** `python-dotenv==1.0.1`
installed -> 107 passed. `python -m compileall -q src tests scripts` clean.
`git diff --check` clean. Diff limited to `pyproject.toml`,
`scripts/hermes_smoke.py`, `tests/test_hermes_smoke.py`, `HANDOFF.md`
(`.env` is untracked). Committed locally; **not pushed** - the earlier
`docs: record live Gemini smoke result` commit (sanitized live-test metadata)
still awaits explicit user authorization to upload, and nothing is pushed
until then.

### Changed files (exactly these + this handoff)

> The list below is the *original* Iteration 06 state. Where it and the
> "Corrections pass" subsection above disagree (timeout mechanism, exact test
> count, SDK pin), the corrections subsection is current.

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

- `python -m pytest -q` -> **107 passed** (57 unchanged: 36 Case 1 + 21
  Case 3, both suites byte-for-byte untouched; + 44 offline spike tests after
  corrections passes 1 and 2; + 6 offline `.env`/smoke tests - see the
  "`.env` support for the smoke script" subsection above).
- Same suite run in a fresh venv with `google-genai==2.22.0` (and, after the
  `.env` task, `python-dotenv==1.0.1`) installed -> **107 passed**
  (environment independence proven; offline path needs no SDK, and installing
  the SDK / dotenv does not change any result).
- `python -m compileall -q src tests scripts` -> clean.
- `git diff --check` -> clean (only CRLF-on-checkout warnings).
- Staged diff after corrections: exactly `pyproject.toml`,
  `src/hermes/hermes_strategist.py`, `tests/test_hermes_strategist.py`
  (+ this handoff). No `types/engine/adapters/protocols.py`, no other doc,
  no `scripts/`, no Case 1/3 tests. No real key or secret literal (the only
  `sk-`/marker-shaped string is a synthetic value inside a test asserting it
  is NOT leaked into metadata).
- Real Gemini round-trip: **run successfully by the user**. No key was written
  to the repository. The key used for this test was later exposed in chat, so
  the user was instructed to revoke it and create a replacement; never reuse
  or request that disclosed credential. The replacement key lives only in a
  local gitignored `.env` at the project root (`GEMINI_API_KEY=...`), loaded by
  `scripts/hermes_smoke.py` before it checks the environment; an already-set
  `GEMINI_API_KEY` env var still wins. The key is entered by the user locally
  and is never requested in chat.

  ```json
  {
    "outcome": "ok",
    "run_meta": {
      "model": "gemini-3.7-flash",
      "prompt_version": "hermes-strategist/2026-09-03.1",
      "latency_ms": 6562.0,
      "repair_used": false,
      "validation_result": "valid",
      "usage": {
        "prompt_tokens": 358,
        "output_tokens": 92,
        "total_tokens": 819
      },
      "cost_usd": null
    },
    "proposal": {
      "action": "WAIT_FOR_PROVIDER_RETRY",
      "diagnosis": "Temporary failure due to insufficient funds with active provider retry eligibility",
      "rationale": "Provider retry is eligible and supported by evidence, allowing automated recovery without unnecessary customer friction",
      "confidence": 0.85,
      "proposed_wait_hours": 24,
      "message_intent": null
    }
  }
  ```

  Result: **live connectivity and structural validation PASS**. This does
  *not* establish a Case 3 semantic failure. The fixture sets
  `provider_retry_eligible=True` and `retry_outcome_recorded=True` (one prior
  retry failed) - a failed retry is not retry exhaustion, and a further
  provider-eligible wait can be a legitimate choice. The prior verdict that
  "another wait is not acceptable" and that policy must be changed to forbid it
  is withdrawn; no recovery-rule change is made in this task. What the next
  spec step must do: make the context contract distinguish *current* retry
  eligibility (a live provider fact) from *prior* failure count, and state what
  bounded additional waiting is permitted, before runtime integration. The SDK
  printed a non-fatal AFC recommendation before the JSON; no tool call or side
  effect occurred.

  Smoke-test instructions:
  1. `python -m pip install ".[gemini]"`  (installs `google-genai==2.22.0`
     and `python-dotenv==1.0.1`)
  2. put the key in `<project root>/.env` as `GEMINI_API_KEY=...` (a blank
     `.env` with just that line is created for you; it is gitignored) - or
     export `GEMINI_API_KEY` in the shell, which takes precedence
  3. `python scripts/hermes_smoke.py`  -> prints one JSON object with
     `run_meta` (model, prompt_version, latency, usage, validation_result,
     repair_used, bounded raw) and the parsed `proposal`. The key is never
     printed. On failure only `error_type` + `run_meta` are printed - never the
     raw exception message. Exit 0 = validated proposal, 1 = failure, 2 = no key.
  4. paste the JSON into the block above.

### Remaining limitations

- One real model call succeeded end to end, proving the transport and strict
  output path. The strategist chose `WAIT_FOR_PROVIDER_RETRY` again; with the
  fixture still asserting `provider_retry_eligible=True` this is a defensible
  choice, not a demonstrated bug. Open item is a *spec* clarification (current
  eligibility vs prior failure count; bounded further waiting), not a code
  fix - see "Exact next action".
- On timeout the daemon worker thread keeps running in the background until
  the transport call returns on its own; its result/exception is discarded
  and, being a daemon, it never blocks interpreter exit.
- `HermesStrategist` is not wired into `RecoveryEngine`; wiring + threading
  `StrategistRunMeta` into `AI_PROPOSAL` audit rows is a later task.
- `parse_proposal` validation is structural only (exact key set, types,
  enum, range, blank-message). Content rules (no URL / currency / provider
  id in `message_intent`) remain the engine's `_validate_proposal`
  responsibility, unchanged.
- If Hermes-Agent is still wanted, its Windows install needs
  `git config --global core.longpaths true` (+ OS long-path support) or a
  pre-clone-then-`pip install ./dir` flow; revisit only if the library's
  skills/curator features are actually needed for the demo.

### Exact next action

1. **Spec clarification only (no code):** in the context contract, separate
   *current retry eligibility* (a live provider fact - is another
   Razorpay-managed retry still scheduled/eligible now?) from *prior failed
   retries* (a count of what already happened). Define what bounded additional
   waiting Hermes may propose given each combination, and how many total waits
   a case may accumulate. Do **not** add a rule that forbids waiting after any
   failed retry - the fixture that produced the smoke result still legitimately
   has `provider_retry_eligible=True`.
2. Only after that clarification, decide whether any `authorize` / strategist
   change is warranted, and specify it as its own task.
3. A second live smoke is optional; the transport, parsing, and metadata path
   are already proven. If re-run, the user uses their replacement key in the
   local `.env`.
4. Then: slice 3 - FastAPI signed simulated ingress (**done - see Iteration
   07 below**).

## Iteration 08 — First runnable Case 3 demo (persistence + Gemini + UI)

Branch `feat/fastapi-simulated-ingress` (continued). One coherent operable
insufficient-funds case, offline-tested end to end. Cases 2/4/5 deliberately
not attempted.

### What now works (implemented + offline-tested)

- **Durable ledger.** `src/hermes/pg_ledger.py`: `PgLedger` wraps the tested
  `InMemoryLedger` (unchanged logic - all atomicity, event dedup, version/state
  guards, action-intent ordering, deterministic attribution, unique-payment
  accounting) and, after every mutating call, writes the whole ledger state as
  one JSON document through a `SnapshotStore` in a single committed
  transaction. Reads hit memory. A write failure rolls the in-memory state back
  to the last committed snapshot and raises. `PostgresSnapshotStore` = one
  JSONB row in a dedicated `hermes_demo` schema; `InMemorySnapshotStore` for
  tests. **The persisted logical clock and pending work survive restart**
  (`RecoveryEngine` now resumes `logical_clock()` from the ledger at
  construction; `run()` calls `ledger.advance_clock()`).
- **Repeatable non-destructive init.** `scripts/init_neon.py` -
  `CREATE SCHEMA/TABLE IF NOT EXISTS` + one `INSERT ... ON CONFLICT DO NOTHING`.
  No DROP/TRUNCATE/DELETE, nothing outside `hermes_demo`, safe to re-run, DSN
  never printed.
- **Runtime composition.** `src/hermes/runtime.py` `Settings.load(mode=)`
  loads the gitignored root `.env` (shell env wins), validates without printing
  any value (`describe()` reports presence only). `offline` = `InMemoryLedger`
  + `ScriptedStrategist`. `live` = `PgLedger` over `DATABASE_URL` +
  `HermesStrategist` over `GEMINI_API_KEY`; **missing credentials fail startup -
  live never falls back to scripted proposals.** `src/hermes/asgi.py` is the
  uvicorn entrypoint (`HERMES_MODE` env).
- **Gemini wired into the engine/policy seam.** In live mode the real
  `HermesStrategist` is the engine's strategist. The engine now appends a
  decision-linked `AI_MODEL_RUN` audit record (model, prompt version, latency,
  repair flag, validation result, token usage - never the prompt, customer
  data, or a credential) on every successful proposal and on strategist
  failure. Strict schema validation and ≤1 repair unchanged. `HermesStrategist`
  gained `max_in_flight` (default 2): a `BoundedSemaphore` slot is held until
  the model-call worker thread *finishes* (even one abandoned after a timeout),
  so repeated timeouts cannot pile up unbounded live threads.
- **Deterministic total wait/re-evaluation bound.** New `Case.total_wait_hours`
  accrues every authorized wait; `authorize()` blocks
  `WAIT_FOR_PROVIDER_RETRY` with `total_wait_bound_reached` once it hits
  `MAX_TOTAL_WAIT_HOURS = 72`. Current provider eligibility stays the primary
  gate; `retry_outcome_recorded` (history) never blocks a wait on its own -
  see POLICY_SPEC.md "Retry eligibility vs. prior failures".
- **Approved message templates.** `src/hermes/message_templates.py` -
  `_validate_proposal` rejects any `message_intent` not verbatim on the
  allowlist (the scripted strategist's own line is on it). No free-form
  generated customer copy reaches policy.
- **One Case 3 flow, honest.** `src/hermes/demo_fixtures.py` (labelled
  `SYNTHETIC_DEMO_FIXTURE` merchant context, envelope builders, `demo_sign`).
  `api.py` gains server-side `/demo/case`, `/demo/step` (`advance` /
  `retry_failed` / `capture`), `/demo/case/{id}` (projection + chronological
  timeline). Every simulated event is built + signed with the **demo** secret
  (never Razorpay's - `RAZORPAY_WEBHOOK_SECRET` stays blank/deferred) and goes
  through the same verified `_ingest`. Merchant consent/channel/history come
  only from the trusted synthetic fixture keyed by obligation id, never from
  the payload; absent -> contact denied. The capture step correlates the
  simulated payment id to the recovery link's own reference -> `hermes_assisted`
  (never implies the link settled the subscription). The demo shows the actual
  proposal and policy result; a strategist failure escalates the case and is
  shown, not papered over.
- **Minimal local UI.** `scripts/demo_ui.py` (Streamlit) talks only to the
  local FastAPI, holds no secret, disables buttons while a request is in
  flight. Controls: start fresh case, advance time / inject next outcome,
  inspect case + audit timeline, show proposal / policy / actions / attribution
  / simulated recovered value, reopen a persisted case by id.
- **Launcher.** `scripts/run_demo.ps1` starts uvicorn (background job) + the
  Streamlit UI on localhost; Ctrl+C stops the UI and the script stops the API
  job. Shutdown notes in the header.

### Changed / new files

- New: `src/hermes/{pg_ledger,runtime,asgi,demo_fixtures,message_templates}.py`;
  `scripts/{init_neon.py,demo_ui.py,run_demo.ps1}`;
  `tests/{test_pg_ledger,test_runtime,test_demo_flow,test_recovery_bounds,test_pg_integration}.py`.
- Modified: `src/hermes/protocols.py` (`Ledger.logical_clock` / `advance_clock`);
  `src/hermes/types.py` (`Case`/`CaseSnapshot`/`CaseProjection.total_wait_hours`,
  `StrategySnapshot.wait_hours_remaining`, `AUDIT_AI_MODEL_RUN`);
  `src/hermes/adapters.py` (`InMemoryLedger` clock methods; `total_wait_hours`
  accrual in `apply_evaluation`);
  `src/hermes/engine.py` (`MAX_TOTAL_WAIT_HOURS`, wait bound in `authorize`,
  clock resume/advance, `_note_model_run`, `logical_time` property, message
  allowlist in `_validate_proposal`);
  `src/hermes/hermes_strategist.py` (`max_in_flight` bounded slot);
  `src/hermes/api.py` (merchant-context registry, `_ingest` refactor,
  `/demo/case|step|case/{id}`, `razorpay` param);
  `pyproject.toml` (`[db]`, `[ui]`, `uvicorn` in `[api]`); `.env.example`
  (`DATABASE_URL`, `HERMES_DEMO_SIGNING_SECRET`, `HERMES_STRATEGIST_MODEL`,
  `HERMES_DEMO_SCHEMA`, deferred Razorpay keys as comments); `POLICY_SPEC.md`
  and `IMPLEMENTATION_SPEC.md` (wait bound, retry-eligibility-vs-history,
  message templates, obsolete "fresh isolated Hermes AIAgent" text corrected to
  the direct google-genai adapter, tracer sequence updated).

### Verification (offline)

- `python -m pytest -q` -> **201 passed, 1 skipped** (the skip is
  `tests/test_pg_integration.py`, which runs only with `HERMES_PG_TEST_DSN`
  set). The 174 prior tests are all still green; Case 1/3 *behaviour* is
  unchanged (they use the in-memory ledger and scripted strategist).
- Covered by the new tests: dump/hydrate round-trip of a full Case 3 ledger;
  `PgLedger` restart recovery + clock resume + a second case not erasing the
  first; write-failure rollback; `advance_clock` monotonicity; full API->engine
  Case 3 with a stubbed Gemini (happy path, `AI_MODEL_RUN` linkage + redaction,
  duplicate capture no double-count, second fresh case isolation, honest
  strategist-failure escalation, absent/present merchant context); `Settings`
  validation + no-secret `describe()` + live-requires-credentials +
  live-never-scripted + offline app `/health` + `/demo/case`; cumulative wait
  bound (unit + through the engine); off-allowlist message rejection; scripted
  message on allowlist; engine clock resume + no-backward.
- `python -m compileall -q src tests scripts` -> clean.
- `git diff --check` -> clean. Staged diff scanned: no real key / DSN / PEM;
  only test literals (`demosig_*`, `postgresql://u:p@h`, `SECRET-PW` inside a
  redaction assertion). `.env` remains gitignored and untracked (not opened).
- `uvicorn hermes.asgi:app` in offline mode: `/health` 200 `SIMULATED`,
  `/demo/case` + `/demo/step advance` verified via `TestClient` in-process
  (no server bound).

### Not verified live (the user runs these)

- No connection to Neon, no `CREATE`/`INSERT` executed, no schema created.
- No Gemini API call; the real `HermesStrategist` transport is unexercised
  end to end this iteration (its shape was probed against `google-genai 2.22.0`
  in a prior iteration).
- Streamlit is **not installed or import-checked** here (`[ui]` is range-pinned).
- `scripts/run_demo.ps1` (two-process launch) not executed.

### Exact user commands (PowerShell, one at a time)

```
cd C:\Users\dwish\Documents\Codex\2026-09-02\fors\outputs\ai-revenue-recovery
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[api,db,gemini,ui]"
Remove-Item Env:GEMINI_API_KEY -ErrorAction SilentlyContinue
```
Then put `GEMINI_API_KEY` (your replacement key) and `DATABASE_URL` (Neon
Connect-panel Postgres URL incl. `?sslmode=require`) in `.\.env`, and:
```
python scripts\init_neon.py
.\scripts\run_demo.ps1
```
Open the Streamlit URL it prints (127.0.0.1:8501). "Start a fresh Case 3",
then "Advance time" (eligible wait), "Inject failed retry", "Advance time"
(recovery link), "Simulate recovery payment". Then stop with Ctrl+C in the
launcher window (the script stops the API job); or `Get-Job | Stop-Job`.
Offline (no credentials): `.\scripts\run_demo.ps1 -Mode offline`.
Opt-in Postgres test: `$env:HERMES_PG_TEST_DSN = "<url>"; python -m pytest -q tests/test_pg_integration.py`.

### Limitations / next

- Snapshot-per-write ledger is demo-grade: correct and durable, but not
  row-per-entity and not built for concurrent writers. A future real Neon slice
  can migrate to normalized tables behind the same `Ledger` protocol.
- `merchant_manual` attribution still has no reachable path.
- Cases 2/4/5, real Razorpay Test Mode, real messaging - untouched.
- Next: user runs the live demo; then Codex review; then the Razorpay Test
  Mode hybrid slice.

## Iteration 07 — FastAPI signed simulated Razorpay ingress (slice 3)

- Branch: `feat/fastapi-simulated-ingress` off `feat/hermes-runtime-spike`
  HEAD `7ada2bb` (which is now on `origin`, together with `5bf44e6`, pushed
  in this session with explicit user authorization via the existing Git
  Credential Manager - `gh` CLI itself remained logged out and was not
  needed).
- Delivery adapter only. `RecoveryEngine.receive` / `run` / `inspect` stay the
  sole recovery-domain surface; no engine/types/adapters/protocols/strategist
  change; Case 1 & 3 tests untouched; no Case 1/3 business-outcome change.
- No real Razorpay / Gemini / Neon / SQLite / Streamlit / Docker / messaging /
  deployment. The webhook secret is injected, never file-stored, never a
  module global.

### Changed files

- `src/hermes/api.py` - **new**. `create_app(*, engine, config)` factory;
  `ApiConfig(webhook_secret, evidence_mode="SIMULATED")` (frozen, injected).
  `normalize_event()` turns a supported Razorpay-shaped failure/capture
  envelope into a typed `RazorpayWebhook`, stamping `evidence_mode="SIMULATED"`;
  unsupported event types or shapes raise `_UnsupportedEvent` -> HTTP 422.
  `_signature_ok()` does raw-bytes HMAC-SHA256 + `hmac.compare_digest`. No
  logging anywhere; error details are generic (no body/signature/secret/
  payment-id echoed). `fastapi` is imported at module top - the module is
  only importable with the `[api]` extra.
- `tests/test_api.py` - **new**, offline, `pytest.importorskip("fastapi")` /
  `("httpx")`, in-memory engine, locally signed fixtures, no network/creds.
- `tests/test_hermes_smoke.py` - the `fake_dotenv` stub now sets values via
  `monkeypatch.setenv` instead of mutating `os.environ` directly (the minor
  leak called out in the prompt).
- `pyproject.toml` - new optional `[api]` extra: `fastapi==0.117.1`,
  `httpx==0.28.1` (verified this iteration; full suite also green in an
  isolated venv against `fastapi==0.141.1`). Default `dependencies` and `dev`
  unchanged.
- `HERMES_RAZORPAY_RESEARCH.md` - new "Retry-state vocabulary" subsection
  (clarification only, no policy change) - see "Retry semantics" below.

### Endpoint contract

| Method + path | Behaviour |
|---|---|
| `GET /health` | `200 {"status":"ok","evidence_mode":"SIMULATED"}` |
| `POST /webhooks/razorpay` | Reads exact raw bytes. **Verifies `X-Razorpay-Signature` (HMAC-SHA256, constant-time) before any JSON decode** - bad/absent -> `401`, no data processed. Requires non-empty `X-Razorpay-Event-Id` -> else `400`. Malformed JSON (valid sig) -> `400`. Unsupported event type / shape -> `422`. Otherwise normalizes (stamping `SIMULATED`) and calls `engine.receive` once - **no recovery loop here**. `200 {"accepted","duplicate","case_id","event_id","evidence_mode"}`; a duplicate `event_id` returns `duplicate:true` with no new case/work/recovered value. |
| `POST /demo/run` | Body `{"until": <int logical hour>}`. Non-int / bool / float -> `400`. Backward time -> `409`. Else runs the engine loop and returns the `RunReport` fields. This is the **only** route that runs recovery. |
| `GET /cases/{case_id}` | `engine.inspect(CaseQuery(case_id=...))` as JSON (`dataclasses.asdict` of `CaseProjection`, `action_intents` included). Unknown id -> `404`. |

### Retry semantics (documentation only - no recovery-policy change)

Recorded in `HERMES_RAZORPAY_RESEARCH.md` -> "Retry-state vocabulary":
`provider_retry_eligible` = another provider-managed retry is *currently*
eligible; `retry_outcome_recorded` = at least one prior retry outcome exists
(not exhaustion); both can be true at once; a future provider integration must
distinguish current eligibility, prior attempt count, and next scheduled retry
from *retrievable provider evidence*, and must not invent a remaining-retry
count Razorpay does not expose. Whether a further wait is allowed after N
recorded failures stays an open policy question, unchanged here.

### Verification

- `python -m pytest -q` -> **133 passed** (107 unchanged: 36 Case 1 + 21
  Case 3 + 44 spike + 6 smoke; + 26 new API tests). Case 1/3 suites
  byte-for-byte untouched.
- Same suite in a fresh venv with the pinned `[api]` + `[gemini]` extras
  installed -> **133 passed, 1 warning** (an `anyio`/`starlette` internal
  `DeprecationWarning` from `starlette/testclient.py`; not our code; the
  module-level `filterwarnings` in `test_api.py` suppresses in-test warnings
  but not this import-time one).
- `python -m compileall -q src tests scripts` -> clean.
- `git diff --check` -> clean.
- Secret scan of the staged diff: only the test literal `whsec_simulated_test_only`
  and the identifier `webhook_secret`; no real key, token, or PEM.
- `.env` remains gitignored (`.gitignore:20`) and untracked; not opened,
  printed, modified, or committed by this task.

### Decisions

- One optional extra per concern (`[gemini]`, `[api]`); neither in default or
  `dev`. API tests skip cleanly without `[api]`.
- Merchant facts (`customer_notify`/`consent`/`reachable_channel`) are **not**
  read from the Razorpay payload - they are not Razorpay data. *(Corrected in
  the correction pass below: normalization now sets `consent=False` and
  `reachable_channel=False` explicitly rather than inheriting the permissive
  `RazorpayWebhook` defaults.)* A merchant-context ingress is a later slice.
- The obligation id is `payload.subscription.entity.id`; a fixture without it
  is `422` (unsupported shape) rather than a guessed fallback.
- `evidence_mode` is an `ApiConfig` field defaulting to `"SIMULATED"`; this
  slice never produces `REAL_TEST_MODE` (that is slice 5).

### Limitations

- Only `payment.failed` / `payment.captured` envelopes are normalized;
  everything else is `422` by design.
- No FastAPI dependency in the base install; `pip install ".[api]"` is
  required to run the app or its tests.
- The real Gemini strategist is **not** wired into the app (still
  `ScriptedStrategist` behind the engine); that is a later step.
- No persistence: the engine (and its logical clock) is per-process and
  in-memory. Neon is next.

### Correction pass — safe simulated-ingress boundaries + credential prep

One consolidated pass (commit `fix(api): enforce safe simulated ingress
boundaries`). Only `src/hermes/api.py`, `tests/test_api.py`, `.env.example`,
`HANDOFF.md`. No engine/types/adapters/protocols/strategist change; Case 1/3
tests untouched.

1. **Configuration** - `ApiConfig` now validates on construction *and*
   `create_app` re-validates before wiring routes: a blank/whitespace
   `webhook_secret` raises `ValueError`; any `evidence_mode` other than the
   literal `"SIMULATED"` (incl. `REAL_TEST_MODE`) raises `ValueError`. There is
   no real/Test Mode path in this adapter.
2. **Currency** - `payload.payment.entity.currency` must be exactly three
   uppercase ASCII letters (`\A[A-Z]{3}\Z`). Missing / non-string / blank /
   malformed -> `422`, no case created. **Never defaulted to `INR`.**
3. **Missing merchant context** - normalization now sets `consent=False` and
   `reachable_channel=False` explicitly (was silently inheriting the permissive
   `RazorpayWebhook` defaults). Payment-payload `consent` / `reachable_channel`
   / `merchant_context` fields are ignored. Authorized customer communication
   will require a future **trusted merchant-context source** (the merchant's
   own contract/consent records) - not built here, and the domain defaults for
   non-API callers are unchanged (change is at the ingress boundary only).
4. **Invalid request handling** - the `X-Razorpay-Signature` value is
   format-checked (`\A[0-9a-fA-F]{64}\Z`) *before* `hmac.compare_digest`;
   missing / non-ASCII / wrong-length values now return `401` instead of
   raising a `TypeError`. `/demo/run` rejects any non-object JSON body
   (arrays, `null`, strings, numbers, booleans) with `400` and never touches
   the engine. Raw-byte signature verification still precedes webhook JSON
   parsing.
5. **Safe errors** - all client-facing error strings are fixed module
   constants; unsupported events, malformed JSON, and bad signatures never
   echo the caller's event value, raw body, signature, identifiers, or an
   exception message. A `422` for an unsupported event carrying a synthetic
   sensitive marker does not return the marker.

### Credential preparation (no live calls made)

`.env.example` now carries two blank entries plus comments:

```
GEMINI_API_KEY=
DATABASE_URL=
```

- **`GEMINI_API_KEY`** - the user's **replacement** Gemini key. The key
  exposed earlier in chat must stay revoked and must never be reused.
- **`DATABASE_URL`** - the Postgres connection string copied from the user's
  **Neon project -> Connect panel**, including the TLS parameters Neon
  supplies (e.g. `?sslmode=require`). The planned ledger (slice 4) speaks
  ordinary **Postgres** - it is *not* a Neon management/API key and *not* a
  new REST integration.
- The user adds both values themselves to the existing gitignored
  project-root `.env` and then just says "ready". This task did not open,
  read, print, or modify `.env`.
- **Shell env overrides `.env`.** If an old `GEMINI_API_KEY` is exported in
  the shell it wins over the file - clear it (`unset GEMINI_API_KEY` /
  `Remove-Item Env:GEMINI_API_KEY`).
- No Gemini call, no Neon connection, no tables, no migration - credential
  prep is not a blocker for finishing these offline fixes and neither
  integration is claimed complete.

### Verification (post-correction)

- `python -m pytest -q` -> **174 passed** (133 from Iteration 07 + 41 new API
  regression tests). Case 1/3 suites still byte-for-byte untouched.
- `python -m compileall -q src tests scripts` -> clean.
- `git diff --check` -> clean.
- Secret scan of tracked changes: only the test literal
  `whsec_simulated_test_only`, the identifier `webhook_secret`, and the two
  **blank** `.env.example` keys; no real key / token / connection string / PEM.
- `.env` remains gitignored (`.gitignore:20`) and untracked; confirmed
  without opening it.

### Exact next action

1. User adds the two blank credentials to their local `.env` (see "Credential
   preparation" above) and replies "ready".
2. Codex review of Iteration 07 + this correction pass (diff
   `feat/hermes-runtime-spike..feat/fastapi-simulated-ingress`).
3. Then slice 4 - **Neon persistence + Gemini strategist integration**:
   implement the `Ledger` contract against Postgres/Neon (webhook inbox,
   cases, due work, proposals, policy decisions, action intents/outcomes,
   audit, attribution, persisted logical clock) using `DATABASE_URL`; wire
   `HermesStrategist` behind the engine using `GEMINI_API_KEY`. SQLite only
   if Neon blocks the deadline.

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
