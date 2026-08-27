"""Aperçu haute définition d’une mise en page ArcGIS Pro."""

from pathlib import Path
from tempfile import gettempdir

from .layout import export_layout


def export_preview(arcpy, layout, dpi: int = 180) -> str:
    target = Path(gettempdir()) / "cartomize-preview.png"
    return export_layout(arcpy, layout, str(target), dpi=dpi)
