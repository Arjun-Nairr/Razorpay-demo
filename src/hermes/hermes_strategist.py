"""Hermes's LLM strategist, behind the existing ``Strategist`` protocol.

SHIPPED PATH: **direct google-genai (Gemini 3.7 Flash)**. The Hermes-Agent
library path (``IMPLEMENTATION_SPEC.md`` tracer-bullet slice 2, primary option)
was *not* taken - see ``HANDOFF.md`` Iteration 06 for the fallback trigger
(``pip install`` of the pinned Hermes commit fails on Windows: its internal
``git clone`` cannot pass ``core.longpaths=true`` and the repo's docusaurus
i18n tree exceeds ``MAX_PATH``). Per the slice-2 prompt's sanctioned fallback,
this module keeps the *same contract* the Hermes path would have honoured:

- strict local JSON schema validation (structural: shape / types / enum / range),
- an application-level timeout that raises :class:`TimeoutError`,
- at most one bounded repair attempt, then :class:`hermes.types.InvalidProposal`,

so the engine's existing ``except Exception -> apply_strategist_failure`` path
stays the sole integration point. The engine's ``_validate_proposal`` remains
the final authority on proposal *content* (URL / currency / provider-id rules);
nothing in the engine, ledger, or ``types.py`` changes.

Isolation: a fresh client per decision, no tools, no memory, no context files,
no side effects beyond one ``generate_content`` call. The API key is read from
the environment and never logged. :data:`ISOLATION_PROFILE` records the exact
switch settings a future real-Hermes ``AIAgent`` swap must reproduce.

This class is **not** wired into the default :class:`~hermes.engine.RecoveryEngine`
construction. It is proven by ``tests/test_hermes_strategist.py`` (offline,
injected transport, zero network, zero key) and ``scripts/hermes_smoke.py``
(one real Gemini round-trip, run by the human user).
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FuturesTimeout
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .types import InvalidProposal, ProposalAction, StrategyProposal, StrategySnapshot

DEFAULT_MODEL = "gemini-3.7-flash"
DEFAULT_TIMEOUT_S = 60.0
DEFAULT_API_KEY_ENV = "GEMINI_API_KEY"
PROMPT_VERSION = "hermes-strategist/2026-09-03.1"
_MAX_RAW_CHARS = 4000  # bounded raw-response capture for run metadata

# The isolation settings the Hermes-Agent path WOULD have applied to every
# fresh ``AIAgent``. Asserted verbatim by the offline tests so a later swap to
# the real library has an explicit checklist. (In the shipped google-genai
# path there is no AIAgent to configure; a plain client already has none of
# these capabilities - the profile is the contract, not live config.)
ISOLATION_PROFILE: dict[str, Any] = {
    "fresh_instance_per_call": True,
    "skip_memory": True,
    "skip_context_files": True,
    "enabled_toolsets": (),  # empty positive allowlist -> no tools at all
    "curator": False,
    "skills_mutation": False,
    "delegation": False,
    "terminal": False,
    "file": False,
    "browser": False,
    "cron": False,
    "code_execution": False,
    "max_iterations": 3,
}


@dataclass
class StrategistRunMeta:
    """Contained model-run metadata for one ``propose`` call.

    Not wired into the ledger's ``AI_PROPOSAL`` audit rows - that is a later
    task. Exposed via :attr:`HermesStrategist.last_run_meta` and printed by the
    smoke script.
    """

    model: str
    prompt_version: str
    latency_ms: float
    repair_used: bool
    validation_result: str  # "valid" | "repaired" | "invalid:<reason>"
    raw_response: str  # bounded to _MAX_RAW_CHARS
    usage: dict[str, Any] | None = None
    cost_usd: float | None = None


class _Transport(Protocol):
    """One text-in / text-out model call. The real implementation wraps
    google-genai; tests inject a stub."""

    def generate(self, *, system: str, user: str) -> tuple[str, dict[str, Any] | None]: ...


# --- prompt (versioned) -------------------------------------------------------

_SYSTEM_PROMPT = """You are Hermes, a merchant-side subscription-payment recovery strategist.
You PROPOSE one strategy; deterministic policy decides what is allowed.

Return ONLY a single JSON object, no prose, with exactly these keys:
  "action": one of WAIT_FOR_PROVIDER_RETRY, SEND_REMINDER,
            REQUEST_PAYMENT_METHOD_UPDATE, CREATE_RECOVERY_LINK,
            RECOMMEND_STRUCTURAL_CHANGE, TAKE_NO_ACTION, STOP, ESCALATE
  "diagnosis": short string
  "rationale": short string
  "confidence": number between 0 and 1
  "proposed_wait_hours": integer >= 0 (only meaningful for WAIT_FOR_PROVIDER_RETRY)
  "message_intent": short string, or null

Never put a URL, currency symbol, amount, discount, or provider identifier in
"message_intent". Use only the facts in the snapshot."""


def _context_facts(snap: StrategySnapshot) -> dict[str, Any]:
    """Minimized, source-labelled facts. No case id, obligation id, amount, or
    currency - the model never needs them and could echo one into a field the
    engine would then reject."""
    return {
        "failure_reason": snap.failure_reason,
        "case_state": snap.state,
        "provider_retry_eligible": snap.provider_retry_eligible,
        "provider_retry_evidence_present": snap.provider_retry_evidence is not None,
        "retry_outcome_recorded": snap.retry_outcome_recorded,
        "communication_owner": snap.communication_owner,
        "consent": snap.consent,
        "reachable_channel": snap.reachable_channel,
        "messages_remaining": snap.messages_remaining,
        "links_remaining": snap.links_remaining,
        "actions_remaining": snap.actions_remaining,
        "prior_action": snap.prior_action,
        "prior_policy_outcome": snap.prior_policy_outcome,
    }


def _user_prompt(snap: StrategySnapshot, *, repair_reason: str | None = None) -> str:
    body = "SNAPSHOT (source-labelled merchant/provider facts):\n" + json.dumps(
        _context_facts(snap), indent=2, sort_keys=True
    )
    if repair_reason:
        body += (
            "\n\nYour previous reply was rejected: "
            + repair_reason
            + "\nReturn ONLY the corrected JSON object, nothing else."
        )
    return body


# --- strict local validation (structural) -----------------------------------


def parse_proposal(raw: str) -> StrategyProposal:
    """Parse strict JSON into a :class:`StrategyProposal`. Structural only:
    shape, required keys, types, enum membership, numeric ranges. Content rules
    (no URL / currency / provider id in ``message_intent``) stay with the
    engine's ``_validate_proposal``. Raises :class:`InvalidProposal`."""
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise InvalidProposal(f"not valid JSON: {exc}")
    if not isinstance(obj, dict):
        raise InvalidProposal(f"top-level JSON is {type(obj).__name__}, expected object")

    required = {"action", "diagnosis", "rationale", "confidence"}
    missing = sorted(required - obj.keys())
    if missing:
        raise InvalidProposal(f"missing keys: {missing}")

    try:
        action = ProposalAction(obj["action"])
    except (ValueError, TypeError):
        raise InvalidProposal(f"unknown action: {obj['action']!r}")

    conf = obj["confidence"]
    if isinstance(conf, bool) or not isinstance(conf, (int, float)):
        raise InvalidProposal(f"confidence not numeric: {conf!r}")
    if not 0.0 <= float(conf) <= 1.0:
        raise InvalidProposal(f"confidence out of range 0..1: {conf!r}")

    wait = obj.get("proposed_wait_hours", 0)
    if isinstance(wait, bool) or not isinstance(wait, int) or wait < 0:
        raise InvalidProposal(f"proposed_wait_hours must be int >= 0: {wait!r}")

    diagnosis = obj["diagnosis"]
    rationale = obj["rationale"]
    if not isinstance(diagnosis, str) or not diagnosis.strip():
        raise InvalidProposal("diagnosis must be a non-empty string")
    if not isinstance(rationale, str) or not rationale.strip():
        raise InvalidProposal("rationale must be a non-empty string")

    message_intent = obj.get("message_intent")
    if message_intent is not None and not isinstance(message_intent, str):
        raise InvalidProposal(f"message_intent must be string or null: {message_intent!r}")
    if isinstance(message_intent, str):
        message_intent = message_intent.strip() or None

    return StrategyProposal(
        action=action,
        diagnosis=diagnosis.strip(),
        rationale=rationale.strip(),
        confidence=float(conf),
        proposed_wait_hours=int(wait),
        message_intent=message_intent,
    )


# --- strategist -----------------------------------------------------------


class HermesStrategist:
    """A ``Strategist`` implementation backed by one isolated Gemini call.

    Parameters
    ----------
    model:
        Gemini model id (default ``gemini-3.7-flash``).
    timeout_s:
        Application-level wall-clock budget for a single model call; exceeding
        it raises :class:`TimeoutError`.
    max_repair_attempts:
        At most one bounded repair call after an invalid first reply (default 1;
        0 disables repair).
    api_key_env:
        Environment variable the real client reads the key from. Never a literal.
    transport_factory:
        Test seam. ``None`` -> the real google-genai client (lazy-imported).
        A callable returning a :class:`_Transport` -> offline / injected.
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_repair_attempts: int = 1,
        api_key_env: str = DEFAULT_API_KEY_ENV,
        transport_factory: Callable[[], _Transport] | None = None,
    ) -> None:
        self._model = model
        self._timeout_s = float(timeout_s)
        self._max_repair_attempts = max(0, int(max_repair_attempts))
        self._api_key_env = api_key_env
        self._transport_factory = transport_factory
        self._last_run_meta: StrategistRunMeta | None = None

    @property
    def last_run_meta(self) -> StrategistRunMeta | None:
        return self._last_run_meta

    # -- Strategist protocol ------------------------------------------------

    def propose(self, snapshot: StrategySnapshot) -> StrategyProposal:
        transport = (self._transport_factory or self._build_real_transport)()
        started = time.monotonic()
        raw, usage = self._call(transport, _user_prompt(snapshot))
        repair_used = False

        try:
            proposal = parse_proposal(raw)
            validation = "valid"
        except InvalidProposal as first_error:
            if self._max_repair_attempts < 1:
                self._record(started, raw, usage, repair_used=False,
                             validation=f"invalid:{first_error}")
                raise
            repair_used = True
            raw, repair_usage = self._call(
                transport, _user_prompt(snapshot, repair_reason=str(first_error))
            )
            usage = repair_usage or usage
            try:
                proposal = parse_proposal(raw)
                validation = "repaired"
            except InvalidProposal as second_error:
                self._record(started, raw, usage, repair_used=True,
                             validation=f"invalid:{second_error}")
                raise

        self._record(started, raw, usage, repair_used=repair_used, validation=validation)
        return proposal

    # -- internals -------------------------------------------------------

    def _call(self, transport: _Transport, user_prompt: str) -> tuple[str, dict[str, Any] | None]:
        """One model call under the application-level timeout. The worker thread
        cannot be force-killed; on timeout it is left to finish and its result
        discarded (acceptable for a single short spike call)."""
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(transport.generate, system=_SYSTEM_PROMPT, user=user_prompt)
            try:
                return future.result(timeout=self._timeout_s)
            except _FuturesTimeout:
                raise TimeoutError(
                    f"strategist model call exceeded {self._timeout_s:.3g}s budget"
                )

    def _record(
        self,
        started: float,
        raw: str,
        usage: dict[str, Any] | None,
        *,
        repair_used: bool,
        validation: str,
    ) -> None:
        self._last_run_meta = StrategistRunMeta(
            model=self._model,
            prompt_version=PROMPT_VERSION,
            latency_ms=round((time.monotonic() - started) * 1000.0, 1),
            repair_used=repair_used,
            validation_result=validation,
            raw_response=(raw or "")[:_MAX_RAW_CHARS],
            usage=usage,
            cost_usd=None,  # Gemini API does not return per-call cost; left None
        )

    def _build_real_transport(self) -> _Transport:
        """Lazy: google-genai is imported only here, so the offline test suite
        (which injects ``transport_factory``) never needs the SDK installed."""
        key = os.environ.get(self._api_key_env)
        if not key:
            raise RuntimeError(
                f"{self._api_key_env} is not set. Real Gemini calls need it; "
                "offline tests must pass transport_factory instead."
            )
        from google import genai  # noqa: PLC0415  (deliberate lazy import)
        from google.genai import types as gt  # noqa: PLC0415

        client = genai.Client(api_key=key)
        model = self._model

        class _GeminiTransport:
            def generate(self, *, system: str, user: str) -> tuple[str, dict[str, Any] | None]:
                config = gt.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    temperature=0.2,
                    max_output_tokens=512,
                )
                resp = client.models.generate_content(
                    model=model, contents=user, config=config
                )
                raw = (getattr(resp, "text", None) or "").strip()
                usage = None
                meta = getattr(resp, "usage_metadata", None)
                if meta is not None:
                    usage = {
                        "prompt_tokens": getattr(meta, "prompt_token_count", None),
                        "output_tokens": getattr(meta, "candidates_token_count", None),
                        "total_tokens": getattr(meta, "total_token_count", None),
                    }
                return raw, usage

        return _GeminiTransport()
