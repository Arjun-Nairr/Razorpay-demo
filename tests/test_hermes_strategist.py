"""Offline proof of the Hermes runtime spike (shipped path: direct google-genai).

Zero network, zero API key: every test injects a stub transport. The real
Gemini round-trip is exercised only by ``scripts/hermes_smoke.py``, run by the
human user. Nothing here imports ``google.genai`` on the tested path, and the
suite passes whether or not the optional ``google-genai`` SDK is installed.
"""

from __future__ import annotations

import builtins
import dataclasses
import json
import pathlib
import time

import pytest

from hermes.hermes_strategist import (
    DEFAULT_MODEL,
    ISOLATION_PROFILE,
    PROMPT_VERSION,
    REQUIRED_KEYS,
    HermesStrategist,
    parse_proposal,
)
from hermes.types import (
    InvalidProposal,
    ProposalAction,
    StrategyProposal,
    StrategySnapshot,
)


def _valid_obj(**over) -> dict:
    obj = {
        "action": "CREATE_RECOVERY_LINK",
        "diagnosis": "insufficient funds, one provider retry already failed",
        "rationale": "wait is spent; offer an alternate collection path",
        "confidence": 0.71,
        "proposed_wait_hours": 0,
        "recommended_intervention": "NONE",
        "human_review_recommended": False,
        "human_review_reason": None,
        "message_intent": None,  # structural tests; message-choice tests set it explicitly
    }
    obj.update(over)
    return obj


VALID_JSON = json.dumps(_valid_obj())

from hermes.message_templates import APPROVED_MESSAGE_INTENT_LIST  # noqa: E402

APPROVED_MSG = APPROVED_MESSAGE_INTENT_LIST[0]


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
    """Scripted transport. Each entry is a response string, a ``BaseException``
    to raise, or a zero-arg callable whose return value is used."""

    def __init__(self, *responses, sleep_s: float = 0.0):
        self._responses = list(responses)
        self._sleep_s = sleep_s
        self.calls: list[dict] = []

    def generate(self, *, system: str, user: str):
        self.calls.append({"system": system, "user": user})
        if self._sleep_s:
            time.sleep(self._sleep_s)
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        raw = item() if callable(item) else item
        return raw, {"prompt_tokens": 10, "output_tokens": 20, "total_tokens": 30}


def strategist(*responses, sleep_s=0.0, **kw):
    stub = StubTransport(*responses, sleep_s=sleep_s)
    return HermesStrategist(transport_factory=lambda: stub, **kw), stub


# --- schema validation: exactly nine keys ---------------------------------


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


def test_required_keys_are_the_documented_nine():
    assert set(REQUIRED_KEYS) == {
        "action", "diagnosis", "rationale", "confidence",
        "proposed_wait_hours", "recommended_intervention",
        "human_review_recommended", "human_review_reason", "message_intent",
    }


@pytest.mark.parametrize("drop", list(REQUIRED_KEYS))
def test_missing_any_required_key_is_rejected(drop):
    obj = _valid_obj()
    obj.pop(drop)
    with pytest.raises(InvalidProposal, match="missing keys"):
        parse_proposal(json.dumps(obj))


@pytest.mark.parametrize("extra", ["surprise", "priority", "action_v2"])
def test_unknown_extra_key_is_rejected(extra):
    obj = _valid_obj()
    obj[extra] = "nope"
    with pytest.raises(InvalidProposal, match="unexpected keys"):
        parse_proposal(json.dumps(obj))


@pytest.mark.parametrize(
    "raw",
    [
        "not json at all",
        json.dumps(["a", "list"]),
        json.dumps("a string"),
    ],
)
def test_non_object_json_is_rejected(raw):
    with pytest.raises(InvalidProposal):
        parse_proposal(raw)


@pytest.mark.parametrize(
    "obj",
    [
        _valid_obj(action="NOT_A_REAL_ACTION"),
        _valid_obj(confidence=2),
        _valid_obj(confidence="high"),
        _valid_obj(confidence=True),
        _valid_obj(proposed_wait_hours=-1),
        _valid_obj(proposed_wait_hours="soon"),
        _valid_obj(proposed_wait_hours=True),
        _valid_obj(diagnosis="   "),
        _valid_obj(rationale=""),
        _valid_obj(message_intent=42),
    ],
)
def test_type_enum_and_range_faults_still_rejected(obj):
    # full six-key payloads, exactly one field wrong -> the type/enum/range
    # checks (not the key-set check) are what fires.
    with pytest.raises(InvalidProposal):
        parse_proposal(json.dumps(obj))


def test_blank_message_intent_is_normalised_to_none():
    assert parse_proposal(json.dumps(_valid_obj(message_intent="   "))).message_intent is None
    assert parse_proposal(json.dumps(_valid_obj(message_intent=None))).message_intent is None


# --- typed advisory contract (recommended_intervention / human_review_*) ---


@pytest.mark.parametrize("value", ["NONE", "PAYMENT_PLAN_REVIEW"])
def test_every_valid_advisory_enum_is_accepted(value):
    """Narrowed to this demo's product scope: NONE and PAYMENT_PLAN_REVIEW
    only."""
    over = {"recommended_intervention": value}
    if value == "NONE":
        over.update(human_review_recommended=False, human_review_reason=None)
    else:
        over.update(human_review_recommended=True, human_review_reason="evidence-based reason")
    proposal = parse_proposal(json.dumps(_valid_obj(**over)))
    assert proposal.recommended_intervention.value == value


@pytest.mark.parametrize("value", [
    "OFFER_DISCOUNT", "UPDATE_PAYMENT_METHOD", "MANDATE_REAUTH_REVIEW",
    "BILLING_SUPPORT_REVIEW", "HUMAN_FOLLOW_UP",
])
def test_unknown_advisory_value_is_rejected(value):
    """Includes every intervention this demo's earlier, broader draft once
    offered - narrowing the live contract must reject them too."""
    with pytest.raises(InvalidProposal):
        parse_proposal(json.dumps(_valid_obj(recommended_intervention=value)))


@pytest.mark.parametrize("bad_bool", [1, 0, "true", "false", None])
def test_human_review_recommended_rejects_non_boolean_truthiness(bad_bool):
    with pytest.raises(InvalidProposal):
        parse_proposal(json.dumps(_valid_obj(human_review_recommended=bad_bool)))


@pytest.mark.parametrize("intervention,hrr,reason", [
    ("NONE", True, None),                                    # must be false
    ("NONE", False, "some reason"),                          # reason must be null
    ("PAYMENT_PLAN_REVIEW", False, "some reason"),            # must be true
    ("PAYMENT_PLAN_REVIEW", True, None),                      # reason required
    ("PAYMENT_PLAN_REVIEW", True, "   "),                     # blank reason
    ("PAYMENT_PLAN_REVIEW", True, "x" * 301),                 # oversized reason
])
def test_every_invalid_advisory_combination_is_rejected(intervention, hrr, reason):
    with pytest.raises(InvalidProposal):
        parse_proposal(json.dumps(_valid_obj(
            recommended_intervention=intervention,
            human_review_recommended=hrr,
            human_review_reason=reason,
        )))


@pytest.mark.parametrize("reason", [
    "call http://example.com/pay",       # URL
    "the amount was ₹500 short",         # currency/amount marker
    "see reference plink_abc123",        # provider/payment identifier
    "case-18 had the same issue",        # case identifier
])
def test_parse_proposal_rejects_unsafe_human_review_reason_content(reason):
    """parse_proposal (the direct-Gemini repair boundary) rejects an unsafe
    reason itself - not only the engine's later, final check - so a bad first
    reply gets a real repair chance instead of surfacing only after the
    strategist already reported success."""
    with pytest.raises(InvalidProposal):
        parse_proposal(json.dumps(_valid_obj(
            recommended_intervention="PAYMENT_PLAN_REVIEW", human_review_recommended=True,
            human_review_reason=reason,
        )))


def test_unsafe_reason_enters_the_repair_path_and_is_fixed():
    """An unsafe first reply is exactly the shape the one-repair boundary
    exists for: propose() feeds the rejection back and accepts a corrected
    second reply - the unsafe reason never reaches the engine."""
    bad = _obj(recommended_intervention="PAYMENT_PLAN_REVIEW", human_review_recommended=True,
               human_review_reason="see reference plink_abc123")
    good = _obj(recommended_intervention="PAYMENT_PLAN_REVIEW", human_review_recommended=True,
                human_review_reason="a safe evidence-based reason")
    s, stub = strategist(bad, good)
    proposal = s.propose(snapshot())
    assert proposal.human_review_reason == "a safe evidence-based reason"
    assert len(stub.calls) == 2  # first + exactly one repair
    assert s.last_run_meta.repair_used is True


def test_unsafe_reason_unfixed_after_repair_never_escapes_to_the_engine():
    """When the repair reply is ALSO unsafe, propose() raises - the strategist
    never returns an unsafe proposal for the engine to see."""
    bad = _obj(recommended_intervention="PAYMENT_PLAN_REVIEW", human_review_recommended=True,
               human_review_reason="call http://example.com/pay")
    s, stub = strategist(bad, bad)
    with pytest.raises(InvalidProposal):
        s.propose(snapshot())
    assert len(stub.calls) == 2  # first + one repair, never more
    assert s.last_run_meta.validation_result.startswith("invalid:")


def test_engine_still_rejects_unsafe_reason_as_defense_in_depth():
    """engine._validate_proposal remains the canonical, final authority even
    though parse_proposal already checks this - a StrategyProposal built by
    ANY path (not only parse_proposal) must still be rejected."""
    from hermes.engine import _validate_proposal

    proposal = parse_proposal(json.dumps(_valid_obj(
        recommended_intervention="PAYMENT_PLAN_REVIEW", human_review_recommended=True,
        human_review_reason="a safe placeholder reason",
    )))
    unsafe = dataclasses.replace(proposal, human_review_reason="see reference plink_abc123")
    with pytest.raises(InvalidProposal):
        _validate_proposal(unsafe)


def test_advisory_never_changes_the_engine_authorization_path():
    """The advisory is evidence only - authorize() never even looks at it."""
    from hermes.engine import authorize
    from hermes.types import CaseSnapshot, ProviderRetryFact

    snap = CaseSnapshot(
        case_id="c1", obligation_id="sub_x", amount_minor=1_000_000, currency="INR",
        state="active", failure_reason="insufficient_funds", version=1,
        retry_outcome_recorded=True,
    )
    fact = ProviderRetryFact("sub_x", True, "provider_retry_signal")
    p_none = parse_proposal(json.dumps(_valid_obj(action="WAIT_FOR_PROVIDER_RETRY",
                                                  proposed_wait_hours=1)))
    p_review = parse_proposal(json.dumps(_valid_obj(
        action="WAIT_FOR_PROVIDER_RETRY", proposed_wait_hours=1,
        recommended_intervention="PAYMENT_PLAN_REVIEW", human_review_recommended=True,
        human_review_reason="evidence-based reason",
    )))
    d_none = authorize(p_none, snap, 10, fact)
    d_review = authorize(p_review, snap, 10, fact)
    assert d_none.outcome == d_review.outcome and d_none.reason_code == d_review.reason_code


# --- repair behaviour ---------------------------------------------------


def test_malformed_then_unfixed_raises_after_exactly_one_repair():
    s, stub = strategist("garbage", "still garbage")
    with pytest.raises(InvalidProposal):
        s.propose(snapshot())
    assert len(stub.calls) == 2  # first + exactly one repair
    assert "rejected" in stub.calls[1]["user"].lower()
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


@pytest.mark.parametrize("configured", [2, 5, 99])
def test_repair_budget_cannot_exceed_one(configured):
    # even asking for many repairs, an always-invalid model gets exactly one.
    s, stub = strategist("bad", "bad", "bad", "bad", max_repair_attempts=configured)
    with pytest.raises(InvalidProposal):
        s.propose(snapshot())
    assert len(stub.calls) == 2  # first + one repair, never more


# --- real wall-clock timeout ------------------------------------------


def test_call_exceeding_budget_raises_timeouterror():
    s, _ = strategist(VALID_JSON, sleep_s=0.30, timeout_s=0.05)
    with pytest.raises(TimeoutError):
        s.propose(snapshot())


def test_propose_returns_near_timeout_not_transport_completion():
    slow_s, budget_s = 1.5, 0.05
    s, _ = strategist(VALID_JSON, sleep_s=slow_s, timeout_s=budget_s)
    start = time.monotonic()
    with pytest.raises(TimeoutError):
        s.propose(snapshot())
    elapsed = time.monotonic() - start
    # tolerant: anything well under the transport's own duration proves we did
    # not wait for it to finish (expected ~budget_s; generous ceiling for CI).
    assert elapsed < 0.6, f"propose() waited {elapsed:.3f}s, near the {slow_s}s transport"


# --- failure metadata -------------------------------------------------


def test_initial_call_timeout_records_safe_metadata():
    s, _ = strategist(VALID_JSON, sleep_s=0.30, timeout_s=0.05)
    with pytest.raises(TimeoutError):
        s.propose(snapshot())
    meta = s.last_run_meta
    assert meta is not None
    assert meta.validation_result == "timeout"
    assert meta.repair_used is False
    assert meta.raw_response == "" and meta.usage is None
    assert meta.model == DEFAULT_MODEL and meta.prompt_version == PROMPT_VERSION
    assert meta.latency_ms >= 0.0


def test_initial_transport_failure_records_safe_metadata():
    # a synthetic marker standing in for anything sensitive an SDK/auth error
    # message might carry; it must not reach the recorded metadata.
    sensitive_marker = "boom-DO-NOT-LEAK-marker"
    s, stub = strategist(RuntimeError(sensitive_marker))
    with pytest.raises(RuntimeError):
        s.propose(snapshot())
    meta = s.last_run_meta
    assert meta.validation_result == "transport_error:RuntimeError"
    assert sensitive_marker not in meta.validation_result  # only the type name is kept
    assert sensitive_marker not in (meta.raw_response or "")
    assert meta.repair_used is False
    assert meta.raw_response == "" and meta.usage is None
    assert len(stub.calls) == 1


def test_repair_call_failure_records_metadata_with_first_reply_evidence():
    s, stub = strategist("garbage first reply", ConnectionError("network down"))
    with pytest.raises(ConnectionError):
        s.propose(snapshot())
    meta = s.last_run_meta
    assert meta.validation_result == "transport_error:ConnectionError"
    assert meta.repair_used is True  # repair had started
    assert meta.raw_response == "garbage first reply"  # available evidence retained
    assert meta.usage == {"prompt_tokens": 10, "output_tokens": 20, "total_tokens": 30}
    assert len(stub.calls) == 2


def test_repair_call_timeout_records_metadata():
    def slow():
        time.sleep(0.30)
        return VALID_JSON

    s, stub = strategist("garbage", slow, timeout_s=0.05)
    with pytest.raises(TimeoutError):
        s.propose(snapshot())
    meta = s.last_run_meta
    assert meta.validation_result == "timeout" and meta.repair_used is True
    assert meta.raw_response == "garbage"  # first reply kept as evidence


# --- isolation contract ---------------------------------------------


def test_isolation_profile_is_declared():
    p = ISOLATION_PROFILE
    assert p["fresh_instance_per_call"] is True
    assert p["skip_memory"] is True and p["skip_context_files"] is True
    assert p["enabled_toolsets"] == ()  # empty positive allowlist
    for off in ("curator", "skills_mutation", "delegation", "terminal", "file",
                "browser", "cron", "code_execution"):
        assert p[off] is False, off
    assert p["max_iterations"] == 3


# --- context minimisation -----------------------------------------


def test_prompt_context_excludes_identifiers_and_amounts():
    s, stub = strategist(VALID_JSON)
    s.propose(snapshot(obligation_id="sub_SECRET_9", case_id="case_SECRET_9",
                       amount_minor=987654))
    sent = stub.calls[0]["system"] + "\n" + stub.calls[0]["user"]
    for leak in ("sub_SECRET_9", "case_SECRET_9", "987654", "9876.54"):
        assert leak not in sent
    assert "insufficient_funds" in sent  # decision-relevant fact is present


# --- SDK independence / lazy import ------------------------------


def test_real_google_import_never_happens_on_the_stub_path(monkeypatch):
    real_import = builtins.__import__

    def guard(name, *args, **kwargs):
        if name == "google" or name.startswith("google."):
            raise AssertionError(f"lazy-import contract broken: imported {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)
    s, _ = strategist(VALID_JSON)
    assert s.propose(snapshot()).action is ProposalAction.CREATE_RECOVERY_LINK


def test_real_transport_build_requires_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    s = HermesStrategist()  # no transport_factory -> real path
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        s.propose(snapshot())
    # transport setup failure is audited too, not left as last_run_meta=None
    meta = s.last_run_meta
    assert meta is not None
    assert meta.validation_result == "transport_error:RuntimeError"
    assert meta.repair_used is False
    assert meta.raw_response == "" and meta.usage is None
    assert meta.model == DEFAULT_MODEL and meta.prompt_version == PROMPT_VERSION
    assert meta.latency_ms >= 0.0


def test_transport_factory_setup_failure_is_audited_and_redacted():
    marker = "sensitive-setup-marker-xyz"

    def boom_factory():
        raise RuntimeError(marker)

    s = HermesStrategist(transport_factory=boom_factory)
    with pytest.raises(RuntimeError, match=marker):  # original error still propagates
        s.propose(snapshot())
    meta = s.last_run_meta
    assert meta is not None  # not None despite failing before any model call
    assert meta.validation_result == "transport_error:RuntimeError"
    assert meta.repair_used is False
    assert meta.raw_response == "" and meta.usage is None
    assert meta.model == DEFAULT_MODEL and meta.prompt_version == PROMPT_VERSION
    assert meta.latency_ms >= 0.0
    # the sensitive marker is in neither recorded field
    assert marker not in meta.validation_result
    assert marker not in (meta.raw_response or "")


def test_setup_failure_does_not_leak_prior_run_metadata():
    good = StubTransport(VALID_JSON)
    n = {"calls": 0}

    def flaky_factory():
        n["calls"] += 1
        if n["calls"] == 1:
            return good
        raise RuntimeError("second setup boom")

    s = HermesStrategist(transport_factory=flaky_factory)
    s.propose(snapshot())
    assert s.last_run_meta.validation_result == "valid"  # first run ok

    with pytest.raises(RuntimeError):
        s.propose(snapshot())  # second run fails during transport construction
    assert s.last_run_meta.validation_result == "transport_error:RuntimeError"  # not stale "valid"
    assert s.last_run_meta.repair_used is False


# --- prompt <-> validation contract alignment (correction 3) ---------


def _obj(**over):
    o = {"action": "CREATE_RECOVERY_LINK", "diagnosis": "d", "rationale": "r",
         "confidence": 0.6, "proposed_wait_hours": 0,
         "recommended_intervention": "NONE", "human_review_recommended": False,
         "human_review_reason": None, "message_intent": None}
    o.update(over)
    return json.dumps(o)


def test_approved_message_proposal_reaches_policy():
    s, stub = strategist(_obj(message_intent=APPROVED_MSG))
    proposal = s.propose(snapshot(retry_outcome_recorded=True))
    assert proposal.message_intent == APPROVED_MSG
    assert len(stub.calls) == 1  # no repair needed
    from hermes.engine import _validate_proposal  # final deterministic guard

    _validate_proposal(proposal)  # must not raise


def test_unapproved_message_gets_exactly_one_repair_then_succeeds():
    s, stub = strategist(_obj(message_intent="totally made up casual copy"),
                         _obj(message_intent=APPROVED_MSG))
    proposal = s.propose(snapshot())
    assert proposal.message_intent == APPROVED_MSG
    assert len(stub.calls) == 2  # first + exactly one repair
    assert "approved" in stub.calls[1]["user"].lower() or "rejected" in stub.calls[1]["user"].lower()
    assert s.last_run_meta.repair_used is True


def test_repeated_unapproved_message_follows_the_safe_failure_path():
    bad = _obj(message_intent="still not on the list")
    s, stub = strategist(bad, bad)
    with pytest.raises(InvalidProposal):
        s.propose(snapshot())
    assert len(stub.calls) == 2  # first + one repair, never more
    assert s.last_run_meta.validation_result.startswith("invalid:")


def test_zero_hour_wait_is_invalid_output_not_rewritten():
    s, stub = strategist(_obj(action="WAIT_FOR_PROVIDER_RETRY", proposed_wait_hours=0),
                         _obj(action="WAIT_FOR_PROVIDER_RETRY", proposed_wait_hours=0))
    with pytest.raises(InvalidProposal):
        s.propose(snapshot())
    assert len(stub.calls) == 2  # bounded: first + one repair


def test_positive_wait_within_remaining_is_accepted():
    s, stub = strategist(_obj(action="WAIT_FOR_PROVIDER_RETRY", proposed_wait_hours=24))
    p = s.propose(snapshot(wait_hours_remaining=48))
    assert p.action.value == "WAIT_FOR_PROVIDER_RETRY" and p.proposed_wait_hours == 24


def test_wait_budget_and_approved_list_are_in_the_model_context():
    s, stub = strategist(_obj(message_intent=APPROVED_MSG))
    s.propose(snapshot(wait_hours_remaining=17))
    system, user = stub.calls[0]["system"], stub.calls[0]["user"]
    assert "wait_hours_remaining" in user and "17" in user
    assert APPROVED_MSG in system  # Gemini is shown the exact approved strings


# --- guardrail ----------------------------------------------


def test_not_wired_into_default_engine():
    engine_src = (
        pathlib.Path(__file__).parent.parent / "src" / "hermes" / "engine.py"
    ).read_text()
    assert "HermesStrategist" not in engine_src
    assert "hermes_strategist" not in engine_src
