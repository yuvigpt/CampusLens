-- ============================================================================
-- CampusLens - migration 012 - auto-create a profiles row on signup
--
-- Closes the gap described in 010: profiles.id REFERENCES auth.users(id), but
-- nothing created that row when a user signed up. Consequences were:
--   * INSERT INTO complaints failed the FK (003), so students could not submit;
--   * is_admin() matched no rows, so admin policies never applied.
--
-- ---------------------------------------------------------------------------
-- ROLE SAFETY - the point of this file
-- ---------------------------------------------------------------------------
-- The insert below supplies (id, email, full_name) ONLY. `role` is deliberately
-- NOT listed, so it takes the column DEFAULT declared in 001:
--
--     role text NOT NULL DEFAULT 'student'   -- 001_profiles.sql:17-18
--
-- Because `role` is absent from the column list, user metadata CANNOT set it.
-- There is no code path by which signing up grants admin - not via
-- raw_user_meta_data, not via user_metadata, not via anything a caller sends.
-- Admin is still only obtainable through 010's promote_to_admin(), which is
-- revoked from PUBLIC, anon and authenticated.
--
-- ---------------------------------------------------------------------------
-- OTHER SAFETY PROPERTIES
-- ---------------------------------------------------------------------------
--   * SECURITY DEFINER + pinned search_path: the trigger runs as its owner, so it
--     can insert into profiles even though profiles has RLS enabled.
--   * ON CONFLICT (id) DO NOTHING: re-running is safe, and a user who already
--     has a profiles row (created by hand, e.g. the 010 manual step) is left
--     completely untouched - their role is NOT overwritten.
--   * DROP TRIGGER IF EXISTS before CREATE TRIGGER, so the trigger itself is
--     re-runnable rather than erroring on the second apply.
--   * full_name is advisory only; it is never used for authorisation.
--
-- SAFE TO RE-RUN.
-- Rollback:  DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
--            DROP FUNCTION IF EXISTS public.handle_new_user();
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- The function. AFTER INSERT on auth.users only: an existing user who signs up
-- later keeps whatever profile row they already have.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    INSERT INTO public.profiles (id, email, full_name)
    VALUES (
        NEW.id,
        NEW.email,
        -- Advisory display name supplied at signup. May be NULL or arbitrary;
        -- it never affects authorisation.
        NULLIF(NEW.raw_user_meta_data ->> 'full_name', '')
    )
    ON CONFLICT (id) DO NOTHING;

    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION public.handle_new_user() IS
  'Creates a profiles row when a Supabase Auth user is created. Role is never set here: it always takes the profiles column default of student, so signup cannot escalate to admin.';

-- Re-runnable trigger: drop first, then create.
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;

CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_new_user();

COMMIT;