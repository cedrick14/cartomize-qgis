"""Analyse et réglage intelligent des étiquettes QGIS."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from qgis.PyQt.QtGui import QColor
from qgis.core import (
    Qgis,
    QgsPalLayerSettings,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)


@dataclass(frozen=True)
class LabelRecommendation:
    layer_id: str
    field_name: str
    role: str
    enabled: bool
    priority: int
    font_size_pt: float
    placement: str
    density: float
    estimated_candidates: int
    confidence: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LabelPlacementAudit:
    total_positions: int
    placed: int
    unplaced: int
    per_layer: dict[str, dict[str, int]]
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LabelIntelligenceEngine:
    """Configure l’étiquetage de façon explicable et mesure le rendu réel du canevas."""

    def recommend(self, layer: QgsVectorLayer, *, role: str, label_field: str, scale: float, density: float = 1.0) -> LabelRecommendation:
        try:
            count = max(0, int(layer.featureCount()))
        except Exception:
            count = 0
        field_name = str(label_field or "")
        if not field_name or not isinstance(layer, QgsVectorLayer):
            return LabelRecommendation(str(layer.id()), field_name, role, False, 0, 0.0, "none", 0.0, 0, 0.85, "Aucun champ d’étiquette fiable n’a été identifié.")
        density = max(0.05, min(1.0, float(density or 1.0)))
        priority = {
            "principal": 9,
            "localités": 9,
            "limites": 7,
            "transport": 6,
            "hydrographie": 5,
            "points_thématiques": 6,
        }.get(role, 4)
        if scale >= 3_000_000:
            size = 10.5
        elif scale >= 800_000:
            size = 9.5
        elif scale >= 150_000:
            size = 9.0
        else:
            size = 8.5
        geometry = self._geometry_name(layer)
        placement = {"point": "around_point", "line": "curved", "polygon": "over_centroid"}.get(geometry, "around_point")
        candidates = min(count, max(1, round(count * density)))
        reason = f"Priorité {priority}/10 et densité {density:.0%} adaptées au rôle « {role} » et à l’échelle 1:{scale:,.0f}."
        return LabelRecommendation(str(layer.id()), field_name, role, True, priority, size, placement, density, candidates, 0.88, reason)

    def apply(self, layer: QgsVectorLayer, recommendation: LabelRecommendation) -> bool:
        if not recommendation.enabled or not recommendation.field_name:
            return False
        settings = QgsPalLayerSettings()
        settings.enabled = True
        settings.fieldName = recommendation.field_name
        settings.priority = int(max(0, min(10, recommendation.priority)))
        settings.placement = self._placement_enum(recommendation.placement)
        # Scale visibility is deliberately conservative. Autopilot controls density through
        # layer roles and the map composition instead of silently hiding labels at arbitrary scales.
        text_format = QgsTextFormat()
        text_format.setSize(float(recommendation.font_size_pt))
        text_format.setColor(QColor("#111827"))
        buffer = QgsTextBufferSettings()
        buffer.setEnabled(True)
        buffer.setSize(1.0)
        buffer.setColor(QColor("#ffffff"))
        text_format.setBuffer(buffer)
        settings.setFormat(text_format)
        layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
        layer.setLabelsEnabled(True)
        layer.setCustomProperty("cartomize/label_field", recommendation.field_name)
        layer.setCustomProperty("cartomize/label_role", recommendation.role)
        layer.setCustomProperty("cartomize/label_density", recommendation.density)
        layer.setCustomProperty("cartomize/label_confidence", recommendation.confidence)
        layer.triggerRepaint()
        return True

    @staticmethod
    def audit_canvas(iface) -> LabelPlacementAudit:
        try:
            canvas = iface.mapCanvas()
            results = canvas.labelingResults(False)
            if results is None:
                return LabelPlacementAudit(0, 0, 0, {}, "Rendu des étiquettes indisponible ou en cours.")
            positions = list(results.allLabels())
        except Exception:
            return LabelPlacementAudit(0, 0, 0, {}, "Résultats d’étiquetage indisponibles.")
        per_layer: dict[str, dict[str, int]] = {}
        placed = unplaced = 0
        for position in positions:
            layer_id = str(getattr(position, "layerID", "") or "")
            is_unplaced = bool(getattr(position, "isUnplaced", False))
            entry = per_layer.setdefault(layer_id, {"placed": 0, "unplaced": 0, "total": 0})
            entry["total"] += 1
            if is_unplaced:
                entry["unplaced"] += 1
                unplaced += 1
            else:
                entry["placed"] += 1
                placed += 1
        total = placed + unplaced
        ratio = unplaced / max(1, total)
        status = "Bon" if ratio <= 0.1 else "À optimiser" if ratio <= 0.3 else "Surchargé"
        return LabelPlacementAudit(total, placed, unplaced, per_layer, status)

    @staticmethod
    def _geometry_name(layer: QgsVectorLayer) -> str:
        try:
            geometry = layer.geometryType()
            # QGIS 3.40 returns Qgis.GeometryType, but integer values remain compatible.
            if int(geometry) == 0:
                return "point"
            if int(geometry) == 1:
                return "line"
            if int(geometry) == 2:
                return "polygon"
        except Exception:
            pass
        return "unknown"

    @staticmethod
    def _placement_enum(name: str):
        enum = getattr(Qgis, "LabelPlacement", None)
        if enum is not None:
            mapping = {
                "around_point": getattr(enum, "AroundPoint", 0),
                "curved": getattr(enum, "Curved", getattr(enum, "Line", 2)),
                "over_centroid": getattr(enum, "OverPoint", getattr(enum, "AroundPoint", 0)),
            }
            return mapping.get(name, mapping["around_point"])
        return getattr(QgsPalLayerSettings, "AroundPoint", 0)
