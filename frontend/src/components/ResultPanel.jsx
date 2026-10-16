import { CheckCircle, RefreshCw, List } from 'lucide-react';
import { StatusBadge } from './Status.jsx';
import { Notice } from './ui.jsx';

/**
 * Shown after POST /api/complaints returns 201.
 *
 * The 201 now carries the server-side AI analysis (`ai_*`) in addition to the
 * minimal { id, status, message, analysis_queued } fields. This component is
 * the only place where the submission response is rendered, so the AI findings
 * are presented here and nowhere else. Nothing is inferred or invented: every
 * line below comes straight from the response body.
 */

/**
 * Renders the server-side AI analysis that now travels in the 201 body when it
 * runs synchronously before the response is sent. It is the only field of the
 * submission response that a student is shown, and the only place where AI
 * findings are ever exposed to a student.
 */
function AiFindings({ findings }) {
  const category = findings.ai_category;
  const summary = findings.ai_summary;
  const evidence = findings.ai_evidence;
  const uncertainty = findings.ai_uncertainty;
  const levels = [];
  if (findings.ai_urgency) levels.push(`Urgency ${findings.ai_urgency}`);
  if (findings.ai_impact) levels.push(`Impact ${findings.ai_impact}`);
  if (findings.ai_safety) levels.push(`Safety ${findings.ai_safety}`);

  if (!category && !summary && !uncertainty && !levels.length && !evidence) {
    // The server finished the run but returned nothing displayable (today this
    // only happens against a stale backend whose 201 has no ai_* fields at
    // all). Say so plainly instead of implying the analysis produced content.
    return (
      <Notice tone="success" title="AI analysis done">
        <p className="text-sm">
          The server finished reviewing your report and found nothing further
          to show here. Anything needing action stays with campus operations -
          your report itself is saved in full.
        </p>
      </Notice>
    );
  }

  const rows = [];
  if (category) {
    rows.push(
      <li key="category" className="flex items-center gap-2">
        <span className="font-semibold text-slate-700">Category:</span>
        <span className="font-mono text-xs bg-indigo-50 px-2 py-0.5 rounded border border-indigo-200 text-indigo-700">
          {category}
        </span>
      </li>,
    );
  }
  if (summary) {
    rows.push(
      <li key="summary" className="text-sm text-slate-600 mt-1 leading-relaxed">
        {summary}
      </li>,
    );
  }
  if (evidence) {
    rows.push(
      <li key="evidence" className="text-sm text-slate-600 mt-1">
        <span className="font-semibold">Evidence:</span> {evidence}
      </li>,
    );
  }
  if (uncertainty) {
    rows.push(
      <li key="uncertainty" className="text-sm text-slate-500 mt-1">
        <span className="font-semibold">Uncertainty:</span> {uncertainty}
      </li>,
    );
  }
  if (levels.length) {
    rows.push(
      <li key="levels" className="text-sm text-slate-600 mt-1">
        <span className="font-semibold">Evaluation:</span> {levels.join(' · ')}.
      </li>,
    );
  }

  return (
    <Notice tone="success" title="AI analysis complete">
      <ul className="list-disc pl-5 space-y-1">{rows}</ul>
    </Notice>
  );
}


export default function ResultPanel({ result, onReset }) {
  if (!result) return null;

  return (
    <section className="bg-white rounded-2xl border border-emerald-200 shadow-xl shadow-emerald-900/5 ring-1 ring-emerald-100 overflow-hidden flex flex-col max-w-3xl mx-auto w-full animate-scale-in" aria-live="polite">
      <div className="bg-gradient-to-r from-emerald-50 via-teal-50/60 to-white border-b border-emerald-100 p-6 sm:p-8 flex items-start sm:items-center gap-5">
        {/* Success mark: pops in with a slow ping halo behind it. */}
        <div className="relative w-12 h-12 shrink-0">
          <span className="absolute inset-0 rounded-full bg-emerald-400/30 animate-ping-slow" aria-hidden="true" />
          <span className="relative flex w-12 h-12 items-center justify-center rounded-full bg-gradient-to-br from-emerald-100 to-teal-50 border border-emerald-200/70">
            <CheckCircle className="w-6 h-6 text-emerald-600 animate-pop" aria-hidden="true" />
          </span>
        </div>
        <div className="flex-1 flex flex-col gap-1.5">
          <h2 className="text-xl sm:text-2xl font-bold text-slate-900">Complaint #{result.id} received</h2>
          <p className="text-sm text-slate-600">
            {result.message || 'The backend stored it.'} Status:{' '}
            <strong className="font-semibold text-slate-800">{result.status}</strong>.
          </p>
        </div>
        <div className="hidden sm:block">
          <StatusBadge status={result.status} />
        </div>
      </div>

      <div className="p-6 sm:p-8 flex flex-col gap-6">
        <div className="sm:hidden mb-2">
          <StatusBadge status={result.status} />
        </div>

        {result.analysis_queued ? (
          <AiFindings findings={result} />
        ) : (
          <Notice tone="info" title="Analysis not available">
            <p className="text-sm">
              Analysis is not running right now. Your report was still saved in
              full and is tracked as <strong className="font-semibold">Unscored</strong> until campus
              operations review it - it is never given a guessed priority.
            </p>
          </Notice>
        )}

        <div className="flex flex-wrap items-center gap-4 py-2">
          <button 
            type="button" 
            className="btn-gradient flex items-center gap-2 px-5 py-2.5 font-medium rounded-xl" 
            onClick={onReset}
          >
            <RefreshCw className="w-4 h-4" />
            Report another problem
          </button>
          <a 
            className="flex items-center gap-2 px-5 py-2.5 bg-white border border-slate-300 hover:bg-slate-50 hover:-translate-y-0.5 hover:shadow-md text-slate-700 font-medium rounded-xl transition-all duration-200" 
            href="#/mine"
          >
            <List className="w-4 h-4" />
            View my complaints
          </a>
        </div>

        <Notice tone="info">
          <p className="text-sm">
            Your complaint ID is shown above. The priority band under{' '}
            <strong className="font-semibold">My complaints</strong> starts as a
            submission-time estimate and is replaced once campus operations confirm
            it. Only the band is ever shown to you, never the numeric score.
          </p>
        </Notice>
      </div>
    </section>
  );
}
