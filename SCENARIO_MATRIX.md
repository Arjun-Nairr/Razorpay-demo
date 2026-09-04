# Five-Case Scenario Matrix

> **SUPERSEDED (2026-09-04, Iteration 14/15):** this five-case plan is
> replaced by THREE deferred exemplars - consistently on-time, consistently
> late, and mixed history with a justified optional history lookup - built
> only after the Razorpay Test Mode HYBRID slice (`RAZORPAY_TEST_SLICE.md`,
> `IMPLEMENTATION_BACKLOG.md` §2/§5) is Codex-reviewed and live-verified. Case
> 3 below is the one already-proven vertical slice (`case-11`); the table
> stays as historical reference for its shared constraints and policy shape,
> not as an authorization to build cases 1/2/4/5 as written.

The batch contains three common payment failures and two payment-history
outliers. All five use the same workflow, action types, and policy engine.

| Case | Type | Evidence | Expected strategy | Evidence mode | Final outcome / attribution |
|---|---|---|---|---|---|
| 1. Temporary bank failure | Common plumbing proof | Temporary card/provider error; retry explicitly eligible; normal payment history | Wait for the provider-owned retry; do not message immediately | Real/hybrid candidate; real calendar retry is not accelerated | Recovered / `provider_self_recovered` |
| 2. Expired payment method | Common | Expired-card failure; otherwise ordinary account | Request the approved payment-method-update flow; suppress pointless same-card retries | Deterministic Razorpay-shaped replay | Customer updates method; recovered with attribution based on the actual payment path |
| 3. Insufficient funds with adaptation | Common hero intelligence case | Card insufficient-funds failure; one eligible retry; merchant owns communication | Wait once; after a simulated failed outcome, change strategy to reminder plus uniquely correlated recovery link | Deterministic replay; every event labelled `SIMULATED` | Alternate payment captured / `hermes_assisted` |
| 4. Normally always on time | Outlier | Long perfect payment history; first anomalous failure; no risk signals | Prefer no immediate contact; allow a short grace window and one retry | Deterministic replay | Recovered / `provider_self_recovered`, zero unnecessary contact |
| 5. Never on time | Outlier | Consistent late-payment history; repeated prior failures/recoveries; current attempts near limit | Make one bounded attempt, then stop/exhaust and recommend a named prepaid/shorter-cycle option | Deterministic replay | `exhausted` / `unrecovered`, structural recommendation only |

## Why these cases

- Cases 1–3 cover common, cleanly distinguishable failure patterns.
- Case 3 proves multi-step strategy adaptation.
- Case 4 proves that taking no immediate action can be intelligent.
- Case 5 proves stopping rules and long-term structural recommendations.
- The batch produces recovery, no-action, strategy-change, and exhaustion
  evidence without adding another payment provider or workflow.

## Shared constraints

- Decision-driving payment history comes from Razorpay or is derived from it.
- Every provider fact includes `payment_method`; card retry behavior is not
  generalized to unsupported methods.
- Events are labelled `REAL TEST MODE` or `SIMULATED`.
- A recovery-link payment is separately correlated and is not described as
  settling the original subscription invoice.
- Optional merchant facts cannot be required for a decision.
- Only verified captured payments increase test-mode recovered value.
- Every case uses the same allowed actions and deterministic policies.
- Scenario fixtures define expected outcomes for repeatable evaluation.
