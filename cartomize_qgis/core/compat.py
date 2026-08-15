"""Compatibilité d'API entre versions QGIS 3.x prises en charge."""
from __future__ import annotations

import logging

from qgis.PyQt.QtCore import Qt
from qgis.core import Qgis, QgsLayoutExporter, QgsLayoutRenderContext, QgsUnitTypes


def layout_mm_unit():
    enum = getattr(Qgis, "LayoutUnit", None)
    if enum is not None and hasattr(enum, "Millimeters"):
        return enum.Millimeters
    return QgsUnitTypes.LayoutUnit.LayoutMillimeters


def distance_meters():
    enum = getattr(Qgis, "DistanceUnit", None)
    if enum is not None and hasattr(enum, "Meters"):
        return enum.Meters
    return QgsUnitTypes.DistanceUnit.DistanceMeters


def render_points_unit():
    enum = getattr(Qgis, "RenderUnit", None)
    if enum is not None and hasattr(enum, "Points"):
        return enum.Points
    return QgsUnitTypes.RenderUnit.RenderPoints


def first_page_width_mm(layout) -> float:
    """Retourne la largeur physique de la première page."""
    try:
        collection = layout.pageCollection()
        page = collection.page(0) if collection is not None else None
        if page is not None:
            size = page.pageSize()
            width = float(size.width())
            if width > 0:
                return width
    except Exception:
        logging.getLogger(__name__).debug(
            "Impossible de lire la largeur de la première page QGIS.",
            exc_info=True,
        )
    return 297.0


def preview_dpi_for_width(layout, target_width_px: int) -> int:
    """Calcule le DPI nécessaire pour rendre la page à la largeur demandée."""
    width_px = max(1920, min(7680, int(target_width_px)))
    width_mm = first_page_width_mm(layout)
    return max(144, min(1200, int(round(width_px * 25.4 / width_mm))))


def configure_layout_rendering(layout, dpi: int) -> None:
    """Active les options de rendu haute qualité disponibles dans QGIS 3.x."""
    context = layout.renderContext()
    context.setDpi(max(120.0, min(1200.0, float(dpi))))

    text_formats = getattr(Qgis, "TextRenderFormat", None)
    if text_formats is not None and hasattr(text_formats, "PreferText"):
        context.setTextRenderFormat(text_formats.PreferText)

    for flag in layout_quality_flags():
        context.setFlag(flag, True)


def preferred_text_render_format():
    enum = getattr(Qgis, "TextRenderFormat", None)
    return getattr(enum, "PreferText", None) if enum is not None else None


def layout_quality_flags():
    """Retourne uniquement les drapeaux exposés par la version QGIS active."""
    flags = []
    modern = getattr(Qgis, "LayoutRenderFlag", None)
    for name in (
        "Antialiasing",
        "UseAdvancedEffects",
        "LosslessImageRendering",
        "SynchronousLegendGraphics",
        "AlwaysUseGlobalMasks",
    ):
        flag = getattr(modern, name, None) if modern is not None else None
        if flag is None:
            flag = getattr(QgsLayoutRenderContext, f"Flag{name}", None)
        if flag is not None:
            flags.append(flag)
    return flags


def right_dock_area():
    return Qt.DockWidgetArea.RightDockWidgetArea


def user_role():
    return Qt.ItemDataRole.UserRole


def checked_state():
    return Qt.CheckState.Checked


def horizontal_alignment(value: str):
    alignment = getattr(Qt, "AlignmentFlag", Qt)
    value = value.strip().lower()
    if value in {"center", "centre"}:
        return alignment.AlignHCenter
    if value in {"right", "droite", "end"}:
        return alignment.AlignRight
    if value in {"justify", "justified"}:
        return alignment.AlignJustify
    return alignment.AlignLeft


def vertical_alignment(value: str):
    alignment = getattr(Qt, "AlignmentFlag", Qt)
    value = value.strip().lower()
    if value in {"center", "middle", "centre"}:
        return alignment.AlignVCenter
    if value in {"bottom", "bas", "end"}:
        return alignment.AlignBottom
    return alignment.AlignTop


def info_level():
    return getattr(Qgis, "Info", getattr(getattr(Qgis, "MessageLevel", object), "Info", 0))


def success_level():
    return getattr(Qgis, "Success", getattr(getattr(Qgis, "MessageLevel", object), "Success", 3))


def warning_level():
    return getattr(Qgis, "Warning", getattr(getattr(Qgis, "MessageLevel", object), "Warning", 1))


def critical_level():
    return getattr(Qgis, "Critical", getattr(getattr(Qgis, "MessageLevel", object), "Critical", 2))


def dialog_exec(dialog):
    method = getattr(dialog, "exec", None) or getattr(dialog, "exec_", None)
    return method()


def export_succeeded(result) -> bool:
    return result == getattr(QgsLayoutExporter, "Success", 0)


def project_read_entry(project, key: str, default=""):
    """Lit une valeur Cartomize persistée dans un projet QGIS."""
    reader = getattr(project, "readEntry", None)
    if callable(reader):
        for project_key in (key, f"/{key}"):
            try:
                result = reader("Cartomize", project_key, default)
                if isinstance(result, tuple):
                    value = result[0]
                    ok = bool(result[1]) if len(result) > 1 else True
                    if ok:
                        return value
                elif result != default:
                    return result
            except Exception:
                logging.getLogger(__name__).debug(
                    "Impossible de lire l'entrée projet Cartomize %s.",
                    project_key,
                    exc_info=True,
                )
    getter = getattr(project, "customProperty", None)
    if callable(getter):
        try:
            return getter(f"cartomize/{key}", default)
        except Exception:
            logging.getLogger(__name__).debug(
                "Impossible de lire la propriété projet Cartomize %s.",
                key,
                exc_info=True,
            )
    return default


def project_write_entry(project, key: str, value) -> bool:
    """Écrit une valeur Cartomize dans le fichier QGZ/QGS."""
    writer = getattr(project, "writeEntry", None)
    if callable(writer):
        try:
            return bool(writer("Cartomize", key, str(value)))
        except Exception:
            logging.getLogger(__name__).debug(
                "Impossible d'écrire l'entrée projet Cartomize %s.",
                key,
                exc_info=True,
            )
    setter = getattr(project, "setCustomProperty", None)
    if callable(setter):
        try:
            setter(f"cartomize/{key}", value)
            return True
        except Exception:
            logging.getLogger(__name__).debug(
                "Impossible d'écrire la propriété projet Cartomize %s.",
                key,
                exc_info=True,
            )
    return False
