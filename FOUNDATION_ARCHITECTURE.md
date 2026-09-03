# Foundation Architecture

Status: core in-memory seam implemented; integration architecture reconciled
2026-09-03

## Product slice

Hermes is a merchant-side recovery operator for failed SaaS subscription
payments initiated through Razorpay. Razorpay remains the payment rail and
source of payment truth. Case 1 proves plumbing; Case 3 is the next intelligence
slice. The demo keeps five golden cases but needs only one real or hybrid Test
Mode path.

## Shape

Use a local modular monolith. Do not split the demo into microservices.

```text
Razorpay webhook -> FastAPI signature boundary -> RecoveryEngine -> Neon
                                                    |       |
                                           Hermes/Gemini   Razorpay
                                                    |
                                             deterministic policy

Streamlit ----> FastAPI ----> RecoveryEngine projections
Demo control -> FastAPI ----> RecoveryEngine logical clock
```

FastAPI and Streamlit are delivery mechanisms. They contain no recovery-domain
rules. FastAPI owns preservation of the raw request body and HMAC verification;
the engine accepts a normalized, verified event.

## Deep module interface

`RecoveryEngine` owns the complete recovery workflow behind three operations:

```python
class RecoveryEngine:
    def receive(self, webhook: RazorpayWebhook) -> ReceiveResult: ...
    def run(self, until: datetime) -> RunReport: ...
    def inspect(self, query: RecoveryQuery) -> RecoveryView: ...
```

### `receive`

- Accepts a normalized event only after the FastAPI adapter verifies the raw
  Razorpay webhook signature.
- Deduplicates the provider event.
- Persists the event and appends audit history atomically.
- Creates or wakes the matching recovery case.
- Enqueues due work.
- Returns quickly without calling Gemini or executing external actions.

### `run`

- Advances the persisted logical clock forward.
- Claims all work due at or before that time.
- Builds a source-labelled case snapshot.
- Requests one candidate strategy from a fresh isolated Hermes Agent instance
  using Gemini, then parses and validates it into the typed proposal contract.
- Applies deterministic policy to the proposal.
- Persists authorized action intent and audit history atomically.
- Executes external effects after the database commit.
- Records results and repeats until no due work remains or a safety limit is
  reached.

Production can call `run(now_utc)`. The demo can jump logical time forward.

## Wake-up rules

Hermes is invoked only for a new meaningful failure, a due re-evaluation, a
failed/nonterminal action outcome, or materially changed provider/merchant
facts. Duplicate or out-of-order events, dashboard reads, terminal cases, and a
verified successful payment do not invoke the model. Payment reconciliation and
case closure are deterministic.

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

A deterministic context builder supplies one minimized, source-labelled
snapshot. A fresh, stateless Hermes `AIAgent` uses Gemini 3.7 Flash and returns
strict JSON that application code parses and validates into one typed proposal:

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

Hermes receives no database credentials, raw webhook body, unnecessary PII, or
general-purpose tools. Use a dedicated profile/home, skip project context and
memory, disable self-improvement/curator behavior, expose no tools initially,
and cap model iterations near three. Because embedded `AIAgent` does not
document a response-schema parameter, invalid JSON/schema output fails closed
and receives at most one bounded repair attempt.

## Decision context

The source-labelled snapshot contains only decision-driving provider facts,
merchant context, prior recovery outcomes, communication ownership/consent,
remaining limits, predefined options, case version, and both real provider time
and logical demo time. Synthetic facts must map to a plausible SaaS source
system and materially affect policy or strategy.

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
- `HermesStrategist` / `ScriptedStrategist`
- `NeonLedger` / `InMemoryLedger`

Do not add a generic multi-payment-provider framework, event bus, repository per
table, workflow framework, or policy plugin system.

Pin the exact tested Hermes repository commit. Timebox its runtime spike; the
existing `Strategist` seam protects the engine if Hermes setup fails.

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
- recovery attribution;
- persisted logical clock.

Use SQLite only as a deadline fallback for a completely local demo. Streamlit
normally reads stable projections through FastAPI; a separate read-only Neon
connection is an emergency fallback, not the preferred write path.

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
- Real Test Mode and simulated events are explicitly labelled and cannot be
  conflated in the UI or metrics.

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

Case 1 recovery through a normal Razorpay-owned retry is attributed to
`provider_self_recovered`. Case 3 is the hero intelligence path and demonstrates
Hermes changing strategy after a simulated failed retry.

## Notification and collection ownership

When `customer_notify=true`, Razorpay owns subscription communication and
Hermes suppresses duplicate merchant contact. Merchant-owned reminder scenarios
use `customer_notify=false` or an explicit simulated communication-ownership
fact.

A Razorpay Payment Link is a separately correlated alternate collection path.
Its unique verified payment may be attributed `hermes_assisted`, but the demo
must not claim it automatically settles or reactivates the original subscription.

## Tool decisions

- Python 3.11+
- FastAPI/Uvicorn
- Hermes Agent pinned to a tested repository commit, embedded behind
  `HermesStrategist`
- native Hermes Gemini provider with configurable model, initially
  `gemini-3.7-flash`
- local Pydantic parsing/validation with fail-closed bounded repair
- Razorpay test mode
- Neon Postgres
- Streamlit locally
- zrok for webhook exposure
- pytest

## Deferred

- Messaging provider integration
- Public dashboard deployment
- LangGraph, Celery, Redis, Docker, microservices, RAG, vector databases, and
  dedicated tracing platforms
- A direct parallel `google-genai` agent loop after Hermes passes its runtime
  spike

See `HERMES_RAZORPAY_RESEARCH.md` for verified runtime constraints and
`IMPLEMENTATION_SPEC.md` for the current build sequence.
