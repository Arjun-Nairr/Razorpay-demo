"""Offline tests for the composition root: config validation without printing
secrets, live-mode requiring credentials (never silently scripted), and the
offline app/engine wiring. No network, no DB, no real .env dependence
(load_env=False + monkeypatched environment).
"""

from __future__ import annotations

import pytest

from hermes.adapters import InMemoryLedger, ScriptedStrategist
from hermes.engine import RecoveryEngine
from hermes.runtime import Settings, build_engine, build_strategist


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("GEMINI_API_KEY", "DATABASE_URL", "HERMES_DEMO_SIGNING_SECRET",
                "HERMES_STRATEGIST_MODEL"):
        monkeypatch.delenv(var, raising=False)


# --- mode + validation --------------------------------------------


def test_bad_mode_rejected():
    with pytest.raises(ValueError):
        Settings.load(mode="prod", load_env=False)


def test_offline_needs_no_credentials():
    s = Settings.load(mode="offline", load_env=False)
    assert s.mode == "offline"
    assert s.has_gemini_key is False and s.has_database_url is False
    assert s.demo_signing_secret.startswith("demosig_")  # generated


def test_live_requires_both_credentials(monkeypatch):
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        Settings.load(mode="live", load_env=False)
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-key")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        Settings.load(mode="live", load_env=False)


def test_live_settings_with_synthetic_credentials(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-key")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db?sslmode=require")
    s = Settings.load(mode="live", load_env=False)
    assert s.mode == "live" and s.has_gemini_key and s.has_database_url


def test_describe_never_exposes_secret_values(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "SECRET-KEY-VALUE-XYZ")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:SECRET-PW@host/db")
    s = Settings.load(mode="live", load_env=False)
    blob = repr(s.describe()) + repr(s)
    assert "SECRET-KEY-VALUE-XYZ" not in blob
    assert "SECRET-PW" not in blob
    assert s.describe()["gemini_key_present"] is True


def test_demo_signing_secret_from_env_is_used(monkeypatch):
    monkeypatch.setenv("HERMES_DEMO_SIGNING_SECRET", "demosig_fixed_value")
    s = Settings.load(mode="offline", load_env=False)
    assert s.demo_signing_secret == "demosig_fixed_value"


# --- wiring --------------------------------------------------


def test_offline_build_uses_in_memory_and_scripted():
    s = Settings.load(mode="offline", load_env=False)
    engine = build_engine(s)
    assert isinstance(engine, RecoveryEngine)
    assert isinstance(build_strategist(s), ScriptedStrategist)
    # engine has an in-memory ledger and resumes clock 0
    assert engine.logical_time == 0


def test_live_mode_never_substitutes_a_scripted_strategist(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-key")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    s = Settings.load(mode="live", load_env=False)
    strategist = build_strategist(s)
    assert type(strategist).__name__ == "HermesStrategist"
    assert not isinstance(strategist, ScriptedStrategist)


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_offline_app_starts_and_serves_health():
    fastapi = pytest.importorskip("fastapi")  # noqa: F841
    from fastapi.testclient import TestClient

    from hermes.runtime import build_app

    app = build_app(Settings.load(mode="offline", load_env=False))
    tc = TestClient(app)
    r = tc.get("/health")
    assert r.status_code == 200 and r.json()["evidence_mode"] == "SIMULATED"
    # the demo route is wired (provider present)
    assert tc.post("/demo/case").status_code == 200
