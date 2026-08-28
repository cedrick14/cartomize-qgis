"""Exports cartographiques natifs ArcGIS Pro."""

from dataclasses import dataclass
from pathlib import Path

from .errors import ExportError
from .layout import export_layout


@dataclass(frozen=True)
class ExportResult:
    path: str
    format: str
    message: str


class NativeLayoutExporter:
    def __init__(self, arcpy_module=None):
        self.arcpy = arcpy_module

    def export(self, layout, destination: str, output_format: str, *, dpi: int = 600, force_vector: bool = True, geo_pdf: bool = False) -> ExportResult:
        fmt = str(output_format or "").strip().casefold()
        if fmt not in {"pdf", "svg", "png", "jpg", "jpeg", "tif", "tiff"}:
            raise ExportError(f"Format d'export non pris en charge : {output_format}")
        target = Path(destination).expanduser()
        suffix = {"jpeg": ".jpg", "tiff": ".tif"}.get(fmt, f".{fmt}")
        if target.suffix.casefold() != suffix:
            target = target.with_suffix(suffix)
        if target.is_symlink() or target.parent.is_symlink():
            raise ExportError("La destination d'export ne peut pas être un lien symbolique.")
        arcpy_module = self.arcpy
        if arcpy_module is None:
            try:
                import arcpy as arcpy_module
            except ImportError as exc:
                raise ExportError("ArcPy est requis pour exporter la mise en page.") from exc
        try:
            path = export_layout(arcpy_module, layout, str(target), dpi=dpi)
        except Exception as exc:
            raise ExportError(str(exc)) from exc
        return ExportResult(path, fmt, "Export ArcGIS Pro terminé.")

    def save_as_qpt(self, layout, destination: str) -> ExportResult:
        """Équivalent ArcGIS Pro du QPT : enregistre une maquette PAGX."""
        target = Path(destination).expanduser().with_suffix(".pagx")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            layout.exportToPAGX(str(target.resolve()))
        except Exception as exc:
            raise ExportError(f"ArcGIS Pro n'a pas pu enregistrer la maquette PAGX : {exc}") from exc
        return ExportResult(str(target.resolve()), "pagx", "Maquette PAGX enregistrée.")


__all__ = ["ExportResult", "NativeLayoutExporter", "export_layout"]
