"""Runs INSIDE the installed Nous Hermes venv, as an isolated subprocess.

Reads one JSON job on stdin, drives a fresh ``run_agent.AIAgent`` for exactly
one Case 3 decision with three case-scoped evidence tools, and prints one line:

    HERMES_CHILD_RESULT {json}

This file must not import anything from the ``hermes`` project package - only
the standard library and the Hermes runtime (``run_agent`` / ``tools`` /
``toolsets``), which is only importable under the Hermes interpreter.

Contract with the parent:
  * exit 0  + ``ok:true``  -> a validated proposal
  * exit 1  + ``ok:false`` -> a bounded, categorised failure (still safe to read)
  * any other exit code    -> abnormal; the parent rejects it even if stdout
    happens to contain a success payload.

Output is bounded and allowlisted: fixed failure CATEGORIES only, never a raw
exception message, stderr slice, or transcript. A synthetic secret in the
model output or an exception can never reach the audit or the console.

Isolation applied here (state, not an OS sandbox):
  * HERMES_HOME is a project-local throwaway dir (set by the parent).
  * skip_context_files / skip_memory / skip_background_review.
  * enabled_toolsets is a positive allowlist of one custom toolset; no
    terminal / browser / file / delegation / cron / code-exec tools exist.
  * tool_search bridge disabled (parent writes config.yaml) so the three tools
    are exposed directly and every dispatch name is asserted.
  * fresh AIAgent per process; the process exits after one decision.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time

RESULT_SENTINEL = "HERMES_CHILD_RESULT "
TOOL_NAMES = ("get_payment_retry_facts", "get_payment_history", "get_recovery_actions")
REQUIRED_KEYS = ("action", "diagnosis", "rationale", "confidence",
                 "proposed_wait_hours", "message_intent")
_ALL_ACTIONS = {
    "WAIT_FOR_PROVIDER_RETRY", "SEND_REMINDER", "REQUEST_PAYMENT_METHOD_UPDATE",
    "CREATE_RECOVERY_LINK", "RECOMMEND_STRUCTURAL_CHANGE", "TAKE_NO_ACTION",
    "STOP", "ESCALATE",
}
# Only the actions deterministic policy can actually authorize/execute today.
# STOP and a standalone SEND_REMINDER are deliberately NOT offered as executable
# (policy would only BLOCK them). Reminder copy still rides along with an
# authorized CREATE_RECOVERY_LINK via message_intent.
_SUPPORTED_ACTIONS = {
    "WAIT_FOR_PROVIDER_RETRY", "CREATE_RECOVERY_LINK", "ESCALATE",
}
MODEL_ITERATION_BUDGET = 8   # shared across the initial reasoning AND the one repair
TOOL_CALL_BUDGET = 6         # shared across the initial reasoning AND the one repair

# Fixed, allowlisted failure categories (no free-form strings ever leave here).
_FAIL_TOOL_EXPOSURE = "tool_exposure_mismatch"
_FAIL_SCHEMA = "schema_invalid_after_repair"
_FAIL_ITER_BUDGET = "model_iteration_budget_exhausted"
_FAIL_CHILD_EXCEPTION = "child_exception"

# Bounded validation reason slugs surfaced via ``validation_result`` (never a
# raw message): not_json, not_object, keys_mismatch, unknown_action,
# unsupported_action, confidence_type, confidence_range, wait_type,
# wait_nonpositive, text_field, message_not_approved, message_type.


def _emit(payload: dict) -> None:
    sys.stdout.write(RESULT_SENTINEL + json.dumps(payload) + "\n")
    sys.stdout.flush()


def _band(conf) -> str:
    try:
        c = float(conf)
    except (TypeError, ValueError):
        return "unknown"
    if c < 0.34:
        return "low"
    if c < 0.67:
        return "medium"
    return "high"


class _Evidence:
    """Case-bound tool backend over an immutable bundle prepared by the parent.

    Accepts no case id, SQL, URL, path, or executable input. ``get_payment_history``
    is a SINGLE optional expansion straight to twelve months, needs a short
    uncertainty reason, and is allowed at most once per decision (including
    during repair). Unavailable / partial history reports its ACTUAL coverage.
    """

    def __init__(self, bundle: dict):
        self._retry = bundle["retry_facts"]
        self._prior_activity = bundle.get("prior_case_activity", [])
        self._allowed_actions = bundle.get("allowed_actions", [])
        self._hist = bundle["history_12m"]  # {"available", "source", "rows":[...], "coverage_months"}
        self.tool_calls = 0
        self.history_requests: list[dict] = []
        self.evidence_returned: list[dict] = []

    def call(self, name: str, args: dict) -> str:
        self.tool_calls += 1
        if self.tool_calls > TOOL_CALL_BUDGET:
            return json.dumps({"error": "tool_call_budget_exhausted"})
        if name == "get_payment_retry_facts":
            return self._facts()
        if name == "get_recovery_actions":
            return self._recovery_actions()
        if name == "get_payment_history":
            return self._history(args if isinstance(args, dict) else {})
        return json.dumps({"error": "unknown_tool"})

    def _mark(self, tool: str, source: str, coverage: str) -> None:
        self.evidence_returned.append({"tool": tool, "source": source, "coverage": coverage})

    def _facts(self) -> str:
        out = dict(self._retry)
        out.setdefault("source", "SIMULATED_PROVIDER")
        out.setdefault("coverage", "current provider state")
        self._mark("get_payment_retry_facts", out["source"], out["coverage"])
        return json.dumps(out)

    def _recovery_actions(self) -> str:
        # ACTUAL prior actions / policy decisions / outcomes for THIS case,
        # plus a SEPARATELY labelled catalog of only-policy-supported actions.
        self._mark("get_recovery_actions", "ENGINE_AUDIT_PROJECTION", "this case, chronological")
        return json.dumps({
            "prior_case_activity": {
                "source": "ENGINE_AUDIT_PROJECTION",
                "coverage": "this case, chronological (bounded)",
                "events": self._prior_activity,
            },
            "allowed_actions_catalog": {
                "source": "DETERMINISTIC_POLICY",
                "note": "only actions deterministic policy can authorize+execute; "
                        "each still faces final policy validation; confidence never "
                        "grants permission",
                "actions": self._allowed_actions,
            },
        })

    def _history(self, args: dict) -> str:
        reason = args.get("reason")
        if not isinstance(reason, str) or not (8 <= len(reason.strip()) <= 200):
            return json.dumps({"error": "reason_required",
                               "note": "give a short (8-200 char) explanation of the "
                                       "uncertainty this 12-month lookup could resolve"})
        if self.history_requests:
            return json.dumps({"error": "single_expansion_only",
                               "note": "the twelve-month history was already returned; "
                                       "no second expansion (including during repair)"})
        self.history_requests.append({"months": 12, "reason": reason.strip()})
        avail = bool(self._hist.get("available"))
        rows = list(self._hist.get("rows", []))
        actual_months = int(self._hist.get("coverage_months", len(rows)))
        if not avail or not rows:
            self._mark("get_payment_history", self._hist.get("source", "SYNTHETIC_MERCHANT_RECORDS"),
                       "requested 12m / UNAVAILABLE")
            return json.dumps({
                "available": False, "requested_months": 12, "actual_coverage_months": 0,
                "source": self._hist.get("source", "SYNTHETIC_MERCHANT_RECORDS"),
                "note": "no merchant-held records for this customer/window; not invented",
            })
        partial = actual_months < 12
        self._mark("get_payment_history", self._hist["source"],
                   f"{actual_months} months{' (PARTIAL)' if partial else ''} (synthetic)")
        return json.dumps({
            "available": True, "source": self._hist["source"], "label": "SYNTHETIC",
            "requested_months": 12, "actual_coverage_months": actual_months,
            "partial": partial, "records": rows,
            "note": "synthetic merchant-held records (due/paid dates, outcomes) for the "
                    "same demo customer; does NOT override current provider facts or consent",
        })


def _parse_strict_json_object(text: str):
    """The final assistant message, stripped, MUST be exactly one JSON object.

    No scanning for a ``{...}`` substring inside prose - a valid-looking blob
    embedded in an otherwise invalid response is rejected, per contract.
    """
    s = (text or "").strip()
    if not s or s[0] != "{" or s[-1] != "}":
        return None, "not_json"
    try:
        obj = json.loads(s)
    except ValueError:
        return None, "not_json"
    return (obj, "ok") if isinstance(obj, dict) else (None, "not_object")


def _validate(obj, approved_messages: set):
    """Strict structural validation inside the one-repair boundary. The engine's
    ``_validate_proposal`` remains the FINAL authority. No silent coercion."""
    if not isinstance(obj, dict):
        return None, "not_object"
    if set(obj) != set(REQUIRED_KEYS):
        return None, "keys_mismatch"
    if obj["action"] not in _ALL_ACTIONS:
        return None, "unknown_action"
    if obj["action"] not in _SUPPORTED_ACTIONS:
        return None, "unsupported_action"
    conf = obj["confidence"]
    if isinstance(conf, bool) or not isinstance(conf, (int, float)):
        return None, "confidence_type"
    if not (0.0 <= float(conf) <= 1.0):
        return None, "confidence_range"
    wait = obj["proposed_wait_hours"]
    if isinstance(wait, bool) or not isinstance(wait, int):
        return None, "wait_type"
    if obj["action"] == "WAIT_FOR_PROVIDER_RETRY" and wait < 1:
        return None, "wait_nonpositive"
    if wait < 0:
        return None, "wait_nonpositive"
    for k in ("diagnosis", "rationale"):
        if not isinstance(obj[k], str) or not obj[k].strip():
            return None, "text_field"
    mi = obj["message_intent"]
    if mi is not None and not isinstance(mi, str):
        return None, "message_type"
    if mi is not None and mi not in approved_messages:
        return None, "message_not_approved"
    return obj, "valid"


def _system_prompt(skill_text: str, ctx: dict, approved_messages: list) -> str:
    return (
        skill_text.strip()
        + "\n\n--- THIS CASE (initial context; deliberately limited) ---\n"
        + json.dumps(ctx, indent=2)
        + "\n\nTools you may call (only when the answer would change your proposal):\n"
          "  get_payment_retry_facts()  - authoritative current provider retry state\n"
          "  get_recovery_actions()     - this case's prior activity + the actions "
          "policy can actually execute\n"
          "  get_payment_history(reason) - ONE optional expansion straight to twelve "
          "months of synthetic history; 'reason' explains the uncertainty it resolves; "
          "callable at most once (including during any correction).\n"
          "Deciding from the initial context with no lookups is fine.\n\n"
          "Approved message_intent values (use one VERBATIM or null - no other text):\n"
        + "\n".join(f"  - {json.dumps(m)}" for m in approved_messages)
        + "\n\nReturn EXACTLY one JSON object, no prose, keys exactly: "
        + ", ".join(REQUIRED_KEYS)
        + ".\n- action must be one of: " + ", ".join(sorted(_SUPPORTED_ACTIONS))
        + " (return ESCALATE when evidence is inadequate or no supported action "
          "applies - do NOT guess).\n"
          "- proposed_wait_hours: integer; >= 1 for WAIT_FOR_PROVIDER_RETRY, else 0.\n"
          "- confidence: your own UNCALIBRATED estimate in [0,1], justified by "
          "completeness, freshness/reliability, consistency and relevance of the "
          "evidence - not record count. It never grants a permission.\n"
          "- rationale: your reasoning, including any doubt that remains."
    )


def main() -> int:
    started = time.monotonic()
    job = json.loads(sys.stdin.read())
    revision = os.environ.get("HERMES_EXPECTED_REVISION", "")
    approved_messages = list(job.get("approved_messages", []))
    approved_set = set(approved_messages)

    audit = {
        "runtime_revision": revision,
        "provider": None, "provider_model": None,
        "duration_ms": None,
        "model_iterations_used": None, "model_iterations_budget": MODEL_ITERATION_BUDGET,
        "tool_calls_used": 0, "tool_calls_budget": TOOL_CALL_BUDGET,
        "tokens": None,
        "evidence_requests": [], "evidence_returned": [],
        "model_confidence": None, "confidence_band": None,
        "confidence_basis": "uncalibrated model self-estimate; not a probability of "
                            "correctness; never grants a permission",
        "decision_action": None,
        "repair_used": False,
        "validation_result": "not_reached",
        "failure_category": None, "failure_stage": None,
    }

    def _fail(category: str, stage: str, code: int = 1) -> int:
        audit["failure_category"] = category
        audit["failure_stage"] = stage
        if audit["duration_ms"] is None:
            audit["duration_ms"] = round((time.monotonic() - started) * 1000)
        _emit({"ok": False, "audit": audit})
        return code

    # Hard self-deadline: daemon so a clean exit never waits on it; cancelled in
    # `finally` on every normal path. The parent's subprocess timeout + reap is
    # the real deadline; this only covers a wedged run on a slow SIGTERM host.
    watchdog = threading.Timer(
        max(5.0, float(job.get("deadline_s", 90)) - 4.0), lambda: os._exit(9)
    )
    watchdog.daemon = True
    watchdog.start()
    try:
        return _run(job, audit, approved_messages, approved_set, started, _fail)
    finally:
        watchdog.cancel()


def _run(job, audit, approved_messages, approved_set, started, _fail) -> int:
    ev = _Evidence(job["evidence_bundle"])
    calls: list[dict] = []

    def _tool_start(tool_call_id, name, args, *a, **k):
        calls.append({"tool": name, "args": args if isinstance(args, dict) else {}})

    from tools.registry import registry
    from toolsets import create_custom_toolset

    def _schema(name, desc, props=None):
        props = props or {}
        return {"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "properties": props,
                           "required": list(props), "additionalProperties": False}}}

    def _h(tool):
        def _handler(args=None, **_ctx):
            return ev.call(tool, args if isinstance(args, dict) else {})
        return _handler

    registry.register("get_payment_retry_facts", "revenue_recovery",
                      _schema("get_payment_retry_facts",
                              "Authoritative current provider retry eligibility + evidence "
                              "for THIS case. No arguments."),
                      _h("get_payment_retry_facts"), override=True)
    registry.register("get_recovery_actions", "revenue_recovery",
                      _schema("get_recovery_actions",
                              "THIS case's actual prior actions, policy decisions and "
                              "outcomes, plus the separately-labelled catalog of actions "
                              "deterministic policy can execute. No arguments."),
                      _h("get_recovery_actions"), override=True)
    registry.register("get_payment_history", "revenue_recovery",
                      _schema("get_payment_history",
                              "ONE optional expansion straight to twelve months of "
                              "synthetic merchant history for the same customer. 'reason' "
                              "is a short note on the uncertainty it could resolve. "
                              "Callable at most once per decision (including any repair).",
                              {"reason": {"type": "string", "minLength": 8, "maxLength": 200}}),
                      _h("get_payment_history"), override=True)
    create_custom_toolset("revenue_recovery", "Case-scoped Case 3 evidence tools",
                          tools=list(TOOL_NAMES))

    from run_agent import AIAgent

    ctx = job["evidence_bundle"]["initial_context"]
    sys_prompt = _system_prompt(job["skill_text"], ctx, approved_messages)

    if job["mode"] == "mock":
        provider, model = "openai-compat", job["mock"]["model"]
        base_kw = dict(api_key="offline-harness", base_url=job["mock"]["base_url"],
                       provider=provider, model=model)
    else:
        provider, model = "gemini", job["gemini"]["model"]
        base_kw = dict(provider=provider, model=model)
    audit["provider"], audit["provider_model"] = provider, model

    def _make_agent(max_iter: int):
        return AIAgent(
            max_iterations=max_iter, enabled_toolsets=["revenue_recovery"],
            quiet_mode=True, skip_context_files=True, skip_memory=True,
            skip_background_review=True, save_trajectories=False, platform="cli",
            tool_start_callback=_tool_start, ephemeral_system_prompt=sys_prompt,
            **base_kw,
        )

    agent = _make_agent(MODEL_ITERATION_BUDGET)
    exposed = sorted(getattr(agent, "valid_tool_names", set()) or set())
    if exposed != sorted(TOOL_NAMES):
        return _fail(_FAIL_TOOL_EXPOSURE, "agent_init")

    def _iterations(result, msgs) -> int:
        """TOTAL model iterations so far. ``msgs`` after the repair call is the
        FULL conversation (initial + repair), so this stays absolute, never
        double-counts, and honours the runtime's own counter when present."""
        for k in ("iterations", "iteration_count", "num_iterations"):
            v = result.get(k)
            if isinstance(v, int) and v > 0:
                return v
        return sum(1 for m in msgs if isinstance(m, dict) and m.get("role") == "assistant") or 1

    def _final_text(msgs) -> str:
        return next((m.get("content") for m in reversed(msgs)
                     if isinstance(m, dict) and m.get("role") == "assistant" and m.get("content")),
                    "") or ""

    # -- initial reasoning ------------------------------------------------
    result = agent.run_conversation(
        "Decide the single next Case 3 recovery step now. Return only the JSON object.",
        conversation_history=[], task_id="case3",
    )
    msgs = result.get("messages", []) or []
    used = _iterations(result, msgs)
    obj, why = _parse_strict_json_object(_final_text(msgs))
    proposal, verdict = (None, why) if obj is None else _validate(obj, approved_set)

    # -- single repair, sharing the SAME iteration + tool budgets --------
    if proposal is None:
        audit["repair_used"] = True
        remaining = MODEL_ITERATION_BUDGET - used
        if remaining < 1:
            audit["validation_result"] = f"invalid:{verdict}"
            audit["model_iterations_used"] = used
            _finish_audit(audit, ev, calls, started, result, msgs, _iterations)
            return _fail(_FAIL_ITER_BUDGET, "repair")
        repair_agent = _make_agent(remaining)
        result = repair_agent.run_conversation(
            "Your previous reply was not a single valid JSON object matching the "
            f"contract ({verdict}). Reply again with ONLY that JSON object, no prose, "
            "keys exactly " + ", ".join(REQUIRED_KEYS) + ".",
            conversation_history=msgs, task_id="case3",
        )
        msgs = result.get("messages", []) or []
        used = max(used + 1, _iterations(result, msgs))  # absolute total, never below prior
        obj, why = _parse_strict_json_object(_final_text(msgs))
        proposal, verdict = (None, why) if obj is None else _validate(obj, approved_set)
        audit["validation_result"] = "repaired" if proposal is not None else f"invalid:{verdict}"
    else:
        audit["validation_result"] = "valid"

    audit["model_iterations_used"] = used
    _finish_audit(audit, ev, calls, started, result, msgs, _iterations)

    if proposal is None:
        return _fail(_FAIL_SCHEMA, "repair" if audit["repair_used"] else "initial")

    audit["model_confidence"] = proposal["confidence"]
    audit["confidence_band"] = _band(proposal["confidence"])
    audit["decision_action"] = proposal["action"]
    _emit({"ok": True, "proposal": proposal, "audit": audit})
    return 0


def _finish_audit(audit, ev, calls, started, result, msgs, _iterations) -> None:
    usage = result.get("usage") or result.get("token_usage")
    if isinstance(usage, dict):
        audit["tokens"] = {k: usage[k] for k in
                           ("prompt_tokens", "completion_tokens", "total_tokens")
                           if k in usage} or None
    audit["tool_calls_used"] = ev.tool_calls
    audit["evidence_requests"] = [
        {"tool": c["tool"], **({"reason": (c["args"].get("reason") or "")[:200]}
                               if c["tool"] == "get_payment_history" else {})}
        for c in calls
    ][:8]
    audit["evidence_returned"] = ev.evidence_returned[:8]
    audit["duration_ms"] = round((time.monotonic() - started) * 1000)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:  # never a raw message; never hang the parent
        _emit({"ok": False, "audit": {"failure_category": _FAIL_CHILD_EXCEPTION,
                                      "failure_stage": "unhandled"}})
        sys.exit(1)
