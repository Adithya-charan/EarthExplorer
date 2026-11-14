"""EarthTrend Explorer API application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.config import APP_NAME, APP_VERSION, Settings, get_settings
from app.errors import AppError
from app.geo.services import GeoServices
from app.routers import analysis, datasets, geo, ingest, story
from app.services.store import DatasetStore

log = logging.getLogger("earthtrend")

DESCRIPTION = """
Trend analysis for Earth-science time series.

**Data status:** observed NASA GPM IMERG V07 *global* area-average series (`observed_global`, not regional) and
clearly labelled **synthetic** demo data (`is_synthetic = true`, including the regional demo series) are bundled as
separate datasets. No regional NASA observations have been supplied, so real regional analysis is disabled. Every
data response carries a `provenance` block that says where the numbers came from.

Explanations are produced by deterministic rules from the computed statistics; no external AI service is used.
"""

UPLOAD_PATHS = ("/api/upload", "/api/profile", "/api/upload-grid")


def create_app(settings: Settings | None = None, *, geo_transport: httpx.BaseTransport | None = None) -> FastAPI:
    """Build the API. ``geo_transport`` lets tests replace the network used by the geocoder and terrain tiles."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.geo.start_warmup()  # Natural Earth index builds in the background
        try:
            yield
        finally:
            application.state.geo.close()

    app = FastAPI(title=APP_NAME, version=APP_VERSION, description=DESCRIPTION, lifespan=lifespan)
    app.state.settings = settings
    app.state.store = DatasetStore(settings)
    app.state.store.load_all()
    app.state.geo = GeoServices(settings, transport=geo_transport)

    app.add_middleware(GZipMiddleware, minimum_size=2048)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # Reject oversized uploads before the body is parsed whenever the client declares its size.
        if request.method == "POST" and request.url.path in UPLOAD_PATHS:
            declared = request.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > settings.max_upload_bytes + 1024 * 1024:
                return JSONResponse(
                    status_code=413,
                    content=AppError(
                        413, "file_too_large", f"The upload is larger than the {settings.max_upload_mb} MB limit."
                    ).to_payload(),
                )
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        parts = []
        for err in exc.errors()[:6]:
            loc = ".".join(str(p) for p in err["loc"] if p not in ("body", "query"))
            parts.append(f"{loc or 'request'}: {err['msg']}")
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "validation_error", "message": "Invalid request - " + "; ".join(parts)}},
        )

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error")  # stack trace goes to the server log only
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "Something went wrong on the server. Please try again."}},
        )

    app.include_router(datasets.router)
    app.include_router(ingest.router)
    app.include_router(analysis.router)
    app.include_router(geo.router)
    app.include_router(story.router)
    return app


app = create_app()
