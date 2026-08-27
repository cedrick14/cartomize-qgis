"""Diagnostic local des composants Cartomize."""

from pathlib import Path
from typing import Any

from .compat import host_capabilities


def run_diagnostics(arcpy: Any, toolbox_path: str, template_root: str) -> dict[str, object]:
    root = Path(template_root)
    return {
        **host_capabilities(arcpy),
        "toolbox": Path(toolbox_path).is_file(),
        "templates": len(list(root.rglob("template.json"))) if root.exists() else 0,
        "status": "Conforme" if Path(toolbox_path).is_file() and root.exists() else "Non conforme",
    }
