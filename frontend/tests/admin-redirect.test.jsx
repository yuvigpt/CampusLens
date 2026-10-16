/**
 * Regression: the landing page after sign-in follows the BACKEND-confirmed
 * role.
 *
 * Bug report this pins: an administrator signed in and always landed on the
 * student home page ("user portal"), because SignInPage redirected to '#/'
 * unconditionally - the role was only consulted later for the sidebar link.
 * Now signIn() loads the profile with the fresh token and the redirect sends
 * admins to '#/dashboard' and everyone else to '#/'.
 *
 * Supabase and the backend are both stubbed - no network, no real account.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

import { jsonResponse } from './setup.js';

const TOKEN = 'tok-role';

async function mountAndSignIn(role) {
  vi.resetModules();
  window.location.hash = '#/signin';

  vi.doMock('../src/lib/supabase.js', () => ({
    authConfigured: true,
    supabase: {
      auth: {
        getSession: vi.fn(async () => ({ data: { session: null } })),
        onAuthStateChange: vi.fn(() => ({
          data: { subscription: { unsubscribe: vi.fn() } },
        })),
        signInWithPassword: vi.fn(async () => ({
          data: {
            session: {
              access_token: TOKEN,
              user: { id: 'u1', email: 'someone@iitk.ac.in' },
            },
          },
          error: null,
        })),
        signUp: vi.fn(),
        signOut: vi.fn(),
      },
    },
  }));

  global.fetch = vi.fn(async (url) => {
    const href = String(url);
    if (href.includes('/api/health')) {
      return jsonResponse(200, { status: 'ok', service: 's', version: '2.0.0' });
    }
    if (href.includes('/api/me')) {
      return jsonResponse(200, {
        id: 'u1',
        email: 'someone@iitk.ac.in',
        full_name: 'Someone',
        role,
        created_at: null,
      });
    }
    return jsonResponse(200, []);
  });

  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react');
  const App = (await import('../src/App.jsx')).default;

  render(<App />);
  await vi.waitFor(() => {
    expect(screen.queryByText(/checking session/i)).toBeNull();
  });

  await fireEvent.change(screen.getByLabelText(/email address/i), {
    target: { value: 'someone@iitk.ac.in' },
  });
  await fireEvent.change(screen.getByLabelText(/^password$/i), {
    target: { value: 'pw123456' },
  });
  // Exact name: the page also has a secondary button whose accessible name
  // merely contains "Sign in" (the mode switch), which a loose regex matches.
  await fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));

  return { cleanup };
}

let cleanupFn = null;

afterEach(() => {
  if (cleanupFn) cleanupFn();
  cleanupFn = null;
  vi.doUnmock('../src/lib/supabase.js');
  window.location.hash = '';
});

describe('post-sign-in landing page', () => {
  it('lands an admin on the operations dashboard', async () => {
    const app = await mountAndSignIn('admin');
    cleanupFn = app.cleanup;

    await vi.waitFor(
      () => {
        expect(window.location.hash).toBe('#/dashboard');
      },
      { timeout: 3000 },
    );
  });

  it('lands a student on the home page', async () => {
    const app = await mountAndSignIn('student');
    cleanupFn = app.cleanup;

    await vi.waitFor(
      () => {
        expect(window.location.hash).toBe('#/');
      },
      { timeout: 3000 },
    );
  });
});
