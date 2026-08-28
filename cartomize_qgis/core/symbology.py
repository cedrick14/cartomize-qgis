"""Symbologie assistée reposant exclusivement sur les renderers QGIS natifs."""
from __future__ import annotations
import logging

from dataclasses import asdict, dataclass, replace
import json
import math
import statistics
from typing import Any

from qgis.PyQt.QtGui import QColor, QFont
from qgis.core import (
    Qgis,
    QgsCategorizedSymbolRenderer,
    QgsGraduatedSymbolRenderer,
    QgsMapLayerStyle,
    QgsPalLayerSettings,
    QgsProject,
    QgsRendererCategory,
    QgsRendererRange,
    QgsSingleSymbolRenderer,
    QgsSymbol,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
    QgsWkbTypes,
)

from .constants import MAX_PROFILE_FEATURES
from .errors import CartomizeError


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


class SmartSymbologyService:
    """Propose une symbologie initiale explicable et réversible."""

    QUALITATIVE = [
        "#1b9e77", "#d95f02", "#7570b3", "#e7298a", "#66a61e",
        "#e6ab02", "#a6761d", "#1f78b4", "#b2df8a", "#fb9a99",
        "#cab2d6", "#fdbf6f", "#6a3d9a", "#b15928", "#17becf",
    ]
    SEQUENTIAL = ["#eff6ff", "#bfdbfe", "#60a5fa", "#2563eb", "#1e3a8a"]
    DIVERGING = ["#7f1d1d", "#ef4444", "#f8fafc", "#3b82f6", "#1e3a8a"]
    LABEL_HINTS = (
        "name",
        "nom",
        "label",
        "libelle",
        "libellé",
        "title",
        "titre",
        "village",
        "commune",
        "district",
        "province",
    )
    CLASS_HINTS = (
        "class",
        "classe",
        "type",
        "category",
        "categorie",
        "catégorie",
        "status",
        "statut",
        "occupation",
        "landuse",
        "zone",
    )

    def __init__(self, project: QgsProject | None = None):
        self.project = project or QgsProject.instance()
        self._history: dict[str, list[QgsMapLayerStyle]] = {}

    def recommend(self, layer) -> SymbologyRecommendation:
        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            raise CartomizeError("Sélectionnez une couche vectorielle valide.")
        profile = self._profile_fields(layer)
        categorical = [item for item in profile if item["kind"] == "categorical"]
        numeric = [
            item for item in profile
            if item["kind"] == "numeric" and int(item.get("unique_count", 0)) >= 2
        ]
        label_field = self._choose_label_field(layer)
        if categorical:
            best = max(categorical, key=lambda item: item["score"])
            return self._with_stored_expert_choice(layer, SymbologyRecommendation(
                "Catégorisé",
                best["name"],
                label_field,
                min(15, best["unique_count"]),
                "qualitative",
                (
                    f"{best['unique_count']} modalités lisibles détectées.",
                    "Une palette qualitative ne suggère pas d'ordre entre les catégories.",
                    "La symbologie reste entièrement modifiable dans les propriétés QGIS.",
                ),
                min(0.95, 0.58 + best["score"] * 0.04),
            ))
        if numeric:
            best = max(numeric, key=lambda item: item["score"])
            classes = 5 if best["count"] >= 30 else 4 if best["count"] >= 12 else 3
            diverging = best["minimum"] < 0 < best["maximum"]
            return self._with_stored_expert_choice(layer, SymbologyRecommendation(
                "Gradué (quantiles)",
                best["name"],
                label_field,
                classes,
                "divergente" if diverging else "séquentielle",
                (
                    "Le champ est numérique et suffisamment renseigné.",
                    "Les quantiles équilibrent le nombre d'entités par classe pour une première lecture.",
                    (
                        "La palette divergente met en évidence le passage par zéro."
                        if diverging
                        else "La palette séquentielle représente une intensité croissante."
                    ),
                ),
                min(0.92, 0.55 + math.log10(max(best["count"], 1)) * 0.1),
            ))
        return self._with_stored_expert_choice(layer, SymbologyRecommendation(
            "Symbole unique",
            "",
            label_field,
            1,
            "Cartomize",
            (
                "Aucun champ attributaire ne présente une structure thématique suffisamment fiable.",
                "Le symbole unique constitue une représentation neutre et réversible.",
            ),
            0.72,
        ))

    def recommend_from_profile(self, layer, profile) -> SymbologyRecommendation:
        """Utilise le profil sémantique Vector Intelligence lorsqu'il est disponible."""
        if profile is None:
            return self.recommend(layer)
        field_name = str(getattr(profile, "thematic_field", "") or "")
        label_field = str(getattr(profile, "label_field", "") or "")
        if not field_name:
            recommendation = self.recommend(layer)
            if label_field and not recommendation.label_field:
                return self._with_stored_expert_choice(layer, SymbologyRecommendation(
                    recommendation.mode, recommendation.field_name, label_field,
                    recommendation.class_count, recommendation.palette,
                    recommendation.rationale, recommendation.confidence,
                ))
            return recommendation
        field_profile = next((item for item in getattr(profile, "fields", ()) if item.name == field_name), None)
        semantic = str(getattr(field_profile, "semantic_role", "") or "")
        if semantic in {"category", "coded_category", "ordinal"}:
            unique_count = max(2, int(getattr(field_profile, "unique_count", 5) or 5))
            return self._with_stored_expert_choice(layer, SymbologyRecommendation(
                "Catégorisé", field_name, label_field, min(20, unique_count), "qualitative",
                (
                    f"Vector Intelligence identifie « {field_name} » comme variable {semantic}.",
                    "Les catégories conservent des couleurs indépendantes et une légende explicite.",
                ),
                max(0.78, float(getattr(field_profile, "confidence", 0.78))),
            ))
        if semantic in {"quantitative", "diverging_quantitative"}:
            return self._with_stored_expert_choice(layer, SymbologyRecommendation(
                "Gradué (quantiles)", field_name, label_field, 5,
                "divergente" if semantic == "diverging_quantitative" else "séquentielle",
                (
                    f"Vector Intelligence identifie « {field_name} » comme variable quantitative.",
                    "Une classification graduée fournit une première représentation explicable et réversible.",
                ),
                max(0.80, float(getattr(field_profile, "confidence", 0.80))),
            ))
        return self.recommend(layer)

    def apply(
        self,
        layer: QgsVectorLayer,
        recommendation: SymbologyRecommendation | None = None,
    ) -> SymbologyRecommendation:
        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            raise CartomizeError("La symbologie intelligente exige une couche vectorielle valide.")
        recommendation = recommendation or self.recommend(layer)
        if recommendation.confidence < 0.65 and not recommendation.expert_confirmed:
            raise CartomizeError(
                "La recommandation a une confiance faible. Vérifiez les champs et confirmez explicitement le choix expert."
            )
        self._snapshot(layer)
        geometry_type = QgsWkbTypes.geometryType(layer.wkbType())
        if recommendation.mode.startswith("Catégorisé"):
            renderer = self._categorized_renderer(
                layer, recommendation.field_name, geometry_type,
                recommendation.class_count, recommendation.palette,
            )
        elif recommendation.mode.startswith("Gradué"):
            renderer = self._graduated_renderer(
                layer,
                recommendation.field_name,
                recommendation.class_count,
                geometry_type,
                recommendation.palette == "divergente",
            )
        else:
            symbol = QgsSymbol.defaultSymbol(geometry_type)
            if symbol is None:
                raise CartomizeError("QGIS n'a pas pu créer de symbole pour cette géométrie.")
            base_palette = self._palette(recommendation.palette)
            symbol.setColor(QColor(base_palette[len(base_palette) // 2]))
            renderer = QgsSingleSymbolRenderer(symbol)
        layer.setRenderer(renderer)
        if recommendation.labels_enabled and recommendation.label_field:
            self._apply_labels(
                layer, recommendation.label_field,
                recommendation.label_font_size_pt, recommendation.label_placement,
            )
        else:
            layer.setLabelsEnabled(False)
        opacity = max(0, min(100, int(recommendation.opacity_percent))) / 100.0
        if hasattr(layer, "setOpacity"):
            layer.setOpacity(opacity)
        layer.setCustomProperty("cartomize/advisor_mode", recommendation.mode)
        layer.setCustomProperty("cartomize/advisor_field", recommendation.field_name)
        layer.setCustomProperty("cartomize/advisor_confidence", recommendation.confidence)
        # Ces propriétés constituent le contrat stable entre l'éditeur expert,
        # Geo Intelligence et Autopilot. Une nouvelle analyse ne doit jamais
        # écraser silencieusement un champ choisi par le cartographe.
        layer.setCustomProperty("cartomize/expert_labels_configured", True)
        layer.setCustomProperty("cartomize/expert_labels_enabled", recommendation.labels_enabled)
        layer.setCustomProperty("cartomize/expert_label_field", recommendation.label_field)
        layer.setCustomProperty("cartomize/expert_label_size_pt", recommendation.label_font_size_pt)
        layer.setCustomProperty("cartomize/expert_label_placement", recommendation.label_placement)
        layer.setCustomProperty("cartomize/expert_style_configured", True)
        layer.setCustomProperty("cartomize/expert_style_mode", recommendation.mode)
        layer.setCustomProperty("cartomize/expert_style_field", recommendation.field_name)
        layer.setCustomProperty("cartomize/expert_style_class_count", recommendation.class_count)
        layer.setCustomProperty("cartomize/expert_style_palette", recommendation.palette)
        layer.setCustomProperty("cartomize/expert_style_opacity", recommendation.opacity_percent)
        layer.setCustomProperty(
            "cartomize/expert_symbology_plan",
            json.dumps(asdict(recommendation), ensure_ascii=False),
        )
        layer.triggerRepaint()
        self.project.setDirty(True)
        return recommendation

    def _with_stored_expert_choice(
        self,
        layer: QgsVectorLayer,
        recommendation: SymbologyRecommendation,
    ) -> SymbologyRecommendation:
        """Réutilise une décision appliquée tant que le schéma la permet."""
        configured = layer.customProperty("cartomize/expert_style_configured", False)
        if configured is not True and str(configured).casefold() not in {"1", "true", "yes"}:
            return recommendation
        field_name = str(layer.customProperty(
            "cartomize/expert_style_field", recommendation.field_name
        ) or "")
        mode = str(layer.customProperty(
            "cartomize/expert_style_mode", recommendation.mode
        ) or recommendation.mode)
        if mode != "Symbole unique" and (not field_name or layer.fields().indexOf(field_name) < 0):
            return replace(
                recommendation,
                rationale=recommendation.rationale + (
                    "La précédente décision experte référence un champ absent; une nouvelle proposition est fournie.",
                ),
            )
        label_field = str(layer.customProperty(
            "cartomize/expert_label_field", recommendation.label_field
        ) or "")
        if label_field and layer.fields().indexOf(label_field) < 0:
            label_field = recommendation.label_field
        labels_raw = layer.customProperty(
            "cartomize/expert_labels_enabled", recommendation.labels_enabled
        )
        labels_enabled = labels_raw is True or str(labels_raw).casefold() in {"1", "true", "yes"}
        try:
            class_count = max(1, min(100, int(layer.customProperty(
                "cartomize/expert_style_class_count", recommendation.class_count
            ))))
        except (TypeError, ValueError):
            class_count = recommendation.class_count
        try:
            opacity = max(0, min(100, int(layer.customProperty(
                "cartomize/expert_style_opacity", recommendation.opacity_percent
            ))))
        except (TypeError, ValueError):
            opacity = recommendation.opacity_percent
        try:
            font_size = max(5.0, min(48.0, float(layer.customProperty(
                "cartomize/expert_label_size_pt", recommendation.label_font_size_pt
            ))))
        except (TypeError, ValueError):
            font_size = recommendation.label_font_size_pt
        return replace(
            recommendation,
            mode=mode,
            field_name=field_name,
            label_field=label_field,
            class_count=class_count,
            palette=str(layer.customProperty(
                "cartomize/expert_style_palette", recommendation.palette
            ) or recommendation.palette),
            labels_enabled=labels_enabled,
            label_font_size_pt=font_size,
            label_placement=str(layer.customProperty(
                "cartomize/expert_label_placement", recommendation.label_placement
            ) or recommendation.label_placement),
            opacity_percent=opacity,
            expert_confirmed=True,
            rationale=recommendation.rationale + (
                "Les paramètres précédemment appliqués par l’expert sont réutilisés.",
            ),
        )

    def undo_last(self, layer: QgsVectorLayer) -> bool:
        history = self._history.get(layer.id()) or []
        if not history:
            return False
        style = history.pop()
        style.writeToLayer(layer)
        layer.triggerRepaint()
        self.project.setDirty(True)
        return True

    def _snapshot(self, layer: QgsVectorLayer) -> None:
        style = QgsMapLayerStyle()
        style.readFromLayer(layer)
        history = self._history.setdefault(layer.id(), [])
        history.append(style)
        del history[:-10]

    def _categorized_renderer(
        self,
        layer: QgsVectorLayer,
        field_name: str,
        geometry_type,
        max_categories: int,
        palette_name: str,
    ):
        index = layer.fields().indexOf(field_name)
        if index < 0:
            raise CartomizeError(f"Champ introuvable : {field_name}")
        values: list[Any] = []
        seen: set[str] = set()
        category_limit = max(2, min(100, int(max_categories or 25)))
        for feature in layer.getFeatures():
            value = feature[index]
            key = repr(value)
            if key in seen:
                continue
            seen.add(key)
            values.append(value)
            if len(values) > category_limit:
                break
        if len(values) > category_limit:
            raise CartomizeError(
                f"Le champ contient plus de {category_limit} catégories. "
                "Augmentez la limite après vérification, choisissez un autre champ "
                "ou utilisez une classification appropriée ; aucune catégorie ne sera masquée silencieusement."
            )
        values.sort(key=lambda value: str(value).casefold())
        categories = []
        colors = _resample_palette(self._palette(palette_name), len(values))
        for position, value in enumerate(values):
            symbol = QgsSymbol.defaultSymbol(geometry_type)
            if symbol is None:
                continue
            symbol.setColor(QColor(colors[position]))
            categories.append(QgsRendererCategory(value, symbol, str(value)))
        if not categories:
            raise CartomizeError("Aucune catégorie exploitable n'a été trouvée.")
        renderer = QgsCategorizedSymbolRenderer(field_name, categories)
        try:
            renderer.sortByLabel()
        except AttributeError:
            logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
        return renderer

    def _palette(self, name: str) -> list[str]:
        return {
            "qualitative": self.QUALITATIVE,
            "séquentielle": self.SEQUENTIAL,
            "sequential": self.SEQUENTIAL,
            "divergente": self.DIVERGING,
            "diverging": self.DIVERGING,
        }.get(str(name or "").casefold(), self.QUALITATIVE)

    def _graduated_renderer(
        self,
        layer: QgsVectorLayer,
        field_name: str,
        classes: int,
        geometry_type,
        diverging: bool,
    ):
        index = layer.fields().indexOf(field_name)
        if index < 0:
            raise CartomizeError(f"Champ introuvable : {field_name}")
        values: list[float] = []
        for feature in layer.getFeatures():
            try:
                value = float(feature[index])
            except (TypeError, ValueError):
                logging.getLogger(__name__).debug("Non-fatal Cartomize item skipped", exc_info=True)
                continue
            if math.isfinite(value):
                values.append(value)
            if len(values) >= 100_000:
                break
        if not values:
            raise CartomizeError("Le champ numérique ne contient aucune valeur exploitable.")
        values.sort()
        unique_count = len(set(values))
        if unique_count < 2:
            raise CartomizeError(
                "Le champ numérique ne contient qu'une seule valeur distincte. Utilisez un symbole unique."
            )
        classes = min(9, max(2, int(classes or 5)), unique_count)
        breaks = _quantile_breaks(values, classes)
        palette = self.DIVERGING if diverging else self.SEQUENTIAL
        colors = _resample_palette(palette, len(breaks) - 1)
        ranges = []
        for position, (lower, upper) in enumerate(zip(breaks[:-1], breaks[1:])):
            symbol = QgsSymbol.defaultSymbol(geometry_type)
            if symbol is None:
                continue
            symbol.setColor(QColor(colors[position]))
            ranges.append(QgsRendererRange(lower, upper, symbol, f"{lower:.4g} à {upper:.4g}"))
        if not ranges:
            raise CartomizeError("QGIS n'a pas pu construire les classes graduées.")
        return QgsGraduatedSymbolRenderer(field_name, ranges)

    def _apply_labels(
        self,
        layer: QgsVectorLayer,
        field_name: str,
        font_size_pt: float = 9.0,
        placement: str = "auto",
    ) -> None:
        pal = QgsPalLayerSettings()
        pal.fieldName = field_name
        pal.isExpression = False
        pal.drawLabels = True
        text_format = QgsTextFormat()
        text_format.setFont(QFont("Noto Sans"))
        text_format.setSize(max(5.0, min(48.0, float(font_size_pt))))
        text_format.setColor(QColor("#111827"))
        buffer = QgsTextBufferSettings()
        buffer.setEnabled(True)
        buffer.setSize(0.9)
        buffer.setColor(QColor("#ffffff"))
        text_format.setBuffer(buffer)
        pal.setFormat(text_format)
        _set_label_placement(pal, placement, layer)
        layer.setLabeling(QgsVectorLayerSimpleLabeling(pal))
        layer.setLabelsEnabled(True)

    def _choose_label_field(self, layer: QgsVectorLayer) -> str:
        fields = list(layer.fields())
        for hint in self.LABEL_HINTS:
            for field in fields:
                if field.name().casefold() == hint:
                    return field.name()
        for field in fields:
            if not field.isNumeric() and not field.isDateOrTime():
                return field.name()
        return fields[0].name() if fields else ""

    def _profile_fields(self, layer: QgsVectorLayer) -> list[dict[str, Any]]:
        features = []
        for feature in layer.getFeatures():
            features.append(feature)
            if len(features) >= MAX_PROFILE_FEATURES:
                break
        result: list[dict[str, Any]] = []
        for index, field in enumerate(layer.fields()):
            values = [feature[index] for feature in features if feature[index] not in (None, "")]
            if not values:
                continue
            if field.isNumeric():
                numbers = []
                for value in values:
                    try:
                        number = float(value)
                    except (TypeError, ValueError):
                        logging.getLogger(__name__).debug("Non-fatal Cartomize item skipped", exc_info=True)
                        continue
                    if math.isfinite(number):
                        numbers.append(number)
                if numbers:
                    result.append({
                        "name": field.name(), "kind": "numeric", "count": len(numbers),
                        "minimum": min(numbers), "maximum": max(numbers),
                        "unique_count": len(set(numbers)),
                        "score": min(10.0, math.log10(len(numbers) + 1) * 2),
                    })
                continue
            unique = {str(value) for value in values}
            if 2 <= len(unique) <= 20:
                fill = len(values) / max(len(features), 1)
                hint_bonus = 1.0 if field.name().casefold() in self.CLASS_HINTS else 0.0
                result.append({
                    "name": field.name(), "kind": "categorical",
                    "unique_count": len(unique),
                    "score": fill * 6 + (20 - len(unique)) / 20 * 3 + hint_bonus,
                })
        return result


def _quantile_breaks(values: list[float], classes: int) -> list[float]:
    if classes <= 1 or values[0] == values[-1]:
        return [values[0], values[-1]]
    breaks = [values[0]]
    last = len(values) - 1
    for index in range(1, classes):
        position = index * last / classes
        low, high = math.floor(position), math.ceil(position)
        value = values[low] if low == high else values[low] * (high - position) + values[high] * (position - low)
        if value > breaks[-1]:
            breaks.append(value)
    if values[-1] > breaks[-1]:
        breaks.append(values[-1])
    if len(breaks) < 3 and values[0] < values[-1]:
        midpoint = statistics.fmean((values[0], values[-1]))
        breaks.insert(1, midpoint)
    return breaks


def _resample_palette(palette: list[str], count: int) -> list[str]:
    if count <= 0:
        return []
    if count == 1:
        return [palette[len(palette) // 2]]
    return [palette[int(round(index * (len(palette) - 1) / (count - 1)))] for index in range(count)]


def _set_label_placement(pal: QgsPalLayerSettings, placement: str, layer: QgsVectorLayer) -> None:
    """Applique un placement demandé sans dépendre d'une seule API QGIS."""
    requested = str(placement or "auto").casefold()
    if requested == "auto":
        geometry = QgsWkbTypes.geometryType(layer.wkbType())
        requested = {
            QgsWkbTypes.GeometryType.PointGeometry: "around_point",
            QgsWkbTypes.GeometryType.LineGeometry: "line",
            QgsWkbTypes.GeometryType.PolygonGeometry: "horizontal",
        }.get(geometry, "horizontal")
    modern = getattr(Qgis, "LabelPlacement", None)
    names = {
        "around_point": "AroundPoint",
        "over_point": "OverPoint",
        "line": "Line",
        "curved": "Curved",
        "horizontal": "Horizontal",
        "free": "Free",
    }
    enum_name = names.get(requested, "Horizontal")
    value = getattr(modern, enum_name, None) if modern is not None else None
    if value is None:
        value = getattr(QgsPalLayerSettings, enum_name, None)
    if value is not None:
        pal.placement = value
