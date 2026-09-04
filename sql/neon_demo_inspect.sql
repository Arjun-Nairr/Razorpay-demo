-- ============================================================================
--  Hermes revenue-recovery demo - read-only Neon inspection
-- ============================================================================
--  Paste any block below into the Neon SQL editor (or psql) while the local
--  app is running. Every statement is a SELECT: no INSERT / UPDATE / DELETE /
--  DDL, no credentials. SELECTs do not contend for the app's session-scoped
--  advisory *writer* lock, so these are safe to run while `hermes` mode holds
--  it.
--
--  Storage is unchanged - ONE JSONB snapshot row is still the single
--  authoritative source (`hermes_demo.ledger_state`, id = 1). The five views
--  below (added by `scripts/init_neon.py`; re-run it any time to refresh them
--  after a code change - it only ever does CREATE OR REPLACE VIEW) are a
--  read-only PRESENTATION layer over that same row - nothing is duplicated
--  or made mutable, and Neon's table/view browser can display them directly
--  instead of everyone hand-unpacking JSON:
--
--    hermes_demo.case_summary      - one row per case; authoritative `state`
--                                    plus a derived, presentation-only
--                                    `display_status` (RECOVERED /
--                                    HUMAN_REVIEW_REQUIRED /
--                                    RECOVERY_IN_PROGRESS /
--                                    WAITING_FOR_PROVIDER_RETRY / ACTIVE)
--    hermes_demo.hermes_decisions  - one row per AI_PROPOSAL, joined to its
--                                    OWN decision cycle's nearest AI_MODEL_RUN
--                                    and POLICY_DECISION (never a global
--                                    first/last)
--    hermes_demo.recovery_actions  - one row per durable action intent;
--                                    `checkout_url_present` only, never the
--                                    full URL; `message_authorized` vs
--                                    `message_sent` kept separate
--    hermes_demo.hermes_evidence   - one row per evidence tool call, with its
--                                    requested reason alongside what came back
--    hermes_demo.audit_timeline    - one row per raw audit event (bounded
--                                    `detail` JSON kept for full inspection)
--
--  The raw JSON is still there if you need something these views don't
--  surface - see "raw snapshot" at the bottom.
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


-- ============================================================================
--  Demo queries: ALL CASES
-- ============================================================================

-- 1. every case: authoritative state + derived display status --------------
SELECT case_id, obligation_id, state, display_status, amount_minor, currency,
       recovered_amount_minor, evidence_mode, attribution, counted,
       human_review_required, created_logical_time
FROM   hermes_demo.case_summary
ORDER  BY created_logical_time;

-- 2. every real Test Mode recovery action (any case) ------------------------
SELECT case_id, intent_id, proposed_action, execution_status, provider_reference,
       checkout_url_present, action_evidence_mode, message_authorized, message_sent,
       case_state, human_review_required, uncertain_reason
FROM   hermes_demo.recovery_actions
ORDER  BY created_logical_time;

-- 3. every Hermes/Gemini decision (any case), most recent first -------------
SELECT case_id, decision_number, logical_time, model, hermes_runtime_revision,
       execution_duration_seconds, latency_ms, validation_result, repair_used,
       confidence, confidence_band, proposed_action, policy_outcome, authorized
FROM   hermes_demo.hermes_decisions
ORDER  BY logical_time DESC;


-- ============================================================================
--  Demo queries: ONE case (replace 'REPLACE_WITH_CASE_ID', e.g. 'case-18')
-- ============================================================================

-- 4. one-line case summary --------------------------------------------------
SELECT * FROM hermes_demo.case_summary WHERE case_id = 'REPLACE_WITH_CASE_ID';

-- 5. its recovery action(s) --------------------------------------------------
SELECT * FROM hermes_demo.recovery_actions WHERE case_id = 'REPLACE_WITH_CASE_ID'
ORDER BY created_logical_time;

-- 6. its Hermes/Gemini decisions, in order -----------------------------------
SELECT * FROM hermes_demo.hermes_decisions WHERE case_id = 'REPLACE_WITH_CASE_ID'
ORDER BY decision_number;

-- 7. its evidence tool calls (what was requested vs what came back) ---------
SELECT * FROM hermes_demo.hermes_evidence WHERE case_id = 'REPLACE_WITH_CASE_ID'
ORDER BY model_run_seq;

-- 8. its full chronological audit timeline -----------------------------------
SELECT seq, logical_time, kind, action, outcome, reason, state, evidence_mode, detail
FROM   hermes_demo.audit_timeline
WHERE  case_id = 'REPLACE_WITH_CASE_ID'
ORDER  BY seq;


-- ============================================================================
--  Raw snapshot (only if a view above doesn't cover what you need)
-- ============================================================================

-- 9. raw case JSON for one case ----------------------------------------------
SELECT data->'cases'->'REPLACE_WITH_CASE_ID' AS raw_case
FROM   hermes_demo.ledger_state WHERE id = 1;

-- 10. raw action_intents JSON -------------------------------------------------
SELECT i.key AS intent_id, i.value AS raw_intent
FROM   hermes_demo.ledger_state s, jsonb_each(s.data->'action_intents') AS i
WHERE  s.id = 1 AND i.value->>'case_id' = 'REPLACE_WITH_CASE_ID';
