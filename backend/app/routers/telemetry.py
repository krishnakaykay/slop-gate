"""Telemetry ingestion, 1-click feedback capture, beta code verification, and admin summary routes."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, Request

from app.config import settings
from app.schemas.telemetry import (
    BetaVerifyRequest,
    ClientEventRequest,
    FeedbackRequest,
    FeedbackResponse,
)
from app.services import session_store
from app.services.telemetry import (
    constant_time_equals,
    emit_cloud_json_log,
    enforce_rate_limit,
    extract_user_hash,
    log_event,
)

router = APIRouter(prefix="/api", tags=["telemetry"])


@router.post("/telemetry/event")
async def ingest_client_event(req: ClientEventRequest, request: Request) -> dict[str, bool]:
    """Capture frontend behavioral telemetry and client-side JS errors."""
    user_hash = enforce_rate_limit(
        request=request,
        bucket="telemetry_event",
        limit=120,
        window_seconds=60.0,
        detail="Telemetry rate limit exceeded.",
    )
    # Keep payload bounded so client events cannot bloat logs/SQLite
    safe_payload: dict[str, object] = {}
    for k, v in list((req.payload or {}).items())[:20]:
        ks = str(k)[:48]
        if isinstance(v, (int, float, bool)) or v is None:
            safe_payload[ks] = v
        else:
            safe_payload[ks] = str(v)[:500]

    await log_event(
        event=req.event.strip()[:80],
        severity=req.severity,
        source="frontend",
        message=f"[frontend] {req.event}" + (f" ({req.stage})" if req.stage else ""),
        session_id=req.session_id,
        revision=req.revision,
        stage=req.stage,
        user_hash=user_hash,
        payload=safe_payload,
    )
    return {"ok": True}


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(req: FeedbackRequest, request: Request) -> FeedbackResponse:
    """Capture 1-click 👍/👎 ratings, quick tags, and optional user comments."""
    user_hash = enforce_rate_limit(
        request=request,
        bucket="user_feedback",
        limit=30,
        window_seconds=3600.0,
        detail="Too many feedback submissions this hour. Thank you!",
    )
    clean_tags = [str(t).strip()[:40] for t in (req.tags or []) if str(t).strip()][:10]
    clean_comment = (req.comment or "").strip()[:2000]
    safe_context = {str(k)[:48]: str(v)[:200] for k, v in list((req.context or {}).items())[:12]}

    fb_id = await session_store.store.upsert_user_feedback(
        feedback_id=req.feedback_id,
        session_id=req.session_id,
        revision=req.revision,
        stage=req.stage,
        user_hash=user_hash,
        rating=req.rating,
        tags=clean_tags,
        comment=clean_comment,
        context=safe_context,
    )

    # Emit as NOTICE in Cloud Logging so feedback is immediately searchable in Logs Explorer
    emit_cloud_json_log(
        severity="NOTICE",
        event="user_feedback",
        source="feedback",
        message=f"[feedback] rating={req.rating} stage={req.stage} tags={clean_tags} comment={clean_comment[:160]}",
        session_id=req.session_id,
        revision=req.revision,
        stage=req.stage,
        user_hash=user_hash,
        payload={
            "feedback_id": fb_id,
            "rating": req.rating,
            "tags": clean_tags,
            "comment": clean_comment,
            "context": safe_context,
        },
    )
    await session_store.store.record_telemetry_event(
        severity="INFO",
        event="user_feedback",
        source="feedback",
        session_id=req.session_id,
        revision=req.revision,
        stage=req.stage,
        user_hash=user_hash,
        payload={"feedback_id": fb_id, "rating": req.rating, "tags": clean_tags, "has_comment": bool(clean_comment)},
    )
    return FeedbackResponse(ok=True, feedback_id=fb_id, rating=req.rating)


@router.post("/beta/verify")
async def verify_beta_code(req: BetaVerifyRequest, request: Request) -> dict[str, object]:
    """Verify optional SLOP_BETA_CODE before unlocking sponsored beta UI."""
    required = (settings.slop_beta_code or "").strip()
    if not required:
        return {"ok": True, "required": False}
    user_hash = enforce_rate_limit(
        request=request,
        bucket="beta_verify",
        limit=10,
        window_seconds=300.0,
        detail="Too many invite code attempts. Please wait 5 minutes.",
    )
    if not constant_time_equals(req.code.strip(), required):
        await log_event(
            event="beta_code_verify_failed",
            severity="WARNING",
            source="guardrail",
            user_hash=user_hash,
        )
        raise HTTPException(status_code=401, detail="Invalid beta access code.")
    await log_event(event="beta_code_verified", severity="INFO", source="guardrail", user_hash=user_hash)
    return {"ok": True, "required": True}


@router.get("/admin/telemetry")
async def get_admin_telemetry(
    limit: int = Query(default=100, ge=1, le=500),
    token: str | None = Query(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, object]:
    """Protected admin endpoint to inspect feedback, funnel counts, and recent errors."""
    configured = (settings.slop_admin_token or "").strip()
    if not configured:
        raise HTTPException(status_code=404, detail="Admin telemetry endpoint is disabled (set SLOP_ADMIN_TOKEN to enable).")
    provided = (x_admin_token or token or "").strip()
    if not provided or not constant_time_equals(provided, configured):
        raise HTTPException(status_code=403, detail="Invalid admin token.")
    return await session_store.store.get_telemetry_summary(limit=limit)
