-- ============================================================================
-- CampusLens - migration 010 - admin bootstrap (procedure, NOT a seed row)
--
-- This file deliberately inserts NOTHING.
--
-- It does not know your email, your UUID, or whether you have signed up yet,
-- and it must never promote an arbitrary or every user. Instead it installs a
-- guarded function you call ONCE, with your own identity, after you have
-- created the account in Supabase Auth.
--
-- ---------------------------------------------------------------------------
-- profiles ROWS ARE NOW AUTO-CREATED (migration 012)
-- ---------------------------------------------------------------------------
-- As of 012, a trigger on auth.users creates the profiles row at signup with
-- role = 'student'. If you apply 012, you no longer need to INSERT a profiles
-- row by hand for ordinary users - just sign up, then promote:
--
--   1. Create the account: Supabase Dashboard -> Authentication -> Users
--      -> Add user. Note the generated UUID.
--   2. SELECT public.promote_to_admin('<that uuid>');
--
-- The manual INSERT below is still needed only when you apply 012 AFTER a user
-- already exists (the trigger fires on future signups, not retroactively).
--
-- promote_to_admin() REFUSES to run until the profiles row exists, so the two
-- steps cannot be done out of order silently.
--
-- ---------------------------------------------------------------------------
-- SAFETY PROPERTIES
-- ---------------------------------------------------------------------------
--   * No INSERT of any fake or placeholder admin.
--   * No "grant admin to all users" statement anywhere.
--   * promote_to_admin() is SECURITY DEFINER and is granted EXECUTE to NOTHING
--     except service_role - a signed-in student cannot call it, because
--     EXECUTE is revoked from PUBLIC, anon and authenticated.
--   * It takes an explicit UUID: it never guesses or selects a user.
--   * Re-running is a no-op once the user is already an admin.
--
-- SAFE TO RE-RUN.  Rollback: DROP FUNCTION public.promote_to_admin(uuid);
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- Promote one specific, already-existing profiles row to 'admin'.
-- Refuses if that row does not exist - it will never create one.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.promote_to_admin(target_user_id uuid)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    current_role text;
BEGIN
    SELECT role INTO current_role
    FROM public.profiles
    WHERE id = target_user_id;

    IF current_role IS NULL THEN
        RAISE EXCEPTION
          'No profiles row for %. Sign the user up in Supabase Auth first, then insert the matching profiles row (see the manual steps in this file).',
          target_user_id;
    END IF;

    IF current_role = 'admin' THEN
        RETURN format('User %s already has role admin - nothing to do.', target_user_id);
    END IF;

    UPDATE public.profiles
    SET role = 'admin'
    WHERE id = target_user_id;

    RETURN format('User %s promoted from %s to admin.', target_user_id, current_role);
END;
$$;

COMMENT ON FUNCTION public.promote_to_admin(uuid) IS
  'Promotes one existing profiles row to admin. Refuses to create rows. Callable only by service_role; never by end users.';

-- Deny everyone by default, then allow only the service role (the backend).
-- PUBLIC includes anon and authenticated, so both are locked out.
REVOKE ALL ON FUNCTION public.promote_to_admin(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.promote_to_admin(uuid) FROM anon;
REVOKE ALL ON FUNCTION public.promote_to_admin(uuid) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.promote_to_admin(uuid) TO service_role;
-- ---------------------------------------------------------------------------
-- Non-mutating report: how many admins exist? Used by 011_verify.sql.
-- SECURITY DEFINER because it reads profiles, whose RLS hides other rows.
-- Granted only to service_role, same reasoning as above.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.admin_bootstrap_status()
RETURNS TABLE (total_profiles bigint, total_admins bigint)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT count(*)::bigint,
           count(*) FILTER (WHERE role = 'admin')::bigint
    FROM public.profiles;
$$;

REVOKE ALL ON FUNCTION public.admin_bootstrap_status() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.admin_bootstrap_status() FROM anon;
REVOKE ALL ON FUNCTION public.admin_bootstrap_status() FROM authenticated;
GRANT EXECUTE ON FUNCTION public.admin_bootstrap_status() TO service_role;

COMMIT;

-- ============================================================================
-- MANUAL STEP - required exactly once, after applying this migration
-- ============================================================================
-- STEP 1  Create your admin account
--         Supabase Dashboard -> Authentication -> Users -> Add user
--         Use YOUR real email. Copy the generated UUID; it looks like
--         8f14e45f-ceea-467a-9ba4-1d2f3b4c5d6e.
--
-- STEP 2  Create the matching profiles row (needed because no signup trigger
--         exists yet). Edit the two values below, then paste and run:
--
--   INSERT INTO public.profiles (id, email, full_name, role)
--   VALUES (
--       '<PASTE-YOUR-AUTH-UUID-HERE>',
--       '<PASTE-YOUR-EMAIL-HERE>',
--       'Your Name',
--       'student'          -- start as student; step 3 promotes you
--   );
--
-- STEP 3  Promote yourself (run in the SQL editor as the postgres role):
--
--   SELECT public.promote_to_admin('<PASTE-YOUR-AUTH-UUID-HERE>');
--
--   Verify without printing anything sensitive:
--   SELECT total_profiles, total_admins FROM public.admin_bootstrap_status();
--   Expect total_admins = 1.
--
-- STEP 4  Confirm is_admin() works from a signed-in session. Sign in as that
--         user in a client and run, as that user:
--
--   SELECT public.is_admin();   -- must return true
--
-- DO NOT run promote_to_admin for anyone else unless they are a real
-- administrator. There is no demote helper on purpose - use:
--   UPDATE public.profiles SET role = 'student' WHERE id = '<uuid>';
-- and record the change in complaint_events.