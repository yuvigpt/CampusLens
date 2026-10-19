"""
CampusLens FastAPI application.

``create_app()`` is a factory so tests can inject settings (and therefore a
fake database / storage / AI layer) without touching the real ones.

Run from the ``backend`` folder:
    python -m uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config, database, security
from .routers import complaints as _complaints_routes

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("campuslens")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Close the database pool on shutdown."""
    try:
        yield
    finally:
        database.close_pool()


def create_app(settings: Optional[config.Settings] = None) -> FastAPI:
    """Build the API. Pass explicit settings to redirect every dependency."""
    app_settings = settings or config.default_settings()

    app = FastAPI(
        title="CampusLens API",
        version=app_settings.service_version,
        lifespan=_lifespan,
    )
    app.state.settings = app_settings

    limiter = security.RateLimiter(
        enabled=app_settings.rate_limit_enabled,
        submit_limit=app_settings.rate_limit_submit_per_minute,
        auth_limit=app_settings.rate_limit_auth_per_minute,
        public_limit=app_settings.rate_limit_public_per_minute,
        general_limit=app_settings.rate_limit_general_per_minute,
    )
    app.state.rate_limiter = limiter

    # Security & Rate Limiting runs inside CORS
    app.add_middleware(
        security.SecurityAndRateLimitMiddleware,
        settings=app_settings,
        limiter=limiter,
    )

    # Never a wildcard, and never with credentials: a stray browser page must
    # not be able to drive this API. Expose rate limit headers so clients can
    # inspect throttle status and retry delays.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(app_settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
        expose_headers=[
            "Retry-After",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
        ],
    )

    # A fresh router per app: FastAPI only allows one include per instance.
    app.include_router(_complaints_routes.build_router())

    @app.get("/", tags=["meta"])
    def root() -> dict[str, str]:
        return {
            "status": "ok",
            "service": app_settings.service_name,
            "version": app_settings.service_version,
        }

    @app.exception_handler(security.RequestSizeExceeded)
    async def request_size_exceeded(
        request: Request, exc: security.RequestSizeExceeded
    ) -> JSONResponse:
        """Handle request size limits without letting them become 500s."""
        return JSONResponse(
            status_code=413,
            content={"detail": "Request entity too large."},
            headers={
                "x-content-type-options": "nosniff",
                "x-frame-options": "DENY",
            },
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        """Last line of defence: never leak a traceback, SQL text or secret."""
        logger.exception("unhandled error on %s", request.url.path)
        return JSONResponse(
            status_code=500, content={"detail": "Internal server error."}
        )

    return app


def __getattr__(name: str):
    """Build the ASGI app lazily.

    `uvicorn app.main:app` needs a module attribute named `app`. Creating it at
    import time would consume a router and leave later create_app() calls (in
    tests) with no routes, so it is built on first access instead.
    """
    if name == "app":
        instance = create_app()
        globals()["app"] = instance
        return instance
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    import os
    import uvicorn

    port = int(os.environ.get("PORT", "10000"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)