"""One real Gemini round-trip for the Hermes runtime spike. Run by the user.

    python -m pip install ".[gemini]"      # google-genai + python-dotenv
    # put your key in <project root>/.env  (a blank .env is created for you):
    #     GEMINI_API_KEY=your-key-here
    # ...or export it: PowerShell  $env:GEMINI_API_KEY="..."   bash  export GEMINI_API_KEY=...
    python scripts/hermes_smoke.py

Builds a Case 3 insufficient-funds snapshot, runs ONE HermesStrategist
decision against the live model, and prints the run metadata + the parsed
proposal as JSON. The API key is read from the environment (a project-root
.env is merged in first, without overriding anything already set) and is
never printed. On failure only the exception *type* and the redacted run
metadata are printed - never the raw exception message.

Exit code: 0 validated proposal / 1 failure / 2 no key.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hermes.hermes_strategist import HermesStrategist  # noqa: E402
from hermes.types import StrategySnapshot  # noqa: E402

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _load_project_env(dotenv_path: str | None = None) -> None:
    """Merge ``<project root>/.env`` into ``os.environ`` without overriding any
    variable that is already set (ambient environment always wins). A missing
    file or a missing ``python-dotenv`` is a silent no-op.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return  # python-dotenv not installed; ambient environment only
    path = dotenv_path or os.path.join(_PROJECT_ROOT, ".env")
    load_dotenv(path, override=False)


SNAPSHOT = StrategySnapshot(
    case_id="smoke-case",
    obligation_id="smoke-sub",
    amount_minor=1_000_000,
    currency="INR",
    failure_reason="insufficient_funds",
    state="waiting",
    provider_retry_eligible=True,
    provider_retry_evidence="provider_retry_signal",
    retry_outcome_recorded=True,  # one prior provider retry has failed
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
    _load_project_env()  # before the key check; existing env vars take precedence
    if not os.environ.get("GEMINI_API_KEY"):
        print(
            "GEMINI_API_KEY not set. Put it in "
            f"{os.path.join('.', '.env')} (GEMINI_API_KEY=...) or export it, then re-run.",
            file=sys.stderr,
        )
        return 2

    strategist = HermesStrategist()  # real google-genai transport
    try:
        proposal = strategist.propose(SNAPSHOT)
    except Exception as exc:  # noqa: BLE001  (spike: report the failure type)
        meta = strategist.last_run_meta
        # Only the type + already-redacted run metadata. Never str(exc): an
        # SDK/auth error message can carry a key fragment or endpoint detail.
        print(json.dumps({
            "outcome": "failed",
            "error_type": type(exc).__name__,
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
