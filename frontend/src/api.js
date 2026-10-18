/**
 * Thin client for the CampusLens API.
 *
 * Every protected call carries the current Supabase access token as
 * `Authorization: Bearer <token>`. The backend verifies that token and reads
 * the user's role from the database - nothing about identity is trusted here.
 *
 * Endpoint map (matches backend/app/routers/complaints.py):
 *   GET    /api/health                            no auth
 *   POST   /api/complaints                        student+   multipart
 *   GET    /api/complaints                        student    own rows only
 *   GET    /api/complaints/{id}                   student    own rows only
 *   GET    /api/admin/complaints                  admin
 *   GET    /api/admin/complaints/{id}             admin
 *   PATCH  /api/admin/complaints/{id}/status      admin
 *   PATCH  /api/admin/complaints/{id}/analysis    admin
 *   GET    /api/admin/analytics/summary           admin
 *   GET    /api/admin/complaints/{id}/events      admin  audit trail
 *   GET    /api/admin/complaints/{id}/notes       admin  investigation notes
 *   POST   /api/admin/complaints/{id}/notes       admin  add a note
 *   DELETE /api/complaints/{id}                   student own rows / admin any
 *   GET    /api/community/campus                  any signed-in user
 *   GET    /api/public/complaints                 no auth
 *
 * Three real backend behaviours this client handles:
 *   1. errors are `{"detail": "..."}` for HTTPException but a list of
 *      validation objects for FastAPI 422s - both shapes are parsed;
 *   2. a 401 means the session expired, so an onUnauthorized hook fires;
 *   3. image_url is already an absolute short-lived signed URL, used as-is.
 */

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';
export const API_BASE = String(RAW_BASE).trim().replace(/\/+$/, '');

let unauthorizedHandler = null;

/** Register a callback fired whenever the API answers 401. */
export function onUnauthorized(handler) {
  unauthorizedHandler = handler;
}

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

/**
 * An image_url from the backend is already absolute (a short-lived signed URL),
 * so it is returned unchanged. Relative values resolve against the API base.
 */
export function imageUrl(value) {
  if (!value) return null;
  if (/^https?:\/\//i.test(value)) return value;
  return apiUrl(value);
}

function describePayload(payload, fallback) {
  const detail = payload ? payload.detail : undefined;
  if (typeof detail === 'string' && detail.trim()) return detail.trim();
  if (Array.isArray(detail) && detail.length > 0) {
    const parts = detail.map((item) => {
      if (typeof item === 'string') return item;
      const rawLoc = item && Array.isArray(item.loc) ? item.loc : [];
      const loc = rawLoc.filter((p) => p !== 'body' && p !== 'query').join(' ');
      const msg = (item && item.msg) || 'invalid value';
      return loc ? `${loc}: ${msg}` : msg;
    });
    return parts.join(' - ');
  }
  return fallback;
}

function authHeaders(token) {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request(path, { token = null, ...options } = {}) {
  let response;
  const isTest = typeof process !== 'undefined' && process.env?.NODE_ENV === 'test';
  const maxRetries = isTest ? 0 : 2;

  let lastFetchError = null;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      response = await fetch(apiUrl(path), {
        ...options,
        headers: { ...authHeaders(token), ...(options.headers || {}) },
      });
      // If Render free tier returns 502/503/504 while waking up, retry
      if ([502, 503, 504].includes(response.status) && attempt < maxRetries) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        continue;
      }
      lastFetchError = null;
      break;
    } catch (err) {
      lastFetchError = err;
      if (attempt < maxRetries) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        continue;
      }
    }
  }

  if (lastFetchError) {
    throw new ApiError(
      'Cannot reach the CampusLens API (Error in backend service). The server may be waking up - please retry in a moment.',
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
    if (response.status === 401 && typeof unauthorizedHandler === 'function') {
      unauthorizedHandler();
    }
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

function buildQuery(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    query.set(key, String(value));
  });
  const rendered = query.toString();
  return rendered ? `?${rendered}` : '';
}

// ---------------------------------------------------------------------------
// Public - no token required
// ---------------------------------------------------------------------------
export function fetchHealth() {
  return request('/api/health');
}

/** Approved, sanitized complaints. */
export function fetchPublicComplaints(params = {}) {
  return request(`/api/public/complaints${buildQuery(params)}`);
}

// ---------------------------------------------------------------------------
// Student
// ---------------------------------------------------------------------------

/**
 * POST /api/complaints - multipart fields: image, description, location.
 * Content-Type is deliberately NOT set: the browser must add the boundary.
 */
export function submitComplaint(formData, token) {
  return request('/api/complaints', { method: 'POST', body: formData, token });
}

/** Own complaints only. status | sort=newest|oldest | limit | offset */
export function listMyComplaints(params = {}, token) {
  return request(`/api/complaints${buildQuery(params)}`, { token });
}

export function getMyComplaint(id, token) {
  return request(`/api/complaints/${encodeURIComponent(id)}`, { token });
}

/**
 * DELETE /api/complaints/{id} -> 204.
 *
 * The backend 404s when the row is someone else's or missing (existence of
 * another student's complaint is never disclosed). Child rows cascade.
 */
export function deleteMyComplaint(id, token) {
  return request(`/api/complaints/${encodeURIComponent(id)}`, {
    method: 'DELETE',
    token,
  });
}

/**
 * GET /api/community/campus - sanitized campus-wide small info.
 * Returns [{id, location, status, band, category, created_at}] - never a
 * reporter identity, description text or a numeric score.
 */
export function listCampusComplaints(token) {
  return request('/api/community/campus', { token });
}

/**
 * GET /api/me - the caller's own profile.
 *
 * The backend derives the user id from the VERIFIED JWT and reads the role from
 * the `profiles` table, so nothing sent from here can influence the result.
 *
 * A failure propagates on purpose: the caller must NOT quietly fall back to
 * "student", because that would hide the admin tab from a real administrator.
 * Hiding admin UI is cosmetic anyway - every admin request is authorised again
 * server-side.
 */
export function getMyProfile(token) {
  return request('/api/me', { token });
}

// ---------------------------------------------------------------------------
// Admin
// ---------------------------------------------------------------------------
export function listAllComplaints(params = {}, token) {
  return request(`/api/admin/complaints${buildQuery(params)}`, { token });
}

export function getAdminComplaint(id, token) {
  return request(`/api/admin/complaints/${encodeURIComponent(id)}`, { token });
}

/** PATCH /api/admin/complaints/{id}/status - body is exactly {"status": "..."} */
export function updateStatus(id, status, token) {
  return request(`/api/admin/complaints/${encodeURIComponent(id)}/status`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
    token,
  });
}

/**
 * PATCH /api/admin/complaints/{id}/analysis
 * body: { confirmed_urgency, confirmed_impact, confirmed_safety }
 * This is the ONLY endpoint that produces a score.
 */
export function confirmAnalysis(id, inputs, token) {
  return request(`/api/admin/complaints/${encodeURIComponent(id)}/analysis`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(inputs),
    token,
  });
}

/** GET /api/admin/analytics/summary - total, by_status, by_band, unscored, unresolved */
export function fetchSummary(token) {
  return request('/api/admin/analytics/summary', { token });
}

/** GET /api/admin/complaints/{id}/events - append-only audit trail. */
export function listComplaintEvents(id, token) {
  return request(`/api/admin/complaints/${encodeURIComponent(id)}/events`, { token });
}

/** GET /api/admin/complaints/{id}/notes - investigation notes (admin-only). */
export function listInvestigationNotes(id, token) {
  return request(`/api/admin/complaints/${encodeURIComponent(id)}/notes`, { token });
}

/** POST /api/admin/complaints/{id}/notes - body: {body: "..."} */
export function addInvestigationNote(id, body, token) {
  return request(`/api/admin/complaints/${encodeURIComponent(id)}/notes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ body }),
    token,
  });
}


// ---------------------------------------------------------------------------
// Public approval (admin only)
// ---------------------------------------------------------------------------
/**
 * Publish a sanitized complaint to the community feed.
 *
 * The three fields are supplied by the admin and stored verbatim - nothing is
 * copied from the reporter's own text, so a summary can never leak it.
 * This is the only route that makes a complaint public.
 */
export function approveForPublic(id, input, token) {
  return request(`/api/admin/complaints/${encodeURIComponent(id)}/public-approval`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
    token,
  });
}

/** Withdraw a complaint from the feed. The entry becomes a draft again. */
export function revokeForPublic(id, token) {
  return request(`/api/admin/complaints/${encodeURIComponent(id)}/public-approval`, {
    method: 'DELETE',
    token,
  });
}

/** Publication state for one complaint; null when it is not published. */
export function getPublicApproval(id, token) {
  return request(`/api/admin/complaints/${encodeURIComponent(id)}/public-approval`, {
    token,
  });
}
