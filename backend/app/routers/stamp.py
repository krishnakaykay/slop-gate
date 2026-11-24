"""Final Read-Through tracking & Owner Accountability PDF Stamping routes."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from app.schemas.stamp import ReadThroughUpdateRequest, StampRequest, StampResponse
from app.services.pdf_stamper import stamp_pdf_sync
from app.services.session_store import store
from app.services.telemetry import extract_user_hash, log_event

router = APIRouter(prefix="/api/sessions", tags=["stamp"])


@router.get("/{session_id}/readthrough")
async def get_readthrough_state(
    session_id: str,
    revision: int | None = Query(default=None),
) -> dict[str, object]:
    rev_data = await store.get_revision(session_id, revision)
    if not rev_data:
        raise HTTPException(status_code=404, detail="Session or revision not found.")
    rev = int(rev_data["revision"])
    reviewed = await store.get_reviewed_pages(session_id, rev)
    return {
        "session_id": session_id,
        "revision": rev,
        "page_count": int(rev_data["page_count"]),
        "reviewed_pages": reviewed,
        "all_reviewed": len(reviewed) >= int(rev_data["page_count"]),
    }


@router.put("/{session_id}/readthrough")
async def update_readthrough_state(
    session_id: str,
    req: ReadThroughUpdateRequest,
    request: Request,
) -> dict[str, object]:
    rev_data = await store.get_revision(session_id, req.revision)
    if not rev_data:
        raise HTTPException(status_code=404, detail="Session or revision not found.")
    page_count = int(rev_data["page_count"])
    valid = [p for p in req.reviewed_pages if 1 <= p <= page_count]
    saved = await store.set_reviewed_pages(session_id, req.revision, valid)
    all_rev = len(saved) >= page_count
    if all_rev:
        await log_event(
            event="readthrough_completed",
            source="backend",
            session_id=session_id,
            revision=req.revision,
            stage="readthrough",
            user_hash=extract_user_hash(request),
            payload={"page_count": page_count},
        )
    return {
        "session_id": session_id,
        "revision": req.revision,
        "page_count": page_count,
        "reviewed_pages": saved,
        "all_reviewed": all_rev,
    }


@router.post("/{session_id}/stamp", response_model=StampResponse)
async def stamp_document(session_id: str, req: StampRequest, request: Request) -> StampResponse:
    rev_data = await store.get_revision(session_id, req.revision)
    if not rev_data:
        raise HTTPException(status_code=404, detail="Session or revision not found.")

    page_count = int(rev_data["page_count"])
    if req.reviewed_pages:
        saved = await store.set_reviewed_pages(session_id, req.revision, [p for p in req.reviewed_pages if 1 <= p <= page_count])
    else:
        saved = await store.get_reviewed_pages(session_id, req.revision)

    if req.enforce_all_reviewed and len(saved) < page_count:
        raise HTTPException(
            status_code=400,
            detail=f"Final Read-Through incomplete ({len(saved)}/{page_count} pages reviewed). Review all pages to unlock the Owner Accountability Stamp.",
        )

    latest_report = await store.get_latest_gate1_report(session_id, req.revision)
    gate2_session = await store.get_gate2_session(session_id, req.revision)
    gate2_complete = bool(
        gate2_session
        and gate2_session["questions"]
        and all(
            gate2_session["answers"].get(q.id) and gate2_session["answers"][q.id].status == "verified"
            for q in gate2_session["questions"]
        )
    )
    if gate2_complete and latest_report and latest_report.verdict == "READY":
        status = "VERIFIED_FULL"
    elif latest_report and latest_report.verdict == "READY":
        status = "VERIFIED"
    else:
        status = "REVIEWED"
    doc_format = latest_report.doc_format if latest_report else str(rev_data["detected_format"])
    doc_purpose = latest_report.doc_purpose if latest_report else "decide"
    target_persona = latest_report.target_persona if latest_report else "leadership"

    source_pdf = Path(rev_data["pdf_path"])
    output_pdf = store.stamped_pdf_path(session_id, req.revision)
    rev_dir = store.revision_dir(session_id, req.revision)

    result = await asyncio.to_thread(
        stamp_pdf_sync,
        source_pdf=source_pdf,
        output_pdf=output_pdf,
        revision_dir=rev_dir,
        owner_name=req.owner_name.strip(),
        scope=req.scope,
        status=status,
        doc_format=doc_format,
        doc_purpose=doc_purpose,
        target_persona=target_persona,
    )

    orig_stem = Path(str(rev_data["filename"])).stem
    out_name = f"{orig_stem}_reviewed.pdf"
    await log_event(
        event="pdf_stamped",
        source="backend",
        session_id=session_id,
        revision=req.revision,
        stage="signoff",
        user_hash=extract_user_hash(request),
        payload={
            "scope": req.scope,
            "page_count": page_count,
            "preferred_corner": str(result["preferred_corner"]),
            "preflight_status": status,
        },
    )
    return StampResponse(
        session_id=session_id,
        revision=req.revision,
        owner_name=req.owner_name.strip(),
        scope=req.scope,
        download_url=f"/api/sessions/{session_id}/stamp/download?revision={req.revision}",
        filename=out_name,
        preferred_corner=str(result["preferred_corner"]),
        placements=result["placements"],  # type: ignore[arg-type]
        metadata_written=result["metadata_written"],  # type: ignore[arg-type]
    )


@router.get("/{session_id}/stamp/download")
async def download_stamped_pdf(
    session_id: str,
    revision: int | None = Query(default=None),
) -> FileResponse:
    rev_data = await store.get_revision(session_id, revision)
    if not rev_data:
        raise HTTPException(status_code=404, detail="Session or revision not found.")
    rev = int(rev_data["revision"])
    stamped = store.stamped_pdf_path(session_id, rev)
    if not stamped.exists():
        raise HTTPException(status_code=404, detail="Stamped PDF has not been generated for this revision yet.")
    orig_stem = Path(str(rev_data["filename"])).stem
    return FileResponse(
        path=stamped,
        media_type="application/pdf",
        filename=f"{orig_stem}_reviewed.pdf",
    )
