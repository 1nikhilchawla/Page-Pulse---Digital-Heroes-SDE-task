"""Page Pulse — a small web tool that audits a URL and reports its vitals.

Run locally:
    uvicorn backend.main:app --reload

API docs (auto-generated): http://localhost:8000/docs
Frontend:                   http://localhost:8000/
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .analyzer import audit_url
from .exceptions import PagePulseError
from .models import AuditRequest, ErrorResponse
from .ratelimit import rate_limit_middleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("page_pulse")

app = FastAPI(
    title="Page Pulse API",
    description="Audits a URL and returns a JSON health report: status, timing, "
    "SEO basics, accessibility, and content signals, plus a composite Pulse Score.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.middleware("http")(rate_limit_middleware)


@app.exception_handler(PagePulseError)
async def page_pulse_error_handler(request: Request, exc: PagePulseError) -> JSONResponse:
    """Every predictable failure mode lands here as a clean JSON error —
    the API never returns a bare 500 for a bad URL, a timeout, or a
    non-HTML response. See exceptions.py for the full list of cases.
    """
    logger.info("audit_error code=%s message=%s", exc.code, exc.message)
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(error=exc.code, message=exc.message, details=exc.details).model_dump(),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort safety net. Per spec — "sensible errors, never a crash" —
    even a bug we didn't anticipate should still come back as JSON, not a
    connection reset. Logged loudly since anything landing here is a gap
    in the specific handlers above and should get its own exception class.
    """
    logger.exception("unhandled error auditing request")
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="internal_error",
            message="Something went wrong on our side while auditing that URL.",
        ).model_dump(),
    )


@app.get("/api/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok"}


@app.post(
    "/api/audit",
    tags=["audit"],
    summary="Audit a URL and return its Page Pulse report",
    response_model=None,  # AuditReport on success, ErrorResponse on failure (see handlers above)
)
async def audit(payload: AuditRequest):
    report = await audit_url(payload.url)
    logger.info(
        "audit_ok url=%s status=%s score=%s ms=%s",
        report.resolved_url,
        report.metrics.http_status,
        report.score.total,
        report.metrics.response_time_ms,
    )
    return report


# Serve the frontend as static files, mounted last so it doesn't shadow /api/*.
_frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
