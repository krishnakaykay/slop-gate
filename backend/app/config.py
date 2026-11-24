"""Application configuration loaded from environment / .env."""

from __future__ import annotations

import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server & storage
    app_name: str = "Slop Gate"
    data_dir: Path = REPO_ROOT / "data"
    examples_dir: Path = REPO_ROOT / "examples"
    frontend_dir: Path = REPO_ROOT / "frontend"
    session_ttl_hours: int = 24
    ttl_sweep_interval_seconds: int = 900  # 15 minutes

    # Ingestion guardrails
    max_file_size_mb: int = 25
    max_pages: int = 40
    max_concurrent_ingests: int = 2

    # LLM provider config (pluggable; defaults to Google Gemini API)
    gemini_api_key: str = ""
    google_api_key: str = ""
    llm_model_fast: str = "gemini-3-flash-preview"
    llm_model_reasoning: str = "gemini-3.1-pro-preview"
    llm_timeout_seconds: int = 120
    llm_inline_max_bytes: int = 15 * 1024 * 1024  # 15 MB guard (Gemini inline limit is 20 MB)

    # Sponsored public-beta guardrails & telemetry (Cloud Run ready)
    slop_beta_code: str = ""              # Optional invite code; empty = open access
    slop_daily_run_limit_per_ip: int = 15 # Max sponsored live runs / 24h per IP (0 = unlimited; BYOK bypasses)
    slop_admin_token: str = ""            # Required to read GET /api/admin/telemetry
    slop_log_salt: str = "slop-gate-beta-v1"
    slop_json_logs: bool = True           # Emit Cloud Logging-compatible JSON lines to stdout

    @property
    def effective_gemini_key(self) -> str:
        return (self.gemini_api_key or self.google_api_key or os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")).strip()

    @property
    def db_path(self) -> Path:
        return self.data_dir / "slop_gate.db"

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"


settings = Settings()
