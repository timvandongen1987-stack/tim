"""Generic parser for printerpro.nl order XML files.

No real sample order XML was available when this was written, so the parser
is deliberately schema-agnostic: it flattens whatever XML structure it is
given and maps tag names to known concepts (product name, size, page count,
...) via the alias lists in xml_field_map.json. Once a real sample XML is
available, tighten xml_field_map.json (put the exact tag name first in each
alias list) rather than rewriting this parser.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ._resources import resource_path

DEFAULT_FIELD_MAP_PATH = resource_path("xml_field_map.json")

_UNIT_TO_MM = {
    "mm": 1.0,
    "millimeter": 1.0,
    "millimeters": 1.0,
    "cm": 10.0,
    "centimeter": 10.0,
    "centimeters": 10.0,
    "m": 1000.0,
    "in": 25.4,
    "inch": 25.4,
    "inches": 25.4,
    "pt": 25.4 / 72.0,
    "point": 25.4 / 72.0,
    "points": 25.4 / 72.0,
}


def _norm_tag(tag: str) -> str:
    """Strip XML namespace and normalize a tag name for matching."""
    if "}" in tag:
        tag = tag.split("}", 1)[1]
    return re.sub(r"[_\-\s]+", "", tag.lower())


def _norm_alias(alias: str) -> str:
    return re.sub(r"[_\-\s]+", "", alias.lower())


@dataclass
class OrderItem:
    order_id: str | None
    product_name: str | None
    width_mm: float | None
    height_mm: float | None
    pages: int | None
    sides: int | None
    quantity: int | None
    finishing: str | None
    filename_hint: str | None
    matched_pdf: str | None = None
    raw_fields: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)


class OrderXmlParser:
    def __init__(self, field_map_path: Path | str = DEFAULT_FIELD_MAP_PATH):
        with open(field_map_path, encoding="utf-8") as fh:
            raw_map = json.load(fh)
        self.field_map: dict[str, list[str]] = {
            k: v for k, v in raw_map.items() if not k.startswith("_")
        }
        # concept -> normalized alias set, aliases kept in priority order
        self._alias_lookup: dict[str, str] = {}
        for concept, aliases in self.field_map.items():
            for alias in aliases:
                self._alias_lookup[_norm_alias(alias)] = concept

    def _flatten(self, elem: ET.Element, out: dict[str, list[str]]) -> None:
        text = (elem.text or "").strip()
        if text:
            tag = _norm_tag(elem.tag)
            out.setdefault(tag, []).append(text)
        for attr_name, attr_val in elem.attrib.items():
            out.setdefault(_norm_tag(attr_name), []).append(attr_val)
        for child in elem:
            self._flatten(child, out)

    def _extract_concepts(self, flat: dict[str, list[str]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for norm_alias, concept in self._alias_lookup.items():
            if concept in result:
                continue
            if norm_alias in flat:
                result[concept] = flat[norm_alias][0]
        return result

    def _find_item_elements(self, root: ET.Element) -> list[ET.Element]:
        """Heuristically find repeating line-item elements (siblings sharing a tag)."""
        tag_groups: dict[str, list[ET.Element]] = {}

        def walk(elem: ET.Element):
            counts: dict[str, list[ET.Element]] = {}
            for child in elem:
                counts.setdefault(_norm_tag(child.tag), []).append(child)
            for tag, group in counts.items():
                if len(group) > 1:
                    tag_groups.setdefault(tag, []).extend(group)
            for child in elem:
                walk(child)

        walk(root)
        if not tag_groups:
            return [root]
        # pick the largest repeating group as the line-item list
        best_tag = max(tag_groups, key=lambda t: len(tag_groups[t]))
        return tag_groups[best_tag]

    def _to_mm(self, value_mm_field: str | None, unit_hint: str | None) -> float | None:
        if value_mm_field is None:
            return None
        try:
            num = float(re.sub(r"[^0-9.\-]", "", value_mm_field))
        except ValueError:
            return None
        factor = _UNIT_TO_MM.get((unit_hint or "mm").strip().lower(), 1.0)
        return round(num * factor, 3)

    def parse(self, xml_path: Path | str) -> list[OrderItem]:
        xml_path = Path(xml_path)
        tree = ET.parse(xml_path)
        root = tree.getroot()

        root_flat: dict[str, list[str]] = {}
        self._flatten(root, root_flat)
        root_concepts = self._extract_concepts(root_flat)

        items = self._find_item_elements(root)
        results: list[OrderItem] = []
        for item_elem in items:
            flat: dict[str, list[str]] = {}
            self._flatten(item_elem, flat)
            concepts = dict(root_concepts)
            concepts.update(self._extract_concepts(flat))

            warnings = []
            unit_hint = concepts.get("unit")
            width_mm = self._to_mm(concepts.get("width_mm"), unit_hint)
            height_mm = self._to_mm(concepts.get("height_mm"), unit_hint)
            if width_mm is None or height_mm is None:
                warnings.append(
                    "Kon breedte/hoogte niet uit de XML halen; controleer "
                    "xml_field_map.json (width_mm/height_mm aliases)."
                )

            def _to_int(v):
                if v is None:
                    return None
                m = re.search(r"-?\d+", str(v))
                return int(m.group()) if m else None

            pages = _to_int(concepts.get("pages"))
            sides = _to_int(concepts.get("sides"))
            quantity = _to_int(concepts.get("quantity"))

            product_name = concepts.get("product_name")
            if not product_name:
                warnings.append(
                    "Kon productnaam/categorie niet uit de XML halen; "
                    "default specs worden gebruikt."
                )

            results.append(
                OrderItem(
                    order_id=concepts.get("order_id"),
                    product_name=product_name,
                    width_mm=width_mm,
                    height_mm=height_mm,
                    pages=pages,
                    sides=sides,
                    quantity=quantity,
                    finishing=concepts.get("finishing"),
                    filename_hint=concepts.get("filename"),
                    raw_fields={k: v[0] for k, v in flat.items()},
                    warnings=warnings,
                )
            )
        return results
