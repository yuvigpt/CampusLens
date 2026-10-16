-- ============================================================================
-- CampusLens - migration 015 - automatic AI scoring (no manual confirmation)
--
-- Product rule change (mirrors migration 014's pattern and reasoning):
-- the admin no longer types urgency/impact/safety to produce a score.
-- Instead the score is computed automatically from the AI suggestion's own
-- levels the moment the suggestion is stored, via the same narrow
-- SECURITY DEFINER elevation:
--
--     store_auto_score(...)     reads the suggestion's ai_urgency /
--                               ai_impact / ai_safety, scores them with the
--                               deterministic scorer, and persists
--                               priority_score + score_breakdown + history +
--                               audit event - nothing else.
--
-- Integrity rules (enforced HERE, not in callers):
--
--   1. ai_* ONLY IN: only the suggestion's own levels are read. There is no
--      parameter for confirmed levels, manual levels, scores or statuses.
--   2. NON-FATAL OUT: the function traps every failure internally and reports
--      it in the `scored` OUT flag instead of raising, so a scoring hiccup
--      can NEVER roll back the stored suggestion.
--   3. NO RE-SCORE: a row that already has a priority_score is left alone
--      (score_confirmed flag). AI re-runs and admin status changes do not
--      silently move a score.
--   4. DEFAULTS, NEVER GUESSED-RANKING: a missing level scores as Low (0),
--      exactly like the student estimate path; the band is derived from the
--      number by the agreed boundaries.
--
-- SAFE TO RE-RUN (CREATE OR REPLACE + idempotent grants).
-- Rollback:
--   DROP FUNCTION IF EXISTS public.store_auto_score(uuid, uuid);
-- ============================================================================

BEGIN;

-- Widen the history trigger reason for automatic scoring. The 004 CHECK only
-- allows admin_confirm/status_change; without this, every ai_auto history
-- row would violate the constraint (the function's EXCEPTION block would
-- then swallow the whole score as scored=false - safe, but wrong).
DO $$
DECLARE
    v_name text;
BEGIN
    SELECT conname INTO v_name
      FROM pg_constraint
     WHERE conrelid = 'public.complaint_scores'::regclass
       AND contype = 'c'
       AND pg_get_constraintdef(oid) LIKE '%trigger_reason%';
    IF v_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE public.complaint_scores DROP CONSTRAINT %I', v_name);
    END IF;
END
$$;
ALTER TABLE public.complaint_scores
  ADD CONSTRAINT complaint_scores_trigger_reason_check
  CHECK (trigger_reason IN ('admin_confirm', 'status_change', 'ai_auto'));

-- Deterministic scorer, in the database, reading only ai_* levels.
-- The arithmetic intentionally mirrors scoring.score_complaint for the
-- Low/Medium/High ladder; age contributes 0 at submission time (a fresh
-- complaint has age_days 0) and recurrence contributes 0 (reference data is
-- unavailable, same rule as the student estimate).
CREATE OR REPLACE FUNCTION public.store_auto_score(
    p_complaint_id uuid,
    p_actor_id uuid
)
RETURNS TABLE(scored boolean, score numeric, band text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_urgency text;
    v_impact  text;
    v_safety  text;
    v_u numeric := 0;
    v_i numeric := 0;
    v_s numeric := 0;
    v_total numeric;
    v_band text;
    v_band_raw text;
    v_existing numeric;
BEGIN
    -- Rule 3: never silently re-score.
    SELECT priority_score INTO v_existing
      FROM public.complaints WHERE id = p_complaint_id;
    IF v_existing IS NOT NULL THEN
        scored := false; score := v_existing; band := NULL;
        RETURN NEXT;
        RETURN;
    END IF;

    -- Rule 1: ai_* only, read straight off the row the suggestion was stored on.
    SELECT ai_urgency, ai_impact, ai_safety
      INTO v_urgency, v_impact, v_safety
      FROM public.complaints WHERE id = p_complaint_id;
    IF NOT FOUND THEN
        scored := false; score := NULL; band := NULL;
        RETURN NEXT;
        RETURN;
    END IF;

    -- Rule 4: missing levels default to Low (0), never a guessed ranking.
    v_u := CASE lower(coalesce(v_urgency, 'low'))
             WHEN 'high' THEN 30 WHEN 'medium' THEN 15 ELSE 0 END;
    v_i := CASE lower(coalesce(v_impact, 'low'))
             WHEN 'high' THEN 25 WHEN 'medium' THEN 12 ELSE 0 END;
    v_s := CASE lower(coalesce(v_safety, 'low'))
             WHEN 'high' THEN 10 WHEN 'medium' THEN 5 ELSE 0 END;

    v_total := v_u + v_i + v_s;
    v_band := CASE
        WHEN v_total <= 29 THEN 'Low'
        WHEN v_total <= 54 THEN 'Medium'
        WHEN v_total <= 74 THEN 'High'
        ELSE 'Critical' END;
    v_band_raw := v_band;
    -- Safety floor: High safety can never band Low (D3).
    IF lower(coalesce(v_safety, 'low')) = 'high' AND v_band = 'Low' THEN
        v_band := 'Medium';
    END IF;


    BEGIN
        UPDATE public.complaints
           SET priority_score = v_total,
               score_breakdown = jsonb_build_object(
                   'urgency', jsonb_build_object('level', coalesce(v_urgency, 'Low'), 'points', v_u, 'max', 30),
                   'impact', jsonb_build_object('level', coalesce(v_impact, 'Low'), 'points', v_i, 'max', 25),
                   'recurrence', jsonb_build_object('count', 0, 'points', 0, 'max', 20, 'not_applicable', true),
                   'age', jsonb_build_object('days', 0, 'points', 0, 'max', 15),
                   'safety', jsonb_build_object('level', coalesce(v_safety, 'Low'), 'points', v_s, 'max', 10),
                   'total', v_total,
                   'band', v_band,
                   'max_possible', 100,
                   'version', 'v1-auto',
                   'source', 'ai_auto'
               ),
               score_computed_at = now()
         WHERE id = p_complaint_id;

        INSERT INTO public.complaint_scores
            (complaint_id, age_days, recurrence_count, score, band, band_raw,
             safety_floor_applied, trigger_reason)
        VALUES (p_complaint_id, 0, 0, v_total, v_band, v_band_raw,
                v_band <> v_band_raw, 'ai_auto');

        INSERT INTO public.complaint_events
            (complaint_id, actor_id, actor_role, event_type, to_value)
        VALUES (p_complaint_id, p_actor_id, 'system', 'scored', v_band);

        scored := true; score := v_total; band := v_band;
    EXCEPTION WHEN OTHERS THEN
        -- Rule 2: a scoring hiccup must never roll back the suggestion.
        scored := false; score := NULL; band := NULL;
    END;
    RETURN NEXT;
END;
$$;

COMMENT ON FUNCTION public.store_auto_score(uuid, uuid) IS
  'Automatic AI scoring: scores the stored ai_* levels deterministically and persists score + history + audit event. Never re-scores. Never raises (reports scored=false instead).';

REVOKE ALL ON FUNCTION public.store_auto_score(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.store_auto_score(uuid, uuid) FROM anon;
GRANT EXECUTE ON FUNCTION public.store_auto_score(uuid, uuid) TO authenticated;
GRANT EXECUTE ON FUNCTION public.store_auto_score(uuid, uuid) TO service_role;

COMMIT;

-- ============================================================================
-- READ-ONLY verification - run AFTER applying, never modifies anything
-- ============================================================================
-- SELECT p.proname, p.prosecdef FROM pg_proc p
--   JOIN pg_namespace n ON n.oid = p.pronamespace
--  WHERE n.nspname = 'public' AND p.proname = 'store_auto_score';
-- -- expect 1 row, prosecdef = true
--
-- End-to-end (rolls back - persists nothing):
--   BEGIN;
--   SET LOCAL ROLE authenticated;
--   SELECT set_config('request.jwt.claims', '{"sub":"<uuid>","role":"system"}', true);
--   SELECT * FROM public.store_auto_score('<uuid>', NULL);
--   ROLLBACK;
-- ============================================================================
