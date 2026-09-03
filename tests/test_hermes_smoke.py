"""Offline tests for scripts/hermes_smoke.py's .env handling and failure output.

These never touch the user's real project-root .env (explicit temp paths or a
monkeypatched loader), never read a real API key, and never call Gemini.
``python-dotenv`` need not be installed: a recording stub stands in for it.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import os
import pathlib
import sys
import types

import pytest

_SMOKE_PATH = pathlib.Path(__file__).parent.parent / "scripts" / "hermes_smoke.py"


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location("hermes_smoke_under_test", _SMOKE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def smoke():
    return _load_smoke_module()


@pytest.fixture(autouse=True)
def _clear_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.fixture
def fake_dotenv(monkeypatch):
    """Stand in for python-dotenv, recording every call and honouring
    ``override`` the way the real package does."""
    calls: list[dict] = []

    def load_dotenv(dotenv_path=None, *, override=False, **_kw):
        calls.append({"path": str(dotenv_path), "override": override})
        try:
            text = pathlib.Path(dotenv_path).read_text()
        except OSError:
            return False
        loaded = False
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if override or key not in os.environ:
                monkeypatch.setenv(key, value)  # auto-restored after the test
                loaded = True
        return loaded

    mod = types.ModuleType("dotenv")
    mod.load_dotenv = load_dotenv
    monkeypatch.setitem(sys.modules, "dotenv", mod)
    return calls


# --- .env file loading -------------------------------------------------


def test_load_project_env_reads_an_explicit_dotenv(smoke, fake_dotenv, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=synthetic-key-from-file\n")

    smoke._load_project_env(str(env_file))

    assert os.environ["GEMINI_API_KEY"] == "synthetic-key-from-file"
    assert fake_dotenv[0]["override"] is False  # never overrides the environment
    assert fake_dotenv[0]["path"] == str(env_file)


def test_missing_dotenv_file_is_a_silent_noop(smoke, fake_dotenv, tmp_path):
    smoke._load_project_env(str(tmp_path / "nope.env"))  # must not raise
    assert os.environ.get("GEMINI_API_KEY") is None


def test_noop_when_python_dotenv_is_not_installed(smoke, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=should-not-be-loaded\n")
    monkeypatch.setitem(sys.modules, "dotenv", None)  # -> `import dotenv` raises ImportError

    smoke._load_project_env(str(env_file))  # must not raise

    assert os.environ.get("GEMINI_API_KEY") is None


# --- environment precedence ---------------------------------------


def test_existing_env_var_takes_precedence_over_dotenv(smoke, fake_dotenv, tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-key-from-environment")
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=synthetic-key-from-file\n")

    smoke._load_project_env(str(env_file))

    assert os.environ["GEMINI_API_KEY"] == "synthetic-key-from-environment"


# --- missing-key behaviour --------------------------------------


def test_main_returns_2_when_no_key(smoke, monkeypatch):
    # no-op the loader so the real project .env is never touched
    monkeypatch.setattr(smoke, "_load_project_env", lambda *a, **k: None)
    assert smoke.main() == 2


# --- failure output is redacted (task point 6) -----------------


@dataclasses.dataclass
class _FakeMeta:
    model: str = "gemini-3.7-flash"
    prompt_version: str = "test"
    latency_ms: float = 1.0
    repair_used: bool = False
    validation_result: str = "transport_error:RuntimeError"
    raw_response: str = ""
    usage: dict | None = None
    cost_usd: float | None = None


def test_smoke_failure_output_omits_raw_exception_message(smoke, monkeypatch, capsys):
    monkeypatch.setattr(smoke, "_load_project_env", lambda *a, **k: None)
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-not-a-real-key")
    marker = "secret-bearing-exception-text-do-not-print"

    class _FakeStrategist:
        def __init__(self, *a, **k):
            self.last_run_meta = _FakeMeta()

        def propose(self, _snapshot):
            raise RuntimeError(marker)

    monkeypatch.setattr(smoke, "HermesStrategist", _FakeStrategist)

    rc = smoke.main()
    out = capsys.readouterr().out

    assert rc == 1
    assert marker not in out  # the raw exception message is never printed
    payload = json.loads(out)
    assert payload["outcome"] == "failed"
    assert payload["error_type"] == "RuntimeError"  # type name only
    assert payload["run_meta"]["validation_result"] == "transport_error:RuntimeError"
    assert "error" not in payload  # no str(exc) field at all
