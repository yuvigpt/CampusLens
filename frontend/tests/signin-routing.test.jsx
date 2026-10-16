/**
 * Regression: the signed-out #/signin route must render the auth form.
 *
 * Both "Sign in" buttons in the signed-out UI (App.jsx topbar and the
 * CommunityPage empty state) link to #/signin. That route is marked
 * `public: true` so its nav link stays visible while signed out, but the
 * signed-out branch in Shell() used to render `null` for ANY public route:
 *
 *     return route.public ? null : <SignInPage />;
 *
 * So the URL changed to #/signin while the page stayed blank - both buttons
 * looked inert and there was no reachable way to create a student account.
 * The route is now matched explicitly.
 *
 * This file also covers the second half of the bug report: the sign-up form
 * behind "Need an account?", which was unreachable for the same reason.
 *
 * Supabase and the backend are both stubbed - no network, no real account.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

import { jsonResponse } from './setup.js';

/**
 * Mount <App/> signed out on a given hash.
 *
 * getSession resolves to a null session, which is the state a first-time
 * visitor is actually in.
 */
async function mountSignedOut(hash) {
  vi.resetModules();
  window.location.hash = hash;

  vi.doMock('../src/lib/supabase.js', () => ({
    authConfigured: true,
    supabase: {
      auth: {
        getSession: vi.fn(async () => ({ data: { session: null } })),
        onAuthStateChange: vi.fn(() => ({ data: { subscription: { unsubscribe: vi.fn() } } })),
        signInWithPassword: vi.fn(),
        signUp: vi.fn(),
        signOut: vi.fn(),
      },
    },
  }));

  // Only the public health probe runs while signed out; /api/me must NOT be
  // called, because there is no token to send.
  global.fetch = vi.fn(async (url) => {
    const href = String(url);
    if (href.includes('/api/health')) {
      return jsonResponse(200, { status: 'ok', service: 's', version: '2.0.0' });
    }
    return jsonResponse(200, []);
  });

  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react');
  const App = (await import('../src/App.jsx')).default;

  render(<App />);

  // Wait for the session check to resolve, so `token` is settled before we
  // assert on what the signed-out branch renders.
  await vi.waitFor(() => {
    expect(screen.queryByText(/checking session/i)).toBeNull();
  });
  await new Promise((resolve) => setTimeout(resolve, 30));

  return { screen, fireEvent, cleanup };
}

let cleanupFn = null;

afterEach(() => {
  if (cleanupFn) cleanupFn();
  cleanupFn = null;
  vi.doUnmock('../src/lib/supabase.js');
  window.location.hash = '';
});

describe('signed-out sign-in routing', () => {
  it('renders the sign-in form at #/signin instead of a blank page', async () => {
    const app = await mountSignedOut('#/signin');
    cleanupFn = app.cleanup;

    // The form itself: email + password fields and the submit button.
    expect(app.screen.getByLabelText(/email address/i)).toBeTruthy();
    expect(app.screen.getByLabelText(/^password$/i)).toBeTruthy();
    expect(app.screen.getByRole('button', { name: 'Sign in' })).toBeTruthy();

    // No token means no admin tab, and the API is never asked who we are.
    expect(
      Array.from(document.querySelectorAll('nav[aria-label="Primary"] a'))
        .map((n) => n.textContent.trim()),
    ).not.toContain('Operations dashboard');
    expect(
      global.fetch.mock.calls.some(([url]) => String(url).includes('/api/me')),
    ).toBe(false);
  });

  it('does not leak the auth form onto other routes while signed out', async () => {
    // #/community stays `public: true`, and the fix must stay scoped to
    // #/signin: no other route should start rendering the auth form.
    //
    // Note: signed out on #/community the signed-out branch still renders
    // `null` (an empty <main>), exactly as it did before the fix - that is
    // unchanged pre-existing behaviour, not something this fix alters.
    const app = await mountSignedOut('#/community');
    cleanupFn = app.cleanup;

    expect(app.screen.queryByLabelText(/email address/i)).toBeNull();
    expect(app.screen.queryByRole('button', { name: /need an account/i })).toBeNull();
    expect(app.screen.queryByRole('heading', { name: /create an account/i })).toBeNull();
  });

  it('offers account creation from #/signin via "Need an account?"', async () => {
    const app = await mountSignedOut('#/signin');
    cleanupFn = app.cleanup;

    // Full name and the signup button only exist in signup mode.
    expect(app.screen.queryByLabelText(/full name/i)).toBeNull();

    app.fireEvent.click(app.screen.getByRole('button', { name: /need an account/i }));

    // Signup form: full name appears, heading and submit button switch over.
    expect(app.screen.getByLabelText(/full name/i)).toBeTruthy();
    expect(app.screen.getByRole('heading', { name: /create an account/i })).toBeTruthy();
    expect(app.screen.getByRole('button', { name: 'Create account' })).toBeTruthy();

    // The toggle now offers the way back.
    expect(app.screen.getByRole('button', { name: /already have an account/i })).toBeTruthy();

    // New accounts are students only - admin access is never self-assigned.
    expect(app.screen.getByText(/always created as students/i)).toBeTruthy();
  });

  it('navigating from the Community empty-state button reaches the form', async () => {
    // The exact user-reported path: signed out on #/community, click "Sign in".
    const app = await mountSignedOut('#/community');
    cleanupFn = app.cleanup;

    const links = Array.from(document.querySelectorAll('a[href="#/signin"]'));
    expect(links.length).toBeGreaterThan(0);

    window.location.hash = '#/signin';
    app.fireEvent(window, new window.HashChangeEvent('hashchange'));
    await new Promise((resolve) => setTimeout(resolve, 30));

    expect(app.screen.getByLabelText(/email address/i)).toBeTruthy();
    expect(app.screen.getByRole('button', { name: 'Sign in' })).toBeTruthy();
  });
});