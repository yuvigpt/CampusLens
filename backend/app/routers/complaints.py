"""
Complaint endpoints.

This is a thin HTTP layer: it validates the request, delegates to app.gemini
for analysis, app.priority for scoring and app.database for storage, then
shapes the response. No SQL and no scoring constants live here.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi import Path as PathParam

from .. import config, database, gemini, priority, schemas

router = APIRouter(prefix="/api/complaints", tags=["complaints"])

# Canonical file extension for each MIME type we accept.
_MIME_EXTENSIONS: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

# And the reverse, for clients that send a generic content type.
_EXTENSION_MIME: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def _settings(request: Request) -> config.Settings:
    """Read the app's settings, which main.create_app() stored on app.state."""
    return request.app.state.settings


def _extension_for(upload: UploadFile, settings: config.Settings) -> str:
    """Choose a safe extension for an upload, or reject the file.

    The client's filename is NEVER used as a path - only its suffix is looked
    at, and only after checking it against the allow-list.
    """
    content_type = (upload.content_type or "").split(";")[0].strip().lower()
    if content_type in _MIME_EXTENSIONS:
        return _MIME_EXTENSIONS[content_type]

    # Some clients send a generic type (or none at all). Fall back to the suffix.
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix in settings.allowed_extensions and suffix in _EXTENSION_MIME:
        return _MIME_EXTENSIONS[_EXTENSION_MIME[suffix]]

    raise HTTPException(
        status_code=422,
        detail=(
            f"Unsupported image type ({content_type or 'unknown'}). "
            f"Allowed: {', '.join(sorted(settings.allowed_mime_types))}"
        ),
    )


async def _save_upload(upload: UploadFile, settings: config.Settings) -> str:
    """Validate and store the uploaded image. Returns the stored relative path.

    The stored name is generated with uuid4(), so two students uploading
    'photo.jpg' can never overwrite each other, and a hostile filename such as
    '../../app/database.py' has no effect.
    """
    extension = _extension_for(upload, settings)

    # Read one byte past the limit so an oversize upload is caught cheaply.
    data = await upload.read(settings.max_upload_bytes + 1)
    if not data:
        raise HTTPException(status_code=422, detail="The uploaded image is empty.")
    if len(data) > settings.max_upload_bytes:
        limit_mb = settings.max_upload_bytes // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"Image is larger than the {limit_mb} MB limit.",
        )

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{extension}"
    (settings.upload_dir / filename).write_bytes(data)
    return f"uploads/{filename}"


@router.post(
    "",
    response_model=schemas.ComplaintOut,
    status_code=201,
    summary="Submit a complaint with a photo",
)
async def submit_complaint(
    request: Request,
    image: UploadFile = File(..., description="The complaint photo (jpg, jpeg, png or webp)."),
    description: str = Form(..., description="The student's complaint text."),
    location: str = Form(..., description="Where on campus the problem is."),
) -> schemas.ComplaintOut:
    """Accept a complaint, analyse it, score it and store it.

    A Gemini failure or an unmapped category is NOT a failed submission: the
    student's words and photo are still saved, with the AI columns and the
    priority score left NULL and a warning explaining what happened.

    A priority score is never guessed. If analysis or the category mapping is
    missing, the complaint is stored unscored rather than assumed to be "Low".
    """
    settings = _settings(request)

    description = (description or "").strip()
    location = (location or "").strip()
    if not description:
        raise HTTPException(status_code=422, detail="'description' must not be blank.")
    if not location:
        raise HTTPException(status_code=422, detail="'location' must not be blank.")

    # Store the image first: analysis needs a real file on disk.
    image_path = await _save_upload(image, settings)
    absolute_image = settings.upload_dir / Path(image_path).name

    warnings: list[str] = []
    ai_fields: dict[str, Any] = {}
    priority_score: Optional[float] = None
    breakdown: Optional[dict[str, Any]] = None

    # ---------------- 1. Gemini analysis (never fatal) ----------------
    result = gemini.analyze_complaint(absolute_image, description)
    outcome = schemas.analysis_outcome(result)
    warnings.extend(result.warnings)

    if result.ok and result.analysis:
        analysis = result.analysis
        ai_fields = {
            "category": analysis["category"],
            "issue_summary": analysis["issue_summary"],
            "safety_risk": analysis["safety_risk"],
            "functional_impact": analysis["functional_impact"],
            "urgency": analysis["urgency"],
            "evidence_from_image": analysis["evidence_from_image"],
            "uncertainty_or_missing_information": analysis[
                "uncertainty_or_missing_information"
            ],
        }

        # ------- 2. Category -> category weight (reuses priority.py) -------
        weight_class = priority.category_weight_class(analysis["category"])
        if weight_class is None:
            warnings.append(
                f"Category '{analysis['category']}' has no entry in "
                "priority.DEFAULT_CATEGORY_CLASSES, so no priority score was "
                "calculated. Add it to that mapping to have it scored."
            )
        else:
            # ------- 3. Score (reuses priority.py, no constants here) -------
            try:
                scored = priority.score_complaint(
                    safety_risk=analysis["safety_risk"],
                    functional_impact=analysis["functional_impact"],
                    urgency=analysis["urgency"],
                    category_weight=weight_class,
                )
                priority_score = scored.score
                breakdown = scored.breakdown
            except priority.PriorityValidationError as exc:
                warnings.append(f"Priority could not be calculated: {exc}")
    else:
        # result.error is already redacted by gemini.py.
        warnings.append(
            f"AI analysis was unavailable ({result.error_kind}), so this complaint "
            f"was saved without analysis or a priority score. {result.error}"
        )

    # ---------------- 4. Persist exactly once ----------------
    complaint = database.create_complaint(
        description=description,
        location=location,
        image_path=image_path,
        priority_score=priority_score,
        score_breakdown=breakdown,
        db_path=settings.db_path,
        **ai_fields,
    )

    return schemas.complaint_out(complaint, analysis=outcome, warnings=warnings)


@router.get(
    "",
    response_model=list[schemas.ComplaintOut],
    summary="List complaints (highest priority first by default)",
)
def list_complaints(
    request: Request,
    status: Optional[str] = Query(None, description="Reported | In Progress | Resolved"),
    category: Optional[str] = Query(None, description="Exact category match."),
    sort: str = Query("priority", description="priority | newest | oldest"),
    limit: Optional[int] = Query(None, ge=0, le=1000, description="Page size."),
    offset: int = Query(0, ge=0, description="Rows to skip."),
) -> list[schemas.ComplaintOut]:
    """List complaints using the filters and sorting the database layer supports."""
    settings = _settings(request)
    try:
        rows = database.list_complaints(
            status=status,
            category=category,
            sort=sort,
            limit=limit,
            offset=offset,
            db_path=settings.db_path,
        )
    except ValueError as exc:
        # database.list_complaints already validates status / category / sort and
        # the paging numbers, so reuse its message instead of duplicating rules.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return [schemas.complaint_out(row) for row in rows]


@router.get(
    "/{complaint_id}",
    response_model=schemas.ComplaintOut,
    summary="Get one complaint",
)
def get_complaint(
    request: Request,
    complaint_id: int = PathParam(..., ge=1, description="The complaint id."),
) -> schemas.ComplaintOut:
    settings = _settings(request)
    complaint = database.get_complaint(complaint_id, db_path=settings.db_path)
    if complaint is None:
        raise HTTPException(status_code=404, detail=f"Complaint {complaint_id} not found.")
    return schemas.complaint_out(complaint)


@router.patch(
    "/{complaint_id}/status",
    response_model=schemas.ComplaintOut,
    summary="Update a complaint's status",
)
def update_status(
    request: Request,
    body: schemas.StatusUpdateIn,
    complaint_id: int = PathParam(..., ge=1, description="The complaint id."),
) -> schemas.ComplaintOut:
    """Move a complaint between the three allowed statuses."""
    settings = _settings(request)
    updated = database.update_complaint_status(
        complaint_id, body.status, db_path=settings.db_path
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Complaint {complaint_id} not found.")
    return schemas.complaint_out(updated)