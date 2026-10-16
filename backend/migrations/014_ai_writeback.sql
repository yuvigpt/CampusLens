-- ============================================================================
-- CampusLens - migration 014 - AI write-back for the system identity
--
-- Problem
--   submit_complaint runs the AI synchronously and then stores the suggestion
--   on the complaint row via `_store_suggestion`, which opens a session as
--   Identity(complaint_id, "system"). database.session() always executes
--   `SET LOCAL ROLE authenticated` plus claims {"sub": <complaint id>,
--   "role": "system"}. On public.complaints the only policies are
--   complaints_own_read (SELECT), complaints_own_insert (INSERT) and
--   complaints_admin_all (ALL, is_admin()). No UPDATE policy is satisfied by
--   the system identity, so PostgreSQL silently updates ZERO rows - no error,
--   no warning - and every ai_* column stays NULL. The admin card's
--   "Full AI assessment" then always shows "Not provided".
--
--   The same identity also fails to record AI failures: the INSERT into
--   analysis_jobs violates jobs_own_insert / jobs_admin_all WITH CHECK and
--   raises 42501 (swallowed by `_record_failure`).
--
-- Fix
--   Two narrow SECURITY DEFINER functions - the same elevation pattern as
--   is_admin() (001) and promote_to_admin() (010):
--
--     store_ai_suggestion(...)  updates EXACTLY the seven ai_* columns of one
--                               complaint id. There are no parameters for
--                               priority_score, status or anything else, so
--                               this can never become a scoring backdoor.
--     record_job_failure(...)   the existing analysis_jobs upsert, elevated.
--
--   Both run as the function owner, so no RLS policy is widened for anyone:
--   authenticated gains EXECUTE and nothing else; anon and PUBLIC get nothing.
--   The backend keeps opening its session as `system` - only the statement it
--   executes changes (SELECT public.store_ai_suggestion(...)).
--
-- SAFE TO RE-RUN (CREATE OR REPLACE + idempotent grants).
-- Rollback:
--   DROP FUNCTION IF EXISTS public.store_ai_suggestion(uuid, text, text, text, text, text, text, text);
--   DROP FUNCTION IF EXISTS public.record_job_failure(uuid, integer, text);
-- ============================================================================

BEGIN;

CREATE OR REPLACE FUNCTION public.store_ai_suggestion(
    p_complaint_id  uuid,
    p_ai_category   text,
    p_ai_summary    text,
    p_ai_evidence   text,
    p_ai_uncertainty text,
    p_ai_urgency    text,
    p_ai_impact     text,
    p_ai_safety     text
)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    UPDATE public.complaints
       SET ai_category    = p_ai_category,
           ai_summary     = p_ai_summary,
           ai_evidence    = p_ai_evidence,
           ai_uncertainty = p_ai_uncertainty,
           ai_urgency     = p_ai_urgency,
           ai_impact      = p_ai_impact,
           ai_safety      = p_ai_safety
     WHERE id = p_complaint_id;
$$;

COMMENT ON FUNCTION public.store_ai_suggestion(uuid, text, text, text, text, text, text, text) IS
  'Writes ONLY the seven ai_* columns for one complaint. SECURITY DEFINER because the system session (SET LOCAL ROLE authenticated, sub = complaint id) matches no UPDATE policy on complaints; without elevation the write is silently filtered to 0 rows.';

REVOKE ALL ON FUNCTION public.store_ai_suggestion(uuid, text, text, text, text, text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.store_ai_suggestion(uuid, text, text, text, text, text, text, text) FROM anon;
GRANT EXECUTE ON FUNCTION public.store_ai_suggestion(uuid, text, text, text, text, text, text, text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.store_ai_suggestion(uuid, text, text, text, text, text, text, text) TO service_role;


-- ---------------------------------------------------------------------------
-- Second half: recording an AI failure as the system identity.
-- The statement is byte-for-byte the old database.record_job_failure SQL,
-- merely elevated so the WITH CHECK policies stop rejecting it.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.record_job_failure(
    p_complaint_id uuid,
    p_attempts     integer,
    p_error        text
)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    INSERT INTO public.analysis_jobs
        (complaint_id, status, attempts, last_error, next_retry_at)
    VALUES (p_complaint_id, 'failed', p_attempts, left(p_error, 500), now())
    ON CONFLICT (complaint_id) WHERE status IN ('pending','running')
    DO UPDATE SET status     = 'failed',
                  attempts   = EXCLUDED.attempts,
                  last_error = EXCLUDED.last_error,
                  updated_at = now();
$$;

COMMENT ON FUNCTION public.record_job_failure(uuid, integer, text) IS
  'Records one AI failure on analysis_jobs for the system session, which has no INSERT/UPDATE policy of its own. Never touches complaints.';

REVOKE ALL ON FUNCTION public.record_job_failure(uuid, integer, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.record_job_failure(uuid, integer, text) FROM anon;
GRANT EXECUTE ON FUNCTION public.record_job_failure(uuid, integer, text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.record_job_failure(uuid, integer, text) TO service_role;

COMMIT;

-- ============================================================================
-- READ-ONLY verification - run AFTER applying, never modifies anything
-- ============================================================================
-- 1. Both functions exist and are SECURITY DEFINER:
--    SELECT p.proname, p.prosecdef, pg_get_function_identity_arguments(p.oid)
--      FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
--     WHERE n.nspname = 'public'
--       AND p.proname IN ('store_ai_suggestion', 'record_job_failure');
--    -- expect 2 rows, both prosecdef = true
--
-- 2. anon cannot execute them:
--    SELECT grantee, privilege_type FROM information_schema.routine_privileges
--     WHERE routine_name = 'store_ai_suggestion';
--    -- expect authenticated + service_role only (no anon, no PUBLIC)
--
-- 3. End-to-end (rolls back - persists nothing):
--    BEGIN;
--    SET LOCAL ROLE authenticated;
--    SELECT set_config('request.jwt.claims',
--           '{"sub":"<a complaint uuid>","role":"system"}', true);
--    SELECT public.store_ai_suggestion('<same uuid>', 'Cat', 'Sum', NULL,
--                                      NULL, 'Low', 'Low', 'Low');
--    SELECT ai_category, ai_summary FROM public.complaints
--     WHERE id = '<same uuid>';   -- expect Cat / Sum
--    ROLLBACK;
-- ============================================================================
