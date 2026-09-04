-- ============================================================================
--  Hermes revenue-recovery demo - read-only Neon inspection
-- ============================================================================
--  Paste any block below into the Neon SQL editor (or psql) while the local
--  app is running. Every statement is a SELECT: no INSERT / UPDATE / DELETE /
--  DDL, no credentials. SELECTs do not contend for the app's session-scoped
--  advisory *writer* lock, so these are safe to run while `hermes` mode holds
--  it.
--
--  Storage is unchanged - one JSONB snapshot row:
--    schema : hermes_demo              (override with HERMES_DEMO_SCHEMA before
--                                       `python scripts/init_neon.py`, then
--                                       search-and-replace hermes_demo below)
--    table  : hermes_demo.ledger_state (id = 1; data = whole-ledger snapshot)
--
--  Snapshot shape (hermes.pg_ledger.dump_ledger):
--    data->'cases'          : { case_id -> case object }
--    data->'audit'          : [ { seq, logical_time, case_id, kind, detail } ]
--    data->'action_intents' : { intent_id -> intent object }
--    data->>'recovered_minor': integer paise, counted once
--
--  Blocks 2..5 filter one case: replace the literal 'REPLACE_WITH_CASE_ID'
--  with the id the CLI printed (e.g. 'case-1').
-- ============================================================================


-- 0. snapshot freshness -----------------------------------------------------
SELECT id,
       updated_at,
       (data->>'clock')::int           AS logical_clock,
       (data->>'recovered_minor')::int AS recovered_minor_total_paise,
       (SELECT count(*) FROM jsonb_object_keys(data->'cases')) AS case_count,
       jsonb_array_length(data->'audit')                       AS audit_event_count
FROM   hermes_demo.ledger_state
WHERE  id = 1;


-- 1. every case: id, status, simulated recovered amount --------------------
SELECT c.key                                       AS case_id,
       c.value->>'obligation_id'                   AS obligation_id,
       c.value->>'state'                           AS status,
       (c.value->>'counted')::boolean              AS counted_once,
       COALESCE((c.value->>'amount_minor')::int,0) AS amount_paise,
       CASE WHEN (c.value->>'counted')::boolean
            THEN (c.value->>'amount_minor')::int ELSE 0 END
                                                   AS simulated_recovered_paise,
       c.value->>'attribution'                     AS attribution,
       c.value->>'failure_reason'                  AS failure_reason,
       (c.value->>'version')::int                  AS version
FROM   hermes_demo.ledger_state s,
       jsonb_each(s.data->'cases') AS c
WHERE  s.id = 1
ORDER  BY (c.value->>'created_time')::int;


-- 2. chronological audit timeline for ONE case ---------------------------
SELECT (e->>'seq')::int          AS seq,
       (e->>'logical_time')::int AS t,
       e->>'kind'                AS kind,
       e->'detail'              AS detail
FROM   hermes_demo.ledger_state s,
       jsonb_array_elements(s.data->'audit') AS e
WHERE  s.id = 1
  AND  e->>'case_id' = 'REPLACE_WITH_CASE_ID'
ORDER  BY (e->>'seq')::int;


-- 3. ACTUAL Hermes evidence, proposal and policy result for ONE case ----
--    AI_MODEL_RUN.detail->'hermes' is the bounded, redacted Hermes audit
--    (runtime revision, provider/model, evidence requests + returned
--    source/coverage, uncalibrated confidence band, decision action,
--    failure category/stage). AI_PROPOSAL / POLICY_DECISION are engine rows.
SELECT (e->>'seq')::int                          AS seq,
       (e->>'logical_time')::int                 AS t,
       e->>'kind'                                AS kind,
       e->'detail'->>'model'                     AS model,
       e->'detail'->'hermes'->>'runtime_revision'  AS hermes_revision,
       e->'detail'->'hermes'->>'decision_action'   AS hermes_decision_action,
       e->'detail'->'hermes'->>'confidence_band'   AS confidence_band,
       e->'detail'->'hermes'->>'confidence_basis'  AS confidence_basis,
       e->'detail'->'hermes'->'evidence_requests'  AS evidence_requests,
       e->'detail'->'hermes'->'evidence_returned'  AS evidence_returned,
       e->'detail'->'hermes'->>'failure_category'  AS failure_category,
       e->'detail'->>'validation_result'           AS validation_result,
       e->'detail'->>'action'                      AS proposal_action,
       e->'detail'->>'outcome'                     AS policy_outcome,
       e->'detail'->>'reason_code'                 AS policy_reason
FROM   hermes_demo.ledger_state s,
       jsonb_array_elements(s.data->'audit') AS e
WHERE  s.id = 1
  AND  e->>'case_id' = 'REPLACE_WITH_CASE_ID'
  AND  e->>'kind' IN ('AI_MODEL_RUN','AI_PROPOSAL','POLICY_DECISION',
                      'ACTION_INTENT','ACTION_OUTCOME','TERMINAL_TRANSITION')
ORDER  BY (e->>'seq')::int;


-- 4. authorized recovery-link intents (simulated; never a real link) ----
SELECT i.value->>'intent_id'            AS intent_id,
       i.value->>'case_id'              AS case_id,
       i.value->>'action'               AS action,
       i.value->>'status'               AS status,
       i.value->>'reference'            AS simulated_reference,
       (i.value->>'message_sent')::boolean AS message_sent
FROM   hermes_demo.ledger_state s,
       jsonb_each(s.data->'action_intents') AS i
WHERE  s.id = 1
ORDER  BY (i.value->>'created_time')::int;


-- 5. one-line recovery summary for ONE case ---------------------------
SELECT c.key             AS case_id,
       c.value->>'state'  AS status,
       CASE WHEN (c.value->>'counted')::boolean
            THEN (c.value->>'amount_minor')::int ELSE 0 END AS simulated_recovered_paise,
       c.value->>'attribution' AS attribution,
       (SELECT count(*) FROM jsonb_array_elements(s.data->'audit') a
         WHERE a->>'case_id' = c.key)                       AS audit_event_count,
       (SELECT count(*) FROM jsonb_array_elements(s.data->'audit') a
         WHERE a->>'case_id' = c.key AND a->>'kind' = 'AI_MODEL_RUN') AS hermes_decisions
FROM   hermes_demo.ledger_state s,
       jsonb_each(s.data->'cases') AS c
WHERE  s.id = 1
  AND  c.key = 'REPLACE_WITH_CASE_ID';
