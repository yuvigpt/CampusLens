/**
 * My-complaints list: every card links to its dedicated detail page, and the
 * search box sends `q` to the backend (which searches WITHIN the caller's own
 * rows only - the isolation is a backend guarantee, this only pins the wiring).
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

import { jsonResponse } from './setup.js';

const COMPLAINT = {
  id: 'abc12345-1111-4222-8333-444455556666',
  description: 'Leaking pipe above the urinal in Hall 4 washroom',
  location: 'Hall 4, Block B',
  status: 'Reported',
  created_at: '2026-01-05T10:00:00Z',
  resolved_at: null,
  image_url: null,
  analysis_status: 'succeeded',
  ai_category: 'Plumbing',
  ai_summary: 'Pipe leak confirmed near the washroom ceiling.',
  ai_evidence: null,
  ai_uncertainty: null,
  ai_urgency: 'High',
  ai_impact: 'Medium',
  ai_safety: 'Low',
  priority_band: 'High',
};

async function mountPage() {
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

  global.fetch = vi.fn(async (url) => {
    const href = String(url);
    if (href.includes('/api/me')) {
      return jsonResponse(200, {
        id: 'u1', email: 'stu@iitk.ac.in', full_name: 'Stu',
        role: 'student', created_at: null,
      });
    }
    if (href.includes('/api/complaints')) {
      return jsonResponse(200, [COMPLAINT]);
    }
    return jsonResponse(200, []);
  });

  const RTL = await import('@testing-library/react');
  const { AuthProvider } = await import('../src/auth.jsx');
  const MyComplaintsPage = (await import('../src/pages/MyComplaintsPage.jsx')).default;

  RTL.render(
    <AuthProvider>
      <MyComplaintsPage />
    </AuthProvider>,
  );

  await RTL.screen.findByText(/leaking pipe/i);
  return RTL;
}

function listUrls() {
  return global.fetch.mock.calls
    .map(([url]) => String(url))
    .filter((url) => url.includes('/api/complaints'));
}

let cleanupFn = null;

afterEach(() => {
  if (cleanupFn) cleanupFn();
  cleanupFn = null;
});

describe('My complaints page', () => {
  it('links each complaint card to its dedicated detail page', async () => {
    const app = await mountPage();
    cleanupFn = app.cleanup;

    const link = await app.screen.findByRole('link', { name: /open complaint/i });
    expect(link.getAttribute('href')).toBe(`#/complaint/${COMPLAINT.id}`);
    // The card shows the analysis honestly.
    expect(app.screen.getByText('Analysed')).toBeTruthy();
    expect(app.screen.getByText('High')).toBeTruthy();
  });

  it('sends the search text to the backend as q', async () => {
    const app = await mountPage();
    cleanupFn = app.cleanup;

    await app.fireEvent.change(app.screen.getByLabelText('Search'), {
      target: { value: 'leak' },
    });
    await app.fireEvent.submit(app.screen.getByRole('search'));

    await vi.waitFor(() => {
      expect(listUrls().some((url) => url.includes('q=leak'))).toBe(true);
    });
  });

  it('sends the status filter to the backend', async () => {
    const app = await mountPage();
    cleanupFn = app.cleanup;

    await app.fireEvent.change(app.screen.getByLabelText('Status'), {
      target: { value: 'Resolved' },
    });

    await vi.waitFor(() => {
      expect(listUrls().some((url) => url.includes('status=Resolved'))).toBe(true);
    });
  });
});
