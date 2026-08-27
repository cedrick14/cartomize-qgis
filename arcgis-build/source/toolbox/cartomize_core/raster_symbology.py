"""Façade de symbologie raster native ArcGIS Pro."""

from dataclasses import dataclass, replace

from .raster_intelligence import RasterClassDefinition, RasterIntelligenceEngine
from .raster_themes import theme_profile
from .symbology import apply_raster_symbology


@dataclass(frozen=True)
class RasterSymbologyRecommendation:
    mode: str; theme: str; band: int; minimum: float | None; maximum: float | None; class_count: int
    palette: tuple[str, ...]; labels: tuple[str, ...]; confidence: float; rationale: tuple[str, ...]
    red_band: int = 1; green_band: int = 2; blue_band: int = 3; class_values: tuple[float, ...] = ()
    class_value_groups: tuple[tuple[float, ...], ...] = (); class_opacities: tuple[float, ...] = (); nodata_values: tuple[float, ...] = ()
    classification_method: str = "equal_interval"; expert_confirmed: bool = False; sample_quantiles: tuple[tuple[float, float], ...] = ()
    theme_label: str = ""; theme_source: str = "automatic"; compatibility_warning: str = ""
    def summary(self) -> str:
        if self.mode == "rgb": return f"Composition RGB {self.red_band}/{self.green_band}/{self.blue_band}"
        if self.mode == "categorical": return f"Raster catégoriel, bande {self.band}, {self.class_count} classes"
        return f"{self.theme.replace('_', ' ').title()}, bande {self.band}"


class RasterSymbologyService:
    def __init__(self, project=None, *, arcpy_module=None):
        self.project = project; self.arcpy = arcpy_module; self._history = {}; self._preview = {}

    def recommend(self, layer, objective: str = "auto") -> RasterSymbologyRecommendation:
        diagnosis = RasterIntelligenceEngine(self.project, arcpy_module=self.arcpy).analyze(layer)
        return self.recommend_from_diagnosis(layer, diagnosis, objective)

    def recommend_from_diagnosis(self, layer, diagnosis, objective: str = "auto") -> RasterSymbologyRecommendation:
        payload = diagnosis.to_dict() if hasattr(diagnosis, "to_dict") else dict(diagnosis)
        inference = payload.get("inference", {})
        inspection = payload.get("inspection", {})
        raster_type = str(inference.get("raster_type") or payload.get("raster_type") or "continuous")
        mode = "rgb" if raster_type == "rgb" else "categorical" if raster_type in {"binary", "categorized"} else "continuous"
        theme = str(payload.get("theme") or (objective if objective != "auto" else "continuous"))
        classes = payload.get("classes", ())
        palette = tuple(str(item.get("color", "#808080")) for item in classes)
        labels = tuple(str(item.get("label", "Classe")) for item in classes)
        values = tuple(float(item.get("values", [0])[0]) for item in classes if item.get("values"))
        return RasterSymbologyRecommendation(mode, theme, int(inspection.get("analyzed_band", 1)), payload.get("minimum"), payload.get("maximum"), max(1, len(classes) or 5), palette, labels, float(inference.get("confidence", payload.get("confidence", .6))), tuple(inference.get("rationale", payload.get("rationale", ()))), class_values=values, sample_quantiles=tuple(tuple(item) for item in inspection.get("sample_quantiles", ())), theme_label=theme.replace("_", " ").title())

    def manual_recommendation_from_diagnosis(self, layer, diagnosis, theme_key: str):
        return replace(self.recommend_from_diagnosis(layer, diagnosis, theme_key), theme=theme_key, theme_source="manual", expert_confirmed=True)

    def class_definitions_for_theme(self, diagnosis, theme_key: str):
        profile = theme_profile(theme_key)
        classes = tuple(getattr(profile, "classes", ()) or ())
        return tuple(RasterClassDefinition((float(index),), item.label, item.color, 0, 0, 0, source="theme") for index, item in enumerate(classes, 1))

    @staticmethod
    def theme_profiles():
        return tuple(theme_profile(key) for key in ("land_cover", "forest_dynamics", "deforestation", "ndvi", "elevation", "risk", "continuous"))

    def apply(self, layer, recommendation: RasterSymbologyRecommendation | None = None, objective: str = "auto"):
        recommendation = recommendation or self.recommend(layer, objective)
        self._history[_key(layer)] = getattr(layer, "symbology", None)
        aprx = self.project or _project(self.arcpy)
        return apply_raster_symbology(aprx, layer, {"raster_type": "rgb" if recommendation.mode == "rgb" else "categorized" if recommendation.mode == "categorical" else "continuous", "theme": recommendation.theme}, recommendation.class_count, palette=recommendation.theme, expert_confirmed=recommendation.expert_confirmed)

    def preview(self, layer, recommendation: RasterSymbologyRecommendation):
        self._preview[_key(layer)] = getattr(layer, "symbology", None); return self.apply(layer, recommendation)
    def cancel_preview(self, layer) -> bool:
        previous = self._preview.pop(_key(layer), None)
        if previous is None: return False
        try: layer.symbology = previous; return True
        except Exception: return False
    def undo_last(self, layer) -> bool:
        previous = self._history.pop(_key(layer), None)
        if previous is None: return False
        try: layer.symbology = previous; return True
        except Exception: return False


def _project(arcpy_module):
    if arcpy_module is None:
        import arcpy as arcpy_module
    return arcpy_module.mp.ArcGISProject("CURRENT")
def _key(layer): return str(getattr(layer, "URI", "") or getattr(layer, "name", "") or layer)


__all__ = ["RasterSymbologyRecommendation", "RasterSymbologyService", "apply_raster_symbology"]
