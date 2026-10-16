/**
 * Operations dashboard triage: the search bar and filters are wired to the
 * backend query parameters, the table shows REAL rows (the old demo fallbacks
 * are gone), and clicking a row opens the full-screen drawer with the AI
 * analysis, actions, audit trail and notes.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

import { jsonResponse } from './setup.js';

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
  ai_uncertainty: 'No other reports in the area.',
  ai_urgency: 'High',
  ai_impact: 'Medium',
  ai_safety: 'Medium',
  created_at: '2026-01-04T09:00:00Z',
  updated_at: null,
  resolved_at: null,
};

const SUMMARY = {
  total: 1,
  by_status: { Reported: 1, 'In Progress': 0, Resolved: 0 },
  by_band: { Critical: 0, High: 1, Medium: 0, Low: 0 },
  unscored: 0,
  unresolved: 1,
};

async function mountDashboard(view) {
  vi.resetModules();

  vi.doMock('../src/lib/supabase.js', () => ({
    authConfigured: true,
    supabase: {
      auth: {
        getSession: vi.fn(async () => ({
          data: {
            session: {
              access_token: 'tok-admin',
              user: { id: 'a1', email: 'admin@iitk.ac.in' },
            },
          },
        })),
        onAuthStateChange: vi.fn(() => ({
          data: { subscription: { unsubscribe: vi.fn() } },
        })),
        signInWithPassword: vi.fn(),
        signUp: vi.fn(),
        signOut: vi.fn(),
      },
    },
  }));

  global.fetch = vi.fn(async (url) => {
    const href = String(url);
    if (href.includes('/api/me')) {
      return jsonResponse(200, {
        id: 'a1', email: 'admin@iitk.ac.in', full_name: 'Admin',
        role: 'admin', created_at: null,
      });
    }
    if (href.includes('/analytics/summary')) return jsonResponse(200, SUMMARY);
    if (href.includes('/events')) return jsonResponse(200, []);
    if (href.includes('/notes')) return jsonResponse(200, []);
    if (href.includes('/api/admin/complaints')) return jsonResponse(200, [ROW]);
    return jsonResponse(200, []);
  });

  const RTL = await import('@testing-library/react');
  const { AuthProvider } = await import('../src/auth.jsx');
  const DashboardPage = (await import('../src/pages/DashboardPage.jsx')).default;

  RTL.render(
    <AuthProvider>
      <DashboardPage view={view} />
    </AuthProvider>,
  );

  await RTL.screen.findByText(/flickering tube light/i);
  return RTL;
}

function adminListUrls() {
  return global.fetch.mock.calls
    .map(([url]) => String(url))
    .filter((url) => url.includes('/api/admin/complaints') && !url.includes('/events') && !url.includes('/notes'));
}

let cleanupFn = null;

afterEach(() => {
  if (cleanupFn) cleanupFn();
  cleanupFn = null;
});

describe('Operations dashboard', () => {
  it('shows real rows and none of the old demo fallbacks', async () => {
    const app = await mountDashboard();
    cleanupFn = app.cleanup;

    expect(app.screen.getByText(/flickering tube light/i)).toBeTruthy();
    // Strings that only existed in the fake demo data / fake SLA claims:
    expect(app.screen.queryByText(/Flickering lights buzzing continuously/i)).toBeNull();
    expect(app.screen.queryByText(/Urgent Action Required/i)).toBeNull();
    expect(app.screen.queryByText(/SLA: 1.8 days/i)).toBeNull();
    // KPI cards carry the real summary values (label appears in the KPI card
    // and again in the distribution panel).
    expect(app.screen.getAllByText('Unscored').length).toBeGreaterThan(0);
  });

  it('sends the search text to the backend as q (triage view)', async () => {
    const app = await mountDashboard('triage');
    cleanupFn = app.cleanup;

    await app.fireEvent.change(app.screen.getByLabelText('Search'), {
      target: { value: 'leak' },
    });
    await app.fireEvent.submit(app.screen.getByRole('search'));

    await vi.waitFor(() => {
      expect(adminListUrls().some((url) => url.includes('q=leak'))).toBe(true);
    });
  });

  it('sends the band filter to the backend (triage view)', async () => {
    const app = await mountDashboard('triage');
    cleanupFn = app.cleanup;

    await app.fireEvent.change(app.screen.getByLabelText('Band'), {
      target: { value: 'Critical' },
    });

    await vi.waitFor(() => {
      expect(adminListUrls().some((url) => url.includes('band=Critical'))).toBe(true);
    });
  });

  it('overview asks the backend for the LATEST complaints only', async () => {
    const app = await mountDashboard();
    cleanupFn = app.cleanup;

    // 3 newest rows + one probe row for "more exist" - never the whole queue,
    // and none of the triage filters are sent from the overview.
    const first = adminListUrls()[0];
    expect(first).toContain('sort=newest');
    expect(first).toContain('limit=4');
    expect(first).not.toContain('band=');
    expect(first).not.toContain('offset=');
  });

  it('overview hides the full filter set and links to the triage workspace', async () => {
    const app = await mountDashboard();
    cleanupFn = app.cleanup;

    expect(app.screen.queryByLabelText('Band')).toBeNull();
    expect(app.screen.queryByRole('button', { name: 'Export CSV' })).toBeNull();

    const link = document.querySelector('a[href="#/triage"]');
    expect(link).toBeTruthy();
    expect(link.textContent).toContain('All complaints');
  });

  it('triage view is the full workspace: title, filters, export, pagination', async () => {
    const app = await mountDashboard('triage');
    cleanupFn = app.cleanup;

    expect(app.screen.getByText('Issue Triage')).toBeTruthy();
    expect(app.screen.getByLabelText('Band')).toBeTruthy();
    expect(app.screen.getByLabelText('Per page')).toBeTruthy();
    expect(app.screen.getByRole('button', { name: 'Export CSV' })).toBeTruthy();
    expect(app.screen.getByLabelText('Previous page')).toBeTruthy();
  });

  it('opens the detail drawer with AI analysis, actions, events and notes', async () => {
    const app = await mountDashboard();
    cleanupFn = app.cleanup;

    await app.fireEvent.click(app.screen.getByRole('button', { name: 'Open' }));

    await app.screen.findByRole('dialog', { name: /complaint #cl-row11111/i });
    expect(
      app.screen.getByText('Light fixture flickering consistently near the door.'),
    ).toBeTruthy();
    expect(app.screen.getByText('Audit trail')).toBeTruthy();
    expect(app.screen.getByText('Investigation notes')).toBeTruthy();
    expect(app.screen.getByText('Confirm scoring inputs')).toBeTruthy();
    expect(app.screen.getByRole('button', { name: 'Confirm & score' })).toBeTruthy();

    // The timeline endpoints were consulted for this row.
    await vi.waitFor(() => {
      const urls = global.fetch.mock.calls.map(([url]) => String(url));
      expect(urls.some((url) => url.includes(`/events`))).toBe(true);
      expect(urls.some((url) => url.includes(`/notes`))).toBe(true);
    });
  });
});
