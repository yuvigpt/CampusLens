-- ============================================================================
-- CampusLens - migration 016 - complaint deletion + community overview
--
-- Two additions:
--
--   1. complaints_own_delete - a student may DELETE their own complaint.
--      Every child table (complaint_scores, analysis_jobs, complaint_events,
--      investigation_notes, public_complaints) already declares ON DELETE
--      CASCADE (migrations 004/005/006/007), so one DELETE removes the whole
--      record cleanly. Admins already have complaints_admin_all (migration
--      003), which covers DELETE.
--
--   2. community_overview() - a SECURITY DEFINER function so any signed-in
--      user can see SMALL sanitized info about every campus complaint. RLS on
--      complaints deliberately hides other students' rows, and adding a SELECT
--      policy would expose the full row (description, student_id, score) to
--      any client talking to PostgREST directly. A function can expose ONLY
--      chosen columns, so that is the safe pattern - the same one migrations
--      014/015 already use for AI write-back.
--
--      Exposed: id, location, status, band (coarse), ai_category, created_at.
--      Never exposed: student_id, description, ai_summary/evidence/uncertainty,
--      priority_score, score_breakdown, confirmed_*, image_path.
--
-- SAFE TO RE-RUN.
-- Rollback: DROP POLICY IF EXISTS complaints_own_delete ON complaints;
--           DROP FUNCTION IF EXISTS public.community_overview();
-- ============================================================================

BEGIN;

-- ---- 1. Students may delete their own complaints --------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname='public'
          AND tablename='complaints' AND policyname='complaints_own_delete'
    ) THEN
        CREATE POLICY complaints_own_delete ON complaints
            FOR DELETE
            USING (student_id = (SELECT auth.uid()));
    END IF;
END
$$;

-- ---- 2. Sanitized campus-wide overview ------------------------------------
CREATE OR REPLACE FUNCTION public.community_overview()
RETURNS TABLE (
    id          uuid,
    location    text,
    status      text,
    band        text,
    ai_category text,
    created_at  timestamptz
)
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public
AS $$
    SELECT
        c.id,
        c.location_raw,
        c.status,
        CASE
            WHEN c.priority_score IS NULL THEN NULL
            WHEN c.priority_score <= 29 THEN 'Low'
            WHEN c.priority_score <= 54 THEN 'Medium'
            WHEN c.priority_score <= 74 THEN 'High'
            ELSE 'Critical'
        END,
        c.ai_category,
        c.created_at
      FROM public.complaints c
     ORDER BY c.created_at DESC
     LIMIT 500;
$$;

COMMENT ON FUNCTION public.community_overview() IS
  'Sanitized campus-wide activity feed for signed-in users: location, status, coarse band, AI category and date only. Never reporter identity, description text or numeric scores.';

REVOKE ALL ON FUNCTION public.community_overview() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.community_overview() FROM anon;
GRANT EXECUTE ON FUNCTION public.community_overview() TO authenticated;

COMMIT;
