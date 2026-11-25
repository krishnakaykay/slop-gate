"""FastAPI application entrypoint with lifespan TTL sweeper and frontend serving."""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import documents, gate1, gate2, stamp, telemetry
from app.services.session_store import store
from app.services.telemetry import enforce_rate_limit, extract_user_hash, log_event

logger = logging.getLogger(__name__)


async def _ttl_sweeper_loop() -> None:
    while True:
        try:
            removed = await store.sweep_expired_sessions()
            evicted = await store.enforce_storage_budget()
            if removed or evicted:
                logger.info("TTL sweeper purged %d expired and %d storage-capped session(s).", removed, evicted)
        except Exception as exc:
            logger.warning("TTL sweeper error: %s", exc)
        await asyncio.sleep(settings.ttl_sweep_interval_seconds)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await store.init()
    sweeper = asyncio.create_task(_ttl_sweeper_loop())
    try:
        yield
    finally:
        sweeper.cancel()
        try:
            await sweeper
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Slop Gate API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.slop_expose_docs else None,
    redoc_url="/redoc" if settings.slop_expose_docs else None,
    openapi_url="/openapi.json" if settings.slop_expose_docs else None,
)

# Same-origin by default (frontend & API share the same host); only enable CORS when explicitly configured
_cors_origins = [o.strip() for o in (settings.slop_allowed_origins or "").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "X-Gemini-Api-Key", "X-Beta-Code", "X-Admin-Token", "Last-Event-ID"],
    )

app.include_router(documents.router)
app.include_router(gate1.router)
app.include_router(gate2.router)
app.include_router(stamp.router)
app.include_router(telemetry.router)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
}


@app.middleware("http")
async def security_and_error_logging_middleware(request: Request, call_next):
    t0 = time.perf_counter()
    path = request.url.path
    try:
        response = await call_next(request)
    except Exception as exc:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-2000:]
        await log_event(
            event="http_unhandled_exception",
            severity="ERROR",
            source="backend",
            message=f"Unhandled {request.method} {path}: {exc}",
            user_hash=extract_user_hash(request),
            payload={
                "method": request.method,
                "path": path,
                "duration_ms": duration_ms,
                "error": str(exc)[:500],
                "traceback": tb,
            },
        )
        response = JSONResponse(status_code=500, content={"detail": "Internal server error."})

    for hdr, val in SECURITY_HEADERS.items():
        response.headers.setdefault(hdr, val)
    if request.headers.get("x-forwarded-proto", "").lower() == "https" or request.url.scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

    if response.status_code >= 400 and path != "/favicon.ico":
        duration_ms = int((time.perf_counter() - t0) * 1000)
        sev = "ERROR" if response.status_code >= 500 else "WARNING"
        await log_event(
            event="http_error_response",
            severity=sev,
            source="backend",
            message=f"{request.method} {path} -> HTTP {response.status_code} ({duration_ms}ms)",
            user_hash=extract_user_hash(request),
            payload={
                "method": request.method,
                "path": path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
    return response


@app.get("/api/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "has_live_llm": bool(settings.effective_gemini_key),
        "model_reasoning": settings.llm_model_reasoning,
        "model_fast": settings.llm_model_fast,
        "beta_code_required": bool((settings.slop_beta_code or "").strip()),
        "daily_run_limit": settings.slop_daily_run_limit_per_ip,
    }


@app.get("/api/models")
async def list_gemini_models(
    request: Request,
    x_gemini_api_key: str | None = Header(default=None),
) -> dict[str, object]:
    """List Gemini models: returns configured defaults for sponsored mode, or live v1beta models for BYOK."""
    enforce_rate_limit(
        request=request,
        bucket="list_models",
        limit=10,
        window_seconds=300.0,
        detail="Too many model lookup requests. Please wait a few minutes.",
    )
    user_key = (x_gemini_api_key or "").strip()
    if not user_key:
        # Avoid unauthenticated external Gemini API calls using the server's sponsored key
        defaults = list(dict.fromkeys([settings.llm_model_reasoning, settings.llm_model_fast]))
        return {"models": defaults, "source": "server_defaults"}
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=user_key, http_options=types.HttpOptions(api_version="v1beta"))
        pager = await client.aio.models.list()
        models: list[str] = []
        async for m in pager:
            name = (getattr(m, "name", "") or "").replace("models/", "")
            actions = getattr(m, "supported_actions", None) or []
            if name.startswith("gemini") and (not actions or "generateContent" in actions):
                models.append(name)
        return {"models": sorted(models, reverse=True), "source": "user_key"}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to list Gemini models: {exc}") from exc


# Serve zero-build frontend cleanly from FastAPI
static_dir = settings.frontend_dir / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def serve_index() -> FileResponse:
    index_path = settings.frontend_dir / "index.html"
    return FileResponse(index_path)
