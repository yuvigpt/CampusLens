/**
 * Session state for the whole app.
 *
 * Holds the Supabase session, exposes sign-in / sign-up / sign-out, and keeps
 * the access token in one place so api.js can attach it to every protected
 * request. The role shown in the UI comes from the backend, never from the
 * token, so a forged claim cannot change what a user can see here.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { authConfigured, supabase } from './lib/supabase.js';

const AuthContext = createContext(null);

const FRIENDLY = {
  'Invalid login credentials': 'That email and password do not match.',
  'User already registered': 'An account already exists for that email.',
  'Email not confirmed': 'Confirm your email address before signing in.',
};

function describe(error) {
  if (!error) return null;
  return FRIENDLY[error.message] || error.message || 'Authentication failed.';
}

export function AuthProvider({ children }) {
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(authConfigured);
  const [profile, setProfile] = useState(null);
  const [profileError, setProfileError] = useState(null);

  // Restore an existing session on load and keep it in sync afterwards.
  useEffect(() => {
    if (!supabase) {
      setLoading(false);
      return undefined;
    }
    let active = true;
    supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      setSession(data?.session ?? null);
      setLoading(false);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_event, next) => {
      setSession(next ?? null);
    });
    return () => {
      active = false;
      sub.subscription.unsubscribe();
    };
  }, []);

  // Ask the backend who this user is. The role is authoritative server-side.
  //
  // On failure we clear the profile and record the reason: we must NOT fall
  // back to treating the caller as a student, because that would silently hide
  // the admin tab from a real administrator. `role` stays null until the
  // backend confirms one.
  const loadProfile = useCallback(async (token) => {
    if (!token) {
      setProfile(null);
      setProfileError(null);
      return null;
    }
    try {
      const { getMyProfile } = await import('./api.js');
      const me = await getMyProfile(token);
      setProfile(me);
      setProfileError(null);
      return me;
    } catch (caught) {
      setProfile(null);
      setProfileError(
        caught?.message
          ? `Could not confirm your account: ${caught.message}`
          : 'Could not confirm your account with the backend.',
      );
      return null;
    }
  }, []);

  useEffect(() => {
    loadProfile(session?.access_token ?? null);
  }, [session?.access_token, loadProfile]);

  const signIn = useCallback(async (email, password) => {
    if (!supabase) return { error: 'Authentication is not configured.' };
    const { data, error } = await supabase.auth.signInWithPassword({
      email: email.trim(),
      password,
    });
    if (error) return { error: describe(error) };
    if (data?.session) {
      setSession(data.session);
    }
    // Load the profile with the fresh token so the caller can route by the
    // backend-confirmed role: an administrator lands on the operations
    // dashboard instead of the student home page. A failure here is not a
    // sign-in failure - `me` is simply null and the caller falls back to the
    // student route (the profileError banner + Retry still apply).
    const me = await loadProfile(data.session?.access_token ?? null);
    return { data, me, error: null };
  }, [loadProfile]);

  const signUp = useCallback(async (email, password, fullName) => {
    if (!supabase) return { error: 'Authentication is not configured.' };
    const { data, error } = await supabase.auth.signUp({
      email: email.trim(),
      password,
      options: {
        // Migration 012 reads full_name from raw_user_meta_data. It never
        // creates an admin: role always takes the database default.
        data: { full_name: (fullName || '').trim() || undefined },
      },
    });
    if (error) return { error: describe(error) };
    if (data?.session) {
      setSession(data.session);
    }
    // When the project has email confirmation disabled, signUp returns a
    // session immediately - load the profile so the caller can route by role
    // exactly like signIn does.
    const me = data.session
      ? await loadProfile(data.session.access_token ?? null)
      : null;
    return { data, me, error: null };
  }, [loadProfile]);

  const signOut = useCallback(async () => {
    try {
      if (supabase) await supabase.auth.signOut();
    } catch {
      // Ignore network errors on sign out
    }
    setSession(null);
    setProfile(null);
    window.location.hash = '#/signin';
  }, []);

  const value = useMemo(
    () => ({
      session,
      token: session?.access_token ?? null,
      user: session?.user ?? null,
      email: session?.user?.email ?? null,
      profile,
      profileError,
      profileLoading: !!session && !profile && !profileError,
      role: profile?.role ?? null,
      isAdmin: profile?.role === 'admin',
      loading,
      configured: authConfigured,
      signIn,
      signUp,
      signOut,
      reloadProfile: () => loadProfile(session?.access_token ?? null),
    }),
    [session, profile, profileError, loading, signIn, signUp, signOut, loadProfile],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>.');
  return value;
}
