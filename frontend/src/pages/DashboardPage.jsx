import { useCallback, useEffect, useRef, useState } from 'react';
import {
  BarChart3,
  Calendar as CalendarIcon,
  ChevronLeft, ChevronRight, Download, MapPin,
  Search, ShieldAlert, X,
} from 'lucide-react';

import {
  addInvestigationNote,
  approveForPublic,
  confirmAnalysis,
  deleteMyComplaint,
  fetchSummary,
  getAdminComplaint,
  imageUrl,
  listAllComplaints,
  listComplaintEvents,
  listInvestigationNotes,
  updateStatus,
} from '../api.js';
import { useAuth } from '../auth.jsx';
import { PriorityBadge, ScoreMeter, UnscoredNote } from '../components/Priority.jsx';
import { StatusBadge, StatusSelect } from '../components/Status.jsx';
import { ErrorBanner, Notice, SkeletonRows } from '../components/ui.jsx';
import { BAND_ORDER, LEVELS, LIMIT_OPTIONS, SORTS, STATUSES } from '../constants.js';

const BAND_OPTIONS = ['', ...BAND_ORDER, 'Unscored'];

function fmtDateTime(value) {
  if (!value) return null;
  return new Date(value).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

function fmtDate(value) {
  if (!value) return 'Unknown';
  return new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function shortId(id) {
  return `#CL-${String(id || '').slice(0, 8).toUpperCase()}`;
}

/**
 * Admin portal, two views of the same page component:
 *
 *   view="overview" (#/dashboard) - KPI cards + distribution panels from
 *     GET /api/admin/analytics/summary and a "Latest complaints" queue that
 *     asks the backend for the newest rows only (sort=newest, no filters).
 *
 *   view="triage" (#/triage) - the full Issue Triage workspace: every
 *     complaint via GET /api/admin/complaints with band/category/q/open/
 *     status/sort/limit/offset (the server filters - the row set is never
 *     faked), pagination and CSV export.
 *
 * Both views open the same detail drawer: GET /api/admin/complaints/{id}
 * plus the events and notes endpoints, with live status / score / publish /
 * note / delete actions.
 *
 * Pagination asks for `pageSize + 1` rows: the extra row only signals "there
 * is a next page" and is never rendered, because the list endpoint is a
 * plain array with no total count.
 */
export default function DashboardPage({ view = 'overview', initialQuery = '' }) {
  const { token } = useAuth();
  const isTriage = view === 'triage';

  const [items, setItems] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState(null);
  const [hasMore, setHasMore] = useState(false);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState(null);

  // Filters - all of these are sent to the backend.
  const [qInput, setQInput] = useState('');
  const [q, setQ] = useState('');
  const [band, setBand] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [category, setCategory] = useState('');
  const [openOnly, setOpenOnly] = useState(false);
  const [sort, setSort] = useState('priority');
  const [limit, setLimit] = useState(20);

  // The overview queue shows a fixed slice of the newest complaints; the
  // triage workspace pages through everything with the chosen page size.
  const pageSize = isTriage ? limit : 3;

  const requestRef = useRef(0);

  // Debounce the search box into the `q` that actually drives the request.
  useEffect(() => {
    const timer = setTimeout(() => setQ(qInput.trim()), 300);
    return () => clearTimeout(timer);
  }, [qInput]);

  // The global top-bar search hands its query over via the hash
  // (#/triage?q=...). Re-sync whenever the route hands us a new query or the
  // view changes, so Overview <-> Triage never leaves a stale filter behind.
  useEffect(() => {
    setQInput(initialQuery);
    setQ(initialQuery);
    setPage(1);
  }, [initialQuery, view]);

  // Any filter change invalidates the current page number.
  useEffect(() => {
    setPage(1);
  }, [q, band, statusFilter, category, openOnly, sort, limit, token]);
  const loadData = useCallback(async () => {
    if (!token) return;
    const id = requestRef.current + 1;
    requestRef.current = id;
    setLoading(true);
    setListError(null);
    try {
      // The overview queue deliberately ignores the triage filters: it only
      // ever shows the LATEST complaints. Everything else lives on #/triage.
      const params = isTriage
        ? {
            sort,
            limit: pageSize + 1,
            offset: (page - 1) * pageSize,
            band: band || undefined,
            status: statusFilter || undefined,
            category: category || undefined,
            q: q || undefined,
            open: openOnly ? true : undefined,
          }
        : { sort: 'newest', limit: pageSize + 1 };
      const rows = await listAllComplaints(params, token);
      if (requestRef.current !== id) return;
      const list = Array.isArray(rows) ? rows : [];
      setHasMore(list.length > pageSize);
      setItems(list.slice(0, pageSize));
    } catch (caught) {
      if (requestRef.current !== id) return;
      setItems([]);
      setHasMore(false);
      setListError(caught.message);
    } finally {
      if (requestRef.current === id) setLoading(false);
    }
  }, [token, sort, pageSize, band, statusFilter, category, q, openOnly, page, isTriage]);

  const loadSummary = useCallback(async () => {
    if (!token) return;
    try {
      const data = await fetchSummary(token);
      if (data && typeof data.total === 'number') {
        setSummary(data);
        return;
      }
    } catch {
      // Fall through to calculation directly from complaints
    }

    try {
      const allRows = await listAllComplaints({ limit: 1000 }, token);
      if (Array.isArray(allRows)) {
        const by_status = { 'Reported': 0, 'In Progress': 0, 'Resolved': 0 };
        const by_band = { 'Critical': 0, 'High': 0, 'Medium': 0, 'Low': 0 };
        let unscored = 0;
        let unresolved = 0;

        for (const row of allRows) {
          const st = row.status || 'Reported';
          by_status[st] = (by_status[st] || 0) + 1;
          if (st !== 'Resolved') {
            unresolved += 1;
          }

          const score = row.priority_score;
          if (score === null || score === undefined) {
            unscored += 1;
          } else {
            const num = Number(score);
            let b = row.band;
            if (!b) {
              if (num <= 29) b = 'Low';
              else if (num <= 54) b = 'Medium';
              else if (num <= 74) b = 'High';
              else b = 'Critical';
            }
            if (by_band[b] !== undefined) {
              by_band[b] += 1;
            } else {
              unscored += 1;
            }
          }
        }

        setSummary({
          total: allRows.length,
          by_status,
          by_band,
          unscored,
          unresolved,
        });
      }
    } catch {
      setSummary((prev) => prev || {
        total: 0,
        by_status: { 'Reported': 0, 'In Progress': 0, 'Resolved': 0 },
        by_band: { 'Critical': 0, 'High': 0, 'Medium': 0, 'Low': 0 },
        unscored: 0,
        unresolved: 0,
      });
    }
  }, [token]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  /** After a drawer action: refresh the open row, the table and the KPIs. */
  async function refreshEverything() {
    if (selected) {
      try {
        const fresh = await getAdminComplaint(selected.id, token);
        setSelected(fresh);
      } catch {
        // Keep showing the previous snapshot; the table refresh still runs.
      }
    }
    loadData();
    loadSummary();
  }

  function handleDeleted() {
    setSelected(null);
    loadData();
    loadSummary();
  }

  function resetFilters() {
    setQInput('');
    setQ('');
    setBand('');
    setStatusFilter('');
    setCategory('');
    setOpenOnly(false);
  }

  const filtersActive = Boolean(q || band || statusFilter || category || openOnly);

  // Category suggestions for the exact-match filter: whatever categories the
  // currently loaded rows actually carry (the backend has no fixed enum).
  const categoryOptions = [...new Set(items.map((row) => row.ai_category).filter(Boolean))];

  function exportCSV() {
    const headers = 'ID,Description,Location,Category,Band,Score,Status,Created\n';
    const rows = items.map((r) =>
      [
        `"${r.id}"`,
        `"${String(r.description || '').replace(/"/g, '""')}"`,
        `"${r.location || ''}"`,
        `"${r.ai_category || ''}"`,
        `"${r.band || ''}"`,
        r.priority_score ?? '',
        `"${r.status}"`,
        `"${r.created_at || ''}"`,
      ].join(','),
    ).join('\n');
    const blob = new Blob([headers + rows], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `IITK_Campus_Complaints_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <div className="flex flex-col gap-6 max-w-7xl mx-auto w-full">
      {/* 1. OPERATIONS HEADER */}
      <div className="relative rounded-2xl overflow-hidden bg-slate-900 text-white p-6 sm:p-7 shadow-sm border border-slate-200">
        <div
          className="absolute inset-0 bg-cover bg-center opacity-35"
          style={{ backgroundImage: `url('/iitk_authentic_campus.jpg')` }}
        />
        <div className="absolute inset-0 bg-gradient-to-r from-slate-950/95 via-slate-900/80 to-indigo-950/60" />
        <div className="relative z-10 flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-indigo-500/30 text-indigo-200 border border-indigo-400/30 text-xs font-semibold mb-2 backdrop-blur-sm">
              <ShieldAlert className="w-3.5 h-3.5" />
              <span>Campus Operations Command</span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight">
              {isTriage ? 'Issue Triage' : 'Operations Dashboard'}
            </h1>
            <p className="text-sm text-slate-300 mt-1">
              {isTriage
                ? 'Every complaint in one queue - search, filter, score, update and resolve.'
                : 'Manage, track, and resolve IIT Kanpur campus issues efficiently.'}
            </p>
          </div>
          <div className="flex items-center gap-2.5 bg-black/40 backdrop-blur-md px-3.5 py-2 rounded-xl border border-white/15 text-xs text-white">
            <img src="/iitk-logo.svg" alt="IITK Seal" className="w-6 h-6 object-contain" />
            <div className="flex flex-col">
              <span className="font-bold leading-tight">IIT Kanpur Operations</span>
              <span className="text-[10px] text-slate-300">Live triage feed</span>
            </div>
          </div>
        </div>
      </div>

      {listError ? (
        <ErrorBanner
          title="Could not sync live complaints"
          message={listError}
          onRetry={loadData}
        />
      ) : null}

      {/* 2. KPI CARDS - every value comes from /api/admin/analytics/summary
          (overview only - the triage page is a focused workspace) */}
      {!isTriage ? (
      <div id="analytics-section" className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 scroll-mt-20" aria-busy={!summary}>
        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex flex-col justify-between">
          <span className="text-xs font-semibold text-slate-500">Total complaints</span>
          <span className="text-3xl font-extrabold font-mono text-slate-900 my-2">
            {summary ? summary.total : 0}
          </span>
          <span className="text-xs text-slate-500 font-medium">All reports in the system</span>
        </div>

        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex flex-col justify-between">
          <span className="text-xs font-semibold text-slate-500">Open reports</span>
          <span className="text-3xl font-extrabold font-mono text-blue-700 my-2">
            {summary ? summary.unresolved : 0}
          </span>
          <span className="text-xs text-slate-500 font-medium">Not yet Resolved</span>
        </div>

        <div className="bg-gradient-to-br from-orange-50/90 to-amber-50/60 p-5 rounded-2xl border border-orange-200 shadow-sm flex flex-col justify-between">
          <span className="text-xs font-bold text-orange-900">Critical band</span>
          <span className="text-3xl font-extrabold font-mono text-orange-700 my-2">
            {summary?.by_band?.Critical ?? 0}
          </span>
          <span className="inline-block w-fit text-[11px] font-bold text-orange-800 bg-orange-100/90 px-2.5 py-1 rounded-full border border-orange-200">
            Priority 75-100
          </span>
        </div>

        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex flex-col justify-between">
          <span className="text-xs font-semibold text-slate-500">Unscored</span>
          <span className="text-3xl font-extrabold font-mono text-slate-900 my-2">
            {summary ? summary.unscored : 0}
          </span>
          <span className="text-xs text-slate-500 font-medium">Awaiting score confirmation</span>
        </div>
      </div>
      ) : null}

      {/* 3. FILTER BAR - every control maps to a backend query parameter
          (triage page only) */}
      {isTriage ? (
      <form
        className="bg-white rounded-2xl border border-slate-200 shadow-sm p-4 flex flex-wrap items-end gap-3"
        role="search"
        aria-label="Filter complaints"
        onSubmit={(event) => {
          event.preventDefault();
          setQ(qInput.trim());
        }}
      >
        <label className="flex flex-col gap-1 flex-1 min-w-[240px]" htmlFor="dash-search">
          <span className="text-xs font-bold uppercase tracking-wider text-slate-500">Search</span>
          <div className="relative">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              id="dash-search"
              type="search"
              value={qInput}
              onChange={(event) => setQInput(event.target.value)}
              placeholder="Search description, location or id..."
              className="w-full pl-9 pr-3 py-2 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
            />
          </div>
        </label>

        <label className="flex flex-col gap-1" htmlFor="dash-band">
          <span className="text-xs font-bold uppercase tracking-wider text-slate-500">Band</span>
          <select
            id="dash-band"
            value={band}
            onChange={(event) => setBand(event.target.value)}
            className="border border-slate-300 rounded-lg text-sm px-3 py-2 bg-white"
          >
            <option value="">All bands</option>
            {BAND_OPTIONS.slice(1).map((value) => (
              <option key={value} value={value}>{value}</option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1" htmlFor="dash-status">
          <span className="text-xs font-bold uppercase tracking-wider text-slate-500">Status</span>
          <select
            id="dash-status"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
            className="border border-slate-300 rounded-lg text-sm px-3 py-2 bg-white"
          >
            <option value="">All statuses</option>
            {STATUSES.map((value) => (
              <option key={value} value={value}>{value}</option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1" htmlFor="dash-category">
          <span className="text-xs font-bold uppercase tracking-wider text-slate-500">Category</span>
          <input
            id="dash-category"
            type="text"
            list="dash-category-options"
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            placeholder="Exact category"
            className="border border-slate-300 rounded-lg text-sm px-3 py-2 bg-white w-36"
          />
          <datalist id="dash-category-options">
            {categoryOptions.map((value) => (
              <option key={value} value={value} />
            ))}
          </datalist>
        </label>

        <label className="flex items-center gap-2 py-2 text-sm font-medium text-slate-700" htmlFor="dash-open">
          <input
            id="dash-open"
            type="checkbox"
            checked={openOnly}
            onChange={(event) => setOpenOnly(event.target.checked)}
            className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
          />
          Open only
        </label>

        <label className="flex flex-col gap-1" htmlFor="dash-sort">
          <span className="text-xs font-bold uppercase tracking-wider text-slate-500">Sort</span>
          <select
            id="dash-sort"
            value={sort}
            onChange={(event) => setSort(event.target.value)}
            className="border border-slate-300 rounded-lg text-sm px-3 py-2 bg-white"
          >
            {SORTS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1" htmlFor="dash-limit">
          <span className="text-xs font-bold uppercase tracking-wider text-slate-500">Per page</span>
          <select
            id="dash-limit"
            value={limit}
            onChange={(event) => setLimit(Number(event.target.value))}
            className="border border-slate-300 rounded-lg text-sm px-3 py-2 bg-white"
          >
            {LIMIT_OPTIONS.map((value) => (
              <option key={value} value={value}>{value}</option>
            ))}
          </select>
        </label>

        <button type="submit" className="btn-gradient px-4 py-2 rounded-lg text-sm font-semibold">
          Search
        </button>
        {filtersActive ? (
          <button
            type="button"
            onClick={resetFilters}
            className="px-3 py-2 rounded-lg text-sm font-semibold text-slate-600 border border-slate-300 hover:bg-slate-50"
          >
            Clear filters
          </button>
        ) : null}
      </form>
      ) : null}

      {/* 4. WORKSPACE: summary panels (overview) + complaint table (both) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {!isTriage ? (
        <div className="lg:col-span-3 flex flex-col gap-5">
          <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm">
            <h3 className="text-sm font-bold text-slate-900 mb-4">Priority distribution</h3>
            {summary ? (
              <div className="flex flex-col gap-3">
                {[...BAND_ORDER, 'Unscored'].map((name) => {
                  const count = name === 'Unscored' ? (summary.unscored ?? 0) : (summary.by_band?.[name] ?? 0);
                  const pct = Math.round((count / Math.max(1, summary.total ?? 1)) * 100);
                  const color = {
                    Critical: 'bg-rose-500', High: 'bg-orange-500', Medium: 'bg-amber-500',
                    Low: 'bg-emerald-500', Unscored: 'bg-slate-400',
                  }[name];
                  return (
                    <div key={name} className="flex flex-col gap-1">
                      <div className="flex justify-between text-xs font-semibold text-slate-600">
                        <span>{name}</span>
                        <span className="font-mono">{count}</span>
                      </div>
                      <div className="h-2 rounded-full bg-slate-100 overflow-hidden">
                        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <SkeletonRows count={5} />
            )}
          </div>

          <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm">
            <h3 className="text-sm font-bold text-slate-900 mb-3">Status breakdown</h3>
            {summary ? (
              <div className="flex flex-col gap-2.5">
                {STATUSES.map((name) => (
                  <div key={name} className="flex items-center justify-between gap-2">
                    <StatusBadge status={name} />
                    <span className="font-mono font-bold text-slate-700 text-sm">
                      {summary.by_status?.[name] ?? 0}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <SkeletonRows count={3} />
            )}
          </div>
        </div>
        ) : null}

        <div className={isTriage ? 'lg:col-span-12 flex flex-col' : 'lg:col-span-9 flex flex-col'}>
          {/* Triage table - rows straight from GET /api/admin/complaints */}
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-200 flex items-center justify-between gap-3 flex-wrap">
              <div>
                <h2 className="text-sm font-bold text-slate-900 m-0">
                  {isTriage ? 'Triage queue' : 'Recent complaints'}
                </h2>
                <p className="text-xs text-slate-500 m-0 mt-0.5">
                  {isTriage
                    ? 'Click a row to open the full detail drawer with analysis, actions, events and notes.'
                    : 'Showing the 3 newest reports - click a row to open it. All complaints and filters live in Issue Triage.'}
                </p>
              </div>
              {isTriage ? (
                <button
                  type="button"
                  onClick={exportCSV}
                  disabled={items.length === 0}
                  className="py-1.5 px-3.5 rounded-xl text-xs font-semibold text-slate-700 bg-white border border-slate-300 hover:bg-slate-100 flex items-center gap-1.5 shadow-sm transition-colors disabled:opacity-50"
                >
                  <Download className="w-3.5 h-3.5 text-slate-500" />
                  <span>Export CSV</span>
                </button>
              ) : (
                <a
                  href="#/triage"
                  className="py-1.5 px-3.5 rounded-xl text-xs font-semibold text-indigo-700 bg-indigo-50 border border-indigo-200 hover:bg-indigo-100 flex items-center gap-1.5 shadow-sm transition-colors"
                >
                  <span>All complaints</span>
                  <ChevronRight className="w-3.5 h-3.5" />
                </a>
              )}
            </div>

            {loading ? <SkeletonRows count={isTriage ? 5 : 3} /> : null}

            {!loading && items.length === 0 ? (
              <div className="p-8 text-center flex flex-col items-center gap-2">
                <p className="font-bold text-slate-800 m-0">
                  {filtersActive ? 'No complaints match the current filters.' : 'No complaints yet.'}
                </p>
                <p className="text-sm text-slate-500 m-0">
                  {filtersActive
                    ? 'Clear the filters to see the whole queue.'
                    : 'New reports appear here as soon as students submit them.'}
                </p>
                {filtersActive ? (
                  <button
                    type="button"
                    onClick={resetFilters}
                    className="btn-gradient px-4 py-2 rounded-lg text-sm font-semibold mt-2"
                  >
                    Clear filters
                  </button>
                ) : null}
              </div>
            ) : null}

            {!loading && items.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead>
                    <tr className="border-b border-slate-200 bg-slate-50 text-[11px] font-bold uppercase tracking-wider text-slate-500">
                      <th className="py-3 px-5">Complaint</th>
                      <th className="py-3 px-4">Priority</th>
                      <th className="py-3 px-4">Status</th>
                      <th className="py-3 px-4">Created</th>
                      <th className="py-3 px-5 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 text-sm">
                    {items.map((complaint) => (
                      <tr
                        key={complaint.id}
                        onClick={() => setSelected(complaint)}
                        className="hover:bg-slate-50/70 transition-colors cursor-pointer"
                      >
                        <td className="py-4 px-5">
                          <div className="flex flex-col gap-1 max-w-xs sm:max-w-sm">
                            <span className="font-mono text-xs font-bold text-slate-900">
                              {shortId(complaint.id)}
                            </span>
                            <p className="font-semibold text-slate-900 leading-snug line-clamp-2 m-0">
                              {complaint.description}
                            </p>
                            <span className="text-xs text-slate-500 flex items-center gap-1 mt-0.5">
                              <MapPin className="w-3 h-3 text-indigo-500 shrink-0" />
                              {complaint.location}
                            </span>
                          </div>
                        </td>
                        <td className="py-4 px-4 align-top">
                          <div className="flex flex-col gap-1 items-start">
                            <PriorityBadge band={complaint.band} score={complaint.priority_score} />
                            <span className="text-[11px] text-slate-500 font-medium">
                              {complaint.ai_category || 'Uncategorised'}
                            </span>
                          </div>
                        </td>
                        <td className="py-4 px-4 align-top">
                          <StatusBadge status={complaint.status} />
                        </td>
                        <td className="py-4 px-4 align-top text-xs text-slate-500 whitespace-nowrap">
                          {fmtDate(complaint.created_at)}
                        </td>
                        <td className="py-4 px-5 align-top text-right">
                          <button
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation();
                              setSelected(complaint);
                            }}
                            className="py-1.5 px-3 rounded-lg text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-700 transition-colors shadow-sm whitespace-nowrap"
                          >
                            Open
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
            {/* Real pagination (triage only): limit+1 probe, no fake page counts */}
            {isTriage ? (
            <div className="px-5 py-3 border-t border-slate-200 bg-slate-50/50 flex items-center justify-between gap-3">
              <span className="text-xs font-medium text-slate-600">
                Page {page}
                {hasMore ? ' · more available' : ' · last page'}
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setPage((value) => Math.max(1, value - 1))}
                  disabled={page === 1 || loading}
                  aria-label="Previous page"
                  className="p-1.5 rounded border border-slate-300 hover:bg-white text-slate-600 disabled:opacity-40"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                <button
                  type="button"
                  onClick={() => setPage((value) => value + 1)}
                  disabled={!hasMore || loading}
                  aria-label="Next page"
                  className="p-1.5 rounded border border-slate-300 hover:bg-white text-slate-600 disabled:opacity-40"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </div>
            ) : null}
          </div>
        </div>
      </div>

      {/* 5. FULL-SCREEN DETAIL DRAWER */}
      {selected ? (
        <DetailDrawer
          key={selected.id}
          complaint={selected}
          token={token}
          onClose={() => setSelected(null)}
          onRefresh={refreshEverything}
          onDeleted={handleDeleted}
        />
      ) : null}
    </div>
  );
}

/**
 * Full-screen drawer for ONE complaint.
 *
 * Everything here is live backend functionality:
 *   - status change      -> PATCH /api/admin/complaints/{id}/status
 *   - score confirmation -> PATCH /api/admin/complaints/{id}/analysis
 *   - publish            -> POST  /api/admin/complaints/{id}/public-approval
 *   - delete             -> DELETE /api/complaints/{id} (admins may delete any)
 *   - audit trail        -> GET   /api/admin/complaints/{id}/events
 *   - investigation notes-> GET/POST /api/admin/complaints/{id}/notes
 *
 * The score form is PREFILLED from the admin-confirmed values, falling back to
 * the AI suggestion - but nothing is scored until this form is submitted.
 */
function DetailDrawer({ complaint, token, onClose, onRefresh, onDeleted }) {
  const [events, setEvents] = useState([]);
  const [notes, setNotes] = useState([]);
  const [timelineError, setTimelineError] = useState(null);
  const [busy, setBusy] = useState(null); // 'status' | 'score' | 'publish' | 'note' | 'delete'
  const [feedback, setFeedback] = useState(null); // { text, tone: 'ok' | 'error' }

  const [statusValue, setStatusValue] = useState(
    STATUSES.includes(complaint.status) ? complaint.status : STATUSES[0],
  );
  const [scoreInputs, setScoreInputs] = useState({
    confirmed_urgency: complaint.confirmed_urgency || complaint.ai_urgency || 'Medium',
    confirmed_impact: complaint.confirmed_impact || complaint.ai_impact || 'Medium',
    confirmed_safety: complaint.confirmed_safety || complaint.ai_safety || 'Low',
  });

  const [pubOpen, setPubOpen] = useState(false);
  const [pubSummary, setPubSummary] = useState('');
  const [pubCategory, setPubCategory] = useState(complaint.ai_category || 'General');
  const [pubLocation, setPubLocation] = useState(complaint.location || '');

  const [noteDraft, setNoteDraft] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(false);

  const loadTimeline = useCallback(async () => {
    setTimelineError(null);
    const [eventsResult, notesResult] = await Promise.allSettled([
      listComplaintEvents(complaint.id, token),
      listInvestigationNotes(complaint.id, token),
    ]);
    setEvents(
      eventsResult.status === 'fulfilled' && Array.isArray(eventsResult.value)
        ? eventsResult.value
        : [],
    );
    setNotes(
      notesResult.status === 'fulfilled' && Array.isArray(notesResult.value)
        ? notesResult.value
        : [],
    );
    if (eventsResult.status === 'rejected' || notesResult.status === 'rejected') {
      setTimelineError('The audit trail or the notes could not be loaded.');
    }
  }, [complaint.id, token]);

  useEffect(() => {
    loadTimeline();
  }, [loadTimeline]);

  /** Run one drawer action: busy state -> API -> refresh row/list/timeline. */
  async function run(section, action, successText) {
    setBusy(section);
    setFeedback(null);
    try {
      await action();
      setFeedback({ text: successText, tone: 'ok' });
      await onRefresh();
      await loadTimeline();
    } catch (caught) {
      setFeedback({ text: caught.message, tone: 'error' });
    } finally {
      setBusy(null);
    }
  }

  function saveStatus() {
    return run('status', () => updateStatus(complaint.id, statusValue, token), `Status set to "${statusValue}".`);
  }

  function saveScore() {
    return run('score', () => confirmAnalysis(complaint.id, scoreInputs, token), 'Priority score confirmed and recomputed.');
  }

  function publish() {
    if (pubSummary.trim().length < 10) {
      setFeedback({ text: 'The public summary must be at least 10 characters.', tone: 'error' });
      return undefined;
    }
    return run(
      'publish',
      () => approveForPublic(
        complaint.id,
        {
          public_summary: pubSummary.trim(),
          public_category: pubCategory.trim() || 'General',
          public_location: pubLocation.trim() || complaint.location,
        },
        token,
      ),
      'Published to the community feed.',
    );
  }

  function addNote() {
    if (noteDraft.trim().length < 2) return undefined;
    const draft = noteDraft.trim();
    return run('note', async () => {
      await addInvestigationNote(complaint.id, draft, token);
      setNoteDraft('');
    }, 'Investigation note added.');
  }

  async function removeComplaint() {
    setBusy('delete');
    setFeedback(null);
    try {
      await deleteMyComplaint(complaint.id, token);
      onDeleted();
    } catch (caught) {
      setFeedback({ text: caught.message, tone: 'error' });
      setBusy(null);
    }
  }
  const breakdown = complaint.score_breakdown || null;
  const breakdownRows = breakdown
    ? ['urgency', 'impact', 'recurrence', 'age', 'safety']
        .filter((key) => breakdown[key] && typeof breakdown[key] === 'object')
        .map((key) => ({
          key,
          label: key.charAt(0).toUpperCase() + key.slice(1),
          detail: breakdown[key].level
            ?? (breakdown[key].count != null ? `x${breakdown[key].count}`
              : breakdown[key].days != null ? `${breakdown[key].days}d` : ''),
          points: breakdown[key].points,
          max: breakdown[key].max,
        }))
    : [];

  return (
    <div
      className="fixed inset-0 z-50 flex"
      role="dialog"
      aria-modal="true"
      aria-label={`Complaint ${shortId(complaint.id)} details`}
    >
      <div
        className="absolute inset-0 bg-slate-900/60 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      <div className="relative ml-auto w-full max-w-3xl h-full bg-slate-50 overflow-y-auto shadow-2xl">
        {/* Sticky header */}
        <div className="sticky top-0 z-10 bg-white/95 backdrop-blur border-b border-slate-200 px-6 py-4 flex items-center justify-between gap-3">
          <div className="flex items-center gap-3 flex-wrap min-w-0">
            <h2 className="font-mono font-extrabold text-lg text-slate-900 m-0 shrink-0">
              {shortId(complaint.id)}
            </h2>
            <StatusBadge status={complaint.status} />
            <PriorityBadge band={complaint.band} score={complaint.priority_score} />
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close detail drawer"
            className="p-2 rounded-lg text-slate-500 hover:text-slate-800 hover:bg-slate-100 shrink-0"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 flex flex-col gap-5">
          {/* Action feedback */}
          {feedback ? (
            <div
              role="status"
              className={`rounded-xl px-4 py-3 text-sm font-semibold border ${
                feedback.tone === 'error'
                  ? 'bg-red-50 border-red-200 text-red-700'
                  : 'bg-emerald-50 border-emerald-200 text-emerald-700'
              }`}
            >
              {feedback.text}
            </div>
          ) : null}

          {/* Report */}
          <section className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            {complaint.image_url ? (
              <a
                href={imageUrl(complaint.image_url)}
                target="_blank"
                rel="noopener noreferrer"
                className="block relative group overflow-hidden bg-slate-100"
                title="View full-resolution photo in a new tab"
              >
                <img
                  src={imageUrl(complaint.image_url)}
                  alt={`Photo uploaded with complaint ${complaint.id}`}
                  className="w-full h-56 object-cover transition-transform duration-200 group-hover:scale-[1.02]"
                  loading="lazy"
                />
              </a>
            ) : null}
            <div className="p-5 flex flex-col gap-3">
              <p className="text-sm text-slate-800 leading-relaxed m-0 whitespace-pre-wrap">
                {complaint.description}
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 text-xs border-t border-slate-100 pt-3">
                <span className="flex items-center gap-1.5 text-slate-500 py-1">
                  <MapPin className="w-3.5 h-3.5 text-indigo-400" />
                  <strong className="text-slate-700 font-semibold">Location:</strong> {complaint.location}
                </span>
                <span className="flex items-center gap-1.5 text-slate-500 py-1">
                  <CalendarIcon className="w-3.5 h-3.5" />
                  <strong className="text-slate-700 font-semibold">Created:</strong> {fmtDateTime(complaint.created_at) || 'Unknown'}
                </span>
                <span className="flex items-center gap-1.5 text-slate-500 py-1">
                  <BarChart3 className="w-3.5 h-3.5" />
                  <strong className="text-slate-700 font-semibold">Category:</strong> {complaint.ai_category || 'Uncategorised'}
                </span>
                {complaint.resolved_at ? (
                  <span className="flex items-center gap-1.5 text-slate-500 py-1">
                    <span>✓</span>
                    <strong className="text-slate-700 font-semibold">Resolved:</strong> {fmtDateTime(complaint.resolved_at)}
                  </span>
                ) : null}
              </div>
            </div>
          </section>
          {/* Priority score + breakdown (admin-only numbers) */}
          <section className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
            <h3 className="text-sm font-bold uppercase tracking-wider text-slate-500 m-0 mb-3">
              Priority score
            </h3>
            <ScoreMeter band={complaint.band} score={complaint.priority_score} />
            {complaint.priority_score == null ? (
              <UnscoredNote />
            ) : breakdownRows.length > 0 ? (
              <div className="mt-4">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-slate-400 font-bold uppercase tracking-wider">
                      <th className="py-1.5">Factor</th>
                      <th className="py-1.5">Input</th>
                      <th className="py-1.5 text-right">Points</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {breakdownRows.map((row) => (
                      <tr key={row.key}>
                        <td className="py-1.5 font-semibold text-slate-700">{row.label}</td>
                        <td className="py-1.5 text-slate-500">{row.detail}</td>
                        <td className="py-1.5 text-right font-mono font-bold text-slate-800">
                          {Number(row.points).toFixed(1)} / {row.max}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {breakdown.safety_floor_applied ? (
                  <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mt-3 m-0">
                    Safety floor applied: High safety kept the band at{' '}
                    <strong>{complaint.band}</strong> (raw band {breakdown.band_raw}). The numeric
                    score was not altered.
                  </p>
                ) : null}
              </div>
            ) : null}
          </section>

          {/* AI analysis */}
          <section className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
            <h3 className="text-sm font-bold uppercase tracking-wider text-slate-500 m-0 mb-3">
              AI analysis
            </h3>
            {complaint.ai_summary || complaint.ai_category ? (
              <div className="flex flex-col gap-2.5 text-sm">
                {complaint.ai_category ? (
                  <div className="flex justify-between gap-3">
                    <span className="text-slate-500 font-medium">Category</span>
                    <span className="font-semibold text-slate-800 text-right">{complaint.ai_category}</span>
                  </div>
                ) : null}
                {complaint.ai_summary ? (
                  <div>
                    <span className="text-slate-500 font-medium block mb-0.5">Summary</span>
                    <p className="text-slate-700 m-0 leading-relaxed">{complaint.ai_summary}</p>
                  </div>
                ) : null}
                {complaint.ai_evidence ? (
                  <div>
                    <span className="text-slate-500 font-medium block mb-0.5">Evidence</span>
                    <p className="text-slate-700 m-0 leading-relaxed">{complaint.ai_evidence}</p>
                  </div>
                ) : null}
                <div className="flex justify-between gap-3">
                  <span className="text-slate-500 font-medium">Urgency / Impact / Safety</span>
                  <span className="flex gap-1.5 font-semibold">
                    {[complaint.ai_urgency, complaint.ai_impact, complaint.ai_safety]
                      .filter(Boolean)
                      .map((value, index) => (
                        <span
                          key={index}
                          className={`px-2 py-0.5 rounded-full text-xs ${
                            value === 'High'
                              ? 'bg-red-100 text-red-700'
                              : value === 'Medium'
                                ? 'bg-amber-100 text-amber-700'
                                : 'bg-slate-100 text-slate-600'
                          }`}
                        >
                          {value}
                        </span>
                      ))}
                  </span>
                </div>
                {complaint.ai_uncertainty ? (
                  <div>
                    <span className="text-slate-500 font-medium block mb-0.5">Uncertainty</span>
                    <p className="text-slate-600 m-0 leading-relaxed">{complaint.ai_uncertainty}</p>
                  </div>
                ) : null}
              </div>
            ) : (
              <p className="text-sm text-slate-400 italic m-0">
                No AI suggestion was stored for this complaint.
              </p>
            )}
          </section>
          {/* ACTIONS: status, score, publish, delete */}
          <section className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 flex flex-col gap-5">
            <h3 className="text-sm font-bold uppercase tracking-wider text-slate-500 m-0">Actions</h3>

            {/* Status change / resolve */}
            <div className="flex flex-col gap-2">
              <label className="text-xs font-bold text-slate-700" htmlFor="dash-drawer-status">
                Status
              </label>
              <div className="flex gap-2">
                <StatusSelect
                  id="dash-drawer-status"
                  value={statusValue}
                  onChange={setStatusValue}
                  complaintId={complaint.id}
                  disabled={busy === 'status'}
                />
                <button
                  type="button"
                  onClick={saveStatus}
                  disabled={busy === 'status'}
                  className="px-4 py-2 rounded-lg text-sm font-semibold text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 whitespace-nowrap"
                >
                  {busy === 'status' ? 'Saving...' : statusValue === 'Resolved' ? 'Resolve' : 'Update status'}
                </button>
              </div>
            </div>

            {/* Score confirmation - the ONLY path to a score */}
            <div className="flex flex-col gap-2 border-t border-slate-100 pt-4">
              <h4 className="text-xs font-bold text-slate-700 m-0">Confirm scoring inputs</h4>
              <p className="text-xs text-slate-500 m-0 leading-relaxed">
                The scorer reads only these admin-confirmed levels (never the AI text). Values are
                prefilled from earlier confirmations or the AI suggestion - review before submitting.
              </p>
              <div className="grid grid-cols-3 gap-2">
                {[
                  ['confirmed_urgency', 'Urgency (max 30)'],
                  ['confirmed_impact', 'Impact (max 25)'],
                  ['confirmed_safety', 'Safety (max 10)'],
                ].map(([field, label]) => (
                  <label key={field} className="flex flex-col gap-1 text-xs font-semibold text-slate-600">
                    {label}
                    <select
                      value={scoreInputs[field]}
                      disabled={busy === 'score'}
                      onChange={(event) =>
                        setScoreInputs((current) => ({ ...current, [field]: event.target.value }))
                      }
                      className="border border-slate-300 rounded-lg text-sm px-2 py-2 bg-white"
                    >
                      {LEVELS.map((value) => (
                        <option key={value} value={value}>{value}</option>
                      ))}
                    </select>
                  </label>
                ))}
              </div>
              <button
                type="button"
                onClick={saveScore}
                disabled={busy === 'score'}
                className="self-start px-4 py-2 rounded-lg text-sm font-semibold text-white bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50"
              >
                {busy === 'score' ? 'Scoring...' : 'Confirm & score'}
              </button>
            </div>
            {/* Publish to the public feed */}
            <div className="flex flex-col gap-2 border-t border-slate-100 pt-4">
              {!pubOpen ? (
                <button
                  type="button"
                  onClick={() => setPubOpen(true)}
                  className="self-start px-4 py-2 rounded-lg text-sm font-semibold text-slate-700 bg-white border border-slate-300 hover:bg-slate-50"
                >
                  Publish to community feed...
                </button>
              ) : (
                <div className="flex flex-col gap-2">
                  <p className="text-xs text-slate-500 m-0">
                    Only sanitised wording goes public - it is stored verbatim and never copied from
                    the reporter&apos;s text.
                  </p>
                  <label className="flex flex-col gap-1 text-xs font-semibold text-slate-600">
                    Public summary
                    <textarea
                      rows={2}
                      value={pubSummary}
                      onChange={(event) => setPubSummary(event.target.value)}
                      placeholder="e.g. Lighting fault on the main stairwell repaired."
                      className="border border-slate-300 rounded-lg text-sm px-3 py-2"
                    />
                  </label>
                  <div className="grid grid-cols-2 gap-2">
                    <label className="flex flex-col gap-1 text-xs font-semibold text-slate-600">
                      Category
                      <input
                        type="text"
                        value={pubCategory}
                        onChange={(event) => setPubCategory(event.target.value)}
                        className="border border-slate-300 rounded-lg text-sm px-3 py-2"
                      />
                    </label>
                    <label className="flex flex-col gap-1 text-xs font-semibold text-slate-600">
                      Location
                      <input
                        type="text"
                        value={pubLocation}
                        onChange={(event) => setPubLocation(event.target.value)}
                        className="border border-slate-300 rounded-lg text-sm px-3 py-2"
                      />
                    </label>
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={publish}
                      disabled={busy === 'publish'}
                      className="px-4 py-2 rounded-lg text-sm font-semibold text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50"
                    >
                      {busy === 'publish' ? 'Publishing...' : 'Publish'}
                    </button>
                    <button
                      type="button"
                      onClick={() => setPubOpen(false)}
                      disabled={busy === 'publish'}
                      className="px-4 py-2 rounded-lg text-sm font-semibold border border-slate-300 text-slate-600"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Destructive */}
            <div className="flex flex-col gap-2 border-t border-slate-100 pt-4">
              {!confirmDelete ? (
                <button
                  type="button"
                  onClick={() => setConfirmDelete(true)}
                  className="self-start inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-semibold text-red-600 bg-white border border-red-200 hover:bg-red-50"
                >
                  Delete complaint...
                </button>
              ) : (
                <div className="bg-red-50 border border-red-200 rounded-xl p-3 flex flex-col gap-2">
                  <p className="text-sm font-bold text-red-800 m-0">
                    Delete {shortId(complaint.id)} permanently?
                  </p>
                  <p className="text-xs text-red-700 m-0">
                    The report, photo, score history, events and notes are all removed. This cannot
                    be undone.
                  </p>
                  <div className="flex gap-2 justify-end">
                    <button
                      type="button"
                      onClick={() => setConfirmDelete(false)}
                      disabled={busy === 'delete'}
                      className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-slate-300 bg-white"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={removeComplaint}
                      disabled={busy === 'delete'}
                      className="px-3 py-1.5 rounded-lg text-xs font-semibold text-white bg-red-600 hover:bg-red-700 disabled:opacity-50"
                    >
                      {busy === 'delete' ? 'Deleting...' : 'Yes, delete'}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </section>
          {/* AUDIT TRAIL */}
          <section className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
            <h3 className="text-sm font-bold uppercase tracking-wider text-slate-500 m-0 mb-3">
              Audit trail
            </h3>
            {timelineError ? (
              <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 m-0">
                {timelineError}
              </p>
            ) : null}
            {!timelineError && events.length === 0 ? (
              <p className="text-sm text-slate-400 italic m-0">No events recorded yet.</p>
            ) : null}
            <ol className="flex flex-col gap-0 m-0 p-0 list-none">
              {events.map((event) => (
                <li
                  key={event.id}
                  className="flex items-start justify-between gap-3 text-sm border-b border-slate-100 py-2.5 last:border-0"
                >
                  <div className="flex flex-col min-w-0">
                    <span className="font-semibold text-slate-800 capitalize">
                      {String(event.event_type || '').replace(/_/g, ' ')}
                    </span>
                    {event.from_value || event.to_value ? (
                      <span className="text-xs text-slate-500 font-mono truncate">
                        {event.from_value || '—'} → {event.to_value || '—'}
                      </span>
                    ) : null}
                  </div>
                  <div className="text-right text-xs text-slate-400 shrink-0">
                    <div className="font-medium text-slate-500">{event.actor_email || event.actor_role}</div>
                    <div>{fmtDateTime(event.created_at)}</div>
                  </div>
                </li>
              ))}
            </ol>
          </section>

          {/* INVESTIGATION NOTES (admin-only) */}
          <section className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
            <h3 className="text-sm font-bold uppercase tracking-wider text-slate-500 m-0 mb-1">
              Investigation notes
            </h3>
            <p className="text-xs text-slate-400 m-0 mb-3">
              Internal to administrators - students never see these.
            </p>
            {notes.length === 0 ? (
              <p className="text-sm text-slate-400 italic m-0 mb-3">No notes yet.</p>
            ) : (
              <ul className="flex flex-col gap-3 m-0 p-0 list-none mb-3">
                {notes.map((note) => (
                  <li key={note.id} className="bg-slate-50 border border-slate-100 rounded-lg p-3">
                    <p className="text-sm text-slate-700 m-0 whitespace-pre-wrap">{note.body}</p>
                    <p className="text-xs text-slate-400 m-0 mt-1.5">
                      {note.author_email || note.author_kind} · {fmtDateTime(note.created_at)}
                    </p>
                  </li>
                ))}
              </ul>
            )}
            <label className="flex flex-col gap-1.5 text-xs font-semibold text-slate-600" htmlFor="dash-note-input">
              Add a note
              <textarea
                id="dash-note-input"
                rows={2}
                value={noteDraft}
                onChange={(event) => setNoteDraft(event.target.value)}
                placeholder="What did you find or decide about this complaint?"
                className="border border-slate-300 rounded-lg text-sm px-3 py-2"
              />
            </label>
            <button
              type="button"
              onClick={addNote}
              disabled={busy === 'note' || noteDraft.trim().length < 2}
              className="self-start mt-2 px-4 py-2 rounded-lg text-sm font-semibold text-white bg-slate-800 hover:bg-slate-900 disabled:opacity-50"
            >
              {busy === 'note' ? 'Adding...' : 'Add note'}
            </button>
          </section>
        </div>
      </div>
    </div>
  );
}