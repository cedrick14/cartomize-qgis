"""Aperçu haute définition des mises en page QGIS."""
from __future__ import annotations
import logging

from dataclasses import dataclass
from typing import Iterable

from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtGui import QPainter
from qgis.PyQt.QtWidgets import QGraphicsView
from qgis.core import (
    QgsLayoutItem,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLayoutItemPicture,
    QgsPrintLayout,
)

from .compat import configure_layout_rendering, first_page_width_mm, preview_dpi_for_width


@dataclass(frozen=True)
class PreviewResult:
    target_width_px: int
    dpi: int
    page_width_mm: float
    refreshed_items: int
    map_items: int
    zoom_mode: str


class HighDefinitionPreviewController:
    """Prépare et ouvre une mise en page avec un rendu d'écran renforcé."""

    def __init__(self, iface):
        self.iface = iface

    def prepare(
        self,
        layout: QgsPrintLayout,
        target_width_px: int,
        *,
        zoom_mode: str = "width",
    ) -> PreviewResult:
        effective_width = max(1920, min(7680, int(target_width_px)))
        page_width_mm = first_page_width_mm(layout)
        effective_dpi = preview_dpi_for_width(layout, effective_width)
        configure_layout_rendering(layout, effective_dpi)
        layout.setCustomProperty("cartomize/preview_mode", "4k")
        layout.setCustomProperty("cartomize/preview_target_width_px", effective_width)
        layout.setCustomProperty("cartomize/preview_dpi", effective_dpi)
        layout.setCustomProperty("cartomize/preview_zoom", zoom_mode)

        refreshed = 0
        maps = 0
        for item in _layout_items(layout):
            if isinstance(item, QgsLayoutItemMap):
                maps += 1
            refreshed += _refresh_item(item)

        invalidate = getattr(layout, "invalidateCachedRenders", None)
        if callable(invalidate):
            try:
                invalidate()
            except Exception:
                logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
        try:
            layout.refresh()
        except Exception:
            logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
        try:
            layout.update()
        except Exception:
            logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)

        return PreviewResult(
            target_width_px=effective_width,
            dpi=effective_dpi,
            page_width_mm=page_width_mm,
            refreshed_items=refreshed,
            map_items=maps,
            zoom_mode=zoom_mode,
        )

    def open(
        self,
        layout: QgsPrintLayout,
        target_width_px: int,
        *,
        zoom_mode: str = "width",
    ):
        result = self.prepare(layout, target_width_px, zoom_mode=zoom_mode)
        designer = self.iface.openLayoutDesigner(layout)
        if designer is None:
            return result

        QTimer.singleShot(0, lambda: self._configure_designer(designer, layout, result))
        QTimer.singleShot(180, lambda: self._refresh_visible_preview(designer, layout))
        QTimer.singleShot(650, lambda: self._refresh_visible_preview(designer, layout))
        QTimer.singleShot(1400, lambda: self._refresh_visible_preview(designer, layout))
        return result

    def _configure_designer(self, designer, layout, result: PreviewResult) -> None:
        view = _safe_call(designer, "view")
        if view is None:
            return
        _enable_view_quality(view)
        _apply_zoom(view, result.zoom_mode)
        try:
            viewport = view.viewport()
            if viewport is not None:
                viewport.update()
        except Exception:
            logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)

    def _refresh_visible_preview(self, designer, layout) -> None:
        for item in _layout_items(layout):
            _refresh_item(item)
        try:
            layout.refresh()
        except Exception:
            logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
        view = _safe_call(designer, "view")
        if view is not None:
            _enable_view_quality(view)
            try:
                view.viewport().update()
            except Exception:
                logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)



def _layout_items(layout: QgsPrintLayout) -> Iterable[QgsLayoutItem]:
    try:
        return tuple(item for item in layout.items() if isinstance(item, QgsLayoutItem))
    except Exception:
        return tuple()


def _refresh_item(item: QgsLayoutItem) -> int:
    changed = False
    for method_name in ("invalidateCache", "refresh", "redraw", "update"):
        method = getattr(item, method_name, None)
        if not callable(method):
            continue
        try:
            method()
            changed = True
        except Exception:
            logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)

    if isinstance(item, QgsLayoutItemLegend):
        method = getattr(item, "updateLegend", None)
        if callable(method):
            try:
                method()
                changed = True
            except Exception:
                logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
    elif isinstance(item, QgsLayoutItemPicture):
        method = getattr(item, "refreshPicture", None)
        if callable(method):
            try:
                method()
                changed = True
            except Exception:
                logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
    return int(changed)


def _enable_view_quality(view) -> None:
    render_hint_enum = getattr(QPainter, "RenderHint", QPainter)
    for name in (
        "Antialiasing",
        "TextAntialiasing",
        "SmoothPixmapTransform",
        "HighQualityAntialiasing",
    ):
        hint = getattr(render_hint_enum, name, None)
        if hint is None:
            hint = getattr(QPainter, name, None)
        if hint is not None:
            try:
                view.setRenderHint(hint, True)
            except Exception:
                logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)

    update_mode_enum = getattr(QGraphicsView, "ViewportUpdateMode", QGraphicsView)
    mode = getattr(update_mode_enum, "FullViewportUpdate", None)
    if mode is None:
        mode = getattr(QGraphicsView, "FullViewportUpdate", None)
    if mode is not None:
        try:
            view.setViewportUpdateMode(mode)
        except Exception:
            logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)

    optimization_enum = getattr(QGraphicsView, "OptimizationFlag", QGraphicsView)
    flag = getattr(optimization_enum, "DontAdjustForAntialiasing", None)
    if flag is None:
        flag = getattr(QGraphicsView, "DontAdjustForAntialiasing", None)
    if flag is not None:
        try:
            view.setOptimizationFlag(flag, False)
        except Exception:
            logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)


def _apply_zoom(view, zoom_mode: str) -> None:
    mode = (zoom_mode or "width").strip().lower()
    method_name = {
        "actual": "zoomActual",
        "full": "zoomFull",
        "width": "zoomWidth",
    }.get(mode, "zoomWidth")
    method = getattr(view, method_name, None)
    if callable(method):
        try:
            method()
            return
        except Exception:
            logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
    fallback = getattr(view, "zoomFull", None)
    if callable(fallback):
        try:
            fallback()
        except Exception:
            logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)


def _safe_call(obj, method_name: str):
    method = getattr(obj, method_name, None)
    if not callable(method):
        return None
    try:
        return method()
    except Exception:
        return None
