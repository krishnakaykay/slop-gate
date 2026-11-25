"""Document upload, calibration sample loader, revision diff, and page image routes."""

from __future__ import annotations

import asyncio
import secrets
import shutil
from pathlib import Path

from fastapi import APIRouter, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from app.config import settings
from app.schemas.document import DocumentPreScanResponse, SampleInfo
from app.services.pdf_ingest import IngestionError, compute_revision_diff, ingest_pdf_sync
from app.services.session_store import store
from app.services.telemetry import enforce_rate_limit, enforce_sponsored_access, log_event

router = APIRouter(prefix="/api", tags=["documents"])

_ingest_semaphore = asyncio.Semaphore(settings.max_concurrent_ingests)

CALIBRATION_SAMPLES: list[SampleInfo] = [
    SampleInfo(
        id="hard_15p_qbr",
        label="15-Slide Board QBR Deck (Subtle Contradictions)",
        category="hard",
        filename="04_hard_15p_exec_deck_appendix_contradiction.pdf",
        relative_path="hard/04_hard_15p_exec_deck_appendix_contradiction.pdf",
        suggested_format="slide_deck",
        suggested_purpose="decide",
        suggested_persona="leadership",
        description="Mostly sharp 15-slide Board plan hiding 2 subtle contradictions (Slides 2↔14 ARR/NRR and Slides 6↔13 OpEx).",
    ),
    SampleInfo(
        id="sharp_memo_copilot",
        label="2-Page Amazon Decision Memo (Sharp)",
        category="sharp",
        filename="02_sharp_memo_ai_support_copilot.pdf",
        relative_path="sharp/02_sharp_memo_ai_support_copilot.pdf",
        suggested_format="narrative_memo",
        suggested_purpose="decide",
        suggested_persona="leadership",
        description="Clean PR/FAQ-style decision memo with explicit Ask, reconciled math, trend chart, and pre-emptive FAQ.",
    ),
    SampleInfo(
        id="slop_deck_helios",
        label="6-Slide Cloud Migration Deck (AI Slop)",
        category="slop",
        filename="01_slop_deck_cloud_migration.pdf",
        relative_path="slop/01_slop_deck_cloud_migration.pdf",
        suggested_format="slide_deck",
        suggested_purpose="decide",
        suggested_persona="leadership",
        description="Passive headings, cluttered diagrams, flat bar chart contradicting 'exponential growth', and $2.4M vs $1.1M clashes.",
    ),
    SampleInfo(
        id="hard_smooth_slop",
        label="5-Slide Expansion Deck (Smooth 2026 Slop)",
        category="hard",
        filename="01_hard_smooth_2026_ai_slop.pdf",
        relative_path="hard/01_hard_smooth_2026_ai_slop.pdf",
        suggested_format="slide_deck",
        suggested_purpose="decide",
        suggested_persona="leadership",
        description="Zero cliché buzzwords and clean visuals, but cherry-picked seasonal baseline and hollow generic strategy.",
    ),
    SampleInfo(
        id="hard_messy_rfc",
        label="2-Page Principal Eng RFC (Must Pass)",
        category="hard",
        filename="02_hard_messy_human_genius_rfc.pdf",
        relative_path="hard/02_hard_messy_human_genius_rfc.pdf",
        suggested_format="narrative_memo",
        suggested_purpose="decide",
        suggested_persona="leadership",
        description="Dense plain RFC with standard eng acronyms (p99, WAL, gRPC) and airtight math — tests zero false positives.",
    ),
    SampleInfo(
        id="hard_inform_postmortem",
        label="2-Page SEV-1 Postmortem (Inform-Only)",
        category="hard",
        filename="03_hard_inform_only_sev1_postmortem.pdf",
        relative_path="hard/03_hard_inform_only_sev1_postmortem.pdf",
        suggested_format="narrative_memo",
        suggested_purpose="inform",
        suggested_persona="leadership",
        description="Crisp Inform-only postmortem with zero funding Ask — verifies Inform purpose never triggers Missing Ask.",
    ),
    SampleInfo(
        id="slop_cross_org",
        label="5-Slide API Sunset (Cross-Org Slop)",
        category="slop",
        filename="03_slop_deck_cross_org_api_deprecation.pdf",
        relative_path="slop/03_slop_deck_cross_org_api_deprecation.pdf",
        suggested_format="slide_deck",
        suggested_purpose="decide",
        suggested_persona="cross_org",
        description="Visually tidy deck that buries Payments impact on Slide 4 behind platform jargon and conflicts Oct 15 vs Nov 30.",
    ),
    SampleInfo(
        id="sharp_deck_helios",
        label="6-Slide Cloud Migration Deck (Sharp A/B Pair)",
        category="sharp",
        filename="01_sharp_deck_cloud_migration.pdf",
        relative_path="sharp/01_sharp_deck_cloud_migration.pdf",
        suggested_format="slide_deck",
        suggested_purpose="decide",
        suggested_persona="leadership",
        description="Sharp McKinsey Pyramid counterpart to the Helios slop deck — ideal to upload as v2!",
    ),
]


def _build_prescan_response(
    *,
    session_id: str,
    revision: int,
    filename: str,
    ingested: dict[str, object],
    diff=None,
) -> DocumentPreScanResponse:
    pages = ingested["pages"]  # type: ignore[assignment]
    page_count = int(ingested["page_count"])
    thumbs = [f"/api/documents/{session_id}/pages/{p}/image?revision={revision}&thumb=true" for p in range(1, page_count + 1)]
    titles = [
        {
            "page": p.page_number,
            "heading": p.heading,
            "word_count": p.word_count,
            "is_scanned": p.is_scanned,
            "extracted_text": p.extracted_text[:2500],
        }
        for p in pages
    ]
    return DocumentPreScanResponse(
        session_id=session_id,
        revision=revision,
        filename=filename,
        page_count=page_count,
        detected_format=ingested["detected_format"],  # type: ignore[arg-type]
        format_confidence=ingested["format_confidence"],  # type: ignore[arg-type]
        ghost_deck_mode=ingested["ghost_deck_mode"],  # type: ignore[arg-type]
        page_thumbnails=thumbs,
        page_titles=titles,
        revision_diff=diff,
        has_live_llm=bool(settings.effective_gemini_key),
    )


async def _read_upload_bounded(file: UploadFile) -> bytes:
    """Read uploaded PDF with a hard byte ceiling and PDF magic-header check before ingestion."""
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds {settings.max_file_size_mb} MB upload limit.",
            )
        chunks.append(chunk)
    data = b"".join(chunks)
    if len(data) < 5 or not data[:1024].lstrip().startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid PDF document.")
    return data


async def _ingest_new_session(pdf_bytes: bytes, filename: str) -> DocumentPreScanResponse:
    await store.enforce_storage_budget()
    session_id = secrets.token_hex(12)
    rev_dir = store.revision_dir(session_id, 1)
    async with _ingest_semaphore:
        try:
            ingested = await asyncio.to_thread(ingest_pdf_sync, pdf_bytes, rev_dir)
        except IngestionError as exc:
            shutil.rmtree(store.sessions_dir / session_id, ignore_errors=True)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            shutil.rmtree(store.sessions_dir / session_id, ignore_errors=True)
            raise HTTPException(status_code=500, detail=f"PDF ingestion failed: {exc}") from exc

    await store.create_session_with_revision(
        session_id=session_id,
        filename=filename,
        pdf_path=ingested["pdf_path"],  # type: ignore[arg-type]
        page_count=int(ingested["page_count"]),
        detected_format=str(ingested["detected_format"]),
        format_confidence=str(ingested["format_confidence"]),
        ghost_deck_mode=str(ingested["ghost_deck_mode"]),
        pages=ingested["pages"],  # type: ignore[arg-type]
    )
    return _build_prescan_response(session_id=session_id, revision=1, filename=filename, ingested=ingested)


@router.get("/samples", response_model=list[SampleInfo])
async def list_samples() -> list[SampleInfo]:
    available: list[SampleInfo] = []
    for s in CALIBRATION_SAMPLES:
        if (settings.examples_dir / s.relative_path).exists():
            available.append(s)
    return available


@router.post("/documents/sample/{sample_id}", response_model=DocumentPreScanResponse)
async def load_sample_document(
    sample_id: str,
    request: Request,
    x_gemini_api_key: str | None = Header(default=None),
    x_beta_code: str | None = Header(default=None),
) -> DocumentPreScanResponse:
    enforce_rate_limit(
        request=request,
        bucket="upload_doc",
        limit=25,
        window_seconds=3600.0,
        detail="Too many document uploads this hour. Please wait a bit before uploading more.",
    )
    user_hash = await enforce_sponsored_access(request=request, x_gemini_api_key=x_gemini_api_key, x_beta_code=x_beta_code)
    sample = next((s for s in CALIBRATION_SAMPLES if s.id == sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail=f"Unknown sample_id '{sample_id}'")
    path = settings.examples_dir / sample.relative_path
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Sample PDF missing on disk: {sample.relative_path}")
    raw = path.read_bytes()
    resp = await _ingest_new_session(raw, sample.filename)
    await log_event(
        event="doc_uploaded",
        source="backend",
        session_id=resp.session_id,
        revision=1,
        stage="upload",
        user_hash=user_hash,
        payload={
            "is_sample": True,
            "sample_id": sample_id,
            "page_count": resp.page_count,
            "detected_format": resp.detected_format,
            "size_kb": round(len(raw) / 1024, 1),
        },
    )
    return resp


@router.post("/documents", response_model=DocumentPreScanResponse)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    x_gemini_api_key: str | None = Header(default=None),
    x_beta_code: str | None = Header(default=None),
) -> DocumentPreScanResponse:
    enforce_rate_limit(
        request=request,
        bucket="upload_doc",
        limit=25,
        window_seconds=3600.0,
        detail="Too many document uploads this hour. Please wait a bit before uploading more.",
    )
    user_hash = await enforce_sponsored_access(request=request, x_gemini_api_key=x_gemini_api_key, x_beta_code=x_beta_code)
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only .pdf files are supported.")
    pdf_bytes = await _read_upload_bounded(file)
    resp = await _ingest_new_session(pdf_bytes, Path(file.filename).name)
    await log_event(
        event="doc_uploaded",
        source="backend",
        session_id=resp.session_id,
        revision=1,
        stage="upload",
        user_hash=user_hash,
        payload={
            "is_sample": False,
            "page_count": resp.page_count,
            "detected_format": resp.detected_format,
            "size_kb": round(len(pdf_bytes) / 1024, 1),
        },
    )
    return resp


@router.post("/documents/{session_id}/revisions", response_model=DocumentPreScanResponse)
async def upload_revision(
    session_id: str,
    request: Request,
    file: UploadFile = File(...),
    x_gemini_api_key: str | None = Header(default=None),
    x_beta_code: str | None = Header(default=None),
) -> DocumentPreScanResponse:
    enforce_rate_limit(
        request=request,
        bucket="upload_doc",
        limit=25,
        window_seconds=3600.0,
        detail="Too many document uploads this hour. Please wait a bit before uploading more.",
    )
    user_hash = await enforce_sponsored_access(request=request, x_gemini_api_key=x_gemini_api_key, x_beta_code=x_beta_code)
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only .pdf files are supported.")
    prev = await store.get_revision(session_id)
    if not prev:
        raise HTTPException(status_code=404, detail="Session not found.")

    prev_rev = int(prev["revision"])
    new_rev = prev_rev + 1
    rev_dir = store.revision_dir(session_id, new_rev)
    pdf_bytes = await _read_upload_bounded(file)
    await store.enforce_storage_budget()

    async with _ingest_semaphore:
        try:
            ingested = await asyncio.to_thread(ingest_pdf_sync, pdf_bytes, rev_dir)
        except IngestionError as exc:
            shutil.rmtree(rev_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            shutil.rmtree(rev_dir, ignore_errors=True)
            raise HTTPException(status_code=500, detail=f"Revision ingestion failed: {exc}") from exc

    diff = compute_revision_diff(
        prev["pages"],
        ingested["pages"],  # type: ignore[arg-type]
        from_revision=prev_rev,
        to_revision=new_rev,
    )

    # Preserve Final Read-Through checkmarks on unchanged pages across v1 -> v2!
    prev_reviewed = set(await store.get_reviewed_pages(session_id, prev_rev))
    preserved_reviewed = [
        v2_p for v2_p, v1_p in diff.page_map.items() if v1_p is not None and v1_p in prev_reviewed
    ]

    await store.add_revision(
        session_id=session_id,
        revision=new_rev,
        filename=file.filename,
        pdf_path=ingested["pdf_path"],  # type: ignore[arg-type]
        page_count=int(ingested["page_count"]),
        detected_format=str(ingested["detected_format"]),
        format_confidence=str(ingested["format_confidence"]),
        ghost_deck_mode=str(ingested["ghost_deck_mode"]),
        pages=ingested["pages"],  # type: ignore[arg-type]
        diff=diff,
        preserved_reviewed_pages=preserved_reviewed,
    )
    resp = _build_prescan_response(session_id=session_id, revision=new_rev, filename=file.filename, ingested=ingested, diff=diff)
    await log_event(
        event="revision_uploaded",
        source="backend",
        session_id=session_id,
        revision=new_rev,
        stage="report",
        user_hash=user_hash,
        payload={
            "page_count": resp.page_count,
            "unchanged_pages": len(diff.unchanged_pages),
            "modified_pages": len(diff.modified_pages),
            "inserted_pages": len(diff.inserted_pages),
        },
    )
    return resp


@router.get("/documents/{session_id}/pages/{page_num}/image")
async def get_page_image(
    session_id: str,
    page_num: int,
    revision: int | None = Query(default=None),
    thumb: bool = Query(default=False),
) -> FileResponse:
    rev_data = await store.get_revision(session_id, revision)
    if not rev_data:
        raise HTTPException(status_code=404, detail="Document revision not found.")
    rev = int(rev_data["revision"])
    rev_dir = store.revision_dir(session_id, rev)
    fname = f"thumb_{page_num:03d}.png" if thumb else f"page_{page_num:03d}.png"
    img_path = rev_dir / fname
    if not img_path.exists():
        raise HTTPException(status_code=404, detail=f"Page {page_num} image not found.")
    return FileResponse(path=img_path, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})
