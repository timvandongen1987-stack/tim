"""Orchestrates checking (and optionally fixing) one printerpro.nl order
folder: find the order XML + artwork PDFs, match each artwork to its
product spec, run the checks, and optionally write a corrected PDF."""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from .pdf_fix import apply_fixes
from .pdf_inspect import DocInfo, inspect_pdf
from .report import Issue, OrderFolderReport, PdfCheckResult
from .specs import ProductSpec, SpecsRegistry
from .xml_order import OrderItem, OrderXmlParser

SIZE_TOLERANCE_MM = 0.5


@dataclass
class ValidatorConfig:
    specs_path: Path | str | None = None
    field_map_path: Path | str | None = None
    apply_fixes: bool = True
    fix_bleed: bool = True
    fix_size: bool = True
    fix_page_count: bool = True


def _find_files(folder: Path) -> tuple[list[Path], list[Path]]:
    xml_files = sorted(folder.glob("*.xml"))
    pdf_files = sorted(p for p in folder.glob("*.pdf") if "_corrected" not in p.stem)
    return xml_files, pdf_files


def _match_pdf_for_item(item: OrderItem, pdf_files: list[Path], used: set) -> Path | None:
    candidates = [p for p in pdf_files if p not in used]
    if not candidates:
        return None
    if item.filename_hint:
        hint_stem = Path(item.filename_hint).stem.lower()
        for p in candidates:
            if p.stem.lower() == hint_stem:
                return p
        for p in candidates:
            if hint_stem in p.stem.lower() or p.stem.lower() in hint_stem:
                return p
    if len(candidates) == 1:
        return candidates[0]
    if item.product_name:
        names = {p: p.stem.lower() for p in candidates}
        best = difflib.get_close_matches(item.product_name.lower(), names.values(), n=1, cutoff=0.3)
        if best:
            for p, n in names.items():
                if n == best[0]:
                    return p
    return None


def _expected_page_count(item: OrderItem) -> int | None:
    if item.pages:
        return item.pages
    if item.sides:
        return item.sides
    return None


def _check_pdf(doc_info: DocInfo, spec: ProductSpec, item: OrderItem | None) -> list[Issue]:
    issues: list[Issue] = []

    if doc_info.pdf_version is not None and doc_info.pdf_version < spec.pdf_min_version:
        issues.append(
            Issue(
                "warn",
                "pdf_version",
                f"PDF-versie {doc_info.pdf_version} is lager dan aanbevolen "
                f"{spec.pdf_min_version} ({spec.pdf_standard}).",
            )
        )

    if spec.fonts_embedded_required and not doc_info.all_fonts_embedded():
        names = ", ".join(doc_info.non_embedded_fonts())
        issues.append(
            Issue(
                "fail",
                "fonts_not_embedded",
                f"Niet alle fonts zijn ingesloten: {names}. Dit kan niet automatisch "
                "worden gecorrigeerd -- exporteer opnieuw met fonts ingesloten.",
            )
        )

    expected_pages = _expected_page_count(item) if item else None
    if expected_pages and doc_info.page_count != expected_pages:
        issues.append(
            Issue(
                "fail",
                "page_count_mismatch",
                f"Aantal pagina's ({doc_info.page_count}) komt niet overeen met "
                f"order ({expected_pages}).",
            )
        )
    if spec.page_count_multiple_of and doc_info.page_count % spec.page_count_multiple_of != 0:
        issues.append(
            Issue(
                "warn",
                "page_count_multiple",
                f"Aantal pagina's ({doc_info.page_count}) is geen veelvoud van "
                f"{spec.page_count_multiple_of} (aanname, niet bevestigd op website -- controleer).",
            )
        )

    target_w = item.width_mm if item else None
    target_h = item.height_mm if item else None
    for page in doc_info.pages:
        pw, ph = page.trim_width_mm, page.trim_height_mm
        if target_w and target_h:
            direct = abs(pw - target_w) <= SIZE_TOLERANCE_MM and abs(ph - target_h) <= SIZE_TOLERANCE_MM
            swapped = abs(pw - target_h) <= SIZE_TOLERANCE_MM and abs(ph - target_w) <= SIZE_TOLERANCE_MM
            if not direct and not swapped:
                issues.append(
                    Issue(
                        "fail",
                        "trim_size_mismatch",
                        f"Pagina {page.index + 1}: formaat {pw}x{ph} mm komt niet overeen "
                        f"met besteld formaat {target_w}x{target_h} mm.",
                    )
                )
            elif swapped and not direct:
                issues.append(
                    Issue(
                        "warn",
                        "trim_size_rotated",
                        f"Pagina {page.index + 1}: formaat komt overeen na 90 graden "
                        "rotatie -- controleer of de afdrukstand klopt.",
                    )
                )

        margin = page.bleed_margin_mm()
        if not page.has_explicit_bleedbox or margin < spec.bleed_mm - 0.3:
            issues.append(
                Issue(
                    "fail",
                    "bleed_missing",
                    f"Pagina {page.index + 1}: bleed/afloop is "
                    f"{margin if page.has_explicit_bleedbox else 0} mm, vereist is {spec.bleed_mm} mm.",
                )
            )

        for img in page.images:
            if img.dpi_min < spec.dpi_min:
                issues.append(
                    Issue(
                        "fail",
                        "dpi_too_low",
                        f"Pagina {page.index + 1}: afbeelding resolutie {img.dpi_min:.0f} DPI is "
                        f"lager dan minimum {spec.dpi_min} DPI. Wordt niet automatisch vergroot "
                        "(dit voegt geen echte detail toe) -- lever een bestand met hogere resolutie aan.",
                    )
                )
            elif img.dpi_min < spec.dpi_recommended:
                issues.append(
                    Issue(
                        "warn",
                        "dpi_below_recommended",
                        f"Pagina {page.index + 1}: afbeelding resolutie {img.dpi_min:.0f} DPI is "
                        f"lager dan aanbevolen {spec.dpi_recommended} DPI.",
                    )
                )
            if "RGB" in img.colorspace.upper() and "CMYK" not in img.colorspace.upper():
                issues.append(
                    Issue(
                        "info",
                        "rgb_image",
                        f"Pagina {page.index + 1}: afbeelding is RGB, aanbevolen CMYK-profiel "
                        f"is {spec.cmyk_profile}. Niet automatisch geconverteerd -- controleer kleuromzetting.",
                    )
                )

    issues.append(
        Issue(
            "info",
            "manual_reminders",
            "Handmatig te controleren (niet automatisch te toetsen): veiligheidsmarge "
            f"{spec.safety_margin_mm} mm vanaf de rand, kaderbreedte min. {spec.border_min_mm} mm, "
            f"diepzwart-waarde CMYK {tuple(spec.rich_black_cmyk)}.",
        )
    )
    return issues


def validate_folder(folder: Path | str, config: ValidatorConfig | None = None) -> OrderFolderReport:
    folder = Path(folder)
    config = config or ValidatorConfig()
    specs = SpecsRegistry(config.specs_path) if config.specs_path else SpecsRegistry()
    xml_parser = (
        OrderXmlParser(config.field_map_path) if config.field_map_path else OrderXmlParser()
    )

    xml_files, pdf_files = _find_files(folder)
    report = OrderFolderReport(
        folder=str(folder),
        xml_files=[p.name for p in xml_files],
        pdf_files=[p.name for p in pdf_files],
    )

    if not pdf_files:
        report.general_warnings.append("Geen PDF-bestanden gevonden in deze map.")
        return report
    if not xml_files:
        report.general_warnings.append(
            "Geen order-XML gevonden; PDF's worden gecontroleerd met alleen algemene "
            "specs (productcategorie herkend via bestandsnaam, geen ordergegevens zoals formaat/paginas)."
        )

    items: list[OrderItem] = []
    for xf in xml_files:
        try:
            items.extend(xml_parser.parse(xf))
        except Exception as exc:
            report.general_warnings.append(f"Kon {xf.name} niet parsen: {exc}")

    used_pdfs: set[Path] = set()
    pairs: list[tuple[OrderItem | None, Path]] = []
    for item in items:
        pdf = _match_pdf_for_item(item, pdf_files, used_pdfs)
        if pdf is None:
            report.general_warnings.append(
                f"Kon orderregel '{item.product_name or item.order_id or '?'}' niet koppelen "
                "aan een PDF-bestand in deze map."
            )
            continue
        used_pdfs.add(pdf)
        pairs.append((item, pdf))

    for pdf in pdf_files:
        if pdf not in used_pdfs:
            report.general_warnings.append(
                f"{pdf.name}: geen bijbehorende orderregel gevonden in de XML; "
                "gecontroleerd met alleen algemene specs."
            )
            pairs.append((None, pdf))

    for item, pdf in pairs:
        product_name = item.product_name if item else pdf.stem
        spec = specs.match(product_name or "")
        try:
            doc_info = inspect_pdf(pdf)
        except Exception as exc:
            report.results.append(
                PdfCheckResult(
                    pdf_path=pdf.name,
                    product_key=spec.key,
                    product_display_name=spec.display_name,
                    spec_confirmed=spec.confirmed,
                    order_item_summary=None,
                    issues=[Issue("fail", "unreadable_pdf", f"Kon PDF niet lezen: {exc}")],
                )
            )
            continue

        issues = _check_pdf(doc_info, spec, item)
        order_summary = None
        if item:
            order_summary = (
                f"{item.width_mm}x{item.height_mm} mm, pagina's={item.pages}, "
                f"zijden={item.sides}, aantal={item.quantity}"
            )
            if item.warnings:
                for w in item.warnings:
                    issues.append(Issue("warn", "xml_field_missing", w))

        result = PdfCheckResult(
            pdf_path=pdf.name,
            product_key=spec.key,
            product_display_name=spec.display_name,
            spec_confirmed=spec.confirmed,
            order_item_summary=order_summary,
            issues=issues,
            remaining_issues=issues,
        )

        fixable = config.apply_fixes and item and any(
            i.code in ("trim_size_mismatch", "bleed_missing", "page_count_mismatch")
            for i in issues
        )
        if fixable:
            target_trim = (item.width_mm, item.height_mm) if item.width_mm and item.height_mm else None
            target_pages = _expected_page_count(item)
            out_path = pdf.with_name(f"{pdf.stem}_corrected.pdf")
            fix_result = apply_fixes(
                src_path=pdf,
                output_path=out_path,
                target_trim_mm=target_trim,
                bleed_mm=spec.bleed_mm,
                target_pages=target_pages,
                fix_bleed=config.fix_bleed,
                fix_size=config.fix_size,
                fix_page_count_flag=config.fix_page_count,
            )
            result.fix_attempted = True
            result.fix_output_path = str(fix_result.output_path)
            result.fixes_applied = fix_result.applied
            result.fixes_skipped = fix_result.skipped
            try:
                fixed_doc_info = inspect_pdf(fix_result.output_path)
                result.remaining_issues = _check_pdf(fixed_doc_info, spec, item)
            except Exception as exc:
                result.remaining_issues = issues + [
                    Issue("fail", "refresh_check_failed", f"Kon gecorrigeerd bestand niet opnieuw controleren: {exc}")
                ]

        report.results.append(result)

    return report
