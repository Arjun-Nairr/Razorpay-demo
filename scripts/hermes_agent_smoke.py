"""User-run smoke: ONE Case 3 DECISION through the ACTUAL isolated Nous Hermes
runtime + real Gemini. One decision may take several model requests (initial
reasoning, tool calls, and at most one schema-repair turn). Records sanitized
runtime / tool-call evidence only - no transcript, no chain-of-thought.

    python scripts/hermes_agent_smoke.py

Requires GEMINI_API_KEY in the environment or the gitignored root .env, and the
installed Hermes runtime at the proven revision. No DB, no Razorpay, no
messages / charges / links. Nothing secret is printed. Exits nonzero on any
failure, even when audit metadata is absent.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hermes.hermes_agent_strategist import HermesAgentStrategist  # noqa: E402
from hermes.runtime import _load_dotenv  # noqa: E402
from hermes.types import StrategySnapshot  # noqa: E402

_ALLOWED_META_KEYS = (
    "runtime_revision", "provider", "provider_model", "duration_ms",
    "model_iterations_used", "model_iterations_budget",
    "tool_calls_used", "tool_calls_budget", "tokens",
    "evidence_requests", "evidence_returned",
    "model_confidence", "confidence_band", "confidence_basis",
    "decision_action", "repair_used", "validation_result",
    "failure_category", "failure_stage", "child_exit_code",
)


def _print_meta(meta) -> None:
    print("\nSANITIZED RUN EVIDENCE (allowlisted audit fields; no transcript):")
    if meta is None:
        print("  (no run metadata available)")
        return
    extra = meta.extra if isinstance(getattr(meta, "extra", None), dict) else {}
    safe = {
        "model": getattr(meta, "model", None),
        "prompt_version": getattr(meta, "prompt_version", None),
        "latency_ms": round(getattr(meta, "latency_ms", 0) or 0),
        "repair_used": getattr(meta, "repair_used", None),
        "validation_result": getattr(meta, "validation_result", None),
        **{k: extra[k] for k in _ALLOWED_META_KEYS if k in extra},
    }
    print(json.dumps(safe, indent=2))


def main() -> int:
    _load_dotenv()
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        print("GEMINI_API_KEY not set (env or root .env). Nothing was called.", file=sys.stderr)
        return 2

    snap = StrategySnapshot(
        case_id="smoke-case", obligation_id="sub_demo_smoke", amount_minor=1_000_000,
        currency="INR", failure_reason="insufficient_funds", state="active",
        provider_retry_eligible=True, provider_retry_evidence="provider_retry_signal",
        retry_outcome_recorded=False, wait_hours_remaining=72,
        messages_remaining=2, links_remaining=1, actions_remaining=3,
        is_demo_case=True,  # the smoke fixture is an explicitly identified demo customer
    )

    try:
        strat = HermesAgentStrategist()  # verifies the installed revision; no mock
    except Exception as exc:  # runtime missing / wrong revision
        print(f"Hermes runtime unavailable ({type(exc).__name__}). No call made.", file=sys.stderr)
        return 2

    print(f"Hermes revision : {strat._revision}")
    print(f"Isolated home   : {strat._home}")
    print(f"Model           : {strat._gemini_model}")
    print("Running one Case 3 decision through actual Hermes + Gemini "
          "(may involve several model requests) ...\n")

    ok = True
    try:
        proposal = strat.propose(snap)
        print("PROPOSAL (still faces deterministic policy validation):")
        print(f"  action              : {proposal.action.value}")
        print(f"  proposed_wait_hours : {proposal.proposed_wait_hours}")
        print(f"  confidence (uncal.) : {proposal.confidence}")
        print(f"  message_intent      : {proposal.message_intent!r}")
    except Exception as exc:  # bounded-failure path; category is in the audit
        ok = False
        cat = None
        if getattr(strat, "last_run_meta", None) and isinstance(strat.last_run_meta.extra, dict):
            cat = strat.last_run_meta.extra.get("failure_category")
        print(f"DECISION FAILED ({type(exc).__name__}); failure_category={cat}. "
              "The engine would record a strategist failure.", file=sys.stderr)

    _print_meta(getattr(strat, "last_run_meta", None))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
