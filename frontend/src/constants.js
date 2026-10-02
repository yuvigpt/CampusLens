/**
 * Vocabularies mirrored from the backend so the UI only ever offers values the
 * API actually accepts. These constants describe INPUT choices and labels -
 * they never decide a complaint's priority. Bands and scores always come from
 * the API response.
 */

// database.ALLOWED_STATUSES - exact strings, including the spaces.
export const STATUSES = ['Reported', 'In Progress', 'Resolved'];

// database._ALLOWED_SORTS keys.
export const SORTS = [
  { value: 'priority', label: 'Priority · highest first' },
  { value: 'newest', label: 'Newest first' },
  { value: 'oldest', label: 'Oldest first' },
];

// priority.BAND_THRESHOLDS band names, most severe first.
export const BAND_ORDER = ['Critical', 'High', 'Medium', 'Low'];

export const SCORE_MAX = 100;

// gemini.ALLOWED_IMAGE_TYPES / gemini.MAX_IMAGE_BYTES - mirrored so we can
// reject an unusable file before spending a round trip.
export const ACCEPTED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
export const ACCEPTED_IMAGE_EXTENSIONS = '.jpg,.jpeg,.png,.webp';
export const MAX_IMAGE_BYTES = 8 * 1024 * 1024;
export const MAX_IMAGE_MB = MAX_IMAGE_BYTES / (1024 * 1024);

// GET /api/complaints accepts limit up to 1000.
export const LIMIT_OPTIONS = [10, 20, 50, 100];

// analytics.UNSCORED_LABEL / UNCLASSIFIED_LABEL.
export const UNSCORED_LABEL = 'Unscored';
export const UNCLASSIFIED_LABEL = 'Unclassified';
