import { BAND_ORDER } from '../constants.js';
import { EmptyState, ErrorBanner, Notice, Spinner } from './ui.jsx';

const slug = (value) => String(value).toLowerCase().replace(/[^a-z0-9]+/g, '-');

function pct(count, total) {
  if (!total) return 0;
  return Math.round((count / total) * 100);
}

const TONE_STYLES = {
  neutral: 'bg-white text-slate-800 border-slate-200',
  warn: 'bg-amber-50 text-amber-900 border-amber-200',
  good: 'bg-emerald-50 text-emerald-900 border-emerald-200',
  none: 'bg-slate-50 text-slate-500 border-slate-200 border-dashed'
};

function StatTile({ label, value, tone = 'neutral', hint, index = 0 }) {
  const style = TONE_STYLES[tone] || TONE_STYLES.neutral;
  return (
    <div
      className={`flex flex-col p-4 rounded-xl border ${style} shadow-sm card-lift animate-fade-up`}
      style={{ animationDelay: `${index * 60}ms` }}
    >
      <span className="text-3xl font-bold font-mono tracking-tight mb-1">{value}</span>
      <span className="text-sm font-semibold uppercase tracking-wider opacity-80">{label}</span>
      {hint && <span className="text-xs opacity-70 mt-auto pt-2">{hint}</span>}
    </div>
  );
}

const FILL_STYLES = {
  critical: 'bg-rose-500',
  high: 'bg-orange-500',
  medium: 'bg-amber-500',
  low: 'bg-emerald-500',
  unscored: 'bg-slate-400'
};

const DOT_STYLES = {
  reported: 'bg-slate-400',
  'in-progress': 'bg-blue-500',
  resolved: 'bg-emerald-500'
};

export default function SummaryPanel({ summary, loading, error, onRetry }) {
  if (error) {
    return <ErrorBanner title="Analytics could not be loaded" message={error} onRetry={onRetry} />;
  }
  if (loading) {
    return (
      <div className="bg-white p-8 rounded-xl border border-slate-200 shadow-sm flex items-center justify-center min-h-[200px]">
        <Spinner label="Loading analytics..." />
      </div>
    );
  }
  if (!summary) return null;

  const byBand = summary.by_band || {};
  const bandTotal = BAND_ORDER.reduce((sum, band) => sum + (byBand[band] ?? 0), 0);
  const unscored = summary.unscored ?? 0;
  const accounted = bandTotal + unscored;
  const statuses = Object.entries(summary.by_status || {});

  return (
    <section className="flex flex-col gap-6" aria-label="Analytics summary">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatTile label="Total complaints" value={summary.total} index={0} />
        <StatTile label="Unresolved" value={summary.unresolved} tone="warn" hint="Anything not Resolved" index={1} />
        <StatTile label="Resolved" value={(summary.by_status || {}).Resolved ?? 0} tone="good" hint="Backend says Resolved" index={2} />
        <StatTile label="Unscored" value={unscored} tone="none" hint="No priority score" index={3} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex flex-col gap-4">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">Priority mix</h3>
          <ul className="flex flex-col gap-3">
            {BAND_ORDER.map((band) => {
              const count = byBand[band] ?? 0;
              const fill = FILL_STYLES[slug(band)] || FILL_STYLES.unscored;
              return (
                <li className="flex items-center gap-3 text-sm" key={band}>
                  <span className="w-16 font-medium text-slate-700">{band}</span>
                  <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
                    <div className={`h-full rounded-full bar-grow ${fill}`} style={{ width: `${pct(count, summary.total)}%` }} />
                  </div>
                  <span className="w-8 text-right font-mono text-slate-500">{count}</span>
                </li>
              );
            })}
            <li className="flex items-center gap-3 text-sm opacity-80 mt-2 pt-2 border-t border-slate-100">
              <span className="w-16 font-medium text-slate-500">Unscored</span>
              <div className="flex-1 h-2 bg-slate-50 border border-slate-200 border-dashed rounded-full overflow-hidden">
                <div className="h-full rounded-full bg-slate-300 bar-grow" style={{ width: `${pct(unscored, summary.total)}%` }} />
              </div>
              <span className="w-8 text-right font-mono text-slate-500">{unscored}</span>
            </li>
          </ul>
          <p className="text-xs text-slate-400 mt-2">
            Unscored complaints are counted separately and are never folded into Low.
            {accounted === summary.total ? ` Bands ${bandTotal} + unscored ${unscored} = ${accounted} = total.` : ''}
          </p>
        </div>

        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex flex-col gap-4">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">Status</h3>
          {statuses.length > 0 ? (
            <ul className="flex flex-col gap-3">
              {statuses.map(([status, count]) => (
                <li className="flex items-center gap-3 text-sm p-2 rounded-lg hover:bg-slate-50 transition-colors" key={status}>
                  <span className={`w-2 h-2 rounded-full ${DOT_STYLES[slug(status)] || DOT_STYLES.reported}`} aria-hidden="true" />
                  <span className="flex-1 font-medium text-slate-700">{status}</span>
                  <span className="font-mono text-slate-500">
                    {count} <span className="opacity-50 ml-1">- {pct(count, summary.total)}%</span>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="No complaints yet" body="Nothing has been reported." />
          )}
        </div>

        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex flex-col gap-4">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">Scoring</h3>
          <Notice tone="info">
            <p className="text-sm text-blue-800 leading-relaxed">
              A priority score only exists once an administrator confirms the
              urgency, impact and safety levels. Until then a complaint stays
              <strong className="font-semibold text-blue-900"> Unscored</strong>.
            </p>
          </Notice>
        </div>
      </div>
    </section>
  );
}
