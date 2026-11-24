"""Unit and end-to-end integration tests for Phase 2 (Gate 2: Meeting Q&A Prep)."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pymupdf as fitz
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.main import app
from app.services.gate2_engine import is_generic_limitation, is_verbatim_retype
from app.services.session_store import SessionStore

EXAMPLES = REPO_ROOT / "examples"


def test_smart_verbatim_retype_guard() -> None:
    source = [
        "All eight enterprise account executive hires are funded via reallocation from paused small business paid search spend resulting in zero incremental operating expense."
    ]
    # Exact contiguous copy of >=7 content words must trigger
    copied = "enterprise account executive hires funded via reallocation from paused small business paid search spend"
    assert is_verbatim_retype(copied, source) is True

    # Short technical terms, numbers, and genuine synthesis in own words must NOT trigger
    own_words = "We pause after 4 AEs if Q2 pipeline coverage drops under 3.0x, keeping FY27 runway above 6 years."
    assert is_verbatim_retype(own_words, source) is False


def test_generic_limitation_guard() -> None:
    assert is_generic_limitation("Looks good") is True
    assert is_generic_limitation("No issues at all, looks solid to me.") is True
    assert is_generic_limitation("Our model assumes 31% co-sell win rate holds at 2x scale; we need a 24% downside table in v2.") is False


@pytest.mark.asyncio
async def test_gate2_full_flow_triage_lock_preservation_and_full_stamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_store = SessionStore(db_path=tmp_path / "g2.db", sessions_dir=tmp_path / "sessions")
    await test_store.init()
    for mod in (
        "app.services.session_store.store",
        "app.routers.documents.store",
        "app.routers.gate1.store",
        "app.routers.gate2.store",
        "app.routers.stamp.store",
    ):
        monkeypatch.setattr(mod, test_store)
    monkeypatch.setattr("app.config.settings.gemini_api_key", "")
    monkeypatch.setattr("app.config.settings.google_api_key", "")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Load 15-slide QBR sample & run Gate 1
        r_load = await client.post("/api/documents/sample/hard_15p_qbr")
        assert r_load.status_code == 200
        sid = r_load.json()["session_id"]

        r_run = await client.post(
            f"/api/sessions/{sid}/gate1/runs",
            json={"revision": 1, "doc_format": "slide_deck", "doc_purpose": "decide", "target_persona": "leadership"},
        )
        assert r_run.status_code == 202
        run_info = r_run.json()
        run_id = run_info["run_id"]
        async with client.stream("GET", run_info["events_url"]) as resp:
            async for _ in resp.aiter_text():
                pass

        # 2. Gate 2 MUST be blocked (400) while non-Polish issues are unresolved!
        r_g2_blk = await client.post(f"/api/sessions/{sid}/gate2/start", json={"revision": 1})
        assert r_g2_blk.status_code == 400

        # 3. Resolve all non-Polish Gate 1 issues (Intentional + Ignore for now)
        rep = (await client.get(f"/api/sessions/{sid}/gate1")).json()
        for idx, iss in enumerate(rep["issues"]):
            payload = (
                {"status": "intentional", "note": "Will reconcile gross vs organic ARR live in the room."}
                if idx == 0
                else {"status": "ignored", "note": "Deferred for now"}
            )
            r_disp = await client.patch(f"/api/sessions/{sid}/gate1/runs/{run_id}/issues/{iss['id']}", json=payload)
            assert r_disp.status_code == 200

        # 4. Start Gate 2 -> receives 3 high-relevance questions + 1 Known Limitations card = 4 total
        r_g2 = await client.post(f"/api/sessions/{sid}/gate2/start", json={"revision": 1})
        assert r_g2.status_code == 200
        g2 = r_g2.json()
        assert g2["total_count"] == 4
        assert g2["all_verified"] is False
        assert g2["questions"][-1]["is_limitation"] is True

        # 5. Test generic limitation nudge & real answer verification across all 4 cards
        lim_id = g2["questions"][-1]["id"]
        r_nudge = await client.post(
            f"/api/sessions/{sid}/gate2/answer",
            json={"revision": 1, "question_id": lim_id, "answer_text": "Looks good, nothing to fix."},
        )
        assert r_nudge.status_code == 200
        assert r_nudge.json()["answers"][lim_id]["status"] == "nudge"

        sample_answers = {
            g2["questions"][0]["id"]: "We pause H2 hiring if Q2 pipeline coverage dips below 3.0x and cap first wave at 4 AEs.",
            g2["questions"][1]["id"]: "I will open with 109% organic NRR and treat the $1.1M pull-forward strictly as renewal timing.",
            g2["questions"][2]["id"]: "Only $600K of DACH ARR is weighted in Q3; North America marketplace co-sell covers a 6-week slip.",
            lim_id: "Our model assumes 31% co-sell win rate holds at double AE headcount; v2 needs a 24% downside case.",
        }
        latest_g2 = None
        for qid, text in sample_answers.items():
            r_ans = await client.post(
                f"/api/sessions/{sid}/gate2/answer",
                json={"revision": 1, "question_id": qid, "answer_text": text},
            )
            assert r_ans.status_code == 200
            latest_g2 = r_ans.json()
            assert latest_g2["answers"][qid]["status"] == "verified"

        assert latest_g2 is not None
        assert latest_g2["all_verified"] is True
        assert "Meeting Q&A Prep Sheet" in latest_g2["prep_sheet_markdown"]
        assert "★ Known Limitation" in latest_g2["prep_sheet_markdown"]

        # 6. Complete Final Read-Through & Stamp -> PreFlightStatus must be VERIFIED_FULL!
        r_stamp = await client.post(
            f"/api/sessions/{sid}/stamp",
            json={"revision": 1, "owner_name": "Krishna Kumar", "scope": "all", "reviewed_pages": list(range(1, 16))},
        )
        assert r_stamp.status_code == 200
        assert r_stamp.json()["metadata_written"]["PreFlightStatus"] == "VERIFIED_FULL"

        # 7. Upload v2 with a NEW slide inserted at index 0 (shifting all pages +1!) ->
        #    Gate 2 must preserve all verified answers on unchanged pages & remap their page numbers!
        orig_bytes = (EXAMPLES / "hard" / "04_hard_15p_exec_deck_appendix_contradiction.pdf").read_bytes()
        pdf = fitz.open(stream=orig_bytes, filetype="pdf")
        p0 = pdf.new_page(pno=0, width=pdf[0].rect.width, height=pdf[0].rect.height)
        p0.insert_text((72, 120), "Inserted Title Cover v2", fontsize=24)
        v2_bytes = pdf.tobytes()
        pdf.close()

        r_rev = await client.post(
            f"/api/documents/{sid}/revisions",
            files={"file": ("qbr_v2.pdf", v2_bytes, "application/pdf")},
        )
        assert r_rev.status_code == 200
        assert r_rev.json()["revision"] == 2
        assert len(r_rev.json()["revision_diff"]["unchanged_pages"]) == 15

        r_g2_v2 = await client.post(f"/api/sessions/{sid}/gate2/start", json={"revision": 2})
        assert r_g2_v2.status_code == 200
        g2_v2 = r_g2_v2.json()
        # All 3 non-limitation answers + limitation preserved across the shifted pages!
        assert g2_v2["preserved_count"] >= 3
        # Original Q1 cited pages [6, 13] -> after inserting a cover at index 0, must remap to [7, 14]!
        assert g2_v2["questions"][0]["pages"] == [7, 14]
        assert g2_v2["answers"][g2_v2["questions"][0]["id"]]["preserved_from_revision"] == 1


@pytest.mark.asyncio
async def test_session_store_migrates_legacy_gate2_answers_without_feedback(tmp_path: Path) -> None:
    """Phase 1 DBs lacked gate2_answers.feedback; SessionStore.init() must auto-migrate cleanly."""
    import aiosqlite

    db_path = tmp_path / "legacy_phase1.db"
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(
            """
            CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                latest_revision INTEGER NOT NULL DEFAULT 1,
                active_run_count INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                last_accessed_at REAL NOT NULL
            );
            CREATE TABLE gate2_answers (
                answer_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                source_revision INTEGER NOT NULL,
                page_fingerprints_json TEXT NOT NULL,
                question_json TEXT NOT NULL,
                answer_text TEXT NOT NULL,
                verified INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL
            );
            INSERT INTO sessions VALUES ('s1', 'doc.pdf', 1, 0, 1.0, 1.0);
            INSERT INTO gate2_answers VALUES ('a1', 's1', 1, '["fp1"]', '{}', 'old answer', 1, 1.0);
            """
        )
        await db.commit()

    store = SessionStore(db_path=db_path, sessions_dir=tmp_path / "sessions")
    await store.init()

    async with aiosqlite.connect(db_path) as db:
        async with db.execute("PRAGMA table_info(gate2_answers)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
        assert "feedback" in cols
        async with db.execute("SELECT answer_text, feedback FROM gate2_answers WHERE answer_id = 'a1'") as cur:
            row = await cur.fetchone()
        assert row == ("old answer", "")

