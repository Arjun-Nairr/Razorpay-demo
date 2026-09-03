# Hermes and Razorpay Runtime Verification

Research date: 2026-09-03

## Decision

Use Hermes Agent as the model harness behind the existing `Strategist` seam,
with Gemini 3.7 Flash as the configured provider. Keep every workflow write,
policy decision, and recovered-value calculation inside deterministic
application code.

Adoption is gated by a short runtime spike because Hermes is installed from its
repository rather than as an ordinary supported PyPI package. Pin the exact
tested Hermes commit. If the spike fails within its timebox, retain the
`Strategist` seam and use the smallest verified Gemini adapter necessary for the
demo instead of delaying the whole project.

## Verified facts

- Gemini 3.7 Flash is a current stable Gemini API model and supports structured
  outputs and function calling. [Gemini models](https://ai.google.dev/gemini-api/docs/models)
- Hermes provides a native Gemini provider and documents
  `gemini-3.7-flash`. [Hermes Gemini guide](https://hermes-agent.nousresearch.com/docs/guides/google-gemini)
- Embedded Hermes uses a fresh `AIAgent` per concurrent task. Its Python guide
  documents `skip_memory`, `skip_context_files`, tool allowlists, and bounded
  `max_iterations`, and warns that one instance is not thread-safe across
  tasks. [Hermes Python library](https://hermes-agent.nousresearch.com/docs/guides/python-library)
- Hermes tool availability is controlled most safely through a positive
  `enabled_toolsets` allowlist. [Hermes toolsets](https://hermes-agent.nousresearch.com/docs/reference/toolsets-reference)
- Razorpay card-subscription retries occur on T+1, T+2, and T+3 calendar days;
  Hermes logical time cannot accelerate them. [Razorpay subscription retries](https://razorpay.com/docs/payments/subscriptions/payment-retries/)
- `customer_notify=true` means Razorpay owns subscription communication;
  `false` means the merchant owns it. [Create Subscription API](https://razorpay.com/docs/api/payments/subscriptions/create-subscription/)
- Razorpay webhook signatures must be calculated from the unchanged raw body;
  delivery can duplicate or arrive out of order, and
  `x-razorpay-event-id` is the deduplication key. [Webhook validation](https://razorpay.com/docs/webhooks/validate-test/)
- Payment Links accept a unique `reference_id` and form a separate collection
  flow. Their payment must be correlated to Hermes, but must not be described
  as automatically settling the original subscription invoice. [Payment Link API](https://razorpay.com/docs/api/payments/payment-links/create-standard/)

## Retry-state vocabulary (clarification, no policy change)

The in-memory slice carries two separate retry facts. They are not the same
thing and neither one is a remaining-retry count:

- **`provider_retry_eligible`** - whether *another* Razorpay-managed retry is
  **currently** eligible for this obligation (a live provider fact). Fail-closed:
  absent evidence resolves to `False`.
- **`retry_outcome_recorded`** - whether **at least one** prior retry outcome
  already exists for this obligation. It records that history happened; it does
  **not** mean provider retries are exhausted.
- A prior failed retry and current eligibility **can both be true** at once: the
  documented card-retry schedule (T+1 / T+2 / T+3) can still hold a further
  eligible attempt after an earlier one failed. So a repeated
  `WAIT_FOR_PROVIDER_RETRY` proposal, on its own, is not evidence of a bug.
- A real provider integration must distinguish three things using **retrievable
  provider evidence**, not inference: (a) current eligibility, (b) prior attempt
  count / outcomes, (c) the next scheduled retry time. Do **not** synthesise a
  "retries remaining" number - Razorpay's subscription-retry API does not expose
  one, and Hermes must not invent it.
- Bounded waiting stays governed by the existing deterministic caps (max
  proposed wait 72 logical hours; provider eligibility must be an explicit fact
  with evidence). Whether a *further* wait is allowed after N recorded failures
  is a policy question to settle before runtime integration - it is deliberately
  left unchanged in this slice.

## Corrections to the imported handoff

1. Embedded `AIAgent` does not document a provider-enforced response-schema
   parameter on its normal `chat`/conversation surface. Ask for strict JSON,
   parse and validate it locally, fail closed, and permit at most one bounded
   repair attempt. Do not claim provider-enforced schema until the runtime
   spike proves it.
2. `skip_memory=True` is necessary but not sufficient isolation. Use a
   dedicated Hermes profile/home, skip context files, disable memory and
   curator/self-improvement behavior, install without skills where practical,
   and expose no tools for the first demo decision.
3. The five-minute adaptation sequence must use deterministic provider-shaped
   simulated events. A real Test Mode event may anchor the demo, but simulated
   later outcomes must be labelled `SIMULATED`.
4. Attribute normal provider retry recovery to `provider_self_recovered`, not
   to Hermes. Attribute a uniquely correlated alternate collection to
   `hermes_assisted` without claiming that the subscription invoice changed.
5. The documented T+3 retry sequence is specifically the card flow. Provider
   facts and scenarios must include `payment_method`; do not generalize card
   behavior to every method.

## Recommended runtime configuration

- Fresh `AIAgent` for each due decision.
- Dedicated, isolated Hermes profile/home.
- `provider: gemini`, configurable model defaulting to
  `gemini-3.7-flash`.
- No tools for the first integration; deterministic context is passed directly.
- Memory, context-file loading, skills mutation, curator behavior, delegation,
  terminal, file, browser, cron, and code execution disabled.
- `max_iterations` near 3, with application-level timeout and one schema repair
  at most.
- Local Pydantic validation followed by the existing deterministic policy.
- Model name, prompt version, latency, usage/cost when available, raw response,
  validation result, proposal, and policy result recorded in the audit ledger.

