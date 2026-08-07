#!/usr/bin/env python3
from __future__ import annotations

import configparser
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "cartomize_qgis"
DIST = ROOT / "dist"


def main() -> int:
    result = subprocess.run([sys.executable, str(ROOT / "tools" / "preflight.py")])
    if result.returncode:
        return result.returncode

    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(PLUGIN / "metadata.txt", encoding="utf-8")
    version = cfg["general"]["version"].strip()
    output = DIST / f"Cartomize-{version}-QGIS-OFFICIAL-SUBMISSION.zip"
    DIST.mkdir(exist_ok=True)
    if output.exists():
        output.unlink()

    with tempfile.TemporaryDirectory(prefix="cartomize-qgis-build-") as tmp:
        staged = Path(tmp) / "cartomize_qgis"
        shutil.copytree(
            PLUGIN,
            staged,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "Thumbs.db"),
        )
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for path in sorted(staged.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(Path(tmp)).as_posix())

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
