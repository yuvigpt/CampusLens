/**
 * Supabase Auth client for the browser.
 *
 * SECURITY: only VITE_-prefixed variables reach the bundle, and only the PUBLIC
 * anon key is used here. The service_role key is a SERVER secret and must never
 * appear in any VITE_ variable - Vite would publish it to every visitor.
 */

import { createClient } from '@supabase/supabase-js';

const SUPABASE_URL = (import.meta.env.VITE_SUPABASE_URL || '').trim();
const SUPABASE_ANON_KEY = (import.meta.env.VITE_SUPABASE_ANON_KEY || '').trim();

/**
 * True when both public values are configured. When false the app still runs:
 * the public feed works, but sign-in is disabled instead of crashing.
 */
export const authConfigured = Boolean(SUPABASE_URL && SUPABASE_ANON_KEY);

export const supabase = authConfigured
  ? createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    })
  : null;
