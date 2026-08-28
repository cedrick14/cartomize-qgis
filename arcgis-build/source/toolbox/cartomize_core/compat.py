"""Contrôles et équivalences d'API pour l'hôte ArcGIS Pro."""

import logging
from typing import Any


_PROJECT_VALUES: dict[tuple[int, str], object] = {}


def host_capabilities(arcpy: Any) -> dict[str, object]:
    info = arcpy.GetInstallInfo() if hasattr(arcpy, "GetInstallInfo") else {}
    return {
        "host": info.get("ProductName", "ArcGIS Pro"),
        "version": info.get("Version", ""),
        "arcpy_mp": hasattr(arcpy, "mp"),
        "raster": hasattr(arcpy, "Raster"),
    }


def layout_mm_unit(): return "MILLIMETER"
def distance_meters(): return "METERS"
def render_points_unit(): return "POINTS"


def first_page_width_mm(layout) -> float:
    for name in ("pageWidth", "page_width", "width"):
        try:
            value = getattr(layout, name)
            value = value() if callable(value) else value
            if float(value) > 0:
                return float(value)
        except Exception:
            pass
    return 297.0


def preview_dpi_for_width(layout, target_width_px: int) -> int:
    width_px = max(1920, min(7680, int(target_width_px)))
    return max(144, min(1200, int(round(width_px * 25.4 / first_page_width_mm(layout)))))


def configure_layout_rendering(layout, dpi: int) -> None:
    """ArcGIS Pro configure le DPI sur l'objet d'export; conserve la valeur demandée."""
    try:
        setattr(layout, "_cartomize_export_dpi", max(120, min(1200, int(dpi))))
    except Exception:
        pass


def preferred_text_render_format(): return "TEXT"
def layout_quality_flags(): return ("ANTIALIASING", "ADVANCED_EFFECTS", "LOSSLESS_IMAGES")
def right_dock_area(): return "RIGHT"
def user_role(): return 32
def checked_state(): return True


def horizontal_alignment(value: str):
    return {"center": "CENTER", "centre": "CENTER", "right": "RIGHT", "droite": "RIGHT", "end": "RIGHT", "justify": "JUSTIFY", "justified": "JUSTIFY"}.get(str(value).strip().casefold(), "LEFT")


def vertical_alignment(value: str):
    return {"center": "CENTER", "middle": "CENTER", "centre": "CENTER", "bottom": "BOTTOM", "bas": "BOTTOM", "end": "BOTTOM"}.get(str(value).strip().casefold(), "TOP")


def info_level(): return 0
def success_level(): return 3
def warning_level(): return 1
def critical_level(): return 2


def dialog_exec(dialog):
    method = getattr(dialog, "exec", None) or getattr(dialog, "exec_", None) or getattr(dialog, "show", None)
    return method() if callable(method) else None


def export_succeeded(result) -> bool:
    return result in (None, 0, True, "Success", "SUCCESS")


def project_read_entry(project, key: str, default=""):
    reader = getattr(project, "readEntry", None)
    if callable(reader):
        try:
            result = reader("Cartomize", key, default)
            return result[0] if isinstance(result, tuple) else result
        except Exception:
            logging.getLogger(__name__).debug("Lecture de propriété impossible", exc_info=True)
    return _PROJECT_VALUES.get((id(project), str(key)), default)


def project_write_entry(project, key: str, value) -> bool:
    writer = getattr(project, "writeEntry", None)
    if callable(writer):
        try:
            return bool(writer("Cartomize", key, str(value)))
        except Exception:
            logging.getLogger(__name__).debug("Écriture de propriété impossible", exc_info=True)
    _PROJECT_VALUES[(id(project), str(key))] = value
    return True
