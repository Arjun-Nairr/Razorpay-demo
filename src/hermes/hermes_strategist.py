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
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .message_templates import APPROVED_MESSAGE_INTENT_LIST, is_approved_message_intent
from .types import (
    MAX_HUMAN_REVIEW_REASON_CHARS,
    NO_REVIEW_INTERVENTIONS,
    InvalidProposal,
    ProposalAction,
    RecommendedIntervention,
    StrategyProposal,
    StrategySnapshot,
)

DEFAULT_MODEL = "gemini-3.7-flash"
DEFAULT_TIMEOUT_S = 60.0
DEFAULT_API_KEY_ENV = "GEMINI_API_KEY"
# Bumped: the prompt/schema now require an explicit non-executable advisory
# (recommended_intervention + human_review_recommended + human_review_reason),
# validated structurally here within the one-repair boundary.
PROMPT_VERSION = "hermes-strategist/2026-09-05.1"
_MAX_RAW_CHARS = 4000  # bounded raw-response capture for run metadata

# The model must return a JSON object with EXACTLY these keys - no more, no less.
REQUIRED_KEYS: tuple[str, ...] = (
    "action",
    "diagnosis",
    "rationale",
    "confidence",
    "proposed_wait_hours",
    "recommended_intervention",
    "human_review_recommended",
    "human_review_reason",
    "message_intent",
)

_ALL_INTERVENTIONS: frozenset[str] = frozenset(r.value for r in RecommendedIntervention)
_NO_REVIEW_VALUES: frozenset[str] = frozenset(r.value for r in NO_REVIEW_INTERVENTIONS)

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

_APPROVED_MESSAGES_BLOCK = "\n".join(
    f'  {i + 1}. "{text}"' for i, text in enumerate(APPROVED_MESSAGE_INTENT_LIST)
)

_SYSTEM_PROMPT = f"""You are Hermes, a merchant-side subscription-payment recovery strategist.
You PROPOSE one strategy; deterministic policy decides what is allowed.

Return ONLY a single JSON object, no prose, with exactly these keys:
  "action": one of WAIT_FOR_PROVIDER_RETRY, SEND_REMINDER,
            REQUEST_PAYMENT_METHOD_UPDATE, CREATE_RECOVERY_LINK,
            RECOMMEND_STRUCTURAL_CHANGE, TAKE_NO_ACTION, STOP, ESCALATE
  "diagnosis": short string
  "rationale": short string
  "confidence": number between 0 and 1
  "proposed_wait_hours": integer (only meaningful for WAIT_FOR_PROVIDER_RETRY;
                         when action is WAIT_FOR_PROVIDER_RETRY it MUST be an
                         integer >= 1 and MUST NOT exceed "wait_hours_remaining"
                         from the snapshot)
  "recommended_intervention": a SEPARATE, non-executable advisory - one of
                         NONE, UPDATE_PAYMENT_METHOD, MANDATE_REAUTH_REVIEW,
                         PAYMENT_PLAN_REVIEW, BILLING_SUPPORT_REVIEW,
                         HUMAN_FOLLOW_UP. It never authorizes anything and
                         never recommends a discount, access change,
                         suspension, or freeze.
  "human_review_recommended": true/false. MUST be false for NONE and
                         UPDATE_PAYMENT_METHOD; MUST be true for every other
                         recommended_intervention.
  "human_review_reason": null for NONE/UPDATE_PAYMENT_METHOD; otherwise a
                         short (<= {MAX_HUMAN_REVIEW_REASON_CHARS} char),
                         evidence-based reason - never a URL, amount, or
                         payment/provider identifier, never an invented fact.
  "message_intent": EITHER null, OR one of these approved strings COPIED VERBATIM
                    (no other text is accepted; pick the closest fit):
{_APPROVED_MESSAGES_BLOCK}

"provider_retry_eligible" is the CURRENT provider fact. "retry_outcome_recorded"
only means a prior retry already failed - it does NOT mean retries are
exhausted; the two are independent. Use only the facts in the snapshot."""


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
        "wait_hours_remaining": snap.wait_hours_remaining,
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
    exact key set, types, enum membership, numeric ranges, blank-message
    normalization. Content rules (no URL / currency / provider id in
    ``message_intent``) stay with the engine's ``_validate_proposal``. Raises
    :class:`InvalidProposal`."""
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise InvalidProposal(f"not valid JSON: {exc}")
    if not isinstance(obj, dict):
        raise InvalidProposal(f"top-level JSON is {type(obj).__name__}, expected object")

    keys = set(obj.keys())
    allowed = set(REQUIRED_KEYS)
    missing = sorted(allowed - keys)
    if missing:
        raise InvalidProposal(f"missing keys: {missing}")
    extra = sorted(keys - allowed)
    if extra:
        raise InvalidProposal(f"unexpected keys: {extra}")

    try:
        action = ProposalAction(obj["action"])
    except (ValueError, TypeError):
        raise InvalidProposal(f"unknown action: {obj['action']!r}")

    conf = obj["confidence"]
    if isinstance(conf, bool) or not isinstance(conf, (int, float)):
        raise InvalidProposal(f"confidence not numeric: {conf!r}")
    if not 0.0 <= float(conf) <= 1.0:
        raise InvalidProposal(f"confidence out of range 0..1: {conf!r}")

    wait = obj["proposed_wait_hours"]
    if isinstance(wait, bool) or not isinstance(wait, int) or wait < 0:
        raise InvalidProposal(f"proposed_wait_hours must be int >= 0: {wait!r}")
    if action is ProposalAction.WAIT_FOR_PROVIDER_RETRY and wait < 1:
        raise InvalidProposal("WAIT_FOR_PROVIDER_RETRY requires proposed_wait_hours >= 1")

    diagnosis = obj["diagnosis"]
    rationale = obj["rationale"]
    if not isinstance(diagnosis, str) or not diagnosis.strip():
        raise InvalidProposal("diagnosis must be a non-empty string")
    if not isinstance(rationale, str) or not rationale.strip():
        raise InvalidProposal("rationale must be a non-empty string")

    message_intent = obj["message_intent"]
    if message_intent is not None and not isinstance(message_intent, str):
        raise InvalidProposal(f"message_intent must be string or null: {message_intent!r}")
    if isinstance(message_intent, str):
        message_intent = message_intent.strip() or None
    # Message choice is validated here too (within the one-repair boundary), so
    # a repair prompt can tell Gemini exactly which strings are allowed. The
    # engine's _validate_proposal is still the final deterministic guard.
    if not is_approved_message_intent(message_intent):
        raise InvalidProposal(
            "message_intent must be null or one of the approved templates verbatim"
        )

    ri_raw = obj["recommended_intervention"]
    if ri_raw not in _ALL_INTERVENTIONS:
        raise InvalidProposal(f"unknown recommended_intervention: {ri_raw!r}")
    recommended_intervention = RecommendedIntervention(ri_raw)

    hrr = obj["human_review_recommended"]
    if not isinstance(hrr, bool):
        raise InvalidProposal(f"human_review_recommended must be a real boolean: {hrr!r}")

    reason = obj["human_review_reason"]
    if reason is not None:
        if not isinstance(reason, str) or not reason.strip():
            raise InvalidProposal("human_review_reason must be null or a nonblank string")
        if len(reason) > MAX_HUMAN_REVIEW_REASON_CHARS:
            raise InvalidProposal(
                f"human_review_reason exceeds {MAX_HUMAN_REVIEW_REASON_CHARS} characters"
            )
        reason = reason.strip()

    if ri_raw in _NO_REVIEW_VALUES:
        if hrr is not False or reason is not None:
            raise InvalidProposal(
                f"{ri_raw} must not set human_review_recommended or human_review_reason"
            )
    else:
        if hrr is not True or not reason:
            raise InvalidProposal(
                f"{ri_raw} requires human_review_recommended=true and a nonblank "
                "human_review_reason"
            )

    return StrategyProposal(
        action=action,
        diagnosis=diagnosis.strip(),
        rationale=rationale.strip(),
        confidence=float(conf),
        proposed_wait_hours=int(wait),
        message_intent=message_intent,
        recommended_intervention=recommended_intervention,
        human_review_recommended=hrr,
        human_review_reason=reason,
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
        it raises :class:`TimeoutError` promptly (the abandoned worker thread is
        a daemon and its result is discarded).
    max_repair_attempts:
        Repair budget after an invalid first reply. Hard-clamped to ``{0, 1}``:
        any value >= 1 becomes 1, anything else 0. A caller can never trigger
        more than one repair call.
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
        max_in_flight: int = 2,
    ) -> None:
        self._model = model
        self._timeout_s = float(timeout_s)
        # Contract: at most one repair, ever. Clamp explicitly to {0, 1}.
        self._max_repair_attempts = 1 if int(max_repair_attempts) >= 1 else 0
        self._api_key_env = api_key_env
        self._transport_factory = transport_factory
        # Caps the number of model-call worker threads alive at once. A slot is
        # held until the worker thread *finishes* (even one abandoned after a
        # timeout), so repeated timeouts cannot pile up unbounded live threads;
        # a call that cannot get a slot within the timeout budget raises
        # TimeoutError like any other overrun.
        self._slots = threading.BoundedSemaphore(max(1, int(max_in_flight)))
        self._last_run_meta: StrategistRunMeta | None = None

    @property
    def last_run_meta(self) -> StrategistRunMeta | None:
        return self._last_run_meta

    # -- Strategist protocol ------------------------------------------------

    def propose(self, snapshot: StrategySnapshot) -> StrategyProposal:
        # Never leave stale metadata from a prior call visible if this one
        # fails early. Time from before transport construction so setup
        # latency is included.
        self._last_run_meta = None
        started = time.monotonic()

        # -- transport construction ---------------------------------------
        # Covers a raising transport_factory, the lazy SDK import,
        # genai.Client(...) init, and a missing GEMINI_API_KEY. Only the
        # exception *type name* is recorded - never its message or any
        # credential/SDK detail it might carry.
        try:
            transport = (self._transport_factory or self._build_real_transport)()
        except Exception as exc:
            self._record(started, "", None, repair_used=False,
                         validation=f"transport_error:{type(exc).__name__}")
            raise

        # -- first model call ------------------------------------------------
        try:
            raw, usage = self._call(transport, _user_prompt(snapshot))
        except TimeoutError:
            self._record(started, "", None, repair_used=False, validation="timeout")
            raise
        except Exception as exc:  # transport / SDK failure
            self._record(started, "", None, repair_used=False,
                         validation=f"transport_error:{type(exc).__name__}")
            raise

        try:
            proposal = parse_proposal(raw)
            self._record(started, raw, usage, repair_used=False, validation="valid")
            return proposal
        except InvalidProposal as first_error:
            if self._max_repair_attempts < 1:
                self._record(started, raw, usage, repair_used=False,
                             validation=f"invalid:{first_error}")
                raise
            first_reason = str(first_error)  # `first_error` is out of scope below

        # -- exactly one repair call --------------------------------------
        try:
            raw2, usage2 = self._call(
                transport, _user_prompt(snapshot, repair_reason=first_reason)
            )
        except TimeoutError:
            # keep the first reply's raw/usage - it is the available evidence
            self._record(started, raw, usage, repair_used=True, validation="timeout")
            raise
        except Exception as exc:
            self._record(started, raw, usage, repair_used=True,
                         validation=f"transport_error:{type(exc).__name__}")
            raise

        usage = usage2 or usage
        try:
            proposal = parse_proposal(raw2)
        except InvalidProposal as second_error:
            self._record(started, raw2, usage, repair_used=True,
                         validation=f"invalid:{second_error}")
            raise
        self._record(started, raw2, usage, repair_used=True, validation="repaired")
        return proposal

    # -- internals -------------------------------------------------------

    def _call(self, transport: _Transport, user_prompt: str) -> tuple[str, dict[str, Any] | None]:
        """One model call under the application-level wall-clock timeout.

        The call runs on a daemon thread. On timeout this method raises
        :class:`TimeoutError` immediately; the worker is abandoned (it cannot be
        force-killed) and, being a daemon, never blocks interpreter exit. Its
        eventual result or exception is discarded. No executor, so no
        ``shutdown(wait=True)`` and no ``atexit`` join.
        """
        if not self._slots.acquire(timeout=self._timeout_s):
            raise TimeoutError("strategist concurrency limit reached")

        box: dict[str, Any] = {}

        def _worker() -> None:
            try:
                box["result"] = transport.generate(system=_SYSTEM_PROMPT, user=user_prompt)
            except BaseException as exc:  # noqa: BLE001  captured, surfaced below
                box["error"] = exc
            finally:
                self._slots.release()  # frees the slot only when THIS thread ends

        worker = threading.Thread(
            target=_worker, name="hermes-strategist-call", daemon=True
        )
        worker.start()
        worker.join(self._timeout_s)
        if worker.is_alive():
            raise TimeoutError(
                f"strategist model call exceeded {self._timeout_s:.3g}s budget"
            )
        if "error" in box:
            raise box["error"]
        return box["result"]

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
