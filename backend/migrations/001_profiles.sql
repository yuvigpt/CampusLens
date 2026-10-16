-- ============================================================================
-- CampusLens - migration 001 - profiles
--
-- One row per authenticated user, carrying the role used for authorisation.
-- We never store passwords: Supabase Auth owns credentials, this table only
-- mirrors identity and role.
--
-- SAFE TO RE-RUN.  Rollback: DROP TABLE profiles;  (destructive)
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS profiles (
    id         uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email      text UNIQUE NOT NULL,
    full_name  text,
    role       text NOT NULL DEFAULT 'student'
               CHECK (role IN ('student', 'admin')),
    created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE profiles IS
 'One row per Supabase Auth user. Role is never self-assigned; the first admin is created out of band (migration 010).';

CREATE INDEX IF NOT EXISTS idx_profiles_role ON profiles (role);

-- Authorisation helper used by the seven admin policies in migrations 003-007.
--
-- SECURITY DEFINER is REQUIRED here, not a preference. Without it this function
-- runs with the caller's rights, its SELECT hits profiles, profiles' own RLS
-- policies are evaluated, profiles_admin_all calls this function again, and
-- PostgreSQL aborts with:
--     42P17  infinite recursion detected in policy for relation "profiles"
-- That breaks all seven admin policies for EVERY signed-in user, including a
-- student reading their own complaints.
--
-- As SECURITY DEFINER the function runs as its owner. Table owners bypass RLS
-- (PostgreSQL: "Table owners normally bypass row security as well"), so the
-- inner SELECT is not filtered and the recursion is broken.
--
-- The pinned search_path and the narrow EXECUTE grant are both mandatory, not
-- decorative:
--   * without a pinned search_path a caller could place their own `profiles`
--     table earlier in the path and be substituted for the real one;
--   * functions default to EXECUTE for PUBLIC (which includes the `anon`
--     role), so without an explicit REVOKE any anonymous caller could invoke
--     a function that executes with the owner's privileges.
--
-- The function stays deliberately narrow: no arguments, returns one boolean,
-- and only ever answers "is the CURRENT caller an admin". It cannot be used to
-- read another user's profile row.
CREATE OR REPLACE FUNCTION public.is_admin()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.profiles p
        WHERE p.id = auth.uid() AND p.role = 'admin'
    );
$$;

-- Deny by default, then grant the narrowest role that needs it.
REVOKE ALL ON FUNCTION public.is_admin() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.is_admin() TO authenticated;

-- Row Level Security: a signed-in user may read only their own profile row.
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'profiles'
          AND policyname = 'profiles_self_read'
    ) THEN
        CREATE POLICY profiles_self_read ON profiles
            FOR SELECT
            USING (id = (SELECT auth.uid()));
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'profiles'
          AND policyname = 'profiles_admin_all'
    ) THEN
        CREATE POLICY profiles_admin_all ON profiles
            FOR ALL
            USING ((SELECT public.is_admin()));
    END IF;
END
$$;

COMMIT;