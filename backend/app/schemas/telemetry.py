"""Pydantic schemas for structured telemetry, error logging, and 1-click user feedback."""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class ClientEventRequest(BaseModel):
    event: str = Field(..., min_length=1, max_length=80)
    severity: Literal["INFO", "WARNING", "ERROR"] = "INFO"
    session_id: str | None = Field(default=None, max_length=64)
    revision: int | None = None
    stage: str | None = Field(default=None, max_length=40)
    payload: dict[str, Any] = Field(default_factory=dict)


class FeedbackRequest(BaseModel):
    feedback_id: int | None = None
    session_id: str | None = Field(default=None, max_length=64)
    revision: int | None = None
    stage: str = Field(default="unknown", max_length=40)
    rating: Literal["up", "down", "note"] = "up"
    tags: list[str] = Field(default_factory=list, max_length=10)
    comment: str = Field(default="", max_length=2000)
    context: dict[str, Any] = Field(default_factory=dict)


class FeedbackResponse(BaseModel):
    ok: bool = True
    feedback_id: int
    rating: str


class BetaVerifyRequest(BaseModel):
    code: str = Field(default="", max_length=128)
