/**
 * The global top-bar search and the admin sidebar's "Issue Triage" button.
 *
 * Two user-reported bugs pinned here:
 *   1. "Issue Triage" pointed at #/dashboard (the Overview route) and the
 *      admin active state was hardcoded to the first item, so clicking it
 *      looked inert. It now opens #/triage - the full triage workspace
 *      (all complaints, filters, pagination, drawer operations).
 *   2. The top-bar search input stored its value in state and never used
 *      it. Enter now hands the query to the page that can really search:
 *      admins -> #/triage?q=..., students -> #/mine?q=... - both backed by
 *      the real backend `q` parameter.
 *
 * Supabase and the backend are both stubbed - no network, no real account.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

import { jsonResponse } from './setup.js';

const TOKEN = 'tok-search';

const ROW = {
  id: 'row11111-2222-4333-8444-555566667777',
  student_id: 'student-9',
  description: 'Flickering tube light in Lab 3 keeps going out',
  location: 'Science Block, Lab 3',
  image_path: null,
  image_url: null,
  status: 'Reported',
  confirmed_urgency: null,
  confirmed_impact: null,
  confirmed_safety: null,
  confirmed_by: null,
  analysis_confirmed_at: null,
  priority_score: 62.5,
  score_breakdown: null,
  score_computed_at: '2026-01-04T10:00:00Z',
  band: 'High',
  ai_category: 'Electrical',
  ai_summary: 'Light fixture flickering consistently near the door.',
  ai_evidence: null,
  ai_uncertainty: null,
  ai_urgency: 'High',
  ai_impact: 'Medium',
  ai_safety: 'Medium',
  created_at: '2026-01-04T09:00:00Z',
  updated_at: null,
  resolved_at: null,
};

/** Mount <App/> signed out on #/signin, sign in, land as the given role. */
async function mountSignedIn(role) {
  vi.resetModules();
  window.location.hash = '#/signin';

  vi.doMock('../src/lib/supabase.js', () => {
    const session = {
      access_token: TOKEN,
      user: { id: 'u1', email: 'someone@iitk.ac.in' },
    };
    // Real Supabase fires the auth-state callback after the password
    // exchange - that event is what puts the token into AuthProvider state.
    // A mock that never fires it would leave every page's `if (!token)
    // return` silently skipping its fetches.
    let authCallback = null;
    return {
      authConfigured: true,
      supabase: {
        auth: {
          getSession: vi.fn(async () => ({ data: { session: null } })),
          onAuthStateChange: vi.fn((callback) => {
            authCallback = callback;
            return { data: { subscription: { unsubscribe: vi.fn() } } };
          }),
          signInWithPassword: vi.fn(async () => {
            if (authCallback) authCallback('SIGNED_IN', session);
            return { data: { session }, error: null };
          }),
          signUp: vi.fn(),
          signOut: vi.fn(),
        },
      },
    };
  });

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
    if (href.includes('/analytics/summary')) {
      return jsonResponse(200, {
        total: 1,
        by_status: { Reported: 1, 'In Progress': 0, Resolved: 0 },
        by_band: { Critical: 0, High: 1, Medium: 0, Low: 0 },
        unscored: 0,
        unresolved: 1,
      });
    }
    if (href.includes('/events') || href.includes('/notes')) {
      return jsonResponse(200, []);
    }
    if (href.includes('/api/admin/complaints')) return jsonResponse(200, [ROW]);
    return jsonResponse(200, []);
  });

  const RTL = await import('@testing-library/react');
  const App = (await import('../src/App.jsx')).default;

  RTL.render(<App />);
  await vi.waitFor(() => {
    expect(RTL.screen.queryByText(/checking session/i)).toBeNull();
  });

  await RTL.fireEvent.change(RTL.screen.getByLabelText(/email address/i), {
    target: { value: 'someone@iitk.ac.in' },
  });
  await RTL.fireEvent.change(RTL.screen.getByLabelText(/^password$/i), {
    target: { value: 'pw123456' },
  });
  // Exact name: the mode-switch button also contains "Sign in".
  await RTL.fireEvent.click(
    RTL.screen.getAllByRole('button', { name: 'Sign in' })[0],
  );

  return RTL;
}

let cleanupFn = null;

afterEach(() => {
  if (cleanupFn) cleanupFn();
  cleanupFn = null;
  // Belt-and-braces: each test builds a fresh module graph (vi.resetModules),
  // so a timed-out test could otherwise leak its container into the next one.
  document.body.innerHTML = '';
  vi.doUnmock('../src/lib/supabase.js');
  window.location.hash = '';
});
describe('admin sidebar: Issue Triage', () => {
  it('opens the full triage workspace and highlights the active item', async () => {
    const app = await mountSignedIn('admin');
    cleanupFn = app.cleanup;

    await vi.waitFor(() => {
      expect(window.location.hash).toBe('#/dashboard');
    }, { timeout: 10000 });

    const link = document.querySelector('nav[aria-label="Primary"] a[href="#/triage"]');
    expect(link).toBeTruthy();
    expect(link.textContent).toContain('Issue Triage');

    app.fireEvent.click(link);
    await vi.waitFor(() => {
      expect(window.location.hash).toBe('#/triage');
    }, { timeout: 10000 });

    // The workspace: heading + full filter set + export + the real rows.
    await app.screen.findByRole('heading', { name: 'Issue Triage' }, {}, { timeout: 10000 });
    expect(app.screen.getByLabelText('Band')).toBeTruthy();
    expect(app.screen.getByRole('button', { name: 'Export CSV' })).toBeTruthy();
    // findByText: the table hides itself while the view's list refetch runs.
    await app.screen.findByText(/flickering tube light/i, {}, { timeout: 10000 });

    // The clicked item now carries the active style (it used to be stuck on
    // the first item regardless of the route).
    expect(
      document.querySelector('nav[aria-label="Primary"] a[href="#/triage"]').className,
    ).toContain('bg-blue-600');
  }, 20000);
});

describe('global top-bar search', () => {
  it('sends an admin to the triage workspace with the query applied', async () => {
    const app = await mountSignedIn('admin');
    cleanupFn = app.cleanup;

    await vi.waitFor(() => {
      expect(window.location.hash).toBe('#/dashboard');
    }, { timeout: 10000 });

    await app.fireEvent.change(
      app.screen.getByPlaceholderText('Search ticket ID, location...'),
      { target: { value: 'leak' } },
    );
    await app.fireEvent.submit(
      app.screen.getByRole('search', { name: 'Search complaints' }),
    );

    await vi.waitFor(() => {
      expect(window.location.hash).toBe('#/triage?q=leak');
    }, { timeout: 10000 });

    // The query reaches the backend as `q` and pre-fills the triage box.
    await vi.waitFor(() => {
      const urls = global.fetch.mock.calls
        .map(([url]) => String(url))
        .filter((url) => url.includes('/api/admin/complaints'));
      expect(urls.some((url) => url.includes('q=leak'))).toBe(true);
    }, { timeout: 10000 });
    await vi.waitFor(() => {
      expect(app.screen.getByLabelText('Search').value).toBe('leak');
    }, { timeout: 10000 });
  }, 20000);

  it('sends a student to My complaints with the query applied', async () => {
    const app = await mountSignedIn('student');
    cleanupFn = app.cleanup;

    await vi.waitFor(() => {
      expect(window.location.hash).toBe('#/');
    }, { timeout: 10000 });

    await app.fireEvent.change(
      app.screen.getByPlaceholderText('Search complaints...'),
      { target: { value: 'hostel' } },
    );
    await app.fireEvent.submit(
      app.screen.getByRole('search', { name: 'Search complaints' }),
    );

    await vi.waitFor(() => {
      expect(window.location.hash).toBe('#/mine?q=hostel');
    }, { timeout: 10000 });

    await vi.waitFor(() => {
      const urls = global.fetch.mock.calls
        .map(([url]) => String(url))
        .filter((url) => /\/api\/complaints\?/.test(url));
      expect(urls.some((url) => url.includes('q=hostel'))).toBe(true);
    }, { timeout: 10000 });
  }, 20000);
});
