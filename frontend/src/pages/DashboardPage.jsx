import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { fetchSummary, listComplaints, updateStatus } from '../api.js';
import { LIMIT_OPTIONS, SORTS, STATUSES, UNCLASSIFIED_LABEL } from '../constants.js';
import ComplaintCard from '../components/ComplaintCard.jsx';
import SummaryPanel from '../components/SummaryPanel.jsx';
import { EmptyState, ErrorBanner, Notice, SkeletonRows } from '../components/ui.jsx';

const DEFAULT_FILTERS = { status: '', category: '', sort: 'priority', limit: 20, offset: 0 };

export default function DashboardPage() {
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [items, setItems] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState(null);
  const [summaryError, setSummaryError] = useState(null);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [updatingId, setUpdatingId] = useState(null);
  const [updateError, setUpdateError] = useState(null);

  // Bumped on every fetch so a slow, superseded response is discarded.
  const requestRef = useRef(0);

  const loadList = useCallback(
    async (requestId) => {
      setLoading(true);
      setListError(null);
      try {
        const rows = await listComplaints(filters);
        if (requestRef.current !== requestId) return;
        setItems(Array.isArray(rows) ? rows : []);
      } catch (caught) {
        if (requestRef.current !== requestId) return;
        setItems([]);
        setListError(caught.message);
      } finally {
        if (requestRef.current === requestId) setLoading(false);
      }
    },
    [filters],
  );

  const loadSummary = useCallback(async () => {
    setSummaryLoading(true);
    setSummaryError(null);
    try {
      setSummary(await fetchSummary());
    } catch (caught) {
      setSummaryError(caught.message);
    } finally {
      setSummaryLoading(false);
    }
  }, []);

  useEffect(() => {
    requestRef.current += 1;
    loadList(requestRef.current);
  }, [loadList]);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  function setFilter(key, value) {
    setFilters((prev) => ({
      ...prev,
      [key]: value,
      // Changing any other filter starts paging over from the first page.
      offset: key === 'offset' ? value : 0,
    }));
  }

  function clearFilters() {
    setFilters(DEFAULT_FILTERS);
  }

  function refreshAll() {
    setUpdateError(null);
    requestRef.current += 1;
    loadList(requestRef.current);
    loadSummary();
  }

  async function handleStatusChange(complaint, nextStatus) {
    if (!nextStatus || nextStatus === complaint.status) return;
    setUpdateError(null);
    setUpdatingId(complaint.id);
    try {
      await updateStatus(complaint.id, nextStatus);
      // Requirement: refresh the data after a status update.
      requestRef.current += 1;
      const requestId = requestRef.current;
      await Promise.all([loadList(requestId), loadSummary()]);
    } catch (caught) {
      setUpdateError(`Complaint #${complaint.id} was not updated: ${caught.message}`);
    } finally {
      setUpdatingId(null);
    }
  }

  // Category filter is an EXACT match on the stored category, so only values
  // that really exist can be offered. The analytics key "Unclassified" stands
  // for a NULL category and therefore cannot be used as a filter value.
  const categoryOptions = useMemo(() => {
    const fromSummary = summary?.by_category ? Object.keys(summary.by_category) : [];
    const fromItems = items.map((row) => row.category).filter(Boolean);
    const all = new Set([...fromSummary, ...fromItems]);
    all.delete(UNCLASSIFIED_LABEL);
    return Array.from(all).sort((a, b) => a.localeCompare(b));
  }, [summary, items]);

  const filtersActive =
    Boolean(filters.status) ||
    Boolean(filters.category) ||
    filters.sort !== 'priority' ||
    filters.offset > 0;

  let emptyState = null;
  if (!loading && !listError && items.length === 0) {
    emptyState =
      summary && summary.total === 0 ? (
        <EmptyState
          title="No complaints yet"
          hint="Once students start reporting, complaints will appear here."
          action={
            <a className="btn btn--primary" href="#/submit">
              Report the first problem
            </a>
          }
        />
      ) : (
        <EmptyState
          title="No complaints match these filters"
          hint="Try a different status or category, or clear the filters."
          action={
            filtersActive ? (
              <button type="button" className="btn btn--ghost" onClick={clearFilters}>
                Clear filters
              </button>
            ) : null
          }
        />
      );
  }

  const showList = !loading && !listError;

  return (
    <div className="page">
      <header className="page__head page__head--row">
        <div>
          <p className="eyebrow">Admin</p>
          <h1>Operations dashboard</h1>
          <p className="page__lede">
            Everything below comes from the CampusLens API. Status changes are sent
            back with PATCH and the data is refreshed afterwards.
          </p>
        </div>
        <button type="button" className="btn btn--ghost" onClick={refreshAll}>
          Refresh
        </button>
      </header>

      <SummaryPanel
        summary={summary}
        error={summaryError}
        loading={summaryLoading && !summary}
        onRetry={loadSummary}
      />

      <section className="panel toolbar" aria-label="Sort and filter">
        <label className="field field--inline" htmlFor="filter-status">
          <span>Status</span>
          <select
            id="filter-status"
            className="select"
            value={filters.status}
            onChange={(event) => setFilter('status', event.target.value)}
          >
            <option value="">All statuses</option>
            {STATUSES.map((status) => (
              <option key={status} value={status}>{status}</option>
            ))}
          </select>
        </label>

        <label className="field field--inline" htmlFor="filter-category">
          <span>Category</span>
          <select
            id="filter-category"
            className="select"
            value={filters.category}
            onChange={(event) => setFilter('category', event.target.value)}
          >
            <option value="">All categories</option>
            {categoryOptions.map((category) => (
              <option key={category} value={category}>{category}</option>
            ))}
          </select>
        </label>

        <label className="field field--inline" htmlFor="filter-sort">
          <span>Sort</span>
          <select
            id="filter-sort"
            className="select"
            value={filters.sort}
            onChange={(event) => setFilter('sort', event.target.value)}
          >
            {SORTS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>

        <label className="field field--inline" htmlFor="filter-limit">
          <span>Per page</span>
          <select
            id="filter-limit"
            className="select"
            value={filters.limit}
            onChange={(event) => setFilter('limit', Number(event.target.value))}
          >
            {LIMIT_OPTIONS.map((option) => (
              <option key={option} value={option}>{option}</option>
            ))}
          </select>
        </label>

        {filtersActive ? (
          <button type="button" className="btn btn--ghost" onClick={clearFilters}>
            Clear
          </button>
        ) : null}
      </section>

      {updateError ? (
        <Notice tone="warning" title="Status update failed">
          <p>{updateError}</p>
        </Notice>
      ) : null}

      {listError ? (
        <ErrorBanner
          title="Complaints could not be loaded"
          message={listError}
          onRetry={refreshAll}
        />
      ) : null}

      <section className="results" aria-label="Complaints" aria-busy={loading}>
        {loading ? <SkeletonRows count={4} /> : null}
        {emptyState}
        {showList && items.length > 0 ? (
          <div className="cards">
            {items.map((complaint) => (
              <ComplaintCard
                key={complaint.id}
                complaint={complaint}
                busy={updatingId === complaint.id}
                onStatusChange={handleStatusChange}
              />
            ))}
          </div>
        ) : null}
      </section>

      {showList && items.length > 0 ? (
        <nav className="pager" aria-label="Pagination">
          <button
            type="button"
            className="btn btn--ghost"
            disabled={filters.offset <= 0}
            onClick={() => setFilter('offset', Math.max(0, filters.offset - filters.limit))}
          >
            ← Previous
          </button>
          <span className="muted">
            Showing {items.length} · offset {filters.offset}
          </span>
          <button
            type="button"
            className="btn btn--ghost"
            disabled={items.length < filters.limit}
            onClick={() => setFilter('offset', filters.offset + filters.limit)}
          >
            Next →
          </button>
        </nav>
      ) : null}
    </div>
  );
}
