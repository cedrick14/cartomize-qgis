"""Orchestration globale de l'intelligence raster, vectorielle et cartographique."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from qgis.core import QgsLayoutItemMap, QgsProject, QgsRasterLayer, QgsVectorLayer

from .label_intelligence import LabelIntelligenceEngine, LabelRecommendation
from .local_memory import LocalPreferenceMemory
from .project_graph import ProjectRelationshipEngine, ProjectRelationshipGraph
from .raster_intelligence import RasterIntelligenceEngine
from .scale_intelligence import ScaleIntelligenceEngine, ScaleRecommendation
from .vector_intelligence import VectorIntelligenceEngine, VectorLayerProfile


@dataclass(frozen=True)
class RasterSummary:
    layer_id: str
    name: str
    raster_type: str
    confidence: float
    class_count: int
    nodata_candidates: int
    anomalies: int
    recommended_renderer: str

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class GeoIntelligenceReport:
    roles: dict[str, str]
    vector_profiles: tuple[VectorLayerProfile, ...]
    raster_summaries: tuple[RasterSummary, ...]
    graph: ProjectRelationshipGraph
    scale_recommendations: tuple[ScaleRecommendation, ...]
    label_recommendations: tuple[LabelRecommendation, ...]
    data_quality_score: int
    automation_confidence: int
    warnings: tuple[str, ...]
    memory_suggestions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "roles": dict(self.roles),
            "vector_profiles": [item.to_dict() for item in self.vector_profiles],
            "raster_summaries": [item.to_dict() for item in self.raster_summaries],
            "graph": self.graph.to_dict(),
            "scale_recommendations": [item.to_dict() for item in self.scale_recommendations],
            "label_recommendations": [item.to_dict() for item in self.label_recommendations],
            "data_quality_score": self.data_quality_score,
            "automation_confidence": self.automation_confidence,
            "warnings": list(self.warnings),
            "memory_suggestions": list(self.memory_suggestions),
        }


class GeoIntelligenceEngine:
    """Comprend le projet avant toute décision de symbologie ou de mise en page."""

    def __init__(self, iface, project: QgsProject | None = None):
        self.iface = iface
        self.project = project or QgsProject.instance()
        self.vector = VectorIntelligenceEngine()
        self.raster = RasterIntelligenceEngine(self.project)
        self.graph = ProjectRelationshipEngine(self.project)
        self.scale = ScaleIntelligenceEngine()
        self.labels = LabelIntelligenceEngine()
        self.memory = LocalPreferenceMemory()

    def analyze(self, layers: Iterable, *, main_layer_id: str, objective: str) -> GeoIntelligenceReport:
        layer_list = [layer for layer in layers if layer is not None and layer.isValid()]
        vector_profiles: list[VectorLayerProfile] = []
        raster_summaries: list[RasterSummary] = []
        roles: dict[str, str] = {}
        warnings: list[str] = []
        confidence_values: list[float] = []

        for layer in layer_list:
            if layer.id() == main_layer_id:
                roles[layer.id()] = "principal"
            if isinstance(layer, QgsVectorLayer):
                try:
                    profile = self.vector.analyze(layer)
                    vector_profiles.append(profile)
                    roles.setdefault(layer.id(), profile.role)
                    confidence_values.append(profile.role_confidence)
                    warnings.extend(f"{profile.name} : {warning}" for warning in profile.warnings)
                except Exception as exc:
                    roles.setdefault(layer.id(), "contexte")
                    warnings.append(f"{layer.name()} : analyse vectorielle partielle ({exc}).")
            elif isinstance(layer, QgsRasterLayer):
                try:
                    diagnosis = self.raster.analyze(layer, deep=False)
                    raster_summaries.append(
                        RasterSummary(
                            str(layer.id()), str(layer.name()), diagnosis.inference.raster_type,
                            float(diagnosis.inference.confidence), len(diagnosis.classes),
                            len(diagnosis.recommended_nodata), len(diagnosis.anomalies),
                            str(diagnosis.inference.recommended_renderer),
                        )
                    )
                    confidence_values.append(float(diagnosis.inference.confidence))
                    roles.setdefault(layer.id(), _raster_role(diagnosis.inference.raster_type, objective))
                    if diagnosis.recommended_nodata:
                        warnings.append(f"{layer.name()} : NoData implicite possible à valider.")
                    if diagnosis.anomalies:
                        warnings.append(f"{layer.name()} : {len(diagnosis.anomalies)} valeur(s) atypique(s) à vérifier.")
                except Exception as exc:
                    roles.setdefault(layer.id(), "raster_contexte")
                    warnings.append(f"{layer.name()} : analyse raster partielle ({exc}).")
            else:
                roles.setdefault(layer.id(), "contexte")
        if main_layer_id:
            roles[main_layer_id] = "principal"

        graph = self.graph.analyze(layer_list, roles=roles, main_layer_id=main_layer_id)
        scale_value = self._map_scale()
        scale_recommendations = self.scale.analyze_project(layer_list, roles, scale_value)
        scale_by_id = {item.layer_id: item for item in scale_recommendations}
        label_recommendations: list[LabelRecommendation] = []
        for profile in vector_profiles:
            layer = self.project.mapLayer(profile.layer_id)
            if layer is None:
                continue
            scale_rec = scale_by_id.get(profile.layer_id)
            density = scale_rec.label_density if scale_rec else 1.0
            label_recommendations.append(
                self.labels.recommend(
                    layer,
                    role=roles.get(profile.layer_id, profile.role),
                    label_field=profile.label_field,
                    scale=scale_value,
                    density=density,
                )
            )

        quality = self._data_quality(vector_profiles, raster_summaries, warnings)
        confidence = int(round(100 * (sum(confidence_values) / max(1, len(confidence_values))))) if confidence_values else 60
        confidence = max(0, min(100, confidence))
        memory_suggestions: list[str] = []
        for key in ("template_id", "style_profile", "page_format"):
            suggestion = self.memory.suggest(objective, key)
            if suggestion and suggestion.confidence >= 0.6:
                memory_suggestions.append(f"{key} : {suggestion.value}. {suggestion.explanation}")

        return GeoIntelligenceReport(
            roles=roles,
            vector_profiles=tuple(vector_profiles),
            raster_summaries=tuple(raster_summaries),
            graph=graph,
            scale_recommendations=scale_recommendations,
            label_recommendations=tuple(label_recommendations),
            data_quality_score=quality,
            automation_confidence=confidence,
            warnings=tuple(dict.fromkeys(warnings))[:30],
            memory_suggestions=tuple(memory_suggestions),
        )

    def apply_labeling(self, report: GeoIntelligenceReport) -> tuple[str, ...]:
        changes: list[str] = []
        for recommendation in report.label_recommendations:
            layer = self.project.mapLayer(recommendation.layer_id)
            if not isinstance(layer, QgsVectorLayer):
                continue
            try:
                if self.labels.apply(layer, recommendation):
                    changes.append(f"étiquetage {layer.name()}")
            except Exception:
                continue
        if changes:
            self.project.setDirty(True)
        return tuple(changes)

    def apply_layout_scale(self, layout, report: GeoIntelligenceReport) -> tuple[str, ...]:
        """Réévalue l’étiquetage avec l’échelle réelle du cadre principal."""
        scale_value = 0.0
        try:
            maps = [item for item in layout.items() if isinstance(item, QgsLayoutItemMap)]
            main = next((item for item in maps if str(item.customProperty("cartomize/role", "main")) == "main"), maps[0] if maps else None)
            if main is not None:
                scale_value = float(main.scale())
        except Exception:
            scale_value = 0.0
        if scale_value <= 0:
            return ()
        profiles = {item.layer_id: item for item in report.vector_profiles}
        changes: list[str] = []
        for layer_id, profile in profiles.items():
            layer = self.project.mapLayer(layer_id)
            if not isinstance(layer, QgsVectorLayer):
                continue
            role = report.roles.get(layer_id, profile.role)
            scale_rec = self.scale.analyze_layer(layer, role, scale_value)
            recommendation = self.labels.recommend(
                layer, role=role, label_field=profile.label_field,
                scale=scale_value, density=scale_rec.label_density,
            )
            try:
                if recommendation.enabled and scale_rec.visible and self.labels.apply(layer, recommendation):
                    changes.append(f"étiquetage {layer.name()} à 1:{scale_value:,.0f}")
                elif not scale_rec.visible:
                    layer.setCustomProperty("cartomize/scale_visibility_recommendation", "masquer à cette échelle")
            except Exception:
                continue
        return tuple(changes)

    def remember_accepted_layout(self, *, objective: str, template_id: str, style_profile: str, page_format: str) -> None:
        self.memory.record(
            objective,
            template_id=template_id,
            style_profile=style_profile,
            page_format=page_format,
        )

    def label_audit(self):
        return self.labels.audit_canvas(self.iface)

    def _map_scale(self) -> float:
        try:
            scale = float(self.iface.mapCanvas().scale())
            if scale > 0:
                return scale
        except Exception:
            pass
        return 500_000.0

    @staticmethod
    def _data_quality(vectors, rasters, warnings) -> int:
        score = 100
        for profile in vectors:
            if profile.invalid_geometry_count:
                score -= min(18, 3 + profile.invalid_geometry_count)
            if profile.empty_geometry_count:
                score -= min(10, 2 + profile.empty_geometry_count)
            if profile.duplicate_geometry_count:
                score -= min(8, 1 + profile.duplicate_geometry_count)
            if not profile.crs:
                score -= 20
        for raster in rasters:
            if raster.nodata_candidates:
                score -= min(8, raster.nodata_candidates * 2)
            if raster.anomalies:
                score -= min(10, raster.anomalies * 2)
        score -= min(10, max(0, len(warnings) - 3))
        return max(0, min(100, score))


def _raster_role(raster_type: str, objective: str) -> str:
    if objective in {"occupation_sol", "topographique", "environnement", "risques"}:
        return objective
    if raster_type in {"categorized", "binary"}:
        return "occupation_sol"
    if raster_type in {"rgb", "multiband"}:
        return "raster_contexte"
    return "raster_thématique"
