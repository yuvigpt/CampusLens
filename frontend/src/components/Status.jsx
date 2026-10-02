import { STATUSES } from '../constants.js';

/**
 * Status is displayed and edited using only the three exact strings the backend
 * accepts (database.ALLOWED_STATUSES).
 */

const STATUS_TONE = {
  Reported: 'reported',
  'In Progress': 'progress',
  Resolved: 'resolved',
};

export function StatusBadge({ status }) {
  const tone = STATUS_TONE[status] || 'unknown';
  return <span className={`badge badge--status badge--${tone}`}>{status}</span>;
}

export function StatusSelect({ id, value, onChange, disabled, complaintId }) {
  // Fall back to the first allowed value so the control never renders an
  // unrecognised status; the badge above still shows the real stored value.
  const safeValue = STATUSES.includes(value) ? value : STATUSES[0];

  return (
    <select
      id={id}
      className="select select--status"
      value={safeValue}
      disabled={disabled}
      aria-label={`Status for complaint ${complaintId}`}
      onChange={(event) => onChange(event.target.value)}
    >
      {STATUSES.map((status) => (
        <option key={status} value={status}>
          {status}
        </option>
      ))}
    </select>
  );
}
