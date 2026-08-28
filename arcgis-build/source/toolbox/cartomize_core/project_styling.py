"""Application des styles recommandés au projet."""

from dataclasses import dataclass

from .raster_symbology import RasterSymbologyService
from .symbology import SmartSymbologyService
from .symbology import apply_raster_symbology, apply_vector_symbology


def apply_recommendation(aprx, layer, analysis):
    if getattr(layer, "isRasterLayer", False):
        return apply_raster_symbology(aprx, layer, analysis)
    return apply_vector_symbology(aprx, layer, analysis)


@dataclass(frozen=True)
class StylingDecision:
    layer_id: str; layer_name: str; role: str; mode: str; confidence: float
    explanation: str; applied: bool; warning: str = ""


class ProjectStylingOrchestrator:
    def __init__(self, project=None, vector_service: SmartSymbologyService | None = None, raster_service: RasterSymbologyService | None = None):
        self.project = project; self.vector_service = vector_service or SmartSymbologyService(project); self.raster_service = raster_service or RasterSymbologyService(project)

    def apply_project(self, layers, *, main_layer_id: str, objective: str, force: bool = True, roles: dict[str, str] | None = None, vector_profiles: dict[str, object] | None = None):
        decisions = []
        for layer in layers:
            key = _key(layer); role = "principal" if key == main_layer_id else (roles or {}).get(key, "contexte")
            if _protected(layer):
                decisions.append(StylingDecision(key, str(layer.name), role, "contexte", 1.0, "Fond cartographique conservé.", False)); continue
            try:
                if getattr(layer, "isRasterLayer", False):
                    recommendation = self.raster_service.recommend(layer, objective); result = self.raster_service.apply(layer, recommendation, objective); mode, confidence = recommendation.mode, recommendation.confidence
                else:
                    profile = (vector_profiles or {}).get(key)
                    recommendation = self.vector_service.recommend_from_profile(layer, profile) if profile is not None else self.vector_service.recommend(layer)
                    result = self.vector_service.apply(layer, recommendation); mode, confidence = recommendation.mode, recommendation.confidence
                applied = bool(result.get("applied", result) if isinstance(result, dict) else result)
                decisions.append(StylingDecision(key, str(layer.name), role, mode, confidence, "Recommandation Cartomize appliquée." if applied else "Style conservé.", applied, "" if applied else str(result.get("reason", "")) if isinstance(result, dict) else ""))
            except Exception as exc:
                decisions.append(StylingDecision(key, str(getattr(layer, "name", "Couche")), role, "inchangé", 0.0, "Style conservé.", False, str(exc)))
        return tuple(decisions)

    def undo_layer(self, layer):
        return self.raster_service.undo_last(layer) if getattr(layer, "isRasterLayer", False) else self.vector_service.undo_last(layer)
    def undo_project(self, layers): return tuple(self.undo_layer(layer) for layer in layers)


def _key(layer): return str(getattr(layer, "URI", "") or getattr(layer, "name", "") or layer)
def _protected(layer):
    name = str(getattr(layer, "name", "")).casefold(); source = str(getattr(layer, "dataSource", "")).casefold()
    return any(token in name or token in source for token in ("basemap", "fond de carte", "world topo", "world imagery", "hillshade", "mapserver"))
