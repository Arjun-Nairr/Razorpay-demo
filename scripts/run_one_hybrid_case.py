"""ONE controlled hybrid demo case: real Hermes/Gemini decisions, at most one
real Razorpay Test Mode recovery link. Never calls the simulated capture step
- final payment confirmation must come from a real, independently-verified
Razorpay webhook (see scripts/webhook_relay.py + the /webhooks/razorpay-test
route). Talks only to the already-running local API (existing endpoints); it
does not open the DB, hold credentials, or force an outcome.

Fails closed before any write: refuses to even open a case unless ``/health``
confirms real Hermes/Gemini mode, the hybrid Razorpay Test Mode provider, and
real Test Mode actions enabled (see ``_require_ready``). The opened case's own
``evidence_mode`` stays ``SIMULATED`` - that is the correct, honest label for
its synthetic failure/retry intake; only the recovery-link creation and its
eventual payment confirmation are real. This script never relabels the case.

    python scripts/run_one_hybrid_case.py

Env: HERMES_API_BASE (default http://127.0.0.1:8000).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("HERMES_API_BASE", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = 120


def _req(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        print(f"  ! {method} {path} -> HTTP {e.code}: {detail}", file=sys.stderr)
        raise SystemExit(2)
    except urllib.error.URLError as e:
        print(f"  ! cannot reach API at {BASE} ({e.reason}).", file=sys.stderr)
        raise SystemExit(2)


def _case(cid: str) -> dict:
    return _req("GET", f"/demo/case/{cid}")


def _require_ready(health: dict) -> None:
    """Fail closed before ANY write (including ``POST /demo/case``) unless
    ``/health`` explicitly confirms all three: real Hermes/Gemini strategist
    mode, the hybrid Razorpay Test Mode provider, and real Test Mode actions
    actually enabled. A missing, fake, disabled, or mismatched field refuses -
    it never assumes readiness from partial or absent evidence."""
    problems = []
    if health.get("mode") != "hermes-runtime":
        problems.append(
            f"strategist mode is {health.get('mode')!r}, need 'hermes-runtime'")
    if health.get("payment_provider") != "hybrid_test_mode":
        problems.append(
            f"payment provider is {health.get('payment_provider')!r}, "
            "need 'hybrid_test_mode'")
    if health.get("payment_provider_test_mode_enabled") is not True:
        problems.append(
            "real Test Mode actions are not enabled "
            "(payment_provider_test_mode_enabled is not true)")
    if problems:
        print("  ! refusing to run - preflight failed:", file=sys.stderr)
        for p in problems:
            print(f"    - {p}", file=sys.stderr)
        raise SystemExit(2)


def _report(cid: str) -> dict:
    view = _case(cid)
    case = view["case"]
    print("\n--- current case snapshot ---")
    print(f"case_id={cid} state={case['state']} attribution={case.get('attribution')}")
    print(f"amount_minor={case.get('amount_minor')} currency={case.get('currency')} "
          f"recovered_minor={case.get('recovered_minor', 0)}")
    for i in case.get("action_intents", []):
        print(f"  intent: action={i['action']} status={i['status']} "
              f"reference={i.get('reference')} url={i.get('url')}")
    return view


def main() -> int:
    health = _req("GET", "/health")
    print(f"API: {BASE}  evidence_mode={health.get('evidence_mode')}  "
          f"mode={health.get('mode')}  payment_provider={health.get('payment_provider')}  "
          f"test_mode_enabled={health.get('payment_provider_test_mode_enabled')}")
    _require_ready(health)

    opened = _req("POST", "/demo/case")
    cid, obl = opened["case_id"], opened["obligation_id"]
    print(f"\nCASE_ID={cid}")
    print(f"obligation={obl} evidence_mode={opened['evidence_mode']}")

    print("\n[1] real Hermes/Gemini decision #1 (advance)...")
    r = _req("POST", "/demo/step", {"case_id": cid, "step": "advance"})
    print(f"    run: {json.dumps(r.get('run', {}))}")
    view = _case(cid)
    state = view["case"]["state"]
    print(f"    case state after decision #1: {state}")
    if state != "waiting":
        print(f"    Not waiting on a provider retry after decision #1 - stopping "
              f"here (Hermes did not propose/authorize a wait). Reporting outcome.")
        _report(cid)
        return 0

    print("\n[2] simulated failed-retry event + real Hermes/Gemini decision #2 "
          "(retry_failed)...")
    r = _req("POST", "/demo/step", {"case_id": cid, "step": "retry_failed"})
    print(f"    run: {json.dumps(r.get('run', {}))}")
    view = _report(cid)
    case = view["case"]

    has_link = any(
        i.get("action") == "CREATE_RECOVERY_LINK" and i.get("status") == "executed"
        for i in case.get("action_intents", [])
    )
    if has_link:
        link = next(i for i in case["action_intents"] if i["action"] == "CREATE_RECOVERY_LINK")
        print("\n>>> REAL Razorpay Test Mode recovery link created:")
        print(f"    link id (reference) = {link['reference']}")
        print(f"    checkout URL        = {link['url']}")
    elif case["state"] == "escalated":
        print(f"\n    Hermes safely escalated this case (attribution="
              f"{case.get('attribution')}). No recovery link was created. "
              f"This is a valid, honest outcome - not forced further.")
    else:
        print(f"\n    No recovery link was created this decision. Final state: "
              f"{case['state']}.")

    print("\nSTOPPING HERE. Not calling the simulated 'capture' step - final "
          "confirmation must come from a real, independently-verified Razorpay "
          "webhook delivered to /webhooks/razorpay-test.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
