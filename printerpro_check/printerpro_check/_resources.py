"""Locate bundled data files (specs.json, xml_field_map.json) both when
running from source and when frozen into a PyInstaller onefile .exe."""
from __future__ import annotations

import sys
from pathlib import Path


def resource_path(filename: str) -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).resolve().parent.parent
    return base / filename
