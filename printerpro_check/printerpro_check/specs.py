"""Load and resolve printerpro.nl delivery specs from specs.json."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ._resources import resource_path

DEFAULT_SPECS_PATH = resource_path("specs.json")


@dataclass
class ProductSpec:
    key: str
    display_name: str
    confirmed: bool
    dpi_min: float
    dpi_recommended: float
    bleed_mm: float
    safety_margin_mm: float
    crop_marks: bool
    fonts_embedded_required: bool
    rich_black_cmyk: list
    border_min_mm: float
    pdf_standard: str
    pdf_min_version: float
    cmyk_profile: str
    rgb_profile: str
    page_count_multiple_of: int | None
    contour_cut: bool
    notes: list = field(default_factory=list)


def _slugify(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


class SpecsRegistry:
    """Loads specs.json and resolves a product name/category to a ProductSpec."""

    def __init__(self, path: Path | str = DEFAULT_SPECS_PATH):
        self.path = Path(path)
        with open(self.path, encoding="utf-8") as fh:
            self._raw = json.load(fh)
        self._default = self._raw["default"]
        self._categories = self._raw["categories"]
        self._resolved: dict[str, ProductSpec] = {}
        for key in self._categories:
            self._resolved[key] = self._resolve(key)

    def _resolve(self, key: str) -> ProductSpec:
        cat = self._categories[key]
        base = dict(self._default)
        if cat.get("inherit") == "default":
            base.update({k: v for k, v in cat.items() if k not in ("inherit",)})
        else:
            base.update(cat)
        # merge notes from default + category rather than overwrite
        notes = list(self._default.get("notes", [])) + list(cat.get("notes", []))
        return ProductSpec(
            key=key,
            display_name=cat.get("display_name", key),
            confirmed=bool(base.get("confirmed", False)),
            dpi_min=base["dpi_min"],
            dpi_recommended=base["dpi_recommended"],
            bleed_mm=base["bleed_mm"],
            safety_margin_mm=base["safety_margin_mm"],
            crop_marks=base["crop_marks"],
            fonts_embedded_required=base["fonts_embedded_required"],
            rich_black_cmyk=base["rich_black_cmyk"],
            border_min_mm=base["border_min_mm"],
            pdf_standard=base["pdf_standard"],
            pdf_min_version=base["pdf_min_version"],
            cmyk_profile=base["cmyk_profile"],
            rgb_profile=base["rgb_profile"],
            page_count_multiple_of=base.get("page_count_multiple_of"),
            contour_cut=bool(base.get("contour_cut", False)),
            notes=notes,
        )

    def keys(self):
        return list(self._resolved.keys())

    def get(self, key: str) -> ProductSpec | None:
        return self._resolved.get(key)

    def match(self, product_name: str) -> ProductSpec:
        """Best-effort match of a free-text product/category name to a spec.

        Falls back to a synthetic spec built from the 'default' block if no
        category matches, so validation can still proceed.
        """
        if not product_name:
            return self._fallback_default()
        slug = _slugify(product_name)
        if slug in self._resolved:
            return self._resolved[slug]
        # substring match against slug or display name (either direction)
        name_lower = product_name.strip().lower()
        best = None
        for key, spec in self._resolved.items():
            disp = spec.display_name.lower()
            if slug in key or key in slug:
                return spec
            if name_lower in disp or disp in name_lower:
                best = spec
        if best:
            return best
        # word-overlap heuristic as last resort
        words = set(re.findall(r"[a-z0-9]+", name_lower))
        best_score = 0
        for key, spec in self._resolved.items():
            disp_words = set(re.findall(r"[a-z0-9]+", spec.display_name.lower()))
            score = len(words & disp_words)
            if score > best_score:
                best_score = score
                best = spec
        if best and best_score > 0:
            return best
        return self._fallback_default()

    def _fallback_default(self) -> ProductSpec:
        d = self._default
        return ProductSpec(
            key="_unmatched_default",
            display_name="(onbekend product - default specs gebruikt)",
            confirmed=False,
            dpi_min=d["dpi_min"],
            dpi_recommended=d["dpi_recommended"],
            bleed_mm=d["bleed_mm"],
            safety_margin_mm=d["safety_margin_mm"],
            crop_marks=d["crop_marks"],
            fonts_embedded_required=d["fonts_embedded_required"],
            rich_black_cmyk=d["rich_black_cmyk"],
            border_min_mm=d["border_min_mm"],
            pdf_standard=d["pdf_standard"],
            pdf_min_version=d["pdf_min_version"],
            cmyk_profile=d["cmyk_profile"],
            rgb_profile=d["rgb_profile"],
            page_count_multiple_of=d.get("page_count_multiple_of"),
            contour_cut=bool(d.get("contour_cut", False)),
            notes=list(d.get("notes", [])) + [
                "Kon productcategorie niet matchen met een bekende printerpro.nl "
                "categorie; algemene default-specs toegepast."
            ],
        )
