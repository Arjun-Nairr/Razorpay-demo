"""One real Gemini round-trip for the Hermes runtime spike. Run by the user.

    pip install "google-genai"          # or: pip install ".[gemini]"
    export GEMINI_API_KEY=...           # PowerShell: $env:GEMINI_API_KEY="..."
    python scripts/hermes_smoke.py

Builds a Case 3 insufficient-funds snapshot, runs ONE HermesStrategist
decision against the live model, and prints the run metadata + the parsed
proposal as JSON. The API key is read from the environment and never printed.
Exit code 0 on a validated proposal, 1 otherwise (the failure type is printed).
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hermes.hermes_strategist import HermesStrategist  # noqa: E402
from hermes.types import StrategySnapshot  # noqa: E402

SNAPSHOT = StrategySnapshot(
    case_id="smoke-case",
    obligation_id="smoke-sub",
    amount_minor=1_000_000,
    currency="INR",
    failure_reason="insufficient_funds",
    state="waiting",
    provider_retry_eligible=True,
    provider_retry_evidence="provider_retry_signal",
    retry_outcome_recorded=True,  # a provider retry has already failed
    communication_owner="merchant",
    consent=True,
    reachable_channel=True,
    messages_remaining=2,
    links_remaining=1,
    actions_remaining=3,
    prior_action="WAIT_FOR_PROVIDER_RETRY",
    prior_policy_outcome="ALLOW",
)


def main() -> int:
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY not set; refusing to run.", file=sys.stderr)
        return 2

    strategist = HermesStrategist()  # real google-genai transport
    try:
        proposal = strategist.propose(SNAPSHOT)
    except Exception as exc:  # noqa: BLE001  (spike: report any failure type)
        meta = strategist.last_run_meta
        print(json.dumps({
            "outcome": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "run_meta": dataclasses.asdict(meta) if meta else None,
        }, indent=2))
        return 1

    print(json.dumps({
        "outcome": "ok",
        "run_meta": dataclasses.asdict(strategist.last_run_meta),
        "proposal": {
            "action": proposal.action.value,
            "diagnosis": proposal.diagnosis,
            "rationale": proposal.rationale,
            "confidence": proposal.confidence,
            "proposed_wait_hours": proposal.proposed_wait_hours,
            "message_intent": proposal.message_intent,
        },
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
