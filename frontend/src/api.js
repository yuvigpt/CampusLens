/**
 * Thin client for the CampusLens API.
 *
 * Two things about the real backend drive this code:
 *
 *  1. Errors are `{"detail": "..."}` for FastAPI HTTPException but
 *     `{"detail": [{loc, msg, type}, ...]}` for FastAPI's own request
 *     validation, so the parser below handles both shapes.
 *  2. `image_url` is root-relative (`/uploads/<name>`), so the API base URL
 *     must be prefixed before a browser can load it.
 *
 * The Gemini key lives only in backend/.env and is never referenced here.
 */

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';
export const API_BASE = String(RAW_BASE).trim().replace(/\/+$/, '');

export class ApiError extends Error {
  constructor(message, { status = 0, payload = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload;
  }
}

export function apiUrl(path) {
  const suffix = path.startsWith('/') ? path : `/${path}`;
  return `${API_BASE}${suffix}`;
}

/** Turn the backend's relative `image_url` into something loadable. */
export function imageUrl(path) {
  if (!path) return null;
  return apiUrl(path);
}

function describePayload(payload, fallback) {
  const detail = payload ? payload.detail : undefined;

  if (typeof detail === 'string' && detail.trim()) {
    return detail.trim();
  }

  if (Array.isArray(detail) && detail.length > 0) {
    const parts = detail.map((item) => {
      if (typeof item === 'string') return item;
      const rawLoc = item && Array.isArray(item.loc) ? item.loc : [];
      // Drop the "body"/"query" prefix so messages read naturally.
      const loc = rawLoc.filter((part) => part !== 'body' && part !== 'query').join(' ');
      const msg = (item && item.msg) || 'invalid value';
      return loc ? `${loc}: ${msg}` : msg;
    });
    return parts.join(' · ');
  }

  return fallback;
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(apiUrl(path), options);
  } catch {
    throw new ApiError(
      `Cannot reach the CampusLens API at ${API_BASE}. Is the backend running?`,
      { status: 0 },
    );
  }

  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const fallback = `Request failed (${response.status}${
      response.statusText ? ` ${response.statusText}` : ''
    })`;
    throw new ApiError(describePayload(payload, fallback), {
      status: response.status,
      payload,
    });
  }

  return payload;
}

function buildQuery(params) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    query.set(key, String(value));
  });
  const rendered = query.toString();
  return rendered ? `?${rendered}` : '';
}

/** GET /api/complaints - status, category, sort, limit, offset. */
export function listComplaints(params = {}) {
  return request(`/api/complaints${buildQuery(params)}`);
}

export function getComplaint(id) {
  return request(`/api/complaints/${id}`);
}

/** POST /api/complaints - multipart fields: image, description, location. */
export function submitComplaint(formData) {
  // Content-Type is deliberately NOT set: the browser has to add the
  // multipart boundary itself.
  return request('/api/complaints', { method: 'POST', body: formData });
}

/** PATCH /api/complaints/{id}/status - body is exactly {"status": "..."}. */
export function updateStatus(id, status) {
  return request(`/api/complaints/${id}/status`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  });
}

export function fetchSummary() {
  return request('/api/analytics/summary');
}

export function fetchHealth() {
  return request('/api/health');
}
