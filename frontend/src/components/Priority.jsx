/**
 * Priority presentation.
 *
 * The band shown is ALWAYS `priority_band` exactly as the backend returned it;
 * nothing here recomputes a band from a score. A null score renders as
 * "Unscored" - never as Low, never as a guessed number.
 */

const toneOf = (band) => String(band || '').toLowerCase().replace(/[^a-z]/g, '');

export function PriorityBadge({ band, score }) {
  if (!band) {
    return (
      <span
        className="badge badge--unscored"
        title="The backend returned no priority score for this complaint."
      >
        Unscored
      </span>
    );
  }

  const hasScore = typeof score === 'number';
  return (
    <span className={`badge badge--band badge--${toneOf(band)}`}>
      {band}
      {hasScore ? <span className="badge__score">{score.toFixed(0)}</span> : null}
    </span>
  );
}

export function ScoreMeter({ band, score }) {
  if (typeof score !== 'number') {
    return (
      <div className="meter meter--empty">
        <div className="meter__track meter__track--dashed" aria-hidden="true" />
        <p className="meter__caption">
          No priority score — this complaint is <strong>not ranked</strong>.
        </p>
      </div>
    );
  }

  const pct = Math.max(0, Math.min(100, score));
  return (
    <div className="meter">
      <div className="meter__track">
        <div
          className={`meter__fill meter__fill--${toneOf(band)}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="meter__scale">
        <span className="meter__value">
          {score.toFixed(1)}
          <span className="meter__max"> / 100</span>
        </span>
        {band ? <span className="meter__band">{band}</span> : null}
      </div>
    </div>
  );
}

/** Explains why a complaint has no score, without inventing a severity. */
export function UnscoredNote() {
  return (
    <p className="unscored-note">
      <strong>No priority score.</strong> The backend did not score this complaint
      (analysis failed or the category has no mapping), so it is deliberately left
      unranked rather than assumed to be low priority.
    </p>
  );
}
