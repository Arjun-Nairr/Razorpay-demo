# Cross-Agent Handoff — FULL ARCHIVE (frozen 2026-09-04)

> This is the historical, append-only record of Iterations 01-12. The live
> current-state index is `HANDOFF.md` (kept under 300 lines). Facts here are
> preserved as written at the time; where a later iteration corrected them the
> correction is in `HANDOFF.md` / the newer iteration entry, not edited in
> place here.
>
> **SUPERSEDED CLAIM:** Iteration 12's status/blocker asserts a *confirmed Neon
> outage/cold-start*. That was **never established and is now disproven**
> (Iteration 13): the stalls were an **IPv6 black hole** on this host (dead
> AAAA route, ~21 s per SYN before IPv4 fallback) plus, for the Gemini call, a
> local **Avast "Web/Mail Shield" TLS-interception root** absent from the
> `certifi` bundle. Neon itself connects in ~3 s once IPv4 is used. Treat every
> "Neon outage" phrasing below as unproven.

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
- Status: **Iteration 12 - hermes-mode startup fix (bounded DB connect)** on
  `feat/isolated-hermes-agent` (baseline `c0e59fd`). **Cause of the silent
  `run_demo.ps1 -Mode hermes` stall:** `PostgresSnapshotStore.__init__` called
  `psycopg.connect(dsn)` with **no timeout**; Neon serverless holds the
  connection open while it resumes suspended compute (measured 25s to >75s,
  variable), so `import hermes.asgi` never finished, uvicorn never printed its
  banner, and the launcher's 15 s health poll aborted with no output. Both the
  direct `.venv` launch and the background job hit the same hang (the job also
  used a bare `python` that resolved to the system interpreter, which happens
  to have fastapi/uvicorn/psycopg installed). **Fix:** `_connect_bounded` in
  `pg_ledger.py` bounds each connect attempt and retries within a finite total
  (defaults 55 s/attempt, 3 attempts, 150 s total; env-overridable
  `HERMES_DB_CONNECT_TIMEOUT_S` / `HERMES_DB_CONNECT_ATTEMPTS`), raising a
  sanitised `RuntimeError` (never the DSN) that `asgi.py` already turns into a
  one-line stderr message + `SystemExit(1)`. `run_demo.ps1` now uses
  `.venv\Scripts\python.exe` explicitly for uvicorn **and** Streamlit, and
  waits a mode-aware bounded time (offline 20 s, live/hermes 100 s) that exits
  immediately when the job dies. Also removed the standalone `SEND_REMINDER`
  from the strategist-facing contract (child `_SUPPORTED_ACTIONS`, parent
  `_POLICY_SUPPORTED_ACTIONS`, `SKILL.md`) - policy only ever BLOCKs it;
  reminder copy still attaches to `CREATE_RECOVERY_LINK` via `message_intent`.
  Actual Hermes mode, pinned runtime, isolated home, tool limits, deterministic
  policy, and no-fallback all preserved.
  **Verification:** offline `python -m pytest -q --ignore=tests/test_hermes_agent.py`
  -> **230 passed, 3 skipped** (`+5` bounded-connect regressions in
  `test_pg_ledger.py`: hang is bounded, retry-then-give-up is sanitised with no
  DSN, transient-fail-then-success, fast path still works, env overrides);
  real-Hermes harness `tests/test_hermes_agent.py` -> **28 passed**; compileall
  + `git diff --check` clean. `import hermes.asgi` in `hermes` mode now **fails
  fast with the sanitised line instead of hanging** (proven).
  **BLOCKER (external): the live Case 3 was NOT executed.** The Neon endpoint
  stopped accepting connections during this session - one connect succeeded
  early (~47 s), then every attempt since (bounded 75 s, 150 s, 180 s, and a
  raw 5-minute `psycopg.connect`) hung with no response and no error. This is a
  Neon-side outage/suspension, not a code fault; the startup fix correctly
  refuses to hang on it. **Next action for the user:** once Neon accepts
  connections again, run `.\scripts\run_demo.ps1 -Mode hermes` (or the one-shot
  below) then `python scripts\neon_proof.py` - the launch is now reliable and
  self-diagnosing. No recovery is claimed.
- Prior status: **Iteration 11 - reviewed-Hermes-blocker corrections + visible
  Neon proof path** on `feat/isolated-hermes-agent` (baseline `48de227`). Ten
  review items fixed on the Iteration 10 isolated real-Hermes integration:
  (1) the unauthorized-tool test uses a harmless sentinel + a canary-file
  isolation assertion (never a destructive host command); `test_asgi_startup`
  neutralises `.env` loading and builds synthetic Settings.
  (2) the child's deadline watchdog is a daemon Timer cancelled on every normal
  path - a clean decision returns promptly, not at the deadline; the parent
  rejects any child exit code other than 0/1 even when stdout claims success;
  the 8-model-iteration budget is now shared across the initial reasoning AND
  the single repair (a fresh capped agent for the repair; tool budget already
  shared), not 8 per `run_conversation`.
  (3) raw diagnostics removed: no `stderr_tail`, no raw exception/`error`
  strings anywhere (child, parent, smoke). Fixed failure CATEGORIES + an
  allowlisted, bounded audit (`_sanitize_audit`); `unresolved_uncertainty`
  (which had been the whole rationale) is gone, replaced by
  `confidence_basis` + `decision_action`. Synthetic secrets in model output /
  child exceptions / malformed output never reach console or audit (tested).
  Smoke exits nonzero on failure and is described as "one decision may take
  several model requests".
  (4) the child now receives the approved message templates explicitly and
  validates message choice + strict field types inside the one-repair boundary
  (boolean confidence, zero/negative WAIT, wrong types, missing/extra keys,
  unapproved message, non-JSON, and JSON-embedded-in-prose all rejected - no
  silent coercion, no extraction). `PROMPT_VERSION` -> `hermes-agent/2026-09-05.1`.
  (5) `get_recovery_actions` returns THIS case's ACTUAL prior activity (a
  bounded redacted audit projection built by the engine via
  `_case_history_projection`) plus a separately-labelled catalog of only the
  actions deterministic policy can execute (no STOP). `get_payment_history` is
  now ONE optional expansion straight to twelve months (6-month option removed),
  needs a >=8-char uncertainty reason, is callable at most once (incl. during
  repair), and reports ACTUAL / partial coverage. A deterministic terminal
  `ESCALATE` transition was added (`authorize` -> `PolicyOutcome.ESCALATE` ->
  `apply_evaluation` sets `escalated`/`unrecovered`, cancels pending work) so
  an "evidence inadequate" outcome has a real safe path, never a faked one
  (regression tests added). Synthetic history is supplied only when a trusted
  `DEMO_CASE_PROVENANCE` record exists (`StrategySnapshot.is_demo_case`);
  unknown cases inherit no fictional records. Synthetic date/outcome labels are
  now derived from the day delta so they never disagree.
  (6) **visible Neon proof**: `sql/neon_demo_inspect.sql` (checked-in,
  read-only, `hermes_demo` schema, matches the JSON snapshot shape, safe while
  the writer lock is held) projects case id/status/recovered amount, the
  chronological audit timeline, and the actual Hermes tool evidence / proposal
  / policy result. `scripts/neon_proof.py` (stdlib only, existing endpoints
  only) creates one case, pauses for a pre-Hermes Neon inspection, runs ONE
  real Hermes decision, shows its persisted `AI_MODEL_RUN` audit, then advances
  the simulated outcome steps only when the case state permits.
  Storage architecture unchanged (JSON snapshot ledger). No dashboard redesign;
  the existing panel's stale fields were pointed at the new audit keys.
  **No silent fallback to direct Gemini.** Offline verified: full suite +
  parent-shape Hermes tests + real-Hermes harness with a stubbed transport +
  compileall + `git diff --check` + local API startup + the CLI path
  (`--no-hermes`). **Live end-to-end NOT verified** - the user runs
  `scripts/hermes_agent_smoke.py` then `scripts/run_demo.ps1 -Mode hermes` +
  `scripts/neon_proof.py` and views the rows via `sql/neon_demo_inspect.sql`.
- Prior status: **Iteration 10 - isolated REAL Nous Hermes runtime for one
  Case 3 decision** on `feat/isolated-hermes-agent` (branched from `f9b640e`).
  New `hermes` execution mode driving the actual `run_agent.AIAgent` (checkout
  `e02d1e41`) in an isolated subprocess with three case-scoped tools, bounded
  iterations/tool-calls/deadline, one repair, one in-flight decision, and
  bounded redacted audit metadata. Offline harness (real AIAgent + stub
  transport) verified; live unverified. Superseded by the Iteration 11
  corrections above.
- Prior status: **Iteration 09 - reviewed-demo-blocker corrections + first
  user-run end-to-end test prep** on `fix/runnable-demo-boundaries` (branched
  from `d2e6572`). Six review blockers fixed: (1) full demo state survives an
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

## Iteration 12 — hermes-mode startup fix (bounded DB connect)

Baseline `c0e59fd`. Implementation + verification only; storage unchanged.

### Cause (bounded diagnosis)

`run_demo.ps1 -Mode hermes` "failed its health check without startup output".
`python -X faulthandler -c "import hermes.asgi"` (HERMES_MODE=hermes, 35 s
dump) showed the process blocked in:

```
psycopg/waiting.py:112 wait_conn  <-  psycopg/connection.py:109 connect
  <-  hermes/pg_ledger.py:163 PostgresSnapshotStore.__init__
  <-  hermes/runtime.py build_ledger  <-  build_app  <-  hermes/asgi.py:<module>
```

`psycopg.connect(dsn)` had **no timeout**. Neon serverless keeps the socket
open while resuming suspended compute; a raw `socket.create_connection` to the
endpoint took **45 s** and `psycopg.connect` **47 s** in one measurement, and
other attempts never completed. So `import hermes.asgi` never returned, uvicorn
never bound / printed its banner, and the launcher's `30 x 500 ms` health poll
gave up first - hence "no startup output". The launcher's background job also
ran a bare `python` that resolved to the **system** interpreter (which also has
fastapi/uvicorn/psycopg installed) rather than the project `.venv`.

### Changes

- `src/hermes/pg_ledger.py` - `_connect_bounded` / `_connect_once`: each
  `psycopg.connect` runs in a daemon thread joined with a per-attempt ceiling
  (55 s), retried up to 3 times within a finite total (150 s default). Timeout
  or error -> `RuntimeError` naming only the exception **type** and the knobs
  (`HERMES_DB_CONNECT_TIMEOUT_S`, `HERMES_DB_CONNECT_ATTEMPTS`) - never the DSN.
  `PostgresSnapshotStore.__init__` gains `connect_timeout_s`. `asgi.py` already
  converts a startup `RuntimeError` to a sanitised one-liner + `SystemExit(1)`.
- `scripts/run_demo.ps1` - resolves `$repo\.venv\Scripts\python.exe` (falls
  back to PATH `python`) and uses it for uvicorn **and** Streamlit; passes it +
  `PYTHONPATH` into the job; mode-aware bounded health wait (offline 20 s,
  live/hermes 100 s) via a stopwatch loop that still breaks immediately when
  the job state is Failed/Completed; reports elapsed + job state on abort.
- `src/hermes/hermes_agent/child_main.py`, `hermes_agent_strategist.py`,
  `config/hermes_agent/SKILL.md` - standalone `SEND_REMINDER` removed from the
  strategist-facing action set / catalog / skill (policy only BLOCKs it;
  reminder copy still rides `CREATE_RECOVERY_LINK` `message_intent`).
- `tests/test_pg_ledger.py` - `_FakePsycopg` accepts `**kwargs` / `delay_s` /
  `raises`; `+5` regressions: hang is bounded (returns in <6 s, not 20 s);
  retry-then-give-up is sanitised and DSN-free and total-bounded;
  transient-fail-then-success on the 2nd attempt; fast path still works and
  forwards a libpq `connect_timeout`; env vars override total + attempts.

### Verification

- `python -m pytest -q --ignore=tests/test_hermes_agent.py` -> **230 passed,
  3 skipped**.
- `python -m pytest -q tests/test_hermes_agent.py` -> **28 passed** (real
  Hermes child + stub transport; SEND_REMINDER removal caused no regression).
- `python -m compileall -q src tests scripts` clean; `git diff --check` clean.
- `HERMES_MODE=hermes python -c "import hermes.asgi"` now **exits fast with the
  sanitised startup line** instead of hanging (verified repeatedly).
- **Live Case 3 NOT run** - Neon endpoint unresponsive this session (see the
  status bullet / blocker). No fabricated recovery.

### Remaining blocker

External: the Neon compute for the demo project was not accepting connections
by the end of this session. When it is back, one repeatable launch:

```
$repo\.venv\Scripts\python.exe -m uvicorn hermes.asgi:app --host 127.0.0.1 --port 8000
```

(or `.\scripts\run_demo.ps1 -Mode hermes`), then `python scripts\neon_proof.py`;
inspect with `sql\neon_demo_inspect.sql` (schema `hermes_demo`). If a cold
resume needs longer than 150 s, `setx`/`$env:HERMES_DB_CONNECT_TIMEOUT_S`.

## Iteration 11 — Hermes-blocker corrections + visible Neon proof

Baseline `48de227` on `feat/isolated-hermes-agent`. Implementation + verification
only. Storage architecture unchanged.

### Changed / new files

- `tests/test_hermes_agent.py` - rewritten: harmless sentinel + canary-file
  isolation assertion; strict-contract rejection matrix (boolean confidence,
  zero WAIT, wrong types, extra key, STOP, JSON-in-prose); single-12m-expansion,
  partial-coverage, unknown-case-no-history, prior-activity, secret-never-leaks;
  parent-shape tests with a faked `subprocess.run` (abnormal-exit rejection,
  allowlisted secret-free audit, no-result failure) that need no runtime.
- `tests/test_asgi_startup.py` - child no-ops `_load_dotenv` and starts from a
  minimal env; no real credential is read.
- `tests/test_recovery_bounds.py` - `+` two ESCALATE regressions (authorize
  permits it; it makes a real terminal transition, persisted, never a blocked
  no-op).
- `src/hermes/hermes_agent/child_main.py` - daemon watchdog cancelled in
  `finally`; shared 8-iteration budget across initial + repair (fresh capped
  agent for the repair); strict single-object JSON parse (no prose extraction);
  `_validate` rejects bool confidence / non-positive WAIT / unapproved message /
  key mismatch / unknown+unsupported action; fixed failure categories +
  allowlisted audit; `get_payment_history(reason)` single 12m expansion with
  actual/partial coverage; `get_recovery_actions` returns prior activity +
  labelled executable-actions catalog.
- `src/hermes/hermes_agent/__init__.py` - `MAX_HISTORY_REQUESTS = 1`.
- `src/hermes/hermes_agent_strategist.py` - `PROMPT_VERSION` bump; passes
  `approved_messages`; `_sanitize_audit` (allowlist, bounded, no `stderr_tail`);
  rejects child exit codes outside {0,1}; fixed parent failure categories;
  `_evidence_bundle` gates synthetic history on `snap.is_demo_case`, single
  12-month window with `history_months_available` (partial), day-delta-derived
  outcome labels, `prior_case_activity` from `snap.case_history`, policy-only
  `allowed_actions`.
- `src/hermes/types.py` - `StrategySnapshot.is_demo_case` + `case_history`.
- `src/hermes/engine.py` - `_is_demo_case` / `_case_history_projection`
  (bounded, redacted, via `audit_projection`); `authorize` -> ESCALATE branch.
- `src/hermes/adapters.py` - `apply_evaluation` performs the ESCALATE terminal
  transition (state `escalated`, attribution `unrecovered`, pending work
  cancelled).
- `src/hermes/asgi.py` - docstring covers `hermes` mode.
- `config/hermes_agent/SKILL.md` - rewritten for the new contract (single 12m
  expansion, executable actions only incl. ESCALATE, confidence basis).
- `scripts/hermes_agent_smoke.py` - nonzero exit on failure, safe output with
  no metadata, allowlisted fields, "several model requests" wording.
- `scripts/demo_ui.py` - panel points at the new audit keys (no
  `unresolved_uncertainty`).
- `sql/neon_demo_inspect.sql` - NEW read-only inspection queries.
- `scripts/neon_proof.py` - NEW user-run CLI over the existing local API.

### Verification (offline, this machine)

- `python -m pytest -q --ignore=tests/test_hermes_agent.py` -> **225 passed,
  3 skipped** (`+2` ESCALATE regressions).
- `python -m pytest -q tests/test_hermes_agent.py` (real Hermes child + stubbed
  OpenAI-compat transport; 5 parent-shape / bundle tests need no runtime) ->
  **28 passed in ~4.8 min**.
- `python -m compileall -q src tests scripts` clean; `git diff --check` clean.
- Local API startup: `hermes` mode fails cleanly without creds
  (`SystemExit(1)`, sanitised line). `scripts/neon_proof.py --no-hermes --yes`
  against the offline API creates + persists one case (exit 0); without
  `--no-hermes` against a non-hermes API it aborts with a clear message
  (exit 2).
- **NOT verified live.** No live Gemini / Neon / Razorpay call was made; no
  credentials were read or printed.

### Limitations

- The offline harness proves the real Hermes tool loop + every bound with a
  stub transport; it does not prove live Gemini semantics or Neon persistence
  under `hermes` mode - user-run.
- `_case_history_projection` is a bounded (last 25) typed slice; it is not a
  full event log.
- The `hermes` demo path is still manual-control only; automatic queue
  wake-ups / sweeps / batch evaluation remain deferred.
- `_DEFAULT_CHECKOUT` / `_DEFAULT_PYTHON` default to this machine's install
  path (env-overridable).

### Exact next action

The user runs the live proof (commands below): `scripts/hermes_agent_smoke.py`,
then `scripts/run_demo.ps1 -Mode hermes` + `scripts/neon_proof.py`, viewing the
persisted rows with `sql/neon_demo_inspect.sql`. Then Codex review of
Iteration 11.

## Iteration 10 — Isolated real Nous Hermes runtime, one Case 3 decision

Branch `feat/isolated-hermes-agent` from `f9b640e`. Codex's untracked
`HERMES_ISOLATED_AGENT_RESEARCH.md` is preserved and committed with this
milestone's docs.

### What was built

- **`src/hermes/hermes_agent/child_main.py`** - runs INSIDE the installed
  Hermes venv as a subprocess. Reads one JSON job on stdin, registers exactly
  three case-bound tools under a custom `revenue_recovery` toolset, asserts
  `agent.valid_tool_names == {those three}` (any other dispatch is rejected by
  the real loop), builds a fresh `run_agent.AIAgent` (`openai-compat` + a
  caller-supplied stub base_url for the offline harness, or native `gemini`
  provider for live), drives `run_conversation` with `max_iterations=8`, does
  at most one schema-repair turn on the *remaining* budget, and prints
  `HERMES_CHILD_RESULT {json}` (proposal + bounded audit, or error + audit).
  Only stdlib + Hermes runtime imports - never the `hermes` project package.
- **`src/hermes/hermes_agent_strategist.py`** - `HermesAgentStrategist`
  (`Strategist` seam, parent side). Verifies `git -C <checkout> rev-parse HEAD`
  == `e02d1e41...` on construction (`HermesRuntimeUnavailable` otherwise);
  prepares the gitignored `HERMES_HOME` (writes `config.yaml` with
  `tools.tool_search: false` so the three tools are exposed directly);
  builds the immutable evidence bundle (coherent synthetic 12-month history for
  the demo customer, shorter windows are trailing subsets, 3-month subset in the
  initial context); spawns the child with `cwd=<checkout>`, a minimal env (no
  `DATABASE_URL` / Razorpay / unrelated keys; `GEMINI_API_KEY` only in live
  mode), `timeout=90` (reaps a timed-out child), one-in-flight
  `BoundedSemaphore`. Maps the child result to `StrategyProposal` or raises
  `InvalidProposal` / `TimeoutError` (engine's existing bounded-failure path).
  `last_run_meta` is a `HermesRunMeta` whose `.extra` carries the child audit.
- **`config/hermes_agent/SKILL.md`** - tracked project skill (evidence-gathering
  + safe-proposal rules), passed explicitly as `skill_text`, never via skill
  discovery.
- **`engine.py`** - `_note_model_run` merges `meta.extra` into
  `AI_MODEL_RUN.detail["hermes"]` (bounded redacted fields only).
- **`runtime.py`** - `Settings` mode is `offline | live | hermes`; `hermes`
  requires `GEMINI_API_KEY` + `DATABASE_URL`; `build_strategist` ->
  `HermesAgentStrategist` for `hermes` (no silent Gemini fallback);
  `build_ledger` uses Postgres for `live` and `hermes`; `mode_label`
  `hermes-runtime`.
- **`scripts/demo_ui.py`** - "Actual Hermes runtime" panel (model, revision,
  decision time, uncalibrated confidence band + disclaimer, evidence
  requests + reasons, returned source/coverage, unresolved uncertainty, stop
  reason, tokens). **`scripts/run_demo.ps1`** - `-Mode hermes`.
- **`scripts/hermes_agent_smoke.py`** - user-run: one real Case 3 decision
  through actual Hermes + real Gemini, prints sanitized run evidence. No DB /
  Razorpay / messages / charges / links.

### Bounds and contract

6 tool executions, 8 model iterations, one 90 s subprocess deadline, <=1 schema
repair (budget not reset), one in-flight decision. `get_payment_history` takes
only 6 or 12 months, needs a >=3-char uncertainty reason, at most two requests,
rejects duplicate windows and no-progress repeats, returns `available:false`
(not invented rows) when the window is unavailable, and never overrides current
provider facts or consent. The engine's `_validate_proposal` + deterministic
policy remain the final authority; confidence never grants a permission and is
never required to rise after more evidence.

### Verification

- **Offline harness (this machine):** `tests/test_hermes_agent.py` - each test
  spawns the ACTUAL child (`run_agent.AIAgent` + its real tool loop) against a
  local OpenAI-compatible **stub transport**; skipped (not failed) when the
  installed runtime is absent or != the proven revision. Covers: real
  AIAgent import/instantiation + tool loop returning a validated proposal;
  legitimate no-extra-lookup path; coherent 6/12-month windows +
  duplicate/no-progress rejection; unavailable history not invented;
  unauthorized-tool-call rejection; forged `case_id`/SQL argument ignored; one
  repair then success; repeated invalid -> bounded `InvalidProposal` with
  `stop_reason=schema_repair_failed`; single-decision-in-flight -> `TimeoutError`;
  short subprocess deadline reaps the child; wrong-revision refusal.
  Result: **11 passed in ~7.6 min** (each test spawns the real runtime).
- **Full offline suite unaffected:** `python -m pytest -q --ignore=tests/test_hermes_agent.py`
  -> **223 passed, 3 skipped**.
- **NOT verified live:** no live Gemini/Neon/Razorpay call was made here.
  Live proof is user-run (`scripts/hermes_agent_smoke.py`, then
  `scripts/run_demo.ps1 -Mode hermes` against Neon).

### Limitations

- The offline harness proves the real Hermes tool loop and every bound with a
  stub transport; it does not prove live Gemini semantics or Neon persistence
  under `hermes` mode - user-run.
- Each child spawn pays the Hermes import cost (~7-15 s); the 90 s deadline
  accommodates it. Manual demo controls only this milestone.
- `iterations_used` / `tokens` are surfaced only if the installed runtime
  returns them in the `run_conversation` result dict; absent -> `null`.

### Exact next action

User runs the two live commands below; then Codex review of Iteration 10; then
automatic scheduling (queue wake-ups, sweeps, batch) and the remaining golden
cases.

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

---

## Iteration 14 archived detail (moved from HANDOFF.md during Iteration 15)

### Startup & connectivity (Iteration 13, refined in 14)

The `run_demo.ps1 -Mode hermes` "silent stall" had two local causes, fixed in
Iteration 13; the earlier "Neon outage" claim is superseded/unproven.

1. IPv6 black hole. `getaddrinfo` returned AAAA first; each dead IPv6 SYN cost
   ~21s before libpq fell to IPv4 (~0.1s). Fix: `pg_ledger` resolves an IPv4
   and passes it as libpq `hostaddr` (TLS still verifies the cert against
   `host`; `sslmode`/`channel_binding` from the DSN untouched). Real Neon now
   connects in ~3s. Iteration 14: the resolution itself is now bounded (a hung
   resolver used to block before the deadline clock even started; it now
   shares the same startup budget and falls back to unresolved on stall).
2. TLS interception. Avast "Web/Mail Shield" re-signs
   `generativelanguage.googleapis.com` with a local root absent from the child
   venv's certifi, so the Gemini call failed verification. Fix: the parent
   writes a CA bundle (certifi + the OS trust store) into the gitignored
   isolated home and hands it to the child via SSL_CERT_FILE /
   REQUESTS_CA_BUNDLE / CURL_CA_BUNDLE / GRPC_DEFAULT_SSL_ROOTS_FILE_PATH.
   Iteration 14: the bundle now imports only OS-store certs that carry
   x509_asn encoding AND are trusted for TLS server-auth (1.3.6.1.5.5.7.3.1) -
   the first cut imported every OS root regardless of purpose/encoding. The
   on-disk cache is versioned (_CA_BUNDLE_VERSION) so any previously-written
   broad bundle is discarded and rebuilt immediately. Override with
   HERMES_CA_BUNDLE.
3. Encoding. The parent decodes the child's streams as UTF-8
   (errors="replace"); Windows cp1252 was dropping the result line (spurious
   no_result_line).
4. One bounded startup budget, now covering DNS too. HERMES_DB_CONNECT_TIMEOUT_S
   (default 30s) bounds DNS pre-resolution + connect + the advisory-lock probe
   + the first snapshot read together; run_demo.ps1 waits that budget + 30s
   fixed margin. The launcher uses .venv\Scripts\python.exe explicitly for
   uvicorn and Streamlit.
5. Timeout cleanup no longer risks blocking on a busy connection. After a
   writer-lock-probe (or first-read) timeout, the probe's own thread may still
   be mid-query on that connection; psycopg serialises access to a connection
   with its own lock, so a synchronous rollback()/close() from the main thread
   would wait for that stuck query. A genuine timeout (_BoundedTimeout) now
   only schedules a best-effort close on its own daemon thread; a real
   completed error (thread already finished) still gets a synchronous
   rollback+close.
6. Late-connection race closed. _connect_once's worker and the timed-out
   caller now decide the connection's fate under one lock instead of an
   independent Event check on one side and is_alive() on the other.
7. Startup failures still exit fast with one sanitised stderr line + nonzero
   code (never the DSN); only positively-identified project processes were
   ever stopped.

### Verified evidence (Iteration 13/14)

- Offline: `python -m pytest -q --ignore=tests/test_hermes_agent.py` -> 237
  passed, 3 skipped. Real-Hermes harness -> 33 passed (~5 min). compileall +
  git diff --check clean. Iteration 14 added +4 test_pg_ledger.py regressions
  (bounded DNS, bounded first read, timeout cleanup does not touch a busy
  connection, late-connection race at the exact boundary - 50-trial
  deterministic interleaving) and +4 test_hermes_agent.py regressions (CA
  bundle: server-auth-trusted cert included, restricted-purpose cert
  excluded, unsupported encoding skipped, previously-generated broad bundle
  rebuilt).
- LIVE, end-to-end (actual Hermes -> Gemini -> deterministic policy ->
  simulated payments -> Neon), Iteration 13, re-verified read-only in 14: case
  `case-11` / obligation `sub_demo_0003_9bc1578f`. Two real gemini-3.7-flash
  decisions (validation_result=valid, 2 evidence tool calls each, ~16s each):
  WAIT_FOR_PROVIDER_RETRY -> policy ALLOW (provider_retry_permitted); then
  after a simulated failed retry, CREATE_RECOVERY_LINK -> policy ALLOW
  (recovery_link_authorized_message_authorized) -> action intent + outcome.
  Simulated capture on the uniquely-correlated link -> TERMINAL_TRANSITION.
  Iteration 14 re-read this SAME case, read-only, direct psycopg, one bounded
  query, no writes, no advisory lock taken: state=recovered,
  attribution=hermes_assisted, counted=true, both AI_MODEL_RUN records
  validation_result=valid, both POLICY_DECISION records outcome=ALLOW,
  linked_payment_id=rlnk_case-11:CREATE_RECOVERY_LINK. Case's own contribution
  recovered_minor=1,000,000 vs the ledger-wide aggregate recovered_minor=
  1,000,000 across cases=3/recovered_cases=1 - same number here only because
  exactly one case has recovered so far; they are different fields.
- Two earlier cases from Iteration 13 (case-1, case-6) are honest failures
  from the two defects fixed there (UTF-8 decode; Avast TLS) and were left
  escalated/unrecovered - not drained or retried; only case-11 ever reached
  recovered.

---

## Iteration 15 archived detail (moved from HANDOFF.md during Iteration 16)

### Razorpay Test Mode - HYBRID slice, first cut (Iteration 15, offline-tested only)

Per RAZORPAY_TEST_SLICE.md. The simulated SaaS obligation, its 3/12-month
history, and the accelerated failure/retry sequence stayed unchanged. Only
authorized recovery-link creation and payment confirmation went through
genuine Razorpay Test Mode calls when the hybrid_test_mode provider was
selected (RAZORPAY_PROVIDER=hybrid_test_mode, independent of Hermes/Gemini
mode; default remained fake, zero behavior change). Native subscription-retry
signals and historical-data retrieval were not implemented.

RazorpayTestModeAdapter (src/hermes/razorpay_test_mode.py): disabled by
default; rejected any key id not starting with rzp_test_ at construction.
create_recovery_link called POST /v1/payment_links with the case's trusted
amount_minor/currency, accept_partial:false, notify:{sms:false,email:false},
reminder_enable:false, and a stable reference_id (hermes-<case_id>). On an
ambiguous POST outcome it raised a "reconcile via the dashboard" RuntimeError.
verify_capture did an independent GET /v1/payments/{id} readback but ONLY
fetched the payment, not its claimed owning link, and copied the caller's
claimed link_id into the returned evidence unverified - this was Iteration
16's defect #1. A mutable `_pending[obligation_id]` dict keyed the
record_capture/verify_capture round trip - Iteration 16's defect #3
(concurrent webhook deliveries for the same obligation could mix evidence).
Missing currency on the readback fell back silently to case.currency instead
of failing closed - Iteration 16's defect #2. An ambiguous POST completion
raised past engine.run() uncaught, leaving a "pending" action intent with no
explicit resolution state - Iteration 16's defect #4. message_sent was set
equal to policy's message_authorized regardless of whether any messaging
adapter existed - Iteration 16's defect #5.

HybridPaymentProvider composed the existing FakeRazorpayAdapter (retry
eligibility only) with the real adapter. New webhook route POST
/webhooks/razorpay-test (mounted only when real_webhook_secret configured)
verified a genuine payment_link.paid envelope against a separate secret via
separate code. CaptureInfo/CaptureCommand gained an optional link_id;
apply_capture's attribution check accepted either the old direct match
(simulated) or a link_id match (real).

Offline: 269 passed, 3 skipped (was 237; +31 tests/test_razorpay_test_mode.py
+ 1 startup-grace regression). Real-Hermes harness 33 passed, unaffected.
case-11 re-read read-only, unchanged. No live Razorpay/Gemini call, no new
Neon case, no public tunnel started.

---

## Iteration 16 archived detail (moved from HANDOFF.md during Iteration 17)

Fixed five Codex-reviewed defects in the Iteration 15 Razorpay HYBRID slice,
offline only. (1) Independent payment-to-link verification:
RazorpayTestModeAdapter.verify_link_payment now fetches BOTH the Payment Link
and the payment (was: payment only, with the webhook's claimed link id
copied unverified into "verified" evidence); requires the link's own
id/reference_id/status/amount/currency to match, the payment's own
id/status/amount/currency to match, and the link's own `payments` list to
show this payment captured at the expected amount. (2) No silent fallback on
incomplete evidence: a missing/wrong-typed currency (or any required field)
now fails closed - the old `capture.currency or case.currency` fallback was
removed; contradictory link/payment amount or currency within the SAME
signed envelope is rejected before any provider call; malformed nested
entity types raise a controlled RealWebhookError, never crash. (3)
Request-scoped verification, once: removed the mutable
`_pending[obligation_id]` dict; `verify_link_payment(LinkPaymentClaim)` takes
an immutable per-call claim; `RazorpayWebhook.pre_verified_capture` carries
confirmed evidence into `engine.receive` so the engine no longer re-fetches
(one provider fetch pair per webhook, not two) while every ledger validation
stays unchanged. (4) Safe stop for uncertain link creation:
`create_recovery_link` raises `ProviderActionUncertain` on an ambiguous POST
or malformed response; `engine.run()` catches it and persists an explicit
`apply_action_intent_uncertain` transition (intent "uncertain", case
"escalated"/"unrecovered"); new `RecoveryEngine.reconcile_uncertain_intents()`
(wired into `runtime.build_app`) catches the same case after a raw crash. (5)
`message_sent` is real capability AND authorization: the real/hybrid
provider exposes `message_delivery_capable = False`, so a real/hybrid case
never reports a message as sent regardless of what policy authorized;
FakeRazorpayAdapter is unaffected (defaults True).

`tests/test_razorpay_test_mode.py` rewritten: 46 tests (was 31). Offline:
284 passed, 3 skipped (was 269). Real-Hermes harness 33 passed, unaffected.
case-11 re-read read-only, unchanged. No live Razorpay/Gemini call, no new
Neon case, no public tunnel.

---

## Iteration 17 archived detail (moved from HANDOFF.md during Iteration 19)

Razorpay Test Mode HYBRID slice, Iterations 15-17 (code + offline tests, no
live call yet at that point). Per RAZORPAY_TEST_SLICE.md: simulated SaaS
obligation/history/retry sequence unchanged; only recovery-link creation and
payment confirmation go through genuine Razorpay Test Mode calls when the
hybrid_test_mode provider is selected (RAZORPAY_PROVIDER=hybrid_test_mode,
independent of Hermes/Gemini mode; default fake, zero behavior change).
Native subscription-retry signals and historical-data retrieval remain not
implemented. Iteration 15's first cut and Iteration 16's five-defect
correction (independent payment-to-link verification, no silent evidence
fallback, request-scoped single verification, safe uncertain-outcome
persistence, authorization != delivery) are archived above. Iteration 17
closed two more gaps: (1) malformed/truncated raw POST responses (not just
timeout/OSError) now reach the same ProviderActionUncertain safe path,
verified against real bytes over a real local socket; (2)
handle_payment_link_paid_webhook requires the envelope's own claimed
payment_link.status=="paid" and payment.status=="captured", and requires its
amount/currency to agree with the persisted case, not just with each other.
Fixture-vs-provider verification: the Payment Link "payments" array field
names in test fixtures (payment_id, amount, status) were checked against
Razorpay's documented Create-Standard-Link response (fetched via WebFetch) -
confirmed matching; not a substitute for a live call.

HybridPaymentProvider composes FakeRazorpayAdapter (retry eligibility only)
with the real adapter. New webhook route POST /webhooks/razorpay-test
(mounted only when real_webhook_secret is configured) verifies a genuine
payment_link.paid envelope against a separate secret via separate code -
signature over the untouched raw body first, then event-id/envelope/
contradiction checks, then persisted link-id correlation, then the one
independent provider readback, then engine.receive. The simulated
/webhooks/razorpay route and its secret are untouched.

---

## Iteration 18 archived detail (moved from HANDOFF.md during Iteration 21)

One live HYBRID attempt, stopped before payment (case-18). scripts/
webhook_relay.py (new) is a loopback-only reverse proxy serving only POST
/webhooks/razorpay-test - every other path/method rejected before touching
the main app; no engine/DB/credentials of its own, so even an unrestricted
tunnel pointed at it can never expose /demo/*//cases/*/docs. An SSH reverse
tunnel (ssh -p 443 -R0:127.0.0.1:8100 free.pinggy.io, no new binary/no pip)
exposed it publicly; verified end-to-end that unrelated paths 404, the wrong
method 405s, an unsigned POST gets a genuine 401. One tunnel domain
(lhr.life/localhost.run) was connection-reset by local Avast Web Shield
(confirmed: unrelated HTTPS sites worked, that domain didn't) - not touched/
excluded, just switched to a working provider (pinggy.io).

scripts/run_one_hybrid_case.py (new) drove ONE case through real Hermes +
Gemini decisions only (never simulated capture). Result: case-18 (obligation
sub_demo_0004_8e781337) - decision 1: WAIT_FOR_PROVIDER_RETRY authorized;
after the simulated failed-retry input, decision 2: CREATE_RECOVERY_LINK
authorized -> ONE real Payment Link created (reference plink_TY2urjqVCjkjvB;
checkout URL persisted in Neon, not reproduced here).

Scope change mid-task: do not complete the checkout. The demo doesn't require
a paid live checkout; recording uses this saved evidence instead. Case-18
left exactly as-is - no simulated capture, no forged webhook, no state edit.
All three processes were stopped by exact PID/port match; verified ports
8000/8100 free, the tunnel URL no longer resolves, Neon re-read shows case-18
unchanged.

---

## Iteration 19 archived detail (moved from HANDOFF.md during Iteration 21)

Review findings closed + read-only Neon views. Phase A (offline only):
/health now reports non-secret payment_provider /
payment_provider_test_mode_enabled flags; run_one_hybrid_case.py fails closed
(refuses POST /demo/case) unless both are the expected real values -
evidence_mode=SIMULATED on the case's own synthetic intake is preserved,
never relabelled. webhook_relay.py hardened: a documented 64 KiB body
ceiling, Content-Length validated (missing/malformed/negative/oversized all
rejected, 411/400/400/413, before any read), a bounded body-read deadline
(408 on a stall), and logging reduced to method + a fixed route category +
status only - never the raw path/query/headers/body.

Phase B: five read-only views added to scripts/init_neon.py (CREATE OR
REPLACE VIEW only; same single ledger_state JSONB row, nothing duplicated or
made mutable): case_summary (authoritative state plus a derived,
presentation-only display_status), hermes_decisions (one row per
AI_PROPOSAL, joined to its own cycle's nearest AI_MODEL_RUN/POLICY_DECISION -
never a global first/last), recovery_actions (checkout_url_present boolean,
never the URL; message_authorized kept separate from message_sent),
hermes_evidence, audit_timeline. Also fixed a real bug found running this:
init_neon.py's bare psycopg.connect(dsn) had no timeout and no IPv4
preference, so it hung indefinitely on this host's known IPv6 black hole -
now reuses the app's own _connect_bounded.

Ran init_neon.py once against the existing .env (DDL only, hermes_demo
schema) and read all five views back directly: case-18 - state=active
(authoritative, unchanged), display_status=RECOVERY_IN_PROGRESS,
recovery_actions shows the real link with checkout_url_present=true,
action_evidence_mode=REAL_TEST_MODE, message_authorized=true /
message_sent=false (kept separate); hermes_decisions shows both real
decisions correctly paired (WAIT_FOR_PROVIDER_RETRY then
CREATE_RECOVERY_LINK, ~19.2s/~19.4s execution, confidence 0.95/high).
case-11 unchanged: state=recovered, display_status=RECOVERED,
attribution=hermes_assisted, counted=true.

---

## Iteration 20 archived detail (moved from HANDOFF.md during Iteration 21)

Relay corrections (offline only, no live activity). Three defects closed in
scripts/webhook_relay.py, none of them touching a live API/Gemini/Razorpay/
Neon call or the relay/tunnel (neither was started):

1. Absolute deadline, not inactivity-only. The old _read_body set one socket
   timeout, then called self.rfile.read(length) - which loops internally
   over MULTIPLE recv() calls, each getting its OWN fresh timeout, so a
   sender drip-feeding bytes just inside each gap could extend the read
   forever. Now an incremental loop recalculates remaining = deadline -
   now() before every read and uses rfile.read1(want) (at most ONE
   underlying recv() per call) - a continuously-active drip-feeder is still
   cut off (408) once the absolute deadline passes, never forwarded partial.
2. Premature EOF. A connection closing before exactly Content-Length bytes
   arrive is now a distinct, fixed 400 rejection (was previously
   indistinguishable from a timeout) - never forwarded upstream.
3. Normalized log method. log_request printed self.command - the client's
   raw, unvalidated method token - directly. Now mapped through a fixed
   allowlist (GET/HEAD/POST/PUT/DELETE/PATCH/OPTIONS); anything else,
   however crafted, logs as the fixed label "OTHER".

+4 tests in tests/test_webhook_relay.py: a continuously drip-feeding sender
(never quiet long enough for a naive per-call timer to fire) is still
rejected well inside the budget; a real premature EOF via shutdown(SHUT_WR)
rejects 400 and never reaches the upstream stub; an attacker-controlled
method string never appears in captured log output, only "OTHER".

IMPLEMENTATION_BACKLOG.md corrected: removed the stale "still uses
FakeRazorpayAdapter" / "live pending" language (case-18 already proved the
hybrid path live in Iteration 18) and trimmed one repeated historical-dataset
sentence.

---

## Iteration 21 archived detail (moved from HANDOFF.md during Iteration 22)

Hermes SOUL wiring + offline verification, then 4 review-finding corrections,
same iteration. Codex authored config/hermes_agent/SOUL.md (agent identity/
scope/limits) and the first exemplar rule in SKILL.md (consistent recent
payment behavior); both preserved verbatim throughout. Wired both into the
isolated child's ephemeral system prompt.

Parent (hermes_agent_strategist.py): added _SOUL_PATH beside _SKILL_PATH and
a soul_path constructor parameter; __init__ fails closed
(HermesRuntimeUnavailable) if either file is missing, unreadable, or not
valid UTF-8 (shared _read_utf8() helper, sanitized message: label + exception
type only, never path/content). Both read as UTF-8 and sent to the child as
two distinct job keys (soul_text, skill_text - never concatenated on the
parent side). PROMPT_VERSION bumped (...2026-09-05.2).

Child (hermes_agent/child_main.py): _system_prompt() takes soul_text first
and prepends it, so the ephemeral prompt order is SOUL identity/scope -> SKILL
judgment rules -> case context -> tool descriptions/approved messages/output
contract. No other child behavior touched.

Correction 2: _propose_locked creates HermesRunMeta and assigns
last_run_meta BEFORE re-reading the instruction files; a load failure marks
that fresh metadata (failure_category=instruction_load_failed,
failure_stage=instruction_load) and raises - a prior successful run's
metadata can no longer leak onto a later failure.

tests/test_hermes_agent.py: missing SOUL/SKILL each fail closed
independently; a faked subprocess.run captures the literal job JSON and
proves soul_text/skill_text are the real files' exact contents as distinct
fields; child_main._system_prompt() is proven to order SOUL before SKILL
before case context, first with markers then with the real file contents;
invalid-UTF-8 SOUL and SKILL each fail closed; a successful decision followed
by a removed SOUL file proves last_run_meta belongs only to the new failure.
The existing @requires_runtime real-Hermes/offline-stub tests still return a
schema-valid proposal after the wiring change - this proves wiring/contract
behavior only, never Hermes's judgment quality.

Verified: offline focused python -m pytest -q tests/test_hermes_agent.py went
33 -> 37 (wiring) -> 41 (corrections) passed; full offline suite steady at
373 passed, 3 skipped throughout. compileall + git diff --check clean both
times; no live service called in either sub-iteration.

---

## Iteration 22 archived detail (moved from HANDOFF.md during Iteration 23)

One live consistent-history exemplar, persisted to Neon - first real run of
the SOUL + Rule 1 wiring against live Gemini. One new trusted demo case
(case-25, obligation sub_demo_0005_e2c073a9) created via the existing POST
/demo/case -> POST /demo/step {"step":"advance"} path, advanced exactly once,
then stopped - no retry-failed, no recovery link, no capture, no second case.
Local FastAPI only (hermes.asgi:app, 127.0.0.1:8000, HERMES_MODE=hermes); no
Streamlit, tunnel, relay, or Docker. Preflight: clean tree at c43234c,
installed Hermes revision matched EXPECTED_HERMES_REVISION, GEMINI_API_KEY/
DATABASE_URL present via .env (values never printed), all five Neon views
present. .env still carried RAZORPAY_PROVIDER=hybrid_test_mode from Iteration
18 - overridden to fake via a process-only shell env var (.env untouched;
load_dotenv uses override=False) so /health reported payment_provider=fake /
payment_provider_test_mode_enabled=false before the case was created.

Result - every expected condition passed, verified, none forced:
action=WAIT_FOR_PROVIDER_RETRY, policy_outcome=ALLOW
(provider_retry_permitted), state=waiting, confidence=0.55 (medium band), one
tool call (get_payment_retry_facts only, no get_payment_history,
history_expansion_requested=false), zero recovery links/messages/Razorpay
calls, human_review_required=false. Rationale cited the two prior on-time
payments within the three-month window, its limited coverage, verified
simulated-provider retry eligibility, and the remaining uncertainty - unedited
model output.

Neon readback (hermes_demo, scoped to case-25): case_summary 1 row
(display_status=WAITING_FOR_PROVIDER_RETRY); hermes_decisions 1 row
(gemini-3.7-flash, prompt_version=hermes-agent/2026-09-05.2, revision
e02d1e41f..., 1 tool call/6 budget, 2 model iterations/8 budget, ~17.1s);
recovery_actions 0 rows (correct - WAIT creates no link); hermes_evidence 1
row (get_payment_retry_facts/SIMULATED_PROVIDER); audit_timeline 6 rows
(INPUT_EVENT, DEMO_CASE_PROVENANCE, AI_MODEL_RUN, AI_PROPOSAL,
POLICY_DECISION, SCHEDULED_ACTION). No source code changed; no code-change
rule invoked. API process stopped and port confirmed free after readback.
