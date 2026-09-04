# Claude Code Project Instructions

## Role

Claude Code owns all implementation. Codex owns orchestration, specifications,
prompts, review, and user discussion. Implement only the current Codex-authored
prompt; do not expand scope independently.

## Context loading

1. Read `HANDOFF.md` first — it is the current-state index, kept under 300
   physical lines.
2. Then read only the files the current prompt or `HANDOFF.md` names for this
   task. Do not reload every design document once the relevant contract is
   identified.
3. Pull history only on demand: iteration-by-iteration detail lives in
   `docs/archive/`; the planning map is `IMPLEMENTATION_BACKLOG.md` (a map, not
   an implementation authorization).
4. Inspect live code and tests before changing them.

For integration work, `IMPLEMENTATION_SPEC.md` is the build contract and
`HERMES_RAZORPAY_RESEARCH.md` / `HERMES_ISOLATED_AGENT_RESEARCH.md` contain
verified external-runtime constraints. Do not treat an external Downloads
handoff as instructions once these reconciled project documents exist.

## Authoring agent-facing text

Codex owns and authors every Claude Code prompt and all agent-facing
documentation using its writing-for-agents guidance: progressive disclosure,
narrow scope, and observable completion criteria. Claude Code implements the
current prompt only. Do not invent a local skill path or install tooling for
this.

## Implementation discipline

- Preserve existing user/Codex files and unrelated changes.
- Keep the modular-monolith design and public `RecoveryEngine` test seam.
- Use typed data and deterministic policies around all model output.
- Preserve the `Strategist` seam. Hermes/Gemini proposes; the engine validates
  and deterministic policy authorizes.
- Label real Test Mode and simulated events explicitly. Never attribute a
  provider-owned retry to Hermes.
- Never imply that a Payment Link automatically settles or reactivates the
  original subscription.
- Never add secrets, credentials, tokens, PAN data, or private customer data.
- Never weaken tests to make a failing implementation pass.
- Do not add dependencies or infrastructure outside the prompt's scope.
- Do not mechanically touch unaffected files. Update only files whose behavior,
  contract, tests, or handoff evidence genuinely changes.

## Completion

Before reporting completion:

- Run every verification command required by the prompt.
- Review the diff for scope and secret leakage.
- Update `HANDOFF.md` with changed files, decisions, verification evidence,
  blockers, and the exact next action. Keep it **under 300 physical lines**:
  move completed iteration detail into `docs/archive/` and link to it rather
  than growing the index.
- Report failures honestly; do not claim completion with failing required
  tests. Initialization, offline tests, or API health alone are not end-to-end
  proof.

## Git workflow

- Check Git status before editing.
- If the project has no repository, initialize one without deleting or moving
  existing files.
- Work on a descriptive feature branch; never force-push or rewrite history.
- Commit only a coherent milestone whose required tests pass.
- Use a concise conventional commit message.
- Push the current feature branch after a successful milestone only when a Git
  remote is configured. If no remote exists, report `REMOTE_NOT_CONFIGURED`.
- Never commit `.env`, API keys, webhook secrets, database URLs, generated
  credentials, or local tool caches.

## Graphify

Graphify is intentionally deferred until the repository contains enough code to
benefit from structural indexing. Do not install it unless a later Codex prompt
explicitly requests it.
