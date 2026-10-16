-- ============================================================================
-- CampusLens - migration 013 - submission INSERT policies
--
-- A submission writes three rows in one transaction:
--   1. public.complaints      (student may INSERT via complaints_own_insert)
--   2. public.complaint_events (step 2, record_created_event)
--   3. public.analysis_jobs   (step 3, enqueue_analysis_job - while AI is on)
--
-- Migrations 005 and 006 granted students only FOR SELECT on tables 2 and 3,
-- so step 2 is denied with 42501 InsufficientPrivilege, the transaction rolls
-- back, and the API answers 503 "Could not save your complaint. Please retry."
--
-- This file adds exactly two narrow FOR INSERT policies, one per table, each
-- WITH CHECK-scoped to the caller's OWN complaints. No existing policy is
-- changed, no UPDATE/DELETE is granted, and admin behaviour is untouched.
--
-- SAFE TO RE-RUN.  Rollback:
--   DROP POLICY IF EXISTS events_own_insert ON public.complaint_events;
--   DROP POLICY IF EXISTS jobs_own_insert   ON public.analysis_jobs;
-- ============================================================================

BEGIN;

-- A student may append the 'created' audit event to ONE OF THEIR OWN
-- complaints - identified through the referenced row, never trusted input.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename  = 'complaint_events'
          AND policyname = 'events_own_insert'
    ) THEN
        CREATE POLICY events_own_insert ON public.complaint_events
            FOR INSERT
            WITH CHECK (EXISTS (
                SELECT 1
                FROM public.complaints c
                WHERE c.id = complaint_events.complaint_id
                  AND c.student_id = auth.uid()
            ));
    END IF;
END
$$;

-- A student may enqueue an analysis job for ONE OF THEIR OWN complaints.
-- Same ownership proof as above. Without this the same 503 reappears the
-- moment AI analysis is enabled.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename  = 'analysis_jobs'
          AND policyname = 'jobs_own_insert'
    ) THEN
        CREATE POLICY jobs_own_insert ON public.analysis_jobs
            FOR INSERT
            WITH CHECK (EXISTS (
                SELECT 1
                FROM public.complaints c
                WHERE c.id = analysis_jobs.complaint_id
                  AND c.student_id = auth.uid()
            ));
    END IF;
END
$$;

COMMIT;

-- ============================================================================
-- READ-ONLY verification - run AFTER applying, never modifies anything
-- ============================================================================
-- SELECT tablename, policyname, cmd
-- FROM pg_policies
-- WHERE schemaname = 'public'
--   AND tablename IN ('complaint_events', 'analysis_jobs')
-- ORDER BY tablename, policyname;
--
-- EXPECT:
--   analysis_jobs   | jobs_admin_all  | ALL
--   analysis_jobs   | jobs_own_insert | INSERT
--   analysis_jobs   | jobs_own_read   | SELECT
--   complaint_events| events_admin_all| ALL
--   complaint_events| events_own_insert| INSERT
--   complaint_events| events_own_read | SELECT
--
-- SIX rows, two of them INSERT. If either INSERT row is missing, the 503
-- persists for that table.
