"""Interprétation thématique et symbologie raster native QGIS."""
from __future__ import annotations
import logging

from dataclasses import asdict, dataclass, replace
import json
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
from .extent_policy import is_remote_basemap
from .raster_intelligence import (
    RasterClassDefinition,
    RasterIntelligenceEngine,
    _renderer_from_classes,
    apply_visual_nodata_transparency,
)
from .raster_sampling import quantile_value
from .raster_themes import (
    THEME_PROFILES,
    detect_raster_theme,
    is_generic_class_label,
    theme_profile,
)


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
    class_value_groups: tuple[tuple[float, ...], ...] = ()
    class_opacities: tuple[float, ...] = ()
    nodata_values: tuple[float, ...] = ()
    classification_method: str = "equal_interval"
    expert_confirmed: bool = False
    sample_quantiles: tuple[tuple[float, float], ...] = ()
    theme_label: str = ""
    theme_source: str = "automatic"
    compatibility_warning: str = ""

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
        self._preview_styles: dict[str, QgsMapLayerStyle] = {}
        self.intelligence = RasterIntelligenceEngine(self.project)

    def recommend(self, layer: QgsRasterLayer, objective: str = "auto") -> RasterSymbologyRecommendation:
        if not isinstance(layer, QgsRasterLayer) or not layer.isValid():
            raise CartomizeError("Sélectionnez une couche raster valide.")
        self._ensure_styleable_raster(layer)
        diagnosis = self.intelligence.analyze(layer, deep=False)
        return self.recommend_from_diagnosis(layer, diagnosis, objective)

    def recommend_from_diagnosis(
        self,
        layer: QgsRasterLayer,
        diagnosis,
        objective: str = "auto",
    ) -> RasterSymbologyRecommendation:
        """Construit le plan de rendu sans relancer une inspection déjà disponible."""
        inference = diagnosis.inference
        inspection = diagnosis.inspection
        band_count = max(1, int(layer.bandCount()))
        reasons = list(inference.rationale)
        reasons.extend(inspection.warnings)

        band = 1
        minimum = inspection.statistics[0].get("minimum") if inspection.statistics else None
        maximum = inspection.statistics[0].get("maximum") if inspection.statistics else None
        semantic_labels = tuple(item.label for item in diagnosis.classes if item.label)
        band_roles = tuple(str(item.get("role") or "") for item in diagnosis.band_semantics)
        metadata_text = " ".join(f"{key} {value}" for key, value in inspection.metadata.items())
        match = detect_raster_theme(
            text=" ".join((layer.name(), layer.source(), objective, metadata_text)),
            raster_type=inference.raster_type,
            minimum=minimum,
            maximum=maximum,
            labels=semantic_labels,
            band_roles=band_roles,
        )
        profile = theme_profile(match.key)
        reasons.extend(match.reasons)
        theme = profile.key
        confidence = min(float(inference.confidence), float(match.confidence))

        explicit_nodata = tuple(
            float(value) for value in inspection.source_nodata
            if value is not None and math.isfinite(float(value))
        )
        effective_nodata = tuple(sorted({
            *explicit_nodata,
            *(float(value) for value in inference.automatic_nodata_values),
        }))
        if inference.automatic_nodata_values:
            values_text = ", ".join(_number(value) for value in inference.automatic_nodata_values)
            reasons.append(
                f"Fond NoData probable masqué visuellement ({values_text}); "
                "la décision reste réversible dans Raster Engine."
            )
        if inference.raster_type == "rgb":
            return RasterSymbologyRecommendation(
                mode="rgb", theme="rgb", band=1, minimum=None, maximum=None,
                class_count=3, palette=(), labels=("Rouge", "Vert", "Bleu"),
                confidence=confidence, rationale=tuple(reasons),
                red_band=1, green_band=min(2, band_count), blue_band=min(3, band_count),
                nodata_values=effective_nodata,
                theme_label=theme_profile("rgb").label,
            )
        if inference.raster_type in {"categorized", "binary"}:
            classes, compatibility_warning = self.class_definitions_for_theme(diagnosis, theme)
            classes = tuple(item for item in classes if item.visible)
            palette = tuple(item.color for item in classes) or self.PALETTES["land_cover"]
            labels = tuple(item.label for item in classes)
            values = tuple(item.values[0] for item in classes if item.values)
            value_groups = tuple(item.values for item in classes if item.values)
            opacities = tuple(item.opacity for item in classes if item.values)
            if compatibility_warning:
                reasons.append(compatibility_warning)
            return RasterSymbologyRecommendation(
                mode="categorical", theme=theme if profile.mode == "categorical" else "categorical",
                band=band, minimum=minimum, maximum=maximum, class_count=len(values),
                palette=palette, labels=labels, confidence=confidence,
                rationale=tuple(reasons), class_values=values, nodata_values=effective_nodata,
                class_value_groups=value_groups, class_opacities=opacities,
                theme_label=(profile.label if profile.mode == "categorical" else theme_profile("categorical").label),
                compatibility_warning=compatibility_warning,
            )

        if inference.raster_type == "multiband" and band_count >= 3:
            reasons.append("Le raster multibande est initialisé en composition RGB modifiable.")
            return RasterSymbologyRecommendation(
                mode="rgb", theme="rgb", band=1, minimum=None, maximum=None,
                class_count=3, palette=(), labels=("Rouge", "Vert", "Bleu"),
                confidence=confidence, rationale=tuple(reasons),
                red_band=1, green_band=2, blue_band=3,
                theme_label=theme_profile("rgb").label,
            )

        quantiles = tuple(inspection.sample_quantiles)
        robust_minimum = quantile_value(quantiles, 0.02)
        robust_maximum = quantile_value(quantiles, 0.98)
        if (
            robust_minimum is not None and robust_maximum is not None
            and robust_minimum < robust_maximum
        ):
            minimum, maximum = robust_minimum, robust_maximum
            reasons.append(
                "Bornes proposées aux quantiles 2 % et 98 % de l’échantillon valide; "
                "elles restent modifiables par l’expert."
            )
        if profile.mode != "continuous":
            profile = theme_profile("continuous")
            theme = profile.key
        return RasterSymbologyRecommendation(
            mode="continuous", theme=theme, band=band, minimum=minimum, maximum=maximum,
            class_count=profile.preferred_class_count,
            palette=profile.palette or self.PALETTES.get(theme, self.PALETTES["continuous"]),
            labels=(), confidence=confidence, rationale=tuple(reasons),
            nodata_values=effective_nodata,
            classification_method="sample_quantiles" if quantiles else "equal_interval",
            sample_quantiles=quantiles,
            theme_label=profile.label,
        )

    def manual_recommendation_from_diagnosis(
        self,
        layer: QgsRasterLayer,
        diagnosis,
        theme_key: str,
    ) -> RasterSymbologyRecommendation:
        """Produit un plan explicite sans réinterpréter les pixels source."""
        profile = theme_profile(theme_key)
        baseline = self.recommend_from_diagnosis(layer, diagnosis)
        reasons = [
            f"Profil thématique choisi manuellement par l'expert : {profile.label}.",
            "Les codes pixels restent inchangés; seule leur représentation est modifiée.",
        ]
        warning = ""
        if profile.mode == "categorical":
            definitions, warning = self.class_definitions_for_theme(diagnosis, profile.key)
            if not definitions:
                raise CartomizeError(
                    "Ce profil exige des valeurs discrètes. Classez d'abord le raster continu "
                    "ou choisissez un profil continu; Cartomize ne fabrique pas de codes pixels."
                )
            visible = tuple(item for item in definitions if item.visible and item.values)
            if warning:
                reasons.append(warning)
            return replace(
                baseline,
                mode="categorical", theme=profile.key, theme_label=profile.label,
                theme_source="manual", palette=tuple(item.color for item in visible),
                labels=tuple(item.label for item in visible),
                class_values=tuple(item.values[0] for item in visible),
                class_value_groups=tuple(item.values for item in visible),
                class_opacities=tuple(item.opacity for item in visible),
                class_count=len(visible), rationale=tuple(reasons),
                confidence=0.72 if not warning else 0.58,
                expert_confirmed=True, compatibility_warning=warning,
            )
        if profile.mode == "rgb":
            red, green, blue, warning = self._rgb_bands_for_profile(diagnosis, profile.key)
            if warning:
                reasons.append(warning)
            return replace(
                baseline,
                mode="rgb", theme=profile.key, theme_label=profile.label,
                theme_source="manual", red_band=red, green_band=green, blue_band=blue,
                palette=(), labels=("Rouge", "Vert", "Bleu"), class_count=3,
                minimum=None, maximum=None, rationale=tuple(reasons),
                confidence=0.85 if not warning else 0.55,
                expert_confirmed=not bool(warning), compatibility_warning=warning,
            )
        return replace(
            baseline,
            mode="continuous", theme=profile.key, theme_label=profile.label,
            theme_source="manual", palette=profile.palette,
            class_count=profile.preferred_class_count,
            rationale=tuple(reasons), confidence=0.90,
            expert_confirmed=True, compatibility_warning="",
        )

    def class_definitions_for_theme(self, diagnosis, theme_key: str):
        """Associe un profil aux codes existants en conservant leur identité."""
        profile = theme_profile(theme_key)
        source = tuple(diagnosis.classes)
        if not source:
            return (), "Aucun code discret n'est disponible pour construire la correspondance."
        if profile.mode != "categorical" or not profile.classes:
            return source, ""
        mapped = []
        thematic_index = 0
        thematic_count = sum(1 for item in source if item.visible and item.values)
        for definition in source:
            # Une classe masquée (notamment un fond NoData détecté) garde
            # son identité et ne décale jamais la correspondance métier.
            if not definition.visible or not definition.values:
                mapped.append(definition)
                continue
            preset = (
                profile.classes[thematic_index]
                if thematic_index < len(profile.classes)
                else None
            )
            thematic_index += 1
            label = definition.label
            if preset is not None and is_generic_class_label(label):
                label = preset.label
            color = preset.color if preset is not None else definition.color
            mapped.append(
                replace(definition, label=label, color=color, source=f"theme:{profile.key}")
            )
        warning = ""
        if thematic_count != len(profile.classes):
            warning = (
                f"Correspondance à confirmer : le raster contient {thematic_count} code(s) visible(s) "
                f"alors que le profil {profile.label} propose {len(profile.classes)} classe(s)."
            )
        return tuple(mapped), warning

    @staticmethod
    def theme_profiles():
        return THEME_PROFILES

    @staticmethod
    def _rgb_bands_for_profile(diagnosis, theme_key: str) -> tuple[int, int, int, str]:
        roles = {
            str(item.get("role") or "").casefold(): int(item.get("band") or 1)
            for item in diagnosis.band_semantics
            if item.get("band")
        }
        band_count = max(1, int(diagnosis.inspection.band_count))
        if theme_key == "false_color":
            if all(role in roles for role in ("nir", "red", "green")):
                return roles["nir"], roles["red"], roles["green"], ""
            if band_count >= 4:
                return 4, 3, 2, (
                    "Bandes NIR/Rouge/Vert non identifiées par les métadonnées; "
                    "la proposition 4/3/2 doit être vérifiée."
                )
            raise CartomizeError("Une composition fausses couleurs exige au moins trois bandes identifiables.")
        if all(role in roles for role in ("red", "green", "blue")):
            return roles["red"], roles["green"], roles["blue"], ""
        return 1, min(2, band_count), min(3, band_count), (
            "Rôles Rouge/Vert/Bleu non confirmés par les métadonnées; vérifiez les bandes."
        )

    def apply(
        self,
        layer: QgsRasterLayer,
        recommendation: RasterSymbologyRecommendation | None = None,
        objective: str = "auto",
    ) -> RasterSymbologyRecommendation:
        if not isinstance(layer, QgsRasterLayer) or not layer.isValid():
            raise CartomizeError("La symbologie automatique exige une couche raster valide.")
        self._ensure_styleable_raster(layer)
        recommendation = recommendation or self.recommend(layer, objective)
        if recommendation.confidence < 0.65 and not recommendation.expert_confirmed:
            raise CartomizeError(
                "La proposition raster a une confiance faible. Vérifiez la bande, les bornes et le mode puis confirmez le choix expert."
            )
        preview_style = self._preview_styles.pop(layer.id(), None)
        if preview_style is not None:
            history = self._history.setdefault(layer.id(), [])
            history.append(preview_style)
            del history[:-10]
        else:
            self._snapshot(layer)
        self._apply_renderer(layer, recommendation, persist=True)
        return recommendation

    def preview(self, layer: QgsRasterLayer, recommendation: RasterSymbologyRecommendation) -> None:
        """Affiche un rendu temporaire annulable sans polluer l'historique."""
        if not isinstance(layer, QgsRasterLayer) or not layer.isValid():
            raise CartomizeError("La prévisualisation exige une couche raster valide.")
        self._ensure_styleable_raster(layer)
        if layer.id() not in self._preview_styles:
            style = QgsMapLayerStyle()
            style.readFromLayer(layer)
            self._preview_styles[layer.id()] = style
        self._apply_renderer(layer, recommendation, persist=False)

    def cancel_preview(self, layer: QgsRasterLayer) -> bool:
        style = self._preview_styles.pop(layer.id(), None)
        if style is None:
            return False
        style.writeToLayer(layer)
        layer.triggerRepaint()
        return True

    def _apply_renderer(
        self,
        layer: QgsRasterLayer,
        recommendation: RasterSymbologyRecommendation,
        *,
        persist: bool,
    ) -> None:
        self._ensure_styleable_raster(layer)
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

        renderer = apply_visual_nodata_transparency(renderer, recommendation.nodata_values)
        layer.setRenderer(renderer)
        layer.setCustomProperty("cartomize/raster_mode", recommendation.mode)
        layer.setCustomProperty("cartomize/raster_theme", recommendation.theme)
        layer.setCustomProperty("cartomize/raster_band", recommendation.band)
        layer.setCustomProperty("cartomize/raster_confidence", recommendation.confidence)
        layer.setCustomProperty("cartomize/raster_theme_source", recommendation.theme_source)
        layer.setCustomProperty(
            "cartomize/expert_raster_plan",
            json.dumps(asdict(recommendation), ensure_ascii=False),
        )
        layer.triggerRepaint()
        if persist:
            self.project.setDirty(True)

    @staticmethod
    def _ensure_styleable_raster(layer: QgsRasterLayer) -> None:
        """Refuse de remplacer le renderer natif d'un fond web distant."""

        if is_remote_basemap(
            layer.providerType(),
            layer.source(),
            layer.name(),
        ):
            raise CartomizeError(
                "Cette couche est un fond cartographique distant. Cartomize "
                "conserve son rendu d'origine et ne lui applique pas de "
                "classification raster."
            )

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
            logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
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
        # Une correspondance explicite issue de l'éditeur est prioritaire sur
        # la RAT source; autrement QGIS rétablirait silencieusement l'ancien rendu.
        groups = tuple(recommendation.class_value_groups)
        if not groups and recommendation.class_values:
            groups = tuple((float(value),) for value in recommendation.class_values)
        if groups:
            definitions = tuple(
                RasterClassDefinition(
                    values=tuple(float(value) for value in group),
                    label=(
                        recommendation.labels[index]
                        if index < len(recommendation.labels)
                        else f"Classe {_number(group[0])}"
                    ),
                    color=(
                        recommendation.palette[index % len(recommendation.palette)]
                        if recommendation.palette else "#808080"
                    ),
                    pixel_count=0,
                    percentage=0.0,
                    border_percentage=0.0,
                    visible=True,
                    show_in_legend=True,
                    source="preview",
                    opacity=(
                        recommendation.class_opacities[index]
                        if index < len(recommendation.class_opacities) else 1.0
                    ),
                )
                for index, group in enumerate(groups)
                if group
            )
            if definitions:
                return _renderer_from_classes(provider, recommendation.band, definitions)
        try:
            rat = provider.attributeTable(recommendation.band)
            if rat is not None and hasattr(rat, "createRenderer"):
                renderer = rat.createRenderer(provider, recommendation.band)
                if renderer is not None:
                    return renderer
        except Exception:
            logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
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
                logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
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
            if recommendation.classification_method == "sample_quantiles" and recommendation.sample_quantiles:
                stops = [
                    quantile_value(recommendation.sample_quantiles, index / max(1, len(colors) - 1))
                    for index in range(len(colors))
                ]
                stop_values = [
                    min(maximum, max(minimum, float(value))) if value is not None else minimum
                    for value in stops
                ]
                # QGIS attend des arrêts strictement ordonnés. Les doublons de
                # quantiles d'un raster quasi discret sont ramenés à une rampe
                # régulière, sans inventer de classes thématiques.
                if any(right <= left for left, right in zip(stop_values, stop_values[1:])):
                    step = (maximum - minimum) / max(1, len(colors) - 1)
                    stop_values = [minimum + index * step for index in range(len(colors))]
            else:
                step = (maximum - minimum) / max(1, len(colors) - 1)
                stop_values = [minimum + index * step for index in range(len(colors))]
            items = [
                QgsColorRampShader.ColorRampItem(
                    stop_values[index],
                    QColor(color),
                    f"{stop_values[index]:.4g}",
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
                logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
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


def _number(value: float) -> str:
    return str(int(round(value))) if _is_integer_like(value) else f"{float(value):.6g}"


def _resample(colors: Iterable[str], count: int) -> list[str]:
    source = list(colors)
    if not source or count <= 0:
        return []
    if count == 1:
        return [source[len(source) // 2]]
    return [source[int(round(index * (len(source) - 1) / (count - 1)))] for index in range(count)]
