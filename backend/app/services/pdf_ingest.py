"""PyMuPDF PDF ingestion, heading extraction, and content-addressed page-hash diffing."""

from __future__ import annotations

import hashlib
import io
import re
import statistics
from pathlib import Path
from typing import Literal

import pymupdf as fitz
from PIL import Image

from app.config import settings
from app.schemas.document import (
    BBox,
    DocFormat,
    PageArtifact,
    PageFingerprint,
    RevisionDiff,
    TextBlockInfo,
)

PURE_METRIC_RE = re.compile(r"^[\s$€£¥+\-−~<>≤≥]*\d[\d,.\s]*[%KMBTxX]?[\s/a-zA-Z]{0,5}$")


class IngestionError(ValueError):
    """Raised on invalid, encrypted, oversized, or corrupted PDF uploads."""


def _compute_dhash(img: Image.Image, hash_size: int = 16) -> str:
    """Compute a perceptual difference hash (default 16x16 = 256 bits -> 64 hex chars)."""
    gray = img.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.BILINEAR)
    pixels = gray.tobytes()
    bits: list[int] = []
    stride = hash_size + 1
    for row in range(hash_size):
        offset = row * stride
        for col in range(hash_size):
            bits.append(1 if pixels[offset + col] < pixels[offset + col + 1] else 0)
    value = 0
    for b in bits:
        value = (value << 1) | b
    hex_len = (hash_size * hash_size) // 4
    return f"{value:0{hex_len}x}"


def _compute_quadrant_dhashes(img: Image.Image) -> list[str]:
    """Compute 2x2 quadrant 64-bit dHashes to catch localized vector-chart edits."""
    w, h = img.size
    mx, my = w // 2, h // 2
    quads = [
        img.crop((0, 0, mx, my)),
        img.crop((mx, 0, w, my)),
        img.crop((0, my, mx, h)),
        img.crop((mx, my, w, h)),
    ]
    return [_compute_dhash(q, hash_size=8) for q in quads]


def hamming_hex(h1: str, h2: str) -> int:
    if len(h1) != len(h2):
        return 9999
    return (int(h1, 16) ^ int(h2, 16)).bit_count()


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).lower()


def _is_pure_metric_token(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) > 18:
        return False
    return bool(PURE_METRIC_RE.match(stripped))


def _rects_overlap(a: BBox, b: tuple[float, float, float, float]) -> bool:
    return not (a.x1 <= b[0] or a.x0 >= b[2] or a.y1 <= b[1] or a.y0 >= b[3])


def _extract_slide_heading(
    blocks: list[TextBlockInfo], page_w: float, page_h: float
) -> tuple[str, bool]:
    """Extract slide title with Principal Eng fixes:
    - Upper 32% left-aligned block >=14pt, width >=25% of slide, rejecting pure KPI metrics.
    - Falls back to upper 65% for centered/low cover titles.
    """
    candidates = [
        b
        for b in blocks
        if b.bbox.y0 <= page_h * 0.32
        and b.max_font_size >= 14.0
        and (b.bbox.x1 - b.bbox.x0) >= page_w * 0.18
        and not _is_pure_metric_token(b.text)
        and len(b.text.strip()) >= 3
    ]
    if candidates:
        # Prefer top-most large-font left-ish heading (not tiny 9pt kickers, not far-right callouts)
        candidates.sort(key=lambda b: (-round(b.max_font_size, 1), b.bbox.y0, b.bbox.x0))
        top_size = candidates[0].max_font_size
        same_tier = [c for c in candidates if c.max_font_size >= top_size - 1.5]
        same_tier.sort(key=lambda b: (b.bbox.y0, b.bbox.x0))
        title = " ".join(c.text.strip() for c in same_tier[:2]).strip()
        total_words = sum(len(b.text.split()) for b in blocks)
        is_cover = (top_size >= 28.0 and total_words <= 45) or (same_tier[0].bbox.y0 >= page_h * 0.25 and total_words <= 45)
        return title[:220], is_cover

    # Cover / section divider fallback (upper 65%)
    cover_candidates = [
        b
        for b in blocks
        if b.bbox.y0 <= page_h * 0.65
        and b.max_font_size >= 16.0
        and not _is_pure_metric_token(b.text)
        and len(b.text.strip()) >= 3
    ]
    if cover_candidates:
        cover_candidates.sort(key=lambda b: (-round(b.max_font_size, 1), b.bbox.y0))
        top_size = cover_candidates[0].max_font_size
        same_tier = [c for c in cover_candidates if c.max_font_size >= top_size - 2.0]
        same_tier.sort(key=lambda b: b.bbox.y0)
        return " ".join(c.text.strip() for c in same_tier[:2]).strip()[:220], True

    return "", False


def _extract_memo_headings(
    blocks: list[TextBlockInfo],
    table_rects: list[tuple[float, float, float, float]],
    body_median_pt: float,
) -> list[str]:
    """Extract section headings for narrative memos while excluding table headers."""
    headings: list[str] = []
    for b in blocks:
        if any(_rects_overlap(b.bbox, tr) for tr in table_rects):
            continue
        txt = " ".join(b.text.split()).strip()
        if not txt or len(txt) > 180 or len(txt) < 3:
            continue
        words = txt.split()
        is_larger = b.max_font_size >= body_median_pt * 1.12
        is_bold_header = b.is_bold and len(words) <= 18 and not txt.endswith(".")
        if is_larger or is_bold_header:
            headings.append(txt)
    return headings


def ingest_pdf_sync(
    pdf_bytes: bytes,
    out_dir: Path,
    *,
    max_pages: int | None = None,
) -> dict[str, object]:
    """Synchronously parse, render, fingerprint, and detect format for a PDF.

    Intended to run inside asyncio.to_thread().
    """
    max_mb = settings.max_file_size_mb
    if len(pdf_bytes) > max_mb * 1024 * 1024:
        raise IngestionError(f"PDF exceeds maximum allowed size of {max_mb} MB.")

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise IngestionError(f"Unable to open PDF file: {exc}") from exc

    try:
        if doc.is_encrypted:
            raise IngestionError("Encrypted or password-protected PDFs are not supported. Please export an unlocked copy.")
        page_count = doc.page_count
        if page_count == 0:
            raise IngestionError("Uploaded PDF contains 0 pages.")
        limit = max_pages or settings.max_pages
        if page_count > limit:
            raise IngestionError(f"PDF has {page_count} pages (limit is {limit} pages in v1).")

        out_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = out_dir / "source.pdf"
        pdf_path.write_bytes(pdf_bytes)

        ui_dpi = 140 if page_count <= 20 else 110
        llm_max_dim = 1280 if page_count <= 12 else 1024

        aspect_ratios: list[float] = []
        word_counts: list[int] = []
        raw_page_data: list[dict[str, object]] = []
        all_body_font_sizes: list[float] = []

        for idx in range(page_count):
            page = doc[idx]
            pno = idx + 1
            rect = page.rect
            aspect_ratios.append(rect.width / max(rect.height, 1.0))

            # Render UI PNG + thumbnail + LLM-optimized JPEG
            pix = page.get_pixmap(dpi=ui_dpi, alpha=False)
            png_path = out_dir / f"page_{pno:03d}.png"
            pix.save(str(png_path))

            pil_img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            thumb = pil_img.copy()
            thumb.thumbnail((360, 360), Image.Resampling.LANCZOS)
            thumb.save(str(out_dir / f"thumb_{pno:03d}.png"), format="PNG", optimize=True)

            llm_img = pil_img.copy()
            llm_img.thumbnail((llm_max_dim, llm_max_dim), Image.Resampling.LANCZOS)
            llm_img.save(str(out_dir / f"llm_{pno:03d}.jpg"), format="JPEG", quality=82, optimize=True)

            # Extract structured text blocks
            tdict = page.get_text("dict")
            blocks: list[TextBlockInfo] = []
            page_text_parts: list[str] = []
            for blk in tdict.get("blocks", []):
                if blk.get("type") != 0:
                    continue
                lines_text: list[str] = []
                max_size = 0.0
                bold_chars = 0
                total_chars = 0
                for line in blk.get("lines", []):
                    span_texts: list[str] = []
                    for sp in line.get("spans", []):
                        st = sp.get("text", "")
                        if not st.strip():
                            continue
                        span_texts.append(st)
                        sz = float(sp.get("size", 10.0))
                        max_size = max(max_size, sz)
                        n_ch = len(st.strip())
                        total_chars += n_ch
                        if (sp.get("flags", 0) & 16) or ("bold" in sp.get("font", "").lower()):
                            bold_chars += n_ch
                        if n_ch >= 25:
                            all_body_font_sizes.append(sz)
                    if span_texts:
                        lines_text.append("".join(span_texts).strip())
                block_text = " ".join(lines_text).strip()
                if block_text:
                    page_text_parts.append(block_text)
                    bx0, by0, bx1, by1 = blk["bbox"]
                    blocks.append(
                        TextBlockInfo(
                            text=block_text,
                            bbox=BBox(x0=bx0, y0=by0, x1=bx1, y1=by1),
                            max_font_size=round(max_size, 2),
                            is_bold=(total_chars > 0 and (bold_chars / total_chars) >= 0.6),
                        )
                    )

            full_text = "\n".join(page_text_parts).strip()
            wc = len(full_text.split())
            word_counts.append(wc)
            is_scanned = len(full_text) < 15

            # Table rectangles (used to exclude table headers from memo headings)
            table_rects: list[tuple[float, float, float, float]] = []
            try:
                tf = page.find_tables()
                for tbl in tf.tables:
                    table_rects.append(tuple(tbl.bbox))  # type: ignore[arg-type]
            except Exception:
                pass

            # 3-part page fingerprint: normalized text + embedded raster image hashes + 256-bit dHash
            text_hash = hashlib.sha256(_normalize_text(full_text).encode("utf-8")).hexdigest()
            img_hashes: list[bytes] = []
            for img_info in page.get_images(full=True):
                xref = img_info[0]
                try:
                    extracted = doc.extract_image(xref)
                    if extracted and extracted.get("image"):
                        img_hashes.append(hashlib.sha256(extracted["image"]).digest())
                except Exception:
                    continue
            embedded_img_hash = hashlib.sha256(b"".join(sorted(img_hashes))).hexdigest()
            visual_dhash_256 = _compute_dhash(pil_img, hash_size=16)
            quadrant_dhashes = _compute_quadrant_dhashes(pil_img)

            raw_page_data.append(
                {
                    "page_number": pno,
                    "width_pt": round(rect.width, 2),
                    "height_pt": round(rect.height, 2),
                    "word_count": wc,
                    "is_scanned": is_scanned,
                    "extracted_text": full_text,
                    "blocks": blocks,
                    "table_rects": table_rects,
                    "fingerprint": PageFingerprint(
                        page_number=pno,
                        text_hash=text_hash,
                        embedded_img_hash=embedded_img_hash,
                        visual_dhash_256=visual_dhash_256,
                        quadrant_dhashes=quadrant_dhashes,
                    ),
                }
            )

        # Format Auto-Detection
        med_aspect = statistics.median(aspect_ratios)
        med_words = statistics.median(word_counts)
        if med_aspect > 1.15:
            detected_format: DocFormat = "slide_deck"
            format_confidence: Literal["high", "medium", "low"] = "high"
        elif med_words >= 170:
            detected_format = "narrative_memo"
            format_confidence = "high"
        elif med_words >= 90:
            detected_format = "narrative_memo"
            format_confidence = "medium"
        else:
            detected_format = "narrative_memo"
            format_confidence = "low"

        body_median_pt = statistics.median(all_body_font_sizes) if all_body_font_sizes else 10.5

        pages: list[PageArtifact] = []
        empty_heading_count = 0
        for item in raw_page_data:
            blocks = item["blocks"]  # type: ignore[assignment]
            if detected_format == "slide_deck":
                heading, is_cover = _extract_slide_heading(
                    blocks, float(item["width_pt"]), float(item["height_pt"])
                )
            else:
                memo_heads = _extract_memo_headings(blocks, item["table_rects"], body_median_pt)  # type: ignore[arg-type]
                heading = " | ".join(memo_heads[:3]) if memo_heads else ""
                is_cover = False
            if not heading:
                empty_heading_count += 1

            pages.append(
                PageArtifact(
                    page_number=int(item["page_number"]),
                    width_pt=float(item["width_pt"]),
                    height_pt=float(item["height_pt"]),
                    word_count=int(item["word_count"]),
                    is_scanned=bool(item["is_scanned"]),
                    extracted_text=str(item["extracted_text"]),
                    heading=heading,
                    is_cover_or_divider_candidate=is_cover,
                    fingerprint=item["fingerprint"],  # type: ignore[arg-type]
                    text_blocks=blocks,
                )
            )

        ghost_deck_mode: Literal["text", "visual_fallback"] = (
            "visual_fallback" if (page_count >= 2 and empty_heading_count / page_count > 0.35) else "text"
        )

        return {
            "pdf_path": pdf_path,
            "page_count": page_count,
            "detected_format": detected_format,
            "format_confidence": format_confidence,
            "ghost_deck_mode": ghost_deck_mode,
            "pages": pages,
        }
    finally:
        doc.close()


def _fingerprints_match(fp1: PageFingerprint, fp2: PageFingerprint) -> bool:
    if fp1.text_hash != fp2.text_hash:
        return False
    if fp1.embedded_img_hash != fp2.embedded_img_hash:
        return False
    if hamming_hex(fp1.visual_dhash_256, fp2.visual_dhash_256) > 4:
        return False
    if fp1.quadrant_dhashes and fp2.quadrant_dhashes and len(fp1.quadrant_dhashes) == len(fp2.quadrant_dhashes):
        if any(hamming_hex(q1, q2) > 3 for q1, q2 in zip(fp1.quadrant_dhashes, fp2.quadrant_dhashes)):
            return False
    return True


def compute_revision_diff(
    v1_pages: list[PageArtifact],
    v2_pages: list[PageArtifact],
    *,
    from_revision: int,
    to_revision: int,
) -> RevisionDiff:
    """Content-addressed page matching robust to insertions, deletions, and reordering."""
    used_v1: set[int] = set()
    page_map: dict[int, int | None] = {}
    unchanged_pages: list[int] = []
    moved_pages: list[tuple[int, int]] = []

    # Pass 1: exact same-index matches first
    v1_by_no = {p.page_number: p for p in v1_pages}
    for p2 in v2_pages:
        p1 = v1_by_no.get(p2.page_number)
        if p1 and p1.page_number not in used_v1 and _fingerprints_match(p1.fingerprint, p2.fingerprint):
            page_map[p2.page_number] = p1.page_number
            used_v1.add(p1.page_number)
            unchanged_pages.append(p2.page_number)

    # Pass 2: cross-index content-addressed match (handles page insert/delete/reorder)
    for p2 in v2_pages:
        if p2.page_number in page_map:
            continue
        candidates = [
            p1
            for p1 in v1_pages
            if p1.page_number not in used_v1 and _fingerprints_match(p1.fingerprint, p2.fingerprint)
        ]
        if candidates:
            candidates.sort(key=lambda p1: abs(p1.page_number - p2.page_number))
            best = candidates[0]
            page_map[p2.page_number] = best.page_number
            used_v1.add(best.page_number)
            unchanged_pages.append(p2.page_number)
            moved_pages.append((best.page_number, p2.page_number))
        else:
            page_map[p2.page_number] = None

    unmatched_v2 = [p.page_number for p in v2_pages if page_map.get(p.page_number) is None]
    unmatched_v1 = [p.page_number for p in v1_pages if p.page_number not in used_v1]

    # Classify unmatched v2 pages as modified vs inserted (same-index or leftover pairing)
    modified_pages: list[int] = []
    inserted_pages: list[int] = []
    remaining_v1 = set(unmatched_v1)
    for p2_no in unmatched_v2:
        if p2_no in remaining_v1:
            modified_pages.append(p2_no)
            remaining_v1.remove(p2_no)
        elif remaining_v1:
            # Nearest unmatched v1 page represents an edited/replaced slide
            nearest = min(remaining_v1, key=lambda x: abs(x - p2_no))
            modified_pages.append(p2_no)
            remaining_v1.remove(nearest)
        else:
            inserted_pages.append(p2_no)

    deleted_v1_pages = sorted(remaining_v1)

    return RevisionDiff(
        from_revision=from_revision,
        to_revision=to_revision,
        page_map=page_map,
        unchanged_pages=sorted(unchanged_pages),
        modified_pages=sorted(modified_pages),
        inserted_pages=sorted(inserted_pages),
        deleted_v1_pages=deleted_v1_pages,
        moved_pages=sorted(moved_pages),
    )
