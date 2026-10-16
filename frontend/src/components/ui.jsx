import { Loader2, AlertTriangle, Info, CheckCircle2, CircleDashed } from 'lucide-react';

/**
 * Small presentational helpers shared by both pages.
 */

export function Spinner({ label = 'Loading' }) {
  return (
    <p className="flex items-center justify-center gap-2 text-slate-500 font-medium" role="status" aria-live="polite">
      <Loader2 className="w-5 h-5 animate-spin text-indigo-500" aria-hidden="true" />
      <span>{label}</span>
    </p>
  );
}

export function ErrorBanner({ title = 'Something went wrong', message, onRetry, retryLabel = 'Try again' }) {
  if (!message) return null;
  return (
    <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4 bg-rose-50 border border-rose-200 rounded-xl p-4 shadow-sm animate-fade-up" role="alert">
      <div className="flex-1 flex flex-col gap-1">
        <strong className="text-sm font-bold text-rose-800">{title}</strong>
        <p className="text-sm text-rose-700 m-0">{message}</p>
      </div>
      {onRetry ? (
        <button type="button" className="px-3 py-1.5 bg-white border border-rose-200 hover:bg-rose-100 text-rose-700 text-sm font-medium rounded-lg transition-colors" onClick={onRetry}>
          {retryLabel}
        </button>
      ) : null}
    </div>
  );
}

const TONE_STYLES = {
  success: 'bg-emerald-50 border-emerald-200 text-emerald-800',
  warning: 'bg-amber-50 border-amber-200 text-amber-800',
  info: 'bg-blue-50 border-blue-200 text-blue-800',
};

const TONE_ICON = {
  success: <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0 mt-0.5" />,
  warning: <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />,
  info: <Info className="w-5 h-5 text-blue-600 shrink-0 mt-0.5" />,
};

export function Notice({ tone = 'info', title, children }) {
  const style = TONE_STYLES[tone] || TONE_STYLES.info;
  const icon = TONE_ICON[tone] || TONE_ICON.info;

  return (
    <div className={`flex items-start gap-3 p-4 rounded-xl border shadow-sm animate-fade-up ${style}`} role={tone === 'warning' ? 'alert' : 'status'}>
      {icon}
      <div className="flex-1 text-sm flex flex-col gap-1 [&>p]:m-0">
        {title ? <strong className="font-bold opacity-90">{title}</strong> : null}
        <div className="opacity-80 leading-relaxed">{children}</div>
      </div>
    </div>
  );
}

export function EmptyState({ title, body, hint, action }) {
  return (
    <div className="flex flex-col items-center justify-center text-center p-12 bg-slate-50 border border-slate-200 border-dashed rounded-xl gap-2 min-h-[200px] animate-fade-up">
      <CircleDashed className="w-10 h-10 text-slate-300 mb-2 animate-float" aria-hidden="true" />
      <h3 className="text-lg font-bold text-slate-800 m-0">{title}</h3>
      {body && <p className="text-sm text-slate-500 m-0 max-w-md">{body}</p>}
      {hint ? <p className="text-sm text-slate-500 m-0 max-w-md">{hint}</p> : null}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function SkeletonRows({ count = 3 }) {
  return (
    <div className="flex flex-col gap-4" aria-hidden="true">
      {Array.from({ length: count }, (_, index) => (
        /* .skeleton adds a travelling sheen (styles.css) instead of the flat
           grey pulse; animation-delay staggers the rows down the list. */
        <div
          className="h-48 rounded-xl skeleton"
          key={index}
          style={{ animationDelay: `${index * 120}ms` }}
        />
      ))}
      <span className="sr-only">Loading complaints</span>
    </div>
  );
}
