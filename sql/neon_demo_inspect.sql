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
--                                    first/last); `recommended_intervention` /
--                                    `model_human_review_recommended` /
--                                    `model_human_review_reason` are the
--                                    model's non-executable advisory -
--                                    'NOT_RECORDED'/null on a pre-milestone row
--    hermes_demo.recovery_actions  - one row per durable action intent;
--                                    `checkout_url_present` only, never the
--                                    full URL; `message_authorized` vs
--                                    `message_sent` kept separate;
--                                    `message_status` is the draft lifecycle
--                                    (NOT_REQUESTED/SUPPRESSED/AUTHORIZED/
--                                    DRAFTED/SENT - 'LEGACY_NOT_STAGED' on a
--                                    pre-milestone row, never DRAFTED/SENT)
--    hermes_demo.hermes_evidence   - one row per evidence tool call, with its
--                                    requested reason alongside what came back
--    hermes_demo.audit_timeline    - one row per raw audit event (bounded
--                                    `detail` JSON kept for full inspection)
--    hermes_demo.demo_case_story   - ONE case's recovery journey, one
--                                    meaningful business step per row
--                                    (PAYMENT_FAILURE_RECEIVED /
--                                    HERMES_DECISION / POLICY_AUTHORIZATION /
--                                    RECOVERY_LINK_AUTHORIZED /
--                                    PROVIDER_RETRY_SCHEDULED /
--                                    PROVIDER_RETRY_FAILED /
--                                    RECOVERY_LINK_CREATED / MESSAGE_DRAFTED /
--                                    TELEGRAM_SENT), implementation noise
--                                    filtered out, `step_number` derived from
--                                    audit order after filtering - this is
--                                    the RECOMMENDED query for recording the
--                                    demo (see "primary recording query"
--                                    below)
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
--  RECOMMENDED Neon SQL Editor query for the recording: one case's complete
--  recovery journey, chronologically, one meaningful business step per row.
-- ============================================================================
SELECT
  step_number,
  stage,
  actor,
  input_or_evidence,
  reasoning_or_rule,
  output_or_action,
  status,
  duration_ms
FROM hermes_demo.demo_case_story
WHERE case_id = 'case-40'
ORDER BY step_number;


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
       message_intent, message_draft, message_status,
       delivery_channel, delivery_status, delivery_message_id, delivery_attempted_time,
       case_state, human_review_required, uncertain_reason
FROM   hermes_demo.recovery_actions
ORDER  BY created_logical_time;

-- 3. every Hermes/Gemini decision (any case), most recent first -------------
SELECT case_id, decision_number, logical_time, model, hermes_runtime_revision,
       execution_duration_seconds, latency_ms, validation_result, repair_used,
       confidence, confidence_band, proposed_action, recommended_intervention,
       model_human_review_recommended, model_human_review_reason,
       payment_plan_eligible, payment_plan_prior_difficulty_count,
       policy_outcome, authorized
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
