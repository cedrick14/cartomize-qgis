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

# Palette Cartomize 10.5.1 issue du service QGIS. ArcGIS Pro reçoit les
# mêmes couleurs ; seul l'objet renderer du SIG hôte change.
_QUALITATIVE = (
    "#1b9e77", "#d95f02", "#7570b3", "#e7298a", "#66a61e",
    "#e6ab02", "#a6761d", "#1f78b4", "#b2df8a", "#fb9a99",
    "#cab2d6", "#fdbf6f", "#6a3d9a", "#b15928", "#17becf",
)
_SEQUENTIAL = ("#eff6ff", "#bfdbfe", "#60a5fa", "#2563eb", "#1e3a8a")
_DIVERGING = ("#7f1d1d", "#ef4444", "#f8fafc", "#3b82f6", "#1e3a8a")

_RASTER_PALETTES = {
    "land_cover": ("#1b5e20", "#388e3c", "#7cb342", "#c0ca33", "#fdd835", "#fb8c00", "#e53935", "#8d6e63", "#90a4ae", "#1565c0"),
    "ndvi": ("#8b0000", "#d73027", "#fee08b", "#d9ef8b", "#1a9850", "#006837"),
    "elevation": ("#0b3d2e", "#2e7d32", "#8bc34a", "#d7ccc8", "#8d6e63", "#ffffff"),
    "temperature": ("#313695", "#4575b4", "#74add1", "#fdae61", "#f46d43", "#a50026"),
    "precipitation": ("#f7fbff", "#c6dbef", "#6baed6", "#2171b5", "#08306b"),
    "risk": ("#ffffcc", "#ffeda0", "#feb24c", "#f03b20", "#bd0026"),
    "probability": ("#f7fbff", "#c6dbef", "#6baed6", "#2171b5", "#08306b"),
    "slope": ("#ffffe5", "#fff7bc", "#fec44f", "#d95f0e", "#7f2704"),
    "forest_dynamics": ("#1b5e20", "#d32f2f", "#f57c00", "#66bb6a", "#9e9e9e"),
    "deforestation": ("#1b5e20", "#d32f2f", "#81c784", "#bdbdbd"),
    "forest_degradation": ("#0b5d1e", "#a5d66a", "#f9a825", "#d84315", "#bdbdbd"),
    "land_cover_change": ("#546e7a", "#2e7d32", "#c62828", "#f9a825", "#1565c0"),
    "categorical": ("#2e7d32", "#f9a825", "#1565c0", "#8d6e63", "#6a1b9a", "#546e7a"),
    "population": ("#f7fcf5", "#c7e9c0", "#74c476", "#238b45", "#00441b"),
    "water": ("#f7fbff", "#bdd7e7", "#6baed6", "#2171b5", "#08306b"),
    "continuous": ("#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"),
    "diverging": ("#7f0000", "#d7301f", "#f7f7f7", "#3182bd", "#08306b"),
    "gray": ("#000000", "#ffffff"),
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
        try:
            sym.renderer.symbol.color = _arcgis_color(_QUALITATIVE[len(_QUALITATIVE) // 2])
        except Exception:
            pass
        renderer = "SimpleRenderer"
    elif categorized:
        sym.updateRenderer("UniqueValueRenderer")
        sym.renderer.fields = [field]
        index = 0
        for group in list(getattr(sym.renderer, "groups", ()) or ()):
            for item in list(getattr(group, "items", ()) or ()):
                try:
                    item.symbol.color = _arcgis_color(_QUALITATIVE[index % len(_QUALITATIVE)])
                    index += 1
                except Exception:
                    pass
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
        breaks = list(getattr(sym.renderer, "classBreaks", ()) or ())
        colors = _resample_palette(
            _DIVERGING if str(palette).strip().casefold() in {"divergente", "diverging"} else _SEQUENTIAL,
            len(breaks),
        )
        for item, color in zip(breaks, colors):
            try:
                item.symbol.color = _arcgis_color(color)
            except Exception:
                pass
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


def apply_raster_symbology(
    aprx: Any, layer: Any, diagnosis: dict[str, Any], class_count: int = 7, *,
    palette: str = "", opacity_percent: int = 100,
    expert_confirmed: bool = False, mode: str = "", band: int = 1,
    classification_method: str = "sample_quantiles",
    minimum: float | None = None, maximum: float | None = None,
    red_band: int = 1, green_band: int = 2, blue_band: int = 3,
) -> dict[str, Any]:
    sym = layer.symbology
    if not hasattr(sym, "colorizer"):
        return {"applied": False, "reason": "Le raster n'expose pas de coloriseur modifiable."}
    raster_type = diagnosis.get("raster_type")
    mode_key = str(mode or "").strip().casefold()
    if raster_type == "rgb" or mode_key == "rgb":
        return {
            "applied": False,
            "native_sdk_required": True,
            "reason": "La composition RGB est transmise au moteur natif ArcGIS Pro.",
            "red_band": max(1, int(red_band)), "green_band": max(1, int(green_band)),
            "blue_band": max(1, int(blue_band)),
        }
    colorizer = "RasterUniqueValueColorizer" if raster_type in {"binary", "categorized"} else "RasterClassifyColorizer"
    try:
        sym.updateColorizer(colorizer)
    except Exception:
        return {"applied": False, "reason": f"ArcGIS Pro n'a pas pu activer {colorizer}."}
    applied_classes = 0
    hidden_classes = 0
    if colorizer == "RasterUniqueValueColorizer":
        definitions = list(diagnosis.get("classes") or ())
        definitions_by_value = {
            _number_key(value): definition
            for definition in definitions
            for value in (definition.get("values") or ())
        }
        try:
            sym.colorizer.field = "Value"
        except Exception:
            pass
        try:
            sym.colorizer.useDefaultColor = False
        except Exception:
            pass
        for group in list(getattr(sym.colorizer, "groups", ()) or ()):
            visible_items = []
            for item in list(getattr(group, "items", ()) or ()):
                definition = next(
                    (
                        definitions_by_value.get(_number_key(value))
                        for value in _iter_item_values(getattr(item, "values", ()) or ())
                        if _number_key(value) in definitions_by_value
                    ),
                    None,
                )
                if definition is None:
                    visible_items.append(item)
                    continue
                visible = bool(definition.get("visible", True))
                show_in_legend = bool(definition.get("show_in_legend", True))
                if not visible or not show_in_legend:
                    hidden_classes += 1
                    continue
                item.label = str(definition.get("label") or getattr(item, "label", "Classe"))
                item.description = str(definition.get("status") or definition.get("source") or "")
                item.color = _arcgis_color(
                    definition.get("color", "#808080"),
                    float(definition.get("opacity", 1.0) or 0.0),
                )
                visible_items.append(item)
                applied_classes += 1
            group.items = visible_items
        try:
            sym.colorizer.noDataColor = {"RGB": [0, 0, 0, 0]}
        except Exception:
            pass
    elif colorizer == "RasterClassifyColorizer":
        sym.colorizer.classificationField = "Value"
        theme = str(diagnosis.get("theme") or "continuous")
        profile = theme_profile(theme)
        preferred = class_count or profile.preferred_class_count
        sym.colorizer.breakCount = max(3, min(12, int(preferred)))
        palette_key = str(palette or theme or "continuous").strip().casefold()
        ramp_name = _PALETTE_RAMPS.get(palette_key, _ESRI_RAMP_HINTS.get(theme, "Viridis"))
        ramps = aprx.listColorRamps(ramp_name) or aprx.listColorRamps()
        if ramps:
            sym.colorizer.colorRamp = ramps[0]
        try:
            sym.colorizer.classificationMethod = "Quantile" if classification_method == "sample_quantiles" else "EqualInterval"
        except Exception:
            pass
        try:
            if minimum is not None:
                sym.colorizer.lowerBound = float(minimum)
        except Exception:
            pass
        breaks = list(getattr(sym.colorizer, "classBreaks", ()) or ())
        colors = _resample_palette(_RASTER_PALETTES.get(palette_key, _RASTER_PALETTES.get(theme, _RASTER_PALETTES["continuous"])), len(breaks))
        bounds = _raster_break_bounds(diagnosis, len(breaks), classification_method, minimum, maximum)
        lower = float(minimum) if minimum is not None else None
        for index, (item, color) in enumerate(zip(breaks, colors)):
            try:
                item.color = _arcgis_color(color)
                if index < len(bounds):
                    item.upperBound = bounds[index]
                    item.label = (
                        f"{_format_number(lower)} – {_format_number(bounds[index])}"
                        if lower is not None else f"≤ {_format_number(bounds[index])}"
                    )
                    lower = bounds[index]
                applied_classes += 1
            except Exception:
                pass
        try:
            sym.colorizer.noDataColor = {"RGB": [0, 0, 0, 0]}
        except Exception:
            pass
    layer.symbology = sym
    opacity = max(0, min(100, int(opacity_percent)))
    try:
        layer.transparency = 100 - opacity
    except Exception:
        pass
    return {
        "applied": True,
        "colorizer": colorizer,
        "theme": diagnosis.get("theme"),
        "class_count": int(class_count),
        "classes_applied": applied_classes,
        "classes_hidden": hidden_classes,
        "palette": palette,
        "opacity_percent": opacity,
        "expert_confirmed": bool(expert_confirmed),
        "mode": mode_key or raster_type,
        "band": max(1, int(band)),
        "classification_method": classification_method,
        "minimum": minimum,
        "maximum": maximum,
    }


def _raster_break_bounds(
    diagnosis: dict[str, Any], count: int, method: str,
    minimum: float | None, maximum: float | None,
) -> tuple[float, ...]:
    if count <= 0:
        return ()
    low = float(minimum if minimum is not None else diagnosis.get("minimum", 0.0) or 0.0)
    high = float(maximum if maximum is not None else diagnosis.get("maximum", low + 1.0) or (low + 1.0))
    if low >= high:
        raise ValueError("Le minimum doit être strictement inférieur au maximum.")
    if method == "sample_quantiles":
        inspection = diagnosis.get("inspection") or {}
        quantiles = [
            (float(item[0]), float(item[1]))
            for item in inspection.get("sample_quantiles", ())
            if isinstance(item, (list, tuple)) and len(item) >= 2
        ]
        if quantiles:
            return tuple(_interpolate_quantile(quantiles, (index + 1) / count) for index in range(count - 1)) + (high,)
    step = (high - low) / count
    return tuple(low + step * (index + 1) for index in range(count))


def _interpolate_quantile(points: list[tuple[float, float]], target: float) -> float:
    ordered = sorted(points)
    if target <= ordered[0][0]:
        return ordered[0][1]
    for (left_q, left_v), (right_q, right_v) in zip(ordered, ordered[1:]):
        if target <= right_q:
            ratio = (target - left_q) / max(1.0e-12, right_q - left_q)
            return left_v + ratio * (right_v - left_v)
    return ordered[-1][1]


def _format_number(value: float | None) -> str:
    return "" if value is None else format(float(value), ".8g")


def _number_key(value: Any) -> str:
    try:
        number = float(value)
        if number.is_integer():
            return str(int(number))
        return format(number, ".15g")
    except (TypeError, ValueError):
        return str(value).strip().casefold()


def _iter_item_values(values: Any):
    for value in values or ():
        if isinstance(value, (list, tuple)):
            yield from _iter_item_values(value)
        else:
            yield value


def _resample_palette(palette: tuple[str, ...], count: int) -> tuple[str, ...]:
    if count <= 0:
        return ()
    if count == 1:
        return (palette[len(palette) // 2],)
    return tuple(
        palette[round(index * (len(palette) - 1) / (count - 1))]
        for index in range(count)
    )


def _arcgis_color(value: Any, opacity: float = 1.0) -> dict[str, list[int]]:
    text = str(value or "#808080").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(character * 2 for character in text)
    try:
        red, green, blue = (int(text[index:index + 2], 16) for index in (0, 2, 4))
    except (TypeError, ValueError):
        red, green, blue = 128, 128, 128
    alpha = max(0, min(100, round(100 * float(opacity))))
    return {"RGB": [red, green, blue, alpha]}


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
