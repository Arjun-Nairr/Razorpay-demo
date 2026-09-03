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
- `HERMES_RAZORPAY_RESEARCH.md` — verified Hermes/Gemini/Razorpay runtime facts,
  unsupported assumptions, and the approved isolation configuration.
- `IMPLEMENTATION_SPEC.md` — reconciled two-day architecture, acceptance
  criteria, and ordered tracer-bullet implementation sequence.
- `CLAUDE.md` — standing implementation, context, handoff, and Git rules for
  Claude Code.

## Coordination rule

Before starting work, read `HANDOFF.md`, then only the specification/research
files it points to for the current slice. After material work, update
`HANDOFF.md` with decisions, changed files, verification evidence, and the next
action. Never place credentials, API keys, webhook secrets, or private tokens
in these files.
