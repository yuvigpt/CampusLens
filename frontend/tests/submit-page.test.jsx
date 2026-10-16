/**
 * Regression: the complaint form must accept a submission with NO photo.
 *
 * The backend accepts `image: Optional[UploadFile]` (`File(None)`), but the
 * form used to refuse to send unless a file was attached, and `onSubmit`
 * built the multipart body with `form.set('image', file, file.name)`, which
 * throws when `file` is null. Both are guarded now: validation only checks a
 * file that is actually present, and the request only appends one.
 *
 * These tests mount the real <SubmitPage/> signed in, with fetch stubbed:
 *  1. description + location, NO photo  -> POST goes out without an image part.
 *  2. the same, WITH a photo           -> POST carries the chosen file.
 *  3. an invalid file type, when chosen -> a field error, and NO request.
 *  4. empty text fields                 -> the other validation is untouched.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

import { jsonResponse } from './setup.js';

/** Mount <SubmitPage/> as a signed-in student.

  * @param {object} [responseBody] - the JSON body the mocked POST /api/complaints
  *   returns; defaults to a submission with no analysis performed.
  */
async function mountSubmitPage(responseBody = {
  id: '1', status: 'Reported', message: 'Complaint received.',
  analysis_queued: false,
}) {
  vi.resetModules();

  vi.doMock('../src/lib/supabase.js', () => ({
    authConfigured: true,
    supabase: {
      auth: {
        getSession: vi.fn(async () => ({
          data: {
            session: {
              access_token: 'tok-1',
              user: { id: 'u1', email: 'student@example.test' },
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

  global.fetch = vi.fn(async (url, init = {}) => {
    const href = String(url);
    if (href.includes('/api/me')) {
      return jsonResponse(200, {
        id: 'u1', email: 'student@example.test', full_name: 'Stu',
        role: 'student', created_at: null,
      });
    }
    if (href.includes('/api/complaints') && init.method === 'POST') {
      return jsonResponse(201, responseBody);
    }
    return jsonResponse(200, []);
  });

  // jsdom has no object URLs; the preview effect only needs them not to throw.
  if (typeof URL.createObjectURL !== 'function') {
    URL.createObjectURL = () => 'blob:mock-photo';
  }
  if (typeof URL.revokeObjectURL !== 'function') {
    URL.revokeObjectURL = () => {};
  }
  // jsdom's scrollTo raises "not implemented"; the success path calls it.
  window.scrollTo = () => {};

  const RTL = await import('@testing-library/react');
  const { AuthProvider } = await import('../src/auth.jsx');
  const SubmitPage = (await import('../src/pages/SubmitPage.jsx')).default;

  RTL.render(
    <AuthProvider>
      <SubmitPage />
    </AuthProvider>,
  );

  // The form itself proves the signed-in branch rendered.
  await vi.waitFor(() => {
    expect(RTL.screen.getByRole('button', { name: /submit complaint/i })).toBeTruthy();
  });

  return RTL;
}

function complaintsPosts() {
  return global.fetch.mock.calls.filter(
    ([url, init]) => String(url).includes('/api/complaints') && (init || {}).method === 'POST',
  );
}

const DESCRIPTION = 'The ceiling light in lab 3 has been flickering since Monday.';
const LOCATION = 'Block C, Lab 3';

let cleanupFn = null;

afterEach(() => {
  if (cleanupFn) cleanupFn();
  cleanupFn = null;
  vi.doUnmock('../src/lib/supabase.js');
});

describe('SubmitPage - optional photo', () => {
  it('submits description and location with no photo attached', async () => {
    const app = await mountSubmitPage();
    cleanupFn = app.cleanup;

    app.fireEvent.change(app.screen.getByLabelText(/what is wrong/i), {
      target: { value: DESCRIPTION },
    });
    app.fireEvent.change(app.screen.getByLabelText(/where on campus/i), {
      target: { value: LOCATION },
    });
    app.fireEvent.click(app.screen.getByRole('button', { name: /submit complaint/i }));

    await vi.waitFor(() => {
      expect(complaintsPosts().length).toBe(1);
    });

    const [, init] = complaintsPosts()[0];
    expect(init.headers.Authorization).toBe('Bearer tok-1');
    // No image part is sent at all - this used to throw on `file.name`.
    expect(init.body.get('image')).toBeNull();
    expect(init.body.get('description')).toContain('flickering');
    expect(init.body.get('location')).toContain('Block C');

    await vi.waitFor(() => {
      expect(app.screen.getByRole('heading', { name: /complaint #1 received/i })).toBeTruthy();
    });
  });

  it('still sends the photo when one is selected', async () => {
    const app = await mountSubmitPage();
    cleanupFn = app.cleanup;

    const file = new File(['fake-bytes'], 'fault.jpg', { type: 'image/jpeg' });
    app.fireEvent.change(app.screen.getByLabelText(/photo of the problem/i), {
      target: { files: [file] },
    });
    app.fireEvent.change(app.screen.getByLabelText(/what is wrong/i), {
      target: { value: DESCRIPTION },
    });
    app.fireEvent.change(app.screen.getByLabelText(/where on campus/i), {
      target: { value: LOCATION },
    });
    app.fireEvent.click(app.screen.getByRole('button', { name: /submit complaint/i }));

    await vi.waitFor(() => {
      expect(complaintsPosts().length).toBe(1);
    });

    const [, init] = complaintsPosts()[0];
    expect(init.body.get('image')?.name).toBe('fault.jpg');
  });

  it('still rejects an invalid file type when one is selected, without sending', async () => {
    const app = await mountSubmitPage();
    cleanupFn = app.cleanup;

    const bad = new File(['x'], 'notes.txt', { type: 'text/plain' });
    app.fireEvent.change(app.screen.getByLabelText(/photo of the problem/i), {
      target: { files: [bad] },
    });
    app.fireEvent.change(app.screen.getByLabelText(/what is wrong/i), {
      target: { value: DESCRIPTION },
    });
    app.fireEvent.change(app.screen.getByLabelText(/where on campus/i), {
      target: { value: LOCATION },
    });
    app.fireEvent.click(app.screen.getByRole('button', { name: /submit complaint/i }));

    await vi.waitFor(() => {
      const alerts = app.screen.getAllByRole('alert').map((n) => n.textContent);
      expect(alerts.some((t) => /unsupported image type/i.test(t))).toBe(true);
    });
    expect(complaintsPosts().length).toBe(0);
  });

  it('still requires description and location', async () => {
    const app = await mountSubmitPage();
    cleanupFn = app.cleanup;

    app.fireEvent.click(app.screen.getByRole('button', { name: /submit complaint/i }));

    await vi.waitFor(() => {
      const alerts = app.screen.getAllByRole('alert').map((n) => n.textContent);
      expect(alerts.some((t) => /describe what is wrong/i.test(t))).toBe(true);
      expect(alerts.some((t) => /where on campus/i.test(t))).toBe(true);
    });
    expect(complaintsPosts().length).toBe(0);
  });

  it('renders the server-side AI analysis once it completes', async () => {
    const responseBody = {
      id: '1', status: 'Reported', message: 'Complaint received.',
      analysis_queued: true,
      ai_category: 'Lighting fault',
      ai_summary: 'Ceiling light flickering since Monday.',
      ai_uncertainty: 'No other reports in the area.',
      ai_urgency: 'Medium', ai_impact: 'Low', ai_safety: 'Low',
    };
    const app = await mountSubmitPage(responseBody);
    cleanupFn = app.cleanup;

    app.fireEvent.change(app.screen.getByLabelText(/what is wrong/i), {
      target: { value: DESCRIPTION },
    });
    app.fireEvent.change(app.screen.getByLabelText(/where on campus/i), {
      target: { value: LOCATION },
    });
    app.fireEvent.click(app.screen.getByRole('button', { name: /submit complaint/i }));

    await vi.waitFor(() => {
      expect(complaintsPosts().length).toBe(1);
    });

    await vi.waitFor(() => {
      expect(app.screen.getByRole('heading', { name: /complaint #1 received/i })).toBeTruthy();
    });

    expect(app.screen.getByText('AI analysis complete')).toBeTruthy();
    expect(app.screen.getByText(/lighting fault/i)).toBeTruthy();
    expect(app.screen.getByText(/ceiling light flickering since monday/i)).toBeTruthy();
  });

  it('shows "AI analysis done" (not an invented analysis) when the run returns nothing', async () => {
    const responseBody = {
      id: '2', status: 'Reported', message: 'Complaint received.',
      analysis_queued: true,
      // No ai_* keys at all: a stale/partial 201 the old code would have
      // rendered as "produced nothing usable".
    };
    const app = await mountSubmitPage(responseBody);
    cleanupFn = app.cleanup;

    app.fireEvent.change(app.screen.getByLabelText(/what is wrong/i), {
      target: { value: DESCRIPTION },
    });
    app.fireEvent.change(app.screen.getByLabelText(/where on campus/i), {
      target: { value: LOCATION },
    });
    app.fireEvent.click(app.screen.getByRole('button', { name: /submit complaint/i }));

    await vi.waitFor(() => {
      expect(app.screen.getByRole('heading', { name: /complaint #2 received/i })).toBeTruthy();
    });

    // A completed-empty run says so honestly; it never invents findings and
    // the old "produced nothing usable" phrasing is gone.
    expect(app.screen.getByText('AI analysis done')).toBeTruthy();
    expect(app.screen.queryByText(/produced nothing usable/i)).toBeNull();
  });
});