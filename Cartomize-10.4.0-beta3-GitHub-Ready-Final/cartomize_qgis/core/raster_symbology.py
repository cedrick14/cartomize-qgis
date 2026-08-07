"""Interprétation thématique et symbologie raster native QGIS."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable

from qgis.PyQt.QtGui import QColor
from qgis.core import (
    Qgis,
    QgsColorRampShader,
    QgsMapLayerStyle,
    QgsMultiBandColorRenderer,
    QgsPalettedRasterRenderer,
    QgsProject,
    QgsRasterBandStats,
    QgsRasterLayer,
    QgsRasterShader,
    QgsSingleBandGrayRenderer,
    QgsSingleBandPseudoColorRenderer,
)

from .errors import CartomizeError
from .raster_intelligence import RasterIntelligenceEngine


@dataclass(frozen=True)
class RasterSymbologyRecommendation:
    mode: str
    theme: str
    band: int
    minimum: float | None
    maximum: float | None
    class_count: int
    palette: tuple[str, ...]
    labels: tuple[str, ...]
    confidence: float
    rationale: tuple[str, ...]
    red_band: int = 1
    green_band: int = 2
    blue_band: int = 3
    class_values: tuple[float, ...] = ()
    nodata_values: tuple[float, ...] = ()

    def summary(self) -> str:
        if self.mode == "rgb":
            return f"Composition RGB {self.red_band}/{self.green_band}/{self.blue_band}"
        if self.mode == "categorical":
            return f"Raster catégoriel, bande {self.band}, {self.class_count} classes"
        return f"{self.theme.replace('_', ' ').title()}, bande {self.band}"


class RasterSymbologyService:
    """Applique une représentation raster explicable et réversible."""

    PALETTES: dict[str, tuple[str, ...]] = {
        "land_cover": (
            "#1b5e20", "#388e3c", "#7cb342", "#c0ca33", "#fdd835",
            "#fb8c00", "#e53935", "#8d6e63", "#90a4ae", "#1565c0",
        ),
        "ndvi": ("#8b0000", "#d73027", "#fee08b", "#d9ef8b", "#1a9850", "#006837"),
        "elevation": ("#0b3d2e", "#2e7d32", "#8bc34a", "#d7ccc8", "#8d6e63", "#ffffff"),
        "temperature": ("#313695", "#4575b4", "#74add1", "#fdae61", "#f46d43", "#a50026"),
        "precipitation": ("#f7fbff", "#c6dbef", "#6baed6", "#2171b5", "#08306b"),
        "risk": ("#ffffcc", "#ffeda0", "#feb24c", "#f03b20", "#bd0026"),
        "population": ("#f7fcf5", "#c7e9c0", "#74c476", "#238b45", "#00441b"),
        "water": ("#f7fbff", "#bdd7e7", "#6baed6", "#2171b5", "#08306b"),
        "continuous": ("#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"),
        "diverging": ("#7f0000", "#d7301f", "#f7f7f7", "#3182bd", "#08306b"),
        "gray": ("#000000", "#ffffff"),
    }

    THEME_RULES: dict[str, tuple[str, ...]] = {
        "land_cover": ("lulc", "landcover", "land_cover", "occupation", "cover", "classe", "classif"),
        "ndvi": ("ndvi", "vegetation index", "indice vegetation"),
        "elevation": ("dem", "mnt", "dtm", "dsm", "elevation", "altitude", "relief", "srtm"),
        "temperature": ("temperature", "temp", "lst", "thermal", "chaleur"),
        "precipitation": ("precip", "pluie", "rain", "chirps"),
        "risk": ("risk", "risque", "hazard", "alea", "susceptibil", "vulnerab"),
        "population": ("population", "density", "densite", "worldpop", "habitants"),
        "water": ("water", "eau", "hydro", "flood", "inond"),
    }

    WORLD_COVER_LABELS = {
        10: "Couvert arboré",
        20: "Arbustes",
        30: "Prairies",
        40: "Cultures",
        50: "Zones bâties",
        60: "Sol nu ou végétation clairsemée",
        70: "Neige et glace",
        80: "Eau permanente",
        90: "Zones humides herbacées",
        95: "Mangroves",
        100: "Mousses et lichens",
    }
    MODIS_IGBP_LABELS = {
        0: "Eau", 1: "Forêt de conifères sempervirente",
        2: "Forêt de feuillus sempervirente", 3: "Forêt de conifères décidue",
        4: "Forêt de feuillus décidue", 5: "Forêt mixte",
        6: "Arbustes fermés", 7: "Arbustes ouverts",
        8: "Savane boisée", 9: "Savane", 10: "Prairie",
        11: "Zone humide permanente", 12: "Cultures",
        13: "Zone urbaine", 14: "Mosaïque cultures et végétation",
        15: "Neige et glace", 16: "Sol nu", 17: "Eau",
    }

    def __init__(self, project: QgsProject | None = None):
        self.project = project or QgsProject.instance()
        self._history: dict[str, list[QgsMapLayerStyle]] = {}
        self.intelligence = RasterIntelligenceEngine(self.project)

    def recommend(self, layer: QgsRasterLayer, objective: str = "auto") -> RasterSymbologyRecommendation:
        if not isinstance(layer, QgsRasterLayer) or not layer.isValid():
            raise CartomizeError("Sélectionnez une couche raster valide.")
        diagnosis = self.intelligence.analyze(layer, deep=False)
        inference = diagnosis.inference
        inspection = diagnosis.inspection
        band_count = max(1, int(layer.bandCount()))
        text = " ".join((layer.name(), layer.source(), objective)).casefold()
        theme = self._detect_theme(text)
        reasons = list(inference.rationale)
        reasons.extend(inspection.warnings)

        if inference.raster_type == "rgb":
            return RasterSymbologyRecommendation(
                mode="rgb", theme="imagery", band=1, minimum=None, maximum=None,
                class_count=3, palette=(), labels=("Rouge", "Vert", "Bleu"),
                confidence=inference.confidence, rationale=tuple(reasons),
                red_band=1, green_band=min(2, band_count), blue_band=min(3, band_count),
            )

        band = 1
        minimum = inspection.statistics[0].get("minimum") if inspection.statistics else None
        maximum = inspection.statistics[0].get("maximum") if inspection.statistics else None
        explicit_nodata = tuple(
            float(value) for value in inspection.source_nodata
            if value is not None and math.isfinite(float(value))
        )
        if inference.raster_type in {"categorized", "binary"}:
            classes = diagnosis.classes
            palette = tuple(item.color for item in classes) or self.PALETTES["land_cover"]
            labels = tuple(item.label for item in classes)
            values = tuple(item.values[0] for item in classes if item.values)
            return RasterSymbologyRecommendation(
                mode="categorical", theme=theme if theme != "continuous" else "land_cover",
                band=band, minimum=minimum, maximum=maximum, class_count=len(values),
                palette=palette, labels=labels, confidence=inference.confidence,
                rationale=tuple(reasons), class_values=values, nodata_values=explicit_nodata,
            )

        if inference.raster_type == "multiband" and band_count >= 3:
            reasons.append("Le raster multibande est initialisé en composition RGB modifiable.")
            return RasterSymbologyRecommendation(
                mode="rgb", theme="imagery", band=1, minimum=None, maximum=None,
                class_count=3, palette=(), labels=("Rouge", "Vert", "Bleu"),
                confidence=inference.confidence, rationale=tuple(reasons),
                red_band=1, green_band=2, blue_band=3,
            )

        if theme == "continuous" and minimum is not None and maximum is not None and minimum < 0 < maximum:
            theme = "diverging"
        return RasterSymbologyRecommendation(
            mode="continuous", theme=theme, band=band, minimum=minimum, maximum=maximum,
            class_count=7, palette=self.PALETTES.get(theme, self.PALETTES["continuous"]),
            labels=(), confidence=inference.confidence, rationale=tuple(reasons),
            nodata_values=explicit_nodata,
        )

    def apply(
        self,
        layer: QgsRasterLayer,
        recommendation: RasterSymbologyRecommendation | None = None,
        objective: str = "auto",
    ) -> RasterSymbologyRecommendation:
        if not isinstance(layer, QgsRasterLayer) or not layer.isValid():
            raise CartomizeError("La symbologie automatique exige une couche raster valide.")
        recommendation = recommendation or self.recommend(layer, objective)
        self._snapshot(layer)
        provider = layer.dataProvider()

        if recommendation.mode == "rgb":
            renderer = QgsMultiBandColorRenderer(
                provider,
                recommendation.red_band,
                recommendation.green_band,
                recommendation.blue_band,
            )
        elif recommendation.mode == "categorical":
            renderer = self._categorical_renderer(layer, recommendation)
        elif recommendation.theme == "gray":
            renderer = QgsSingleBandGrayRenderer(provider, recommendation.band)
        else:
            renderer = self._continuous_renderer(layer, recommendation)

        layer.setRenderer(renderer)
        layer.setCustomProperty("cartomize/raster_mode", recommendation.mode)
        layer.setCustomProperty("cartomize/raster_theme", recommendation.theme)
        layer.setCustomProperty("cartomize/raster_band", recommendation.band)
        layer.setCustomProperty("cartomize/raster_confidence", recommendation.confidence)
        layer.triggerRepaint()
        self.project.setDirty(True)
        return recommendation

    def undo_last(self, layer: QgsRasterLayer) -> bool:
        history = self._history.get(layer.id()) or []
        if not history:
            return False
        history.pop().writeToLayer(layer)
        layer.triggerRepaint()
        self.project.setDirty(True)
        return True

    def _snapshot(self, layer: QgsRasterLayer) -> None:
        style = QgsMapLayerStyle()
        style.readFromLayer(layer)
        history = self._history.setdefault(layer.id(), [])
        history.append(style)
        del history[:-10]

    def _detect_theme(self, text: str) -> str:
        for theme, words in self.THEME_RULES.items():
            if any(word in text for word in words):
                return theme
        return "continuous"

    def _statistics(self, layer: QgsRasterLayer, band: int) -> tuple[float | None, float | None]:
        provider = layer.dataProvider()
        try:
            modern = getattr(Qgis, "RasterBandStatistic", None)
            flag = getattr(modern, "All", None) if modern is not None else None
            if flag is None:
                flag = getattr(QgsRasterBandStats, "All", 0)
            stats = provider.bandStatistics(band, flag, layer.extent(), 250_000)
            minimum = float(stats.minimumValue)
            maximum = float(stats.maximumValue)
            if math.isfinite(minimum) and math.isfinite(maximum) and minimum < maximum:
                return minimum, maximum
        except Exception:
            pass
        return None, None

    @staticmethod
    def _unique_values(layer: QgsRasterLayer, band: int, limit: int) -> list[Any]:
        provider = layer.dataProvider()
        try:
            values = provider.uniqueValues(band, limit)
            return list(values or [])[:limit]
        except Exception:
            return []

    def _categorical_renderer(self, layer: QgsRasterLayer, recommendation: RasterSymbologyRecommendation):
        provider = layer.dataProvider()
        try:
            rat = provider.attributeTable(recommendation.band)
            if rat is not None and hasattr(rat, "createRenderer"):
                renderer = rat.createRenderer(provider, recommendation.band)
                if renderer is not None:
                    return renderer
        except Exception:
            pass
        values = list(recommendation.class_values) if recommendation.class_values else self._unique_values(layer, recommendation.band, max(2, recommendation.class_count))
        if recommendation.nodata_values:
            nodata = {float(value) for value in recommendation.nodata_values}
            values = [value for value in values if float(value) not in nodata]
        colors = _resample(recommendation.palette, len(values))
        class_type = getattr(QgsPalettedRasterRenderer, "Class", None)
        if class_type is not None and values:
            classes = [
                class_type(value, QColor(colors[index]), recommendation.labels[index] if index < len(recommendation.labels) else f"Classe {value}")
                for index, value in enumerate(values)
            ]
            try:
                return QgsPalettedRasterRenderer(provider, recommendation.band, classes)
            except Exception:
                pass
        return self._shader_renderer(layer, recommendation, values=values, exact=True)

    def _continuous_renderer(self, layer: QgsRasterLayer, recommendation: RasterSymbologyRecommendation):
        return self._shader_renderer(layer, recommendation, values=None, exact=False)

    def _shader_renderer(
        self,
        layer: QgsRasterLayer,
        recommendation: RasterSymbologyRecommendation,
        *,
        values: Iterable[Any] | None,
        exact: bool,
    ):
        minimum = recommendation.minimum
        maximum = recommendation.maximum
        if minimum is None or maximum is None or not minimum < maximum:
            minimum, maximum = 0.0, 1.0
        shader_function = QgsColorRampShader(minimum, maximum)
        colors = recommendation.palette or self.PALETTES["continuous"]
        if values:
            value_list = list(values)
            colors = _resample(colors, len(value_list))
            items = [
                QgsColorRampShader.ColorRampItem(
                    float(value),
                    QColor(colors[index]),
                    recommendation.labels[index] if index < len(recommendation.labels) else f"Classe {value}",
                )
                for index, value in enumerate(value_list)
            ]
            ramp_type = _shader_type("Exact") if exact else _shader_type("Discrete")
        else:
            colors = _resample(colors, max(2, recommendation.class_count))
            step = (maximum - minimum) / max(1, len(colors) - 1)
            items = [
                QgsColorRampShader.ColorRampItem(
                    minimum + index * step,
                    QColor(color),
                    f"{minimum + index * step:.4g}",
                )
                for index, color in enumerate(colors)
            ]
            ramp_type = _shader_type("Interpolated")
        shader_function.setColorRampItemList(items)
        if ramp_type is not None:
            shader_function.setColorRampType(ramp_type)
        raster_shader = QgsRasterShader(minimum, maximum)
        raster_shader.setRasterShaderFunction(shader_function)
        renderer = QgsSingleBandPseudoColorRenderer(
            layer.dataProvider(),
            recommendation.band,
            raster_shader,
        )
        for method, value in (("setClassificationMin", minimum), ("setClassificationMax", maximum)):
            if hasattr(renderer, method):
                getattr(renderer, method)(value)
        return renderer

    def _existing_or_generic_labels(self, layer: QgsRasterLayer, band: int, values: list[Any]) -> list[str]:
        renderer = layer.renderer()
        labels_by_value: dict[str, str] = {}
        if renderer is not None and hasattr(renderer, "classes"):
            try:
                for item in renderer.classes():
                    value = getattr(item, "value", None)
                    label = getattr(item, "label", "")
                    if value is not None and str(label).strip():
                        labels_by_value[str(value)] = str(label).strip()
            except Exception:
                pass
        text = f"{layer.name()} {layer.source()}".casefold()
        known = {}
        if "worldcover" in text or "esa" in text:
            known = self.WORLD_COVER_LABELS
        elif "mcd12" in text or "modis" in text or "igbp" in text:
            known = self.MODIS_IGBP_LABELS
        elif any(token in text for token in ("foret", "forêt", "forest")) and set(int(float(v)) for v in values if _is_integer_like(v)) <= {0, 1}:
            known = {0: "Non-forêt", 1: "Forêt"}
        result = []
        for value in values:
            key = str(value)
            numeric = int(float(value)) if _is_integer_like(value) else None
            result.append(labels_by_value.get(key) or known.get(numeric) or f"Classe {value}")
        return result


def _shader_type(name: str):
    legacy = getattr(QgsColorRampShader, name, None)
    if legacy is not None:
        return legacy
    enum = getattr(Qgis, "ShaderInterpolationMethod", None)
    return getattr(enum, name, None) if enum is not None else None


def _is_integer_like(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and abs(number - round(number)) < 1e-9


def _resample(colors: Iterable[str], count: int) -> list[str]:
    source = list(colors)
    if not source or count <= 0:
        return []
    if count == 1:
        return [source[len(source) // 2]]
    return [source[int(round(index * (len(source) - 1) / (count - 1)))] for index in range(count)]
