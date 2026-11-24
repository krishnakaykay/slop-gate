"""Comprehensive unit and API integration tests for Slop Gate Phase 1."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pymupdf as fitz
import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.main import app
from app.schemas.gate1 import EvidenceQuote, Gate1Issue, IssueCategory, Severity
from app.services.gate1_engine import compute_verdict, validate_and_normalize_issues
from app.services.pdf_ingest import compute_revision_diff, ingest_pdf_sync
from app.services.pdf_stamper import stamp_pdf_sync
from app.services.polish_linters import run_polish_linters
from app.services.session_store import SessionStore, store


EXAMPLES = REPO_ROOT / "examples"


def test_pdf_ingestion_detects_format_and_cover_heading(tmp_path: Path) -> None:
    slop_deck = (EXAMPLES / "slop" / "01_slop_deck_cloud_migration.pdf").read_bytes()
    ing = ingest_pdf_sync(slop_deck, tmp_path / "slop_deck")
    assert ing["detected_format"] == "slide_deck"
    assert ing["page_count"] == 6
    pages = ing["pages"]
    # Cover-slide heading fallback must capture Slide 1 title (located ~37% from top)
    assert "Project Helios" in pages[0].heading
    assert pages[0].is_cover_or_divider_candidate is True

    rfc_memo = (EXAMPLES / "hard" / "02_hard_messy_human_genius_rfc.pdf").read_bytes()
    ing_m = ingest_pdf_sync(rfc_memo, tmp_path / "rfc")
    assert ing_m["detected_format"] == "narrative_memo"
    # Table headers should be excluded from memo headings
    assert "Benchmark Config" not in ing_m["pages"][0].heading


def test_content_addressed_page_diff_survives_page_insert_and_catches_edits(tmp_path: Path) -> None:
    sharp_bytes = (EXAMPLES / "sharp" / "01_sharp_deck_cloud_migration.pdf").read_bytes()
    v1 = ingest_pdf_sync(sharp_bytes, tmp_path / "v1")

    # Build v2 by inserting a brand-new blank/title slide at index 1 (shifting old pages 2..6 -> 3..7)
    doc = fitz.open(stream=sharp_bytes, filetype="pdf")
    new_page = doc.new_page(pno=1, width=doc[0].rect.width, height=doc[0].rect.height)
    new_page.insert_text((72, 120), "Inserted Agenda Slide for Board Review", fontsize=22)
    v2_bytes = doc.tobytes()
    doc.close()

    v2 = ingest_pdf_sync(v2_bytes, tmp_path / "v2")
    diff = compute_revision_diff(v1["pages"], v2["pages"], from_revision=1, to_revision=2)

    assert diff.inserted_pages == [2]
    assert diff.modified_pages == []
    # Page 1 stayed at 1; old pages 2..6 shifted to 3..7 and were recognized as unchanged!
    assert diff.page_map[1] == 1
    assert diff.page_map[3] == 2
    assert diff.page_map[7] == 6
    assert len(diff.unchanged_pages) == 6
    assert (2, 3) in diff.moved_pages


def test_polish_linters_respect_reverse_cohesion_for_leadership(tmp_path: Path) -> None:
    rfc_bytes = (EXAMPLES / "hard" / "02_hard_messy_human_genius_rfc.pdf").read_bytes()
    ing = ingest_pdf_sync(rfc_bytes, tmp_path / "rfc_lint")
    tips = run_polish_linters(ing["pages"], doc_format="narrative_memo", target_persona="leadership")
    flagged_acronyms = {t.snippet for t in tips if t.kind == "unexpanded_acronym"}
    # Standard engineering acronyms must NOT nag Leadership
    for std in ("WAL", "TLS", "SLA", "IOPS", "TPS", "RTT", "LSM", "RFC"):
        assert std not in flagged_acronyms


def test_verdict_state_machine_and_grounding_validator() -> None:
    # Inform-only must hard-strip MISSING_ASK
    raw = [
        Gate1Issue(
            id="x1",
            severity=Severity.CRITICAL,
            category=IssueCategory.MISSING_ASK,
            title="Missing Ask",
            pages=[1, 99],  # 99 is out of bounds
            evidence=[EvidenceQuote(page=1, quote="Summary"), EvidenceQuote(page=42, quote="Bogus")],
            explanation="No ask.",
            suggested_fix="Add ask.",
        )
    ]
    cleaned, dropped = validate_and_normalize_issues(raw, page_count=3, doc_purpose="inform")
    assert cleaned == []
    assert compute_verdict(cleaned) == "READY"

    # Decide mode keeps MISSING_ASK and strips invalid page 99 / 42
    cleaned_dec, dropped_dec = validate_and_normalize_issues(raw, page_count=3, doc_purpose="decide")
    assert len(cleaned_dec) == 1
    assert cleaned_dec[0].pages == [1]
    assert dropped_dec == 2
    assert compute_verdict(cleaned_dec) == "FIX_CRITICAL_ISSUES"

    # Smooth slop (HOLLOW_STRATEGY + 2 total verify) triggers NEEDS_REWORK
    slop_issues = [
        Gate1Issue(id="1", severity=Severity.VERIFY, category=IssueCategory.HOLLOW_STRATEGY, title="Hollow", pages=[1], explanation="x", suggested_fix="y"),
        Gate1Issue(id="2", severity=Severity.VERIFY, category=IssueCategory.UNSUPPORTED_LEAP, title="Leap", pages=[2], explanation="x", suggested_fix="y"),
    ]
    assert compute_verdict(slop_issues) == "NEEDS_REWORK"


def test_luminance_adaptive_stamper_and_durable_metadata(tmp_path: Path) -> None:
    slop_bytes = (EXAMPLES / "slop" / "01_slop_deck_cloud_migration.pdf").read_bytes()
    rev_dir = tmp_path / "rev"
    ing = ingest_pdf_sync(slop_bytes, rev_dir)

    out_pdf = tmp_path / "stamped.pdf"
    res = stamp_pdf_sync(
        source_pdf=ing["pdf_path"],
        output_pdf=out_pdf,
        revision_dir=rev_dir,
        owner_name="Krishna Kumar",
        scope="all",
        status="VERIFIED",
    )

    # Slide 1 has dark navy #0F172A background -> dark adaptive theme; Slide 2 has white -> light theme!
    assert res["placements"][0].theme == "dark"
    assert res["placements"][1].theme == "light"

    # Reopen stamped PDF with fresh fitz.open() to prove custom /Info metadata & text persisted
    reopened = fitz.open(str(out_pdf))
    try:
        kw = reopened.metadata.get("keywords", "")
        assert "ReviewedBy=Krishna Kumar" in kw
        assert "slop" not in kw.lower()

        info_type, info_val = reopened.xref_get_key(-1, "Info")
        assert info_type == "xref"
        info_xref = int(info_val.split()[0])
        _, reviewed_by = reopened.xref_get_key(info_xref, "ReviewedBy")
        _, pf_status = reopened.xref_get_key(info_xref, "PreFlightStatus")
        assert reviewed_by == "Krishna Kumar"
        assert pf_status == "VERIFIED"

        # Visible text must say "Reviewed by Krishna Kumar" and never "Slop"
        p1_text = reopened[0].get_text()
        assert "Reviewed by Krishna Kumar" in p1_text
    finally:
        reopened.close()


@pytest.mark.asyncio
async def test_full_api_flow_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Point global store to an isolated temp dir for this test
    test_store = SessionStore(db_path=tmp_path / "test.db", sessions_dir=tmp_path / "sessions")
    await test_store.init()
    monkeypatch.setattr("app.services.session_store.store", test_store)
    monkeypatch.setattr("app.routers.documents.store", test_store)
    monkeypatch.setattr("app.routers.gate1.store", test_store)
    monkeypatch.setattr("app.routers.stamp.store", test_store)
    # Force local demo mode in test so no live network call is made
    monkeypatch.setattr("app.config.settings.gemini_api_key", "")
    monkeypatch.setattr("app.config.settings.google_api_key", "")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Load 15-slide QBR sample
        r_load = await client.post("/api/documents/sample/hard_15p_qbr")
        assert r_load.status_code == 200
        doc = r_load.json()
        sid = doc["session_id"]
        assert doc["page_count"] == 15
        assert doc["detected_format"] == "slide_deck"

        # 2. Start Gate 1 run (202 Accepted)
        r_run = await client.post(
            f"/api/sessions/{sid}/gate1/runs",
            json={"revision": 1, "doc_format": "slide_deck", "doc_purpose": "decide", "target_persona": "leadership"},
        )
        assert r_run.status_code == 202
        run_info = r_run.json()
        run_id = run_info["run_id"]

        # 3. Consume GET SSE stream
        events_text = ""
        async with client.stream("GET", run_info["events_url"]) as resp:
            assert resp.status_code == 200
            async for chunk in resp.aiter_text():
                events_text += chunk
        assert "event: complete" in events_text

        # 4. Save creator intent & fetch report
        r_int = await client.patch(
            f"/api/sessions/{sid}/gate1/runs/{run_id}/intent",
            json={"creator_intent": "Approve FY27 $50M OpEx plan and 8 AEs."},
        )
        assert r_int.status_code == 200
        report = r_int.json()["report"]
        assert report["verdict"] == "FIX_CRITICAL_ISSUES"
        assert len(report["issues"]) >= 2

        # 5. Critical Intentional requires a reason
        iss0 = report["issues"][0]["id"]
        r_bad = await client.patch(
            f"/api/sessions/{sid}/gate1/runs/{run_id}/issues/{iss0}",
            json={"status": "intentional", "note": "ok"},
        )
        assert r_bad.status_code == 400

        r_ok = await client.patch(
            f"/api/sessions/{sid}/gate1/runs/{run_id}/issues/{iss0}",
            json={"status": "intentional", "note": "Slide 2 shows gross headline; Appendix B reconciles organic."},
        )
        assert r_ok.status_code == 200

        # 6. Stamping blocked until all 15 pages reviewed in Final Read-Through
        r_blk = await client.post(
            f"/api/sessions/{sid}/stamp",
            json={"revision": 1, "owner_name": "Krishna Kumar", "scope": "all", "reviewed_pages": [1, 2]},
        )
        assert r_blk.status_code == 400

        # 7. Complete read-through and stamp!
        r_stamp = await client.post(
            f"/api/sessions/{sid}/stamp",
            json={"revision": 1, "owner_name": "Krishna Kumar", "scope": "all", "reviewed_pages": list(range(1, 16))},
        )
        assert r_stamp.status_code == 200
        st = r_stamp.json()
        assert st["metadata_written"]["ReviewedBy"] == "Krishna Kumar"

        r_dl = await client.get(st["download_url"])
        assert r_dl.status_code == 200
        assert r_dl.headers["content-type"] == "application/pdf"
        assert len(r_dl.content) > 5000
