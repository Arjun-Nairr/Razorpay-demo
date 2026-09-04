"""Offline harness for the ISOLATED REAL Nous Hermes integration.

Every test here spawns the actual ``hermes.hermes_agent.child_main`` with the
installed Hermes interpreter (``run_agent.AIAgent`` + its real tool loop),
against a local OpenAI-compatible **stub transport** - no live Gemini, no
network beyond loopback, no DB, no credentials.

Skips (not fails) when the installed runtime is absent or not the proven
revision - that is the "stop on mismatch" contract, verified live by the user.
"""

from __future__ import annotations

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from hermes.hermes_agent import EXPECTED_HERMES_REVISION
from hermes.hermes_agent_strategist import (
    _DEFAULT_CHECKOUT,
    _DEFAULT_PYTHON,
    HermesAgentStrategist,
    HermesRuntimeUnavailable,
)
from hermes.types import InvalidProposal, ProposalAction, StrategySnapshot

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


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
        # Ignore the runtime's non-streaming prewarm/health probe (no messages):
        # it must not consume a queued turn.
        if not req.get("messages"):
            body = json.dumps(_text("ok")).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)
            return
        for m in req.get("messages", []):
            if m.get("role") == "tool":
                type(self).seen_tool_results.append(m.get("content", ""))
        resp = type(self).queue.pop(0) if type(self).queue else _text('{"action":"STOP","diagnosis":"d","rationale":"fallback","confidence":0.2,"proposed_wait_hours":0,"message_intent":null}')
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
            body = json.dumps(resp).encode()
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


_VALID = '{"action":"WAIT_FOR_PROVIDER_RETRY","diagnosis":"insufficient funds, retry eligible","rationale":"one provider retry may still clear","confidence":0.62,"proposed_wait_hours":24,"message_intent":null}'


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
        links_remaining=1, actions_remaining=3,
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


# --- proof gate 2: real AIAgent + tool loop with stub transport -----------


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
    assert ex["confidence_band"] == "medium"
    assert any(e["tool"] == "get_payment_retry_facts" for e in ex["evidence_returned"])
    assert ex["tool_calls_used"] >= 1


@requires_runtime
def test_no_extra_lookup_path_is_legitimate(stub, tmp_path):
    _, S = stub
    S.queue = [_text(_VALID)]  # model decides straight from initial context
    strat = _strat(stub, tmp_path)
    p = strat.propose(_snap())
    assert p.action is ProposalAction.WAIT_FOR_PROVIDER_RETRY
    assert strat.last_run_meta.extra["tool_calls_used"] == 0


@requires_runtime
def test_optional_history_lookup_is_coherent_and_bounded(stub, tmp_path):
    _, S = stub
    S.queue = [
        _tc("get_payment_history", '{"months": 12, "reason": "chronic late payer?"}'),
        _tc("get_payment_history", '{"months": 12, "reason": "chronic late payer?"}'),  # duplicate -> rejected
        _tc("get_payment_history", '{"months": 6, "reason": "recent trend"}'),
        _text(_VALID),
    ]
    strat = _strat(stub, tmp_path)
    strat.propose(_snap())
    results = " ".join(S.seen_tool_results)
    assert "no-progress / duplicate request rejected" in results
    # 6-month window is the trailing subset of the 12-month window
    r12 = json.loads([r for r in S.seen_tool_results if '"coverage_months": 12' in r][0])
    r6 = json.loads([r for r in S.seen_tool_results if '"coverage_months": 6' in r][0])
    assert r6["records"] == r12["records"][-6:]
    reqs = strat.last_run_meta.extra["evidence_requests"]
    hist_reqs = [r for r in reqs if r["tool"] == "get_payment_history"]
    assert len(hist_reqs) == 3 and all(r.get("reason") for r in hist_reqs)


@requires_runtime
def test_history_unavailable_is_not_invented(stub, tmp_path):
    _, S = stub
    S.queue = [_tc("get_payment_history", '{"months": 12, "reason": "history depth"}'), _text(_VALID)]
    strat = _strat(stub, tmp_path, history_available=False)
    strat.propose(_snap())
    got = json.loads([r for r in S.seen_tool_results if "available" in r][0])
    assert got["available"] is False and "not invented" in got["note"]


@requires_runtime
def test_unauthorized_tool_call_is_rejected(stub, tmp_path):
    _, S = stub
    S.queue = [_tc("terminal", '{"cmd": "rm -rf /"}'), _tc("get_secret", "{}"), _text(_VALID)]
    strat = _strat(stub, tmp_path)
    p = strat.propose(_snap())  # still resolves via the real loop's rejection path
    assert p.action is ProposalAction.WAIT_FOR_PROVIDER_RETRY
    joined = " ".join(S.seen_tool_results)
    assert "does not exist" in joined
    ex = strat.last_run_meta.extra
    assert all(e["tool"] in {"get_payment_retry_facts", "get_payment_history", "get_recovery_actions"}
               for e in ex["evidence_returned"])


@requires_runtime
def test_forged_case_id_argument_is_ignored(stub, tmp_path):
    _, S = stub
    S.queue = [_tc("get_payment_retry_facts", '{"case_id": "sub_victim_9999", "sql": "DROP TABLE"}'), _text(_VALID)]
    strat = _strat(stub, tmp_path)
    strat.propose(_snap(provider_retry_eligible=True))
    facts = json.loads([r for r in S.seen_tool_results if "provider_retry_eligible" in r][0])
    assert facts["provider_retry_eligible"] is True
    assert facts["source"] == "SIMULATED_PROVIDER" and "sub_victim_9999" not in json.dumps(facts)


@requires_runtime
def test_invalid_output_gets_one_repair_then_succeeds(stub, tmp_path):
    _, S = stub
    S.queue = [_text("here is my answer: wait a day"), _text(_VALID)]  # 1st not JSON -> 1 repair
    strat = _strat(stub, tmp_path)
    p = strat.propose(_snap())
    assert p.action is ProposalAction.WAIT_FOR_PROVIDER_RETRY
    assert strat.last_run_meta.repair_used is True
    assert strat.last_run_meta.validation_result == "repaired"


@requires_runtime
def test_repeated_invalid_output_is_a_bounded_failure(stub, tmp_path):
    _, S = stub
    S.queue = [_text("nope"), _text("still nope")]  # invalid + repair still invalid
    strat = _strat(stub, tmp_path)
    with pytest.raises(InvalidProposal):
        strat.propose(_snap())
    ex = strat.last_run_meta.extra
    assert ex["stop_reason"] == "schema_repair_failed"
    assert strat.last_run_meta.validation_result.startswith("invalid:")


@requires_runtime
def test_single_decision_in_flight(stub, tmp_path):
    _, S = stub
    S.queue = [_text(_VALID)]
    strat = _strat(stub, tmp_path)
    strat._one_in_flight.acquire()  # simulate a concurrent decision
    try:
        with pytest.raises(TimeoutError):
            strat.propose(_snap())
    finally:
        strat._one_in_flight.release()


@requires_runtime
def test_subprocess_deadline_reaps_child(stub, tmp_path):
    _, S = stub
    S.queue = [_text(_VALID)]
    strat = _strat(stub, tmp_path, deadline_s=0.5)  # unreasonably short -> timeout + reap
    with pytest.raises(TimeoutError):
        strat.propose(_snap())
    assert strat.last_run_meta.extra["stop_reason"] == "subprocess_deadline"


def test_wrong_revision_refuses_to_launch(tmp_path):
    with pytest.raises(HermesRuntimeUnavailable):
        HermesAgentStrategist(home=tmp_path / "h", verify_revision=True,
                              checkout=tmp_path)  # no run_agent.py here
