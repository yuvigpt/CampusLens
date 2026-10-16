/**
 * Dedicated complaint detail page (route #/complaint/{id}).
 *
 * Pins three behaviours: the full report + AI analysis render for the owner,
 * deletion asks for confirmation and then calls DELETE /api/complaints/{id}
 * before returning to the list, and a 404 (someone else's row or missing id)
 * renders an honest "not found" state instead of a broken page.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

import { jsonResponse } from './setup.js';

const ID = 'abc12345-1111-4222-8333-444455556666';

const COMPLAINT = {
  id: ID,
  description: 'Leaking pipe above the urinal in Hall 4 washroom',
  location: 'Hall 4, Block B',
  status: 'In Progress',
  created_at: '2026-01-05T10:00:00Z',
  resolved_at: null,
  image_url: null,
  analysis_status: 'succeeded',
  ai_category: 'Plumbing',
  ai_summary: 'Pipe leak confirmed near the washroom ceiling.',
  ai_evidence: 'Water pooling below a ceiling joint; photo shows a wet patch.',
  ai_uncertainty: null,
  ai_urgency: 'High',
  ai_impact: 'Medium',
  ai_safety: 'Low',
  priority_band: 'High',
};

async function mountDetail({ notFound = false } = {}) {
  vi.resetModules();

  vi.doMock('../src/lib/supabase.js', () => ({
    authConfigured: true,
    supabase: {
      auth: {
        getSession: vi.fn(async () => ({
          data: {
            session: {
              access_token: 'tok-1',
              user: { id: 'u1', email: 'stu@iitk.ac.in' },
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

  global.fetch = vi.fn(async (url, init = {}) => {
    const href = String(url);
    if (href.includes('/api/me')) {
      return jsonResponse(200, {
        id: 'u1', email: 'stu@iitk.ac.in', full_name: 'Stu',
        role: 'student', created_at: null,
      });
    }
    if (href.includes(`/api/complaints/${ID}`) && init.method === 'DELETE') {
      return jsonResponse(204, null);
    }
    if (href.includes(`/api/complaints/${ID}`)) {
      return notFound
        ? jsonResponse(404, { detail: 'Complaint not found.' })
        : jsonResponse(200, COMPLAINT);
    }
    return jsonResponse(200, []);
  });

  const RTL = await import('@testing-library/react');
  const { AuthProvider } = await import('../src/auth.jsx');
  const ComplaintDetailPage = (await import('../src/pages/ComplaintDetailPage.jsx')).default;

  RTL.render(
    <AuthProvider>
      <ComplaintDetailPage complaintId={ID} />
    </AuthProvider>,
  );

  return RTL;
}

function deleteCalls() {
  return global.fetch.mock.calls.filter(
    ([url, init]) =>
      String(url).includes(`/api/complaints/${ID}`) && (init || {}).method === 'DELETE',
  );
}

let cleanupFn = null;

afterEach(() => {
  if (cleanupFn) cleanupFn();
  cleanupFn = null;
  window.location.hash = '';
});

describe('Complaint detail page', () => {
  it('shows the full report with the AI analysis for the owner', async () => {
    const app = await mountDetail();
    cleanupFn = app.cleanup;

    await app.screen.findByText(/leaking pipe/i);
    expect(app.screen.getByText('Pipe leak confirmed near the washroom ceiling.')).toBeTruthy();
    expect(app.screen.getByText('Water pooling below a ceiling joint; photo shows a wet patch.')).toBeTruthy();
    expect(app.screen.getByText('High priority')).toBeTruthy();
    expect(app.screen.getByRole('button', { name: /delete report/i })).toBeTruthy();
  });

  it('asks for confirmation, then deletes and returns to the list', async () => {
    const app = await mountDetail();
    cleanupFn = app.cleanup;

    await app.screen.findByText(/leaking pipe/i);
    await app.fireEvent.click(app.screen.getByRole('button', { name: /delete report/i }));

    // The confirmation panel appears; nothing is sent yet.
    await app.screen.findByRole('alertdialog', { name: /confirm deletion/i });
    expect(deleteCalls()).toHaveLength(0);

    await app.fireEvent.click(
      app.screen.getByRole('button', { name: /yes, delete permanently/i }),
    );

    await vi.waitFor(() => {
      expect(deleteCalls()).toHaveLength(1);
      expect(window.location.hash).toBe('#/mine');
    });
  });

  it('renders an honest not-found state for a 404', async () => {
    const app = await mountDetail({ notFound: true });
    cleanupFn = app.cleanup;

    await app.screen.findByText(/complaint not found/i);
    expect(app.screen.queryByRole('button', { name: /delete report/i })).toBeNull();
  });
});
