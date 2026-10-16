-- ============================================================================
-- CampusLens - migration 008 - triggers
--
-- Keeps updated_at honest. Without a trigger the column silently goes stale,
-- because Postgres does not update it automatically on UPDATE.
--
-- Applied AFTER 003/005 so both target tables exist.
--
-- SAFE TO RE-RUN.  Rollback: DROP TRIGGER ...; (see below) then
--                  DROP FUNCTION public.touch_updated_at();
-- ============================================================================

BEGIN;

CREATE OR REPLACE FUNCTION public.touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION public.touch_updated_at() IS
  'Sets NEW.updated_at on every UPDATE. Applied to complaints and analysis_jobs.';

-- Complaints -------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_complaints_touch ON complaints;
CREATE TRIGGER trg_complaints_touch
    BEFORE UPDATE ON complaints
    FOR EACH ROW
    EXECUTE FUNCTION public.touch_updated_at();

-- Analysis jobs ----------------------------------------------------------
DROP TRIGGER IF EXISTS trg_analysis_jobs_touch ON analysis_jobs;
CREATE TRIGGER trg_analysis_jobs_touch
    BEFORE UPDATE ON analysis_jobs
    FOR EACH ROW
    EXECUTE FUNCTION public.touch_updated_at();

COMMIT;

-- No runtime probe here on purpose. An earlier version ran
--     UPDATE complaints SET description = description WHERE id = <any row>;
-- to prove the trigger fired. That test was defective in two ways:
--   * it left `updated_at` permanently advanced, because the trigger it was
--     testing overwrote the attempted restore with now();
--   * it created real row versions, advanced xmin, and would double-fire any
--     future BEFORE UPDATE trigger.
-- Verifying a trigger by writing to a live table is a test, not a migration.
-- The trigger is now inspected non-mutatingly in 011_verify.sql (presence,
-- attachment to `complaints`, binding to touch_updated_at, and function body),
-- and true runtime execution is covered by the Stage 8 test suite.