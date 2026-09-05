"""Idempotent, non-destructive initialisation of the demo ledger schema.

    python -m pip install ".[db]"
    # DATABASE_URL must be set (in the gitignored root .env or the environment)
    python scripts/init_neon.py

Creates only:
    CREATE SCHEMA IF NOT EXISTS hermes_demo
    CREATE TABLE  IF NOT EXISTS hermes_demo.ledger_state (id, data JSONB, updated_at)
    INSERT the single id=1 row with an empty ledger snapshot, ON CONFLICT DO NOTHING
    CREATE OR REPLACE VIEW for each of the six read-only views in VIEW_DEFINITIONS

It never issues DROP / TRUNCATE / DELETE and never touches anything outside the
`hermes_demo` schema. Safe to run repeatedly. The connection string is read from
the environment and is never printed.

The six views (see VIEW_DEFINITIONS below) are a PRESENTATION layer only, over
the SAME single authoritative `ledger_state.data` JSONB snapshot - no data is
duplicated or made mutable, and the authoritative `state` column never changes
meaning. `case_summary.display_status` is derived read-only status text for
Neon's table/view browser (e.g. `RECOVERY_IN_PROGRESS` for an active case with
an executed, unpaid recovery link); it never contradicts or is written back
into `state`.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hermes.adapters import InMemoryLedger  # noqa: E402
from hermes.pg_ledger import (  # noqa: E402
    _DEFAULT_SCHEMA,
    _connect_bounded,
    _startup_budget_s,
    _validate_schema,
    dump_ledger,
)

SCHEMA = _validate_schema(os.environ.get("HERMES_DEMO_SCHEMA", _DEFAULT_SCHEMA))


def _view_sql(schema: str) -> dict[str, str]:
    """The six read-only views, keyed by name, schema-qualified via the
    ALREADY-VALIDATED ``schema`` (see ``_validate_schema`` - a strict
    lowercase-identifier regex, so this f-string interpolation cannot be used
    for SQL injection). Every view reads ONLY ``ledger_state.data`` - no new
    table, no duplicated mutable state. ``CREATE OR REPLACE VIEW`` only -
    never ``DROP``/``TRUNCATE``/``DELETE``, so re-running this is safe and
    never resets or loses a case.

    Dependency order matters: ``case_summary`` is created first because
    ``recovery_actions`` reads case state/human-review from it rather than
    recomputing the same display-status rule twice.
    """
    return {
        "case_summary": f"""
CREATE OR REPLACE VIEW {schema}.case_summary AS
SELECT
  c.case_id                                                AS case_id,
  c.value->>'obligation_id'                                AS obligation_id,
  c.value->>'state'                                        AS state,
  CASE
    WHEN c.value->>'state' = 'recovered' THEN 'RECOVERED'
    WHEN c.value->>'state' IN ('escalated', 'exhausted', 'stopped')
      THEN 'HUMAN_REVIEW_REQUIRED'
    WHEN c.value->>'state' NOT IN ('recovered', 'escalated', 'exhausted', 'stopped')
      AND EXISTS (
        SELECT 1 FROM jsonb_each(s.data->'action_intents') AS ai(intent_id, value)
        WHERE ai.value->>'case_id' = c.case_id
          AND ai.value->>'action' = 'CREATE_RECOVERY_LINK'
          AND ai.value->>'status' = 'executed'
      ) THEN 'RECOVERY_IN_PROGRESS'
    WHEN c.value->>'state' = 'waiting' THEN 'WAITING_FOR_PROVIDER_RETRY'
    ELSE 'ACTIVE'
  END                                                       AS display_status,
  COALESCE((c.value->>'amount_minor')::int, 0)              AS amount_minor,
  c.value->>'currency'                                      AS currency,
  CASE WHEN COALESCE((c.value->>'counted')::boolean, false)
       THEN COALESCE((c.value->>'amount_minor')::int, 0) ELSE 0 END
                                                             AS recovered_amount_minor,
  COALESCE(c.value->>'evidence_mode', 'SIMULATED')          AS evidence_mode,
  c.value->>'failure_reason'                                AS failure_reason,
  COALESCE((c.value->>'retry_outcome_recorded')::boolean, false)
                                                             AS retry_outcome_recorded,
  COALESCE((c.value->>'actions_taken')::int, 0)             AS actions_taken,
  COALESCE((c.value->>'links_created')::int, 0)             AS links_created,
  COALESCE((c.value->>'messages_sent')::int, 0)             AS messages_sent,
  c.value->>'attribution'                                   AS attribution,
  COALESCE((c.value->>'counted')::boolean, false)           AS counted,
  c.value->>'last_proposal_action'                          AS last_proposed_action,
  c.value->>'last_policy_outcome'                           AS last_policy_outcome,
  (c.value->>'state' IN ('escalated', 'exhausted', 'stopped'))
                                                             AS human_review_required,
  (
    SELECT a->'detail'->>'reason'
    FROM jsonb_array_elements(s.data->'audit') a
    WHERE a->>'case_id' = c.case_id AND a->>'kind' = 'TERMINAL_TRANSITION'
    ORDER BY (a->>'seq')::int DESC
    LIMIT 1
  )                                                          AS human_review_reason,
  COALESCE((c.value->>'created_time')::int, 0)              AS created_logical_time,
  s.updated_at                                               AS snapshot_updated_at
FROM {schema}.ledger_state s,
     jsonb_each(s.data->'cases') AS c(case_id, value)
WHERE s.id = 1
""",
        "hermes_decisions": f"""
CREATE OR REPLACE VIEW {schema}.hermes_decisions AS
SELECT
  p->>'case_id'                                             AS case_id,
  ROW_NUMBER() OVER (PARTITION BY p->>'case_id' ORDER BY (p->>'seq')::int)
                                                             AS decision_number,
  (p->>'logical_time')::int                                 AS logical_time,
  mr.detail->>'model'                                       AS model,
  mr.detail->>'prompt_version'                              AS prompt_version,
  mr.detail->'hermes'->>'runtime_revision'                  AS hermes_runtime_revision,
  (NULLIF(mr.detail->'hermes'->>'duration_ms', '')::numeric / 1000.0)
                                                             AS execution_duration_seconds,
  (mr.detail->>'latency_ms')::numeric                       AS latency_ms,
  COALESCE(mr.detail->>'validation_result', 'not_recorded') AS validation_result,
  COALESCE((mr.detail->>'repair_used')::boolean, false)     AS repair_used,
  (mr.detail->'hermes'->>'model_iterations_used')::int      AS model_iterations_used,
  (mr.detail->'hermes'->>'model_iterations_budget')::int    AS model_iterations_budget,
  (mr.detail->'hermes'->>'tool_calls_used')::int            AS tool_calls_used,
  (mr.detail->'hermes'->>'tool_calls_budget')::int          AS tool_calls_budget,
  COALESCE(mr.detail->'hermes'->'evidence_requests', '[]'::jsonb)
                                                             AS evidence_requests,
  COALESCE(mr.detail->'hermes'->'evidence_returned', '[]'::jsonb)
                                                             AS evidence_returned,
  EXISTS (
    SELECT 1 FROM jsonb_array_elements(
      COALESCE(mr.detail->'hermes'->'evidence_requests', '[]'::jsonb)) er
    WHERE er->>'tool' = 'get_payment_history'
  )                                                          AS history_expansion_requested,
  (
    SELECT er->>'reason'
    FROM jsonb_array_elements(COALESCE(mr.detail->'hermes'->'evidence_requests', '[]'::jsonb)) er
    WHERE er->>'tool' = 'get_payment_history'
    LIMIT 1
  )                                                          AS history_expansion_reason,
  (mr.detail->'hermes'->>'model_confidence')::numeric       AS confidence,
  mr.detail->'hermes'->>'confidence_band'                   AS confidence_band,
  COALESCE(mr.detail->'hermes'->>'confidence_basis', 'not_recorded')
                                                             AS confidence_basis,
  p->'detail'->>'diagnosis'                                 AS diagnosis,
  p->'detail'->>'rationale'                                 AS rationale,
  p->'detail'->>'action'                                    AS proposed_action,
  (p->'detail'->>'proposed_wait_hours')::int                AS proposed_wait_hours,
  pd.detail->>'outcome'                                     AS policy_outcome,
  pd.detail->>'reason_code'                                 AS policy_reason,
  (pd.detail->>'outcome' = 'ALLOW')                         AS authorized,
  mr.detail->'hermes'->>'failure_category'                  AS failure_category,
  mr.detail->'hermes'->>'failure_stage'                     AS failure_stage,
  -- appended at the end - CREATE OR REPLACE VIEW cannot change/reposition an
  -- EXISTING view's existing output columns, only append new ones.
  COALESCE(p->'detail'->>'recommended_intervention', 'NOT_RECORDED')
                                                             AS recommended_intervention,
  (p->'detail'->>'human_review_recommended')::boolean       AS model_human_review_recommended,
  p->'detail'->>'human_review_reason'                       AS model_human_review_reason,
  -- deterministic (never model-derived) PAYMENT_PLAN_REVIEW eligibility fact -
  -- explains WHY a recommendation was allowed or rejected; null/NOT_RECORDED
  -- on a historical row that predates this fact.
  (mr.detail->'hermes'->>'payment_plan_eligible')::boolean  AS payment_plan_eligible,
  (mr.detail->'hermes'->>'payment_plan_prior_difficulty_count')::int
                                                             AS payment_plan_prior_difficulty_count
FROM {schema}.ledger_state s,
     jsonb_array_elements(s.data->'audit') AS p
LEFT JOIN LATERAL (
  SELECT e->'detail' AS detail
  FROM jsonb_array_elements(s.data->'audit') e
  WHERE e->>'case_id' = p->>'case_id' AND e->>'kind' = 'AI_MODEL_RUN'
    AND (e->>'seq')::int < (p->>'seq')::int
  ORDER BY (e->>'seq')::int DESC
  LIMIT 1
) mr ON true
LEFT JOIN LATERAL (
  SELECT e->'detail' AS detail
  FROM jsonb_array_elements(s.data->'audit') e
  WHERE e->>'case_id' = p->>'case_id' AND e->>'kind' = 'POLICY_DECISION'
    AND (e->>'seq')::int > (p->>'seq')::int
  ORDER BY (e->>'seq')::int ASC
  LIMIT 1
) pd ON true
WHERE s.id = 1 AND p->>'kind' = 'AI_PROPOSAL'
""",
        "recovery_actions": f"""
CREATE OR REPLACE VIEW {schema}.recovery_actions AS
SELECT
  i.value->>'case_id'                                       AS case_id,
  i.intent_id                                               AS intent_id,
  COALESCE((i.value->>'created_time')::int, 0)              AS created_logical_time,
  i.value->>'action'                                        AS proposed_action,
  i.value->>'status'                                        AS execution_status,
  i.value->>'reference'                                     AS provider_reference,
  (i.value->>'url' IS NOT NULL AND i.value->>'url' <> '')   AS checkout_url_present,
  CASE WHEN i.value->>'url' IS NOT NULL AND i.value->>'url' <> ''
       THEN 'REAL_TEST_MODE' ELSE 'SIMULATED' END           AS action_evidence_mode,
  COALESCE((ai_evt.detail->>'message_authorized')::boolean, false)
                                                             AS message_authorized,
  COALESCE((i.value->>'message_sent')::boolean, false)      AS message_sent,
  cs.state                                                  AS case_state,
  COALESCE(cs.human_review_required, false)                 AS human_review_required,
  uncertain_evt.detail->>'reason'                           AS uncertain_reason,
  -- appended at the end - CREATE OR REPLACE VIEW cannot change/reposition an
  -- EXISTING view's existing output columns, only append new ones.
  i.value->>'message_intent'                                AS message_intent,
  i.value->>'message_draft'                                 AS message_draft,
  COALESCE(i.value->>'message_status', 'LEGACY_NOT_STAGED') AS message_status,
  -- real message-delivery evidence (e.g. Telegram) - never the checkout URL,
  -- template text, token, or chat id; null on a row with no attempt yet.
  i.value->>'delivery_channel'                              AS delivery_channel,
  i.value->>'delivery_outcome'                              AS delivery_status,
  i.value->>'delivery_message_id'                           AS delivery_message_id,
  (i.value->>'delivery_attempted_time')::int                AS delivery_attempted_time
FROM {schema}.ledger_state s,
     jsonb_each(s.data->'action_intents') AS i(intent_id, value)
LEFT JOIN LATERAL (
  SELECT e->'detail' AS detail
  FROM jsonb_array_elements(s.data->'audit') e
  WHERE e->>'kind' = 'ACTION_INTENT' AND e->'detail'->>'intent_id' = i.intent_id
  ORDER BY (e->>'seq')::int ASC
  LIMIT 1
) ai_evt ON true
LEFT JOIN LATERAL (
  SELECT e->'detail' AS detail
  FROM jsonb_array_elements(s.data->'audit') e
  WHERE e->>'kind' = 'ACTION_OUTCOME' AND e->'detail'->>'intent_id' = i.intent_id
    AND e->'detail'->>'status' = 'uncertain'
  ORDER BY (e->>'seq')::int ASC
  LIMIT 1
) uncertain_evt ON true
LEFT JOIN {schema}.case_summary cs ON cs.case_id = i.value->>'case_id'
WHERE s.id = 1
""",
        "hermes_evidence": f"""
CREATE OR REPLACE VIEW {schema}.hermes_evidence AS
SELECT
  mr_evt->>'case_id'                                        AS case_id,
  (mr_evt->>'seq')::int                                     AS model_run_seq,
  er->>'tool'                                                AS tool,
  er->>'source'                                              AS source,
  er->>'coverage'                                            AS actual_coverage,
  -- get_payment_history's expansion is always straight to 12 months by fixed
  -- tool contract (see config/hermes_agent/SKILL.md) - not a per-call value,
  -- so this is the documented constant, never a fabricated per-row figure.
  CASE WHEN er->>'tool' = 'get_payment_history' THEN 12 ELSE NULL END
                                                              AS requested_months,
  (
    SELECT req->>'reason'
    FROM jsonb_array_elements(COALESCE(mr_evt->'detail'->'hermes'->'evidence_requests', '[]'::jsonb)) req
    WHERE req->>'tool' = er->>'tool'
    LIMIT 1
  )                                                           AS request_reason
FROM {schema}.ledger_state s,
     jsonb_array_elements(s.data->'audit') AS mr_evt,
     jsonb_array_elements(
       COALESCE(mr_evt->'detail'->'hermes'->'evidence_returned', '[]'::jsonb)) AS er
WHERE s.id = 1 AND mr_evt->>'kind' = 'AI_MODEL_RUN'
""",
        "audit_timeline": f"""
CREATE OR REPLACE VIEW {schema}.audit_timeline AS
SELECT
  (e->>'seq')::int                                          AS seq,
  (e->>'logical_time')::int                                 AS logical_time,
  e->>'case_id'                                              AS case_id,
  e->>'kind'                                                 AS kind,
  e->'detail'->>'action'                                     AS action,
  e->'detail'->>'outcome'                                    AS outcome,
  COALESCE(e->'detail'->>'reason_code', e->'detail'->>'reason')
                                                              AS reason,
  e->'detail'->>'state'                                      AS state,
  e->'detail'->>'evidence_mode'                              AS evidence_mode,
  e->'detail'                                                AS detail
FROM {schema}.ledger_state s,
     jsonb_array_elements(s.data->'audit') AS e
WHERE s.id = 1
ORDER BY (e->>'seq')::int
""",
        # demo-facing: one row per MEANINGFUL business step, chronologically,
        # for one case at a time - a filtered/translated view of the same
        # audit trail audit_timeline exposes raw. Reads ONLY ledger_state -
        # no dependency on the other views, so it can be created in any order.
        # step_number is ROW_NUMBER() over the FILTERED set's own seq order,
        # never a hardcoded case-specific integer, so this generalises to any
        # case_id. Implementation-only noise (DEMO_CASE_PROVENANCE,
        # PENDING_WORK_CANCELLED, intermediate delivery "in_progress" claims,
        # duplicate/existing-case INPUT_EVENTs) is excluded entirely.
        "demo_case_story": f"""
CREATE OR REPLACE VIEW {schema}.demo_case_story AS
WITH steps AS (
  -- PAYMENT_FAILURE_RECEIVED: only the case-opening failure, never a
  -- duplicate/existing-case/terminal-case INPUT_EVENT (those carry a 'note').
  SELECT
    e->>'case_id'                                             AS case_id,
    (e->>'seq')::int                                          AS seq,
    'PAYMENT_FAILURE_RECEIVED'                                AS stage,
    'Ingress'                                                 AS actor,
    jsonb_build_object(
      'obligation_id', e->'detail'->>'obligation_id',
      'amount_minor', (e->'detail'->>'amount_minor')::int,
      'reason_code', e->'detail'->>'reason_code')::text       AS input_or_evidence,
    NULL::text                                                 AS reasoning_or_rule,
    'case opened for insufficient_funds recovery'              AS output_or_action,
    'RECORDED'                                                 AS status,
    NULL::numeric                                              AS duration_ms
  FROM {schema}.ledger_state s, jsonb_array_elements(s.data->'audit') e
  WHERE s.id = 1 AND e->>'kind' = 'INPUT_EVENT'
    AND e->'detail'->>'type' = 'payment.failed'
    AND NOT (e->'detail' ? 'note')

  UNION ALL

  -- HERMES_DECISION: one row per AI_PROPOSAL, joined to its OWN cycle's
  -- nearest preceding AI_MODEL_RUN for tools/history/latency evidence -
  -- never a global first/last (same pattern as hermes_decisions above).
  SELECT
    p->>'case_id'                                             AS case_id,
    (p->>'seq')::int                                          AS seq,
    'HERMES_DECISION'                                          AS stage,
    'Hermes'                                                   AS actor,
    -- what Hermes actually received: the persisted evidence_returned records
    -- verbatim (tool, source, actual coverage per tool - never fabricated or
    -- re-derived here) plus whether a 12-month history lookup was requested.
    jsonb_build_object(
      'evidence_returned', COALESCE(mr.detail->'hermes'->'evidence_returned', '[]'::jsonb),
      'history_12mo_requested', EXISTS (
        SELECT 1 FROM jsonb_array_elements(COALESCE(mr.detail->'hermes'->'evidence_requests', '[]'::jsonb)) req
        WHERE req->>'tool' = 'get_payment_history'
      ))::text                                                 AS input_or_evidence,
    p->'detail'->>'rationale'                                  AS reasoning_or_rule,
    p->'detail'->>'action' || ' (recommend: '
      || COALESCE(p->'detail'->>'recommended_intervention', 'NONE') || ')'
                                                                AS output_or_action,
    'PROPOSED'                                                 AS status,
    (mr.detail->>'latency_ms')::numeric                        AS duration_ms
  FROM {schema}.ledger_state s, jsonb_array_elements(s.data->'audit') p
  LEFT JOIN LATERAL (
    SELECT e->'detail' AS detail
    FROM jsonb_array_elements(s.data->'audit') e
    WHERE e->>'case_id' = p->>'case_id' AND e->>'kind' = 'AI_MODEL_RUN'
      AND (e->>'seq')::int < (p->>'seq')::int
    ORDER BY (e->>'seq')::int DESC
    LIMIT 1
  ) mr ON true
  WHERE s.id = 1 AND p->>'kind' = 'AI_PROPOSAL'

  UNION ALL

  -- POLICY_AUTHORIZATION / RECOVERY_LINK_AUTHORIZED: one row per
  -- POLICY_DECISION, named by its OWN cycle's nearest preceding proposal -
  -- distinguishes Hermes's proposal from deterministic policy authorization.
  SELECT
    pd->>'case_id'                                             AS case_id,
    (pd->>'seq')::int                                          AS seq,
    CASE WHEN prop.action = 'CREATE_RECOVERY_LINK' THEN 'RECOVERY_LINK_AUTHORIZED'
         ELSE 'POLICY_AUTHORIZATION' END                       AS stage,
    'Policy'                                                   AS actor,
    jsonb_build_object('proposed_action', prop.action)::text   AS input_or_evidence,
    pd->'detail'->>'reason_code'                                AS reasoning_or_rule,
    CASE WHEN pd->'detail'->>'outcome' = 'ALLOW'
         THEN COALESCE(prop.action, 'ALLOW')
         ELSE pd->'detail'->>'outcome' END                      AS output_or_action,
    CASE WHEN pd->'detail'->>'outcome' = 'ALLOW' THEN 'AUTHORIZED'
         ELSE pd->'detail'->>'outcome' END                      AS status,
    NULL::numeric                                               AS duration_ms
  FROM {schema}.ledger_state s, jsonb_array_elements(s.data->'audit') pd
  LEFT JOIN LATERAL (
    SELECT e->'detail'->>'action' AS action
    FROM jsonb_array_elements(s.data->'audit') e
    WHERE e->>'case_id' = pd->>'case_id' AND e->>'kind' = 'AI_PROPOSAL'
      AND (e->>'seq')::int < (pd->>'seq')::int
    ORDER BY (e->>'seq')::int DESC
    LIMIT 1
  ) prop ON true
  WHERE s.id = 1 AND pd->>'kind' = 'POLICY_DECISION'

  UNION ALL

  -- PROVIDER_RETRY_SCHEDULED: only the 'evaluate' scheduling kind, never the
  -- 'discarded'/'evaluate_retry' bookkeeping kinds (implementation noise).
  SELECT
    e->>'case_id'                                              AS case_id,
    (e->>'seq')::int                                           AS seq,
    'PROVIDER_RETRY_SCHEDULED'                                 AS stage,
    'Recovery Engine'                                          AS actor,
    NULL::text                                                 AS input_or_evidence,
    'awaiting provider retry window'                           AS reasoning_or_rule,
    'due_time=' || COALESCE(e->'detail'->>'due_time', '')      AS output_or_action,
    'SCHEDULED'                                                AS status,
    NULL::numeric                                              AS duration_ms
  FROM {schema}.ledger_state s, jsonb_array_elements(s.data->'audit') e
  WHERE s.id = 1 AND e->>'kind' = 'SCHEDULED_ACTION' AND e->'detail'->>'kind' = 'evaluate'

  UNION ALL

  -- PROVIDER_RETRY_FAILED: a provider-owned fact, never attributed to Hermes -
  -- and never labelled "Razorpay" unless evidence_mode actually says so
  -- (today's retry integration is simulated-only; see RAZORPAY_TEST_SLICE.md).
  SELECT
    e->>'case_id'                                              AS case_id,
    (e->>'seq')::int                                           AS seq,
    'PROVIDER_RETRY_FAILED'                                    AS stage,
    CASE e->'detail'->>'evidence_mode'
      WHEN 'REAL_TEST_MODE' THEN 'Razorpay Test Mode'
      WHEN 'SIMULATED' THEN 'Payment provider (simulated)'
      ELSE 'Payment provider (unverified)'
    END                                                        AS actor,
    jsonb_build_object(
      'reason_code', e->'detail'->>'reason_code',
      'evidence_mode', e->'detail'->>'evidence_mode')::text    AS input_or_evidence,
    NULL::text                                                 AS reasoning_or_rule,
    'provider retry failed; case reactivated'                  AS output_or_action,
    'FAILED'                                                   AS status,
    NULL::numeric                                              AS duration_ms
  FROM {schema}.ledger_state s, jsonb_array_elements(s.data->'audit') e
  WHERE s.id = 1 AND e->>'kind' = 'RETRY_OUTCOME_RECORDED'

  UNION ALL

  -- RECOVERY_LINK_CREATED: the provider reference only - never the checkout URL.
  SELECT
    e->>'case_id'                                              AS case_id,
    (e->>'seq')::int                                           AS seq,
    'RECOVERY_LINK_CREATED'                                    AS stage,
    'Razorpay'                                                 AS actor,
    NULL::text                                                 AS input_or_evidence,
    NULL::text                                                 AS reasoning_or_rule,
    COALESCE(e->'detail'->>'reference', 'no reference recorded')
                                                                AS output_or_action,
    CASE WHEN e->'detail'->>'status' = 'uncertain' THEN 'UNCERTAIN' ELSE 'CREATED' END
                                                                AS status,
    NULL::numeric                                              AS duration_ms
  FROM {schema}.ledger_state s, jsonb_array_elements(s.data->'audit') e
  WHERE s.id = 1 AND e->>'kind' = 'ACTION_OUTCOME'
    AND e->'detail'->>'action' = 'CREATE_RECOVERY_LINK'

  UNION ALL

  -- MESSAGE_DRAFTED: the deterministic approved-template text - never a
  -- model-echoed / interpolated string (see adapters.py's drafting comment).
  SELECT
    e->>'case_id'                                              AS case_id,
    (e->>'seq')::int                                           AS seq,
    'MESSAGE_DRAFTED'                                          AS stage,
    'Recovery Engine'                                          AS actor,
    e->'detail'->>'message_intent'                             AS input_or_evidence,
    'deterministic approved-template rendering'                AS reasoning_or_rule,
    e->'detail'->>'message_draft'                              AS output_or_action,
    'DRAFTED'                                                  AS status,
    NULL::numeric                                              AS duration_ms
  FROM {schema}.ledger_state s, jsonb_array_elements(s.data->'audit') e
  WHERE s.id = 1 AND e->>'kind' = 'MESSAGE_DRAFTED'

  UNION ALL

  -- TELEGRAM_SENT / TELEGRAM_DELIVERY_FAILED / TELEGRAM_DELIVERY_UNCERTAIN:
  -- only the FINAL delivery result per intent (never an intermediate
  -- 'in_progress' claim) - the stage name itself carries the true outcome,
  -- never a fixed "SENT" label regardless of what actually happened.
  -- Parenthesised: an un-parenthesised trailing ORDER BY on a UNION ALL
  -- branch binds to the WHOLE union, not this SELECT, and "e" is out of
  -- scope there - this is what makes DISTINCT ON's own ORDER BY legal here.
  (SELECT DISTINCT ON (e->'detail'->>'intent_id')
    e->>'case_id'                                              AS case_id,
    (e->>'seq')::int                                           AS seq,
    CASE e->'detail'->>'outcome'
      WHEN 'sent' THEN 'TELEGRAM_SENT'
      WHEN 'failed' THEN 'TELEGRAM_DELIVERY_FAILED'
      ELSE 'TELEGRAM_DELIVERY_UNCERTAIN'
    END                                                          AS stage,
    'Telegram'                                                  AS actor,
    jsonb_build_object('channel', e->'detail'->>'channel')::text
                                                                AS input_or_evidence,
    NULL::text                                                  AS reasoning_or_rule,
    e->'detail'->>'message_id'                                  AS output_or_action,
    UPPER(e->'detail'->>'outcome')                              AS status,
    NULL::numeric                                               AS duration_ms
  FROM {schema}.ledger_state s, jsonb_array_elements(s.data->'audit') e
  WHERE s.id = 1 AND e->>'kind' = 'MESSAGE_DELIVERY_ATTEMPTED'
    AND e->'detail'->>'outcome' <> 'in_progress'
  ORDER BY e->'detail'->>'intent_id', (e->>'seq')::int DESC)
)
SELECT
  case_id                                                      AS case_id,
  ROW_NUMBER() OVER (PARTITION BY case_id ORDER BY seq)        AS step_number,
  stage                                                         AS stage,
  actor                                                         AS actor,
  input_or_evidence                                             AS input_or_evidence,
  reasoning_or_rule                                             AS reasoning_or_rule,
  output_or_action                                              AS output_or_action,
  status                                                         AS status,
  duration_ms                                                   AS duration_ms
FROM steps
""",
    }


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    load_dotenv(os.path.join(root, ".env"), override=False)


def main() -> int:
    _load_dotenv()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn or not dsn.strip():
        print("DATABASE_URL is not set. Put the Neon Postgres URL in .env, then re-run.",
              file=sys.stderr)
        return 2
    try:
        import psycopg
    except ImportError:
        print('psycopg is not installed. Run:  python -m pip install ".[db]"', file=sys.stderr)
        return 3

    empty_snapshot = json.dumps(dump_ledger(InMemoryLedger()))
    # Same bounded, IPv4-preferring connect as the running app (pg_ledger._connect_bounded) -
    # a bare psycopg.connect(dsn) here previously had no timeout and no IPv4
    # hostaddr, so a dead IPv6 route could hang this one-off script far longer
    # than the app's own startup budget ever allows.
    with _connect_bounded(psycopg, dsn, _startup_budget_s()) as conn:
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
            cur.execute(
                f"CREATE TABLE IF NOT EXISTS {SCHEMA}.ledger_state ("
                "  id integer PRIMARY KEY,"
                "  data jsonb NOT NULL,"
                "  updated_at timestamptz NOT NULL DEFAULT now()"
                ")"
            )
            cur.execute(
                f"INSERT INTO {SCHEMA}.ledger_state (id, data) VALUES (1, %s::jsonb) "
                "ON CONFLICT (id) DO NOTHING",
                (empty_snapshot,),
            )
            # Dict order is dependency order (case_summary before
            # recovery_actions, which reads it) - see _view_sql's docstring.
            for name, sql in _view_sql(SCHEMA).items():
                cur.execute(sql)
        conn.commit()

    view_names = ", ".join(_view_sql(SCHEMA))
    print(f"OK: schema '{SCHEMA}' ready; ledger_state row present; views ready "
          f"({view_names}). No data was dropped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
