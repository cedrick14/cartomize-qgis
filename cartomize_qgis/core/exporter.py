"""Exports cartographiques natifs par QgsLayoutExporter."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import tempfile

from qgis.core import QgsLayoutExporter, QgsPrintLayout, QgsReadWriteContext

from .compat import export_succeeded, layout_quality_flags, preferred_text_render_format
from .errors import ExportError


@dataclass(frozen=True)
class ExportResult:
    path: str
    format: str
    message: str


class NativeLayoutExporter:
    def export(
        self,
        layout: QgsPrintLayout,
        destination: str,
        output_format: str,
        *,
        dpi: int = 600,
        force_vector: bool = True,
        geo_pdf: bool = False,
    ) -> ExportResult:
        fmt = output_format.lower().strip()
        suffixes = {
            "pdf": ".pdf",
            "svg": ".svg",
            "png": ".png",
            "jpg": ".jpg",
            "jpeg": ".jpg",
            "tif": ".tif",
            "tiff": ".tif",
        }
        if fmt not in suffixes:
            raise ExportError(f"Format d'export non pris en charge : {output_format}")
        final = _safe_destination(destination, suffixes[fmt])
        temporary = _temporary_path(final)
        exporter = QgsLayoutExporter(layout)
        try:
            if fmt == "pdf":
                settings = QgsLayoutExporter.PdfExportSettings()
                settings.dpi = _dpi(dpi)
                _set_if(settings, "forceVectorOutput", bool(force_vector))
                _set_if(settings, "rasterizeWholeImage", False)
                _set_if(settings, "exportMetadata", True)
                _set_if(settings, "appendGeoreference", True)
                _set_if(settings, "writeGeoPdf", bool(geo_pdf))
                text_format = preferred_text_render_format()
                if text_format is not None:
                    _set_if(settings, "textRenderFormat", text_format)
                _enable_quality_flags(settings)
                result = exporter.exportToPdf(str(temporary), settings)
            elif fmt == "svg":
                settings = QgsLayoutExporter.SvgExportSettings()
                settings.dpi = _dpi(dpi)
                _set_if(settings, "forceVectorOutput", bool(force_vector))
                _set_if(settings, "exportMetadata", True)
                text_format = preferred_text_render_format()
                if text_format is not None:
                    _set_if(settings, "textRenderFormat", text_format)
                _enable_quality_flags(settings)
                result = exporter.exportToSvg(str(temporary), settings)
            else:
                settings = QgsLayoutExporter.ImageExportSettings()
                settings.dpi = _dpi(dpi)
                _enable_quality_flags(settings)
                result = exporter.exportToImage(str(temporary), settings)
            if not export_succeeded(result):
                detail = ""
                if hasattr(exporter, "errorMessage"):
                    detail = exporter.errorMessage() or ""
                if not detail and hasattr(exporter, "errorFile"):
                    detail = exporter.errorFile() or ""
                raise ExportError(f"Échec de l'export {fmt.upper()} : {detail or f'code QGIS {result}'}")
            if not temporary.is_file() or temporary.stat().st_size <= 0:
                raise ExportError("QGIS a indiqué un succès, mais le fichier exporté est absent ou vide.")
            os.replace(temporary, final)
            return ExportResult(str(final), fmt, "Export QGIS terminé.")
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)

    def save_as_qpt(self, layout: QgsPrintLayout, destination: str) -> ExportResult:
        final = _safe_destination(destination, ".qpt")
        temporary = _temporary_path(final)
        try:
            ok = layout.saveAsTemplate(str(temporary), QgsReadWriteContext())
            if not ok or not temporary.is_file() or temporary.stat().st_size <= 0:
                raise ExportError("QGIS n'a pas pu enregistrer la maquette QPT.")
            os.replace(temporary, final)
            return ExportResult(str(final), "qpt", "Maquette QPT enregistrée.")
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)


def _safe_destination(value: str, suffix: str) -> Path:
    path = Path(value).expanduser()
    if path.suffix.lower() != suffix:
        path = path.with_suffix(suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise ExportError("La destination d'export ne peut pas être un lien symbolique.")
    return path.resolve(strict=False)


def _temporary_path(final: Path) -> Path:
    fd, name = tempfile.mkstemp(prefix=f".{final.stem}-", suffix=final.suffix, dir=str(final.parent))
    os.close(fd)
    Path(name).unlink(missing_ok=True)
    return Path(name)


def _dpi(value: int) -> int:
    return max(72, min(1200, int(value)))


def _set_if(obj, name: str, value) -> None:
    if hasattr(obj, name):
        setattr(obj, name, value)


def _enable_quality_flags(settings) -> None:
    if not hasattr(settings, "flags"):
        return
    flags = settings.flags
    for flag in layout_quality_flags():
        flags |= flag
    settings.flags = flags
