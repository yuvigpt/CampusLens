/**
 * Small presentational helpers shared by both pages.
 */

export function Spinner({ label = 'Loading' }) {
  return (
    <p className="spinner" role="status" aria-live="polite">
      <span className="spinner__ring" aria-hidden="true" />
      <span>{label}</span>
    </p>
  );
}

export function ErrorBanner({ title = 'Something went wrong', message, onRetry, retryLabel = 'Try again' }) {
  if (!message) return null;
  return (
    <div className="banner banner--error" role="alert">
      <div className="banner__text">
        <strong>{title}</strong>
        <p>{message}</p>
      </div>
      {onRetry ? (
        <button type="button" className="btn btn--ghost" onClick={onRetry}>
          {retryLabel}
        </button>
      ) : null}
    </div>
  );
}

const TONE_MARK = {
  success: '✓',
  warning: '!',
  info: 'i',
};

export function Notice({ tone = 'info', title, children }) {
  return (
    <div className={`banner banner--${tone}`} role={tone === 'warning' ? 'alert' : 'status'}>
      <span className={`banner__mark banner__mark--${tone}`} aria-hidden="true">
        {TONE_MARK[tone] || 'i'}
      </span>
      <div className="banner__text">
        {title ? <strong>{title}</strong> : null}
        {children}
      </div>
    </div>
  );
}

export function EmptyState({ title, hint, action }) {
  return (
    <div className="empty">
      <div className="empty__glyph" aria-hidden="true">◎</div>
      <h3>{title}</h3>
      {hint ? <p>{hint}</p> : null}
      {action}
    </div>
  );
}

export function SkeletonRows({ count = 3 }) {
  return (
    <div className="skeletons" aria-hidden="true">
      {Array.from({ length: count }, (_, index) => (
        <div className="skeleton" key={index} />
      ))}
      <span className="sr-only">Loading complaints</span>
    </div>
  );
}
