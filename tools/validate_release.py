#!/usr/bin/env python3
"""Validate the Cartomize source tree without requiring a QGIS runtime."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "cartomize_qgis"
EXPECTED_VERSION = "10.5.1"


def main() -> None:
    if not (PLUGIN / "__init__.py").is_file():
        raise SystemExit("Missing QGIS plugin entry point")

    python_files = sorted(PLUGIN.rglob("*.py"))
    json_files = sorted(PLUGIN.rglob("*.json"))
    for path in python_files:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for path in json_files:
        json.loads(path.read_text(encoding="utf-8"))

    metadata = (PLUGIN / "metadata.txt").read_text(encoding="utf-8")
    match = re.search(r"(?m)^version=(.+)$", metadata)
    if not match or match.group(1).strip() != EXPECTED_VERSION:
        raise SystemExit("metadata.txt version does not match the release")

    constants = (PLUGIN / "core" / "constants.py").read_text(encoding="utf-8")
    if f'PLUGIN_VERSION = "{EXPECTED_VERSION}"' not in constants:
        raise SystemExit("Runtime version does not match metadata.txt")

    forbidden = [
        path
        for path in PLUGIN.rglob("*")
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}
    ]
    if forbidden:
        raise SystemExit(f"Generated files must not be committed: {forbidden[0]}")

    print(f"Validated {len(python_files)} Python and {len(json_files)} JSON files")
    print(f"Cartomize version: {EXPECTED_VERSION}")


if __name__ == "__main__":
    main()
