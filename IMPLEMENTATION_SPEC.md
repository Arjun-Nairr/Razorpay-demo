# Two-Day Implementation Specification

Status: ready for implementation prompts after Codex review

## Problem

Razorpay already performs eligible subscription retries and may own customer
notifications. A merchant still needs a bounded operator that combines provider
truth with merchant context, adapts after failed outcomes, suppresses duplicate
contact, and produces an auditable recovery result without giving an LLM
financial authority.

## Solution

Hermes is the merchant-side recovery operator above Razorpay. A deterministic
context builder gives a fresh, isolated Hermes Agent instance a minimized,
source-labelled snapshot. Gemini 3.7 Flash returns one candidate strategy.
Deterministic policy authorizes, replaces, blocks, stops, escalates, or exhausts
that proposal. Only verified, unique payments change recovered-value metrics.

The demo keeps five golden scenarios, but only one flow needs real or hybrid
Razorpay Test Mode evidence. All accelerated multi-day outcomes are explicitly
simulated.

## User stories

1. As a merchant operator, I want a verified payment failure to create one
   recovery case, so that duplicate webhooks do not create duplicate work.
2. As a merchant operator, I want Hermes to adapt after an unsuccessful wait,
   so that the system demonstrates reasoning rather than a fixed retry rule.
3. As a customer, I want communication ownership, consent, and cooldowns
   respected, so that Razorpay and the merchant do not contact me twice.
4. As a finance reviewer, I want provider, Hermes-assisted, manual, and
   unrecovered attribution separated, so that the demo does not overclaim
   Hermes impact.
5. As an auditor, I want every input, model proposal, policy decision, action
   intent, outcome, and terminal transition recorded, so that every result is
   explainable.
6. As a demo presenter, I want deterministic replay and logical time controls,
   so that multi-day recovery paths complete within five minutes.
7. As a billing operator, I want commercial changes recorded only as named
   recommendations, so that Hermes cannot invent or apply contract terms.
8. As a reliable customer, I want an anomalous failure to avoid unnecessary
   contact, so that automation does not become spam.
9. As a chronically late customer, I want attempts to stop at a fixed limit,
   so that automation cannot loop indefinitely.
10. As an evaluator, I want five repeatable scenarios and aggregate metrics,
    so that changes to prompts or policy can be compared objectively.

## Architecture decisions

### Runtime boundaries

- FastAPI preserves the raw webhook body, verifies the Razorpay signature,
  extracts the provider event ID, normalizes the event, and acknowledges
  quickly. Signature verification is a delivery-adapter responsibility.
- `RecoveryEngine.receive`, `run`, and `inspect` remain the only recovery-domain
  surface.
- `RecoveryEngine.run` builds context deterministically, calls one
  `Strategist`, applies deterministic policy, and persists action intent before
  executing an effect.
- `HermesStrategist` implements the existing `Strategist` protocol. It creates
  a fresh isolated Hermes `AIAgent` per decision and uses Gemini 3.7 Flash.
- Embedded Hermes output is parsed and Pydantic-validated locally; invalid
  output executes nothing and receives at most one bounded repair attempt.
- Streamlit reads stable projections through FastAPI. Direct read-only Neon
  access is a deadline fallback only.

### Data and time

- Neon is the target shared ledger for webhook inbox, cases, due work, model
  runs, proposals, policy decisions, action intents/outcomes, audit events,
  attribution, evaluation results, and the persisted logical clock.
- SQLite is the fallback only if Neon credentials or migration work threaten
  the recording deadline.
- Provider timestamps remain real. Logical time accelerates only Hermes waits,
  cooldowns, and deterministic scenario replay.
- Work wakes only for a new meaningful failure, due re-evaluation, nonterminal
  action outcome, or materially changed facts.

### Context contract

Each decision receives only source-labelled fields required by policy or the
chosen strategy:

- provider failure, retry, subscription/invoice/payment state, payment method,
  amount, and timestamp;
- merchant tenure/value band, deterministic payment-history classification,
  relevant usage/support/dispute facts, and source system;
- prior proposals, policy results, action outcomes, case version, and
  attribution state;
- communication owner, consent, reachable channel, last contact, and cooldown;
- remaining retry/action/message/link/wait limits;
- predefined available interventions;
- real provider time and logical demo time.

Secrets, raw webhook bodies, unnecessary PII, and unexplained synthetic facts
never enter the model context.

### Attribution

- `provider_self_recovered`: a normal provider-owned retry succeeds without a
  Hermes-owned intervention.
- `hermes_assisted`: a uniquely correlated Hermes-authorized alternate
  collection or merchant communication path precedes the verified payment.
- `merchant_manual`: a merchant action outside the Hermes workflow recovers it.
- `unrecovered`: no unique verified payment is linked before termination.

Attribution is distinct from payment truth. A Payment Link payment may be
Hermes-assisted alternate collection but does not automatically settle or
reactivate the original subscription.

## Tracer-bullet implementation sequence

1. **Adaptation and attribution slice** — first close the known
   `CaptureCommand.expected_state` validation gap, then extend the in-memory
   public seam with the insufficient-funds failed-retry outcome, reminder/link
   intent, communication limits, action outcomes, and attribution. Preserve
   Case 1.
2. **Hermes runtime spike** — pin one Hermes commit, prove isolated Gemini
   invocation, strict local schema validation, timeout/repair behavior, and
   audit metadata through the `Strategist` protocol. Timebox aggressively.
3. **FastAPI signed simulated ingress** — accept locally signed
   Razorpay-shaped fixtures, preserve raw-body verification, deduplicate, and
   expose engine projections/demo controls.
4. **Shared persistence slice** — implement the ledger contract in Neon,
   including authoritative logical time and action intents. Use SQLite only if
   Neon blocks the deadline.
5. **Razorpay Test Mode hybrid slice** — ingest at least one real signed event,
   reconcile provider truth, and label every real/simulated event explicitly.
6. **Five-case dashboard slice** — run all five golden cases, show timelines,
   policy outcomes, attribution, recovered value, unnecessary intervention,
   escalation/exhaustion, and a repeatable five-minute demo control.

Each slice must fit one Claude context, add public-seam behavioral tests, update
`HANDOFF.md`, and commit/push only after its verification passes.

## Acceptance criteria

- Case 1 remains green as plumbing proof.
- Capture finalization rejects both stale expected version and stale expected
  state.
- Case 3 demonstrates wait -> failed outcome -> changed strategy -> verified
  alternate recovery.
- All five scenarios reach their expected terminal outcome.
- A normal Razorpay retry is never counted as Hermes-assisted.
- Simulated events are visibly labelled and cannot be confused with Test Mode.
- Duplicate/out-of-order events and repeated payments never double-count money.
- Hermes receives no write tools, credentials, raw webhook body, or unnecessary
  PII.
- Invalid model output executes nothing and is audited.
- Customer communication is suppressed when Razorpay owns it.
- Every outbound action begins as a persisted, idempotent intent.
- Batch metrics equal the sum of unique verified linked payments.

## Out of scope

- Live payments or live customer data
- Automatic plan, price, discount, billing-date, payment-method, or entitlement
  mutation
- Claiming that Payment Links settle subscription invoices
- Real messaging provider unless the entire core demo is rehearsed
- Production scheduling, microservices, Docker, Redis, Celery, LangGraph, RAG,
  vector databases, external tracing, or broad Hermes tool access
- More than one real/hybrid Razorpay path
- Replacing the existing recovery engine with Hermes-managed state
