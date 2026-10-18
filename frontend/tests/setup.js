/**
 * Shared test setup.
 *
 * The API is mocked with fetch, so these tests exercise the real api.js
 * (URL building, auth headers, error parsing, 401 handling) without ever
 * contacting a server or Supabase.
 */

import { afterEach, beforeEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

beforeEach(() => {
  global.fetch = vi.fn();
  vi.resetModules();
});

afterEach(() => {
  cleanup();
});

/** Build a Response-like object for the mocked fetch. */
export function jsonResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    text: async () => (body === null ? '' : JSON.stringify(body)),
  };
}

/** Minimal multipart body standing in for a browser FormData upload. */
export function formBody() {
  return {
    entries: () => [
      ['description', 'Broken light in the stairwell'],
      ['location', 'Science Block'],
    ],
  };
}
