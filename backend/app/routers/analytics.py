"""
Dashboard analytics.

Aggregation happens in Python on top of ``database.list_complaints()`` rather
than with new SQL. That keeps a single place in the codebase that reads
complaints and avoids duplicating query logic from database.py. It is fine at
hackathon scale; the trade-off is called out in the stage report.

Complaints with no priority score are counted separately as ``unscored`` so the
bands always add up to ``total``.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from .. import database, priority, schemas

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

UNSCORED_LABEL = "Unscored"
UNCLASSIFIED_LABEL = "Unclassified"


@router.get(
    "/summary",
    response_model=schemas.AnalyticsSummaryOut,
    summary="Complaint counts for the admin dashboard",
)
def summary(request: Request) -> schemas.AnalyticsSummaryOut:
    settings = request.app.state.settings
    rows = database.list_complaints(
        db_path=settings.db_path, database_url=settings.database_url
    )

    # Start from the allowed vocabularies so every key is always present,
    # even when the count is zero.
    by_status: dict[str, int] = {name: 0 for name in database.ALLOWED_STATUSES}
    by_priority_band: dict[str, int] = {
        name: 0 for _, name in priority.BAND_THRESHOLDS
    }
    by_category: dict[str, int] = {}
    unscored = 0

    for row in rows:
        status = row.get("status")
        by_status[status] = by_status.get(status, 0) + 1

        band = schemas.priority_band_for(row)
        if band is None:
            unscored += 1
        else:
            by_priority_band[band] = by_priority_band.get(band, 0) + 1

        category = row.get("category") or UNCLASSIFIED_LABEL
        by_category[category] = by_category.get(category, 0) + 1

    total = len(rows)
    unresolved = total - by_status.get(database.STATUS_RESOLVED, 0)

    return schemas.AnalyticsSummaryOut(
        total=total,
        by_status=by_status,
        by_priority_band=by_priority_band,
        unscored=unscored,
        unresolved=unresolved,
        by_category=by_category,
    )