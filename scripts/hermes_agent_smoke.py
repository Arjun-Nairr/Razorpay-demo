"""User-run smoke: ONE real Case 3 decision through the ACTUAL isolated Nous
Hermes runtime + real Gemini. Records sanitized runtime / tool-call evidence.

    python scripts/hermes_agent_smoke.py

Requires GEMINI_API_KEY in the environment or the gitignored root .env, and the
installed Hermes runtime at the proven revision. Makes ONE real Gemini call via
Hermes. No DB, no Razorpay, no messages/charges/links. Nothing secret is printed.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hermes.hermes_agent_strategist import HermesAgentStrategist  # noqa: E402
from hermes.runtime import _load_dotenv  # noqa: E402
from hermes.types import StrategySnapshot  # noqa: E402

_load_dotenv()
if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
    print("GEMINI_API_KEY not set (env or root .env). Nothing was called.")
    raise SystemExit(2)

snap = StrategySnapshot(
    case_id="smoke-case", obligation_id="sub_demo_smoke", amount_minor=1_000_000,
    currency="INR", failure_reason="insufficient_funds", state="active",
    provider_retry_eligible=True, provider_retry_evidence="provider_retry_signal",
    retry_outcome_recorded=False, wait_hours_remaining=72,
    messages_remaining=2, links_remaining=1, actions_remaining=3,
)

strat = HermesAgentStrategist()  # verifies the installed revision; no mock
print(f"Hermes revision : {strat._revision}")
print(f"Isolated home   : {strat._home}")
print(f"Model           : {strat._gemini_model}")
print("Calling actual Hermes + Gemini for one Case 3 decision ...\n")

try:
    proposal = strat.propose(snap)
    print("PROPOSAL (still faces deterministic policy):")
    print(f"  action              : {proposal.action.value}")
    print(f"  proposed_wait_hours : {proposal.proposed_wait_hours}")
    print(f"  confidence (uncal.) : {proposal.confidence}")
    print(f"  message_intent      : {proposal.message_intent!r}")
except Exception as exc:  # bounded-failure path
    print(f"DECISION FAILED (engine would record a strategist failure): {type(exc).__name__}: {exc}")

meta = strat.last_run_meta
print("\nSANITIZED RUN EVIDENCE (audit metadata, no transcript / chain-of-thought):")
print(json.dumps({
    "model": meta.model,
    "prompt_version": meta.prompt_version,
    "latency_ms": round(meta.latency_ms),
    "repair_used": meta.repair_used,
    "validation_result": meta.validation_result,
    "usage": meta.usage,
    "hermes": meta.extra,
}, indent=2))
