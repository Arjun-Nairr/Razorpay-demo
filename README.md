# AI Revenue Recovery — Shared Workspace

This folder is the shared source of truth for work exchanged between the user,
Codex, and Claude Code.

## Files

- `PROJECT_BRIEF.md` — original product direction and constraints.
- `HANDOFF.md` — current decisions, state, blockers, and exact next action.
- `TOOLING_RESEARCH.md` — current primary-source tooling research and stack
  recommendation.
- `FOUNDATION_ARCHITECTURE.md` — approved technical foundation to refine into
  Claude Code implementation prompts.
- `SCENARIO_MATRIX.md` — the three common cases and two payment-history
  outliers used for the demo batch.
- `POLICY_SPEC.md` — exact AI action contract, deterministic limits, safety
  rules, and acceptance tests.
- `RAZORPAY_DEVTOOLS_RESEARCH.md` — why the CLI/MCP page does not bypass
  Dashboard onboarding or replace the direct API integration.
- `CLAUDE.md` — standing implementation, context, handoff, and Git rules for
  Claude Code.

## Coordination rule

Before starting work, read `PROJECT_BRIEF.md` and `HANDOFF.md`. After material
work, update `HANDOFF.md` with decisions, changed files, verification evidence,
and the next action. Never place credentials, API keys, webhook secrets, or
private tokens in these files.
