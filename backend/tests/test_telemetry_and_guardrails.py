"""Tests for 1-click feedback capture, behavioral/error telemetry, and sponsored beta guardrails."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.main import app
from app.services.session_store import SessionStore


@pytest.mark.asyncio
async def test_feedback_capture_telemetry_and_admin_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_store = SessionStore(db_path=tmp_path / "tel.db", sessions_dir=tmp_path / "sessions")
    await test_store.init()
    monkeypatch.setattr("app.services.session_store.store", test_store)
    monkeypatch.setattr("app.config.settings.slop_admin_token", "secret-admin-123")
    monkeypatch.setattr("app.config.settings.slop_json_logs", False)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. 1-click thumbs-up submits immediately
        r1 = await client.post(
            "/api/feedback",
            json={
                "session_id": "sess_abc",
                "revision": 1,
                "stage": "report",
                "rating": "up",
                "context": {"doc_format": "slide_deck", "page_count": 6},
            },
        )
        assert r1.status_code == 200
        fb_id = r1.json()["feedback_id"]
        assert fb_id > 0

        # 2. Follow-up tags + comment updates the same feedback row cleanly (no duplicate)
        r2 = await client.post(
            "/api/feedback",
            json={
                "feedback_id": fb_id,
                "session_id": "sess_abc",
                "revision": 1,
                "stage": "report",
                "rating": "up",
                "tags": ["Spot-on catch"],
                "comment": "Caught the OpEx clash immediately!",
            },
        )
        assert r2.status_code == 200
        assert r2.json()["feedback_id"] == fb_id

        # 3. Client behavioral event & client JS error
        r_ev = await client.post(
            "/api/telemetry/event",
            json={"event": "tab_switched", "stage": "report", "payload": {"tab": "mirror"}},
        )
        assert r_ev.status_code == 200
        r_err = await client.post(
            "/api/telemetry/event",
            json={"event": "client_js_error", "severity": "ERROR", "stage": "prep", "payload": {"message": "Boom"}},
        )
        assert r_err.status_code == 200

        # 4. Admin summary rejects wrong token and succeeds with right token
        assert (await client.get("/api/admin/telemetry")).status_code == 403
        r_adm = await client.get("/api/admin/telemetry", headers={"X-Admin-Token": "secret-admin-123"})
        assert r_adm.status_code == 200
        summary = r_adm.json()
        assert summary["feedback_count"] == 1
        assert summary["feedback"][0]["comment"] == "Caught the OpEx clash immediately!"
        assert summary["feedback"][0]["tags"] == ["Spot-on catch"]
        assert summary["event_counts"]["tab_switched"] == 1
        assert any(e["event"] == "client_js_error" for e in summary["recent_errors"])


@pytest.mark.asyncio
async def test_beta_code_and_daily_sponsored_quota_guardrails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_store = SessionStore(db_path=tmp_path / "beta.db", sessions_dir=tmp_path / "sessions")
    await test_store.init()
    for mod in (
        "app.services.session_store.store",
        "app.routers.documents.store",
        "app.routers.gate1.store",
    ):
        monkeypatch.setattr(mod, test_store)
    monkeypatch.setattr("app.config.settings.slop_beta_code", "invite-42")
    monkeypatch.setattr("app.config.settings.slop_daily_run_limit_per_ip", 1)
    monkeypatch.setattr("app.config.settings.gemini_api_key", "fake-sponsored-key")
    monkeypatch.setattr("app.config.settings.slop_json_logs", False)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Health advertises beta_code_required=True
        h = (await client.get("/api/health")).json()
        assert h["beta_code_required"] is True

        # Without beta code -> 401
        r_denied = await client.post("/api/documents/sample/sharp_memo_copilot")
        assert r_denied.status_code == 401

        # Wrong beta code -> 401
        assert (await client.post("/api/beta/verify", json={"code": "wrong"})).status_code == 401
        assert (await client.post("/api/beta/verify", json={"code": "invite-42"})).status_code == 200

        # Valid beta code -> loads sample cleanly
        r_ok = await client.post(
            "/api/documents/sample/sharp_memo_copilot",
            headers={"X-Beta-Code": "invite-42"},
        )
        assert r_ok.status_code == 200
        sid = r_ok.json()["session_id"]

        # Simulate 1 prior sponsored run within 24h -> second sponsored run hits HTTP 429
        from app.services.telemetry import extract_user_hash
        # Compute hash matching httpx AsyncClient default client host ("127.0.0.1")
        import hashlib
        from app.config import settings
        uh = hashlib.sha256(f"{settings.slop_log_salt}:127.0.0.1".encode()).hexdigest()[:12]
        await test_store.record_telemetry_event(
            severity="INFO",
            event="gate1_started_sponsored",
            source="backend",
            user_hash=uh,
        )

        r_quota = await client.post(
            f"/api/sessions/{sid}/gate1/runs",
            headers={"X-Beta-Code": "invite-42"},
            json={"revision": 1, "doc_format": "narrative_memo", "doc_purpose": "decide", "target_persona": "leadership"},
        )
        assert r_quota.status_code == 429


@pytest.mark.asyncio
async def test_security_headers_pdf_magic_gate2_bypass_and_global_usd_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.telemetry import rate_limiter

    rate_limiter.reset()
    test_store = SessionStore(db_path=tmp_path / "sec.db", sessions_dir=tmp_path / "sessions")
    await test_store.init()
    for mod in (
        "app.services.session_store.store",
        "app.routers.documents.store",
        "app.routers.gate1.store",
        "app.routers.gate2.store",
    ):
        monkeypatch.setattr(mod, test_store)
    monkeypatch.setattr("app.config.settings.slop_beta_code", "")
    monkeypatch.setattr("app.config.settings.gemini_api_key", "fake-sponsored-key")
    monkeypatch.setattr("app.config.settings.slop_global_daily_usd_cap", 0.50)
    monkeypatch.setattr("app.config.settings.slop_daily_run_limit_per_ip", 10)
    monkeypatch.setattr("app.config.settings.slop_json_logs", False)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Security headers present & /docs disabled by default
        r_idx = await client.get("/")
        assert r_idx.status_code == 200
        assert r_idx.headers["x-content-type-options"] == "nosniff"
        assert r_idx.headers["x-frame-options"] == "DENY"
        assert "default-src 'self'" in r_idx.headers["content-security-policy"]
        assert "access-control-allow-origin" not in r_idx.headers
        assert (await client.get("/docs")).status_code == 404
        assert (await client.get("/openapi.json")).status_code == 404

        # 2. /api/models without BYOK returns server_defaults without calling Gemini
        r_mod = await client.get("/api/models")
        assert r_mod.status_code == 200
        assert r_mod.json()["source"] == "server_defaults"

        # 3. Non-PDF disguised with .pdf filename is rejected by %PDF- magic header check
        r_bad = await client.post(
            "/api/documents",
            files={"file": ("evil.pdf", b"<html><script>alert(1)</script></html>", "application/pdf")},
        )
        assert r_bad.status_code == 400

        # 4. Gate 2 cannot bypass Gate 1 when using sponsored key
        r_ok = await client.post("/api/documents/sample/sharp_memo_copilot")
        assert r_ok.status_code == 200
        sid = r_ok.json()["session_id"]
        assert len(sid) == 24  # 96-bit unguessable session id

        r_g2_bypass = await client.post(f"/api/sessions/{sid}/gate2/start", json={"revision": 1})
        assert r_g2_bypass.status_code == 400

        # 5. Global daily USD cap blocks sponsored runs from ANY IP once crossed
        await test_store.record_telemetry_event(
            severity="INFO",
            event="gate1_completed",
            source="backend",
            user_hash="otheruser123",
            payload={"sponsored": True, "est_cost_usd": 0.65},
        )
        r_cap = await client.post(
            f"/api/sessions/{sid}/gate1/runs",
            json={"revision": 1, "doc_format": "narrative_memo", "doc_purpose": "decide", "target_persona": "leadership"},
        )
        assert r_cap.status_code == 429
        assert "budget" in r_cap.json()["detail"].lower()

