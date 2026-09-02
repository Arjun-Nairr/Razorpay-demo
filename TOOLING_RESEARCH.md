# Tooling Research: AI Revenue Recovery Demo

Research date: 2026-09-02

## Decision summary

The smallest credible stack is:

- **Payments:** Razorpay test-mode card subscriptions and signed webhooks
- **Agent:** local Python with the official Google GenAI SDK and Pydantic
- **Model:** Gemini 3.7 Flash initially, configured so the model can be swapped
- **API/webhooks:** FastAPI and Uvicorn, running locally
- **State and audit:** Neon Postgres Free
- **Scheduling:** database-backed accelerated logical clock; no job-queue product
- **Dashboard:** Streamlit locally; Community Cloud only if a public UI becomes useful
- **Tunnel:** zrok only for the Razorpay webhook endpoint
- **Testing/evaluation:** pytest plus five hand-authored golden scenarios
- **Synthetic data:** hand-authored decision-driving SaaS context; Faker only for
  cosmetic identities
- **Messaging:** provider-neutral outbox first; Telegram only as a stretch adapter

Do not add LangGraph, Celery, Redis, Docker, a vector database, microservices,
hosted workers, real-time multi-day scheduling, or a dedicated observability
platform before the recorded demo works.

## Facts versus recommendations

All items labelled **Fact** are grounded in first-party documentation. Items
labelled **Decision** are recommendations for this deadline rather than vendor
claims.

## Tool-by-tool assessment

| Area | Recommended tool | Verified free/cost boundary | Run mode | Needed by Sept 4? | Why it fits |
|---|---|---|---|---|---|
| Payment integration | Razorpay test mode | **Fact:** test mode uses mock payments rather than real money. Test mode permits up to 30 Payment Links per business. [Test checkout](https://razorpay.com/docs/payments/payment-gateway/web-integration/standard/integration-steps/) · [Payment Link limit](https://razorpay.com/docs/api/payments/payment-links/create-standard/) | Hosted provider, local client | Yes | Produces real Razorpay entities, failure states, test charges, and webhook events without moving money. |
| LLM runtime | Gemini API, begin with `gemini-3.7-flash` | **Fact:** free-tier input/output is available; paid pricing through Dec 31, 2026 is $0.75/M input tokens and $3.75/M output tokens. Paid prompts are not used to improve Google's products; free-tier content may be. Limits vary by model/tier and the active values are shown in AI Studio. [Pricing](https://ai.google.dev/gemini-api/docs/pricing) · [Rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) | Hosted API called from local agent | Yes | Current programmatic API, structured outputs, ample quality, and the available $22 budget is far beyond five-case demo needs. |
| Agent code | Plain Python, `google-genai`, Pydantic | **Fact:** Google recommends its `google-genai` Python SDK and Gemini supports schema-constrained structured output, including Pydantic schemas. Schema validity does not replace application-level semantic checks. [Libraries](https://ai.google.dev/gemini-api/docs/libraries) · [Structured output](https://ai.google.dev/gemini-api/docs/structured-output) | Local virtual environment; no Docker initially | Yes | Keeps the AI surface narrow: the model proposes a typed strategy and deterministic code authorizes actions. |
| API/webhooks | FastAPI + Uvicorn | **Fact:** FastAPI can receive request bodies and run locally through an ASGI server. [Request bodies](https://fastapi.tiangolo.com/tutorial/body/) · [Running FastAPI](https://fastapi.tiangolo.com/deployment/manually/) | Local | Yes | Small Python-native webhook/API boundary. |
| Database/state | Neon Postgres Free | **Fact:** Free currently provides 100 projects, 100 CU-hours/month per project, 0.5 GB storage/project, compute up to 2 CU/8 GB RAM, 5 GB transfer, and scale-to-zero after inactivity. [Pricing](https://neon.com/pricing) | Hosted | Yes, given the chosen shared-state shape | Hermes and a local or hosted dashboard can share one credible ledger without operating Postgres locally. |
| Scheduler | Persisted `demo_now` plus `due_at` actions | **Fact:** Python time/scheduling can be abstracted; no external quota applies to ordinary application logic. [Python `sched`](https://docs.python.org/3/library/sched.html) | Local logic + Neon state | Yes | One “advance time” operation can automatically claim every due action across the batch, making multi-day behavior deterministic in a five-minute video. |
| Webhook tunnel | zrok Free | **Fact:** Free is $0 with 5 GB/day, 25 environments, and 50 share backends. Razorpay's webhook testing documentation recommends zrok for exposing localhost. [zrok pricing](https://zrok.io/pricing/) · [Razorpay validation/testing](https://razorpay.com/docs/webhooks/validate-test/) | Local client + hosted tunnel | Yes for real webhooks | Exposes only the local FastAPI webhook endpoint; the rest of the demo stays local. |
| Dashboard | Streamlit | **Fact:** Streamlit runs locally and has a SQL connection backed by SQLAlchemy. Community Cloud deployment is free and GitHub-connected; documented approximate cloud limits are 0.078–2 CPU cores, 690 MB–2.7 GB RAM, and up to 50 GB storage, subject to change. [SQL connection](https://docs.streamlit.io/develop/api-reference/connections/st.connections.sqlconnection) · [Community Cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud) · [Resource limits](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app) | Local first; hosted optionally | Yes, locally | Fastest route to batch KPIs, a case queue, timelines, policy decisions, actions, and recovered value. |
| Audit/observability | Application audit tables in Neon | **Fact:** Postgres `jsonb` supports validated JSON storage, operators, and indexing. [PostgreSQL JSON types](https://www.postgresql.org/docs/current/datatype-json.html) | Hosted DB, viewed locally | Yes | The challenge needs business events and payment outcomes, not merely LLM traces. |
| Evaluation | pytest parametrization | **Fact:** pytest can run the same behavioral assertions over multiple parameter sets and is open source. [Parametrization](https://docs.pytest.org/en/stable/how-to/parametrize.html) · [Repository](https://github.com/pytest-dev/pytest) | Local | Yes | The five cases become reproducible golden tests for policies, agent proposals, event handling, and aggregate money. |
| Synthetic data | Hand-authored fixtures; Faker for cosmetic fields only | **Fact:** Faker supports seeded generation of names, companies, emails, and similar display data. Its docs warn outputs can change across patch versions. [Faker](https://faker.readthedocs.io/en/master/) | Local | Hand-authored fixtures: yes; Faker: optional | With only five cases, authored causally meaningful histories are more valuable and explainable than statistical synthetic-data tooling. |
| Messaging | Internal outbox; Telegram stretch adapter | **Fact:** Telegram's Bot API can send messages for free at demo scale. Bots cannot initiate contact before a user messages/adds them. Free guidance is roughly one message/sec per chat and about 30 broadcast recipients/sec. [Bot introduction](https://core.telegram.org/bots) · [API](https://core.telegram.org/bots/api#sendmessage) · [limits](https://core.telegram.org/bots/faq) | Hosted API from local worker | Outbox: yes; Telegram: no | The outbox proves an auditable automated action without making the core pipeline depend on a messaging vendor. |
| External LLM tracing | None initially | **Fact:** Langfuse Hobby is free for 50,000 units/month, 30 days' data access, and two users. [Langfuse pricing](https://langfuse.com/pricing) | Hosted if added | No | Useful developer telemetry, but it does not replace the required business audit trail and is deadline-displacing infrastructure. |

## Why not use the existing subscriptions as Hermes' primary model?

- **ChatGPT Plus — Fact:** ChatGPT subscriptions and API billing are separate;
  Plus does not supply backend API usage. [OpenAI billing
  separation](https://help.openai.com/en/articles/8156019-is-api-usage-included-in-chatgpt-subscriptions-even-if-i-have-a-paid-chatgpt-account)
- **OpenCode Go — Fact:** Go is $10/month with $12/5-hour, $30/week, and
  $60/month value limits, and exposes callable endpoints. Its documentation says
  it is designed primarily for OpenCode and similar coding-agent traffic, and
  its model list may change. [OpenCode Go](https://dev.opencode.ai/docs/go/)
- **Decision:** keep ChatGPT Plus for planning/review and OpenCode Go for Claude
  implementation work. Use Gemini's API for the product runtime so a
  coding-agent subscription is not a fragile production dependency.

At the currently documented Gemini 3.7 Flash paid price, an intentionally large
illustrative test of 100 decisions using 10,000 input and 1,000 output tokens
each would cost roughly $1.13. The real five-case demo should be smaller, so the
$22 credit budget is not a material constraint.

## Razorpay: what is real

The demo can use actual test-mode Razorpay behavior for:

- card subscriptions and their plan/customer/status/cycle/count data;
- failed and captured payments with method and structured failure fields;
- orders, attempts, amount paid/due, invoices, and subscription relationships;
- immediate test subscription charges selected as success or failure;
- subscription pending/charged/halted lifecycle events;
- Payment Links and their paid status;
- signed webhook events and API lookups.

Razorpay documents immediate test charging through the Dashboard and four
consecutive failures before a test subscription becomes halted. Test card
tokens can be used for subsequent debits only within three days, so account
setup should not be left until the recording day. [Test
subscriptions](https://razorpay.com/docs/payments/subscriptions/test/)

For ordinary subscriptions, Razorpay controls native retries on T+1, T+2, and
T+3. The demo's accelerated logical clock must therefore accelerate **our
agent's decisions and actions**; it must not falsely claim to accelerate
Razorpay's production retry clock. Immediate Razorpay test charges can supply
the demonstration events. [Subscription
retries](https://razorpay.com/docs/payments/subscriptions/payment-retries/)

## Recovery accounting rule

**Decision:** count test-mode recovered value only when all of the following are
true:

1. A Razorpay webhook signature is valid over the unchanged raw body.
2. The unique payment is `captured` and linked to the at-risk case/order,
   invoice, subscription, or recovery collection.
3. Capture occurred after the recovery workflow began.
4. The payment and webhook event have not already been counted.

Creating a link, sending a message, receiving an authorization, or scheduling a
retry does not recover money. Razorpay documents at-least-once webhook delivery,
possible duplicates, and no ordering guarantee; use `x-razorpay-event-id` for
event deduplication and the payment ID for money deduplication. [Webhook
validation](https://razorpay.com/docs/webhooks/validate-test/) · [Webhook best
practices](https://razorpay.com/docs/webhooks/best-practices/) · [Payment
events](https://razorpay.com/docs/webhooks/payments/)

Display the metric as **test-mode recovered value**, with gross captured value
and (if refunds are demonstrated) net value after refunds.

## Synthetic enrichment boundary

### Permitted and useful

These fields could realistically come from a SaaS company's billing, product
analytics, CRM, support, and consent systems:

- account ID, plan, recurring amount, tenure, and subscription status;
- prior provider payment attempts and previous recovery outcomes;
- last successful payment and payment-method preference derived from history;
- recent logins/API usage, active seats, and meaningful feature adoption;
- open support incidents or disputes;
- contact consent, available channel, timezone, and last-contact time;
- recovery attempt count, cooldown, opt-out, and account status.

Every decision-driving field must be traceable to one of those plausible source
systems and must change or justify an action, policy result, or stopping rule.

### Prohibited

- bank balances or hidden issuer/account data;
- private wealth, emotion, personality, or psychographic guesses;
- certainty that a future retry will succeed;
- unexplained churn scores or facts a SaaS company could not lawfully possess.

## Minimal business audit data

The implementation specification should include authoritative records for:

- cases and customer/account snapshots;
- raw/normalized payment events and webhook inbox event IDs;
- agent runs, model/prompt version, structured proposals, latency, and cost;
- policy evaluations and their evidence;
- scheduled actions, attempts, results, and idempotency keys;
- message outbox state;
- append-only audit events;
- evaluation expectations/results;
- demo logical clock.

## Evaluation gate

Each of the five scenarios should assert:

- correct risk/diagnosis evidence;
- proposed action belongs to the allowed action set;
- retry, cooldown, consent, dispute, and terminal-payment rules are obeyed;
- no duplicate action or double-counted payment occurs;
- only a verified captured payment changes recovered value;
- expected stop/escalate/no-action behavior occurs;
- batch recovered value equals the sum of unique verified recoveries.

Report decision correctness, policy blocks/violations, duplicate actions,
latency, model cost, resolution time, conversion, gross/net recovered value, and
unnecessary-intervention rate.

## Explicitly defer

- checkout abandonment and B2B receivables;
- production-scale batch throughput;
- LangGraph/Temporal/Celery/Redis/RabbitMQ;
- Docker/Kubernetes and separate microservices;
- RAG/vector databases;
- hosted background workers and real multi-day waits;
- external tracing/evaluation platforms;
- statistical synthetic-data frameworks;
- email/domain setup;
- dashboard deployment until the local recording path is stable.

## Recommended implementation order for Claude Code

This is sequencing guidance, not authorization to implement yet:

1. Prove one test subscription failure can enter the system and be audited.
2. Prove one typed AI proposal can be policy-checked without executing an
   unsafe action.
3. Prove a signed, duplicate-safe captured-payment event changes recovered
   value exactly once and stops pending actions.
4. Add the persisted logical clock and automated due-action processing.
5. Add the local Streamlit views.
6. Turn the first case into five golden scenarios and aggregate metrics.
7. Add Telegram only if all core gates pass and recording rehearsal is stable.

