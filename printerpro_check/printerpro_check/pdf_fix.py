"""Best-effort automatic fixes for common printerpro.nl delivery issues.

These fixes are deliberately conservative:
  - Never overwrite the original file; always write a new "_corrected.pdf".
  - Never silently distort content: if trim size can't be matched without
    changing the aspect ratio beyond a small tolerance, we skip the resize
    and flag it for manual review instead of stretching the artwork.
  - Bleed is added by rasterizing the page and mirroring a thin strip of
    the edge pixels outward (a standard "mirror bleed" technique). This
    loses vector sharpness/searchable text on the affected page, which is
    noted in the report -- for critical jobs, extending bleed by hand in
    the design file is still preferable.
  - Low image DPI is never upscaled (upscaling fabricates detail rather
    than fixing the problem); it is only ever reported.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

MM_TO_PT = 72.0 / 25.4
ASPECT_TOLERANCE = 0.01  # 1% relative difference in W/H ratio is still "matches"
SIZE_TOLERANCE_MM = 0.5  # differences smaller than this are not worth fixing


@dataclass
class FixResult:
    applied: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    output_path: Path | None = None


def _mirror_pad(img: Image.Image, pad: int) -> Image.Image:
    """Extend `img` by `pad` pixels on every edge, mirroring the border
    pixels outward so the extension blends with the artwork."""
    if pad <= 0:
        return img
    w, h = img.size
    pad = min(pad, w - 1, h - 1) if min(w, h) > 1 else 0
    new = Image.new(img.mode, (w + 2 * pad, h + 2 * pad))
    new.paste(img, (pad, pad))
    if pad == 0:
        return new
    left = img.crop((0, 0, pad, h)).transpose(Image.FLIP_LEFT_RIGHT)
    right = img.crop((w - pad, 0, w, h)).transpose(Image.FLIP_LEFT_RIGHT)
    new.paste(left, (0, pad))
    new.paste(right, (w + pad, pad))
    top = img.crop((0, 0, w, pad)).transpose(Image.FLIP_TOP_BOTTOM)
    bottom = img.crop((0, h - pad, w, h)).transpose(Image.FLIP_TOP_BOTTOM)
    new.paste(top, (pad, 0))
    new.paste(bottom, (pad, h + pad))
    tl = img.crop((0, 0, pad, pad)).transpose(Image.ROTATE_180)
    tr = img.crop((w - pad, 0, w, pad)).transpose(Image.ROTATE_180)
    bl = img.crop((0, h - pad, pad, h)).transpose(Image.ROTATE_180)
    br = img.crop((w - pad, h - pad, w, h)).transpose(Image.ROTATE_180)
    new.paste(tl, (0, 0))
    new.paste(tr, (w + pad, 0))
    new.paste(bl, (0, h + pad))
    new.paste(br, (w + pad, h + pad))
    return new


def scale_page_to_trim(
    src_doc: fitz.Document, page_index: int, target_w_mm: float, target_h_mm: float
) -> tuple[fitz.Document | None, str | None]:
    """Vector-preserving scale of one page into a new single-page document
    whose TrimBox/MediaBox exactly match the target size.

    Returns (new_doc, None) on success, or (None, reason) if the aspect
    ratio differs too much to resize without distorting the artwork.
    """
    src_page = src_doc[page_index]
    trim = src_page.trimbox
    src_w = trim.width
    src_h = trim.height
    target_w_pt = target_w_mm * MM_TO_PT
    target_h_pt = target_h_mm * MM_TO_PT

    if src_w <= 0 or src_h <= 0:
        return None, "bronpagina heeft ongeldige afmetingen"

    src_ratio = src_w / src_h
    target_ratio = target_w_pt / target_h_pt
    if abs(src_ratio - target_ratio) / target_ratio > ASPECT_TOLERANCE:
        return None, (
            f"beeldverhouding wijkt te veel af ({src_ratio:.3f} vs "
            f"{target_ratio:.3f}); schalen zou het ontwerp vervormen"
        )

    new_doc = fitz.open()
    new_page = new_doc.new_page(width=target_w_pt, height=target_h_pt)
    # place the source page's trimbox area, scaled to fill the target page
    new_page.show_pdf_page(new_page.rect, src_doc, page_index, clip=trim)
    new_page.set_mediabox(new_page.rect)
    new_page.set_trimbox(new_page.rect)
    return new_doc, None


def add_bleed_to_doc(
    doc: fitz.Document, bleed_mm: float, target_dpi: int = 300, max_px: int = 6000
) -> fitz.Document:
    """Rasterize every page and mirror-pad it by `bleed_mm`, returning a new
    document with correct MediaBox/TrimBox/BleedBox set."""
    out = fitz.open()
    for i in range(doc.page_count):
        page = doc[i]
        trim = page.trimbox
        w_pt, h_pt = trim.width, trim.height

        zoom = target_dpi / 72.0
        if max(w_pt, h_pt) * zoom > max_px:
            zoom = max_px / max(w_pt, h_pt)
        actual_dpi = zoom * 72.0

        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=trim)
        mode = "RGB" if pix.n < 4 else "CMYK"
        img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)

        pad_px = round(bleed_mm / 25.4 * actual_dpi)
        padded = _mirror_pad(img, pad_px)

        out_w_pt = w_pt + 2 * bleed_mm * MM_TO_PT
        out_h_pt = h_pt + 2 * bleed_mm * MM_TO_PT
        new_page = out.new_page(width=out_w_pt, height=out_h_pt)

        import io

        buf = io.BytesIO()
        padded.save(buf, format="PNG")
        new_page.insert_image(new_page.rect, stream=buf.getvalue())

        bleed_pt = bleed_mm * MM_TO_PT
        trimbox = fitz.Rect(bleed_pt, bleed_pt, out_w_pt - bleed_pt, out_h_pt - bleed_pt)
        new_page.set_mediabox(new_page.rect)
        new_page.set_trimbox(trimbox)
        new_page.set_bleedbox(new_page.rect)
    return out


def _page_is_blank(page: fitz.Page) -> bool:
    if page.get_text().strip():
        return False
    if page.get_images():
        return False
    if page.get_drawings():
        return False
    return True


def fix_page_count(doc: fitz.Document, target_pages: int) -> tuple[fitz.Document, list]:
    """Append blank pages (matching the last page's size) or drop trailing
    blank pages so the document has exactly `target_pages` pages. Returns
    (doc, notes). Never removes a page that has content."""
    notes = []
    current = doc.page_count
    if current == target_pages:
        return doc, notes

    if current < target_pages:
        last = doc[current - 1]
        # Capture plain Rects (not the Page object) -- new_page() can
        # invalidate previously obtained Page proxies on the same doc.
        mediabox = fitz.Rect(last.mediabox)
        trimbox = fitz.Rect(last.trimbox)
        bleedbox = fitz.Rect(last.bleedbox)
        w, h = mediabox.width, mediabox.height
        for _ in range(target_pages - current):
            new_page = doc.new_page(width=w, height=h)
            new_page.set_mediabox(mediabox)
            new_page.set_trimbox(trimbox)
            new_page.set_bleedbox(bleedbox)
        notes.append(f"{target_pages - current} lege pagina('s) toegevoegd aan het einde.")
    else:
        removed = 0
        while doc.page_count > target_pages and doc.page_count > 0:
            last_idx = doc.page_count - 1
            if _page_is_blank(doc[last_idx]):
                doc.delete_page(last_idx)
                removed += 1
            else:
                break
        if removed:
            notes.append(f"{removed} lege pagina('s) aan het eind verwijderd.")
        if doc.page_count != target_pages:
            notes.append(
                f"Kon paginaaantal niet automatisch op {target_pages} brengen "
                f"zonder pagina's met inhoud te verwijderen (nu {doc.page_count})."
            )
    return doc, notes


def apply_fixes(
    src_path: Path,
    output_path: Path,
    target_trim_mm: tuple | None,
    bleed_mm: float,
    target_pages: int | None,
    fix_bleed: bool,
    fix_size: bool,
    fix_page_count_flag: bool,
) -> FixResult:
    result = FixResult()
    doc = fitz.open(src_path)

    if fix_size and target_trim_mm:
        target_w_mm, target_h_mm = target_trim_mm
        pages_out = fitz.open()
        any_scaled = False
        for i in range(doc.page_count):
            trim_w_mm = doc[i].trimbox.width * 25.4 / 72.0
            trim_h_mm = doc[i].trimbox.height * 25.4 / 72.0
            needs = (
                abs(trim_w_mm - target_w_mm) > SIZE_TOLERANCE_MM
                or abs(trim_h_mm - target_h_mm) > SIZE_TOLERANCE_MM
            )
            if not needs:
                pages_out.insert_pdf(doc, from_page=i, to_page=i)
                continue
            scaled, reason = scale_page_to_trim(doc, i, target_w_mm, target_h_mm)
            if scaled is None:
                result.skipped.append(f"pagina {i + 1}: formaat niet aangepast ({reason})")
                pages_out.insert_pdf(doc, from_page=i, to_page=i)
            else:
                pages_out.insert_pdf(scaled, from_page=0, to_page=0)
                any_scaled = True
                scaled.close()
        if any_scaled:
            result.applied.append(f"Paginaformaat aangepast naar {target_w_mm}x{target_h_mm} mm.")
        doc.close()
        doc = pages_out

    if fix_page_count_flag and target_pages:
        doc, notes = fix_page_count(doc, target_pages)
        result.applied.extend(notes)

    if fix_bleed:
        pages_needing_bleed = []
        for i in range(doc.page_count):
            page = doc[i]
            trim = page.trimbox
            bleedbox = page.bleedbox
            margin = min(
                trim.x0 - bleedbox.x0,
                trim.y0 - bleedbox.y0,
                bleedbox.x1 - trim.x1,
                bleedbox.y1 - trim.y1,
            )
            if margin < bleed_mm * MM_TO_PT - 0.5:
                pages_needing_bleed.append(i)
        if pages_needing_bleed:
            fixed = add_bleed_to_doc(doc, bleed_mm)
            doc.close()
            doc = fixed
            result.applied.append(
                f"Bleed/afloop van {bleed_mm} mm toegevoegd op basis van gespiegelde "
                f"randpixels (pagina's {[i + 1 for i in pages_needing_bleed]}); "
                "LET OP: deze pagina's zijn hierdoor volledig gerasterd -- tekst is niet "
                "meer doorzoekbaar/bewerkbaar en fonts zijn niet meer relevant (alles is nu "
                "beeldmateriaal). Voor kritieke opdrachten is handmatig afloop toevoegen in "
                "het ontwerpbestand voorkeur boven deze automatische correctie."
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_path)
    doc.close()
    result.output_path = output_path
    return result
