"""
CampusLens FastAPI application.

``create_app()`` is a factory so tests can point the API at a temporary database
and upload folder without touching the real ones. ``app`` at the bottom is what
uvicorn imports:

    backend\\venv\\Scripts\\python.exe -m uvicorn app.main:app --reload

Run that from the ``backend`` folder (or pass --app-dir backend).
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from . import config, database, schemas, storage
from .routers import analytics, complaints

# Generated upload names are 32 hex characters plus one known extension. This
# pattern is the first of several checks on the way to serving a file.
_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Prepare storage once, at startup. Safe to run repeatedly (idempotent)."""
    settings: config.Settings = app.state.settings
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    database.init_db(settings.db_path)
    yield


def create_app(settings: Optional[config.Settings] = None) -> FastAPI:
    """Build the API. Pass explicit settings to redirect the database/uploads."""
    settings = settings or config.default_settings()

    app = FastAPI(
        title="CampusLens API",
        version=settings.service_version,
        lifespan=_lifespan,
    )
    app.state.settings = settings

    # Origins come from CORS_ORIGINS (comma-separated), defaulting to the
    # local Vite dev server when it is unset or empty. No wildcard, and no
    # credentials, so a stray browser page cannot drive this API.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    app.include_router(complaints.router)
    app.include_router(analytics.router)

    @app.get("/api/health", response_model=schemas.HealthOut, tags=["meta"])
    def health() -> schemas.HealthOut:
        """Liveness probe. Reveals nothing about paths, config or secrets."""
        return schemas.HealthOut(
            status="ok",
            service=settings.service_name,
            version=settings.service_version,
        )

    @app.get("/uploads/{filename}", include_in_schema=False)
    def uploaded_image(filename: str, request: Request) -> Response:
        """Serve a stored complaint image.

        The name must look like a generated upload, carry an allowed image
        extension, and resolve to a file sitting directly inside the uploads
        folder. Everything else returns a plain 404, so probing cannot tell the
        difference between "not allowed" and "not there".

        A file on disk (local development, or rows created before Supabase
        Storage) is served directly with a FileResponse. When Supabase
        Storage is configured and no local file exists, the object lives in
        the private bucket: a short-lived signed URL (5 minutes) is created
        on demand and the browser is redirected to it. If signing fails, a
        generic 502 is returned that reveals nothing about the backend.
        """
        current: config.Settings = request.app.state.settings

        # 1. Reject anything that is not a plain filename.
        if not _SAFE_FILENAME.match(filename) or ".." in filename:
            raise HTTPException(status_code=404, detail="Not found.")

        # 2. Only serve image extensions we accept.
        if Path(filename).suffix.lower() not in current.allowed_extensions:
            raise HTTPException(status_code=404, detail="Not found.")

        # 3. Resolve and confirm the file is directly inside the uploads folder.
        upload_dir = current.upload_dir.resolve()
        candidate = (upload_dir / filename).resolve()
        if candidate.parent != upload_dir:
            raise HTTPException(status_code=404, detail="Not found.")

        # 4a. On disk: local development and legacy rows behave exactly as
        # they always have.
        if candidate.is_file():
            return FileResponse(candidate)

        # 4b. Private Supabase bucket: sign the object for this request only
        # and redirect (the bucket itself never accepts direct public reads).
        if current.supabase_enabled:
            try:
                signed = storage.signed_url(current, f"uploads/{filename}")
            except storage.StorageError:
                raise HTTPException(
                    status_code=502, detail="Image storage unavailable."
                ) from None
            return RedirectResponse(signed, status_code=302)

        # 5. Nothing stored under that name.
        raise HTTPException(status_code=404, detail="Not found.")

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        """Last line of defence: never leak a traceback or secret to a client."""
        return JSONResponse(status_code=500, content={"detail": "Internal server error."})

    return app


app = create_app()