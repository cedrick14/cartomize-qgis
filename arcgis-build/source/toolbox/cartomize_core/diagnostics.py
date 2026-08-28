"""Diagnostic local des composants Cartomize."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .compat import host_capabilities
from .constants import APP_VERSION


def run_diagnostics(arcpy: Any, toolbox_path: str, template_root: str) -> dict[str, object]:
    root = Path(template_root)
    return {
        **host_capabilities(arcpy),
        "toolbox": Path(toolbox_path).is_file(),
        "templates": len(list(root.rglob("template.json"))) if root.exists() else 0,
        "status": "Conforme" if Path(toolbox_path).is_file() and root.exists() else "Non conforme",
    }


@dataclass(frozen=True)
class DiagnosticReport:
    ok: bool
    lines: tuple[str, ...]

    def as_text(self) -> str: return "\n".join(self.lines)


class DiagnosticEngine:
    REQUIRED_CAPABILITIES = ("arcpy_mp", "raster")

    def __init__(self, plugin_root: Path, arcpy_module=None):
        self.plugin_root = Path(plugin_root).resolve()
        self.arcpy = arcpy_module

    def run(self) -> DiagnosticReport:
        arcpy_module = self.arcpy
        if arcpy_module is None:
            try:
                import arcpy as arcpy_module
            except ImportError:
                arcpy_module = None
        capabilities = host_capabilities(arcpy_module) if arcpy_module is not None else {"host": "ArcGIS Pro", "version": "", "arcpy_mp": False, "raster": False}
        lines = [f"Cartomize {APP_VERSION}", f"Version d'ArcGIS Pro : {capabilities.get('version') or 'indisponible'}", "", "Composants requis"]
        ok = arcpy_module is not None
        for key in self.REQUIRED_CAPABILITIES:
            available = bool(capabilities.get(key))
            ok = ok and available
            lines.append(f"{key} : {'disponible' if available else 'indisponible'}")
        toolbox = self.plugin_root / "toolbox" / "Cartomize.pyt"
        template_root = self.plugin_root / "templates_library"
        template_count = len([path for path in template_root.rglob("*.json") if path.name != "offline_catalog.json"]) if template_root.exists() else 0
        ok = ok and toolbox.is_file() and template_count == 24
        lines.append(f"Boîte à outils Cartomize : {'disponible' if toolbox.is_file() else 'indisponible'}")
        lines.append(f"Catalogue de maquettes : {template_count} maquettes")
        if arcpy_module is not None:
            try:
                project = arcpy_module.mp.ArcGISProject("CURRENT")
                lines.extend(("", "Projet courant", f"Cartes : {len(project.listMaps())}", f"Mises en page : {len(project.listLayouts())}"))
            except Exception as exc:
                ok = False
                lines.append(f"Projet ArcGIS Pro : indisponible. {exc}")
        lines.extend(("", f"Statut général : {'Conforme' if ok else 'Non conforme'}"))
        return DiagnosticReport(ok, tuple(lines))
