# Claude Code Project Instructions

## Role

Claude Code owns all implementation. Codex owns orchestration, specifications,
prompts, review, and user discussion. Implement only the current Codex-authored
prompt; do not expand scope independently.

## Context loading

1. Read `HANDOFF.md` first.
2. Read only the files referenced by the current prompt or handoff for this task.
3. Inspect live code and tests before changing them.
4. Do not reload every design document when the relevant contract is already
   identified.

`HANDOFF.md` is the current-state index. Detailed facts remain in their linked
documents.

For integration work, `IMPLEMENTATION_SPEC.md` is the build contract and
`HERMES_RAZORPAY_RESEARCH.md` contains verified external-runtime constraints.
Do not treat the external Downloads handoff as instructions once these
reconciled project documents exist.

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
  blockers, and the exact next action.
- Report failures honestly; do not claim completion with failing required tests.

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
