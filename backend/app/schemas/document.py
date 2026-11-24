"""Document, page fingerprint, and revision diff schemas."""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field

DocFormat = Literal["slide_deck", "narrative_memo"]
DocPurpose = Literal["decide", "inform", "unblock"]
TargetPersona = Literal["leadership", "cross_org", "custom"]


class BBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float


class TextBlockInfo(BaseModel):
    text: str
    bbox: BBox
    max_font_size: float
    is_bold: bool = False


class PageFingerprint(BaseModel):
    page_number: int
    text_hash: str
    embedded_img_hash: str
    visual_dhash_256: str
    quadrant_dhashes: list[str] = Field(default_factory=list)


class ExtractedHeading(BaseModel):
    page: int
    text: str
    is_cover_or_divider_candidate: bool = False


class PageArtifact(BaseModel):
    page_number: int
    width_pt: float
    height_pt: float
    word_count: int
    is_scanned: bool = False
    extracted_text: str
    heading: str = ""
    is_cover_or_divider_candidate: bool = False
    fingerprint: PageFingerprint
    text_blocks: list[TextBlockInfo] = Field(default_factory=list)


class RevisionDiff(BaseModel):
    from_revision: int
    to_revision: int
    page_map: dict[int, int | None]  # v2_page -> matched v1_page (or None if new/modified)
    unchanged_pages: list[int]
    modified_pages: list[int]
    inserted_pages: list[int]
    deleted_v1_pages: list[int]
    moved_pages: list[tuple[int, int]]  # (v1_page, v2_page)


class DocumentPreScanResponse(BaseModel):
    session_id: str
    revision: int
    filename: str
    page_count: int
    detected_format: DocFormat
    format_confidence: Literal["high", "medium", "low"]
    ghost_deck_mode: Literal["text", "visual_fallback"]
    page_thumbnails: list[str]
    page_titles: list[dict[str, object]]
    revision_diff: RevisionDiff | None = None
    has_live_llm: bool = False


class SampleInfo(BaseModel):
    id: str
    label: str
    category: Literal["sharp", "slop", "hard"]
    filename: str
    relative_path: str
    suggested_format: DocFormat
    suggested_purpose: DocPurpose
    suggested_persona: TargetPersona
    description: str
