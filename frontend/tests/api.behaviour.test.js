import { describe, expect, it, vi } from 'vitest';

import { jsonResponse } from './setup.js';

async function loadApi() {
  return import('../src/api.js');
}

describe('api.js - error handling', () => {
  it('parses a FastAPI HTTPException detail string', async () => {
    global.fetch.mockResolvedValue(jsonResponse(502, { detail: 'Image storage unavailable.' }));
    const { submitComplaint } = await loadApi();
    await expect(submitComplaint({}, 'tok')).rejects.toThrow('Image storage unavailable.');
  });

  it('parses a FastAPI 422 validation list into readable text', async () => {
    const body = {
      detail: [{ loc: ['body', 'description'], msg: 'field required', type: 'missing' }],
    };
    global.fetch.mockResolvedValue(jsonResponse(422, body));
    const { listMyComplaints } = await loadApi();
    await expect(listMyComplaints({}, 'tok')).rejects.toThrow('description: field required');
  });

  it('fires the unauthorized hook on 401 and reports the status', async () => {
    let fired = 0;
    const { onUnauthorized, listMyComplaints } = await loadApi();
    onUnauthorized(() => { fired += 1; });
    global.fetch.mockResolvedValue(jsonResponse(401, { detail: 'Invalid token.' }));
    await expect(listMyComplaints({}, 'tok')).rejects.toMatchObject({ status: 401 });
    expect(fired).toBe(1);
  });

  it('reports a friendly message when the API is unreachable', async () => {
    global.fetch.mockRejectedValue(new TypeError('network down'));
    const { fetchHealth } = await loadApi();
    await expect(fetchHealth()).rejects.toThrow(/Cannot reach the CampusLens API/);
  });

  it('surfaces 403 for a non-admin hitting an admin route', async () => {
    global.fetch.mockResolvedValue(jsonResponse(403, { detail: 'Administrator access required.' }));
    const { listAllComplaints } = await loadApi();
    await expect(listAllComplaints({}, 'tok')).rejects.toMatchObject({ status: 403 });
  });
});

describe('api.js - response passthrough', () => {
  it('returns the student payload unchanged, including no score fields', async () => {
    const row = {
      id: 'c1',
      description: 'Broken light',
      location: 'Science Block',
      status: 'Reported',
      image_url: null,
      analysis_status: null,
    };
    global.fetch.mockResolvedValue(jsonResponse(200, [row]));
    const { listMyComplaints } = await loadApi();
    const rows = await listMyComplaints({}, 'tok');
    expect(rows).toHaveLength(1);
    expect(rows[0]).not.toHaveProperty('priority_score');
    expect(rows[0]).not.toHaveProperty('score_breakdown');
  });

  it('keeps an absolute signed image_url unchanged', async () => {
    const { imageUrl } = await loadApi();
    const signed = 'https://project.supabase.co/storage/v1/object/sign/x?token=abc';
    expect(imageUrl(signed)).toBe(signed);
  });

  it('resolves a relative image_url against the API base', async () => {
    const { imageUrl } = await loadApi();
    expect(imageUrl('/uploads/a.jpg')).toBe('http://127.0.0.1:8000/uploads/a.jpg');
  });

  it('returns null image_url unchanged', async () => {
    const { imageUrl } = await loadApi();
    expect(imageUrl(null)).toBeNull();
    expect(imageUrl('')).toBeNull();
  });
});
