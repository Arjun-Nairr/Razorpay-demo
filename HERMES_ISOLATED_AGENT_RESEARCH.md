# Isolated real Hermes integration — 2026-09-04

## Decision and authority

The user now requires actual Nous Hermes, not the direct-Gemini fallback. No automatic fallback is authorized. Claude implements; Codex researches and reviews. Green light is for a timeboxed implementation/proof, not a claim of working integration.

## Local evidence (read-only inspection)

- Runtime: `C:/Users/dwish/AppData/Local/hermes/hermes-agent`.
- Git HEAD: `e02d1e41fc6104187e20af9eac8b2820566e3508`; pyproject version `0.20.4`.
- Existing `.venv/Scripts/python.exe --version` succeeds: Python 3.11.15.
- `run_agent.py:439-512` exposes provider, enabled_toolsets, max_iterations, skip_context_files, skip_memory, skip_background_review and callbacks.
- `tools/registry.py:737` implements register(name, toolset, schema, handler, ...).
- `hermes_constants.py:182-226` treats an independent HERMES_HOME outside the normal desktop home as its own root. Skills directory overrides are present at lines 231-276.
- No edits were found by git diff in the inspected run_agent/constants/registry/agent_init/tool_executor files. This does not certify the entire installation unmodified.
- Existing agent configuration, credentials and conversation contents were not read. No runtime updates, agent launches, or API calls were performed.

## Proposed implementation boundary

Reuse the installed interpreter/runtime read-only through a dedicated subprocess, not the existing desktop sessions. Set a new process-local HERMES_HOME before importing Hermes; use a neutral project-owned workspace. Keep its config, skills, sessions, memory and logs separate. Do not change sticky profiles, clone existing profiles, update Hermes, modify the shared virtual environment, or copy existing agent data.

Provide three case-scoped read tools: payment/retry facts, merchant history, prior recovery actions. A minimized immutable decision snapshot can back these tools; reject other case identifiers. The model chooses tool order and which evidence to inspect. Final proposal still passes deterministic policy. Record actual tool calls and outcomes, not hidden reasoning.

Load only an explicit project skill/instruction file. Disable external skill directories, skill mutation, memory sharing, background review, default MCP and general terminal/browser/file/delegation tools. HERMES_HOME is state isolation, NOT an OS security sandbox. Inherit only necessary environment values, never unrelated provider credentials. Keep database and Razorpay credentials out of the agent subprocess.

## Verified public interfaces and caveats

- [Profiles](https://hermes-agent.nousresearch.com/docs/user-guide/profiles/): profile homes separate state, not host filesystem permissions; profile creation/cloning/updating can seed or share material. Prefer an independent home without shared management commands.
- [Python embedding](https://hermes-agent.nousresearch.com/docs/guides/python-library/): `from run_agent import AIAgent`; `run_conversation` returns final_response and messages. Use a fresh instance per decision and bounded iterations. Current docs support checkout development environments rather than a supported requirements wheel.
- [Tools runtime](https://hermes-agent.nousresearch.com/docs/developer-guide/tools-runtime/): singleton registration and tool discovery mean process separation matters. Assert exact exposed tool names AND rejection of unauthorized dispatch, using the installed source rather than assuming filtering suffices.
- [Skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/): external and project-local discovery must be controlled; dedicated folder alone is insufficient.
- [Gemini](https://hermes-agent.nousresearch.com/docs/guides/google-gemini): native Gemini provider documented, with GOOGLE_API_KEY/GEMINI_API_KEY. Verify installed provider behavior; current web docs are not a version guarantee.

## Required proof gates

1. Separate-home path resolution and exact tool exposure/dispatch, without network; no existing-agent writes.
2. Actual AIAgent import/instantiation and tool loop using stubbed model transport; no hand-written loop masquerading as Hermes.
3. Bounded subprocess lifetime, iteration/tool budgets, strict final schema and at most one repair; kill timed-out child cleanly.
4. User-run live Gemini call through actual Hermes, with recorded runtime identity and real tool-call evidence. No live success claimed before this.
5. Integrate after known ledger rollback race, unknown-case consent reconstruction, startup redaction, and same-case capture-during-model regression are corrected.

The installed checkout differs from the earlier planned v0.21.0 pin. Record and guard this exact local revision; do not silently upgrade the user's running installation. Desktop auto-updates are a reproducibility risk: recheck before launch and stop on mismatch. If reuse fails, report the blocker to the user, do not reinstall or fall back silently.
