"""Orchestration cohérente de la symbologie de toutes les couches du projet."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsFillSymbol,
    QgsLineSymbol,
    QgsMapLayerStyle,
    QgsMarkerSymbol,
    QgsProject,
    QgsRasterLayer,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
    QgsWkbTypes,
)

from .raster_symbology import RasterSymbologyService
from .symbology import SmartSymbologyService


@dataclass(frozen=True)
class StylingDecision:
    layer_id: str
    layer_name: str
    role: str
    mode: str
    confidence: float
    explanation: str
    applied: bool
    warning: str = ""


class ProjectStylingOrchestrator:
    """Construit une hiérarchie visuelle multi-couches sans quitter QGIS."""

    def __init__(
        self,
        project: QgsProject | None = None,
        vector_service: SmartSymbologyService | None = None,
        raster_service: RasterSymbologyService | None = None,
    ):
        self.project = project or QgsProject.instance()
        self.vector = vector_service or SmartSymbologyService(self.project)
        self.raster = raster_service or RasterSymbologyService(self.project)
        self._history: dict[str, list[QgsMapLayerStyle]] = {}

    def apply_project(
        self,
        layers: Iterable,
        *,
        main_layer_id: str,
        objective: str,
        force: bool = True,
        roles: dict[str, str] | None = None,
        vector_profiles: dict[str, object] | None = None,
    ) -> tuple[StylingDecision, ...]:
        decisions: list[StylingDecision] = []
        roles = roles or {}
        vector_profiles = vector_profiles or {}
        for layer in layers:
            if not layer or not layer.isValid():
                continue
            role = "principal" if layer.id() == main_layer_id else roles.get(layer.id(), self._role(layer))
            try:
                if isinstance(layer, QgsRasterLayer):
                    recommendation = self.raster.recommend(layer, objective)
                    if force or role == "principal" or self._is_default_raster_style(layer):
                        self.raster.apply(layer, recommendation, objective)
                        applied = True
                    else:
                        applied = False
                    decisions.append(
                        StylingDecision(
                            layer.id(), layer.name(), role, recommendation.summary(),
                            recommendation.confidence,
                            " ".join(recommendation.rationale), applied,
                        )
                    )
                    continue
                if isinstance(layer, QgsVectorLayer):
                    if role != "principal":
                        self._snapshot(layer)
                    if role != "principal" and self._apply_context_style(layer, role):
                        decisions.append(
                            StylingDecision(
                                layer.id(), layer.name(), role, "Style contextuel",
                                0.88,
                                "Le style renforce la hiérarchie entre la couche principale et les couches de contexte.",
                                True,
                            )
                        )
                    else:
                        recommendation = self.vector.recommend_from_profile(
                            layer, vector_profiles.get(layer.id())
                        )
                        self.vector.apply(layer, recommendation)
                        decisions.append(
                            StylingDecision(
                                layer.id(), layer.name(), role, recommendation.summary(),
                                recommendation.confidence,
                                " ".join(recommendation.rationale), True,
                            )
                        )
            except Exception as exc:
                decisions.append(
                    StylingDecision(
                        layer.id(), layer.name(), role, "Non modifié", 0.0,
                        "La couche conserve son style actuel.", False, str(exc),
                    )
                )
        self.project.setDirty(True)
        return tuple(decisions)


    def undo_layer(self, layer) -> bool:
        """Restaure le dernier style, y compris les styles contextuels Autopilot."""
        history = self._history.get(layer.id()) or []
        if history:
            history.pop().writeToLayer(layer)
            layer.triggerRepaint()
            self.project.setDirty(True)
            return True
        if isinstance(layer, QgsRasterLayer):
            return self.raster.undo_last(layer)
        if isinstance(layer, QgsVectorLayer):
            return self.vector.undo_last(layer)
        return False

    def undo_project(self, layers: Iterable) -> int:
        """Restaure au plus un style par couche et retourne le nombre de restaurations."""
        restored = 0
        for layer in layers:
            if layer is not None and self.undo_layer(layer):
                restored += 1
        return restored

    def _snapshot(self, layer: QgsVectorLayer) -> None:
        style = QgsMapLayerStyle()
        style.readFromLayer(layer)
        history = self._history.setdefault(layer.id(), [])
        history.append(style)
        del history[:-10]

    @staticmethod
    def _role(layer) -> str:
        name = f"{layer.name()} {layer.source()}".casefold()
        if any(token in name for token in ("route", "road", "rail", "transport")):
            return "transport"
        if any(token in name for token in ("riv", "fleuve", "hydro", "water", "eau", "lac")):
            return "hydrographie"
        if any(token in name for token in ("ville", "city", "village", "localite", "localité", "chef lieu")):
            return "localités"
        if any(token in name for token in ("limite", "boundary", "province", "district", "commune", "departement")):
            return "limites"
        return "contexte"

    @staticmethod
    def _apply_context_style(layer: QgsVectorLayer, role: str) -> bool:
        geometry = QgsWkbTypes.geometryType(layer.wkbType())
        symbol = None
        if geometry == QgsWkbTypes.LineGeometry:
            color = "#2563eb" if role == "hydrographie" else "#6b7280"
            width = "0.65" if role == "transport" else "0.45"
            symbol = QgsLineSymbol.createSimple({"color": color, "width": width, "capstyle": "round"})
        elif geometry == QgsWkbTypes.PolygonGeometry and role == "limites":
            symbol = QgsFillSymbol.createSimple({
                "color": "255,255,255,0",
                "outline_color": "#374151",
                "outline_width": "0.55",
                "outline_style": "solid",
            })
        elif geometry == QgsWkbTypes.PointGeometry and role == "localités":
            symbol = QgsMarkerSymbol.createSimple({
                "name": "circle",
                "color": "#111827",
                "outline_color": "#ffffff",
                "outline_width": "0.35",
                "size": "2.2",
            })
        if symbol is None:
            return False
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        layer.setCustomProperty("cartomize/advisor_mode", "Style contextuel")
        layer.setCustomProperty("cartomize/advisor_role", role)
        layer.triggerRepaint()
        return True

    @staticmethod
    def _is_default_raster_style(layer: QgsRasterLayer) -> bool:
        renderer = layer.renderer()
        if renderer is None:
            return True
        name = renderer.type().casefold() if hasattr(renderer, "type") else ""
        return name in {"singlebandgray", "multibandcolor", ""}
