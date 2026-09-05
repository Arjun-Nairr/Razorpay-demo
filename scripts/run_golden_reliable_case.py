"""ONE controlled golden-path demo case: real Hermes/Gemini decisions, one
real Razorpay Test Mode recovery link, one real verified Telegram delivery.
Talks only to the already-running local API (existing endpoints plus the new
``deliver_message`` step); it does not open the DB, hold credentials, or
force an outcome. Requires ``--confirm-live`` - this makes real Gemini,
Razorpay Test Mode, and Telegram calls.

    python scripts/run_demo.ps1 -Mode hermes      # start the API first (separate window)
    python scripts/run_golden_reliable_case.py --confirm-live

Env: HERMES_API_BASE (default http://127.0.0.1:8000).

Preflight fails closed (no case, no write) unless: the pinned Hermes
revision is installed, ``GEMINI_API_KEY``/``DATABASE_URL`` are present,
``/health`` confirms real Hermes/Gemini mode + hybrid Razorpay Test Mode +
Telegram delivery enabled. No value is ever printed - only presence.

Runs exactly one fresh case through the reliable-customer (consistent
3-month history) path and REQUIRES, at each step, the exact expected shape:
decision #1 = WAIT_FOR_PROVIDER_RETRY + recommended_intervention=NONE;
decision #2 (after a simulated failed retry) = an authorized
CREATE_RECOVERY_LINK with no payment-plan recommendation; the real link's
draft message delivered through Telegram, verified SENT. If any required
decision differs, any safety guard rejects it, or any external response is
uncertain, this stops and reports honestly - it never forces state, edits
model output, fabricates evidence, or automatically reruns. Never opens or
completes checkout, never marks money recovered, never starts a tunnel.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

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
        print(f"  ! cannot reach API at {BASE} ({e.reason}). Start it first "
              "(scripts/run_demo.ps1 -Mode hermes).", file=sys.stderr)
        raise SystemExit(2)


def _case(cid: str) -> dict:
    return _req("GET", f"/demo/case/{cid}")


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    load_dotenv(os.path.join(root, ".env"), override=False)


def _preflight_env() -> list[str]:
    """Presence-only checks against the LOCAL process env - never a value
    printed. Complements (not replaces) the /health checks below, which
    confirm the RUNNING API's actual wiring."""
    _load_dotenv()
    problems = []
    if not os.environ.get("GEMINI_API_KEY", "").strip():
        problems.append("GEMINI_API_KEY is not set")
    if not os.environ.get("DATABASE_URL", "").strip():
        problems.append("DATABASE_URL is not set")
    if os.environ.get("RAZORPAY_PROVIDER", "").strip() != "hybrid_test_mode":
        problems.append("RAZORPAY_PROVIDER must be 'hybrid_test_mode'")
    for name in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET"):
        if not os.environ.get(name, "").strip():
            problems.append(f"{name} is not set")
    if (os.environ.get("TELEGRAM_ENABLED", "").strip().lower()
            not in ("1", "true", "yes", "on")):
        problems.append("TELEGRAM_ENABLED is not set to 1")
    if not os.environ.get("TELEGRAM_BOT_TOKEN", "").strip():
        problems.append("TELEGRAM_BOT_TOKEN is not set")
    if not os.environ.get("TELEGRAM_CHAT_ID", "").strip():
        problems.append("TELEGRAM_CHAT_ID is not set")
    try:
        from hermes.hermes_agent import EXPECTED_HERMES_REVISION
        from hermes.hermes_agent_strategist import _DEFAULT_CHECKOUT, _DEFAULT_PYTHON
        import subprocess
        if not _DEFAULT_PYTHON.exists() or not (_DEFAULT_CHECKOUT / "run_agent.py").exists():
            problems.append("the isolated Hermes runtime checkout/interpreter is missing")
        else:
            head = subprocess.run(
                ["git", "-C", str(_DEFAULT_CHECKOUT), "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=15,
            ).stdout.strip()
            if head != EXPECTED_HERMES_REVISION:
                problems.append(
                    f"installed Hermes revision {head[:12] or '?'} != pinned "
                    f"{EXPECTED_HERMES_REVISION[:12]}"
                )
    except Exception as exc:  # noqa: BLE001 - report the category, not a raw traceback
        problems.append(f"could not verify the Hermes runtime revision ({type(exc).__name__})")
    return problems


def _require_ready(health: dict) -> None:
    problems = []
    if health.get("mode") != "hermes-runtime":
        problems.append(f"strategist mode is {health.get('mode')!r}, need 'hermes-runtime'")
    if health.get("payment_provider") != "hybrid_test_mode":
        problems.append(
            f"payment provider is {health.get('payment_provider')!r}, need 'hybrid_test_mode'")
    if health.get("payment_provider_test_mode_enabled") is not True:
        problems.append("real Test Mode actions are not enabled")
    if health.get("message_delivery_channel") != "telegram":
        problems.append(
            f"message delivery channel is {health.get('message_delivery_channel')!r}, "
            "need 'telegram'")
    if problems:
        print("  ! refusing to run - preflight failed:", file=sys.stderr)
        for p in problems:
            print(f"    - {p}", file=sys.stderr)
        raise SystemExit(2)


def _decision(view: dict, decision_number: int) -> dict | None:
    """The Nth persisted AI_PROPOSAL's detail (1-indexed), or None."""
    proposals = [r["detail"] for r in view["timeline"] if r["kind"] == "AI_PROPOSAL"]
    if len(proposals) < decision_number:
        return None
    return proposals[decision_number - 1]


def _stop(reason: str) -> int:
    print(f"\n  ! STOPPING - {reason}. Reporting honestly; not forcing, not editing, "
          "not automatically rerunning.", file=sys.stderr)
    return 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--confirm-live", action="store_true",
                    help="required - this makes real Gemini/Razorpay/Telegram calls")
    args = ap.parse_args()
    if not args.confirm_live:
        print("Refusing to run without --confirm-live (this makes real external calls).",
              file=sys.stderr)
        return 2

    env_problems = _preflight_env()
    if env_problems:
        print("  ! refusing to run - preflight failed:", file=sys.stderr)
        for p in env_problems:
            print(f"    - {p}", file=sys.stderr)
        return 2

    health = _req("GET", "/health")
    print(f"API: {BASE}  mode={health.get('mode')}  "
          f"payment_provider={health.get('payment_provider')}  "
          f"test_mode_enabled={health.get('payment_provider_test_mode_enabled')}  "
          f"message_delivery_channel={health.get('message_delivery_channel')}")
    _require_ready(health)

    opened = _req("POST", "/demo/case")
    cid, obl = opened["case_id"], opened["obligation_id"]
    print(f"\nCASE_ID={cid}")
    print(f"obligation={obl} evidence_mode={opened['evidence_mode']}")

    print("\n[1] real Hermes/Gemini decision #1 (advance)...")
    r = _req("POST", "/demo/step", {"case_id": cid, "step": "advance"})
    print(f"    run: {json.dumps(r.get('run', {}))}")
    view = _case(cid)
    d1 = _decision(view, 1)
    state = view["case"]["state"]
    if state != "waiting" or d1 is None or d1.get("action") != "WAIT_FOR_PROVIDER_RETRY":
        return _stop(
            f"decision #1 was not the required bounded provider-retry wait "
            f"(state={state!r}, action={(d1 or {}).get('action')!r})")
    ri1 = d1.get("recommended_intervention")
    if ri1 not in (None, "NONE"):
        return _stop(f"decision #1 carried recommended_intervention={ri1!r}, required NONE")
    print(f"    decision #1 OK: WAIT_FOR_PROVIDER_RETRY, recommended_intervention=NONE, "
          f"confidence={d1.get('confidence')}")

    print("\n[2] simulated failed-retry event + real Hermes/Gemini decision #2 "
          "(retry_failed)...")
    r = _req("POST", "/demo/step", {"case_id": cid, "step": "retry_failed"})
    print(f"    run: {json.dumps(r.get('run', {}))}")
    view = _case(cid)
    case = view["case"]
    d2 = _decision(view, 2)
    has_link = any(
        i.get("action") == "CREATE_RECOVERY_LINK" and i.get("status") == "executed"
        for i in case.get("action_intents", [])
    )
    if d2 is None or d2.get("action") != "CREATE_RECOVERY_LINK" or not has_link:
        return _stop(
            f"decision #2 did not authorize a recovery link "
            f"(action={(d2 or {}).get('action')!r}, has_link={has_link})")
    ri2 = d2.get("recommended_intervention")
    if ri2 not in (None, "NONE"):
        return _stop(f"decision #2 carried recommended_intervention={ri2!r}, required NONE "
                     "(no payment-plan recommendation on a single failure)")
    link = next(i for i in case["action_intents"] if i["action"] == "CREATE_RECOVERY_LINK")
    if not link.get("url"):
        # The API's own case JSON has no separate "evidence mode" field on an
        # action intent (that label only exists in the Neon recovery_actions
        # view) - a non-empty checkout url on this hybrid-provider deployment
        # IS the confirmation: the fake adapter's link_url() always returns
        # None, so this can only be populated by a real Test Mode link.
        return _stop("the recovery link has no confirmed checkout URL")
    print(f"    decision #2 OK: CREATE_RECOVERY_LINK authorized, recommended_intervention=NONE")
    print(f"    REAL Razorpay Test Mode link created: reference={link['reference']}")
    print("    checkout URL: [redacted - see Neon recovery_actions.checkout_url_present]")
    if link.get("message_status") != "DRAFTED":
        return _stop(f"the approved message was not staged (message_status="
                     f"{link.get('message_status')!r}); refusing to attempt delivery")
    print(f"    message staged: message_status=DRAFTED")

    print("\n[3] atomically claim + send the staged message via the real Telegram adapter...")
    r = _req("POST", "/demo/step", {"case_id": cid, "step": "deliver_message"})
    delivery = r.get("delivery", {})
    print(f"    delivery step result: {json.dumps(delivery)}")
    view = _case(cid)
    link = next(i for i in view["case"]["action_intents"] if i["action"] == "CREATE_RECOVERY_LINK")
    if link.get("message_status") != "SENT" or link.get("delivery_outcome") != "sent":
        return _stop(
            f"Telegram delivery was not verified SENT (message_status="
            f"{link.get('message_status')!r}, delivery_outcome={link.get('delivery_outcome')!r}). "
            "This is an honest, safe stop - never claim SENT without a verified response.")
    print(f"    VERIFIED SENT: delivery_channel={link.get('delivery_channel')} "
          f"delivery_message_id={link.get('delivery_message_id')}")

    print("\n--- final case snapshot ---")
    final = view["case"]
    print(f"case_id={cid} state={final['state']} attribution={final.get('attribution')}")
    print(f"recovered_minor={final.get('recovered_minor', 0)} counted={final.get('counted')}")
    print("\nSTOPPING HERE. Not opening/completing checkout, not marking money recovered, "
          "not starting a tunnel. Full evidence is in Neon (see sql/neon_demo_inspect.sql).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
