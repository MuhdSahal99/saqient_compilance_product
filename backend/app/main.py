from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import (
    ai,
    audit_completion,
    audit_risks,
    auth,
    checklists,
    datasets,
    documents,
    einvoices,
    engagements,
    entities,
    members,
    monitors,
    reviews,
    rule_packs,
    sampling,
    tax_calendar,
    tax_losses,
    tax_setup,
    transfer_pricing,
    workpapers,
    workspace,
)
from app.config import get_settings
from app.db import get_engine

# Register job handlers for the API process too (eager mode uses them).
from app.services import ai_suggestions as _ai_jobs  # noqa: F401
from app.services import datasets as _dataset_jobs  # noqa: F401
from app.services import documents as _doc_jobs  # noqa: F401
from app.services import reviews as _review_jobs  # noqa: F401

logger = logging.getLogger("saqient")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.validate_for_production()
    settings.validate_ai()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    settings.validate_for_production()
    app = FastAPI(
        title="Saqient Compliance Workspace API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/api/docs",
        openapi_url=None if settings.is_production else "/api/openapi.json",
        redoc_url=None,
    )
    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Content-Type", "X-CSRF-Token"],
        )

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault(
            "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
        )
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if settings.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Do not echo submitted values back (they may contain document text or secrets).
        errors = [{"loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()]
        first = errors[0] if errors else {"loc": [], "msg": "Invalid request"}
        field = ".".join(str(p) for p in (first["loc"] or [])[1:]) or "request"
        return JSONResponse(
            status_code=422, content={"detail": f"{field}: {first['msg']}", "errors": errors}
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled error", extra={"path": request.url.path, "error_class": type(exc).__name__}
        )
        return JSONResponse(
            status_code=500, content={"detail": "Something went wrong. Please try again."}
        )

    for module in (
        auth,
        documents,
        checklists,
        reviews,
        ai,
        workspace,
        entities,
        rule_packs,
        datasets,
        members,
        tax_setup,
        tax_calendar,
        tax_losses,
        einvoices,
        transfer_pricing,
        monitors,
        workpapers,
        engagements,
        audit_risks,
        sampling,
        audit_completion,
    ):
        app.include_router(module.router, prefix="/api")

    @app.get("/api/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/health/ready", tags=["health"])
    def ready() -> JSONResponse:
        checks: dict[str, str] = {}
        try:
            with get_engine().connect() as conn:
                conn.execute(text("select 1"))
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "unavailable"
        try:
            import redis

            redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1).ping()
            checks["redis"] = "ok"
        except Exception:
            checks["redis"] = "unavailable"
        ok = all(v == "ok" for v in checks.values())
        return JSONResponse(
            status_code=200 if ok else 503, content={"status": "ok" if ok else "degraded", **checks}
        )

    return app


app = create_app()
