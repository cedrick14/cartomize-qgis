"""Application réversible de symbologies natives ArcGIS Pro."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .raster_themes import theme_profile


_ESRI_RAMP_HINTS = {
    "land_cover": "Green to Yellow to Red",
    "forest_dynamics": "Green to Red",
    "deforestation": "Green to Red",
    "forest_degradation": "Green to Red",
    "land_cover_change": "Green to Red",
    "ndvi": "Red to Green",
    "elevation": "Elevation #1",
    "slope": "Yellow to Red",
    "temperature": "Cold to Hot",
    "precipitation": "Blues",
    "risk": "Yellow to Red",
    "probability": "Blues",
    "continuous": "Viridis",
}

_PALETTE_RAMPS = {
    "qualitative": "Basic Random",
    "séquentielle": "Blues",
    "sequentielle": "Blues",
    "sequential": "Blues",
    "divergente": "Green to Red",
    "diverging": "Green to Red",
}


@dataclass(frozen=True)
class SymbologyRecommendation:
    mode: str
    field_name: str
    label_field: str
    class_count: int
    palette: str
    rationale: tuple[str, ...]
    confidence: float
    labels_enabled: bool = True
    label_font_size_pt: float = 9.0
    label_placement: str = "auto"
    opacity_percent: int = 100
    expert_confirmed: bool = False

    def summary(self) -> str:
        field = f", champ « {self.field_name} »" if self.field_name else ""
        return f"{self.mode}{field}"


def apply_vector_symbology(
    aprx: Any, layer: Any, profile: dict[str, Any], class_count: int = 7, *,
    mode: str = "", field_name: str = "", palette: str = "",
    label_field: str = "", labels_enabled: bool | None = None,
    label_size: float = 9.0, label_placement: str = "auto",
    opacity_percent: int = 100, expert_confirmed: bool = False,
) -> dict[str, Any]:
    field = str(field_name or profile.get("thematic_field") or "")
    mode_key = str(mode or "").strip().casefold()
    single = mode_key in {"symbole unique", "single", "single_symbol"}
    if not field and not single:
        return {"applied": False, "reason": "Aucun champ thématique fiable n'a été identifié."}
    field_profile = next((item for item in profile.get("fields", []) if item.get("name") == field), {})
    role = field_profile.get("semantic_role")
    sym = layer.symbology
    if not hasattr(sym, "renderer"):
        return {"applied": False, "reason": "Le type de couche n'expose pas de moteur de rendu pris en charge."}
    categorized = mode_key in {"catégorisé", "categorise", "categorize", "categorized"} or (not mode_key and role in {"category", "coded_category"})
    if single:
        sym.updateRenderer("SimpleRenderer")
        renderer = "SimpleRenderer"
    elif categorized:
        sym.updateRenderer("UniqueValueRenderer")
        sym.renderer.fields = [field]
        renderer = "UniqueValueRenderer"
    else:
        sym.updateRenderer("GraduatedColorsRenderer")
        sym.renderer.classificationField = field
        sym.renderer.breakCount = max(3, min(12, int(class_count)))
        sym.renderer.classificationMethod = "Quantile" if "quantile" in mode_key else "NaturalBreaks"
        ramp_name = _PALETTE_RAMPS.get(str(palette).strip().casefold(), "Green to Yellow to Red")
        ramps = aprx.listColorRamps(ramp_name) or aprx.listColorRamps()
        if ramps:
            sym.renderer.colorRamp = ramps[0]
        renderer = "GraduatedColorsRenderer"
    layer.symbology = sym
    label_field = str(label_field or profile.get("label_field") or "")
    labels_applied = False
    enable_labels = bool(label_field) if labels_enabled is None else bool(labels_enabled)
    if label_field and enable_labels:
        try:
            classes = list(layer.listLabelClasses())
            if classes:
                classes[0].expression = f"$feature.{label_field}"
                if hasattr(classes[0], "visible"):
                    classes[0].visible = True
                layer.showLabels = True
                labels_applied = True
                _apply_label_cim(layer, label_size, label_placement)
        except Exception:
            pass
    elif hasattr(layer, "showLabels"):
        try:
            layer.showLabels = False
        except Exception:
            pass
    opacity = max(0, min(100, int(opacity_percent)))
    try:
        layer.transparency = 100 - opacity
    except Exception:
        pass
    return {
        "applied": True,
        "field": field,
        "renderer": renderer,
        "label_field": label_field,
        "labels_applied": labels_applied,
        "class_count": max(1, int(class_count)),
        "palette": palette,
        "label_size": float(label_size),
        "label_placement": label_placement,
        "opacity_percent": opacity,
        "expert_confirmed": bool(expert_confirmed),
    }


def apply_raster_symbology(aprx: Any, layer: Any, diagnosis: dict[str, Any], class_count: int = 7, *, palette: str = "", opacity_percent: int = 100, expert_confirmed: bool = False) -> dict[str, Any]:
    sym = layer.symbology
    if not hasattr(sym, "colorizer"):
        return {"applied": False, "reason": "Le raster n'expose pas de coloriseur modifiable."}
    raster_type = diagnosis.get("raster_type")
    if raster_type == "rgb":
        return {"applied": False, "reason": "La composition RGB existante est conservée par sécurité."}
    colorizer = "RasterUniqueValueColorizer" if raster_type in {"binary", "categorized"} else "RasterClassifyColorizer"
    try:
        sym.updateColorizer(colorizer)
    except Exception:
        return {"applied": False, "reason": f"ArcGIS Pro n'a pas pu activer {colorizer}."}
    if colorizer == "RasterClassifyColorizer":
        sym.colorizer.classificationField = "Value"
        theme = str(diagnosis.get("theme") or "continuous")
        profile = theme_profile(theme)
        preferred = class_count or profile.preferred_class_count
        sym.colorizer.breakCount = max(3, min(12, int(preferred)))
        ramp_name = _PALETTE_RAMPS.get(str(palette).strip().casefold(), _ESRI_RAMP_HINTS.get(theme, "Viridis"))
        ramps = aprx.listColorRamps(ramp_name) or aprx.listColorRamps()
        if ramps:
            sym.colorizer.colorRamp = ramps[0]
    layer.symbology = sym
    opacity = max(0, min(100, int(opacity_percent)))
    try:
        layer.transparency = 100 - opacity
    except Exception:
        pass
    return {"applied": True, "colorizer": colorizer, "theme": diagnosis.get("theme"), "class_count": int(class_count), "palette": palette, "opacity_percent": opacity, "expert_confirmed": bool(expert_confirmed)}


class SmartSymbologyService:
    def __init__(self, project=None, *, arcpy_module=None):
        self.project = project
        self.arcpy = arcpy_module
        self._history: dict[str, Any] = {}

    def recommend(self, layer) -> SymbologyRecommendation:
        from .vector_intelligence import VectorIntelligenceEngine
        return self.recommend_from_profile(layer, VectorIntelligenceEngine(self.arcpy).analyze(layer))

    def recommend_from_profile(self, layer, profile) -> SymbologyRecommendation:
        payload = profile.to_dict() if hasattr(profile, "to_dict") else dict(profile)
        field = str(payload.get("thematic_field") or "")
        field_info = next((item for item in payload.get("fields", ()) if item.get("name") == field), {})
        role = str(field_info.get("semantic_role") or "")
        mode = "Catégorisé" if role in {"category", "coded_category"} else "Gradué — quantiles" if field else "Symbole unique"
        return SymbologyRecommendation(mode, field, str(payload.get("label_field") or ""), 5, "Qualitative" if mode == "Catégorisé" else "Séquentielle", tuple(payload.get("warnings", ())), float(payload.get("role_confidence", .6)), bool(payload.get("label_field")))

    def apply(self, layer, recommendation: SymbologyRecommendation | None = None):
        recommendation = recommendation or self.recommend(layer)
        self._history[_layer_key(layer)] = getattr(layer, "symbology", None)
        aprx = self.project
        if aprx is None:
            arcpy_module = self.arcpy
            if arcpy_module is None:
                import arcpy as arcpy_module
            aprx = arcpy_module.mp.ArcGISProject("CURRENT")
        profile = {"thematic_field": recommendation.field_name, "label_field": recommendation.label_field, "fields": []}
        return apply_vector_symbology(aprx, layer, profile, recommendation.class_count, mode=recommendation.mode, field_name=recommendation.field_name, palette=recommendation.palette, label_field=recommendation.label_field, labels_enabled=recommendation.labels_enabled, label_size=recommendation.label_font_size_pt, label_placement=recommendation.label_placement, opacity_percent=recommendation.opacity_percent, expert_confirmed=recommendation.expert_confirmed)

    def undo_last(self, layer) -> bool:
        previous = self._history.pop(_layer_key(layer), None)
        if previous is None: return False
        try:
            layer.symbology = previous; return True
        except Exception:
            return False


def _layer_key(layer) -> str: return str(getattr(layer, "URI", "") or getattr(layer, "name", "") or layer)


def _apply_label_cim(layer, size: float, placement: str) -> None:
    try:
        cim = layer.getDefinition("V3")
        for label_class in list(getattr(cim, "labelClasses", ()) or ()):
            symbol = getattr(getattr(label_class, "textSymbol", None), "symbol", None)
            if symbol is not None and hasattr(symbol, "height"): symbol.height = max(5.0, min(48.0, float(size)))
            if hasattr(label_class, "labelPlacement"): label_class.labelPlacement = str(placement or "auto")
        layer.setDefinition(cim)
    except Exception:
        pass
