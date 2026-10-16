/**
 * The public approval gate, exercised through the frontend API client.
 *
 * A complaint must only reach the public feed through an explicit, admin-only
 * approval request. These tests pin the client contract for that flow.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';

import { jsonResponse } from './setup.js';

const BASE = 'http://127.0.0.1:8000';

async function loadApi() {
  return import('../src/api.js');
}

beforeEach(() => {
  global.fetch = vi.fn();
});

describe('admin publication flow', () => {
  it('POSTs sanitized text to the approval route with the token', async () => {
    global.fetch.mockResolvedValue(
      jsonResponse(200, {
        id: 'p1',
        public_summary: 'Lighting fault reported',
        public_category: 'Electrical',
        public_location: 'Science Block',
        status: 'Reported',
        approved_at: '2026-01-01T00:00:00Z',
      }),
    );
    const { approveForPublic } = await loadApi();
    await approveForPublic(
      'c-1',
      {
        public_summary: 'Lighting fault reported',
        public_category: 'Electrical',
        public_location: 'Science Block',
      },
      'tok',
    );
    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toBe(`${BASE}/api/admin/complaints/c-1/public-approval`);
    expect(init.method).toBe('POST');
    expect(init.headers.Authorization).toBe('Bearer tok');
    expect(JSON.parse(init.body)).toEqual({
      public_summary: 'Lighting fault reported',
      public_category: 'Electrical',
      public_location: 'Science Block',
    });
  });

  it('sends only the admin-authored text, never the complaint body', async () => {
    global.fetch.mockResolvedValue(jsonResponse(200, {}));
    const { approveForPublic } = await loadApi();
    const input = {
      public_summary: 'Lighting fault reported',
      public_category: 'Electrical',
      public_location: 'Science Block',
    };
    await approveForPublic('c-1', input, 'tok');
    const sent = JSON.parse(global.fetch.mock.calls[0][1].body);
    // No reporter fields are ever included in the approval payload.
    expect(sent.description).toBeUndefined();
    expect(sent.student_id).toBeUndefined();
    expect(sent.location_raw).toBeUndefined();
    expect(Object.keys(sent).sort()).toEqual([
      'public_category', 'public_location', 'public_summary',
    ]);
  });

  it('DELETEs to withdraw, with the token', async () => {
    global.fetch.mockResolvedValue({ ok: true, status: 204, statusText: 'No Content', text: async () => '' });
    const { revokeForPublic } = await loadApi();
    await revokeForPublic('c-1', 'tok');
    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toBe(`${BASE}/api/admin/complaints/c-1/public-approval`);
    expect(init.method).toBe('DELETE');
    expect(init.headers.Authorization).toBe('Bearer tok');
  });

  it('reports a 403 when a non-admin attempts to publish', async () => {
    global.fetch.mockResolvedValue(
      jsonResponse(403, { detail: 'Administrator access required.' }),
    );
    const { approveForPublic } = await loadApi();
    await expect(
      approveForPublic('c-1', { public_summary: 'x'.repeat(15), public_category: 'E', public_location: 'S' }, 'tok'),
    ).rejects.toMatchObject({ status: 403 });
  });

  it('returns null when a complaint is not published', async () => {
    global.fetch.mockResolvedValue(jsonResponse(200, null));
    const { getPublicApproval } = await loadApi();
    expect(await getPublicApproval('c-1', 'tok')).toBeNull();
  });
});

describe('public feed client', () => {
  it('reads the feed without an Authorization header', async () => {
    global.fetch.mockResolvedValue(jsonResponse(200, []));
    const { fetchPublicComplaints } = await loadApi();
    await fetchPublicComplaints();
    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toContain('/api/public/complaints');
    expect(init.headers.Authorization).toBeUndefined();
  });

  it('renders only the approved fields the backend returns', async () => {
    global.fetch.mockResolvedValue(
      jsonResponse(200, [
        {
          id: 'p1',
          public_summary: 'Lighting fault reported',
          public_category: 'Electrical',
          public_location: 'Science Block',
          status: 'Reported',
          approved_at: '2026-01-01T00:00:00Z',
        },
      ]),
    );
    const { fetchPublicComplaints } = await loadApi();
    const rows = await fetchPublicComplaints();
    expect(Object.keys(rows[0]).sort()).toEqual([
      'approved_at', 'id', 'public_category', 'public_location',
      'public_summary', 'status',
    ]);
    // Internal fields are absent from the payload entirely.
    expect(rows[0].student_id).toBeUndefined();
    expect(rows[0].priority_score).toBeUndefined();
  });
});
