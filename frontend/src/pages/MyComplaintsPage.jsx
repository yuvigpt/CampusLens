import { useCallback, useEffect, useRef, useState } from 'react';
import { BarChart2, Calendar, CheckCircle, ChevronRight, Clock, Image as ImageIcon, MapPin, Search, X } from 'lucide-react';

import { imageUrl, listMyComplaints } from '../api.js';
import { useAuth } from '../auth.jsx';
import { StatusBadge } from '../components/Status.jsx';
import { EmptyState, ErrorBanner, Notice, SkeletonRows } from '../components/ui.jsx';
import { STATUSES } from '../constants.js';

function hasAIFound(complaint) {
  return Boolean(
    complaint.ai_category ||
    complaint.ai_urgency ||
    complaint.ai_impact ||
    complaint.ai_safety ||
    complaint.ai_summary
  );
}

/**
 * The signed-in student's own complaints.
 *
 * List rows come from GET /api/complaints (own rows only, StudentComplaintOut:
 * AI analysis fields + coarse priority_band, never the numeric score). The
 * search box and the filters are sent to the backend as `q` / `status`, so the
 * search only ever matches WITHIN the caller's own rows.
 *
 * Each card is a link to the dedicated detail page `#/complaint/{id}`, which
 * shows the full report, the analysis and the delete action.
 */
export default function MyComplaintsPage({ initialQuery = '' }) {
  const { token, email } = useAuth();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Search: the input is debounced into `q`, and submitting the form applies
  // the current text immediately (the later debounce tick is a no-op).
  const [qInput, setQInput] = useState('');
  const [q, setQ] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [sort, setSort] = useState('newest');
  const requestRef = useRef(0);

  useEffect(() => {
    const timer = setTimeout(() => setQ(qInput.trim()), 300);
    return () => clearTimeout(timer);
  }, [qInput]);

  // The global top-bar search hands its query over via the hash (#/mine?q=...).
  useEffect(() => {
    setQInput(initialQuery);
    setQ(initialQuery);
  }, [initialQuery]);

  const load = useCallback(async () => {
    if (!token) {
      setLoading(false);
      return;
    }
    const id = requestRef.current + 1;
    requestRef.current = id;
    setLoading(true);
    setError(null);
    try {
      const rows = await listMyComplaints(
        { sort, limit: 50, q: q || undefined, status: statusFilter || undefined },
        token,
      );
      if (requestRef.current !== id) return;
      setItems(Array.isArray(rows) ? rows : []);
    } catch (caught) {
      if (requestRef.current !== id) return;
      setItems([]);
      setError(caught.message);
    } finally {
      if (requestRef.current === id) setLoading(false);
    }
  }, [token, q, statusFilter, sort]);

  useEffect(() => {
    load();
  }, [load]);

  const filtersActive = Boolean(q || statusFilter);

  function clearFilters() {
    setQInput('');
    setQ('');
    setStatusFilter('');
  }
  return (
    <div className="flex flex-col gap-8 max-w-5xl mx-auto">
      <header className="flex flex-col gap-2 animate-fade-up">
        <p className="text-xs font-bold uppercase tracking-widest text-gradient">Student</p>
        <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">My complaints</h1>
        <p className="text-slate-600 max-w-3xl text-lg mt-2 leading-relaxed">
          Only your own reports are listed here. Signed in as{' '}
          <strong className="font-semibold text-slate-900">{email || 'unknown'}</strong>.
          Click a report to see its full detail, its analysis and the delete option.
        </p>
      </header>

      {/* Search + filters - every value is sent to the backend */}
      <form
        className="bg-white rounded-xl border border-slate-200 shadow-sm p-4 flex flex-wrap items-end gap-3"
        role="search"
        aria-label="Search my complaints"
        onSubmit={(event) => {
          event.preventDefault();
          setQ(qInput.trim());
        }}
      >
        <label className="flex flex-col gap-1 flex-1 min-w-[220px]" htmlFor="mine-search">
          <span className="text-xs font-bold uppercase tracking-wider text-slate-500">Search</span>
          <div className="relative">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              id="mine-search"
              type="search"
              value={qInput}
              onChange={(event) => setQInput(event.target.value)}
              placeholder="Search description or location..."
              className="w-full pl-9 pr-3 py-2 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
            />
          </div>
        </label>

        <label className="flex flex-col gap-1" htmlFor="mine-status">
          <span className="text-xs font-bold uppercase tracking-wider text-slate-500">Status</span>
          <select
            id="mine-status"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
            className="border border-slate-300 rounded-lg text-sm px-3 py-2 bg-white focus:ring-2 focus:ring-indigo-500"
          >
            <option value="">All statuses</option>
            {STATUSES.map((value) => (
              <option key={value} value={value}>{value}</option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1" htmlFor="mine-sort">
          <span className="text-xs font-bold uppercase tracking-wider text-slate-500">Sort</span>
          <select
            id="mine-sort"
            value={sort}
            onChange={(event) => setSort(event.target.value)}
            className="border border-slate-300 rounded-lg text-sm px-3 py-2 bg-white focus:ring-2 focus:ring-indigo-500"
          >
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
          </select>
        </label>

        <button type="submit" className="btn-gradient px-4 py-2 rounded-lg text-sm font-semibold">
          Search
        </button>

        {filtersActive ? (
          <button
            type="button"
            onClick={clearFilters}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold text-slate-600 border border-slate-300 hover:bg-slate-50"
          >
            <X className="w-4 h-4" /> Clear
          </button>
        ) : null}
      </form>
      <ErrorBanner
        title="Your complaints could not be loaded"
        message={error}
        onRetry={load}
      />

      <section className="flex flex-col gap-4" aria-label="My complaints" aria-busy={loading}>
        {loading ? <SkeletonRows count={3} /> : null}

        {!loading && !error && items.length === 0 ? (
          filtersActive ? (
            <EmptyState
              title="No complaints match your search"
              body="Try a different keyword or clear the filters to see all of your reports."
              action={
                <button
                  type="button"
                  onClick={clearFilters}
                  className="btn-gradient inline-flex px-5 py-2.5 font-medium rounded-xl mt-2"
                >
                  Clear filters
                </button>
              }
            />
          ) : (
            <EmptyState
              title="You have not reported anything yet"
              body="When you do, it will appear here with its current status."
              action={
                <a className="btn-gradient inline-flex px-5 py-2.5 font-medium rounded-xl mt-2" href="#/submit">
                  Report a problem
                </a>
              }
            />
          )
        ) : null}

        {!loading && items.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {items.map((complaint, index) => (
              <a
                href={`#/complaint/${complaint.id}`}
                key={complaint.id}
                aria-label={`Open complaint ${(complaint.id || '').slice(0, 8).toUpperCase()}`}
                className="bg-white rounded-xl border border-slate-200 shadow-sm card-lift overflow-hidden flex gap-4 p-5 animate-fade-up hover:border-indigo-300 hover:shadow-md transition-all"
                style={{ animationDelay: `${Math.min(index, 8) * 60}ms` }}
              >
                {complaint.image_url ? (
                  <div className="w-16 h-16 rounded-lg overflow-hidden bg-slate-50 border border-slate-100 shrink-0">
                    <img src={imageUrl(complaint.image_url)} alt="" className="w-full h-full object-cover" loading="lazy" />
                  </div>
                ) : (
                  <div className="w-16 h-16 rounded-lg bg-slate-50 border border-slate-100 shrink-0 flex items-center justify-center text-slate-300">
                    <ImageIcon className="w-6 h-6" />
                  </div>
                )}

                <div className="flex-1 min-w-0 flex flex-col gap-2">
                  <div className="flex items-start justify-between gap-3">
                    <h3 className="font-mono font-bold text-slate-800 text-sm m-0 truncate">
                      #{(complaint.id || '').slice(0, 8).toUpperCase()}
                    </h3>
                    <StatusBadge status={complaint.status} />
                  </div>

                  <p className="text-sm text-slate-700 leading-snug m-0 line-clamp-2">
                    {complaint.description}
                  </p>

                  <p className="text-xs text-slate-500 font-medium flex items-center gap-1.5 m-0">
                    <MapPin className="w-3.5 h-3.5 text-indigo-400 shrink-0" />
                    <span className="truncate">{complaint.location}</span>
                    <span className="text-slate-300">•</span>
                    <Calendar className="w-3.5 h-3.5 shrink-0" />
                    {complaint.created_at
                      ? new Date(complaint.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
                      : 'Unknown'}
                  </p>

                  <div className="flex items-center justify-between text-xs pt-2 mt-auto border-t border-slate-100">
                    <span className="flex items-center gap-3">
                      <span className="flex items-center gap-1 text-slate-500 font-medium">
                        <BarChart2 className="w-3.5 h-3.5 text-indigo-400" />
                        {complaint.priority_band || (
                          <span className="italic text-slate-400">Not yet rated</span>
                        )}
                      </span>
                      {hasAIFound(complaint) ? (
                        <span className="flex items-center gap-1 text-emerald-600 font-medium">
                          <CheckCircle className="w-3.5 h-3.5" /> Analysed
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-slate-400 font-medium">
                          <Clock className="w-3.5 h-3.5" /> Not started
                        </span>
                      )}
                    </span>
                    <span className="inline-flex items-center gap-1 font-semibold text-indigo-600">
                      View details <ChevronRight className="w-4 h-4" />
                    </span>
                  </div>
                </div>
              </a>
            ))}
          </div>
        ) : null}
      </section>

      <Notice tone="info">
        <p className="text-sm leading-relaxed">
          Your report shows only a coarse priority band (Low, Medium, High or
          Critical) once campus operations rate it. The numeric score, its
          breakdown and any AI findings stay internal to administrators. Your
          report is saved even if analysis is unavailable.
        </p>
      </Notice>
    </div>
  );
}