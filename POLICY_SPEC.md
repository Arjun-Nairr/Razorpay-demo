# Hermes Recovery Policy Specification

Status: ready to convert into implementation tasks

## Purpose

This contract defines what Hermes may propose and what deterministic policy may
authorize. Gemini never receives direct authority over payments, commercial
terms, account access, or recovered-money accounting.

## User stories

1. As a billing operator, I want failed Razorpay subscriptions to create one
   recovery case, so that failures are handled without duplication.
2. As a customer, I want recovery contact to respect consent and cooldowns, so
   that I am not spammed.
3. As a reliable customer, I want one anomalous failure treated cautiously, so
   that a temporary issue does not trigger an aggressive response.
4. As a chronically late customer, I want attempts to stop at a defined limit,
   so that Hermes does not create an endless retry loop.
5. As a billing operator, I want Hermes to change strategy after a failed
   attempt, so that recovery is adaptive rather than repetitive.
6. As a company, I want every AI proposal policy-checked, so that the model
   cannot perform unauthorized actions.
7. As a company, I want commercial changes to require consent, so that Hermes
   cannot alter plans, prices, discounts, billing dates, or payment methods.
8. As a company, I want access-hold decisions governed by billing policy, so
   that one model decision cannot freeze a customer account.
9. As an auditor, I want every input, proposal, policy decision, action, and
   outcome recorded, so that the full recovery path is explainable.
10. As an evaluator, I want recovered value based only on verified captured
    payments, so that the demo does not overstate results.
11. As an operator, I want disputed or inconsistent cases escalated, so that
    automation fails safely.
12. As a demo presenter, I want logical time to advance deterministically, so
    that multi-step cases complete inside five minutes.

## AI proposal contract

Gemini may propose exactly one of these actions:

| Proposal | Meaning |
|---|---|
| `WAIT_FOR_PROVIDER_RETRY` | Wait for a Razorpay-managed eligible retry and re-evaluate afterward. |
| `SEND_REMINDER` | Queue one provider-neutral recovery message. |
| `REQUEST_PAYMENT_METHOD_UPDATE` | Queue a message directing the customer to an approved Razorpay update flow. |
| `CREATE_RECOVERY_LINK` | Create one alternate Razorpay collection link, explicitly reconciled to the case. |
| `RECOMMEND_STRUCTURAL_CHANGE` | Record a non-executing recommendation such as prepaid or a shorter billing cycle. |
| `TAKE_NO_ACTION` | Deliberately wait without customer contact or payment action. |
| `STOP` | Recommend ending automated recovery. |
| `ESCALATE` | Recommend human review. |

Each proposal includes diagnosis, cited evidence fields, requested execution
time, concise rationale, optional message intent, and confidence.

Gemini cannot propose or supply payment amounts, customer/provider identifiers,
URLs, retry limits, discounts, new plan terms, or access-control commands.

## Always prohibited

Hermes must never directly:

- charge a payment method outside an existing Razorpay mandate and provider
  eligibility;
- change a plan, price, discount, billing date, payment method, or contract;
- mark a payment successful;
- freeze, delete, or modify account access;
- continue work after a terminal state;
- use missing optional merchant data as a reason to refuse a basic decision.

## Default deterministic limits

These values are configuration, not prompt instructions:

| Limit | Default |
|---|---:|
| Authorized recovery actions per case | 3 |
| Customer messages per case | 2 |
| Message cooldown | 24 logical hours |
| Recovery links per case | 1 |
| Payment-method update requests per case | 1 |
| Maximum AI schema/timeout retry | 1 |
| Maximum proposed wait | 72 logical hours |
| Grace before access-hold recommendation | 72 logical hours after confirmed nonpayment |
| Work-loop steps per `run` call | 50 |

Provider-native retry eligibility and limits remain authoritative. Hermes does
not invent or bypass a Razorpay retry.

## Policy evaluation order

Every proposal is evaluated in this fixed order:

1. **Provider truth:** if the obligation is already captured, cancel pending
   work and mark recovered.
2. **Case state:** terminal cases cannot authorize further recovery actions.
3. **Freshness:** stale case versions or out-of-order facts require reload or
   reconciliation.
4. **Deduplication:** reject an existing event, payment, or action idempotency
   key.
5. **Dispute and consent:** disputes escalate; messaging requires consent.
6. **Attempt limits:** enforce provider and Hermes action limits.
7. **Cooldowns:** block premature repeat contact.
8. **Action preconditions:** validate the proposal against the failure class and
   available provider flow.
9. **Commercial safety:** replace any plan, pricing, or access change with a
   non-executing recommendation or escalation.
10. **Authorization:** persist the allowed action and audit decision before any
    external effect.

Policy returns `ALLOW`, `REPLACE`, `BLOCK`, `STOP`, `ESCALATE`, or `EXHAUST` with
a stable reason code.

## Action-specific rules

### Wait for provider retry

Allow only when Razorpay considers the subscription retryable and no terminal
payment exists. Block for expired/invalid payment credentials or exhausted
provider retries. Waiting is an authorized action even though it has no outbound
message.

### Send reminder

Require contact consent, a reachable channel, an unpaid obligation, an expired
cooldown, and unused message capacity. Message text cannot promise a discount,
threaten suspension, or claim payment success.

### Request payment-method update

Allow for expired/invalid credential or authentication-related failures when an
approved Razorpay customer flow exists. The customer must complete the change.
Hermes never modifies the payment method.

### Create recovery link

Allow at most once when alternate collection is appropriate and the link can be
uniquely correlated to the case. Payment through this link must be reconciled as
an alternate collection; it must not falsely mark the original subscription
invoice paid.

### Recommend structural change

Always non-executing. It may recommend prepaid, a shorter billing cycle, a
downgrade, or a billing-date review. The dashboard records it separately from
recovery actions and recovered value.

### Stop, escalate, or exhaust

- Stop when further action is inappropriate, consent prevents all useful
  contact, the account/subscription is cancelled, or policy says no intervention.
- Escalate disputes, inconsistent provider state, uncertain payment outcomes
  that reconciliation cannot resolve, or repeated internal failures.
- Exhaust when all permitted recovery attempts finish without captured payment.

## Access-hold boundary

Hermes may record `ACCESS_HOLD_RECOMMENDED`; it cannot apply the hold.

The deterministic recommendation requires all of:

- verified outstanding payment;
- exhausted permitted attempts;
- expired 72-hour logical grace period;
- no active dispute;
- no verified captured payment.

A real SaaS entitlement system and automatic access restriction are outside the
first demo. If added later, the company-owned billing policy must apply the hold,
prefer limited/read-only access first, and restore access after verified payment.

## Payment-history classifications

These are deterministic derived facts supplied to Gemini:

- **Normally on time:** at least six prior obligations and at least 95% paid by
  their due time.
- **Chronically late:** at least five prior obligations and at least 80% paid
  after their due time or only after recovery action.
- Otherwise: **ordinary history**.

Gemini may use these facts to choose tone and timing. They never override
provider truth, consent, attempt limits, or terminal-state rules.

## Five expected policy paths

| Case | First action | Adaptation | Expected terminal state |
|---|---|---|---|
| Temporary bank failure | Wait for provider retry | None | `recovered` |
| Expired payment method | Request payment-method update | None | `recovered` |
| Insufficient funds | Wait once | Reminder/recovery link after failed retry | `recovered` |
| Normally always on time | Take no immediate action/grace | One provider retry | `recovered` with zero messages |
| Chronically late | One bounded attempt | Stop and recommend prepaid/shorter cycle | `exhausted` |

## Recovery and completion rules

Recovered value increases only after a signature-verified Razorpay event proves
that one unique linked payment is captured after case creation. A captured
payment contributes once. Creating a link, sending a message, authorization, or
an AI prediction contributes zero.

A case completes as `recovered`, `stopped`, `escalated`, or `exhausted`. On
completion, cancel pending actions and retain the append-only audit history.

## Acceptance tests through `RecoveryEngine`

Tests use only `receive`, `run`, and `inspect` with fake Razorpay, scripted
Gemini, and in-memory ledger adapters.

Required behaviors:

- invalid signatures create no trusted case;
- duplicate and out-of-order webhooks do not duplicate cases or money;
- every proposal produces an audited policy decision;
- blocked proposals execute no effect;
- message cooldown and count limits hold;
- terminal cases schedule no work;
- structural changes and access holds remain recommendations;
- Gemini failure produces no unsafe action;
- each of the five scenarios reaches its expected state;
- batch recovered value equals unique verified captured payments;
- the normally-on-time case has zero unnecessary messages;
- the chronically-late case stops at its bounded limit.

## Out of scope

- Actual plan, price, billing-date, discount, or entitlement changes
- Real access suspension
- Real messaging provider in the first vertical slice
- Checkout abandonment and B2B receivables
- Production compliance or legal-policy claims
- Credit scoring, bank-balance inference, psychographics, or churn prediction
- General payment-provider abstraction

