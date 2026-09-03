# Razorpay Developer Tools Finding

Research date: 2026-09-02; integration facts refreshed 2026-09-03

## Verified facts

- The screenshot is Razorpay's documentation landing page, not an independent
  sandbox or merchant dashboard.
- The Razorpay CLI requires a Dashboard-generated Key ID and Key Secret. Test
  mode uses an `rzp_test_` key. [CLI installation](https://razorpay.com/docs/cli/install-cli/)
- The Razorpay MCP server also requires Razorpay API credentials. Its remote
  version uses a merchant token derived from the key and secret; the local
  version uses the key and secret directly. [Official MCP repository](https://github.com/razorpay/razorpay-mcp-server)
- Neither tool supplies an account, credentials, or a separate sandbox. Test
  behavior is selected with test API keys. [Sandbox setup](https://razorpay.com/docs/api/sandbox-setup/)
- Razorpay states that Test Mode can be used before KYC completion, while live
  payments require completed KYC. [Quickstart](https://razorpay.com/docs/payments/quickstart/)

## Decision

- Keep Hermes on the direct Razorpay API/official SDK plus signed webhooks.
- Do not use MCP as the product runtime. It adds another AI/tool layer, still
  needs the blocked credentials, and does not provide the full subscription and
  webhook surface required by Hermes.
- The CLI may be used later for manual setup/debugging, but it cannot solve the
  PAN onboarding issue.

## Integration facts

- Card-subscription retries are provider-owned calendar-time behavior on
  T+1/T+2/T+3; Hermes logical time cannot accelerate them. [Payment retries](https://razorpay.com/docs/payments/subscriptions/payment-retries/)
- `customer_notify=true` assigns subscription communication to Razorpay;
  `false` assigns it to the merchant. Hermes must suppress duplicate merchant
  contact when Razorpay owns communication. [Create Subscription API](https://razorpay.com/docs/api/payments/subscriptions/create-subscription/)
- Payment Links use a separately correlated collection flow. A captured link
  payment can prove alternate recovery, but it must not be claimed to settle or
  reactivate the original subscription without separate evidence. [Payment Link API](https://razorpay.com/docs/api/payments/payment-links/create-standard/)
- The real webhook boundary must verify HMAC over the unchanged raw body,
  deduplicate with `x-razorpay-event-id`, and tolerate out-of-order delivery.
  [Webhook validation](https://razorpay.com/docs/webhooks/validate-test/)

## Required next Razorpay action

Open the actual [Razorpay Dashboard](https://dashboard.razorpay.com), enter Test
Mode, then navigate to Account & Settings -> API Keys -> Generate Key. If that
exact Dashboard path still forces PAN and provides no Test Dashboard option, do
not enter false data; capture that screen and contact Razorpay support.

