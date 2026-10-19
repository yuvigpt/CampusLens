import { describe, expect, it, vi } from 'vitest';

import { jsonResponse, formBody } from './setup.js';

/** Import api.js fresh so the mocked fetch applies. */
async function loadApi() {
  const mod = await import('../src/api.js');
  return mod;
}

const BASE = 'http://127.0.0.1:8000';

describe('api.js - endpoint wiring', () => {
  it('calls GET /api/health with no auth header', async () => {
    global.fetch.mockResolvedValue(jsonResponse(200, { status: 'ok' }));
    const { fetchHealth } = await loadApi();
    await fetchHealth();
    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toBe(`${BASE}/api/health`);
    expect(init.headers.Authorization).toBeUndefined();
  });

  it('attaches Authorization: Bearer <token> to protected calls', async () => {
    global.fetch.mockResolvedValue(jsonResponse(200, []));
    const { listMyComplaints } = await loadApi();
    await listMyComplaints({}, 'tok-123');
    const [, init] = global.fetch.mock.calls[0];
    expect(init.headers.Authorization).toBe('Bearer tok-123');
  });

  it('never sends an Authorization header on public calls', async () => {
    global.fetch.mockResolvedValue(jsonResponse(200, []));
    const { fetchPublicComplaints } = await loadApi();
    await fetchPublicComplaints();
    const [, init] = global.fetch.mock.calls[0];
    expect(init.headers.Authorization).toBeUndefined();
  });

  it('POSTs multipart to /api/complaints without setting Content-Type', async () => {
    global.fetch.mockResolvedValue(jsonResponse(201, { id: '1', status: 'Reported' }));
    const { submitComplaint } = await loadApi();
    const form = formBody();
    await submitComplaint(form, 'tok');
    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toBe(`${BASE}/api/complaints`);
    expect(init.method).toBe('POST');
    expect(init.body).toBe(form);
    // The browser must add the multipart boundary itself.
    expect(init.headers['Content-Type']).toBeUndefined();
  });

  it('PATCHes status to the admin route with exactly {status}', async () => {
    global.fetch.mockResolvedValue(jsonResponse(200, { id: '1' }));
    const { updateStatus } = await loadApi();
    await updateStatus('abc', 'Resolved', 'tok');
    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toBe(`${BASE}/api/admin/complaints/abc/status`);
    expect(init.method).toBe('PATCH');
    expect(JSON.parse(init.body)).toEqual({ status: 'Resolved' });
  });

  it('PATCHes the three confirmed fields to the analysis route', async () => {
    global.fetch.mockResolvedValue(jsonResponse(200, { id: '1' }));
    const { confirmAnalysis } = await loadApi();
    await confirmAnalysis(
      'abc',
      { confirmed_urgency: 'High', confirmed_impact: 'Low', confirmed_safety: 'Low' },
      'tok',
    );
    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toBe(`${BASE}/api/admin/complaints/abc/analysis`);
    expect(JSON.parse(init.body)).toEqual({
      confirmed_urgency: 'High',
      confirmed_impact: 'Low',
      confirmed_safety: 'Low',
    });
  });

  it('builds admin and public query strings', async () => {
    global.fetch.mockResolvedValue(jsonResponse(200, []));
    const { listAllComplaints, fetchPublicComplaints } = await loadApi();
    await listAllComplaints({ status: 'Reported', sort: 'newest', limit: 20 }, 'tok');
    expect(global.fetch.mock.calls[0][0]).toContain('/api/admin/complaints?status=Reported');
    await fetchPublicComplaints({ limit: 10 });
    expect(global.fetch.mock.calls[1][0]).toContain('/api/public/complaints?limit=10');
  });

  describe('imageUrl() helper', () => {
    it('returns null for nullish or empty value', async () => {
      const { imageUrl } = await loadApi();
      expect(imageUrl(null)).toBeNull();
      expect(imageUrl('')).toBeNull();
      expect(imageUrl(undefined)).toBeNull();
    });

    it('resolves relative paths against API_BASE', async () => {
      const { imageUrl } = await loadApi();
      expect(imageUrl('/photos/pic.jpg')).toBe(`${BASE}/photos/pic.jpg`);
    });

    it('normalizes Supabase signed URLs missing /storage/v1', async () => {
      const { imageUrl } = await loadApi();
      const broken = 'https://abcdefgh.supabase.co/object/sign/CLimage/uid/pic.jpg?token=123';
      const fixed = imageUrl(broken);
      expect(fixed).toBe('https://abcdefgh.supabase.co/storage/v1/object/sign/CLimage/uid/pic.jpg?token=123');
    });

    it('leaves already canonical Supabase URLs intact', async () => {
      const { imageUrl } = await loadApi();
      const canonical = 'https://abcdefgh.supabase.co/storage/v1/object/sign/CLimage/uid/pic.jpg?token=123';
      expect(imageUrl(canonical)).toBe(canonical);
    });
  });
});

