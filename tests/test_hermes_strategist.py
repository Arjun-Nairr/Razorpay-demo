"""Offline proof of the Hermes runtime spike (shipped path: direct google-genai).

Zero network, zero API key: every test injects a stub transport. The real
Gemini round-trip is exercised only by ``scripts/hermes_smoke.py``, run by the
human user. Nothing here imports ``google.genai``.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import time

import pytest

from hermes.hermes_strategist import (
    DEFAULT_MODEL,
    ISOLATION_PROFILE,
    PROMPT_VERSION,
    HermesStrategist,
    parse_proposal,
)
from hermes.types import (
    InvalidProposal,
    ProposalAction,
    StrategyProposal,
    StrategySnapshot,
)

VALID_JSON = json.dumps(
    {
        "action": "CREATE_RECOVERY_LINK",
        "diagnosis": "insufficient funds, one provider retry already failed",
        "rationale": "wait is spent; offer an alternate collection path",
        "confidence": 0.71,
        "proposed_wait_hours": 0,
        "message_intent": "Your recent payment did not go through - a secure way to complete it is ready.",
    }
)


def snapshot(**over) -> StrategySnapshot:
    base = dict(
        case_id="case-x",
        obligation_id="sub_x",
        amount_minor=1_000_000,
        currency="INR",
        failure_reason="insufficient_funds",
        state="waiting",
        provider_retry_eligible=True,
        provider_retry_evidence="provider_retry_signal",
        retry_outcome_recorded=True,
        communication_owner="merchant",
        consent=True,
        reachable_channel=True,
        messages_remaining=2,
        links_remaining=1,
        actions_remaining=3,
        prior_action="WAIT_FOR_PROVIDER_RETRY",
        prior_policy_outcome="ALLOW",
    )
    base.update(over)
    return StrategySnapshot(**base)


class StubTransport:
    """Scripted transport. Each entry is either a response string or a callable
    (invoked for side effects like sleeping, then its return used)."""

    def __init__(self, *responses, sleep_s: float = 0.0):
        self._responses = list(responses)
        self._sleep_s = sleep_s
        self.calls: list[dict] = []

    def generate(self, *, system: str, user: str):
        self.calls.append({"system": system, "user": user})
        if self._sleep_s:
            time.sleep(self._sleep_s)
        item = self._responses.pop(0)
        raw = item() if callable(item) else item
        return raw, {"prompt_tokens": 10, "output_tokens": 20, "total_tokens": 30}


def strategist(*responses, sleep_s=0.0, **kw):
    stub = StubTransport(*responses, sleep_s=sleep_s)
    return HermesStrategist(transport_factory=lambda: stub, **kw), stub


# --- schema validation ------------------------------------------------------


def test_valid_json_becomes_typed_proposal():
    s, stub = strategist(VALID_JSON)
    proposal = s.propose(snapshot())
    assert isinstance(proposal, StrategyProposal)
    assert proposal.action is ProposalAction.CREATE_RECOVERY_LINK
    assert 0.0 <= proposal.confidence <= 1.0
    assert len(stub.calls) == 1
    meta = s.last_run_meta
    assert meta is not None
    assert meta.validation_result == "valid" and meta.repair_used is False
    assert meta.model == DEFAULT_MODEL and meta.prompt_version == PROMPT_VERSION
    assert meta.usage == {"prompt_tokens": 10, "output_tokens": 20, "total_tokens": 30}
    assert meta.latency_ms >= 0.0


@pytest.mark.parametrize(
    "bad",
    [
        "not json at all",
        json.dumps({"action": "CREATE_RECOVERY_LINK"}),  # missing required keys
        json.dumps({"action": "NOPE", "diagnosis": "d", "rationale": "r", "confidence": 0.5}),
        json.dumps({"action": "STOP", "diagnosis": "d", "rationale": "r", "confidence": 2}),
        json.dumps({"action": "STOP", "diagnosis": "d", "rationale": "r", "confidence": 0.5,
                    "proposed_wait_hours": -1}),
        json.dumps(["a", "list"]),
    ],
)
def test_parse_proposal_rejects_structurally_invalid(bad):
    with pytest.raises(InvalidProposal):
        parse_proposal(bad)


def test_malformed_then_unfixed_raises_after_exactly_one_repair():
    s, stub = strategist("garbage", "still garbage")
    with pytest.raises(InvalidProposal):
        s.propose(snapshot())
    assert len(stub.calls) == 2  # first + exactly one repair
    assert "rejected" in stub.calls[1]["user"].lower()  # repair prompt carries the error
    meta = s.last_run_meta
    assert meta.repair_used is True and meta.validation_result.startswith("invalid:")


def test_repair_succeeds_on_second_try():
    s, stub = strategist("{oops", VALID_JSON)
    proposal = s.propose(snapshot())
    assert proposal.action is ProposalAction.CREATE_RECOVERY_LINK
    assert len(stub.calls) == 2
    assert s.last_run_meta.repair_used is True
    assert s.last_run_meta.validation_result == "repaired"


def test_zero_repair_budget_raises_on_first_invalid():
    s, stub = strategist("garbage", max_repair_attempts=0)
    with pytest.raises(InvalidProposal):
        s.propose(snapshot())
    assert len(stub.calls) == 1
    assert s.last_run_meta.repair_used is False


def test_blank_message_intent_is_normalised_to_none():
    raw = json.dumps(
        {"action": "WAIT_FOR_PROVIDER_RETRY", "diagnosis": "d", "rationale": "r",
         "confidence": 0.5, "proposed_wait_hours": 24, "message_intent": "   "}
    )
    assert parse_proposal(raw).message_intent is None


# --- timeout --------------------------------------------------------------


def test_call_exceeding_budget_raises_timeouterror():
    s, stub = strategist(VALID_JSON, sleep_s=0.30, timeout_s=0.05)
    with pytest.raises(TimeoutError):
        s.propose(snapshot())


# --- isolation contract -------------------------------------------------


def test_isolation_profile_is_declared():
    p = ISOLATION_PROFILE
    assert p["fresh_instance_per_call"] is True
    assert p["skip_memory"] is True and p["skip_context_files"] is True
    assert p["enabled_toolsets"] == ()  # empty positive allowlist
    for off in ("curator", "skills_mutation", "delegation", "terminal", "file",
                "browser", "cron", "code_execution"):
        assert p[off] is False, off
    assert p["max_iterations"] == 3


# --- context minimisation ---------------------------------------------


def test_prompt_context_excludes_identifiers_and_amounts():
    s, stub = strategist(VALID_JSON)
    s.propose(snapshot(obligation_id="sub_SECRET_9", case_id="case_SECRET_9",
                       amount_minor=987654))
    sent = stub.calls[0]["system"] + "\n" + stub.calls[0]["user"]
    for leak in ("sub_SECRET_9", "case_SECRET_9", "987654", "9876.54"):
        assert leak not in sent
    assert "insufficient_funds" in sent  # decision-relevant fact is present


# --- guardrails ------------------------------------------------------


def _genai_importable() -> bool:
    try:
        return importlib.util.find_spec("google.genai") is not None
    except ModuleNotFoundError:
        return False


def test_offline_path_needs_no_genai_sdk():
    # The project interpreter has no google.genai; the module + stub path work anyway.
    assert _genai_importable() is False
    s, _ = strategist(VALID_JSON)
    assert s.propose(snapshot()).action is ProposalAction.CREATE_RECOVERY_LINK


def test_not_wired_into_default_engine():
    engine_src = (
        pathlib.Path(__file__).parent.parent / "src" / "hermes" / "engine.py"
    ).read_text()
    assert "HermesStrategist" not in engine_src
    assert "hermes_strategist" not in engine_src


def test_real_transport_build_requires_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    s = HermesStrategist()  # no transport_factory -> real path
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        s.propose(snapshot())
