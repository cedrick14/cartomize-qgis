"""Analyse combinée du projet et des relations cartographiques."""

from dataclasses import dataclass
from typing import Any

from .audit import audit_project
from .label_intelligence import LabelIntelligenceEngine, LabelRecommendation, audit_labels
from .local_memory import LocalPreferenceMemory
from .project_graph import ProjectRelationshipEngine, ProjectRelationshipGraph
from .project_service import project_summary
from .raster_intelligence import RasterIntelligenceEngine
from .scale_intelligence import ScaleIntelligenceEngine, ScaleRecommendation
from .vector_intelligence import VectorIntelligenceEngine, VectorLayerProfile


def analyze_project(arcpy, aprx) -> dict[str, object]:
    report = audit_project(arcpy, aprx)
    return {"summary": project_summary(aprx), "audit": report.to_dict()}


@dataclass(frozen=True)
class RasterSummary:
    layer_id: str; name: str; raster_type: str; confidence: float; class_count: int
    nodata_candidates: int; anomalies: int; recommended_renderer: str
    def to_dict(self) -> dict[str, Any]: return self.__dict__.copy()


@dataclass(frozen=True)
class GeoIntelligenceReport:
    roles: dict[str, str]; vector_profiles: tuple[VectorLayerProfile, ...]; raster_summaries: tuple[RasterSummary, ...]
    graph: ProjectRelationshipGraph; scale_recommendations: tuple[ScaleRecommendation, ...]; label_recommendations: tuple[LabelRecommendation, ...]
    data_quality_score: int; automation_confidence: int; warnings: tuple[str, ...]; memory_suggestions: tuple[str, ...]
    def to_dict(self) -> dict[str, Any]:
        return {"roles": dict(self.roles), "vector_profiles": [item.to_dict() for item in self.vector_profiles], "raster_summaries": [item.to_dict() for item in self.raster_summaries], "graph": self.graph.to_dict(), "scale_recommendations": [item.to_dict() for item in self.scale_recommendations], "label_recommendations": [item.to_dict() for item in self.label_recommendations], "data_quality_score": self.data_quality_score, "automation_confidence": self.automation_confidence, "warnings": list(self.warnings), "memory_suggestions": list(self.memory_suggestions)}


class GeoIntelligenceEngine:
    def __init__(self, iface=None, project=None, *, arcpy_module=None):
        self.arcpy = arcpy_module or _import_arcpy(); self.project = project or self.arcpy.mp.ArcGISProject("CURRENT"); self.memory = LocalPreferenceMemory()

    def analyze(self, layers, *, main_layer_id: str, objective: str) -> GeoIntelligenceReport:
        layers = tuple(layer for layer in layers if layer is not None and not getattr(layer, "isBroken", False))
        roles = {_key(layer): "principal" if _key(layer) == main_layer_id else "contexte" for layer in layers}
        vectors, rasters, labels, warnings = [], [], [], []
        scale = self._map_scale()
        scale_engine, label_engine = ScaleIntelligenceEngine(), LabelIntelligenceEngine()
        for layer in layers:
            if getattr(layer, "isFeatureLayer", False):
                profile = VectorIntelligenceEngine(self.arcpy).analyze(layer); vectors.append(profile); warnings.extend(profile.warnings)
                labels.append(label_engine.recommend(layer, role=roles[_key(layer)], label_field=profile.label_field, scale=scale))
            elif getattr(layer, "isRasterLayer", False):
                diagnosis = RasterIntelligenceEngine(self.project, arcpy_module=self.arcpy).analyze(layer)
                rasters.append(RasterSummary(_key(layer), str(layer.name), diagnosis.inference.raster_type, diagnosis.inference.confidence, len(diagnosis.classes), len(diagnosis.recommended_nodata), len(diagnosis.anomalies), diagnosis.inference.recommended_renderer))
        graph = ProjectRelationshipEngine(self.arcpy).analyze(layers, roles=roles)
        scale_recommendations = scale_engine.analyze_project(layers, roles, scale)
        quality = max(0, min(100, 100 - 4 * len(warnings)))
        confidence_values = [item.role_confidence for item in vectors] + [item.confidence for item in rasters]
        confidence = round(100 * sum(confidence_values) / max(1, len(confidence_values)))
        suggestions = tuple(filter(None, (self.memory.suggest(objective, key).explanation if self.memory.suggest(objective, key) else "" for key in ("template_id", "style_profile", "page_format"))))
        return GeoIntelligenceReport(roles, tuple(vectors), tuple(rasters), graph, tuple(scale_recommendations), tuple(labels), quality, confidence, tuple(warnings), suggestions)

    def apply_labeling(self, report: GeoIntelligenceReport):
        by_id = {_key(layer): layer for map_item in self.project.listMaps() for layer in map_item.listLayers()}
        engine = LabelIntelligenceEngine(); return tuple(engine.apply(by_id[item.layer_id], item) for item in report.label_recommendations if item.layer_id in by_id)

    def apply_layout_scale(self, layout, report: GeoIntelligenceReport):
        scales = [item.scale for item in report.scale_recommendations if item.visible]
        if not scales: return False
        target = min(scales)
        for frame in layout.listElements("MAPFRAME_ELEMENT"):
            try: frame.camera.scale = target
            except Exception: pass
        return True

    def remember_accepted_layout(self, *, objective: str, template_id: str, style_profile: str, page_format: str):
        self.memory.record(objective, template_id=template_id, style_profile=style_profile, page_format=page_format)

    def label_audit(self): return audit_labels(self.project)

    def _map_scale(self) -> float:
        try:
            active = self.project.activeMap or self.project.listMaps()[0]
            return float(active.defaultCamera.scale or 100_000)
        except Exception:
            return 100_000.0


def _key(layer): return str(getattr(layer, "URI", "") or getattr(layer, "name", "") or layer)
def _import_arcpy():
    try:
        import arcpy; return arcpy
    except ImportError as exc: raise RuntimeError("ArcPy est requis pour l'analyse du projet.") from exc
