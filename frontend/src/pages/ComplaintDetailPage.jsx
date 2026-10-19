import { useCallback, useEffect, useState } from 'react';
import {
  ArrowLeft, BarChart2, Calendar, CheckCircle, Clock, Image as ImageIcon,
  MapPin, Trash2,
} from 'lucide-react';

import { deleteMyComplaint, getMyComplaint, imageUrl } from '../api.js';
import { useAuth } from '../auth.jsx';
import { StatusBadge } from '../components/Status.jsx';
import { EmptyState, ErrorBanner, Notice, SkeletonRows } from '../components/ui.jsx';

const ANALYSIS_LABEL = {
  succeeded: 'Analysis complete',
  failed: 'Analysis unavailable',
  pending: 'Analysis pending',
};

function hasAIFound(complaint) {
  return Boolean(
    complaint.ai_category ||
    complaint.ai_urgency ||
    complaint.ai_impact ||
    complaint.ai_safety ||
    complaint.ai_summary
  );
}

function AIBadge({ severity }) {
  if (!severity) return null;
  const tone = {
    Low: 'bg-slate-100 text-slate-600',
    Medium: 'bg-amber-100 text-amber-700',
    High: 'bg-red-100 text-red-700',
  }[severity] || 'bg-slate-100 text-slate-600';
  return (
    <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold ${tone}`}>
      {severity}
    </span>
  );
}

function MetaRow({ icon, label, children }) {
  return (
    <div className="flex items-center justify-between text-sm py-2 border-b border-slate-100 last:border-0">
      <span className="text-slate-500 font-medium flex items-center gap-2">{icon}{label}</span>
      <span className="text-slate-800 font-medium text-right">{children}</span>
    </div>
  );
}

/**
 * Dedicated detail page for ONE of the student's own complaints.
 *
 * Route: `#/complaint/{id}` -> GET /api/complaints/{id} (own rows only; the
 * backend 404s for anyone else's row). Shows the full report plus every AI
 * analysis field the student is allowed to see (coarse band, never the
 * numeric score) and offers deletion, which the backend also re-checks.
 */
export default function ComplaintDetailPage({ complaintId }) {
  const { token, email } = useAuth();
  const [complaint, setComplaint] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState(null);

  const load = useCallback(async () => {
    if (!token || !complaintId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    setDeleteError(null);
    setConfirming(false);
    try {
      const row = await getMyComplaint(complaintId, token);
      setComplaint(row);
    } catch (caught) {
      setComplaint(null);
      setError(caught);
    } finally {
      setLoading(false);
    }
  }, [token, complaintId]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleDelete() {
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteMyComplaint(complaintId, token);
      // The row is gone; return to the list. On success no state update is
      // needed - the hash change unmounts this page.
      window.location.hash = '#/mine';
    } catch (caught) {
      setDeleteError(caught.message);
      setDeleting(false);
    }
  }

  if (!token) {
    return (
      <div className="flex flex-col gap-6 max-w-3xl mx-auto">
        <Notice tone="info">
          <p className="text-sm">
            Sign in to view this report.{' '}
            <a className="font-semibold underline" href="#/signin">Sign in</a>
          </p>
        </Notice>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex flex-col gap-6 max-w-3xl mx-auto">
        <a href="#/mine" className="text-sm font-medium text-indigo-600 hover:text-indigo-800 inline-flex items-center gap-1.5 w-fit">
          <ArrowLeft className="w-4 h-4" /> Back to my complaints
        </a>
        <SkeletonRows count={3} />
      </div>
    );
  }

  const notFound = error && (error.status === 404 || /not found/i.test(error.message || ''));
  if (notFound) {
    return (
      <div className="flex flex-col gap-6 max-w-3xl mx-auto">
        <a href="#/mine" className="text-sm font-medium text-indigo-600 hover:text-indigo-800 inline-flex items-center gap-1.5 w-fit">
          <ArrowLeft className="w-4 h-4" /> Back to my complaints
        </a>
        <EmptyState
          title="Complaint not found"
          body="This report does not exist, was deleted, or belongs to another account."
          action={
            <a className="btn-gradient inline-flex px-5 py-2.5 font-medium rounded-xl" href="#/mine">
              Back to my complaints
            </a>
          }
        />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col gap-6 max-w-3xl mx-auto">
        <a href="#/mine" className="text-sm font-medium text-indigo-600 hover:text-indigo-800 inline-flex items-center gap-1.5 w-fit">
          <ArrowLeft className="w-4 h-4" /> Back to my complaints
        </a>
        <ErrorBanner title="This report could not be loaded" message={error.message} onRetry={load} />
      </div>
    );
  }

  if (!complaint) {
    return null;
  }

  return (
    <div className="flex flex-col gap-6 max-w-3xl mx-auto animate-fade-up">
      <a
        href="#/mine"
        className="text-sm font-medium text-indigo-600 hover:text-indigo-800 inline-flex items-center gap-1.5 w-fit"
      >
        <ArrowLeft className="w-4 h-4" /> Back to my complaints
      </a>

      {/* Header: id, status, band, delete */}
      <header className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-2">
          <h1 className="font-mono font-extrabold text-xl text-slate-900 m-0">
            #{(complaint.id || '').slice(0, 8).toUpperCase()}
          </h1>
          <div className="flex items-center gap-2 flex-wrap">
            <StatusBadge status={complaint.status} />
            {complaint.priority_band ? (
              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold bg-indigo-50 text-indigo-700 border border-indigo-100">
                {complaint.priority_band} priority
              </span>
            ) : (
              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-100 text-slate-500 border border-slate-200 italic">
                Not yet rated
              </span>
            )}
          </div>
          <p className="text-xs text-slate-500 m-0">
            Signed in as <strong>{email || 'unknown'}</strong>
          </p>
        </div>

        <button
          type="button"
          onClick={() => setConfirming((value) => !value)}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold text-red-600 bg-white border border-red-200 hover:bg-red-50 transition-colors"
        >
          <Trash2 className="w-4 h-4" /> Delete report
        </button>
      </header>

      {/* Delete confirmation */}
      {confirming ? (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 flex flex-col gap-3" role="alertdialog" aria-label="Confirm deletion">
          <div className="flex items-start gap-2.5">
            <Trash2 className="w-5 h-5 text-red-500 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-bold text-red-800 m-0">Delete this report permanently?</p>
              <p className="text-sm text-red-700 m-0 mt-1 leading-relaxed">
                The report, its photo, its analysis and its history will be removed.
                This cannot be undone.
              </p>
            </div>
          </div>
          {deleteError ? (
            <p className="text-sm font-semibold text-red-700 m-0">Delete failed: {deleteError}</p>
          ) : null}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setConfirming(false)}
              disabled={deleting}
              className="px-4 py-2 rounded-xl text-sm font-semibold border border-slate-300 bg-white hover:bg-slate-50 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleDelete}
              disabled={deleting}
              className="px-4 py-2 rounded-xl text-sm font-semibold text-white bg-red-600 hover:bg-red-700 disabled:opacity-50 inline-flex items-center gap-2"
            >
              {deleting ? 'Deleting...' : 'Yes, delete permanently'}
            </button>
          </div>
        </div>
      ) : null}
      {/* Photo + description */}
      <section className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <figure className="h-64 bg-slate-50 border-b border-slate-100 overflow-hidden relative m-0">
          {complaint.image_url ? (
            <a
              href={imageUrl(complaint.image_url)}
              target="_blank"
              rel="noopener noreferrer"
              className="block w-full h-full relative group cursor-zoom-in"
              title="View full-resolution photo in a new tab"
            >
              <img
                src={imageUrl(complaint.image_url)}
                alt="Photo you uploaded with this report"
                loading="lazy"
                decoding="async"
                className="w-full h-full object-cover transition-transform duration-200 group-hover:scale-[1.02]"
              />
            </a>
          ) : (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-slate-400">
              <ImageIcon className="w-10 h-10 opacity-40" />
              <span className="text-xs font-medium uppercase tracking-wider">No photo</span>
            </div>
          )}
        </figure>
        <div className="p-5">
          <p className="text-sm text-slate-700 leading-relaxed m-0 whitespace-pre-wrap break-words">
            {complaint.description}
          </p>
        </div>
      </section>

      {/* Details + AI analysis side by side on wide screens */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-start">
        <section className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
          <h2 className="text-sm font-bold uppercase tracking-wider text-slate-500 m-0 mb-2">Details</h2>
          <MetaRow icon={<MapPin className="w-4 h-4 text-indigo-400" />} label="Location">
            {complaint.location}
          </MetaRow>
          <MetaRow icon={<Calendar className="w-4 h-4" />} label="Submitted">
            {complaint.created_at
              ? new Date(complaint.created_at).toLocaleString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })
              : 'Unknown'}
          </MetaRow>
          {complaint.resolved_at ? (
            <MetaRow icon={<CheckCircle className="w-4 h-4 text-emerald-500" />} label="Resolved">
              {new Date(complaint.resolved_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
            </MetaRow>
          ) : null}
          <MetaRow icon={<Clock className="w-4 h-4" />} label="Analysis">
            {ANALYSIS_LABEL[complaint.analysis_status] || (hasAIFound(complaint) ? 'Analysis complete' : 'Not started')}
          </MetaRow>
          <MetaRow icon={<BarChart2 className="w-4 h-4 text-indigo-400" />} label="Priority band">
            {complaint.priority_band ? (
              <strong className="text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded border border-indigo-100">
                {complaint.priority_band}
              </strong>
            ) : (
              <span className="italic text-slate-400">Not yet rated</span>
            )}
          </MetaRow>
        </section>

        <section className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
          <div className="flex items-center gap-2 mb-3">
            <BarChart2 className="w-4 h-4 text-indigo-400" />
            <h2 className="text-sm font-bold uppercase tracking-wider text-slate-500 m-0">AI analysis</h2>
          </div>
          {complaint.ai_summary || complaint.ai_category ? (
            <div className="flex flex-col gap-3">
              {complaint.ai_category ? (
                <div className="flex items-center justify-between text-sm">
                  <span className="text-slate-500 font-medium">Category</span>
                  <span className="text-slate-800 font-semibold">{complaint.ai_category}</span>
                </div>
              ) : null}
              {complaint.ai_summary ? (
                <div className="text-sm">
                  <span className="text-slate-500 font-medium block mb-1">Summary</span>
                  <p className="text-slate-700 leading-relaxed m-0">{complaint.ai_summary}</p>
                </div>
              ) : null}
              {complaint.ai_evidence ? (
                <div className="text-sm">
                  <span className="text-slate-500 font-medium block mb-1">Evidence</span>
                  <p className="text-slate-700 leading-relaxed m-0">{complaint.ai_evidence}</p>
                </div>
              ) : null}
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-500 font-medium">Urgency</span>
                <AIBadge severity={complaint.ai_urgency} />
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-500 font-medium">Impact</span>
                <AIBadge severity={complaint.ai_impact} />
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-500 font-medium">Safety</span>
                <AIBadge severity={complaint.ai_safety} />
              </div>
              {complaint.ai_uncertainty ? (
                <div className="text-sm pt-2 mt-1 border-t border-slate-100">
                  <span className="text-slate-500 font-medium block mb-1">Uncertainty</span>
                  <p className="text-slate-600 leading-relaxed m-0">{complaint.ai_uncertainty}</p>
                </div>
              ) : null}
            </div>
          ) : (
            <p className="text-sm text-slate-400 italic m-0">
              AI analysis is not available for this report. It was still saved in full.
            </p>
          )}
        </section>
      </div>

      <Notice tone="info">
        <p className="text-sm leading-relaxed">
          The numeric priority score and its breakdown stay internal to campus
          operations - you only ever see the coarse band above.
        </p>
      </Notice>
    </div>
  );
}