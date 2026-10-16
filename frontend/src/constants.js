/**
 * Vocabularies mirrored from the backend so the UI only ever offers values the
 * API actually accepts. These describe INPUT choices and labels - they never
 * decide a complaint's priority. Bands and scores always come from the API.
 */

// database.ALLOWED_STATUSES - exact strings, including the spaces.
export const STATUSES = ['Reported', 'In Progress', 'Resolved'];

// Backend sorts: admin list accepts priority | newest | oldest.
export const SORTS = [
  { value: 'priority', label: 'Priority - highest first' },
  { value: 'newest', label: 'Newest first' },
  { value: 'oldest', label: 'Oldest first' },
];

// Admin list accepts limit up to 200.
export const LIMIT_OPTIONS = [10, 20, 50, 100];

// Band names, most severe first. Boundary values live in the backend only.
export const BAND_ORDER = ['Critical', 'High', 'Medium', 'Low'];

export const SCORE_MAX = 100;

// Confirmed scoring inputs: Low | Medium | High.
export const LEVELS = ['Low', 'Medium', 'High'];

// The three admin-confirmed levels, in the order the API expects them.
export const SCORING_FIELDS = [
  { key: 'confirmed_urgency', label: 'Urgency', max: 30 },
  { key: 'confirmed_impact', label: 'Impact', max: 25 },
  { key: 'confirmed_safety', label: 'Safety', max: 10 },
];

// Backend upload limits (app/scoring.py). Mirrored so an unusable file is
// rejected before a round trip; the backend re-validates regardless.
export const ACCEPTED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
export const ACCEPTED_IMAGE_EXTENSIONS = '.jpg,.jpeg,.png,.webp';
export const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
export const MAX_IMAGE_MB = MAX_IMAGE_BYTES / (1024 * 1024);
