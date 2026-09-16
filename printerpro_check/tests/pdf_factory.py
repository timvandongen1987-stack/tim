"""Helpers to synthesize test PDFs with controlled trim/bleed size, image
DPI and font embedding, for exercising the checker without needing real
printerpro.nl sample files."""
from __future__ import annotations

import io
from pathlib import Path

import fitz
from PIL import Image

DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
MM_TO_PT = 72.0 / 25.4


def make_pdf(
    path: Path,
    trim_w_mm: float,
    trim_h_mm: float,
    bleed_mm: float = 0,
    dpi: int = 300,
    embed_font: bool = True,
    n_pages: int = 1,
) -> Path:
    trim_w_pt = trim_w_mm * MM_TO_PT
    trim_h_pt = trim_h_mm * MM_TO_PT
    bleed_pt = bleed_mm * MM_TO_PT
    page_w = trim_w_pt + 2 * bleed_pt
    page_h = trim_h_pt + 2 * bleed_pt

    doc = fitz.open()
    for _ in range(n_pages):
        page = doc.new_page(width=page_w, height=page_h)
        page.set_mediabox(page.rect)
        if bleed_mm > 0:
            page.set_trimbox(fitz.Rect(bleed_pt, bleed_pt, page_w - bleed_pt, page_h - bleed_pt))
            page.set_bleedbox(page.rect)
        else:
            page.set_trimbox(page.rect)
            page.set_bleedbox(page.rect)

        img_w_px = max(1, round(page_w / 72.0 * dpi))
        img_h_px = max(1, round(page_h / 72.0 * dpi))
        img = Image.new("RGB", (img_w_px, img_h_px), (180, 60, 60))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        page.insert_image(page.rect, stream=buf.getvalue())

        if embed_font:
            page.insert_text(
                (bleed_pt + 5, bleed_pt + 20), "Test tekst", fontfile=DEJAVU, fontname="F0", fontsize=10
            )
        else:
            page.insert_text((bleed_pt + 5, bleed_pt + 20), "Test tekst", fontname="helv", fontsize=10)

    doc.save(path)
    doc.close()
    return path


def make_order_xml(
    path: Path,
    product_name: str,
    width_mm: float,
    height_mm: float,
    filename_hint: str,
    sides: int = 1,
    quantity: int = 10,
    order_id: str = "PP-TEST-1",
) -> Path:
    xml = f"""<order>
  <ordernummer>{order_id}</ordernummer>
  <item>
    <productnaam>{product_name}</productnaam>
    <breedte>{width_mm}</breedte>
    <hoogte>{height_mm}</hoogte>
    <zijdig>{sides}</zijdig>
    <aantal>{quantity}</aantal>
    <bestandsnaam>{filename_hint}</bestandsnaam>
  </item>
</order>
"""
    path.write_text(xml, encoding="utf-8")
    return path
