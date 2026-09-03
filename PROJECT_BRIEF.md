# Project Brief: AI Revenue Recovery Agent

## Goal

Build a working selection-project demo for Track 3: AI Revenue Recovery. Treat
September 4 evening as the internal submission target because the official
September 5 cutoff time is not yet known. The demo should be technically deep
and agentic, not a chatbot or a one-step workflow.

The submission includes a five-minute recorded demo video.

## Official challenge statement

Build an agent that detects revenue at risk, determines the right intervention,
and executes a bounded recovery workflow spanning problems such as payment
failures, checkout abandonment, failed subscriptions, and overdue receivables.

The stated judging bar is not merely identifying the problem. The demo must show
measured money recovered across a batch, compliant escalation, stopping rules,
and an audit trail.

## Product direction

- Position Hermes as a merchant-side recovery operator layered above
  Razorpay—not as a replacement for Razorpay's provider-owned retries,
  notifications, or payment truth.
- Target a fictional SaaS related to Razorpay's domain; exact product identity
  can be selected during product shaping.
- Focus on SaaS subscription-payment recovery. Do not include B2B receivables
  in the first demo.
- Handle a small evaluation batch of rich payment-recovery cases deeply rather
  than optimizing for production-scale batch throughput. Report aggregate
  results across that batch to satisfy the judging bar.
- Use Razorpay test mode as the payment source/integration.
- Target flow:
  `payment failure -> diagnose context -> choose bounded recovery strategy -> execute allowed action -> observe outcome -> re-evaluate -> recover/escalate/stop -> preserve audit trail`
- Demonstrate multi-step adaptation when an initial recovery strategy fails.
- Start with one end-to-end case, then expand to at most five deliberately
  designed customer scenarios that exercise different reasoning patterns.
- Keep all five as deterministic golden scenarios, but require only one real or
  hybrid Razorpay Test Mode path before recording.
- Use an accelerated logical clock so multi-step retries, cooldowns, and
  adaptation can be demonstrated without waiting through real-world delays.

## Context available to the agent

- Payment failure reason and amount at risk
- Customer tenure and value
- Previous failed payments and successful recovery patterns
- Previous recovery attempts and communication history
- Preferred payment methods and timing patterns
- Plan/subscription history

## Candidate actions

- Retry later
- Recommend a different payment method
- Generate a Razorpay payment link
- Send a reminder
- Offer a grace period
- Change billing date
- Recommend a shorter billing cycle
- Recommend prepaid credits/pay-as-you-go
- Recommend downgrade or plan change
- Escalate to a human
- Deliberately take no action

## Core safety boundary

The AI selects a strategy. Deterministic code decides what is permitted.

The deterministic layer should cover retry limits, communication cooldowns,
duplicate-event protection, idempotency, stopping rules, allowed commercial
changes, reconciliation, and webhook validation.

## Demo metrics

- Recovered revenue and recovery rate
- Resolution time
- Unnecessary-intervention rate
- Policy blocks
- Escalations

## Likely UI needs

- Current recovery cases
- Per-case timeline
- Agent reasoning or strategy rationale
- Policy checks and tool actions
- Final outcome and recovered amount
- Structural recommendation

## Builder profile

- CS student; strongest in Python and agent architecture
- Experienced with LLM tool calling, APIs, deterministic safety gates,
  stateful workflows, retries, reconciliation, database journaling,
  dashboards, evaluations, and structured agent handoffs
- Has designed an autonomous paper-trading system named Hermes
- Less experienced with advanced frontend, production deployment, and
  traditional supervised ML
- Comfortable using coding agents heavily

## Constraints

- Very short build window
- Prefer free or genuinely usable free-tier tools
- Avoid unnecessary production infrastructure and overengineering
- Research current tooling before proposing architecture or writing code
- Do not code or finalize architecture until the product shape, risks,
  real-vs-synthetic boundary, AI-vs-deterministic boundary, and exclusions have
  been discussed with the user
- The repository and in-memory Case 1 foundation now exist. Preserve the public
  `RecoveryEngine.receive/run/inspect` seam while adding integrations in narrow
  tracer-bullet slices.
- Razorpay test mode still needs to be set up.
- Available model resources include ChatGPT Plus, an OpenCode Go subscription,
  and up to USD 22 of Gemini API credits if justified.
- The first demo records messaging as an auditable action intent. A real
  Telegram or email provider remains optional and should not block recording.
- Prefer real payment/customer data exposed by Razorpay test APIs. Use synthetic
  customer history only for context that Razorpay does not provide.
- Synthetic enrichment must represent data a real payment/SaaS company could
  actually possess and must materially affect the agent's decision. Do not
  invent inaccessible or decorative omniscient data.
- The agent should automate ordinary recovery paths. Human audit/escalation
  remains a bounded policy outcome when required, rather than the default path.
- Run the core demo locally. If deployment is useful, deploy only the dashboard;
  the local agent may communicate with a hosted database such as Neon, subject
  to research and architecture approval.
- Separate attribution into provider self-recovery, Hermes-assisted recovery,
  merchant-manual recovery, and unrecovered outcomes. Do not claim a normal
  Razorpay retry as Hermes-caused revenue.

## Requested research scope (after discovery questions are answered)

Research current options for Razorpay test integration, agent/LLM runtime,
database/state, scheduling/background jobs, webhook handling, messaging,
dashboard/frontend, hosting/tunneling, observability/audit trail,
evaluation/testing, and synthetic customer-history generation. For each option,
record fit, free-tier limits, local/Docker/hosted recommendation, and whether it
is necessary for the September 5 demo.

## Collaboration model

Codex is the sole orchestrator, researcher, planner, user-facing collaborator,
performance analyst, and prompt provider to Claude Code. Claude Code owns all
implementation without exception and returns created files, retrieved data,
test results, and other implementation evidence to Codex for review. Codex must
not duplicate Claude Code's implementation work.
