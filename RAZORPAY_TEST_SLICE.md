# Razorpay Test Mode integration slice

Verified 2026-09-04. Implementation contract for one hybrid recovery flow;
not evidence that Razorpay has already been integrated.

## Verified provider facts

- Standard links use POST /v1/payment_links. reference_id is unique and at
  most 40 characters. notify controls email/SMS; reminder_enable controls
  reminders. A unique reference is not proof of a generic idempotency header.
  [Create link](https://razorpay.com/docs/api/payments/payment-links/create-standard/?preferred-country=IN)
- payment_link.paid includes link/order/payment entities. Subscribe to the
  Payment Link event rather than assuming generic payment events contain
  every correlation field.
  [Webhook payload](https://razorpay.com/docs/webhooks/payment-links/?preferred-country=US)
- Verify raw request bytes before parsing, deduplicate x-razorpay-event-id,
  and tolerate out-of-order delivery.
  [Validation](https://razorpay.com/docs/webhooks/validate-test/?preferred-country=IN)
- Payment records include ID, amount in minor units, currency, status, method,
  order/invoice references where present, timestamp and failure fields such
  as error_reason. Missing fields are unknown, not invented facts.
  [Payment entity](https://razorpay.com/docs/api/payments/entity/)

## Recommended bounded implementation

Keep the initial SaaS obligation/history and accelerated failure/retry sequence
explicitly simulated. Replace only the authorized recovery-link creation and
confirmation with genuine Razorpay Test Mode operations. This is HYBRID proof,
not a native subscription-retry integration. Do not mutate historical case-11.

Persist case/action/reference/link-ID/payment-ID correlation across restart.
Keep returned link URL separate from payment ID. On an ambiguous create timeout,
do not mint another reference or blindly repeat a POST: reconcile or stop safely.
Do not mark recovered until signed event plus provider readback agree on link,
payment, amount, currency and captured/paid status. Count once even if multiple
provider event types arrive. Never claim the original subscription is settled
or reactivated by a separate Payment Link.

Expose only the webhook route through any public tunnel; never expose demo
mutation/read endpoints or the dashboard. Dashboard webhook setup and manual
test checkout are user-gated. Default real-provider execution to disabled;
require explicit test mode and reject non-test credentials.

Offline tests first. Operator authorizes one fresh hybrid run later, after
Codex review. No customer notifications, partial payments, live-money APIs,
plan/access changes, self-learning, or three-scenario expansion in this slice.
