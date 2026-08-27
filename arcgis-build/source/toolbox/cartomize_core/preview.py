"""Aperçu haute définition d’une mise en page ArcGIS Pro."""

from dataclasses import dataclass
from pathlib import Path
from tempfile import gettempdir

from .compat import first_page_width_mm, preview_dpi_for_width
from .layout import export_layout


def export_preview(arcpy, layout, dpi: int = 180) -> str:
    target = Path(gettempdir()) / "cartomize-preview.png"
    return export_layout(arcpy, layout, str(target), dpi=dpi)


@dataclass(frozen=True)
class PreviewResult:
    target_width_px: int; dpi: int; page_width_mm: float; refreshed_items: int; map_items: int; zoom_mode: str


class HighDefinitionPreviewController:
    def __init__(self, iface=None, *, arcpy_module=None): self.iface = iface; self.arcpy = arcpy_module
    def prepare(self, layout, target_width_px: int, *, zoom_mode: str = "width") -> PreviewResult:
        width = max(1920, min(7680, int(target_width_px))); dpi = preview_dpi_for_width(layout, width)
        elements = list(layout.listElements()); maps = list(layout.listElements("MAPFRAME_ELEMENT"))
        for item in elements:
            refresh = getattr(item, "refresh", None)
            if callable(refresh):
                try: refresh()
                except Exception: pass
        return PreviewResult(width, dpi, first_page_width_mm(layout), len(elements), len(maps), str(zoom_mode or "width"))
    def open(self, layout, target_width_px: int, *, zoom_mode: str = "width") -> PreviewResult:
        result = self.prepare(layout, target_width_px, zoom_mode=zoom_mode)
        try: layout.openView()
        except Exception: pass
        return result
