"""Data structures and rendering for per-order validation reports."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


@dataclass
class Issue:
    severity: str  # "fail" | "warn" | "info"
    code: str
    message: str


@dataclass
class PdfCheckResult:
    pdf_path: str
    product_key: str
    product_display_name: str
    spec_confirmed: bool
    order_item_summary: str | None
    issues: list = field(default_factory=list)  # Issue, from the ORIGINAL file
    fix_attempted: bool = False
    fix_output_path: str | None = None
    fixes_applied: list = field(default_factory=list)
    fixes_skipped: list = field(default_factory=list)
    remaining_issues: list = field(default_factory=list)  # Issue, after fix (or == issues)

    def has_failures(self) -> bool:
        return any(i.severity == "fail" for i in self.remaining_issues)


@dataclass
class OrderFolderReport:
    folder: str
    xml_files: list = field(default_factory=list)
    pdf_files: list = field(default_factory=list)
    general_warnings: list = field(default_factory=list)
    results: list = field(default_factory=list)  # PdfCheckResult

    def to_json(self) -> str:
        return json.dumps(_to_plain(self), indent=2, ensure_ascii=False)


def _to_plain(obj):
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _to_plain(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [_to_plain(v) for v in obj]
    return obj


_SEVERITY_LABEL = {"fail": "FOUT", "warn": "WAARSCHUWING", "info": "INFO"}


def render_text_report(report: OrderFolderReport) -> str:
    lines = []
    lines.append(f"PrinterPro bestandscontrole -- {report.folder}")
    lines.append("=" * 70)
    lines.append(f"XML-bestand(en): {', '.join(report.xml_files) or '(geen gevonden)'}")
    lines.append(f"PDF-bestand(en): {', '.join(report.pdf_files) or '(geen gevonden)'}")
    if report.general_warnings:
        lines.append("")
        lines.append("Algemene meldingen:")
        for w in report.general_warnings:
            lines.append(f"  - {w}")

    for res in report.results:
        lines.append("")
        lines.append("-" * 70)
        lines.append(f"Bestand: {res.pdf_path}")
        lines.append(
            f"Product: {res.product_display_name} "
            f"({'specs bevestigd van website' if res.spec_confirmed else 'specs NIET bevestigd -- controleer handmatig'})"
        )
        if res.order_item_summary:
            lines.append(f"Order: {res.order_item_summary}")

        lines.append("")
        lines.append("Controle van origineel bestand:")
        if not res.issues:
            lines.append("  Alles OK.")
        for issue in res.issues:
            lines.append(f"  [{_SEVERITY_LABEL[issue.severity]}] {issue.message}")

        if res.fix_attempted:
            lines.append("")
            lines.append(f"Automatisch gecorrigeerd bestand: {res.fix_output_path}")
            if res.fixes_applied:
                lines.append("  Toegepaste correcties:")
                for f in res.fixes_applied:
                    lines.append(f"    - {f}")
            if res.fixes_skipped:
                lines.append("  Niet automatisch gecorrigeerd:")
                for f in res.fixes_skipped:
                    lines.append(f"    - {f}")
            lines.append("  Resterende controlepunten na correctie:")
            if not res.remaining_issues:
                lines.append("    Alles OK.")
            for issue in res.remaining_issues:
                lines.append(f"    [{_SEVERITY_LABEL[issue.severity]}] {issue.message}")

    lines.append("")
    lines.append("=" * 70)
    total_fail = sum(1 for r in report.results if r.has_failures())
    lines.append(f"Samenvatting: {len(report.results)} bestand(en) gecontroleerd, {total_fail} met openstaande fouten.")
    return "\n".join(lines)
