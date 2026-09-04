"""``HermesAgentStrategist`` - the ``Strategist`` seam backed by the *actual*
installed Nous Hermes runtime, driven in an isolated subprocess.

One ``propose`` call == one throwaway Hermes ``AIAgent`` decision:

  parent (this file, project venv)
    -> build a bounded, immutable evidence bundle from the case snapshot
    -> spawn ``hermes.hermes_agent.child_main`` with the *Hermes* interpreter,
       in a project-local gitignored HERMES_HOME, no DB / Razorpay / unrelated
       creds, tool_search bridge off, three case-scoped tools only
    -> enforce a single 90s deadline, reap a timed-out child
    -> parse the child's one-line JSON result
    -> map to ``StrategyProposal`` (engine still validates + authorizes) or
       raise ``InvalidProposal`` / ``TimeoutError`` (engine's bounded-failure path)

There is **no fallback to direct Gemini**: if the runtime is missing, the wrong
revision, or the child fails, ``propose`` raises and the deterministic engine
records a strategist failure.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from .hermes_agent import (
    CHILD_MAIN,
    EXPECTED_HERMES_REVISION,
    MAX_MODEL_ITERATIONS,
    RESULT_SENTINEL,
    SUBPROCESS_DEADLINE_S,
    TOOL_NAMES,
)
from .message_templates import APPROVED_MESSAGE_INTENT_LIST
from .types import InvalidProposal, ProposalAction, StrategyProposal, StrategySnapshot

# Bumped: the child now receives the approved message templates explicitly and
# validates message choice + strict field types inside the one-repair boundary;
# get_payment_history is a single 12-month expansion; get_recovery_actions
# returns the real per-case audit projection.
PROMPT_VERSION = "hermes-agent/2026-09-05.1"

# Fixed, allowlisted parent-side failure categories (no raw strings ever).
_PARENT_FAIL_TIMEOUT = "subprocess_deadline"
_PARENT_FAIL_NO_RESULT = "no_result_line"
_PARENT_FAIL_ABNORMAL_EXIT = "abnormal_child_exit"
_PARENT_FAIL_CHILD = "child_reported_failure"
_PARENT_FAIL_PROPOSAL_SHAPE = "proposal_shape"

# Only the actions deterministic policy can authorize + execute today. This is
# what the child advertises as the "allowed actions" catalog - STOP is omitted.
_POLICY_SUPPORTED_ACTIONS: tuple[str, ...] = (
    "WAIT_FOR_PROVIDER_RETRY (only while provider_retry_eligible is true and wait "
    "budget remains; integer proposed_wait_hours >= 1)",
    "CREATE_RECOVERY_LINK (only after a recorded failed retry outcome; at most one; "
    "optional message_intent must be an approved template)",
    "SEND_REMINDER (merchant-owned communication + consent + reachable channel; "
    "approved template only)",
    "ESCALATE (the safe path when evidence is inadequate or no other action is "
    "authorized; deterministic terminal transition to 'escalated'/unrecovered)",
)

_DEFAULT_CHECKOUT = Path(os.environ.get(
    "HERMES_AGENT_CHECKOUT",
    r"C:\Users\dwish\AppData\Local\hermes\hermes-agent",
))
_DEFAULT_PYTHON = Path(os.environ.get(
    "HERMES_AGENT_PYTHON",
    str(_DEFAULT_CHECKOUT / ".venv" / "Scripts" / "python.exe"),
))
# Project-local, gitignored runtime home (state isolation, NOT an OS sandbox).
_DEFAULT_HOME = Path(os.environ.get(
    "HERMES_AGENT_HOME",
    str(Path(__file__).resolve().parents[2] / ".hermes_home" / "isolated"),
))
_SKILL_PATH = Path(__file__).resolve().parents[2] / "config" / "hermes_agent" / "SKILL.md"


class HermesRuntimeUnavailable(RuntimeError):
    """The isolated Hermes runtime cannot be used (missing / wrong revision)."""


@dataclass
class HermesRunMeta:
    """Bounded audit metadata for one real-Hermes decision. Consumed by
    ``RecoveryEngine._note_model_run`` (model / prompt_version / latency_ms /
    repair_used / validation_result / usage) plus ``extra`` = the sanitised,
    allowlisted child audit (runtime revision, provider/model, timing, shared
    iteration + tool budgets, evidence requests + reasons, returned
    source/coverage, uncalibrated confidence band + basis, decision action,
    failure category/stage, child exit code). No raw messages or transcripts."""

    model: str
    prompt_version: str = PROMPT_VERSION
    latency_ms: float = 0.0
    repair_used: bool = False
    validation_result: str = "not_reached"
    usage: dict[str, Any] | None = None
    cost_usd: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _verify_revision(checkout: Path) -> str:
    try:
        head = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise HermesRuntimeUnavailable(f"cannot read Hermes revision: {type(exc).__name__}") from None
    if head != EXPECTED_HERMES_REVISION:
        raise HermesRuntimeUnavailable(
            f"installed Hermes revision {head[:12] or '?'} != proven "
            f"{EXPECTED_HERMES_REVISION[:12]}; refusing to launch (do not auto-upgrade)"
        )
    return head


# --- coherent synthetic 12-month history for a KNOWN demo customer ----------
# Plausible merchant-held records only: due date, paid date, and an outcome
# label that is DERIVED from the day delta so date and label never disagree.
# Supplied ONLY for cases with a trusted DEMO_CASE_PROVENANCE record; an
# unknown case inherits no fictional customer records.
_HISTORY_DUE_PAID: tuple[tuple[str, str | None], ...] = (
    ("2025-10-01", "2025-10-01"),
    ("2025-11-01", "2025-11-01"),
    ("2025-12-01", "2025-12-03"),   # 2 days late
    ("2026-01-01", "2026-01-01"),
    ("2026-02-01", "2026-02-01"),
    ("2026-03-01", "2026-03-02"),   # 1 day late
    ("2026-04-01", "2026-04-01"),
    ("2026-05-01", "2026-05-01"),
    ("2026-06-01", "2026-06-01"),
    ("2026-07-01", "2026-07-01"),
    ("2026-08-01", "2026-08-01"),
    ("2026-09-01", None),           # the current failure
)


def _history_row(due: str, paid: str | None) -> dict:
    if paid is None:
        return {"due": due, "paid": None, "outcome": "failed_insufficient_funds"}
    delta = (date.fromisoformat(paid) - date.fromisoformat(due)).days
    if delta <= 0:
        label = "paid_on_time"
    elif delta == 1:
        label = "paid_1_day_late"
    else:
        label = f"paid_{delta}_days_late"
    return {"due": due, "paid": paid, "outcome": label}


_SYNTHETIC_HISTORY_12M: tuple[dict, ...] = tuple(_history_row(d, p) for d, p in _HISTORY_DUE_PAID)


def _evidence_bundle(
    snap: StrategySnapshot, *, history_available: bool = True,
    history_months_available: int = 12,
) -> dict:
    """Immutable bundle backing the three child tools. No amounts / URLs / ids
    the model could echo as customer copy; provider facts and consent are
    authoritative.

    Synthetic customer history is included ONLY when the case is a trusted demo
    case (``snap.is_demo_case``). ``history_months_available`` < 12 models a
    partial merchant record set - the tool then reports its ACTUAL coverage.
    """
    is_demo = bool(getattr(snap, "is_demo_case", False))
    give_history = is_demo and history_available and history_months_available > 0
    months = max(0, min(12, int(history_months_available))) if give_history else 0
    rows_12 = list(_SYNTHETIC_HISTORY_12M)[-months:] if months else []

    initial_context = {
        "failure_reason": snap.failure_reason,
        "state": snap.state,
        "retry_outcome_recorded": snap.retry_outcome_recorded,
        "communication_owner": snap.communication_owner,
        "consent": snap.consent,
        "reachable_channel": snap.reachable_channel,
        "policy_limits": {
            "messages_remaining": snap.messages_remaining,
            "links_remaining": snap.links_remaining,
            "actions_remaining": snap.actions_remaining,
            "wait_hours_remaining": snap.wait_hours_remaining,
        },
        # Three months of monthly payment history in the initial prompt.
        "payment_history_3m": (
            {"source": "SYNTHETIC_MERCHANT_RECORDS", "label": "SYNTHETIC",
             "coverage_months": min(3, len(rows_12)), "records": rows_12[-3:]}
            if give_history else
            {"source": "SYNTHETIC_MERCHANT_RECORDS", "available": False,
             "note": "no synthetic customer records for this case"}
        ),
    }
    return {
        "initial_context": initial_context,
        "retry_facts": {
            "source": "SIMULATED_PROVIDER", "coverage": "current provider state",
            "provider_retry_eligible": snap.provider_retry_eligible,
            "provider_retry_evidence": snap.provider_retry_evidence,
            "retry_outcome_recorded": snap.retry_outcome_recorded,
        },
        # ACTUAL prior activity for this case (redacted audit projection built by
        # the engine) - surfaced only when get_recovery_actions is called.
        "prior_case_activity": [dict(e) for e in getattr(snap, "case_history", ()) or ()][-25:],
        # Separately labelled: only actions deterministic policy can execute.
        "allowed_actions": list(_POLICY_SUPPORTED_ACTIONS),
        "history_12m": {
            "available": bool(give_history and rows_12),
            "source": "SYNTHETIC_MERCHANT_RECORDS",
            "coverage_months": len(rows_12),
            "rows": rows_12,
        },
    }


_ACTION_MAP = {a.value: a for a in ProposalAction}


class HermesAgentStrategist:
    """Strategist backed by the real isolated Hermes runtime."""

    def __init__(
        self,
        *,
        checkout: Path | str = _DEFAULT_CHECKOUT,
        python: Path | str = _DEFAULT_PYTHON,
        home: Path | str = _DEFAULT_HOME,
        skill_path: Path | str = _SKILL_PATH,
        mock_base_url: str | None = None,   # offline harness: OpenAI-compat stub
        mock_model: str = "stub-model",
        gemini_model: str = "gemini-3.7-flash",
        deadline_s: float = SUBPROCESS_DEADLINE_S,
        verify_revision: bool = True,
        history_available: bool = True,   # False -> get_payment_history returns "unavailable"
        history_months_available: int = 12,  # < 12 -> tool reports actual partial coverage
    ) -> None:
        self._checkout = Path(checkout)
        self._python = Path(python)
        self._home = Path(home)
        self._skill_path = Path(skill_path)
        self._mock_base_url = mock_base_url
        self._mock_model = mock_model
        self._gemini_model = gemini_model
        self._deadline_s = float(deadline_s)
        self._history_available = bool(history_available)
        self._history_months_available = int(history_months_available)
        self._one_in_flight = threading.BoundedSemaphore(1)
        self.last_run_meta: HermesRunMeta | None = None

        if not self._python.exists():
            raise HermesRuntimeUnavailable(f"Hermes interpreter not found at {self._python}")
        if not (self._checkout / "run_agent.py").exists():
            raise HermesRuntimeUnavailable(f"Hermes checkout not found at {self._checkout}")
        if not self._skill_path.exists():
            raise HermesRuntimeUnavailable(f"project skill file missing: {self._skill_path}")
        self._revision = _verify_revision(self._checkout) if verify_revision else "unverified"
        self._prepare_home()

    # -- isolation setup --------------------------------------------------
    def _prepare_home(self) -> None:
        self._home.mkdir(parents=True, exist_ok=True)
        # tool_search bridge OFF so the three tools are exposed directly and
        # every dispatch name is asserted; nothing else is configured, so no
        # MCP servers, plugins, or skills are discoverable in this home.
        (self._home / "config.yaml").write_text(
            "tools:\n  tool_search: false\nmcp_servers: {}\nplugins:\n  enabled: []\n",
            encoding="utf-8",
        )

    def _child_env(self) -> dict[str, str]:
        """Only what the child needs. No DATABASE_URL / Razorpay / unrelated keys."""
        keep = {}
        for k in ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "PATHEXT",
                  "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "COMSPEC", "PATH",
                  "APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOMEDRIVE", "HOMEPATH"):
            if k in os.environ:
                keep[k] = os.environ[k]
        keep["HERMES_HOME"] = str(self._home)
        keep["HERMES_SKIP_UPDATE_CHECK"] = "1"
        keep["HERMES_EXPECTED_REVISION"] = self._revision
        keep["PYTHONIOENCODING"] = "utf-8"
        if self._mock_base_url is None:
            key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
            if not key:
                raise HermesRuntimeUnavailable("live Hermes needs GEMINI_API_KEY in the environment")
            keep["GEMINI_API_KEY"] = key
            keep["GOOGLE_API_KEY"] = key
        return keep

    # -- the Strategist protocol ----------------------------------------
    def propose(self, snapshot: StrategySnapshot) -> StrategyProposal:
        if not self._one_in_flight.acquire(blocking=False):
            raise TimeoutError("a Hermes agent decision is already in flight")
        try:
            return self._propose_locked(snapshot)
        finally:
            self._one_in_flight.release()

    def _propose_locked(self, snap: StrategySnapshot) -> StrategyProposal:
        job = {
            "mode": "mock" if self._mock_base_url else "gemini",
            "deadline_s": self._deadline_s,
            "max_iterations": MAX_MODEL_ITERATIONS,
            "skill_text": self._skill_path.read_text(encoding="utf-8"),
            "approved_messages": list(APPROVED_MESSAGE_INTENT_LIST),
            "evidence_bundle": _evidence_bundle(
                snap, history_available=self._history_available,
                history_months_available=self._history_months_available,
            ),
        }
        if self._mock_base_url:
            job["mock"] = {"base_url": self._mock_base_url, "model": self._mock_model}
        else:
            job["gemini"] = {"model": self._gemini_model}

        started = time.monotonic()
        meta = HermesRunMeta(model=(self._mock_model if self._mock_base_url else self._gemini_model))
        meta.extra = {"runtime_revision": self._revision}
        self.last_run_meta = meta
        try:
            proc = subprocess.run(
                [str(self._python), CHILD_MAIN],
                cwd=str(self._checkout), env=self._child_env(),
                input=json.dumps(job), capture_output=True, text=True,
                timeout=self._deadline_s,
            )
        except subprocess.TimeoutExpired:
            # subprocess.run kills + reaps the child before re-raising.
            meta.latency_ms = (time.monotonic() - started) * 1000
            meta.validation_result = "invalid:subprocess_timeout"
            meta.extra = {"runtime_revision": self._revision,
                          "failure_category": _PARENT_FAIL_TIMEOUT, "failure_stage": "subprocess"}
            raise TimeoutError("Hermes agent subprocess exceeded its hard deadline") from None

        meta.latency_ms = (time.monotonic() - started) * 1000
        rc = proc.returncode
        payload = _parse_result(proc.stdout)
        if payload is None:
            meta.validation_result = "invalid:no_result_line"
            meta.extra = {"runtime_revision": self._revision,
                          "failure_category": _PARENT_FAIL_NO_RESULT, "failure_stage": "parse",
                          "child_exit_code": rc}
            raise InvalidProposal("Hermes child produced no parseable result line")

        audit = _sanitize_audit(payload.get("audit"))
        audit["runtime_revision"] = audit.get("runtime_revision") or self._revision
        audit["child_exit_code"] = rc
        meta.extra = audit
        meta.repair_used = bool(audit.get("repair_used"))
        meta.validation_result = audit.get("validation_result", meta.validation_result)
        meta.usage = audit.get("tokens")
        meta.model = audit.get("provider_model") or meta.model

        ok = bool(payload.get("ok"))
        # Reject an unexpected exit code even when stdout claims success; the
        # child returns 0 for ok and 1 for a categorised failure - nothing else.
        if (ok and rc != 0) or (not ok and rc not in (0, 1)):
            audit["failure_category"] = _PARENT_FAIL_ABNORMAL_EXIT
            audit["failure_stage"] = "subprocess_exit"
            meta.validation_result = "invalid:abnormal_child_exit"
            raise InvalidProposal("Hermes child exited abnormally")

        if not ok:
            audit.setdefault("failure_category", _PARENT_FAIL_CHILD)
            raise InvalidProposal("Hermes decision failed (see audit failure_category)")

        return _to_proposal(payload.get("proposal"), audit)


def _parse_result(stdout: str) -> dict | None:
    for line in reversed((stdout or "").splitlines()):
        if line.startswith(RESULT_SENTINEL):
            try:
                return json.loads(line[len(RESULT_SENTINEL):])
            except ValueError:
                return None
    return None


# Only these keys are ever surfaced from a child audit dict. Anything else the
# child might emit (or a malformed payload injects) is dropped - no stderr
# slices, no raw messages, no transcripts.
_AUDIT_ALLOWED_KEYS: frozenset[str] = frozenset({
    "runtime_revision", "provider", "provider_model", "duration_ms",
    "model_iterations_used", "model_iterations_budget",
    "tool_calls_used", "tool_calls_budget", "tokens",
    "evidence_requests", "evidence_returned",
    "model_confidence", "confidence_band", "confidence_basis",
    "decision_action", "repair_used", "validation_result",
    "failure_category", "failure_stage",
})
_MAX_EVIDENCE_ITEMS = 8


def _sanitize_audit(raw: Any) -> dict:
    d = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}
    for k in _AUDIT_ALLOWED_KEYS:
        if k not in d:
            continue
        v = d[k]
        if k in ("evidence_requests", "evidence_returned") and isinstance(v, list):
            v = [x for x in v if isinstance(x, dict)][:_MAX_EVIDENCE_ITEMS]
        elif k == "validation_result" and isinstance(v, str):
            v = v[:60]
        out[k] = v
    return out


def _to_proposal(obj: Any, audit: dict) -> StrategyProposal:
    """Map the child's already-validated proposal dict to a typed proposal. The
    child guarantees exact keys + types; this only builds the object. The
    engine's ``_validate_proposal`` is still the final authority."""
    if not isinstance(obj, dict):
        audit["failure_category"] = _PARENT_FAIL_PROPOSAL_SHAPE
        raise InvalidProposal("Hermes proposal payload was not an object")
    action = _ACTION_MAP.get(str(obj.get("action")))
    if action is None or not isinstance(obj.get("confidence"), (int, float)) \
            or isinstance(obj.get("confidence"), bool) \
            or not isinstance(obj.get("proposed_wait_hours"), int) \
            or isinstance(obj.get("proposed_wait_hours"), bool):
        audit["failure_category"] = _PARENT_FAIL_PROPOSAL_SHAPE
        raise InvalidProposal("Hermes proposal fields failed the parent shape check")
    mi = obj.get("message_intent")
    return StrategyProposal(
        action=action,
        diagnosis=str(obj.get("diagnosis", "")).strip() or "(none)",
        rationale=str(obj.get("rationale", "")).strip() or "(none)",
        confidence=float(obj["confidence"]),
        proposed_wait_hours=int(obj["proposed_wait_hours"]),
        message_intent=mi if isinstance(mi, str) and mi.strip() else None,
    )
