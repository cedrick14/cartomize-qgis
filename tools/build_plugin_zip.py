#!/usr/bin/env python3
"""Build an installable Cartomize ZIP with a single plugin root directory."""
from __future__ import annotations

import argparse
from pathlib import Path
import zipfile


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPOSITORY_ROOT / "cartomize_qgis"
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache"}


def iter_release_files():
    for path in sorted(PLUGIN_ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(REPOSITORY_ROOT)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        yield path, relative


def build(output: Path) -> Path:
    metadata = PLUGIN_ROOT / "metadata.txt"
    if not metadata.is_file():
        raise SystemExit("Missing cartomize_qgis/metadata.txt")

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for source, relative in iter_release_files():
            archive.write(source, relative.as_posix())

    with zipfile.ZipFile(output) as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise SystemExit(f"Corrupt ZIP member: {bad_member}")
        names = archive.namelist()
        if "cartomize_qgis/metadata.txt" not in names:
            raise SystemExit("Invalid QGIS plugin ZIP structure")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "dist" / "Cartomize-10.5.1.zip",
    )
    args = parser.parse_args()
    print(build(args.output))


if __name__ == "__main__":
    main()
