import { useCallback, useEffect, useState } from 'react';
import { Activity, Calendar, MapPin, Search } from 'lucide-react';

import { fetchPublicComplaints, listCampusComplaints } from '../api.js';
import { useAuth } from '../auth.jsx';
import { PriorityBadge } from '../components/Priority.jsx';
import { StatusBadge } from '../components/Status.jsx';
import { EmptyState, ErrorBanner, Notice, SkeletonRows } from '../components/ui.jsx';

/**
 * Public community feed - GET /api/public/complaints.
 *
 * No token is sent and none is needed. The backend reads public_complaints,
 * which has no reporter identity and no priority score, so this page cannot
 * show either even if it wanted to.
 */
export default function CommunityPage() {
  const { token } = useAuth();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [feedQuery, setFeedQuery] = useState('');

  // Signed-in campus feed: GET /api/community/campus (sanitised small info -
  // location/status/band/category/date only, never a description or identity).
  const [campus, setCampus] = useState([]);
  const [campusLoading, setCampusLoading] = useState(true);
  const [campusError, setCampusError] = useState(null);
  const [campusQuery, setCampusQuery] = useState('');

  const loadCampus = useCallback(async () => {
    if (!token) {
      setCampusLoading(false);
      return;
    }
    setCampusLoading(true);
    setCampusError(null);
    try {
      const rows = await listCampusComplaints(token);
      setCampus(Array.isArray(rows) ? rows : []);
    } catch (caught) {
      setCampus([]);
      setCampusError(caught.message);
    } finally {
      setCampusLoading(false);
    }
  }, [token]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const rows = await fetchPublicComplaints({ limit: 50 });
      setItems(Array.isArray(rows) ? rows : []);
    } catch (caught) {
      setItems([]);
      setError(caught.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    loadCampus();
  }, [loadCampus]);

  const campusMatches = campus.filter((row) => {
    const needle = campusQuery.trim().toLowerCase();
    if (!needle) return true;
    return [row.location, row.category, row.status, row.band]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(needle));
  });

  const feedMatches = items.filter((row) => {
    const needle = feedQuery.trim().toLowerCase();
    if (!needle) return true;
    return [row.public_location, row.public_category, row.public_summary]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(needle));
  });

  return (
    <div className="flex flex-col gap-8 max-w-5xl mx-auto">
      <header className="flex flex-col gap-2 animate-fade-up">
        <p className="text-xs font-bold uppercase tracking-widest text-gradient">Community</p>
        <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">Published campus issues</h1>
        <p className="text-slate-600 max-w-3xl text-lg mt-2 leading-relaxed">
          A sanitised view of problems campus operations have reviewed and
          approved for publication. Reporters are never identified.
        </p>
      </header>

      <ErrorBanner
        title="The public feed could not be loaded"
        message={error}
        onRetry={load}
      />

      {!token ? (
        <div className="bg-gradient-to-r from-indigo-50 to-violet-50 border border-indigo-100 rounded-xl p-4 flex items-center justify-between gap-4 animate-fade-up">
          <p className="text-sm text-indigo-800 m-0">
            Want to report an issue or track your own submissions?
          </p>
          <a href="#/signin" className="btn-gradient whitespace-nowrap px-4 py-2 text-sm font-medium rounded-lg">Sign in</a>
        </div>
      ) : null}

      {/* Campus activity - signed-in, sanitised small info (migration 016). */}
      {token ? (
        <section className="flex flex-col gap-4" aria-label="Campus activity" aria-busy={campusLoading}>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="flex flex-col gap-1">
              <h2 className="text-lg font-extrabold text-slate-900 m-0 flex items-center gap-2">
                <Activity className="w-5 h-5 text-indigo-500" />
                Campus activity
              </h2>
              <p className="text-sm text-slate-600 m-0">
                Sanitised status of reports across campus - where, what kind and how it is
                going. Reporter identities, descriptions and scores are never included.
              </p>
            </div>
            <label className="flex items-center gap-2" htmlFor="campus-search">
              <Search className="w-4 h-4 text-slate-400" />
              <input
                id="campus-search"
                type="search"
                value={campusQuery}
                onChange={(event) => setCampusQuery(event.target.value)}
                placeholder="Filter by location or category..."
                className="border border-slate-300 rounded-lg text-base sm:text-sm px-3 py-2 w-full sm:w-64 focus:ring-2 focus:ring-indigo-500"
              />
            </label>
          </div>

          <ErrorBanner
            title="The campus feed could not be loaded"
            message={campusError}
            onRetry={loadCampus}
          />

          {!campusLoading && !campusError && campus.length === 0 ? (
            <EmptyState
              title="No campus reports yet"
              body="Once reports start coming in, their sanitised status will appear here."
            />
          ) : null}

          {!campusLoading && campus.length > 0 && campusMatches.length === 0 ? (
            <EmptyState
              title="Nothing matches that filter"
              body="Try a different location or category."
            />
          ) : null}

          {campusLoading ? <SkeletonRows count={2} /> : null}

          {!campusLoading && campusMatches.length > 0 ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
              {campusMatches.map((row) => (
                <article
                  key={row.id}
                  className="bg-white rounded-xl border border-slate-200 shadow-sm p-4 flex flex-col gap-2"
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-bold text-slate-800 m-0 leading-snug line-clamp-2">
                      {row.category || 'General'}
                    </p>
                    <StatusBadge status={row.status} />
                  </div>
                  <p className="text-xs text-slate-500 font-medium flex items-center gap-1.5 m-0">
                    <MapPin className="w-3.5 h-3.5 text-indigo-400 shrink-0" />
                    <span className="truncate">{row.location}</span>
                  </p>
                  <div className="flex items-center justify-between text-xs mt-auto pt-2 border-t border-slate-100">
                    <PriorityBadge band={row.band} />
                    <span className="text-slate-400 flex items-center gap-1">
                      <Calendar className="w-3.5 h-3.5" />
                      {row.created_at
                        ? new Date(row.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
                        : '—'}
                    </span>
                  </div>
                </article>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      <section className="flex flex-col gap-4" aria-label="Published issues" aria-busy={loading}>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="flex flex-col gap-1">
            <h2 className="text-lg font-extrabold text-slate-900 m-0">Published issues</h2>
            <p className="text-sm text-slate-600 m-0">
              Approved summaries that campus operations published for everyone.
            </p>
          </div>
          {items.length > 0 ? (
            <label className="flex items-center gap-2" htmlFor="feed-search">
              <Search className="w-4 h-4 text-slate-400" />
              <input
                id="feed-search"
                type="search"
                value={feedQuery}
                onChange={(event) => setFeedQuery(event.target.value)}
                placeholder="Search published issues..."
                className="border border-slate-300 rounded-lg text-base sm:text-sm px-3 py-2 w-full sm:w-64 focus:ring-2 focus:ring-indigo-500"
              />
            </label>
          ) : null}
        </div>
        {loading ? <SkeletonRows count={3} /> : null}

        {!loading && !error && items.length === 0 ? (
          <EmptyState
            title="Nothing published yet"
            body="Approved summaries will appear here once campus operations review them."
            action={
              token ? (
                <a className="btn-gradient inline-flex px-5 py-2.5 font-medium rounded-xl" href="#/submit">
                  Report a problem
                </a>
              ) : (
                <a className="btn-gradient inline-flex px-5 py-2.5 font-medium rounded-xl" href="#/signin">
                  Sign in
                </a>
              )
            }
          />
        ) : null}

        {!loading && items.length > 0 && feedMatches.length === 0 ? (
          <EmptyState
            title="No published issues match your search"
            body="Try a different keyword."
          />
        ) : null}

        {!loading && feedMatches.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {feedMatches.map((item, index) => (
              <article
                className="bg-white rounded-xl border border-slate-200 shadow-sm card-lift p-5 flex flex-col h-full gap-4 animate-fade-up"
                style={{ animationDelay: `${Math.min(index, 8) * 60}ms` }}
                key={item.id}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex flex-col gap-1">
                    <h3 className="font-bold text-slate-900 m-0 leading-tight">{item.public_category}</h3>
                    <p className="text-xs text-slate-500 font-medium flex items-center gap-1 m-0">
                      <MapPin className="w-3 h-3 text-indigo-400" />
                      {item.public_location}
                    </p>
                  </div>
                  <div className="shrink-0 mt-0.5">
                    <StatusBadge status={item.status} />
                  </div>
                </div>
                
                <p className="text-sm text-slate-700 leading-relaxed m-0 flex-1">{item.public_summary}</p>
                
                {item.approved_at ? (
                  <div className="flex items-center gap-1.5 text-xs text-slate-400 font-medium pt-3 border-t border-slate-100 mt-auto">
                    <Calendar className="w-3.5 h-3.5" />
                    Published {new Date(item.approved_at).toLocaleDateString()}
                  </div>
                ) : null}
              </article>
            ))}
          </div>
        ) : null}
      </section>
    </div>
  );
}
