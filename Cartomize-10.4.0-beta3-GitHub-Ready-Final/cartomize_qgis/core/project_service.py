"""Accès unique au projet QGIS et aux couches réellement chargées."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from qgis.core import (
    QgsCoordinateTransform,
    QgsMapLayer,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsVectorLayer,
)


@dataclass(frozen=True)
class ProjectSummary:
    layer_count: int
    visible_count: int
    vector_count: int
    raster_count: int
    invalid_count: int
    project_crs: str
    extent_text: str


class ProjectService:
    """Maintient une seule vérité : les objets du QgsProject courant."""

    def __init__(self, iface, project: QgsProject | None = None):
        self.iface = iface
        self.project = project or QgsProject.instance()

    def ordered_layers(self, visible_only: bool = False) -> list[QgsMapLayer]:
        layers: list[QgsMapLayer] = []
        root = self.project.layerTreeRoot()
        for node in root.findLayers():
            layer = node.layer()
            if layer is None:
                continue
            if visible_only and not node.isVisible():
                continue
            layers.append(layer)
        return layers

    def visible_layers(self) -> list[QgsMapLayer]:
        canvas = self.iface.mapCanvas()
        canvas_layers = [layer for layer in canvas.layers() if layer and layer.isValid()]
        if canvas_layers:
            return canvas_layers
        return [layer for layer in self.ordered_layers(True) if layer.isValid()]

    def active_layer(self) -> QgsMapLayer | None:
        layer = self.iface.activeLayer()
        return layer if layer and layer.isValid() else None

    def active_vector_layer(self) -> QgsVectorLayer | None:
        active = self.active_layer()
        if isinstance(active, QgsVectorLayer):
            return active
        return next((layer for layer in self.visible_layers() if isinstance(layer, QgsVectorLayer)), None)

    def layer_by_id(self, layer_id: str) -> QgsMapLayer | None:
        return self.project.mapLayer(layer_id)

    def display_crs(self, layers: Iterable[QgsMapLayer] | None = None):
        """Retourne un CRS de rendu valide sans mélanger des emprises incompatibles."""
        project_crs = self.project.crs()
        if project_crs.isValid():
            return project_crs
        try:
            canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
            if canvas_crs.isValid():
                return canvas_crs
        except Exception:
            pass
        for layer in list(layers or self.ordered_layers()):
            if layer and layer.isValid() and layer.crs().isValid():
                return layer.crs()
        return project_crs

    def combined_extent(
        self,
        layers: Iterable[QgsMapLayer],
        *,
        target_crs=None,
        margin_ratio: float = 0.0,
    ) -> QgsRectangle | None:
        layer_list = list(layers)
        target_crs = target_crs or self.display_crs(layer_list)
        result: QgsRectangle | None = None
        for layer in layer_list:
            if not layer or not layer.isValid():
                continue
            candidate = QgsRectangle(layer.extent())
            if candidate.isNull() or candidate.isEmpty():
                continue
            try:
                if layer.crs().isValid() and target_crs.isValid() and layer.crs() != target_crs:
                    transform = QgsCoordinateTransform(layer.crs(), target_crs, self.project)
                    candidate = transform.transformBoundingBox(candidate)
            except Exception:
                continue
            if result is None:
                result = QgsRectangle(candidate)
            else:
                result.combineExtentWith(candidate)
        if result and not result.isEmpty() and margin_ratio > 0:
            result = _expanded(result, margin_ratio)
        return result

    def preferred_extent(
        self,
        layers: Iterable[QgsMapLayer],
        margin_ratio: float = 0.03,
        *,
        target_crs=None,
    ) -> QgsRectangle:
        layer_list = list(layers)
        target_crs = target_crs or self.display_crs(layer_list)
        canvas = self.iface.mapCanvas()
        canvas_extent = QgsRectangle(canvas.extent())
        if not canvas_extent.isNull() and not canvas_extent.isEmpty():
            try:
                canvas_crs = canvas.mapSettings().destinationCrs()
                if canvas_crs.isValid() and target_crs.isValid() and canvas_crs != target_crs:
                    transform = QgsCoordinateTransform(canvas_crs, target_crs, self.project)
                    canvas_extent = transform.transformBoundingBox(canvas_extent)
                return _expanded(canvas_extent, margin_ratio)
            except Exception:
                pass
        combined = self.combined_extent(layer_list, target_crs=target_crs, margin_ratio=margin_ratio)
        if combined and not combined.isEmpty():
            return combined
        if target_crs.isValid() and target_crs.isGeographic():
            return QgsRectangle(-180.0, -90.0, 180.0, 90.0)
        return QgsRectangle(0.0, 0.0, 1_000_000.0, 1_000_000.0)

    def project_extent(self, margin_ratio: float = 0.08, *, target_crs=None) -> QgsRectangle:
        layers = self.ordered_layers()
        target_crs = target_crs or self.display_crs(layers)
        combined = self.combined_extent(layers, target_crs=target_crs, margin_ratio=margin_ratio)
        if combined and not combined.isEmpty():
            return combined
        return self.preferred_extent(self.visible_layers(), margin_ratio, target_crs=target_crs)

    def zoom_to_layer(self, layer: QgsMapLayer) -> None:
        if not layer or not layer.isValid():
            return
        canvas = self.iface.mapCanvas()
        extent = self.combined_extent([layer], target_crs=canvas.mapSettings().destinationCrs(), margin_ratio=0.03)
        if extent and not extent.isEmpty():
            canvas.setExtent(extent)
            canvas.refresh()

    def summary(self) -> ProjectSummary:
        layers = self.ordered_layers()
        visible = self.visible_layers()
        vectors = sum(isinstance(layer, QgsVectorLayer) for layer in layers)
        rasters = sum(isinstance(layer, QgsRasterLayer) for layer in layers)
        invalid = sum(not layer.isValid() for layer in layers)
        extent = self.combined_extent(layers)
        extent_text = "Non disponible"
        if extent and not extent.isEmpty():
            extent_text = (
                f"{extent.xMinimum():.3f}, {extent.yMinimum():.3f} à "
                f"{extent.xMaximum():.3f}, {extent.yMaximum():.3f}"
            )
        crs = self.project.crs()
        return ProjectSummary(
            layer_count=len(layers),
            visible_count=len(visible),
            vector_count=vectors,
            raster_count=rasters,
            invalid_count=invalid,
            project_crs=crs.authid() or crs.description() or "Non défini",
            extent_text=extent_text,
        )


def _expanded(rect: QgsRectangle, ratio: float) -> QgsRectangle:
    result = QgsRectangle(rect)
    dx = max(abs(result.width()) * ratio, 1e-9)
    dy = max(abs(result.height()) * ratio, 1e-9)
    result.grow(max(dx, dy))
    return result
