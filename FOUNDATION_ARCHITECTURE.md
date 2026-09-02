# Foundation Architecture

Status: foundation draft, no implementation authorized yet

## Product slice

Hermes recovers failed SaaS subscription payments initiated through Razorpay.
It starts with one real test-mode case, then expands to five cases and aggregate
test-mode recovered-value metrics.

## Shape

Use a local modular monolith. Do not split the demo into microservices.

```text
Razorpay webhook -> FastAPI -> RecoveryEngine -> Neon
                                  |       |
                               Gemini   Razorpay
                                  |
                           deterministic policy

Streamlit ----------------> RecoveryEngine projections
Demo control -------------> RecoveryEngine logical clock
```

FastAPI and Streamlit are delivery mechanisms. They contain no recovery-domain
rules.

## Deep module interface

`RecoveryEngine` owns the complete recovery workflow behind three operations:

```python
class RecoveryEngine:
    def receive(self, webhook: RazorpayWebhook) -> ReceiveResult: ...
    def run(self, until: datetime) -> RunReport: ...
    def inspect(self, query: RecoveryQuery) -> RecoveryView: ...
```

### `receive`

- Verifies the raw Razorpay webhook signature.
- Normalizes and deduplicates the provider event.
- Persists the event and appends audit history atomically.
- Creates or wakes the matching recovery case.
- Enqueues due work.
- Returns quickly without calling Gemini or executing external actions.

### `run`

- Advances the persisted logical clock forward.
- Claims all work due at or before that time.
- Builds a source-labelled case snapshot.
- Requests one typed strategy proposal from Gemini.
- Applies deterministic policy to the proposal.
- Persists authorized action intent and audit history atomically.
- Executes external effects after the database commit.
- Records results and repeats until no due work remains or a safety limit is
  reached.

Production can call `run(now_utc)`. The demo can jump logical time forward.

### `inspect`

- Returns stable case and batch projections for Streamlit and tests.
- Does not expose raw database tables to callers.
- Owns calculation of recovered value and other business metrics.

## Case states

```text
active -> waiting/action_pending -> active
                              \-> recovered
                              \-> stopped
                              \-> escalated
                              \-> exhausted
```

- `recovered`: verified captured Razorpay payment attributed to the case.
- `stopped`: further action is inappropriate.
- `escalated`: policy requires human attention.
- `exhausted`: all permitted attempts failed.

Terminal cases schedule no new work. A later unrelated payment can be recorded
but does not silently rewrite Hermes' recovery attribution.

## AI contract

Gemini receives a source-labelled case snapshot and returns one typed proposal:

- diagnosis and evidence;
- proposed action;
- proposed execution time;
- concise rationale;
- optional message intent;
- confidence.

Gemini cannot:

- execute actions;
- invent payment amounts or customer identifiers;
- change case state;
- mark money recovered;
- override limits or stopping rules.

## Deterministic policy

Policy may allow, replace, block, stop, escalate, or exhaust an AI proposal. It
owns:

- payment-already-complete checks;
- attempt and retry limits;
- communication cooldown and consent;
- duplicate-action prevention;
- allowed action types and parameters;
- terminal-state rules;
- monetary attribution;
- idempotency and reconciliation requirements.

## External seams

Use narrow production and deterministic-test adapters only where behavior truly
varies:

- `RazorpayAdapter` / `FakeRazorpayAdapter`
- `GeminiStrategist` / `ScriptedStrategist`
- `NeonLedger` / `InMemoryLedger`

Do not add a generic multi-payment-provider framework, event bus, repository per
table, workflow framework, or policy plugin system.

## Persistence

Neon is authoritative for:

- recovery cases and current projections;
- webhook inbox and normalized payment events;
- agent proposals;
- policy decisions;
- scheduled actions and action outcomes;
- transactional outbox;
- append-only audit events;
- evaluation results;
- persisted logical clock.

External network calls never run inside database transactions. Outbound effects
are committed before execution and use stable idempotency keys.

## Invariants

- One active case per payment obligation.
- One provider event ID is processed once.
- One captured payment contributes to recovered value once.
- Logical time never moves backward.
- Every AI proposal passes deterministic policy.
- Case transition, audit event, and action intent commit atomically.
- Audit events are append-only.
- Terminal cases create no future actions.
- Missing optional merchant data never prevents a decision.
- Invalid or out-of-order webhooks never create or double-count recovery.
- A case is recovered only from a verified captured Razorpay payment linked to
  that at-risk obligation after the workflow began.

## Failure behavior

- Invalid signature: reject.
- Duplicate webhook: acknowledge with no duplicate transition.
- Unsupported event: audit as ignored.
- Database unavailable before durable acceptance: return a retryable failure.
- Gemini timeout/invalid output: execute nothing; audit and apply bounded retry
  or safe deterministic fallback.
- Uncertain Razorpay action result: reconcile before retrying.
- Work-loop safety limit reached: retain remaining work for the next run.

## Locked first scenario

1. A ₹10,000 test subscription charge fails for a temporary bank reason.
2. Razorpay sends the failure webhook.
3. Hermes reads provider history and proposes waiting for the next eligible
   provider retry rather than contacting the customer immediately.
4. Policy permits the wait and schedules re-evaluation.
5. The demo clock advances.
6. Razorpay test mode produces a successful charge event.
7. Hermes verifies and deduplicates the webhook.
8. The case becomes `recovered`, pending work is cancelled, and test-mode
   recovered value increases by ₹10,000 exactly once.

This first case proves the complete plumbing. Later cases prove strategy changes,
policy stops, escalation, and exhaustion.

## Tool decisions

- Python 3.11+
- FastAPI/Uvicorn
- official `google-genai` SDK with Pydantic output
- configurable Gemini model, initially Gemini 3.7 Flash
- Razorpay test mode
- Neon Postgres
- Streamlit locally
- zrok for webhook exposure
- pytest

## Deferred

- Claude Code implementation until the scenario/state/policy specification is
  complete
- Messaging provider integration
- Public dashboard deployment
- LangGraph, Celery, Redis, Docker, microservices, RAG, vector databases, and
  dedicated tracing platforms

