"""Owner accountability stamp & Final Read-Through schemas."""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class ReadThroughUpdateRequest(BaseModel):
    revision: int
    reviewed_pages: list[int]


class StampRequest(BaseModel):
    revision: int
    owner_name: str = Field(..., min_length=1, max_length=80)
    scope: Literal["all", "cover"] = "all"
    reviewed_pages: list[int] = Field(default_factory=list)
    enforce_all_reviewed: bool = True


class PageStampPlacement(BaseModel):
    page: int
    stamped: bool
    corner: str | None = None
    theme: Literal["light", "dark"] | None = None


class StampResponse(BaseModel):
    session_id: str
    revision: int
    owner_name: str
    scope: Literal["all", "cover"]
    download_url: str
    filename: str
    preferred_corner: str
    placements: list[PageStampPlacement]
    metadata_written: dict[str, str]
