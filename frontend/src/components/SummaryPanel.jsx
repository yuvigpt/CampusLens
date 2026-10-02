import { BAND_ORDER, UNCLASSIFIED_LABEL } from '../constants.js';
import { ErrorBanner, Spinner } from './ui.jsx';

const pct = (count, total) => (total > 0 ? Math.round((count / total) * 100) : 0);
const slug = (value) => String(value).toLowerCase().replace(/[^a-z]/g, '');

function StatTile({ label, value, tone, hint }) {
  return (
    <div className={`stat${tone ? ` stat--${tone}` : ''}`}>
      <span className="stat__label">{label}</span>
      <strong className="stat__value">{value}</strong>
      {hint ? <span className="stat__hint">{hint}</span> : null}
    </div>
  );
}

/** Pure render of GET /api/analytics/summary. Counts are shown as returned. */
export default function SummaryPanel({ summary, error, loading, onRetry }) {
  if (error) {
    return (
      <ErrorBanner title="Analytics could not be loaded" message={error} onRetry={onRetry} />
    );
  }
  if (loading) {
    return (
      <div className="panel">
        <Spinner label="Loading analytics…" />
      </div>
    );
  }
  if (!summary) return null;

  const bandTotal = BAND_ORDER.reduce(
    (sum, band) => sum + (summary.by_priority_band[band] ?? 0),
    0,
  );
  const accounted = bandTotal + (summary.unscored ?? 0);
  const statuses = Object.entries(summary.by_status ?? {});
  const categories = Object.entries(summary.by_category ?? {}).sort((a, b) => b[1] - a[1]);

  return (
    <section className="summary" aria-label="Analytics summary">
      <div className="stats">
        <StatTile label="Total complaints" value={summary.total} />
        <StatTile
          label="Unresolved"
          value={summary.unresolved}
          tone="warn"
          hint="Anything not Resolved"
        />
        <StatTile
          label="Resolved"
          value={summary.by_status?.Resolved ?? 0}
          tone="good"
          hint="Backend says Resolved"
        />
        <StatTile
          label="Unscored"
          value={summary.unscored}
          tone="none"
          hint="No priority score"
        />
      </div>

      <div className="summary__grid">
        <div className="panel panel--sub">
          <h3>Priority mix</h3>
          <ul className="bars">
            {BAND_ORDER.map((band) => {
              const count = summary.by_priority_band[band] ?? 0;
              return (
                <li className="bar" key={band}>
                  <span className="bar__label">{band}</span>
                  <span className="bar__track">
                    <span
                      className={`bar__fill bar__fill--${slug(band)}`}
                      style={{ width: `${pct(count, summary.total)}%` }}
                    />
                  </span>
                  <span className="bar__count">{count}</span>
                </li>
              );
            })}
            <li className="bar bar--unscored">
              <span className="bar__label">Unscored</span>
              <span className="bar__track bar__track--dashed">
                <span
                  className="bar__fill bar__fill--unscored"
                  style={{ width: `${pct(summary.unscored, summary.total)}%` }}
                />
              </span>
              <span className="bar__count">{summary.unscored}</span>
            </li>
          </ul>
          <p className="muted small">
            Unscored complaints are counted separately and are never folded into Low.
            {accounted === summary.total ? ` Bands ${bandTotal} + unscored ${summary.unscored} = ${accounted} = total.` : ''}
          </p>
        </div>

        <div className="panel panel--sub">
          <h3>Status</h3>
          <ul className="breakdown">
            {statuses.map(([status, count]) => (
              <li key={status}>
                <span className={`dotpill dotpill--${slug(status)}`} aria-hidden="true" />
                <span className="breakdown__name">{status}</span>
                <span className="breakdown__count">
                  {count} · {pct(count, summary.total)}%
                </span>
              </li>
            ))}
          </ul>
        </div>

        <div className="panel panel--sub">
          <h3>Category</h3>
          {categories.length > 0 ? (
            <ul className="breakdown">
              {categories.map(([name, count]) => (
                <li key={name}>
                  <span className="breakdown__name">
                    {name === UNCLASSIFIED_LABEL ? 'Unclassified (no category)' : name}
                  </span>
                  <span className="breakdown__count">{count}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No categories recorded yet.</p>
          )}
        </div>
      </div>
    </section>
  );
}
