"""Runs INSIDE the installed Nous Hermes venv, as an isolated subprocess.

Reads one JSON job on stdin, drives a fresh ``run_agent.AIAgent`` for exactly
one Case 3 decision with three case-scoped evidence tools, and prints one line:

    HERMES_CHILD_RESULT {json}

This file must not import anything from the ``hermes`` project package - only
the standard library and the Hermes runtime (``run_agent`` / ``tools`` /
``toolsets``), which is only importable under the Hermes interpreter.

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
import re
import sys
import threading
import time

RESULT_SENTINEL = "HERMES_CHILD_RESULT "
TOOL_NAMES = ("get_payment_retry_facts", "get_payment_history", "get_recovery_actions")
REQUIRED_KEYS = ("action", "diagnosis", "rationale", "confidence",
                 "proposed_wait_hours", "message_intent")
_VALID_ACTIONS = {
    "WAIT_FOR_PROVIDER_RETRY", "SEND_REMINDER", "REQUEST_PAYMENT_METHOD_UPDATE",
    "CREATE_RECOVERY_LINK", "RECOMMEND_STRUCTURAL_CHANGE", "TAKE_NO_ACTION",
    "STOP", "ESCALATE",
}


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
    takes only 6 or 12 months, needs a short uncertainty reason, allows at most
    two expanded-history requests, and rejects duplicate / no-progress repeats.
    """

    def __init__(self, bundle: dict):
        self._retry = bundle["retry_facts"]
        self._actions = bundle["recovery_actions"]
        self._hist12 = bundle["history_12m"]  # {"available": bool, "source", "rows":[...12 oldest->newest]}
        self.tool_calls = 0
        self.history_requests: list[dict] = []
        self.evidence_returned: list[dict] = []

    # -- dispatch guard ------------------------------------------------------
    def call(self, name: str, args: dict) -> str:
        self.tool_calls += 1
        if self.tool_calls > 6:
            return json.dumps({"error": "tool call budget (6) exhausted"})
        if name == "get_payment_retry_facts":
            return self._facts()
        if name == "get_recovery_actions":
            return self._recovery_actions()
        if name == "get_payment_history":
            return self._history(args if isinstance(args, dict) else {})
        return json.dumps({"error": f"unknown tool {name!r}"})

    def _mark(self, tool: str, source: str, coverage: str) -> None:
        self.evidence_returned.append({"tool": tool, "source": source, "coverage": coverage})

    def _facts(self) -> str:
        out = dict(self._retry)
        out.setdefault("source", "SIMULATED_PROVIDER")
        out.setdefault("coverage", "current provider state")
        self._mark("get_payment_retry_facts", out["source"], out["coverage"])
        return json.dumps(out)

    def _recovery_actions(self) -> str:
        out = dict(self._actions)
        out.setdefault("source", "DETERMINISTIC_POLICY_CATALOG")
        out.setdefault("coverage", "current case")
        self._mark("get_recovery_actions", out["source"], out["coverage"])
        return json.dumps(out)

    def _history(self, args: dict) -> str:
        months = args.get("months")
        reason = args.get("reason")
        if months not in (6, 12):
            return json.dumps({"error": "months must be exactly 6 or 12"})
        if not isinstance(reason, str) or not (3 <= len(reason.strip()) <= 200):
            return json.dumps({"error": "reason must be a short (3-200 char) explanation "
                                        "of the uncertainty being investigated"})
        reason = reason.strip()
        if len(self.history_requests) >= 2:
            return json.dumps({"error": "at most two expanded-history requests per decision"})
        for prev in self.history_requests:
            if prev["months"] == months:
                return json.dumps({"error": f"already returned {months}-month history; "
                                            "no-progress / duplicate request rejected"})
        self.history_requests.append({"months": months, "reason": reason})
        if not self._hist12.get("available", False):
            self._mark("get_payment_history", self._hist12.get("source", "SYNTHETIC_MERCHANT_RECORDS"),
                       f"{months}m requested / UNAVAILABLE")
            return json.dumps({"available": False, "months_requested": months,
                               "source": self._hist12.get("source", "SYNTHETIC_MERCHANT_RECORDS"),
                               "note": "merchant holds no records for this window; not invented"})
        rows = list(self._hist12.get("rows", []))
        subset = rows[-months:] if months <= len(rows) else rows
        self._mark("get_payment_history", self._hist12["source"], f"{months} months (synthetic)")
        return json.dumps({
            "available": True, "source": self._hist12["source"], "label": "SYNTHETIC",
            "coverage_months": months, "records": subset,
            "note": "synthetic merchant-held records (due/paid dates, outcomes) for the "
                    "same demo customer; does not override current provider facts or consent",
        })


def _extract_json_object(text: str):
    """Return the first top-level JSON object in ``text`` or None."""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except ValueError:
        return None


def _validate(obj) -> tuple[dict | None, str]:
    if not isinstance(obj, dict):
        return None, "not an object"
    if set(obj) != set(REQUIRED_KEYS):
        return None, f"keys must be exactly {sorted(REQUIRED_KEYS)}"
    if obj["action"] not in _VALID_ACTIONS:
        return None, f"action not recognised: {obj['action']!r}"
    if not isinstance(obj["confidence"], (int, float)) or not (0.0 <= obj["confidence"] <= 1.0):
        return None, "confidence must be a number in [0,1]"
    if not isinstance(obj["proposed_wait_hours"], int) or isinstance(obj["proposed_wait_hours"], bool):
        return None, "proposed_wait_hours must be an integer"
    if obj["proposed_wait_hours"] < 0:
        return None, "proposed_wait_hours must be >= 0"
    for k in ("diagnosis", "rationale"):
        if not isinstance(obj[k], str) or not obj[k].strip():
            return None, f"{k} must be a non-empty string"
    if obj["message_intent"] is not None and not isinstance(obj["message_intent"], str):
        return None, "message_intent must be a string or null"
    return obj, "valid"


def _system_prompt(skill_text: str, ctx: dict) -> str:
    return (
        skill_text.strip()
        + "\n\n--- THIS CASE (initial context; limited on purpose) ---\n"
        + json.dumps(ctx, indent=2)
        + "\n\nYou may call get_payment_retry_facts, get_recovery_actions, and "
          "(at most twice) get_payment_history to gather more evidence before "
          "deciding. Current provider retry facts and consent always win over "
          "history. When evidence is inadequate, return the STOP or ESCALATE "
          "action rather than guessing.\n"
          "Reply with ONE JSON object and nothing else, with EXACTLY these keys: "
        + ", ".join(REQUIRED_KEYS)
        + ". 'confidence' is your own uncalibrated estimate in [0,1]; it never "
          "grants permission. Put any remaining doubt in 'rationale'."
    )


def main() -> int:
    started = time.monotonic()
    job = json.loads(sys.stdin.read())
    revision = os.environ.get("HERMES_EXPECTED_REVISION", "")
    audit: dict = {
        "runtime_revision": revision,
        "model": None, "provider": None,
        "duration_ms": None, "iterations_used": None, "tool_calls_used": 0,
        "tokens": None, "evidence_requests": [], "evidence_returned": [],
        "model_confidence": None, "confidence_band": None,
        "unresolved_uncertainty": None, "stop_reason": "error",
        "repair_used": False, "validation_result": "not_reached",
    }

    # hard self-deadline in case the parent's SIGTERM is slow on Windows
    threading.Timer(
        max(5.0, float(job.get("deadline_s", 90)) - 4.0),
        lambda: os._exit(9),
    ).start()

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
        # Hermes calls handlers as handler(parsed_args_dict, task_id=..., **ctx);
        # bind only the args dict, ignore runtime kwargs.
        def _handler(args=None, **_ctx):
            return ev.call(tool, args if isinstance(args, dict) else {})
        return _handler

    registry.register("get_payment_retry_facts", "revenue_recovery",
                      _schema("get_payment_retry_facts",
                              "Current provider retry eligibility and evidence for THIS case. No arguments."),
                      _h("get_payment_retry_facts"), override=True)
    registry.register("get_recovery_actions", "revenue_recovery",
                      _schema("get_recovery_actions",
                              "The deterministic catalog of recovery actions permitted for THIS case. No arguments."),
                      _h("get_recovery_actions"), override=True)
    registry.register("get_payment_history", "revenue_recovery",
                      _schema("get_payment_history",
                              "Expanded synthetic merchant payment history for the same customer. "
                              "months must be 6 or 12; reason is a short note on the uncertainty "
                              "you are investigating. At most two calls; no duplicate windows.",
                              {"months": {"type": "integer", "enum": [6, 12]},
                               "reason": {"type": "string", "maxLength": 200}}),
                      _h("get_payment_history"), override=True)
    create_custom_toolset("revenue_recovery", "Case-scoped Case 3 evidence tools",
                          tools=list(TOOL_NAMES))

    from run_agent import AIAgent

    ctx = job["evidence_bundle"]["initial_context"]
    sys_prompt = _system_prompt(job["skill_text"], ctx)

    if job["mode"] == "mock":
        provider, model = "openai-compat", job["mock"]["model"]
        kw = dict(api_key="offline-harness", base_url=job["mock"]["base_url"],
                  provider=provider, model=model)
    else:  # native Gemini
        provider, model = "gemini", job["gemini"]["model"]
        kw = dict(provider=provider, model=model)  # GEMINI_API_KEY read from env by the runtime
    audit["provider"], audit["model"] = provider, model

    agent = AIAgent(
        max_iterations=int(job.get("max_iterations", 8)),
        enabled_toolsets=["revenue_recovery"],
        quiet_mode=True, skip_context_files=True, skip_memory=True,
        skip_background_review=True, save_trajectories=False, platform="cli",
        tool_start_callback=_tool_start,
        ephemeral_system_prompt=sys_prompt,
        **kw,
    )
    exposed = sorted(getattr(agent, "valid_tool_names", set()) or set())
    if exposed != sorted(TOOL_NAMES):
        audit["stop_reason"] = "tool_exposure_mismatch"
        audit["duration_ms"] = round((time.monotonic() - started) * 1000)
        _emit({"ok": False, "error": f"exposed tools {exposed} != {sorted(TOOL_NAMES)}", "audit": audit})
        return 1

    user = "Decide the single next Case 3 recovery step now. Return only the JSON object."

    def _run(msg, history):
        return agent.run_conversation(msg, conversation_history=history or [], task_id="case3")

    result = _run(user, [])
    msgs = result.get("messages", []) or []
    final = next((m.get("content") for m in reversed(msgs)
                  if isinstance(m, dict) and m.get("role") == "assistant" and m.get("content")), "") or ""
    obj = _extract_json_object(final)
    proposal, verdict = _validate(obj)

    if proposal is None:
        audit["repair_used"] = True
        repair_user = ("Your previous reply was not a single valid JSON object with exactly "
                       f"the keys {list(REQUIRED_KEYS)} ({verdict}). Reply again with ONLY "
                       "that JSON object, no prose.")
        result = _run(repair_user, msgs)
        msgs = result.get("messages", []) or []
        final = next((m.get("content") for m in reversed(msgs)
                      if isinstance(m, dict) and m.get("role") == "assistant" and m.get("content")), "") or ""
        obj = _extract_json_object(final)
        proposal, verdict = _validate(obj)
        audit["validation_result"] = "repaired" if proposal is not None else f"invalid:{verdict}"
    else:
        audit["validation_result"] = "valid"

    # usage / iterations if the runtime surfaced them
    usage = result.get("usage") or result.get("token_usage")
    if isinstance(usage, dict):
        audit["tokens"] = {k: usage.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens")
                           if k in usage} or usage
    audit["iterations_used"] = result.get("iterations") or result.get("iteration_count")
    audit["tool_calls_used"] = ev.tool_calls
    audit["evidence_requests"] = [
        {"tool": c["tool"], **({"months": c["args"].get("months"),
                                "reason": (c["args"].get("reason") or "")[:200]}
                               if c["tool"] == "get_payment_history" else {})}
        for c in calls
    ]
    audit["evidence_returned"] = ev.evidence_returned
    audit["duration_ms"] = round((time.monotonic() - started) * 1000)

    if proposal is None:
        audit["stop_reason"] = "schema_repair_failed"
        _emit({"ok": False, "error": f"no valid proposal ({verdict})", "audit": audit})
        return 1

    audit["model_confidence"] = proposal["confidence"]
    audit["confidence_band"] = _band(proposal["confidence"])
    audit["unresolved_uncertainty"] = (proposal.get("rationale") or "").strip()[:400] or "none stated"
    audit["stop_reason"] = (
        "iteration_limit" if result.get("partial") else
        f"{proposal['action'].lower()}_proposed"
    )
    _emit({"ok": True, "proposal": proposal, "audit": audit})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # last-resort: never hang the parent
        _emit({"ok": False, "error": f"{type(exc).__name__}: {exc}",
               "audit": {"stop_reason": "child_exception"}})
        sys.exit(1)
