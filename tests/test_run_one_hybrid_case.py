"""Offline tests for scripts/run_one_hybrid_case.py's fail-closed preflight:
it must refuse to open a case (never call POST /demo/case) unless /health
explicitly confirms real Hermes/Gemini mode, the hybrid Razorpay Test Mode
provider, AND real Test Mode actions enabled. No live server, no network.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "run_one_hybrid_case.py"
_spec = importlib.util.spec_from_file_location("run_one_hybrid_case", _MODULE_PATH)
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)  # noqa: S102 - loading our own script by path

READY_HEALTH = {
    "status": "ok", "evidence_mode": "SIMULATED", "mode": "hermes-runtime",
    "payment_provider": "hybrid_test_mode", "payment_provider_test_mode_enabled": True,
}


class _StopAtCaseCreation(Exception):
    """Raised by the fake ``_req`` when ``POST /demo/case`` is reached - proof
    the preflight passed and the runner tried to proceed."""


def _fake_req(health: dict, calls: list):
    def fake(method: str, path: str, body: dict | None = None):
        calls.append((method, path))
        if (method, path) == ("GET", "/health"):
            return dict(health)
        if (method, path) == ("POST", "/demo/case"):
            raise _StopAtCaseCreation()
        raise AssertionError(f"unexpected call reached: {method} {path}")
    return fake


# --- _require_ready: pure preflight logic ---------------------------------


def test_require_ready_accepts_the_fully_ready_state():
    runner._require_ready(READY_HEALTH)  # must not raise


def test_require_ready_refuses_fake_provider():
    bad = {**READY_HEALTH, "payment_provider": "fake"}
    with pytest.raises(SystemExit):
        runner._require_ready(bad)


def test_require_ready_refuses_disabled_test_mode():
    bad = {**READY_HEALTH, "payment_provider_test_mode_enabled": False}
    with pytest.raises(SystemExit):
        runner._require_ready(bad)


def test_require_ready_refuses_missing_provider_field():
    bad = {k: v for k, v in READY_HEALTH.items() if k != "payment_provider"}
    with pytest.raises(SystemExit):
        runner._require_ready(bad)


def test_require_ready_refuses_missing_enabled_field():
    bad = {k: v for k, v in READY_HEALTH.items() if k != "payment_provider_test_mode_enabled"}
    with pytest.raises(SystemExit):
        runner._require_ready(bad)


def test_require_ready_refuses_mismatched_strategist_mode():
    bad = {**READY_HEALTH, "mode": "scripted-offline"}
    with pytest.raises(SystemExit):
        runner._require_ready(bad)


def test_require_ready_refuses_empty_health():
    with pytest.raises(SystemExit):
        runner._require_ready({})


@pytest.mark.parametrize("truthy_not_true", ["true", 1, "1"])
def test_require_ready_refuses_a_truthy_but_not_literal_true_enabled_flag(truthy_not_true):
    """Only the exact boolean True counts as enabled - a string/int that is
    merely truthy is not accepted, closing a type-confusion loophole."""
    bad = {**READY_HEALTH, "payment_provider_test_mode_enabled": truthy_not_true}
    with pytest.raises(SystemExit):
        runner._require_ready(bad)


# --- main(): the refusal happens BEFORE any case is opened -----------------


@pytest.mark.parametrize("bad_health", [
    {**READY_HEALTH, "payment_provider": "fake"},
    {**READY_HEALTH, "payment_provider_test_mode_enabled": False},
    {k: v for k, v in READY_HEALTH.items() if k != "payment_provider"},
    {**READY_HEALTH, "mode": "live-gemini"},
    {},
])
def test_main_never_opens_a_case_when_not_ready(monkeypatch, bad_health):
    calls: list = []
    monkeypatch.setattr(runner, "_req", _fake_req(bad_health, calls))
    with pytest.raises(SystemExit) as ei:
        runner.main()
    assert ei.value.code == 2
    assert ("POST", "/demo/case") not in calls


def test_main_proceeds_to_open_a_case_only_when_fully_ready(monkeypatch):
    calls: list = []
    monkeypatch.setattr(runner, "_req", _fake_req(READY_HEALTH, calls))
    with pytest.raises(_StopAtCaseCreation):
        runner.main()
    assert ("POST", "/demo/case") in calls
