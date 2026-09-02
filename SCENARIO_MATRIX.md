# Five-Case Scenario Matrix

The batch contains three common payment failures and two payment-history
outliers. All five use the same workflow, action types, and policy engine.

| Case | Type | Evidence | Expected strategy | Final outcome |
|---|---|---|---|---|
| 1. Temporary bank failure | Common | Temporary provider/bank error; normal payment history | Wait for the next eligible Razorpay retry; do not message immediately | Retry succeeds; recovered |
| 2. Expired payment method | Common | Expired-card failure; otherwise ordinary account | Request payment-method update; suppress pointless same-card retries | Customer updates method; recovered |
| 3. Insufficient funds with adaptation | Common | Insufficient-funds failure; one permitted retry | Wait once; if the retry fails, change strategy and send a recovery reminder/link | Second strategy succeeds; recovered |
| 4. Normally always on time | Outlier | Long perfect payment history; first anomalous failure; no risk signals | Prefer no immediate contact; allow a short grace window and one retry | Retry succeeds; recovered with zero unnecessary contact |
| 5. Never on time | Outlier | Consistent late-payment history; repeated prior failures/recoveries; current attempts near limit | Avoid an endless retry loop; make one bounded recovery attempt, then stop/exhaust and recommend prepaid or shorter billing | Recovery fails; exhausted with structural recommendation |

## Why these cases

- Cases 1–3 cover common, cleanly distinguishable failure patterns.
- Case 3 proves multi-step strategy adaptation.
- Case 4 proves that taking no immediate action can be intelligent.
- Case 5 proves stopping rules and long-term structural recommendations.
- The batch produces recovery, no-action, strategy-change, and exhaustion
  evidence without adding another payment provider or workflow.

## Shared constraints

- Decision-driving payment history comes from Razorpay or is derived from it.
- Optional merchant facts cannot be required for a decision.
- Only verified captured payments increase test-mode recovered value.
- Every case uses the same allowed actions and deterministic policies.
- Scenario fixtures define expected outcomes for repeatable evaluation.

