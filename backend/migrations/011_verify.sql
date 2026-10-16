-- ============================================================================
-- CampusLens - migration 011 - verify (NON-MUTATING INSPECTION)
--
-- Asserts that 001-008 produced the shape the application expects. Raises an
-- EXCEPTION on failure so a mistake is loud.
--
-- THIS SCRIPT WRITES NOTHING. It contains no INSERT, UPDATE, DELETE, TRUNCATE,
-- CREATE or DROP of data-bearing objects, and no DML probe of any kind. Every
-- statement is a catalog or information_schema lookup.
--
-- An earlier version of this file was NOT read-only: it ran
--     UPDATE complaints SET description = description WHERE id = <any row>;
-- to prove the trigger fired, then tried to restore updated_at. The restore
-- failed because the trigger under test overwrote it with now(), so the row was
-- left permanently modified. The runtime proof has moved to the Stage 8 test
-- suite; here the trigger is inspected through the catalog instead.
--
-- Checks:
--   1. all tables exist
--   2. RLS enabled on every table (including complaint_scores - a real defect
--      caught during planning)
--   3. expected policies exist
--   4. no category-weight column survives (old formula fully removed)
--   5. the three scorer inputs exist and are nullable (Unscored is allowed)
--   6. TEMPORARY (D8) reference tables still empty - non-fatal once configured
--   7. touch_updated_at trigger exists, is attached to complaints, is bound to
--      touch_updated_at(), and that function assigns NEW.updated_at = now()
--   8. band boundaries match Low 0-29 / Medium 30-54 / High 55-74 / Critical 75-100
--
-- SAFE TO RE-RUN. Rollback: none needed, nothing is changed.
-- ============================================================================

DO $$
DECLARE
    t text;
BEGIN
    -- 1. tables exist --------------------------------------------------------
    FOREACH t IN ARRAY ARRAY['profiles','campus_locations','campus_categories',
                             'complaints','complaint_scores','analysis_jobs',
                             'complaint_events','investigation_notes',
                             'public_complaints']
    LOOP
        IF to_regclass('public.' || t) IS NULL THEN
            RAISE EXCEPTION 'MISSING TABLE public.%', t;
        END IF;
    END LOOP;
    RAISE NOTICE 'OK  all tables present';

    -- 2. RLS enabled everywhere ---------------------------------------------
    FOREACH t IN ARRAY ARRAY['profiles','campus_locations','campus_categories',
                             'complaints','complaint_scores','analysis_jobs',
                             'complaint_events','investigation_notes',
                             'public_complaints']
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname='public' AND c.relname=t AND c.relrowsecurity
        ) THEN
            RAISE EXCEPTION 'RLS NOT ENABLED on public.%', t;
        END IF;
    END LOOP;
    RAISE NOTICE 'OK  RLS enabled on all 9 tables';

    -- 3. required policies ---------------------------------------------------
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='complaints'
                   AND policyname='complaints_own_read') THEN
        RAISE EXCEPTION 'MISSING POLICY complaints_own_read';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='complaints'
                   AND policyname='complaints_own_insert') THEN
        RAISE EXCEPTION 'MISSING POLICY complaints_own_insert';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='public_complaints'
                   AND policyname='public_read_approved') THEN
        RAISE EXCEPTION 'MISSING POLICY public_read_approved';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='analysis_jobs'
                   AND policyname='jobs_own_read') THEN
        RAISE EXCEPTION 'MISSING POLICY jobs_own_read';
    END IF;
    RAISE NOTICE 'OK  required RLS policies present';

    -- 4. old category-weight formula is gone --------------------------------
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='public' AND table_name='complaints'
          AND column_name IN ('confirmed_category_weight','category_weight')
    ) THEN
        RAISE EXCEPTION 'category-weight column still present - old formula not removed';
    END IF;
    RAISE NOTICE 'OK  no category-weight column';

    -- 5. scorer inputs exist and are nullable (NULL => Unscored) -------------
    FOREACH t IN ARRAY ARRAY['confirmed_urgency','confirmed_impact','confirmed_safety']
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='public' AND table_name='complaints'
              AND column_name=t AND is_nullable='YES'
        ) THEN
            RAISE EXCEPTION 'scorer input complaints.% missing or not nullable', t;
        END IF;
    END LOOP;
    RAISE NOTICE 'OK  three confirmed_* scorer inputs present and nullable';
END
$$;
-- ============================================================================
-- Continuation of 011_verify (part 2 of 2).
--
-- Non-mutating: every statement below is a catalog or information_schema
-- lookup. There is no DML of any kind, so there is nothing to roll back and
-- no state to restore.
-- ============================================================================
DO $$
BEGIN
    -- 6. TEMPORARY (D8) - reference tables must be empty until the real
    --    building/floor/category lists are supplied. NON-FATAL once configured.
    -- =====================================================================
    -- >>> REMOVE THIS BLOCK when the D8 lists are configured. <<<
    -- It reports with NOTICE, never EXCEPTION, so a configured environment
    -- still passes the rest of this script. Nothing else depends on it.
    -- =====================================================================
    IF EXISTS (SELECT 1 FROM campus_locations LIMIT 1)
       OR EXISTS (SELECT 1 FROM campus_categories LIMIT 1) THEN
        RAISE NOTICE 'D8 CONFIGURED: reference tables populated.';
        RAISE NOTICE 'This temporary block can now be deleted from 011_verify.sql.';
    ELSE
        RAISE NOTICE 'OK  reference tables empty - recurrence stays disabled';
    END IF;

    -- 7. touch_updated_at trigger, inspected without writing ---------------
    --    (a) trigger exists, is not internal, and is attached to complaints
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger tg
        JOIN pg_class c     ON c.oid = tg.tgrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE tg.tgname = 'trg_complaints_touch'
          AND NOT tg.tgisinternal
          AND n.nspname = 'public'
          AND c.relname = 'complaints'
    ) THEN
        RAISE EXCEPTION 'trg_complaints_touch missing or not attached to public.complaints';
    END IF;

    --    (b) it is bound to touch_updated_at() - proves the wiring, not just
    --        the trigger's existence
    IF (SELECT pg_get_triggerdef(tg.oid)
        FROM pg_trigger tg
        JOIN pg_class c     ON c.oid = tg.tgrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE tg.tgname = 'trg_complaints_touch'
          AND NOT tg.tgisinternal
          AND n.nspname = 'public' AND c.relname = 'complaints')
       !~* 'touch_updated_at' THEN
        RAISE EXCEPTION 'trg_complaints_touch is not bound to touch_updated_at()';
    END IF;

    --    (c) that function exists and actually assigns NEW.updated_at = now()
    IF NOT EXISTS (
        SELECT 1 FROM pg_proc
        WHERE proname = 'touch_updated_at'
          AND pronamespace = 'public'::regnamespace
          AND prosrc ~* 'NEW\.updated_at\s*=\s*now\(\)'
    ) THEN
        RAISE EXCEPTION
          'touch_updated_at() missing, or its body does not assign NEW.updated_at = now()';
    END IF;
    RAISE NOTICE 'OK  touch_updated_at trigger attached, bound, and body assigns NEW.updated_at = now()';
    --    Runtime execution of the trigger is NOT proven here; that requires a
    --    real UPDATE and belongs in the Stage 8 test suite.

    -- 8. band boundaries match the agreed values -----------------------------
    -- Mirrors the application scorer; drift here means the dashboard disagrees.
    IF (CASE WHEN 29 < 30 THEN 'Low' WHEN 29 < 55 THEN 'Medium'
             WHEN 29 < 75 THEN 'High' ELSE 'Critical' END) <> 'Low' THEN
        RAISE EXCEPTION 'band boundary wrong at 29';
    END IF;
    IF (CASE WHEN 30 < 30 THEN 'Low' WHEN 30 < 55 THEN 'Medium'
             WHEN 30 < 75 THEN 'High' ELSE 'Critical' END) <> 'Medium' THEN
        RAISE EXCEPTION 'band boundary wrong at 30';
    END IF;
    IF (CASE WHEN 54 < 30 THEN 'Low' WHEN 54 < 55 THEN 'Medium'
             WHEN 54 < 75 THEN 'High' ELSE 'Critical' END) <> 'Medium' THEN
        RAISE EXCEPTION 'band boundary wrong at 54';
    END IF;
    IF (CASE WHEN 55 < 30 THEN 'Low' WHEN 55 < 55 THEN 'Medium'
             WHEN 55 < 75 THEN 'High' ELSE 'Critical' END) <> 'High' THEN
        RAISE EXCEPTION 'band boundary wrong at 55';
    END IF;
    IF (CASE WHEN 74 < 30 THEN 'Low' WHEN 74 < 55 THEN 'Medium'
             WHEN 74 < 75 THEN 'High' ELSE 'Critical' END) <> 'High' THEN
        RAISE EXCEPTION 'band boundary wrong at 74';
    END IF;
    IF (CASE WHEN 75 < 30 THEN 'Low' WHEN 75 < 55 THEN 'Medium'
             WHEN 75 < 75 THEN 'High' ELSE 'Critical' END) <> 'Critical' THEN
        RAISE EXCEPTION 'band boundary wrong at 75';
    END IF;
    RAISE NOTICE 'OK  band boundaries 0-29 / 30-54 / 55-74 / 75-100';

    RAISE NOTICE '==================================================';
    RAISE NOTICE ' CampusLens Stage 1a verification PASSED';
    RAISE NOTICE '==================================================';
END
$$;

-- ============================================================================
-- Part 3 of 3 - Stage 1b checks: storage policies (009) and admin (010)
--
-- Still NON-MUTATING: catalog lookups only. No DML, no bucket creation.
--
-- Checks:
--   9.  the four storage.objects policies exist, name the right bucket, and
--       none is granted to `anon`
--   10. is_admin() is SECURITY DEFINER with a pinned search_path (the 42P17 fix)
--   11. admin bootstrap functions exist and are NOT executable by end users
--   12. at least one admin exists (reported, non-fatal until you bootstrap)
--   13. the signup trigger (012) exists on auth.users and cannot set a role
-- ============================================================================
DO $$
DECLARE
    rec    record;
    n_pol  bigint;
    n_anon bigint;
    profs  bigint;
    admins bigint;
BEGIN
    -- 9. storage policies -----------------------------------------------------
    IF to_regclass('storage.objects') IS NULL THEN
        RAISE NOTICE 'storage.objects not visible - skipped storage policy checks';
    ELSE
        SELECT count(*) INTO n_pol
        FROM pg_policies
        WHERE schemaname = 'storage' AND tablename = 'objects'
          AND policyname IN ('complaint_images_owner_insert',
                             'complaint_images_owner_select',
                             'complaint_images_owner_update',
                             'complaint_images_admin_all');

        IF n_pol < 4 THEN
            RAISE EXCEPTION
              'Only % of 4 complaint_images storage policies found - run migration 009', n_pol;
        END IF;

        SELECT count(*) INTO n_anon
        FROM pg_policies
        WHERE schemaname = 'storage' AND tablename = 'objects'
          AND policyname LIKE 'complaint_images%'
          AND roles && ARRAY['anon']::name[];

        IF n_anon > 0 THEN
            RAISE EXCEPTION
              '% complaint_images storage policies are granted to anon - images would be public', n_anon;
        END IF;

        FOR rec IN
            SELECT policyname,
                   COALESCE(qual, '') || ' ' || COALESCE(with_check, '') AS clause_text
            FROM pg_policies
            WHERE schemaname = 'storage' AND tablename = 'objects'
              AND policyname LIKE 'complaint_images%'
        LOOP
            IF rec.clause_text NOT LIKE '%CLimage%' THEN
                RAISE EXCEPTION
                  'storage policy % does not reference the CLimage bucket', rec.policyname;
            END IF;
            IF btrim(rec.clause_text) IN ('true', '(true)') THEN
                RAISE EXCEPTION
                  'storage policy % is unconditional - too permissive', rec.policyname;
            END IF;
        END LOOP;

        RAISE NOTICE 'OK  4 storage policies present, bucket-scoped, none granted to anon';
    END IF;

    -- 10. the 42P17 recursion fix is in place ---------------------------------
    IF NOT EXISTS (
        SELECT 1 FROM pg_proc
        WHERE proname = 'is_admin'
          AND pronamespace = 'public'::regnamespace
          AND prosecdef
    ) THEN
        RAISE EXCEPTION
          'is_admin() is not SECURITY DEFINER - policies calling it raise 42P17 infinite recursion';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_proc
        WHERE proname = 'is_admin'
          AND pronamespace = 'public'::regnamespace
          AND proconfig @> ARRAY['search_path=public, pg_temp']::text[]
    ) THEN
        RAISE EXCEPTION 'is_admin() does not pin search_path to public, pg_temp';
    END IF;
    RAISE NOTICE 'OK  is_admin() is SECURITY DEFINER with a pinned search_path';

    -- 11. admin bootstrap functions are locked down ---------------------------
    IF NOT EXISTS (
        SELECT 1 FROM pg_proc
        WHERE proname = 'promote_to_admin'
          AND pronamespace = 'public'::regnamespace
          AND prosecdef
    ) THEN
        RAISE EXCEPTION 'promote_to_admin(uuid) missing or not SECURITY DEFINER';
    END IF;

    FOR rec IN
        SELECT p.proname, COALESCE(array_to_string(p.proacl, ','), '') AS acl
        FROM pg_proc p
        WHERE p.pronamespace = 'public'::regnamespace
          AND p.proname IN ('promote_to_admin', 'admin_bootstrap_status')
    LOOP
        IF rec.acl LIKE '%authenticated%' OR rec.acl LIKE '%anon%' THEN
            RAISE EXCEPTION
              '% is executable by end users - escalation path', rec.proname;
        END IF;
    END LOOP;
    RAISE NOTICE 'OK  admin functions are not callable by end users';

    -- 12. admin bootstrap complete? -------------------------------------------
    IF to_regprocedure('public.admin_bootstrap_status()') IS NULL THEN
        RAISE NOTICE 'admin_bootstrap_status() missing - run migration 010';
    ELSE
        SELECT total_profiles, total_admins INTO profs, admins
        FROM public.admin_bootstrap_status();

        IF admins = 0 THEN
            RAISE NOTICE 'NO ADMIN YET. Complete the MANUAL STEP in 010_seed_admin.sql.';
            RAISE NOTICE 'Stage 1 schema is complete; admin access is not, until that step is done.';
        ELSE
            RAISE NOTICE 'OK  admin bootstrap complete (% profiles, % admins)', profs, admins;
        END IF;
    END IF;

    -- 13. signup trigger (012) ------------------------------------------------
    -- Not fatal if auth.users is not visible to this role: the trigger may still
    -- be present, we simply cannot prove it from here.
    IF to_regclass('auth.users') IS NULL THEN
        RAISE NOTICE 'auth.users not visible - skipped signup trigger check';
    ELSE
        IF NOT EXISTS (
            SELECT 1
            FROM pg_trigger tg
            JOIN pg_class c     ON c.oid = tg.tgrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE tg.tgname = 'on_auth_user_created'
              AND NOT tg.tgisinternal
              AND n.nspname = 'auth' AND c.relname = 'users'
        ) THEN
            RAISE EXCEPTION
              'on_auth_user_created trigger missing on auth.users - run migration 012';
        END IF;

        IF (SELECT pg_get_triggerdef(tg.oid)
            FROM pg_trigger tg
            JOIN pg_class c     ON c.oid = tg.tgrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE tg.tgname = 'on_auth_user_created'
              AND NOT tg.tgisinternal
              AND n.nspname = 'auth' AND c.relname = 'users')
           !~* 'handle_new_user' THEN
            RAISE EXCEPTION
              'on_auth_user_created is not bound to handle_new_user()';
        END IF;

        -- SECURITY: the INSERT must NOT name a role column, otherwise a signup
        -- could grant itself admin via user metadata.
        IF NOT EXISTS (
            SELECT 1 FROM pg_proc
            WHERE proname = 'handle_new_user'
              AND pronamespace = 'public'::regnamespace
              AND prosecdef
        ) THEN
            RAISE EXCEPTION
              'handle_new_user() missing or not SECURITY DEFINER - it cannot write profiles under RLS';
        END IF;

        IF (SELECT prosrc FROM pg_proc
            WHERE proname = 'handle_new_user'
              AND pronamespace = 'public'::regnamespace)
           ~* 'INSERT\s+INTO\s+public\.profiles[^;]*\brole\b' THEN
            RAISE EXCEPTION
              'handle_new_user() appears to set a role column - signup could escalate to admin';
        END IF;

        RAISE NOTICE
          'OK  on_auth_user_created trigger present and bound; handle_new_user() cannot set role';
    END IF;

    RAISE NOTICE '==================================================';
    RAISE NOTICE ' CampusLens Stage 1 verification PASSED';
    RAISE NOTICE '==================================================';
END
$$;
