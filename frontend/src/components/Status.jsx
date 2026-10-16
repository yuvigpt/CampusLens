import { STATUSES } from '../constants.js';

/**
 * Status is displayed and edited using only the three exact strings the backend
 * accepts (database.ALLOWED_STATUSES).
 */

const STATUS_STYLE = {
  Reported: 'bg-slate-100 text-slate-700 border-slate-200',
  'In Progress': 'bg-blue-50 text-blue-700 border-blue-200',
  Resolved: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  unknown: 'bg-slate-100 text-slate-500 border-slate-200'
};

export function StatusBadge({ status }) {
  const style = STATUS_STYLE[status] || STATUS_STYLE.unknown;
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold tracking-wide uppercase border ${style}`}>
      {status}
    </span>
  );
}

export function StatusSelect({ id, value, onChange, disabled, complaintId }) {
  // Fall back to the first allowed value so the control never renders an
  // unrecognised status; the badge above still shows the real stored value.
  const safeValue = STATUSES.includes(value) ? value : STATUSES[0];

  return (
    <select
      id={id}
      className="w-full bg-white border border-slate-300 text-slate-900 text-sm rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 block px-3 py-2 transition-shadow disabled:opacity-50 disabled:cursor-not-allowed"
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

