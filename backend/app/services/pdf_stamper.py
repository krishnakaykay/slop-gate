"""Luminance-adaptive, collision-aware Owner Accountability PDF stamper.

Implements all Principal UX + Principal Engineering fixes:
- Zero mention of the word "Slop" in visible badge or PDF metadata.
- Calls page.wrap_contents() for CTM / rotation safety.
- Computes a document-wide preferred corner (clear on >=80% of pages) to avoid corner-jumping.
- Tucks compact 13pt badge cleanly below standard 25pt slide footers (y1 - 18).
- Samples rendered PNG corner luminance for Frosted-Paper (light) vs Dark-Glass (dark) pill.
- Draws crisp vector checkmark-circle icon (never flaky Unicode glyphs).
- Writes durable metadata to BOTH standard `keywords` AND explicit `/Info` xref keys.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import pymupdf as fitz
from PIL import Image

from app.schemas.stamp import PageStampPlacement


CORNER_ORDER = ["bottom-right", "bottom-left", "bottom-center", "top-right", "top-left"]


def _format_badge_label(owner_name: str) -> str:
    clean = " ".join(owner_name.strip().split())
    if len(clean) > 24:
        clean = clean[:22].rstrip() + "..."
    return f"Reviewed by {clean}"


def _badge_dimensions(label: str) -> tuple[float, float]:
    font_size = 7.2
    text_w = fitz.get_text_length(label, fontname="helv", fontsize=font_size)
    icon_w = 10.5
    pad_x = 7.0
    width = pad_x + icon_w + 3.5 + text_w + pad_x
    height = 13.5
    return width, height


def _slot_rect(page_rect: fitz.Rect, corner: str, bw: float, bh: float) -> fitz.Rect:
    mx = 10.0
    my_bottom = 4.5  # Occupies 4.5pt..18pt from bottom — tucks cleanly under 25pt footers!
    my_top = 6.0
    if corner == "bottom-right":
        return fitz.Rect(page_rect.x1 - bw - mx, page_rect.y1 - bh - my_bottom, page_rect.x1 - mx, page_rect.y1 - my_bottom)
    if corner == "bottom-left":
        return fitz.Rect(page_rect.x0 + mx, page_rect.y1 - bh - my_bottom, page_rect.x0 + mx + bw, page_rect.y1 - my_bottom)
    if corner == "bottom-center":
        cx = (page_rect.x0 + page_rect.x1) / 2.0
        return fitz.Rect(cx - bw / 2.0, page_rect.y1 - bh - my_bottom, cx + bw / 2.0, page_rect.y1 - my_bottom)
    if corner == "top-right":
        return fitz.Rect(page_rect.x1 - bw - mx, page_rect.y0 + my_top, page_rect.x1 - mx, page_rect.y0 + my_top + bh)
    return fitz.Rect(page_rect.x0 + mx, page_rect.y0 + my_top, page_rect.x0 + mx + bw, page_rect.y0 + my_top + bh)


def _page_obstacles(page: fitz.Page) -> list[fitz.Rect]:
    obstacles: list[fitz.Rect] = []
    page_area = max(page.rect.width * page.rect.height, 1.0)
    for blk in page.get_text("blocks"):
        if len(blk) >= 5 and str(blk[4]).strip():
            obstacles.append(fitz.Rect(blk[0], blk[1], blk[2], blk[3]))
    for info in page.get_image_info(xrefs=False):
        bbox = info.get("bbox")
        if bbox:
            r = fitz.Rect(bbox)
            if (r.width * r.height) / page_area < 0.72:
                obstacles.append(r)
    for drw in page.get_drawings():
        r = drw.get("rect")
        if r and (r.width * r.height) / page_area < 0.70 and r.width > 4 and r.height > 4:
            obstacles.append(r)
    return obstacles


def _collides(cand: fitz.Rect, obstacles: list[fitz.Rect], pad: float = 2.0) -> bool:
    padded = fitz.Rect(cand.x0 - pad, cand.y0 - pad, cand.x1 + pad, cand.y1 + pad)
    for obs in obstacles:
        if padded.intersects(obs):
            return True
    return False


def _sample_corner_luminance(png_path: Path | None, page_rect: fitz.Rect, badge_rect: fitz.Rect) -> float:
    """Sample mean pixel luminance (0..255) under the target badge rect from the rendered PNG."""
    if not png_path or not png_path.exists():
        return 245.0
    try:
        with Image.open(png_path) as im:
            gray = im.convert("L")
            sx = gray.width / max(page_rect.width, 1.0)
            sy = gray.height / max(page_rect.height, 1.0)
            x0 = max(0, int((badge_rect.x0 - page_rect.x0) * sx))
            y0 = max(0, int((badge_rect.y0 - page_rect.y0) * sy))
            x1 = min(gray.width, max(x0 + 1, int((badge_rect.x1 - page_rect.x0) * sx)))
            y1 = min(gray.height, max(y0 + 1, int((badge_rect.y1 - page_rect.y0) * sy)))
            crop = gray.crop((x0, y0, x1, y1))
            data = crop.tobytes()
            return sum(data) / max(len(data), 1)
    except Exception:
        return 245.0


def _draw_adaptive_badge(page: fitz.Page, rect: fitz.Rect, label: str, is_dark: bool) -> None:
    """Draw a crisp vector pill + checkmark-circle + Helvetica label."""
    shape = page.new_shape()
    if is_dark:
        fill_col = (15 / 255, 23 / 255, 42 / 255)      # Dark-glass slate #0F172A
        fill_op = 0.72
        stroke_col = (1.0, 1.0, 1.0)
        stroke_op = 0.28
        ink_col = (226 / 255, 232 / 255, 240 / 255)    # Crisp light #E2E8F0
    else:
        fill_col = (1.0, 1.0, 1.0)                     # Frosted-paper white
        fill_op = 0.86
        stroke_col = (203 / 255, 213 / 255, 225 / 255) # Hairline #CBD5E1
        stroke_op = 0.85
        ink_col = (71 / 255, 85 / 255, 105 / 255)      # Muted slate #475569

    # Rounded pill background
    radius = 0.48
    shape.draw_rect(rect)
    shape.finish(
        color=stroke_col,
        fill=fill_col,
        width=0.55,
        fill_opacity=fill_op,
        stroke_opacity=stroke_op,
    )

    # Vector checkmark circle on the left of the pill
    cx = rect.x0 + 9.5
    cy = (rect.y0 + rect.y1) / 2.0
    r = 3.8
    shape.draw_circle(fitz.Point(cx, cy), r)
    shape.finish(color=ink_col, width=0.85, stroke_opacity=0.9)

    p1 = fitz.Point(cx - 1.9, cy + 0.1)
    p2 = fitz.Point(cx - 0.5, cy + 1.6)
    p3 = fitz.Point(cx + 2.1, cy - 1.5)
    shape.draw_polyline([p1, p2, p3])
    shape.finish(color=ink_col, width=0.95, lineCap=1, lineJoin=1, stroke_opacity=0.95)
    shape.commit(overlay=True)

    # Label text
    font_size = 7.2
    tx = rect.x0 + 16.5
    ty = rect.y0 + (rect.height + font_size * 0.72) / 2.0
    page.insert_text(
        fitz.Point(tx, ty),
        label,
        fontname="helv",
        fontsize=font_size,
        color=ink_col,
        overlay=True,
    )


def _write_durable_metadata(
    doc: fitz.Document,
    *,
    owner_name: str,
    status: str,
    doc_format: str,
    doc_purpose: str,
    target_persona: str,
    verified_at: str,
) -> dict[str, str]:
    existing = doc.metadata or {}
    existing_kw = (existing.get("keywords") or "").strip()
    tag = f"PreFlightVerified; ReviewedBy={owner_name}; Status={status}; VerifiedAt={verified_at}"
    new_kw = f"{existing_kw}; {tag}" if existing_kw else tag
    existing["keywords"] = new_kw
    doc.set_metadata(existing)

    # Explicitly write custom /Info xref keys (PyMuPDF's set_metadata ignores custom keys!)
    info_type, info_val = doc.xref_get_key(-1, "Info")
    info_xref: int | None = None
    if info_type == "xref":
        try:
            info_xref = int(info_val.split()[0])
        except Exception:
            info_xref = None
    if info_xref is None:
        info_xref = doc.get_new_xref()
        doc.update_object(info_xref, "<<>>")
        doc.xref_set_key(-1, "Info", f"{info_xref} 0 R")

    custom_fields = {
        "ReviewedBy": owner_name,
        "PreFlightStatus": status,
        "DocumentFormat": doc_format,
        "DocumentPurpose": doc_purpose,
        "TargetPersona": target_persona,
        "VerifiedAt": verified_at,
    }
    for k, v in custom_fields.items():
        doc.xref_set_key(info_xref, k, fitz.get_pdf_str(v))

    return custom_fields


def stamp_pdf_sync(
    *,
    source_pdf: Path,
    output_pdf: Path,
    revision_dir: Path,
    owner_name: str,
    scope: Literal["all", "cover"] = "all",
    status: str = "VERIFIED",
    doc_format: str = "slide_deck",
    doc_purpose: str = "decide",
    target_persona: str = "leadership",
) -> dict[str, object]:
    """Stamp PDF with luminance-adaptive Owner Accountability Badge + durable metadata."""
    label = _format_badge_label(owner_name)
    bw, bh = _badge_dimensions(label)
    verified_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    doc = fitz.open(str(source_pdf))
    try:
        page_count = doc.page_count
        target_indices = [0] if scope == "cover" else list(range(page_count))

        # Step 1: Compute obstacles per target page & pick a document-wide preferred corner
        obstacles_by_idx: dict[int, list[fitz.Rect]] = {}
        clear_counts = {c: 0 for c in CORNER_ORDER}
        for idx in target_indices:
            page = doc[idx]
            obs = _page_obstacles(page)
            obstacles_by_idx[idx] = obs
            for corner in CORNER_ORDER:
                if not _collides(_slot_rect(page.rect, corner, bw, bh), obs):
                    clear_counts[corner] += 1

        preferred_corner = CORNER_ORDER[0]
        threshold = max(1, int(len(target_indices) * 0.8))
        for corner in CORNER_ORDER:
            if clear_counts[corner] >= threshold:
                preferred_corner = corner
                break
        else:
            preferred_corner = max(CORNER_ORDER, key=lambda c: clear_counts[c])

        # Step 2: Stamp each target page cleanly
        placements: list[PageStampPlacement] = []
        for idx in range(page_count):
            pno = idx + 1
            if idx not in target_indices:
                placements.append(PageStampPlacement(page=pno, stamped=False))
                continue

            page = doc[idx]
            # Isolate dirty CTM / unbalanced q/Q operators before drawing!
            page.wrap_contents()
            obs = obstacles_by_idx[idx]

            chosen_corner = preferred_corner
            chosen_rect = _slot_rect(page.rect, chosen_corner, bw, bh)
            if _collides(chosen_rect, obs):
                for alt in CORNER_ORDER:
                    alt_rect = _slot_rect(page.rect, alt, bw, bh)
                    if not _collides(alt_rect, obs):
                        chosen_corner = alt
                        chosen_rect = alt_rect
                        break

            png_path = revision_dir / f"page_{pno:03d}.png"
            lum = _sample_corner_luminance(png_path, page.rect, chosen_rect)
            is_dark = lum < 128.0
            _draw_adaptive_badge(page, chosen_rect, label, is_dark=is_dark)

            placements.append(
                PageStampPlacement(
                    page=pno,
                    stamped=True,
                    corner=chosen_corner,
                    theme="dark" if is_dark else "light",
                )
            )

        meta_written = _write_durable_metadata(
            doc,
            owner_name=owner_name.strip(),
            status=status,
            doc_format=doc_format,
            doc_purpose=doc_purpose,
            target_persona=target_persona,
            verified_at=verified_at,
        )

        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = output_pdf.with_suffix(".pdf.tmp")
        doc.save(str(tmp_path), garbage=3, deflate=True)
        tmp_path.replace(output_pdf)

        return {
            "preferred_corner": preferred_corner,
            "placements": placements,
            "metadata_written": meta_written,
        }
    finally:
        doc.close()
