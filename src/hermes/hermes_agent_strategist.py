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
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
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
from .hermes_strategist import PROMPT_VERSION as _GEMINI_PROMPT_VERSION  # noqa: F401 (doc ref)
from .types import InvalidProposal, ProposalAction, StrategyProposal, StrategySnapshot

PROMPT_VERSION = "hermes-agent/2026-09-04.1"

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
    repair_used / validation_result / usage) plus ``extra`` for the
    Hermes-specific fields (runtime revision, evidence requests + reasons,
    returned source/coverage, confidence band, unresolved uncertainty, stop
    reason, duration, tokens)."""

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


# --- coherent synthetic 12-month history for the demo customer ---------------
# Plausible merchant-held records only: due date, paid date, outcome. Labelled
# SYNTHETIC. Shorter windows are the trailing subset of this list.
_SYNTHETIC_HISTORY_12M: tuple[dict[str, str], ...] = (
    {"due": "2025-10-01", "paid": "2025-10-01", "outcome": "paid_on_time"},
    {"due": "2025-11-01", "paid": "2025-11-01", "outcome": "paid_on_time"},
    {"due": "2025-12-01", "paid": "2025-12-02", "outcome": "paid_next_day"},
    {"due": "2026-01-01", "paid": "2026-01-01", "outcome": "paid_on_time"},
    {"due": "2026-02-01", "paid": "2026-02-01", "outcome": "paid_on_time"},
    {"due": "2026-03-01", "paid": "2026-03-01", "outcome": "paid_on_time"},
    {"due": "2026-04-01", "paid": "2026-04-03", "outcome": "paid_next_day"},
    {"due": "2026-05-01", "paid": "2026-05-01", "outcome": "paid_on_time"},
    {"due": "2026-06-01", "paid": "2026-06-01", "outcome": "paid_on_time"},
    {"due": "2026-07-01", "paid": "2026-07-01", "outcome": "paid_on_time"},
    {"due": "2026-08-01", "paid": "2026-08-01", "outcome": "paid_on_time"},
    {"due": "2026-09-01", "paid": "", "outcome": "failed_insufficient_funds"},
)


def _evidence_bundle(snap: StrategySnapshot, *, history_available: bool = True) -> dict:
    """Immutable bundle backing the three child tools. No amounts/URLs/ids the
    model could echo as customer copy; provider facts and consent are authoritative."""
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
        "payment_history_3m": {
            "source": "SYNTHETIC_MERCHANT_RECORDS", "label": "SYNTHETIC",
            "coverage_months": 3, "records": list(_SYNTHETIC_HISTORY_12M[-3:]),
        },
    }
    return {
        "initial_context": initial_context,
        "retry_facts": {
            "source": "SIMULATED_PROVIDER", "coverage": "current provider state",
            "provider_retry_eligible": snap.provider_retry_eligible,
            "provider_retry_evidence": snap.provider_retry_evidence,
            "retry_outcome_recorded": snap.retry_outcome_recorded,
        },
        "recovery_actions": {
            "source": "DETERMINISTIC_POLICY_CATALOG", "coverage": "current case",
            "actions": [
                "WAIT_FOR_PROVIDER_RETRY (only while provider_retry_eligible and wait budget remains)",
                "CREATE_RECOVERY_LINK (only after a recorded failed retry; at most one)",
                "SEND_REMINDER (merchant-owned comms + consent + reachable channel only)",
                "STOP", "ESCALATE",
            ],
            "note": "confidence never grants permission; deterministic policy authorizes",
        },
        "history_12m": {
            "available": bool(history_available),
            "source": "SYNTHETIC_MERCHANT_RECORDS",
            "rows": list(_SYNTHETIC_HISTORY_12M) if history_available else [],
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
            "evidence_bundle": _evidence_bundle(snap, history_available=self._history_available),
        }
        if self._mock_base_url:
            job["mock"] = {"base_url": self._mock_base_url, "model": self._mock_model}
        else:
            job["gemini"] = {"model": self._gemini_model}

        started = time.monotonic()
        meta = HermesRunMeta(model=(self._mock_model if self._mock_base_url else self._gemini_model))
        self.last_run_meta = meta
        try:
            proc = subprocess.run(
                [str(self._python), CHILD_MAIN],
                cwd=str(self._checkout), env=self._child_env(),
                input=json.dumps(job), capture_output=True, text=True,
                timeout=self._deadline_s,
            )
        except subprocess.TimeoutExpired:
            meta.latency_ms = (time.monotonic() - started) * 1000
            meta.validation_result = "invalid:subprocess_timeout"
            meta.extra = {"stop_reason": "subprocess_deadline", "runtime_revision": self._revision}
            raise TimeoutError("Hermes agent subprocess exceeded the 90s deadline") from None

        meta.latency_ms = (time.monotonic() - started) * 1000
        payload = _parse_result(proc.stdout)
        if payload is None:
            meta.validation_result = "invalid:no_result_line"
            meta.extra = {"stop_reason": "no_result_line", "runtime_revision": self._revision,
                          "stderr_tail": (proc.stderr or "")[-600:]}
            raise InvalidProposal("Hermes child produced no parseable result")

        audit = payload.get("audit") or {}
        meta.extra = audit
        meta.repair_used = bool(audit.get("repair_used"))
        meta.validation_result = audit.get("validation_result", meta.validation_result)
        meta.usage = audit.get("tokens")
        meta.model = audit.get("model") or meta.model

        if not payload.get("ok"):
            raise InvalidProposal(f"Hermes decision failed: {payload.get('error', 'unknown')}")

        return _to_proposal(payload["proposal"])


def _parse_result(stdout: str) -> dict | None:
    for line in reversed((stdout or "").splitlines()):
        if line.startswith(RESULT_SENTINEL):
            try:
                return json.loads(line[len(RESULT_SENTINEL):])
            except ValueError:
                return None
    return None


def _to_proposal(obj: dict) -> StrategyProposal:
    action = _ACTION_MAP.get(str(obj.get("action")))
    if action is None:
        raise InvalidProposal(f"unknown action from Hermes: {obj.get('action')!r}")
    try:
        confidence = float(obj["confidence"])
        wait = int(obj.get("proposed_wait_hours", 0))
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidProposal(f"malformed proposal field: {exc}") from None
    mi = obj.get("message_intent")
    return StrategyProposal(
        action=action,
        diagnosis=str(obj.get("diagnosis", "")).strip() or "(none)",
        rationale=str(obj.get("rationale", "")).strip() or "(none)",
        confidence=confidence,
        proposed_wait_hours=wait,
        message_intent=mi if isinstance(mi, str) and mi.strip() else None,
    )
