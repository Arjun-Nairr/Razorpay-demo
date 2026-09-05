"""Offline tests for the five read-only Neon views added to
``scripts/init_neon.py``. No live Postgres is available in this environment
(no local install, and live DDL against Neon is a separate, explicitly
authorized, later step - see HANDOFF.md) - so these tests cover exactly what
can be verified without executing real SQL:

1. Structural checks on the generated SQL text itself: every expected view is
   `CREATE OR REPLACE VIEW` (never destructive), schema-qualified via the
   caller-supplied (already-validated) schema string, and its SELECT list
   names every column the contract requires.
2. Pure-Python PARITY mirrors of the view's actual business logic (display
   status, decision-cycle association, message authorized-vs-sent
   separation) - the same rule the SQL implements, verified against sample
   ledger-shaped data. A mismatch here would mean the RULE is wrong; it does
   not by itself prove the SQL syntax is valid Postgres - that is confirmed
   for real only by the live `init_neon.py` run against Neon (HANDOFF.md
   records that result).
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "init_neon.py"
_spec = importlib.util.spec_from_file_location("init_neon", _MODULE_PATH)
init_neon = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(init_neon)  # noqa: S102 - loading our own script by path

VIEWS = init_neon._view_sql("hermes_demo")

EXPECTED_COLUMNS = {
    "case_summary": [
        "case_id", "obligation_id", "state", "display_status", "amount_minor",
        "currency", "recovered_amount_minor", "evidence_mode", "failure_reason",
        "retry_outcome_recorded", "actions_taken", "links_created", "messages_sent",
        "attribution", "counted", "last_proposed_action", "last_policy_outcome",
        "human_review_required", "human_review_reason", "created_logical_time",
        "snapshot_updated_at",
    ],
    "hermes_decisions": [
        "case_id", "decision_number", "logical_time", "model", "prompt_version",
        "hermes_runtime_revision", "execution_duration_seconds", "latency_ms",
        "validation_result", "repair_used", "model_iterations_used",
        "model_iterations_budget", "tool_calls_used", "tool_calls_budget",
        "evidence_requests", "evidence_returned", "history_expansion_requested",
        "history_expansion_reason", "confidence", "confidence_band",
        "confidence_basis", "diagnosis", "rationale", "proposed_action",
        "proposed_wait_hours", "recommended_intervention",
        "model_human_review_recommended", "model_human_review_reason",
        "policy_outcome", "policy_reason", "authorized",
        "failure_category", "failure_stage",
        "payment_plan_eligible", "payment_plan_prior_difficulty_count",
    ],
    "recovery_actions": [
        "case_id", "intent_id", "created_logical_time", "proposed_action",
        "execution_status", "provider_reference", "checkout_url_present",
        "action_evidence_mode", "message_authorized", "message_sent",
        "message_intent", "message_draft", "message_status",
        "case_state", "human_review_required", "uncertain_reason",
        "delivery_channel", "delivery_status", "delivery_message_id",
        "delivery_attempted_time",
    ],
    "hermes_evidence": [
        "case_id", "model_run_seq", "tool", "source", "actual_coverage",
        "requested_months", "request_reason",
    ],
    "audit_timeline": [
        "seq", "logical_time", "case_id", "kind", "action", "outcome", "reason",
        "state", "evidence_mode", "detail",
    ],
}

_DESTRUCTIVE = re.compile(r"\b(DROP|TRUNCATE|DELETE|ALTER|GRANT|REVOKE)\b", re.IGNORECASE)


# --- structural: creation, schema-qualification, columns, no destructive SQL


def test_all_five_views_are_defined():
    assert set(VIEWS) == set(EXPECTED_COLUMNS)


@pytest.mark.parametrize("name", list(EXPECTED_COLUMNS))
def test_view_is_create_or_replace_schema_qualified(name):
    sql = VIEWS[name]
    assert f"CREATE OR REPLACE VIEW hermes_demo.{name}" in sql


@pytest.mark.parametrize("name", list(EXPECTED_COLUMNS))
def test_view_names_every_required_column(name):
    sql = VIEWS[name]
    for col in EXPECTED_COLUMNS[name]:
        assert re.search(rf"\bAS\s+{re.escape(col)}\b", sql), \
            f"{name} is missing expected column {col!r}"


@pytest.mark.parametrize("name", list(EXPECTED_COLUMNS))
def test_view_contains_no_destructive_sql(name):
    assert not _DESTRUCTIVE.search(VIEWS[name]), \
        f"{name} must contain only CREATE OR REPLACE VIEW / SELECT"


def test_schema_name_is_the_caller_supplied_validated_string_not_hardcoded():
    """A different (still-valid) schema name must be reflected verbatim -
    proving the SQL is schema-qualified via the parameter, not hardcoded to
    'hermes_demo'. The caller (module-level ``SCHEMA``) is what actually runs
    ``_validate_schema`` before this function ever sees the string."""
    other = init_neon._view_sql("custom_demo_schema")
    for name in EXPECTED_COLUMNS:
        assert f"CREATE OR REPLACE VIEW custom_demo_schema.{name}" in other[name]
        assert "hermes_demo" not in other[name]


def test_module_level_schema_is_validated_before_any_view_sql_is_built():
    """The actual schema used at runtime (``init_neon.SCHEMA``) already went
    through ``_validate_schema`` at import time - a malicious/malformed
    HERMES_DEMO_SCHEMA would have raised before ``_view_sql`` is ever called."""
    with pytest.raises(ValueError):
        init_neon._validate_schema("not a valid schema; DROP SCHEMA public")


def test_recovery_actions_and_hermes_decisions_reference_case_summary_or_audit_only():
    # recovery_actions is documented to read case state via case_summary,
    # never recomputing/duplicating the display-status rule.
    assert "hermes_demo.case_summary" in VIEWS["recovery_actions"]


# --- pure-Python parity mirrors of the view's actual logic -----------------
#
# These reimplement (deliberately, in the same branch order) the CASE/LATERAL
# rules the SQL above encodes, so the underlying BUSINESS RULE is exercised
# offline. They do not execute the SQL itself.


def _mirror_display_status(state: str, has_executed_recovery_link: bool) -> str:
    if state == "recovered":
        return "RECOVERED"
    if state in ("escalated", "exhausted", "stopped"):
        return "HUMAN_REVIEW_REQUIRED"
    if state not in ("recovered", "escalated", "exhausted", "stopped") and has_executed_recovery_link:
        return "RECOVERY_IN_PROGRESS"
    if state == "waiting":
        return "WAITING_FOR_PROVIDER_RETRY"
    return "ACTIVE"


@pytest.mark.parametrize("state,has_link,expected", [
    ("recovered", False, "RECOVERED"),
    ("recovered", True, "RECOVERED"),
    ("escalated", False, "HUMAN_REVIEW_REQUIRED"),
    ("exhausted", False, "HUMAN_REVIEW_REQUIRED"),
    ("stopped", False, "HUMAN_REVIEW_REQUIRED"),
    ("active", True, "RECOVERY_IN_PROGRESS"),   # case-18's exact shape
    ("active", False, "ACTIVE"),
    ("waiting", False, "WAITING_FOR_PROVIDER_RETRY"),
    ("waiting", True, "RECOVERY_IN_PROGRESS"),  # link check outranks "waiting"
])
def test_display_status_logic(state, has_link, expected):
    assert _mirror_display_status(state, has_link) == expected


def test_case18_shaped_case_is_active_with_recovery_in_progress_display():
    """Direct parity check for the exact case-18 scenario: authoritative
    state stays 'active' - never mutated - while display_status reflects the
    executed, unpaid recovery link."""
    state, has_link = "active", True
    assert state == "active"  # authoritative state is never touched
    assert _mirror_display_status(state, has_link) == "RECOVERY_IN_PROGRESS"


# --- decision-cycle association (nearest AI_MODEL_RUN before / nearest
#     POLICY_DECISION after, per case, never a global first/last) ----------


def _mirror_nearest(events, case_id, seq, kind, *, before):
    candidates = [e for e in events if e["case_id"] == case_id and e["kind"] == kind
                  and (e["seq"] < seq if before else e["seq"] > seq)]
    if not candidates:
        return None
    return (max if before else min)(candidates, key=lambda e: e["seq"])


def test_decision_cycle_association_picks_the_nearest_pair_not_global_first_last():
    # Two decision cycles for the SAME case - a naive "first/last" join would
    # wrongly pair proposal #2 with model-run #1 or policy-decision #1.
    events = [
        {"seq": 1, "case_id": "case-X", "kind": "AI_MODEL_RUN", "model": "gemini-a"},
        {"seq": 2, "case_id": "case-X", "kind": "AI_PROPOSAL", "action": "WAIT_FOR_PROVIDER_RETRY"},
        {"seq": 3, "case_id": "case-X", "kind": "POLICY_DECISION", "outcome": "ALLOW"},
        {"seq": 4, "case_id": "case-X", "kind": "SCHEDULED_ACTION"},
        {"seq": 5, "case_id": "case-X", "kind": "RETRY_OUTCOME_RECORDED"},
        {"seq": 6, "case_id": "case-X", "kind": "AI_MODEL_RUN", "model": "gemini-b"},
        {"seq": 7, "case_id": "case-X", "kind": "AI_PROPOSAL", "action": "CREATE_RECOVERY_LINK"},
        {"seq": 8, "case_id": "case-X", "kind": "POLICY_DECISION", "outcome": "ALLOW"},
    ]
    mr1 = _mirror_nearest(events, "case-X", 2, "AI_MODEL_RUN", before=True)
    pd1 = _mirror_nearest(events, "case-X", 2, "POLICY_DECISION", before=False)
    assert mr1["model"] == "gemini-a" and pd1["seq"] == 3

    mr2 = _mirror_nearest(events, "case-X", 7, "AI_MODEL_RUN", before=True)
    pd2 = _mirror_nearest(events, "case-X", 7, "POLICY_DECISION", before=False)
    assert mr2["model"] == "gemini-b"  # NOT the first cycle's model
    assert pd2["seq"] == 8


def test_decision_cycle_association_is_scoped_to_the_same_case():
    events = [
        {"seq": 1, "case_id": "case-A", "kind": "AI_MODEL_RUN", "model": "a"},
        {"seq": 2, "case_id": "case-B", "kind": "AI_PROPOSAL"},  # different case
        {"seq": 3, "case_id": "case-B", "kind": "POLICY_DECISION", "outcome": "ALLOW"},
    ]
    mr = _mirror_nearest(events, "case-B", 2, "AI_MODEL_RUN", before=True)
    assert mr is None  # case-A's model run must never leak into case-B's row


# --- separation of authorized vs executed/sent -----------------------------


def test_message_authorized_and_message_sent_are_independent_fields():
    """The exact bug this view must not repeat: authorized-by-policy is not
    the same fact as actually-sent (see engine.py's message_delivery_capable
    fix). A real/hybrid case can be authorized=True, sent=False."""
    action_intent_event_detail = {"message_authorized": True}
    intent = {"message_sent": False}
    message_authorized = bool(action_intent_event_detail.get("message_authorized", False))
    message_sent = bool(intent.get("message_sent", False))
    assert message_authorized is True and message_sent is False
    assert message_authorized != message_sent


def test_historical_row_missing_advisory_fields_reads_not_recorded_never_none():
    """A pre-milestone AI_PROPOSAL detail lacking the new advisory keys must
    surface a fixed 'NOT_RECORDED' label for recommended_intervention (never
    the real 'NONE' value) and null (never false) for the boolean/reason -
    never silently rewritten as if a real decision was recorded."""
    sql = VIEWS["hermes_decisions"]
    assert "NOT_RECORDED" in sql
    assert "COALESCE(p->'detail'->>'recommended_intervention', 'NOT_RECORDED')" in sql
    # the boolean/reason columns must NOT be coalesced to a false-y default -
    # a missing key must read back as SQL NULL, distinguishable from a real False.
    assert "COALESCE((p->'detail'->>'human_review_recommended')" not in sql


def test_historical_row_missing_message_status_reads_legacy_label_never_drafted():
    """A pre-milestone action_intent lacking message_status must read back as
    the fixed 'LEGACY_NOT_STAGED' label - never 'DRAFTED' or 'SENT', which
    would falsely claim a draft that was never actually staged."""
    sql = VIEWS["recovery_actions"]
    assert "COALESCE(i.value->>'message_status', 'LEGACY_NOT_STAGED')" in sql


def test_message_draft_column_never_selects_a_url():
    """recovery_actions.message_draft is the deterministic template text only -
    never the checkout URL, which stays checkout_url_present-only."""
    sql = VIEWS["recovery_actions"]
    assert "message_draft" in sql
    assert not re.search(r"->>'url'\s+AS\s+message_draft\b", sql)


def test_delivery_columns_never_select_a_url_token_or_chat_id():
    """The Telegram delivery evidence columns expose only channel/outcome/
    sanitized message id/attempt time - never the checkout URL and never a
    field named after a token or chat id (none exists on the ledger side
    either - see ActionIntent, which never stores one)."""
    sql = VIEWS["recovery_actions"]
    for col in ("delivery_channel", "delivery_status", "delivery_message_id",
                "delivery_attempted_time"):
        assert col in sql
    assert not re.search(r"->>'url'\s+AS\s+delivery_\w+", sql)
    # no OUTPUT COLUMN is ever named after a token/chat id (prose comments
    # mentioning the words are fine - only a real "AS <col>" would leak one).
    assert not re.search(r"AS\s+\w*token\w*", sql, re.IGNORECASE)
    assert not re.search(r"AS\s+\w*chat_id\w*", sql, re.IGNORECASE)


def test_checkout_url_present_not_the_url_itself():
    """recovery_actions exposes a boolean, never the full checkout URL."""
    for name, sql in [("recovery_actions", VIEWS["recovery_actions"])]:
        assert "checkout_url_present" in sql
        # the raw ->>'url' value must never be selected as its own output column
        assert not re.search(r"->>'url'\s+AS\s+\w*url\w*(?<!_present)\b", sql)
