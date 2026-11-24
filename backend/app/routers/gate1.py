"""Gate 1 (Pre-Flight Check) 2-step EventSource-compatible SSE & report routes."""

from __future__ import annotations

import asyncio
import logging
import traceback

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.config import settings
from app.schemas.gate1 import (
    CreatorIntentRequest,
    DispositionRequest,
    Gate1Report,
    Gate1RunCreated,
    Gate1RunRequest,
    IssueDisposition,
)
from app.services.gate1_engine import execute_gate1
from app.services.session_store import store
from app.services.sse_bus import sse_bus
from app.services.telemetry import enforce_sponsored_access, estimate_cost_usd, extract_user_hash, log_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sessions", tags=["gate1"])


async def _run_gate1_background(
    *,
    run_id: str,
    session_id: str,
    revision: int,
    req: Gate1RunRequest,
    api_key_override: str | None,
    user_hash: str,
) -> None:
    try:
        rev_data = await store.get_revision(session_id, revision)
        if not rev_data:
            await store.update_gate1_run(run_id, status="failed", stage="error", error_message="Revision not found.", decrement_active=True)
            await sse_bus.publish(run_id, "error", {"error": "Revision not found."}, terminal=True)
            return

        await store.update_gate1_run(run_id, status="running", stage="ingested")
        await sse_bus.publish(run_id, "stage", {"stage": "started", "message": "Starting Pre-Flight Check..."})

        async def on_progress(ev_name: str, payload: dict[str, object]) -> None:
            st = str(payload.get("stage", ev_name))
            await store.update_gate1_run(run_id, stage=st)
            await sse_bus.publish(run_id, ev_name, payload)

        # Pull latest creator_intent in case user submitted it while Pass 2 was running
        latest_run = await store.get_gate1_run(run_id)
        intent_text = (latest_run["config"].get("creator_intent", "") if latest_run else "") or req.creator_intent

        report = await execute_gate1(
            run_id=run_id,
            session_id=session_id,
            revision=revision,
            pages=rev_data["pages"],
            revision_dir=store.revision_dir(session_id, revision),
            revision_diff=rev_data["diff"],
            doc_format=req.doc_format,
            doc_purpose=req.doc_purpose,
            target_persona=req.target_persona,
            custom_audience=req.custom_audience,
            creator_intent=intent_text,
            ghost_deck_mode=rev_data["ghost_deck_mode"],
            api_key_override=api_key_override,
            model_reasoning=req.model_reasoning,
            model_fast=req.model_fast,
            on_progress=on_progress,
        )

        # Re-read creator_intent right before finalizing so we never clobber user submission
        latest_run2 = await store.get_gate1_run(run_id)
        if latest_run2 and latest_run2["config"].get("creator_intent"):
            report.creator_intent = latest_run2["config"]["creator_intent"]

        await store.update_gate1_run(run_id, status="completed", stage="completed", report=report, decrement_active=True)
        await sse_bus.publish(run_id, "complete", {"run_id": run_id, "report": report.model_dump()}, terminal=True)

        crit_cnt = sum(1 for i in report.issues if i.severity.value == "critical")
        ver_cnt = sum(1 for i in report.issues if i.severity.value == "verify")
        est_usd = estimate_cost_usd(
            prompt_tokens=report.usage.prompt_tokens,
            output_tokens=report.usage.output_tokens,
            thoughts_tokens=report.usage.thoughts_tokens,
            model=req.model_reasoning or settings.llm_model_reasoning,
        ) if report.mode == "live_gemini" else 0.0
        await log_event(
            event="gate1_completed",
            source="backend",
            session_id=session_id,
            revision=revision,
            stage="report",
            user_hash=user_hash,
            payload={
                "run_id": run_id,
                "mode": report.mode,
                "verdict": report.verdict,
                "doc_format": report.doc_format,
                "doc_purpose": report.doc_purpose,
                "target_persona": report.target_persona,
                "page_count": len(report.pages),
                "critical_count": crit_cnt,
                "verify_count": ver_cnt,
                "polish_count": len(report.polish_tips),
                "latency_ms": report.latency_ms,
                "prompt_tokens": report.usage.prompt_tokens,
                "output_tokens": report.usage.output_tokens,
                "thoughts_tokens": report.usage.thoughts_tokens,
                "est_cost_usd": est_usd,
            },
        )
    except Exception as exc:
        logger.exception("Gate 1 run %s failed", run_id)
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-1500:]
        await log_event(
            event="gate1_failed",
            severity="ERROR",
            source="backend",
            message=f"Gate 1 run {run_id} failed: {exc}",
            session_id=session_id,
            revision=revision,
            stage="waiting_intent",
            user_hash=user_hash,
            payload={"run_id": run_id, "error": str(exc)[:500], "traceback": tb},
        )
        await store.update_gate1_run(run_id, status="failed", stage="error", error_message=str(exc), decrement_active=True)
        await sse_bus.publish(run_id, "error", {"run_id": run_id, "error": str(exc)}, terminal=True)


@router.post("/{session_id}/gate1/runs", response_model=Gate1RunCreated, status_code=202)
async def start_gate1_run(
    session_id: str,
    req: Gate1RunRequest,
    request: Request,
    x_gemini_api_key: str | None = Header(default=None),
    x_beta_code: str | None = Header(default=None),
) -> Gate1RunCreated:
    user_hash = await enforce_sponsored_access(
        request=request,
        x_gemini_api_key=x_gemini_api_key,
        x_beta_code=x_beta_code,
        check_daily_quota=True,
    )
    rev_data = await store.get_revision(session_id, req.revision)
    if not rev_data:
        raise HTTPException(status_code=404, detail="Session or revision not found.")
    revision = int(rev_data["revision"])

    run_id = await store.create_gate1_run(
        session_id=session_id,
        revision=revision,
        config=req.model_dump(),
    )
    is_sponsored = not bool((x_gemini_api_key or "").strip()) and bool(settings.effective_gemini_key)
    await log_event(
        event="gate1_started_sponsored" if is_sponsored else "gate1_started",
        source="backend",
        session_id=session_id,
        revision=revision,
        stage="waiting_intent",
        user_hash=user_hash,
        payload={
            "run_id": run_id,
            "sponsored": is_sponsored,
            "doc_format": req.doc_format,
            "doc_purpose": req.doc_purpose,
            "target_persona": req.target_persona,
            "page_count": int(rev_data["page_count"]),
        },
    )
    sse_bus.get_or_create(run_id)
    asyncio.create_task(
        _run_gate1_background(
            run_id=run_id,
            session_id=session_id,
            revision=revision,
            req=req,
            api_key_override=x_gemini_api_key,
            user_hash=user_hash,
        )
    )
    return Gate1RunCreated(
        run_id=run_id,
        session_id=session_id,
        revision=revision,
        status="queued",
        events_url=f"/api/sessions/{session_id}/gate1/runs/{run_id}/events",
    )


@router.get("/{session_id}/gate1/runs/{run_id}/events")
async def stream_gate1_events(
    session_id: str,
    run_id: str,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    run = await store.get_gate1_run(run_id)
    if not run or run["session_id"] != session_id:
        raise HTTPException(status_code=404, detail="Gate 1 run not found.")

    # If the run already finished before SSE connected (or after restart), emit terminal event cleanly
    if run["status"] == "completed" and run["report"] is not None:
        stream = sse_bus.get_or_create(run_id)
        if not stream.done:
            await sse_bus.publish(run_id, "complete", {"run_id": run_id, "report": run["report"].model_dump()}, terminal=True)
    elif run["status"] == "failed":
        stream = sse_bus.get_or_create(run_id)
        if not stream.done:
            await sse_bus.publish(run_id, "error", {"run_id": run_id, "error": run["error_message"] or "Unknown error"}, terminal=True)

    try:
        cursor = int(last_event_id) if last_event_id else 0
    except ValueError:
        cursor = 0

    return StreamingResponse(
        sse_bus.subscribe(run_id, last_event_id=cursor),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{session_id}/gate1", response_model=Gate1Report)
async def get_latest_gate1(
    session_id: str,
    revision: int | None = Query(default=None),
) -> Gate1Report:
    report = await store.get_latest_gate1_report(session_id, revision)
    if not report:
        raise HTTPException(status_code=404, detail="No completed Gate 1 report found for this session/revision.")
    return report


@router.patch("/{session_id}/gate1/runs/{run_id}/issues/{issue_id}", response_model=Gate1Report)
async def set_issue_disposition(
    session_id: str,
    run_id: str,
    issue_id: str,
    req: DispositionRequest,
    request: Request,
) -> Gate1Report:
    run = await store.get_gate1_run(run_id)
    if not run or run["session_id"] != session_id or not run["report"]:
        raise HTTPException(status_code=404, detail="Gate 1 run not found.")

    target_issue = next((i for i in run["report"].issues if i.id == issue_id), None)
    if not target_issue:
        raise HTTPException(status_code=404, detail="Issue not found.")

    if req.status == "clear":
        disp = None
    else:
        if req.status == "intentional" and target_issue.severity.value == "critical" and len(req.note.strip()) < 5:
            raise HTTPException(status_code=400, detail="Please add a brief 1-line reason when marking a Critical issue as Intentional.")
        disp = IssueDisposition(status=req.status, note=req.note.strip())

    updated = await store.update_issue_disposition(run_id=run_id, issue_id=issue_id, disposition=disp)
    if not updated:
        raise HTTPException(status_code=404, detail="Unable to update issue disposition.")
    await log_event(
        event="issue_triaged",
        source="backend",
        session_id=session_id,
        revision=int(run["revision"]),
        stage="report",
        user_hash=extract_user_hash(request),
        payload={
            "issue_id": issue_id,
            "severity": target_issue.severity.value,
            "category": target_issue.category.value,
            "disposition": req.status,
            "verdict_after": updated.verdict,
        },
    )
    return updated


@router.patch("/{session_id}/gate1/runs/{run_id}/intent")
async def save_creator_intent(
    session_id: str,
    run_id: str,
    req: CreatorIntentRequest,
    request: Request,
) -> dict[str, object]:
    run = await store.get_gate1_run(run_id)
    if not run or run["session_id"] != session_id:
        raise HTTPException(status_code=404, detail="Gate 1 run not found.")
    updated = await store.update_creator_intent(run_id=run_id, creator_intent=req.creator_intent.strip())
    await log_event(
        event="intent_submitted",
        source="backend",
        session_id=session_id,
        revision=int(run["revision"]),
        stage="waiting_intent",
        user_hash=extract_user_hash(request),
        payload={"char_len": len(req.creator_intent.strip())},
    )
    return {"ok": True, "creator_intent": req.creator_intent.strip(), "report": updated.model_dump() if updated else None}
