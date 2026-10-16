/**
 * Role detection and admin-tab visibility.
 *
 * The Admin tab renders ONLY when GET /api/me returns role === 'admin'. The role
 * is never inferred from the token, so a student cannot be shown admin UI and an
 * administrator is never silently downgraded.
 *
 * Each test stubs the Supabase client and the backend itself, unmounts at the
 * end, and resets modules - otherwise jsdom keeps one document across tests and
 * assertions match elements left by an earlier render.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

import { jsonResponse } from './setup.js';

vi.stubEnv('VITE_SUPABASE_URL', 'https://fake.supabase.co');
vi.stubEnv('VITE_SUPABASE_ANON_KEY', 'fake-anon-key');

const TOKEN = 'tok-1';

/** Stub Supabase Auth and the backend, then mount <App/> with a fresh session. */
async function mountApp({ role = 'student', failProfile = false } = {}) {
  vi.resetModules();
  vi.unstubAllEnvs();
  vi.stubEnv('VITE_SUPABASE_URL', 'https://fake.supabase.co');
  vi.stubEnv('VITE_SUPABASE_ANON_KEY', 'fake-anon-key');

  vi.doMock('../src/lib/supabase.js', () => ({
    authConfigured: true,
    supabase: {
      auth: {
        getSession: vi.fn(async () => ({
          data: {
            session: {
              access_token: TOKEN,
              user: { id: 'u1', email: 'user@example.test' },
            },
          },
        })),
        onAuthStateChange: vi.fn(() => ({ data: { subscription: { unsubscribe: vi.fn() } } })),
        signInWithPassword: vi.fn(),
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
      if (failProfile) {
        return jsonResponse(403, { detail: 'No profile is associated with this account.' });
      }
      return jsonResponse(200, {
        id: 'u1', email: 'user@example.test', full_name: 'Test', role, created_at: null,
      });
    }
    return jsonResponse(200, []);
  });

  const { render, screen, cleanup } = await import('@testing-library/react');
  const { AuthProvider } = await import('../src/auth.jsx');
  const App = (await import('../src/App.jsx')).default;

  render(
    <AuthProvider>
      <App />
    </AuthProvider>,
  );

  await vi.waitFor(() => {
    const called = global.fetch.mock.calls.some(([url]) => String(url).includes('/api/me'));
    expect(called).toBe(true);
  });
  await new Promise((resolve) => setTimeout(resolve, 30));

  return { screen, cleanup, navLabels: () => navLabels() };
}

function navLabels() {
  // One <a> per visible route inside the primary nav (the old .nav__label
  // class was dropped in the Tailwind restyle).
  return Array.from(
    document.querySelectorAll('nav[aria-label="Primary"] a'),
  ).map((n) => n.textContent.trim());
}

let cleanupFn = null;

afterEach(() => {
  if (cleanupFn) cleanupFn();
  cleanupFn = null;
  vi.doUnmock('../src/lib/supabase.js');
});

describe('admin navigation', () => {
  it('shows the Admin tab only when the backend confirms role admin', async () => {
    const app = await mountApp({ role: 'admin' });
    cleanupFn = app.cleanup;
    expect(app.navLabels()).toContain('Operations dashboard');
    expect(app.navLabels()).toContain('My complaints');
  });

  it('hides the Admin tab for a student', async () => {
    const app = await mountApp({ role: 'student' });
    cleanupFn = app.cleanup;
    expect(app.navLabels()).toContain('My complaints');
    expect(app.navLabels()).not.toContain('Operations dashboard');
  });

  it('requests /api/me with the bearer token', async () => {
    const app = await mountApp({ role: 'admin' });
    cleanupFn = app.cleanup;
    const call = global.fetch.mock.calls.find(([url]) => String(url).includes('/api/me'));
    expect(call).toBeTruthy();
    expect(call[1].headers.Authorization).toBe(`Bearer ${TOKEN}`);
  });
});

describe('profile fetch failure', () => {
  it('surfaces the error, offers a retry, and never shows admin UI', async () => {
    const app = await mountApp({ failProfile: true });
    cleanupFn = app.cleanup;
    expect(app.screen.getByText(/Could not confirm your account/i)).toBeTruthy();
    expect(app.screen.getByText('Retry')).toBeTruthy();
    expect(app.navLabels()).not.toContain('Operations dashboard');
  });
});
