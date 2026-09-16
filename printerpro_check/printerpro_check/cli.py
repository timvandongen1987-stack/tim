"""Command-line entry point for the PrinterPro file checker.

Usage:
    python -m printerpro_check.cli <folder> [options]

If --batch is given, <folder> is treated as a parent directory containing
one order subfolder per job (each with its own XML + PDF files); otherwise
<folder> itself is treated as a single order folder.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .report import render_text_report
from .validator import ValidatorConfig, validate_folder


def _order_subfolders(parent: Path) -> list[Path]:
    return sorted(p for p in parent.iterdir() if p.is_dir())


def _write_reports(folder: Path, report) -> None:
    (folder / "_printerpro_report.txt").write_text(render_text_report(report), encoding="utf-8")
    (folder / "_printerpro_report.json").write_text(report.to_json(), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check printerpro.nl order artwork against delivery specs.")
    parser.add_argument("folder", help="Order folder, or parent folder of order folders with --batch")
    parser.add_argument("--batch", action="store_true", help="Treat FOLDER as a parent of multiple order folders")
    parser.add_argument("--no-fix", action="store_true", help="Only report issues, do not write corrected PDFs")
    parser.add_argument("--specs", default=None, help="Path to a custom specs.json")
    parser.add_argument("--field-map", default=None, help="Path to a custom xml_field_map.json")
    args = parser.parse_args(argv)

    root = Path(args.folder)
    if not root.is_dir():
        print(f"Map niet gevonden: {root}", file=sys.stderr)
        return 2

    config = ValidatorConfig(
        specs_path=args.specs,
        field_map_path=args.field_map,
        apply_fixes=not args.no_fix,
    )

    folders = _order_subfolders(root) if args.batch else [root]
    any_failures = False
    for folder in folders:
        report = validate_folder(folder, config)
        print(render_text_report(report))
        print()
        _write_reports(folder, report)
        if any(r.has_failures() for r in report.results):
            any_failures = True

    return 1 if any_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
