"""Inspect a PDF with PyMuPDF and extract the facts needed to check it
against a printerpro.nl ProductSpec: page/trim/bleed size, image DPI,
color mode, embedded fonts, PDF version.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

PT_TO_MM = 25.4 / 72.0


def pt_to_mm(pt: float) -> float:
    return round(pt * PT_TO_MM, 3)


@dataclass
class ImageInfo:
    xref: int
    width_px: int
    height_px: int
    bbox_mm: tuple  # (x0, y0, x1, y1)
    dpi_x: float
    dpi_y: float
    colorspace: str

    @property
    def dpi_min(self) -> float:
        return min(self.dpi_x, self.dpi_y)


@dataclass
class FontInfo:
    basefont: str
    ext: str
    embedded: bool


@dataclass
class PageInfo:
    index: int
    rotation: int
    mediabox_mm: tuple
    cropbox_mm: tuple
    trimbox_mm: tuple
    bleedbox_mm: tuple
    has_explicit_trimbox: bool
    has_explicit_bleedbox: bool
    images: list = field(default_factory=list)
    fonts: list = field(default_factory=list)

    @property
    def trim_width_mm(self) -> float:
        return round(self.trimbox_mm[2] - self.trimbox_mm[0], 3)

    @property
    def trim_height_mm(self) -> float:
        return round(self.trimbox_mm[3] - self.trimbox_mm[1], 3)

    @property
    def bleed_width_mm(self) -> float:
        return round(self.bleedbox_mm[2] - self.bleedbox_mm[0], 3)

    @property
    def bleed_height_mm(self) -> float:
        return round(self.bleedbox_mm[3] - self.bleedbox_mm[1], 3)

    def bleed_margin_mm(self) -> float:
        """Smallest bleed margin present on any of the 4 edges (mm)."""
        left = self.trimbox_mm[0] - self.bleedbox_mm[0]
        bottom = self.trimbox_mm[1] - self.bleedbox_mm[1]
        right = self.bleedbox_mm[2] - self.trimbox_mm[2]
        top = self.bleedbox_mm[3] - self.trimbox_mm[3]
        return round(min(left, bottom, right, top), 3)


@dataclass
class DocInfo:
    path: str
    pdf_version: float | None
    page_count: int
    pages: list = field(default_factory=list)

    def all_fonts_embedded(self) -> bool:
        for page in self.pages:
            for font in page.fonts:
                if not font.embedded:
                    return False
        return True

    def non_embedded_fonts(self) -> list:
        names = set()
        for page in self.pages:
            for font in page.fonts:
                if not font.embedded:
                    names.add(font.basefont)
        return sorted(names)

    def min_image_dpi(self) -> float | None:
        best = None
        for page in self.pages:
            for img in page.images:
                if best is None or img.dpi_min < best:
                    best = img.dpi_min
        return best

    def has_rgb_images(self) -> bool:
        for page in self.pages:
            for img in page.images:
                cs = img.colorspace.upper()
                if "RGB" in cs and "CMYK" not in cs:
                    return True
        return False


_VERSION_RE = re.compile(r"PDF[\s\-]*(\d+\.\d+)")


def _parse_pdf_version(doc: fitz.Document, path: Path) -> float | None:
    meta_fmt = (doc.metadata or {}).get("format", "") or ""
    m = _VERSION_RE.search(meta_fmt)
    if m:
        return float(m.group(1))
    try:
        with open(path, "rb") as fh:
            header = fh.read(16).decode("latin-1", errors="ignore")
        m = _VERSION_RE.search(header)
        if m:
            return float(m.group(1))
    except OSError:
        pass
    return None


def inspect_pdf(path: Path | str) -> DocInfo:
    path = Path(path)
    doc = fitz.open(path)
    pdf_version = _parse_pdf_version(doc, path)

    pages: list[PageInfo] = []
    for i in range(doc.page_count):
        page = doc[i]
        mediabox = page.mediabox
        cropbox = page.cropbox
        trimbox = page.trimbox
        bleedbox = page.bleedbox

        # A page with no explicit TrimBox/BleedBox reports them equal to the
        # MediaBox in PyMuPDF; peek at the raw page dict so we don't mistake
        # "no bleed marked" for "bleed present" when it coincidentally
        # equals the MediaBox.
        has_trim = i in _explicit_box_pages(path, "TrimBox")
        has_bleed = i in _explicit_box_pages(path, "BleedBox")

        images = []
        for info in page.get_image_info(xrefs=True):
            bbox = info["bbox"]
            width_pt = bbox[2] - bbox[0]
            height_pt = bbox[3] - bbox[1]
            width_in = width_pt / 72.0
            height_in = height_pt / 72.0
            dpi_x = round(info["width"] / width_in, 1) if width_in > 0 else 0.0
            dpi_y = round(info["height"] / height_in, 1) if height_in > 0 else 0.0
            images.append(
                ImageInfo(
                    xref=info.get("xref", 0),
                    width_px=info["width"],
                    height_px=info["height"],
                    bbox_mm=tuple(pt_to_mm(c) for c in bbox),
                    dpi_x=dpi_x,
                    dpi_y=dpi_y,
                    colorspace=info.get("cs-name", "unknown"),
                )
            )

        fonts = []
        for f in page.get_fonts(full=True):
            xref, ext, ftype, basefont, name, encoding = f[:6]
            fonts.append(FontInfo(basefont=basefont, ext=ext, embedded=(ext != "n/a")))

        pages.append(
            PageInfo(
                index=i,
                rotation=page.rotation,
                mediabox_mm=tuple(pt_to_mm(c) for c in mediabox),
                cropbox_mm=tuple(pt_to_mm(c) for c in cropbox),
                trimbox_mm=tuple(pt_to_mm(c) for c in trimbox),
                bleedbox_mm=tuple(pt_to_mm(c) for c in bleedbox),
                has_explicit_trimbox=has_trim,
                has_explicit_bleedbox=has_bleed,
                images=images,
                fonts=fonts,
            )
        )

    info = DocInfo(path=str(path), pdf_version=pdf_version, page_count=doc.page_count, pages=pages)
    doc.close()
    return info


_explicit_box_cache: dict = {}


def _explicit_box_pages(path: Path, box_name: str) -> set:
    """Return the set of page indices that have an explicit /TrimBox or
    /BleedBox key in the raw PDF page dict (PyMuPDF's page.trimbox/bleedbox
    fall back silently to MediaBox when the key is absent, so we peek at the
    raw object to tell "not set" apart from "set and equal to MediaBox")."""
    cache_key = (str(path), box_name)
    if cache_key in _explicit_box_cache:
        return _explicit_box_cache[cache_key]
    result: set = set()
    try:
        doc = fitz.open(path)
        for i in range(doc.page_count):
            xref = doc[i].xref
            raw = doc.xref_object(xref, compressed=True)
            if f"/{box_name}" in raw:
                result.add(i)
        doc.close()
    except Exception:
        pass
    _explicit_box_cache[cache_key] = result
    return result
