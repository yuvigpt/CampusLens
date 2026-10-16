import { AlertCircle } from 'lucide-react';

/**
 * Priority presentation.
 *
 * The band shown is ALWAYS `priority_band` exactly as the backend returned it;
 * nothing here recomputes a band from a score. A null score renders as
 * "Unscored" - never as Low, never as a guessed number.
 */

const toneOf = (band) => String(band || '').toLowerCase().replace(/[^a-z]/g, '');

const BAND_STYLES = {
  critical: 'bg-rose-100 text-rose-800 border-rose-200',
  high: 'bg-orange-100 text-orange-800 border-orange-200',
  medium: 'bg-amber-100 text-amber-800 border-amber-200',
  low: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  unscored: 'bg-slate-100 text-slate-500 border-slate-200 border-dashed'
};

const FILL_STYLES = {
  critical: 'bg-rose-600',
  high: 'bg-orange-500',
  medium: 'bg-amber-500',
  low: 'bg-emerald-500',
  unscored: 'bg-slate-400'
};

export function PriorityBadge({ band, score }) {
  if (!band) {
    return (
      <span
        className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-bold uppercase border ${BAND_STYLES.unscored}`}
        title="The backend returned no priority score for this complaint."
      >
        Unscored
      </span>
    );
  }

  const hasScore = typeof score === 'number';
  const style = BAND_STYLES[toneOf(band)] || BAND_STYLES.unscored;

  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-bold border ${style}`}>
      <span>{band}</span>
      {hasScore && (
        <span className="font-mono text-[10px] opacity-80 px-1.5 py-0.5 rounded bg-white/40">
          {score.toFixed(0)}
        </span>
      )}
    </span>
  );
}

export function ScoreMeter({ band, score }) {
  if (typeof score !== 'number') {
    return (
      <div className="flex flex-col gap-2 w-full">
        <div 
          className="h-2 rounded-full border border-slate-200 border-dashed bg-slate-50" 
          aria-hidden="true" 
        />
        <p className="text-xs text-slate-500">
          No priority score — this complaint is <strong className="font-semibold">not ranked</strong>.
        </p>
      </div>
    );
  }

  const pct = Math.max(0, Math.min(100, score));
  const fillStyle = FILL_STYLES[toneOf(band)] || FILL_STYLES.unscored;

  return (
    <div className="flex flex-col gap-1.5 w-full">
      <div className="h-2 rounded-full bg-slate-100 border border-slate-200 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 bar-grow ${fillStyle}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="flex justify-between items-baseline text-xs">
        <span className="font-mono font-bold text-slate-700">
          {score.toFixed(1)}
          <span className="font-sans font-medium text-slate-400 ml-1">/ 100</span>
        </span>
        {band && <span className="font-bold text-slate-600">{band}</span>}
      </div>
    </div>
  );
}

/** Explains why a complaint has no score, without inventing a severity. */
export function UnscoredNote() {
  return (
    <div className="mt-4 flex items-start gap-3 p-3 bg-slate-50 border-l-4 border-slate-300 rounded-r-lg">
      <AlertCircle className="w-5 h-5 text-slate-400 shrink-0 mt-0.5" />
      <p className="text-sm text-slate-600 m-0">
        <strong className="font-semibold text-slate-800">No priority score.</strong> The backend did not score this complaint
        (analysis failed or the category has no mapping), so it is deliberately left
        unranked rather than assumed to be low priority.
      </p>
    </div>
  );
}
