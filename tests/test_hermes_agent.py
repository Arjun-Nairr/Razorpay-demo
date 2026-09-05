"""Offline harness for the ISOLATED REAL Nous Hermes integration.

Every ``@requires_runtime`` test spawns the actual
``hermes.hermes_agent.child_main`` with the installed Hermes interpreter
(``run_agent.AIAgent`` + its real tool loop), against a local
OpenAI-compatible **stub transport** - no live Gemini, no network beyond
loopback, no DB, no credentials. Skips (not fails) when the installed runtime
is absent or not the proven revision.

The parent-shape tests need no runtime: they drive ``HermesAgentStrategist``
with a fake ``subprocess.run``.
"""

from __future__ import annotations

import json
import ssl
import subprocess
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from hermes.hermes_agent import EXPECTED_HERMES_REVISION
from hermes import hermes_agent_strategist as mod
from hermes.hermes_agent_strategist import (
    _DEFAULT_CHECKOUT,
    _DEFAULT_PYTHON,
    HermesAgentStrategist,
    HermesRuntimeUnavailable,
)
from hermes.message_templates import APPROVED_MESSAGE_INTENT_LIST
from hermes.types import InvalidProposal, ProposalAction, StrategySnapshot

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")
SECRET = "SEKRIT_MARKER_do_not_leak_9f3a"
_APPROVED_MSG = APPROVED_MESSAGE_INTENT_LIST[0]


def _runtime_ready() -> bool:
    if not _DEFAULT_PYTHON.exists() or not (_DEFAULT_CHECKOUT / "run_agent.py").exists():
        return False
    try:
        head = subprocess.run(["git", "-C", str(_DEFAULT_CHECKOUT), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception:
        return False
    return head == EXPECTED_HERMES_REVISION


requires_runtime = pytest.mark.skipif(
    not _runtime_ready(),
    reason=f"isolated Hermes runtime absent or != {EXPECTED_HERMES_REVISION[:12]}",
)


# --- OpenAI-compatible stub transport --------------------------------------


class _Stub(BaseHTTPRequestHandler):
    queue: list = []
    seen_tool_results: list = []

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n).decode())
        if not req.get("messages"):  # prewarm/health probe - never consumes a turn
            self._send_json(_text("ok"))
            return
        for m in req.get("messages", []):
            if m.get("role") == "tool":
                type(self).seen_tool_results.append(m.get("content", ""))
        resp = type(self).queue.pop(0) if type(self).queue else _text(
            '{"action":"ESCALATE","diagnosis":"d","rationale":"fallback","confidence":0.2,'
            '"proposed_wait_hours":0,"recommended_intervention":"NONE",'
            '"human_review_recommended":false,"human_review_reason":null,'
            '"message_intent":null}')
        msg = resp["choices"][0]["message"]
        if req.get("stream") is True:
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
            chunks = [{"id": "m", "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]}]
            if msg.get("content"):
                chunks.append({"id": "m", "choices": [{"index": 0, "delta": {"content": msg["content"]}, "finish_reason": None}]})
            for ti, tc in enumerate(msg.get("tool_calls") or []):
                chunks.append({"id": "m", "choices": [{"index": 0, "delta": {"tool_calls": [{
                    "index": ti, "id": tc["id"], "type": "function",
                    "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]}}]}, "finish_reason": None}]})
            chunks.append({"id": "m", "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if msg.get("tool_calls") else "stop"}]})
            for c in chunks:
                self.wfile.write(f"data: {json.dumps(c)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n"); self.wfile.flush()
        else:
            self._send_json(resp)

    def _send_json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def _tc(name, args="{}"):
    return {"id": "m", "choices": [{"index": 0, "message": {"role": "assistant", "content": "",
            "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": name, "arguments": args}}]},
            "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 12, "completion_tokens": 0, "total_tokens": 12}}


def _text(t):
    return {"id": "m", "choices": [{"index": 0, "message": {"role": "assistant", "content": t}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}}


_VALID = ('{"action":"WAIT_FOR_PROVIDER_RETRY","diagnosis":"insufficient funds, retry eligible",'
          '"rationale":"one provider retry may still clear","confidence":0.62,'
          '"proposed_wait_hours":24,"recommended_intervention":"NONE",'
          '"human_review_recommended":false,"human_review_reason":null,'
          '"message_intent":null}')


@pytest.fixture()
def stub():
    _Stub.queue = []
    _Stub.seen_tool_results = []
    srv = HTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, _Stub
    srv.shutdown()


def _snap(**kw) -> StrategySnapshot:
    base = dict(
        case_id="case-1", obligation_id="sub_demo_0001_abcd", amount_minor=1_000_000,
        currency="INR", failure_reason="insufficient_funds", state="active",
        provider_retry_eligible=True, provider_retry_evidence="provider_retry_signal",
        retry_outcome_recorded=False, wait_hours_remaining=72, messages_remaining=2,
        links_remaining=1, actions_remaining=3, is_demo_case=True,
        case_history=({"t": 0, "kind": "AI_PROPOSAL", "action": "WAIT_FOR_PROVIDER_RETRY"},
                      {"t": 0, "kind": "POLICY_DECISION", "outcome": "ALLOW",
                       "reason_code": "provider_retry_permitted"}),
    )
    base.update(kw)
    return StrategySnapshot(**base)


def _strat(stub, tmp_path, **kw) -> HermesAgentStrategist:
    srv, _ = stub
    port = srv.server_address[1]
    return HermesAgentStrategist(
        mock_base_url=f"http://127.0.0.1:{port}/v1", home=tmp_path / "home",
        deadline_s=kw.pop("deadline_s", 60), **kw,
    )


# === real-runtime harness ================================================


@requires_runtime
def test_real_agent_tool_loop_returns_a_validated_proposal(stub, tmp_path):
    _, S = stub
    S.queue = [_tc("get_payment_retry_facts", "{}"), _text(_VALID)]
    strat = _strat(stub, tmp_path)
    p = strat.propose(_snap())
    assert p.action is ProposalAction.WAIT_FOR_PROVIDER_RETRY
    assert p.proposed_wait_hours == 24 and 0.0 <= p.confidence <= 1.0
    meta = strat.last_run_meta
    assert meta.validation_result == "valid" and meta.repair_used is False
    ex = meta.extra
    assert ex["runtime_revision"] == EXPECTED_HERMES_REVISION
    assert ex["confidence_band"] == "medium" and ex["decision_action"] == "WAIT_FOR_PROVIDER_RETRY"
    assert ex["child_exit_code"] == 0
    assert any(e["tool"] == "get_payment_retry_facts" for e in ex["evidence_returned"])
    assert ex["tool_calls_used"] >= 1
    assert "stderr_tail" not in ex and "unresolved_uncertainty" not in ex


@requires_runtime
def test_success_returns_promptly_not_near_the_deadline(stub, tmp_path):
    _, S = stub
    S.queue = [_text(_VALID)]
    strat = _strat(stub, tmp_path, deadline_s=60)
    p = strat.propose(_snap())
    assert p.action is ProposalAction.WAIT_FOR_PROVIDER_RETRY
    # The daemon watchdog fires at deadline-4 == 56s; a clean success must not
    # wait for it. Generous ceiling for a cold Hermes import.
    assert strat.last_run_meta.extra["duration_ms"] < 40_000


@requires_runtime
def test_no_extra_lookup_path_is_legitimate(stub, tmp_path):
    _, S = stub
    S.queue = [_text(_VALID)]
    strat = _strat(stub, tmp_path)
    p = strat.propose(_snap())
    assert p.action is ProposalAction.WAIT_FOR_PROVIDER_RETRY
    assert strat.last_run_meta.extra["tool_calls_used"] == 0


@requires_runtime
def test_recovery_actions_returns_this_cases_prior_activity(stub, tmp_path):
    _, S = stub
    S.queue = [_tc("get_recovery_actions", "{}"), _text(_VALID)]
    strat = _strat(stub, tmp_path)
    strat.propose(_snap())
    got = json.loads([r for r in S.seen_tool_results if "prior_case_activity" in r][0])
    kinds = [e["kind"] for e in got["prior_case_activity"]["events"]]
    assert "AI_PROPOSAL" in kinds and "POLICY_DECISION" in kinds
    cat = got["allowed_actions_catalog"]["actions"]
    assert any("ESCALATE" in a for a in cat) and not any(a.strip().startswith("STOP") for a in cat)


@requires_runtime
def test_single_twelve_month_expansion_only(stub, tmp_path):
    _, S = stub
    S.queue = [
        _tc("get_payment_history", '{"reason": "is this a chronic late payer over a year?"}'),
        _tc("get_payment_history", '{"reason": "look again, different angle please"}'),  # 2nd -> rejected
        _text(_VALID),
    ]
    strat = _strat(stub, tmp_path)
    strat.propose(_snap())
    joined = " ".join(S.seen_tool_results)
    assert "single_expansion_only" in joined
    first = json.loads([r for r in S.seen_tool_results if '"actual_coverage_months": 12' in r][0])
    assert first["records"] == list(mod._SYNTHETIC_HISTORY_12M)
    reqs = strat.last_run_meta.extra["evidence_requests"]
    hist = [r for r in reqs if r["tool"] == "get_payment_history"]
    assert len(hist) == 2 and all(r.get("reason") for r in hist)  # both attempts recorded


@requires_runtime
def test_history_reason_is_required(stub, tmp_path):
    _, S = stub
    S.queue = [_tc("get_payment_history", '{"reason": "no"}'), _text(_VALID)]  # too short
    strat = _strat(stub, tmp_path)
    strat.propose(_snap())
    assert "reason_required" in " ".join(S.seen_tool_results)


@requires_runtime
def test_history_partial_coverage_is_reported_not_padded(stub, tmp_path):
    _, S = stub
    S.queue = [_tc("get_payment_history", '{"reason": "how far back do records really go?"}'), _text(_VALID)]
    strat = _strat(stub, tmp_path, history_months_available=8)
    strat.propose(_snap())
    got = json.loads([r for r in S.seen_tool_results if "actual_coverage_months" in r][0])
    assert got["actual_coverage_months"] == 8 and got["partial"] is True
    assert len(got["records"]) == 8


@requires_runtime
def test_history_unavailable_is_not_invented(stub, tmp_path):
    _, S = stub
    S.queue = [_tc("get_payment_history", '{"reason": "history depth for this customer"}'), _text(_VALID)]
    strat = _strat(stub, tmp_path, history_available=False)
    strat.propose(_snap())
    got = json.loads([r for r in S.seen_tool_results if "available" in r][0])
    assert got["available"] is False and "not invented" in got["note"]


@requires_runtime
def test_unknown_case_inherits_no_synthetic_records(stub, tmp_path):
    _, S = stub
    S.queue = [_tc("get_payment_history", '{"reason": "does this customer have any history?"}'),
               _text(_VALID)]
    strat = _strat(stub, tmp_path)
    strat.propose(_snap(is_demo_case=False))
    hist = json.loads([r for r in S.seen_tool_results if "actual_coverage_months" in r][0])
    assert hist["available"] is False and hist["actual_coverage_months"] == 0


def test_evidence_bundle_gates_synthetic_history_on_demo_provenance():
    demo = _snap(is_demo_case=True)
    unknown = _snap(is_demo_case=False)
    b_demo = mod._evidence_bundle(demo)
    b_unknown = mod._evidence_bundle(unknown)
    assert b_demo["history_12m"]["available"] is True
    assert len(b_demo["initial_context"]["payment_history_3m"]["records"]) == 3
    assert b_unknown["history_12m"]["available"] is False
    assert b_unknown["initial_context"]["payment_history_3m"].get("available") is False
    assert "records" not in b_unknown["initial_context"]["payment_history_3m"]
    # day-delta-derived outcome labels never disagree with the dates
    for row in mod._SYNTHETIC_HISTORY_12M:
        if row["paid"]:
            d = (mod.date.fromisoformat(row["paid"]) - mod.date.fromisoformat(row["due"])).days
            assert (d <= 0) == (row["outcome"] == "paid_on_time")


def test_evidence_bundle_partial_history_reports_actual_months():
    b = mod._evidence_bundle(_snap(is_demo_case=True), history_months_available=8)
    assert b["history_12m"]["coverage_months"] == 8
    assert len(b["history_12m"]["rows"]) == 8


@requires_runtime
def test_unauthorized_tool_call_is_rejected(stub, tmp_path):
    _, S = stub
    canary = tmp_path / "TERMINAL_BREACH_CANARY.txt"
    S.queue = [_tc("terminal", json.dumps({"cmd": f'echo breach > "{canary}"'})),
               _tc("get_secret", "{}"), _text(_VALID)]
    strat = _strat(stub, tmp_path)
    p = strat.propose(_snap())
    assert p.action is ProposalAction.WAIT_FOR_PROVIDER_RETRY
    assert not canary.exists(), "ISOLATION BREACH: `terminal` actually executed"
    assert "does not exist" in " ".join(S.seen_tool_results)
    assert all(e["tool"] in {"get_payment_retry_facts", "get_payment_history", "get_recovery_actions"}
               for e in strat.last_run_meta.extra["evidence_returned"])


@requires_runtime
def test_forged_case_id_argument_is_ignored(stub, tmp_path):
    _, S = stub
    S.queue = [_tc("get_payment_retry_facts", '{"case_id": "sub_victim_9999", "sql": "DROP TABLE"}'), _text(_VALID)]
    strat = _strat(stub, tmp_path)
    strat.propose(_snap(provider_retry_eligible=True))
    facts = json.loads([r for r in S.seen_tool_results if "provider_retry_eligible" in r][0])
    assert facts["provider_retry_eligible"] is True and facts["source"] == "SIMULATED_PROVIDER"
    assert "sub_victim_9999" not in json.dumps(facts)


@requires_runtime
def test_invalid_output_gets_one_repair_then_succeeds(stub, tmp_path):
    _, S = stub
    S.queue = [_text("here is my answer: wait a day"), _text(_VALID)]
    strat = _strat(stub, tmp_path)
    p = strat.propose(_snap())
    assert p.action is ProposalAction.WAIT_FOR_PROVIDER_RETRY
    assert strat.last_run_meta.repair_used is True
    assert strat.last_run_meta.validation_result == "repaired"


@requires_runtime
@pytest.mark.parametrize("bad", [
    '{"action":"WAIT_FOR_PROVIDER_RETRY","diagnosis":"d","rationale":"r","confidence":true,"proposed_wait_hours":24,"message_intent":null}',
    '{"action":"WAIT_FOR_PROVIDER_RETRY","diagnosis":"d","rationale":"r","confidence":0.6,"proposed_wait_hours":0,"message_intent":null}',
    '{"action":"WAIT_FOR_PROVIDER_RETRY","diagnosis":"d","rationale":"r","confidence":0.6,"proposed_wait_hours":24,"message_intent":"buy now, 50% off, click http://x"}',
    '{"action":"WAIT_FOR_PROVIDER_RETRY","diagnosis":"d","rationale":"r","confidence":0.6,"proposed_wait_hours":24,"message_intent":null,"extra":1}',
    '{"action":"STOP","diagnosis":"d","rationale":"r","confidence":0.6,"proposed_wait_hours":0,"message_intent":null}',
    'sure! {"action":"WAIT_FOR_PROVIDER_RETRY","diagnosis":"d","rationale":"r","confidence":0.6,"proposed_wait_hours":24,"message_intent":null}',
])
def test_strict_contract_rejections_then_repair_exhaustion(stub, tmp_path, bad):
    _, S = stub
    S.queue = [_text(bad), _text(bad)]  # invalid + repair still invalid -> bounded failure
    strat = _strat(stub, tmp_path)
    with pytest.raises(InvalidProposal):
        strat.propose(_snap())
    ex = strat.last_run_meta.extra
    assert ex["failure_category"] in ("schema_invalid_after_repair", "model_iteration_budget_exhausted")
    assert strat.last_run_meta.validation_result.startswith("invalid:")


@requires_runtime
def test_unapproved_message_then_approved_repair_succeeds(stub, tmp_path):
    _, S = stub
    bad = ('{"action":"CREATE_RECOVERY_LINK","diagnosis":"retry failed","rationale":"link now",'
           '"confidence":0.6,"proposed_wait_hours":0,"message_intent":"totally made up copy"}')
    good = ('{"action":"CREATE_RECOVERY_LINK","diagnosis":"retry failed","rationale":"link now",'
            '"confidence":0.6,"proposed_wait_hours":0,"recommended_intervention":"NONE",'
            '"human_review_recommended":false,"human_review_reason":null,'
            f'"message_intent":{json.dumps(_APPROVED_MSG)}}}')
    S.queue = [_text(bad), _text(good)]
    strat = _strat(stub, tmp_path)
    p = strat.propose(_snap(retry_outcome_recorded=True))
    assert p.action is ProposalAction.CREATE_RECOVERY_LINK
    assert p.message_intent == _APPROVED_MSG


@requires_runtime
def test_unsafe_human_review_reason_enters_the_repair_path_and_is_fixed(stub, tmp_path):
    """The isolated Hermes child's own validator (not only engine
    ._validate_proposal) rejects an unsafe human_review_reason - a bad first
    reply gets the SAME one-repair chance any other schema violation does,
    and never escapes as a successful proposal."""
    _, S = stub
    bad = ('{"action":"WAIT_FOR_PROVIDER_RETRY","diagnosis":"d","rationale":"r",'
           '"confidence":0.6,"proposed_wait_hours":24,'
           '"recommended_intervention":"HUMAN_FOLLOW_UP","human_review_recommended":true,'
           '"human_review_reason":"see reference plink_abc123","message_intent":null}')
    good = ('{"action":"WAIT_FOR_PROVIDER_RETRY","diagnosis":"d","rationale":"r",'
            '"confidence":0.6,"proposed_wait_hours":24,'
            '"recommended_intervention":"HUMAN_FOLLOW_UP","human_review_recommended":true,'
            '"human_review_reason":"a safe evidence-based reason","message_intent":null}')
    S.queue = [_text(bad), _text(good)]
    strat = _strat(stub, tmp_path)
    p = strat.propose(_snap())
    assert p.human_review_reason == "a safe evidence-based reason"
    assert strat.last_run_meta.repair_used is True
    assert strat.last_run_meta.validation_result == "repaired"


@requires_runtime
def test_unsafe_human_review_reason_unfixed_never_returns_a_proposal(stub, tmp_path):
    _, S = stub
    bad = ('{"action":"WAIT_FOR_PROVIDER_RETRY","diagnosis":"d","rationale":"r",'
           '"confidence":0.6,"proposed_wait_hours":24,'
           '"recommended_intervention":"HUMAN_FOLLOW_UP","human_review_recommended":true,'
           '"human_review_reason":"call http://example.com/pay","message_intent":null}')
    S.queue = [_text(bad), _text(bad)]
    strat = _strat(stub, tmp_path)
    with pytest.raises(InvalidProposal):
        strat.propose(_snap())
    assert strat.last_run_meta.extra["failure_category"] == "schema_invalid_after_repair"
    assert strat.last_run_meta.repair_used is True


@requires_runtime
def test_synthetic_secret_in_model_output_never_leaks(stub, tmp_path, capsys):
    _, S = stub
    poison = f"my reasoning: {SECRET} ... not json"
    S.queue = [_text(poison), _text(poison)]
    strat = _strat(stub, tmp_path)
    with pytest.raises(InvalidProposal):
        strat.propose(_snap())
    blob = json.dumps(strat.last_run_meta.extra) + capsys.readouterr().out + capsys.readouterr().err
    assert SECRET not in blob


@requires_runtime
def test_single_decision_in_flight(stub, tmp_path):
    _, S = stub
    S.queue = [_text(_VALID)]
    strat = _strat(stub, tmp_path)
    strat._one_in_flight.acquire()
    try:
        with pytest.raises(TimeoutError):
            strat.propose(_snap())
    finally:
        strat._one_in_flight.release()


@requires_runtime
def test_subprocess_deadline_terminates_and_reaps_child(stub, tmp_path):
    _, S = stub
    S.queue = [_text(_VALID)]
    strat = _strat(stub, tmp_path, deadline_s=0.5)
    with pytest.raises(TimeoutError):
        strat.propose(_snap())
    assert strat.last_run_meta.extra["failure_category"] == "subprocess_deadline"


# === parent-shape tests (no runtime) ====================================


def _fake_proc(stdout: str, rc: int):
    return types.SimpleNamespace(stdout=stdout, stderr="", returncode=rc)


def _parent_only(monkeypatch, tmp_path, stdout: str, rc: int) -> HermesAgentStrategist:
    """A strategist whose subprocess is faked - exercises parent logic only,
    with no dependency on the installed runtime."""
    fake_checkout = tmp_path / "checkout"
    fake_checkout.mkdir()
    (fake_checkout / "run_agent.py").write_text("# fake\n", encoding="utf-8")
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: _fake_proc(stdout, rc))
    return HermesAgentStrategist(
        mock_base_url="http://127.0.0.1:1/v1", home=tmp_path / "h",
        checkout=fake_checkout, python=__import__("sys").executable,
        verify_revision=False,
    )


_SENTINEL = mod.RESULT_SENTINEL


def test_success_payload_with_abnormal_exit_is_rejected(monkeypatch, tmp_path):
    ok_payload = _SENTINEL + json.dumps({
        "ok": True,
        "proposal": {"action": "WAIT_FOR_PROVIDER_RETRY", "diagnosis": "d", "rationale": "r",
                     "confidence": 0.6, "proposed_wait_hours": 24, "message_intent": None},
        "audit": {"validation_result": "valid"},
    })
    s = _parent_only(monkeypatch, tmp_path, ok_payload, rc=3)  # abnormal exit code
    with pytest.raises(InvalidProposal):
        s.propose(_snap())
    assert s.last_run_meta.extra["failure_category"] == "abnormal_child_exit"
    assert s.last_run_meta.extra["child_exit_code"] == 3


def test_child_failure_audit_is_allowlisted_and_secret_free(monkeypatch, tmp_path):
    payload = _SENTINEL + json.dumps({
        "ok": False,
        "audit": {"failure_category": "schema_invalid_after_repair",
                  "validation_result": "invalid:not_json",
                  "stderr_tail": f"boom {SECRET}", "raw_response": SECRET,
                  "secret_env": SECRET},
    })
    s = _parent_only(monkeypatch, tmp_path, payload, rc=1)
    with pytest.raises(InvalidProposal):
        s.propose(_snap())
    ex = s.last_run_meta.extra
    assert "stderr_tail" not in ex and "raw_response" not in ex and "secret_env" not in ex
    assert SECRET not in json.dumps(ex)
    assert ex["failure_category"] == "schema_invalid_after_repair"


def test_no_result_line_is_a_bounded_failure(monkeypatch, tmp_path):
    s = _parent_only(monkeypatch, tmp_path, "garbage on stdout, no sentinel", rc=1)
    with pytest.raises(InvalidProposal):
        s.propose(_snap())
    assert s.last_run_meta.extra["failure_category"] == "no_result_line"


def test_wrong_revision_refuses_to_launch(tmp_path):
    with pytest.raises(HermesRuntimeUnavailable):
        HermesAgentStrategist(home=tmp_path / "h", verify_revision=True, checkout=tmp_path)


# === SOUL wiring (offline, no runtime) ===================================


def _fake_checkout(tmp_path) -> Path:
    fake_checkout = tmp_path / "checkout"
    fake_checkout.mkdir()
    (fake_checkout / "run_agent.py").write_text("# fake\n", encoding="utf-8")
    return fake_checkout


def test_missing_soul_file_fails_closed(tmp_path):
    with pytest.raises(HermesRuntimeUnavailable, match="soul"):
        HermesAgentStrategist(
            home=tmp_path / "h", checkout=_fake_checkout(tmp_path), verify_revision=False,
            soul_path=tmp_path / "no_such_soul.md",
        )


def test_missing_skill_file_fails_closed(tmp_path):
    with pytest.raises(HermesRuntimeUnavailable, match="skill"):
        HermesAgentStrategist(
            home=tmp_path / "h", checkout=_fake_checkout(tmp_path), verify_revision=False,
            skill_path=tmp_path / "no_such_skill.md",
        )


def test_soul_and_skill_reach_child_job_as_distinct_exact_fields(monkeypatch, tmp_path):
    """Prove the parent sends the real SOUL.md and SKILL.md contents verbatim,
    as two distinct job keys - never concatenated on the parent side."""
    from hermes.hermes_agent_strategist import _SKILL_PATH, _SOUL_PATH

    captured = {}

    def _fake_run(*args, **kwargs):
        captured["job"] = json.loads(kwargs["input"])
        return _fake_proc(_SENTINEL + json.dumps({
            "ok": True,
            "proposal": {"action": "ESCALATE", "diagnosis": "d", "rationale": "r",
                         "confidence": 0.3, "proposed_wait_hours": 0,
                         "recommended_intervention": "NONE",
                         "human_review_recommended": False, "human_review_reason": None,
                         "message_intent": None},
            "audit": {"validation_result": "valid"},
        }), rc=0)

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    strat = HermesAgentStrategist(
        mock_base_url="http://127.0.0.1:1/v1", home=tmp_path / "h",
        checkout=_fake_checkout(tmp_path), python=__import__("sys").executable,
        verify_revision=False,
    )
    strat.propose(_snap())
    job = captured["job"]
    assert job["soul_text"] == _SOUL_PATH.read_text(encoding="utf-8")
    assert job["skill_text"] == _SKILL_PATH.read_text(encoding="utf-8")
    assert job["soul_text"] != job["skill_text"]


def test_system_prompt_orders_soul_before_skill_before_case_context():
    """Prove the exact order the child builds the system prompt in: SOUL
    identity/scope, then SKILL judgment rules, then case context, then tool
    descriptions, then the output contract."""
    from hermes.hermes_agent import child_main

    prompt = child_main._system_prompt(
        "SOUL-MARKER-IDENTITY", "SKILL-MARKER-JUDGMENT",
        {"case_marker": "CASE-CONTEXT-MARKER"}, [_APPROVED_MSG],
    )
    i_soul = prompt.index("SOUL-MARKER-IDENTITY")
    i_skill = prompt.index("SKILL-MARKER-JUDGMENT")
    i_case = prompt.index("CASE-CONTEXT-MARKER")
    i_tools = prompt.index("Tools you may call")
    i_contract = prompt.index("Return EXACTLY one JSON object")
    assert i_soul < i_skill < i_case < i_tools < i_contract


# === child_main._validate: typed advisory contract (offline, no runtime) ===


def _child_obj(**over) -> dict:
    o = {
        "action": "WAIT_FOR_PROVIDER_RETRY", "diagnosis": "d", "rationale": "r",
        "confidence": 0.5, "proposed_wait_hours": 24,
        "recommended_intervention": "NONE", "human_review_recommended": False,
        "human_review_reason": None, "message_intent": None,
    }
    o.update(over)
    return o


def test_child_validate_accepts_every_valid_advisory_enum():
    from hermes.hermes_agent import child_main

    for value in ("NONE", "UPDATE_PAYMENT_METHOD", "MANDATE_REAUTH_REVIEW",
                  "PAYMENT_PLAN_REVIEW", "BILLING_SUPPORT_REVIEW", "HUMAN_FOLLOW_UP"):
        over = {"recommended_intervention": value}
        if value in ("NONE", "UPDATE_PAYMENT_METHOD"):
            over.update(human_review_recommended=False, human_review_reason=None)
        else:
            over.update(human_review_recommended=True, human_review_reason="a reason")
        obj, verdict = child_main._validate(_child_obj(**over), set())
        assert verdict == "valid", value


def test_child_validate_rejects_unknown_advisory():
    from hermes.hermes_agent import child_main

    obj, verdict = child_main._validate(
        _child_obj(recommended_intervention="OFFER_DISCOUNT"), set()
    )
    assert obj is None and verdict == "unknown_intervention"


@pytest.mark.parametrize("bad_bool", [1, 0, "true", None])
def test_child_validate_rejects_non_boolean_human_review_recommended(bad_bool):
    from hermes.hermes_agent import child_main

    obj, verdict = child_main._validate(
        _child_obj(human_review_recommended=bad_bool), set()
    )
    assert obj is None and verdict == "human_review_type"


@pytest.mark.parametrize("reason", ["", "   ", "x" * 301])
def test_child_validate_rejects_blank_or_oversized_reason(reason):
    from hermes.hermes_agent import child_main

    obj, verdict = child_main._validate(
        _child_obj(recommended_intervention="HUMAN_FOLLOW_UP",
                   human_review_recommended=True, human_review_reason=reason),
        set(),
    )
    assert obj is None and verdict == "human_review_reason_invalid"


@pytest.mark.parametrize("reason", [
    "call http://example.com/pay",       # URL
    "the amount was ₹500 short",         # currency/amount marker
    "see reference plink_abc123",        # provider/payment identifier
    "customer cus_9f8a raised a dispute", # customer identifier
    "case-18 had the same issue",         # case identifier
])
def test_child_validate_rejects_unsafe_reason_content(reason):
    """The isolated Hermes child's own validator - not only the engine's
    canonical _validate_proposal - rejects a reason containing a URL,
    currency/amount marker, or payment/provider/customer/case identifier."""
    from hermes.hermes_agent import child_main

    obj, verdict = child_main._validate(
        _child_obj(recommended_intervention="HUMAN_FOLLOW_UP",
                   human_review_recommended=True, human_review_reason=reason),
        set(),
    )
    assert obj is None and verdict == "human_review_reason_unsafe"


@pytest.mark.parametrize("intervention,hrr,reason", [
    ("NONE", True, None),
    ("NONE", False, "unexpected reason"),
    ("MANDATE_REAUTH_REVIEW", False, "a reason"),
    ("MANDATE_REAUTH_REVIEW", True, None),
])
def test_child_validate_rejects_every_invalid_combination(intervention, hrr, reason):
    from hermes.hermes_agent import child_main

    obj, verdict = child_main._validate(
        _child_obj(recommended_intervention=intervention,
                   human_review_recommended=hrr, human_review_reason=reason),
        set(),
    )
    assert obj is None and verdict == "human_review_mismatch"


def test_invalid_utf8_soul_fails_closed(tmp_path):
    bad_soul = tmp_path / "soul_bad.md"
    bad_soul.write_bytes(b"\xff\xfe not valid utf-8")
    good_skill = tmp_path / "skill.md"
    good_skill.write_text("skill", encoding="utf-8")
    with pytest.raises(HermesRuntimeUnavailable, match="soul"):
        HermesAgentStrategist(
            home=tmp_path / "h", checkout=_fake_checkout(tmp_path), verify_revision=False,
            soul_path=bad_soul, skill_path=good_skill,
        )


def test_invalid_utf8_skill_fails_closed(tmp_path):
    good_soul = tmp_path / "soul.md"
    good_soul.write_text("soul", encoding="utf-8")
    bad_skill = tmp_path / "skill_bad.md"
    bad_skill.write_bytes(b"\xff\xfe not valid utf-8")
    with pytest.raises(HermesRuntimeUnavailable, match="skill"):
        HermesAgentStrategist(
            home=tmp_path / "h", checkout=_fake_checkout(tmp_path), verify_revision=False,
            soul_path=good_soul, skill_path=bad_skill,
        )


@pytest.mark.parametrize("blank", ["", "   ", "\n\n\t  \n"])
def test_blank_soul_file_fails_closed(tmp_path, blank):
    blank_soul = tmp_path / "soul_blank.md"
    blank_soul.write_text(blank, encoding="utf-8")
    good_skill = tmp_path / "skill.md"
    good_skill.write_text("skill", encoding="utf-8")
    with pytest.raises(HermesRuntimeUnavailable, match="soul"):
        HermesAgentStrategist(
            home=tmp_path / "h", checkout=_fake_checkout(tmp_path), verify_revision=False,
            soul_path=blank_soul, skill_path=good_skill,
        )


@pytest.mark.parametrize("blank", ["", "   ", "\n\n\t  \n"])
def test_blank_skill_file_fails_closed(tmp_path, blank):
    good_soul = tmp_path / "soul.md"
    good_soul.write_text("soul", encoding="utf-8")
    blank_skill = tmp_path / "skill_blank.md"
    blank_skill.write_text(blank, encoding="utf-8")
    with pytest.raises(HermesRuntimeUnavailable, match="skill"):
        HermesAgentStrategist(
            home=tmp_path / "h", checkout=_fake_checkout(tmp_path), verify_revision=False,
            soul_path=good_soul, skill_path=blank_skill,
        )


def test_stale_run_meta_not_leaked_after_instruction_load_failure(monkeypatch, tmp_path):
    """A successful decision followed by a removed instruction file must not
    leave the previous successful run's metadata on the new failure."""
    soul_path = tmp_path / "soul.md"
    skill_path = tmp_path / "skill.md"
    soul_path.write_text("soul text", encoding="utf-8")
    skill_path.write_text("skill text", encoding="utf-8")

    ok_payload = _SENTINEL + json.dumps({
        "ok": True,
        "proposal": {"action": "WAIT_FOR_PROVIDER_RETRY", "diagnosis": "d", "rationale": "r",
                     "confidence": 0.6, "proposed_wait_hours": 24,
                     "recommended_intervention": "NONE",
                     "human_review_recommended": False, "human_review_reason": None,
                     "message_intent": None},
        "audit": {"validation_result": "valid", "tool_calls_used": 2, "confidence_band": "medium"},
    })
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: _fake_proc(ok_payload, rc=0))
    strat = HermesAgentStrategist(
        mock_base_url="http://127.0.0.1:1/v1", home=tmp_path / "h",
        checkout=_fake_checkout(tmp_path), python=__import__("sys").executable,
        verify_revision=False, soul_path=soul_path, skill_path=skill_path,
    )
    p = strat.propose(_snap())
    assert p.action is ProposalAction.WAIT_FOR_PROVIDER_RETRY
    assert strat.last_run_meta.extra.get("tool_calls_used") == 2

    soul_path.unlink()  # second attempt now fails to load its instructions
    with pytest.raises(HermesRuntimeUnavailable):
        strat.propose(_snap())

    ex = strat.last_run_meta.extra
    assert ex["failure_category"] == "instruction_load_failed"
    assert ex["failure_stage"] == "instruction_load"
    assert "tool_calls_used" not in ex and "confidence_band" not in ex
    assert strat.last_run_meta.validation_result == "invalid:instruction_load_failed"


def test_final_system_prompt_contains_real_soul_and_skill_in_order():
    """Direct proof using the REAL project SOUL.md/SKILL.md content (not
    markers): the final prompt contains both exact file contents, in order
    SOUL -> SKILL -> case context -> tool/output contract."""
    from hermes.hermes_agent import child_main
    from hermes.hermes_agent_strategist import _SKILL_PATH, _SOUL_PATH

    soul_text = _SOUL_PATH.read_text(encoding="utf-8")
    skill_text = _SKILL_PATH.read_text(encoding="utf-8")
    ctx = {"case_marker": "CASE-CONTEXT-MARKER"}
    prompt = child_main._system_prompt(soul_text, skill_text, ctx, [_APPROVED_MSG])

    assert soul_text.strip() in prompt
    assert skill_text.strip() in prompt
    i_soul = prompt.index(soul_text.strip())
    i_skill = prompt.index(skill_text.strip())
    i_case = prompt.index("CASE-CONTEXT-MARKER")
    i_contract = prompt.index("Return EXACTLY one JSON object")
    assert i_soul < i_skill < i_case < i_contract


def test_child_stream_decoded_as_utf8_not_locale(tmp_path):
    """Regression: the child's result line must be recovered even when the
    Hermes runtime writes non-cp1252 bytes to its streams. A real tiny child
    prints box-drawing output to stderr AND a valid result line to stdout;
    the parent's subprocess decode must not drop the result."""
    import subprocess as sp
    import sys

    child = tmp_path / "noisy_child.py"
    child.write_text(
        "import sys\n"
        "sys.stderr.buffer.write('\\u2500\\u2502 hermes banner \\u258f\\n'.encode('utf-8'))\n"
        "print('HERMES_CHILD_RESULT ' + '{\"ok\": true, \"proposal\": "
        "{\"action\": \"ESCALATE\", \"diagnosis\": \"d\", \"rationale\": \"r\", "
        "\"confidence\": 0.3, \"proposed_wait_hours\": 0, \"message_intent\": null}, "
        "\"audit\": {\"validation_result\": \"valid\"}}')\n",
        encoding="utf-8",
    )
    proc = sp.run([sys.executable, str(child)], capture_output=True,
                  text=True, encoding="utf-8", errors="replace", timeout=30)
    payload = mod._parse_result(proc.stdout)
    assert payload is not None and payload["ok"] is True
    assert payload["proposal"]["action"] == "ESCALATE"


# === CA bundle: restricted trust purpose + encoding (offline, no runtime) ===


def _bare_strategist(tmp_path) -> HermesAgentStrategist:
    fake_checkout = tmp_path / "checkout"
    fake_checkout.mkdir()
    (fake_checkout / "run_agent.py").write_text("# fake\n", encoding="utf-8")
    return HermesAgentStrategist(
        mock_base_url="http://127.0.0.1:1/v1", home=tmp_path / "h",
        checkout=fake_checkout, python=__import__("sys").executable,
        verify_revision=False,
    )


def test_ca_bundle_includes_a_server_auth_trusted_cert(monkeypatch, tmp_path):
    strat = _bare_strategist(tmp_path)
    monkeypatch.setattr(
        ssl, "enum_certificates",
        lambda store: [(b"DER-ALL-PURPOSE", "x509_asn", True)],  # trusted for everything
    )
    monkeypatch.setattr(ssl, "DER_cert_to_PEM_cert", lambda der: "PEM<" + der.decode() + ">")
    path = strat._ca_bundle()
    assert path is not None
    assert "PEM<DER-ALL-PURPOSE>" in Path(path).read_text()


def test_ca_bundle_excludes_a_restricted_non_server_auth_cert(monkeypatch, tmp_path):
    """A cert the OS trusts only for e.g. code signing (not server auth) must
    not be imported into the outbound-TLS trust store."""
    strat = _bare_strategist(tmp_path)
    code_signing_oid = "1.3.6.1.5.5.7.3.3"
    monkeypatch.setattr(
        ssl, "enum_certificates",
        lambda store: [(b"DER-CODE-SIGNING-ONLY", "x509_asn", {code_signing_oid})],
    )
    monkeypatch.setattr(ssl, "DER_cert_to_PEM_cert", lambda der: "PEM<" + der.decode() + ">")
    path = strat._ca_bundle()
    text = Path(path).read_text() if path else ""
    assert "PEM<DER-CODE-SIGNING-ONLY>" not in text


def test_ca_bundle_skips_unsupported_encoding(monkeypatch, tmp_path):
    """``ssl.enum_certificates`` documents ``x509_asn`` as the only currently
    supported encoding; anything else must be skipped, not guess-decoded."""
    strat = _bare_strategist(tmp_path)
    monkeypatch.setattr(
        ssl, "enum_certificates",
        lambda store: [(b"NOT-REALLY-DER", "some_future_encoding", True)],
    )
    called = []
    monkeypatch.setattr(ssl, "DER_cert_to_PEM_cert",
                        lambda der: called.append(der) or "PEM<" + der.decode() + ">")
    strat._ca_bundle()
    assert called == []  # never handed to the DER decoder


def test_ca_bundle_rebuilds_a_previously_generated_broad_bundle(tmp_path):
    """A bundle written by the earlier (unrestricted) logic must be discarded
    and rebuilt immediately, not trusted for the rest of its 24h cache window."""
    strat = _bare_strategist(tmp_path)
    home = tmp_path / "h"
    home.mkdir(parents=True, exist_ok=True)
    stale = home / "ca-bundle.pem"
    stale.write_bytes(b"-----BEGIN CERTIFICATE-----\nSTALE-BROAD-BUNDLE\n-----END CERTIFICATE-----\n")
    path = strat._ca_bundle()
    assert path is not None
    text = Path(path).read_text()
    assert "STALE-BROAD-BUNDLE" not in text
    assert text.startswith(f"# hermes-ca-bundle v{mod._CA_BUNDLE_VERSION}")
