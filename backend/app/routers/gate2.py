"""Gate 2 (Meeting Q&A Prep & Ownership Check) FastAPI routes."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, Request

from app.config import settings
from app.schemas.gate2 import Gate2AnswerRequest, Gate2StartRequest, Gate2StateResponse
from app.services.gate2_engine import (
    build_gate2_response,
    evaluate_gate2_answer,
    start_or_resume_gate2,
)
from app.services.session_store import store
from app.services.telemetry import enforce_sponsored_access, log_event

router = APIRouter(prefix="/api/sessions", tags=["gate2"])


@router.post("/{session_id}/gate2/start", response_model=Gate2StateResponse)
async def start_gate2(
    session_id: str,
    req: Gate2StartRequest,
    request: Request,
    x_gemini_api_key: str | None = Header(default=None),
    x_beta_code: str | None = Header(default=None),
) -> Gate2StateResponse:
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

    is_sponsored = not bool((x_gemini_api_key or "").strip()) and bool(settings.effective_gemini_key)

    # Enforce user rule: all non-Polish Gate 1 issues must be resolved (fixed, Intentional, or Ignore for now)
    gate1_report = await store.get_latest_gate1_report(session_id, revision)
    if is_sponsored and gate1_report is None:
        raise HTTPException(
            status_code=400,
            detail="Complete the Pre-Flight Check before starting Meeting Q&A Prep.",
        )
    if gate1_report:
        unresolved = [i for i in gate1_report.issues if i.disposition is None]
        if unresolved:
            raise HTTPException(
                status_code=400,
                detail=f"Resolve all {len(unresolved)} non-Polish Pre-Flight issue(s) (Fix, Intentional, or Ignore for now) before starting Meeting Q&A Prep.",
            )

    # Return existing Gate 2 session for this revision if already created
    existing = await store.get_gate2_session(session_id, revision)
    if existing:
        return build_gate2_response(
            session_id=session_id,
            revision=revision,
            filename=str(rev_data["filename"]),
            mode=existing["mode"],
            questions=existing["questions"],
            answers=existing["answers"],
            preserved_count=int(existing["preserved_count"]),
            gate1_report=gate1_report,
        )

    prior_verified = await store.list_verified_gate2_answers(session_id)
    doc_format = gate1_report.doc_format if gate1_report else rev_data["detected_format"]
    doc_purpose = gate1_report.doc_purpose if gate1_report else "decide"
    target_persona = gate1_report.target_persona if gate1_report else "leadership"
    custom_audience = gate1_report.custom_audience if gate1_report else ""

    eff_reasoning = settings.llm_model_reasoning if is_sponsored else req.model_reasoning
    mode, questions, answers, preserved_count = await start_or_resume_gate2(
        session_id=session_id,
        revision=revision,
        filename=str(rev_data["filename"]),
        pages=rev_data["pages"],
        revision_dir=store.revision_dir(session_id, revision),
        doc_format=doc_format,
        doc_purpose=doc_purpose,
        target_persona=target_persona,
        custom_audience=custom_audience,
        prior_verified_answers=prior_verified,
        gate1_report=gate1_report,
        api_key_override=x_gemini_api_key,
        model_reasoning=eff_reasoning,
    )

    await store.save_gate2_session(
        session_id=session_id,
        revision=revision,
        mode=mode,
        questions=questions,
        answers=answers,
        preserved_count=preserved_count,
    )
    est_g2_usd = 0.045 if (mode == "live_gemini" and is_sponsored) else 0.0
    await log_event(
        event="gate2_started",
        source="backend",
        session_id=session_id,
        revision=revision,
        stage="prep",
        user_hash=user_hash,
        payload={
            "sponsored": is_sponsored,
            "mode": mode,
            "question_count": len(questions),
            "preserved_count": preserved_count,
            "est_cost_usd": est_g2_usd,
        },
    )
    return build_gate2_response(
        session_id=session_id,
        revision=revision,
        filename=str(rev_data["filename"]),
        mode=mode,
        questions=questions,
        answers=answers,
        preserved_count=preserved_count,
        gate1_report=gate1_report,
    )


@router.get("/{session_id}/gate2", response_model=Gate2StateResponse)
async def get_gate2_state(
    session_id: str,
    revision: int | None = Query(default=None),
) -> Gate2StateResponse:
    rev_data = await store.get_revision(session_id, revision)
    if not rev_data:
        raise HTTPException(status_code=404, detail="Session or revision not found.")
    rev = int(rev_data["revision"])
    existing = await store.get_gate2_session(session_id, rev)
    if not existing:
        raise HTTPException(status_code=404, detail="Meeting Q&A Prep has not been started for this revision.")
    gate1_report = await store.get_latest_gate1_report(session_id, rev)
    return build_gate2_response(
        session_id=session_id,
        revision=rev,
        filename=str(rev_data["filename"]),
        mode=existing["mode"],
        questions=existing["questions"],
        answers=existing["answers"],
        preserved_count=int(existing["preserved_count"]),
        gate1_report=gate1_report,
    )


@router.post("/{session_id}/gate2/answer", response_model=Gate2StateResponse)
async def submit_gate2_answer(
    session_id: str,
    req: Gate2AnswerRequest,
    request: Request,
    x_gemini_api_key: str | None = Header(default=None),
    x_beta_code: str | None = Header(default=None),
) -> Gate2StateResponse:
    user_hash = await enforce_sponsored_access(
        request=request,
        x_gemini_api_key=x_gemini_api_key,
        x_beta_code=x_beta_code,
        check_gate2_answer_quota=True,
    )
    rev_data = await store.get_revision(session_id, req.revision)
    if not rev_data:
        raise HTTPException(status_code=404, detail="Session or revision not found.")
    existing = await store.get_gate2_session(session_id, req.revision)
    if not existing:
        raise HTTPException(status_code=404, detail="Meeting Q&A Prep session not found.")

    questions = existing["questions"]
    answers = existing["answers"]
    target_q = next((q for q in questions if q.id == req.question_id), None)
    if not target_q:
        raise HTTPException(status_code=404, detail=f"Question '{req.question_id}' not found.")

    is_sponsored = not bool((x_gemini_api_key or "").strip()) and bool(settings.effective_gemini_key)
    eff_fast = settings.llm_model_fast if is_sponsored else req.model_fast
    prior_attempts = answers[req.question_id].attempts if req.question_id in answers else 0
    evaluated = await evaluate_gate2_answer(
        question=target_q,
        answer_text=req.answer_text,
        prior_attempts=prior_attempts,
        pages=rev_data["pages"],
        api_key_override=x_gemini_api_key,
        model_fast=eff_fast,
    )
    answers[req.question_id] = evaluated

    await store.save_gate2_session(
        session_id=session_id,
        revision=req.revision,
        mode=existing["mode"],
        questions=questions,
        answers=answers,
        preserved_count=int(existing["preserved_count"]),
    )

    if evaluated.status == "verified":
        await store.upsert_verified_gate2_answer(
            session_id=session_id,
            source_revision=req.revision,
            question=target_q,
            answer_text=evaluated.answer_text,
            feedback=evaluated.feedback,
        )

    est_ans_usd = 0.004 if (existing["mode"] == "live_gemini" and is_sponsored) else 0.0
    await log_event(
        event="gate2_answer_submitted",
        source="backend",
        session_id=session_id,
        revision=req.revision,
        stage="prep",
        user_hash=user_hash,
        payload={
            "sponsored": is_sponsored,
            "question_id": req.question_id,
            "is_limitation": target_q.is_limitation,
            "status": evaluated.status,
            "attempts": evaluated.attempts,
            "answer_len": len(req.answer_text.strip()),
            "est_cost_usd": est_ans_usd,
        },
    )

    gate1_report = await store.get_latest_gate1_report(session_id, req.revision)
    return build_gate2_response(
        session_id=session_id,
        revision=req.revision,
        filename=str(rev_data["filename"]),
        mode=existing["mode"],
        questions=questions,
        answers=answers,
        preserved_count=int(existing["preserved_count"]),
        gate1_report=gate1_report,
    )
