"""Inspection, diagnostic et schéma de classes pour les rasters Cartomize."""
from __future__ import annotations
import logging

from dataclasses import asdict, dataclass, replace
import json
import math
from pathlib import Path
from typing import Any, Iterable

from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsMapLayerStyle,
    QgsPalettedRasterRenderer,
    QgsProject,
    QgsRasterBandStats,
    QgsRasterLayer,
    QgsRasterTransparency,
)

from .errors import CartomizeError
from .extent_policy import is_remote_basemap
from .raster_intelligence_core import (
    RasterEvidence,
    RasterInference,
    RasterValueProfile,
    infer_raster,
)
from .band_semantics import infer_band_semantics, propose_spectral_indices
from .raster_sampling import (
    RasterSampleSummary,
    exact_valid_values,
    profile_array,
    weighted_quantile_curve,
)


SCHEME_PROPERTY = "cartomize/raster_class_scheme"
DIAGNOSIS_PROPERTY = "cartomize/raster_diagnosis"


@dataclass(frozen=True)
class RasterClassDefinition:
    values: tuple[float, ...]
    label: str
    color: str
    pixel_count: int
    percentage: float
    border_percentage: float
    status: str = "Classe"
    confidence: float = 1.0
    visible: bool = True
    show_in_legend: bool = True
    source: str = "detected"
    opacity: float = 1.0

    @property
    def code_label(self) -> str:
        return ", ".join(_pretty_number(value) for value in self.values)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["values"] = list(self.values)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RasterClassDefinition":
        return cls(
            values=tuple(float(value) for value in payload.get("values", [])),
            label=str(payload.get("label") or "Classe"),
            color=str(payload.get("color") or "#808080"),
            pixel_count=max(0, int(payload.get("pixel_count", 0))),
            percentage=float(payload.get("percentage", 0.0)),
            border_percentage=float(payload.get("border_percentage", 0.0)),
            status=str(payload.get("status") or "Classe"),
            confidence=float(payload.get("confidence", 1.0)),
            visible=bool(payload.get("visible", True)),
            show_in_legend=bool(payload.get("show_in_legend", True)),
            source=str(payload.get("source") or "manual"),
            opacity=max(0.0, min(1.0, float(payload.get("opacity", 1.0)))),
        )


@dataclass(frozen=True)
class RasterInspection:
    layer_id: str
    layer_name: str
    source: str
    provider: str
    storage_type: str
    width: int
    height: int
    total_pixels: int
    crs: str
    extent: tuple[float, float, float, float]
    resolution_x: float | None
    resolution_y: float | None
    band_count: int
    data_types: tuple[str, ...]
    band_names: tuple[str, ...]
    band_color_interpretations: tuple[str, ...]
    statistics: tuple[dict[str, Any], ...]
    source_nodata: tuple[float | None, ...]
    has_mask: bool
    has_alpha: bool
    has_color_table: bool
    has_rat: bool
    metadata: dict[str, str]
    color_table_labels: tuple[tuple[float, str], ...]
    rat_labels: tuple[tuple[float, str], ...]
    value_profiles: tuple[RasterValueProfile, ...]
    exact_counts: bool
    sample_fraction: float
    warnings: tuple[str, ...] = ()
    valid_pixels: int = 0
    nodata_pixels: int = 0
    observed_unique_count: int = 0
    profile_limited: bool = False
    analyzed_band: int = 1
    band_metadata: tuple[dict[str, Any], ...] = ()
    sample_quantiles: tuple[tuple[float, float], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["value_profiles"] = [item.to_dict() for item in self.value_profiles]
        return payload


@dataclass(frozen=True)
class RasterDiagnosis:
    inspection: RasterInspection
    inference: RasterInference
    classes: tuple[RasterClassDefinition, ...]
    recommended_nodata: tuple[dict[str, Any], ...]
    anomalies: tuple[dict[str, Any], ...]
    legend: tuple[tuple[str, str], ...]
    band_semantics: tuple[dict[str, Any], ...] = ()
    spectral_indices: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "inspection": self.inspection.to_dict(),
            "inference": self.inference.to_dict(),
            "classes": [item.to_dict() for item in self.classes],
            "recommended_nodata": list(self.recommended_nodata),
            "anomalies": list(self.anomalies),
            "legend": [list(item) for item in self.legend],
            "band_semantics": list(self.band_semantics),
            "spectral_indices": list(self.spectral_indices),
        }

    def summary_lines(self) -> tuple[str, ...]:
        return (
            f"Type détecté : {raster_type_label(self.inference.raster_type)}",
            f"Confiance : {self.inference.confidence:.0%}",
            f"Bandes : {self.inspection.band_count}",
            f"NoData déclaré : {_nodata_text(self.inspection.source_nodata)}",
            f"Classes détectées : {len(self.classes)}",
            f"Valeurs atypiques : {len(self.anomalies)}",
            f"Table de couleurs : {'présente' if self.inspection.has_color_table else 'absente'}",
            f"Raster Attribute Table : {'présente' if self.inspection.has_rat else 'absente'}",
            f"Comptage : {'exact' if self.inspection.exact_counts else 'échantillonné'}",
            f"Pixels valides estimés : {self.inspection.valid_pixels:,}",
            f"Valeurs distinctes observées : {self.inspection.observed_unique_count:,}",
        )


class RasterIntelligenceEngine:
    """Analyse un raster sans modifier ses pixels et produit un schéma de rendu réversible."""

    QUALITATIVE_COLORS = (
        "#2E7D32", "#F9A825", "#1565C0", "#C62828", "#6A1B9A", "#00838F",
        "#8D6E63", "#7CB342", "#EF6C00", "#3949AB", "#00897B", "#5D4037",
        "#D81B60", "#546E7A", "#43A047", "#FDD835", "#1E88E5", "#E53935",
    )

    def __init__(self, project: QgsProject | None = None):
        self.project = project or QgsProject.instance()
        self._history: dict[str, list[QgsMapLayerStyle]] = {}

    def analyze(self, layer: QgsRasterLayer, *, deep: bool = False, feedback=None) -> RasterDiagnosis:
        """Analyse une couche avec progression/annulation QGIS facultative."""
        self._ensure_thematic_raster(layer)
        inspection = RasterInspector().inspect(layer, deep=deep, feedback=feedback)
        return self.diagnose_inspection(layer, inspection)

    def diagnose_inspection(self, layer: QgsRasterLayer, inspection: RasterInspection) -> RasterDiagnosis:
        band = 1
        evidence = RasterEvidence(
            band_count=inspection.band_count,
            data_type=inspection.data_types[0] if inspection.data_types else "",
            total_pixels=inspection.total_pixels,
            valid_pixels=inspection.valid_pixels or max(0, sum(item.pixel_count for item in inspection.value_profiles)),
            unique_count=inspection.observed_unique_count or len(inspection.value_profiles),
            values=inspection.value_profiles,
            minimum=_stat_value(inspection.statistics, band, "minimum"),
            maximum=_stat_value(inspection.statistics, band, "maximum"),
            source_nodata=inspection.source_nodata[0] if inspection.source_nodata else None,
            has_mask=inspection.has_mask,
            has_alpha=inspection.has_alpha,
            has_color_table=inspection.has_color_table,
            has_rat=inspection.has_rat,
            rat_labels=inspection.rat_labels,
            color_labels=inspection.color_table_labels,
            band_color_interpretations=inspection.band_color_interpretations,
            metadata_text=" ".join(f"{key} {value}" for key, value in inspection.metadata.items()),
            sample_fraction=inspection.sample_fraction,
        )
        inference = infer_raster(evidence)
        classes = self._build_classes(layer, inspection, inference)
        nodata = tuple(item.to_dict() for item in inference.nodata_candidates)
        anomalies = tuple(item.to_dict() for item in inference.anomalous_values)
        legend = tuple((item.label, item.color) for item in classes if item.visible and item.show_in_legend)
        semantics = infer_band_semantics(
            inspection.band_names,
            inspection.band_color_interpretations,
            inspection.band_metadata,
        )
        indices = propose_spectral_indices(semantics)
        diagnosis = RasterDiagnosis(
            inspection, inference, classes, nodata, anomalies, legend,
            tuple(item.to_dict() for item in semantics),
            tuple(item.to_dict() for item in indices),
        )
        layer.setCustomProperty(DIAGNOSIS_PROPERTY, json.dumps(diagnosis.to_dict(), ensure_ascii=False))
        return diagnosis

    def apply_classes(self, layer: QgsRasterLayer, classes: Iterable[RasterClassDefinition], *, band: int = 1) -> None:
        if not isinstance(layer, QgsRasterLayer) or not layer.isValid():
            raise CartomizeError("La couche raster est invalide.")
        self._ensure_thematic_raster(layer)
        class_list = tuple(classes)
        if not class_list:
            raise CartomizeError("Le schéma de classes est vide.")
        self._snapshot(layer)
        provider = layer.dataProvider()
        renderer = _renderer_from_classes(provider, band, class_list)
        layer.setRenderer(renderer)
        layer.setCustomProperty(SCHEME_PROPERTY, json.dumps([item.to_dict() for item in class_list], ensure_ascii=False))
        layer.setCustomProperty("cartomize/raster_band", int(band))
        layer.setCustomProperty("cartomize/raster_intelligence", True)
        layer.triggerRepaint()
        self.project.setDirty(True)

    @staticmethod
    def _ensure_thematic_raster(layer: QgsRasterLayer) -> None:
        """Exclut les fonds web du moteur d'analyse et de classification."""

        if not isinstance(layer, QgsRasterLayer) or not layer.isValid():
            raise CartomizeError("La couche raster est invalide.")
        if is_remote_basemap(
            layer.providerType(),
            layer.source(),
            layer.name(),
        ):
            raise CartomizeError(
                "Le fond cartographique distant est une couche de contexte, "
                "pas un raster thématique à analyser ou reclasser."
            )

    def saved_classes(self, layer: QgsRasterLayer) -> tuple[RasterClassDefinition, ...]:
        raw = str(layer.customProperty(SCHEME_PROPERTY, "") or "")
        if not raw:
            return ()
        try:
            payload = json.loads(raw)
            return tuple(RasterClassDefinition.from_dict(item) for item in payload if isinstance(item, dict))
        except Exception:
            return ()

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

    def _build_classes(
        self,
        layer: QgsRasterLayer,
        inspection: RasterInspection,
        inference: RasterInference,
    ) -> tuple[RasterClassDefinition, ...]:
        profiles = {float(item.value): item for item in inspection.value_profiles}
        rat_labels = {float(value): label for value, label in inspection.rat_labels}
        color_labels = {float(value): label for value, label in inspection.color_table_labels}
        existing_labels, existing_colors = _renderer_labels(layer)
        palette = self.QUALITATIVE_COLORS
        result: list[RasterClassDefinition] = []
        explicit_nodata = {
            float(value) for value in inspection.source_nodata
            if value is not None and _finite(value)
        }
        anomaly_values = {float(item.value): item.confidence for item in inference.anomalous_values}
        automatic_nodata = {float(value) for value in inference.automatic_nodata_values}
        all_values = tuple(sorted({
            *(float(value) for value in inference.class_values),
            *automatic_nodata,
        }))
        visible_index = 0
        for value in all_values:
            profile = profiles.get(float(value), RasterValueProfile(float(value), 0, 0.0))
            is_automatic_nodata = float(value) in automatic_nodata
            metadata_label = (
                rat_labels.get(float(value))
                or color_labels.get(float(value))
                or existing_labels.get(float(value))
                or _known_class_label(layer, value)
            )
            label = (
                f"Fond / NoData détecté ({_pretty_number(value)})"
                if is_automatic_nodata
                else metadata_label or f"Classe {_pretty_number(value)}"
            )
            color = existing_colors.get(float(value)) or palette[visible_index % len(palette)]
            if not is_automatic_nodata:
                visible_index += 1
            status = (
                "NoData visuel automatique"
                if is_automatic_nodata
                else "Valeur atypique" if float(value) in anomaly_values else "Classe"
            )
            confidence = anomaly_values.get(float(value), inference.confidence)
            result.append(
                RasterClassDefinition(
                    values=(float(value),),
                    label=label,
                    color=color,
                    pixel_count=profile.pixel_count,
                    percentage=profile.percentage,
                    border_percentage=profile.border_percentage,
                    status=status,
                    confidence=confidence,
                    visible=not is_automatic_nodata and float(value) not in explicit_nodata,
                    show_in_legend=not is_automatic_nodata and float(value) not in explicit_nodata,
                    source=(
                        "source_nodata" if float(value) in explicit_nodata
                        else "automatic_nodata" if is_automatic_nodata
                        else "metadata" if float(value) in rat_labels or float(value) in color_labels
                        else "detected"
                    ),
                )
            )
        return tuple(result)


class RasterInspector:
    """Collecte les métadonnées et un profil statistique sans écrire dans la source."""

    SAMPLE_SIDE = 512
    MAX_EXACT_PIXELS = 25_000_000

    def inspect(self, layer: QgsRasterLayer, *, deep: bool = False, feedback=None) -> RasterInspection:
        if not isinstance(layer, QgsRasterLayer) or not layer.isValid():
            raise CartomizeError("Sélectionnez une couche raster valide.")
        source = _source_path(layer.source())
        gdal_result = self._inspect_gdal(source, deep=deep, feedback=feedback) if source else None
        if gdal_result:
            return replace(gdal_result, layer_id=layer.id(), layer_name=layer.name(), provider=layer.providerType())
        return self._inspect_provider(layer)

    def inspect_source(self, source: str, *, deep: bool = True, feedback=None) -> RasterInspection:
        result = self._inspect_gdal(_source_path(source) or source, deep=deep, feedback=feedback)
        if result is None:
            raise CartomizeError("L’analyse approfondie exige une source raster locale lisible par GDAL.")
        return result

    def _inspect_provider(self, layer: QgsRasterLayer) -> RasterInspection:
        provider = layer.dataProvider()
        width, height = int(layer.width()), int(layer.height())
        total = max(0, width * height)
        statistics: list[dict[str, Any]] = []
        nodata: list[float | None] = []
        data_types: list[str] = []
        warnings = ["Analyse basée sur le fournisseur QGIS. Les fréquences sont échantillonnées."]
        for band in range(1, max(1, layer.bandCount()) + 1):
            minimum = maximum = None
            try:
                stats = provider.bandStatistics(
                    band,
                    QgsRasterBandStats.Stats.All,
                    layer.extent(),
                    250_000,
                )
                minimum, maximum = float(stats.minimumValue), float(stats.maximumValue)
            except Exception:
                logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
            statistics.append({"band": band, "minimum": minimum, "maximum": maximum})
            try:
                nodata.append(float(provider.sourceNoDataValue(band)) if provider.sourceHasNoDataValue(band) else None)
            except Exception:
                nodata.append(None)
            try:
                data_types.append(str(provider.sourceDataType(band)))
            except Exception:
                data_types.append("")
        sample = self._sample_provider(layer, 1)
        metadata = {"layer_name": layer.name(), "source": layer.source(), "provider": layer.providerType()}
        extent = layer.extent()
        valid_estimate = int(round(sample.valid_pixels / max(1, sample.sampled_pixels) * total))
        nodata_estimate = max(0, total - valid_estimate)
        return RasterInspection(
            layer_id=layer.id(), layer_name=layer.name(), source=layer.source(),
            provider=layer.providerType(), storage_type=_safe_call(provider, "storageType", ""),
            width=width, height=height, total_pixels=total,
            crs=layer.crs().authid() or layer.crs().description(),
            extent=(extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum()),
            resolution_x=abs(extent.width() / width) if width else None,
            resolution_y=abs(extent.height() / height) if height else None,
            band_count=max(1, layer.bandCount()), data_types=tuple(data_types),
            band_names=tuple(_band_names(provider, layer.bandCount())),
            band_color_interpretations=(), statistics=tuple(statistics),
            source_nodata=tuple(nodata), has_mask=False, has_alpha=False,
            has_color_table=_provider_has_color_table(provider), has_rat=_provider_has_rat(provider),
            metadata=metadata, color_table_labels=(), rat_labels=(),
            value_profiles=sample.profiles, exact_counts=False,
            sample_fraction=min(1.0, sample.sampled_pixels / max(1, total)),
            warnings=tuple(warnings), valid_pixels=valid_estimate, nodata_pixels=nodata_estimate,
            observed_unique_count=sample.observed_unique_count,
            profile_limited=sample.profile_limited, analyzed_band=1,
            sample_quantiles=sample.quantiles,
        )

    def _sample_provider(self, layer: QgsRasterLayer, band: int) -> RasterSampleSummary:
        provider = layer.dataProvider()
        side_x = min(self.SAMPLE_SIDE, max(1, layer.width()))
        side_y = min(self.SAMPLE_SIDE, max(1, layer.height()))
        try:
            block = provider.block(band, layer.extent(), side_x, side_y)
        except Exception:
            return RasterSampleSummary((), 0, 0, 0, 0, False)
        counts: dict[float, int] = {}
        border: dict[float, int] = {}
        center: dict[float, int] = {}
        corners: dict[float, int] = {}
        border_total = center_total = corner_total = 0
        edge = max(1, min(side_x, side_y) // 20)
        corner_edge = max(1, min(side_x, side_y) // 10)
        for row in range(side_y):
            for col in range(side_x):
                try:
                    if hasattr(block, "isNoData") and block.isNoData(row, col):
                        continue
                    value = float(block.value(row, col))
                except Exception:
                    logging.getLogger(__name__).debug("Non-fatal Cartomize item skipped", exc_info=True)
                    continue
                if not math.isfinite(value):
                    continue
                counts[value] = counts.get(value, 0) + 1
                is_border = row < edge or col < edge or row >= side_y - edge or col >= side_x - edge
                if is_border:
                    border[value] = border.get(value, 0) + 1
                    border_total += 1
                else:
                    center[value] = center.get(value, 0) + 1
                    center_total += 1
                is_corner = (
                    (row < corner_edge or row >= side_y - corner_edge)
                    and (col < corner_edge or col >= side_x - corner_edge)
                )
                if is_corner:
                    corners[value] = corners.get(value, 0) + 1
                    corner_total += 1
        sample_total = sum(counts.values())
        sampled_pixels = side_x * side_y
        total_pixels = max(1, layer.width() * layer.height())
        valid_population = int(round(
            sample_total / max(1, sampled_pixels) * total_pixels
        ))
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:4096]
        profiles = tuple(
            RasterValueProfile(
                value,
                int(round(count / max(1, sample_total) * valid_population)),
                count / max(1, sample_total) * 100.0,
                border.get(value, 0) / max(1, border_total),
                center.get(value, 0) / max(1, center_total),
                True,
                corners.get(value, 0) / max(1, corner_total),
            )
            for value, count in sorted(ranked, key=lambda item: item[0])
        )
        return RasterSampleSummary(
            profiles, sampled_pixels, sample_total, sampled_pixels - sample_total,
            len(counts), len(counts) > 4096, weighted_quantile_curve(counts),
        )

    def _inspect_gdal(self, source: str, *, deep: bool, feedback=None) -> RasterInspection | None:
        try:
            from osgeo import gdal
        except Exception:
            return None
        try:
            ds = gdal.OpenEx(source, gdal.OF_RASTER | gdal.OF_READONLY)
        except Exception:
            ds = None
        if ds is None:
            return None
        width, height, bands = int(ds.RasterXSize), int(ds.RasterYSize), int(ds.RasterCount)
        total = max(0, width * height)
        geotransform = ds.GetGeoTransform(can_return_null=True)
        projection = ds.GetProjectionRef() or ""
        metadata = {str(k): str(v) for k, v in (ds.GetMetadata() or {}).items()}
        metadata.setdefault("driver", getattr(ds.GetDriver(), "ShortName", ""))
        metadata.setdefault("description", ds.GetDescription() or source)
        _feedback_progress(feedback, 2)
        stats_rows: list[dict[str, Any]] = []
        nodata: list[float | None] = []
        data_types: list[str] = []
        names: list[str] = []
        color_interpretations: list[str] = []
        band_metadata: list[dict[str, Any]] = []
        has_mask = has_alpha = has_color_table = has_rat = False
        color_labels: list[tuple[float, str]] = []
        rat_labels: list[tuple[float, str]] = []
        first_band_array = None
        first_band_mask = None
        exact_counts = False
        warnings: list[str] = []

        for number in range(1, bands + 1):
            if _feedback_cancelled(feedback):
                return None
            band = ds.GetRasterBand(number)
            nodata_value = band.GetNoDataValue()
            nodata.append(float(nodata_value) if nodata_value is not None else None)
            data_types.append(gdal.GetDataTypeName(band.DataType) or "")
            names.append(band.GetDescription() or f"Bande {number}")
            interpretation = gdal.GetColorInterpretationName(band.GetColorInterpretation()) or ""
            color_interpretations.append(interpretation)
            current_metadata = {str(k): str(v) for k, v in (band.GetMetadata() or {}).items()}
            current_metadata["description"] = band.GetDescription() or f"Bande {number}"
            current_metadata["color_interpretation"] = interpretation
            scale, offset, unit = band.GetScale(), band.GetOffset(), band.GetUnitType()
            if scale is not None:
                current_metadata["scale"] = str(scale)
            if offset is not None:
                current_metadata["offset"] = str(offset)
            if unit:
                current_metadata["unit"] = str(unit)
            band_metadata.append(current_metadata)
            has_alpha = has_alpha or interpretation.casefold() == "alpha"
            try:
                mask_flags = int(band.GetMaskFlags())
                has_mask = has_mask or mask_flags != int(getattr(gdal, "GMF_ALL_VALID", 1))
            except Exception:
                logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
            table = band.GetColorTable()
            if table is not None:
                has_color_table = True
                if number == 1:
                    for index in range(min(table.GetCount(), 4096)):
                        color_labels.append((float(index), f"Classe {index}"))
            rat = band.GetDefaultRAT()
            if rat is not None and rat.GetRowCount() > 0:
                has_rat = True
                if number == 1:
                    rat_labels.extend(_read_rat_labels(rat))
            minimum = maximum = mean = stddev = None
            try:
                # Ne force jamais un balayage complet pendant l'inspection rapide.
                statistics = band.GetStatistics(False, False)
                if statistics:
                    minimum, maximum, mean, stddev = [float(value) for value in statistics]
            except Exception:
                logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
            stats_rows.append({"band": number, "minimum": minimum, "maximum": maximum, "mean": mean, "stddev": stddev})
            if number == 1:
                sx, sy = min(self.SAMPLE_SIDE, width), min(self.SAMPLE_SIDE, height)
                try:
                    first_band_array = band.ReadAsArray(0, 0, width, height, sx, sy)
                    mask_band = band.GetMaskBand()
                    first_band_mask = mask_band.ReadAsArray(0, 0, width, height, sx, sy) if mask_band else None
                except Exception as exc:
                    warnings.append(f"Échantillonnage GDAL incomplet : {exc}")
            _feedback_progress(feedback, 5 + number / max(1, bands) * 30)

        sample = profile_array(
            first_band_array, first_band_mask, nodata[0] if nodata else None,
            max_profiles=4096,
        )
        estimated_valid_population = int(round(
            sample.valid_pixels / max(1, sample.sampled_pixels) * total
        ))
        if sample.valid_pixels:
            sample = profile_array(
                first_band_array, first_band_mask, nodata[0] if nodata else None,
                total_pixels=estimated_valid_population, max_profiles=4096,
            )
        profiles = sample.profiles
        if stats_rows and first_band_array is not None and stats_rows[0].get("minimum") is None:
            valid_values, _ = exact_valid_values(first_band_array, first_band_mask, nodata[0] if nodata else None)
            if getattr(valid_values, "size", 0):
                stats_rows[0].update({
                    "minimum": float(valid_values.min()), "maximum": float(valid_values.max()),
                    "mean": float(valid_values.mean()), "stddev": float(valid_values.std()),
                    "estimated": True,
                })

        dtype_text = (data_types[0] if data_types else "").casefold()
        categorical_storage = (
            has_color_table or has_rat
            or (any(token in dtype_text for token in ("byte", "int", "uint")) and "float" not in dtype_text)
        )
        exact_allowed = (
            deep and total <= self.MAX_EXACT_PIXELS and bands and categorical_storage
            and not sample.profile_limited and sample.observed_unique_count <= 4096
        )
        if exact_allowed:
            try:
                exact, exact_valid, exact_nodata = _exact_counts_gdal(
                    ds.GetRasterBand(1), width, height, nodata[0] if nodata else None,
                    feedback=feedback, max_unique=4096,
                )
                profiles = _merge_exact_counts(profiles, exact, exact_valid)
                exact_counts = True
            except Exception as exc:
                warnings.append(f"Comptage exact indisponible : {exc}")
        elif deep:
            warnings.append(
                "Le comptage exact a été remplacé par un échantillonnage contrôlé "
                "(volume, type continu ou cardinalité trop élevée)."
            )

        if geotransform:
            resolution_x = abs(float(geotransform[1]))
            resolution_y = abs(float(geotransform[5]))
            minx = float(geotransform[0])
            maxy = float(geotransform[3])
            maxx = minx + width * float(geotransform[1]) + height * float(geotransform[2])
            miny = maxy + width * float(geotransform[4]) + height * float(geotransform[5])
            extent = (min(minx, maxx), min(miny, maxy), max(minx, maxx), max(miny, maxy))
        else:
            resolution_x = resolution_y = None
            extent = (0.0, 0.0, float(width), float(height))
        valid_pixels = exact_valid if exact_counts else int(round(sample.valid_pixels / max(1, sample.sampled_pixels) * total))
        nodata_pixels = exact_nodata if exact_counts else max(0, total - valid_pixels)
        _feedback_progress(feedback, 100)
        return RasterInspection(
            layer_id="", layer_name="", source=source, provider="gdal",
            storage_type=metadata.get("driver", ""), width=width, height=height,
            total_pixels=total, crs=projection, extent=extent,
            resolution_x=resolution_x, resolution_y=resolution_y, band_count=bands,
            data_types=tuple(data_types), band_names=tuple(names),
            band_color_interpretations=tuple(color_interpretations),
            statistics=tuple(stats_rows), source_nodata=tuple(nodata), has_mask=has_mask,
            has_alpha=has_alpha, has_color_table=has_color_table, has_rat=has_rat,
            metadata=metadata, color_table_labels=tuple(color_labels), rat_labels=tuple(rat_labels),
            value_profiles=profiles, exact_counts=exact_counts,
            sample_fraction=min(1.0, sample.sampled_pixels / max(1, total)),
            warnings=tuple(warnings), valid_pixels=valid_pixels, nodata_pixels=nodata_pixels,
            observed_unique_count=len(profiles) if exact_counts else sample.observed_unique_count,
            profile_limited=sample.profile_limited, analyzed_band=1,
            band_metadata=tuple(band_metadata),
            sample_quantiles=sample.quantiles,
        )


def raster_type_label(code: str) -> str:
    return {
        "binary": "Raster binaire",
        "categorized": "Raster catégoriel / classifié",
        "continuous": "Raster continu",
        "rgb": "Image RGB",
        "multiband": "Raster multibande",
    }.get(code, code)


def _renderer_from_classes(provider, band: int, classes: tuple[RasterClassDefinition, ...]):
    visible = [item for item in classes if item.visible]
    hidden_values = tuple(
        float(value)
        for item in classes if not item.visible
        for value in item.values
    )
    multi_type = getattr(QgsPalettedRasterRenderer, "MultiValueClass", None)
    if multi_type is not None and hasattr(QgsPalettedRasterRenderer, "setMultiValueClasses"):
        try:
            flattened = []
            for item in visible:
                color = QColor(item.color)
                color.setAlphaF(max(0.0, min(1.0, item.opacity)))
                for value in item.values:
                    flattened.append(QgsPalettedRasterRenderer.Class(float(value), color, item.label if item.show_in_legend else ""))
            renderer = QgsPalettedRasterRenderer(provider, band, flattened)
            multi = []
            for item in visible:
                color = QColor(item.color)
                color.setAlphaF(max(0.0, min(1.0, item.opacity)))
                multi.append(multi_type(list(item.values), color, item.label if item.show_in_legend else ""))
            renderer.setMultiValueClasses(multi)
            return apply_visual_nodata_transparency(renderer, hidden_values)
        except Exception:
            logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
    flat = []
    for item in visible:
        color = QColor(item.color)
        color.setAlphaF(max(0.0, min(1.0, item.opacity)))
        for value in item.values:
            flat.append(QgsPalettedRasterRenderer.Class(float(value), color, item.label if item.show_in_legend else ""))
    renderer = QgsPalettedRasterRenderer(provider, band, flat)
    return apply_visual_nodata_transparency(renderer, hidden_values)


def apply_visual_nodata_transparency(renderer, values: Iterable[float]):
    """Masque des codes NoData dans le rendu, sans modifier le raster source."""
    unique = tuple(sorted({float(value) for value in values if _finite(value)}))
    if renderer is None or not unique:
        return renderer
    try:
        transparency = QgsRasterTransparency()
        pixel_type = QgsRasterTransparency.TransparentSingleValuePixel
        pixels = []
        for value in unique:
            try:
                pixel = pixel_type(value, value, 0.0)
            except TypeError:
                pixel = pixel_type()
                if hasattr(pixel, "min"):
                    pixel.min = value
                    pixel.max = value
                else:
                    pixel.minimum = value
                    pixel.maximum = value
                if hasattr(pixel, "opacity"):
                    pixel.opacity = 0.0
                elif hasattr(pixel, "percentTransparent"):
                    pixel.percentTransparent = 100.0
            pixels.append(pixel)
        transparency.setTransparentSingleValuePixelList(pixels)
        renderer.setRasterTransparency(transparency)
        if hasattr(renderer, "setNodataColor"):
            renderer.setNodataColor(QColor(0, 0, 0, 0))
    except Exception:
        logging.getLogger(__name__).warning(
            "Impossible d'appliquer la transparence NoData au renderer raster.",
            exc_info=True,
        )
    return renderer


def _exact_counts_gdal(
    band,
    width: int,
    height: int,
    nodata: float | None,
    *,
    feedback=None,
    max_unique: int = 4096,
) -> tuple[dict[float, int], int, int]:
    import numpy as np
    counts: dict[float, int] = {}
    valid_total = nodata_total = 0
    block_y = max(256, min(2048, int(8_000_000 / max(1, width))))
    for yoff in range(0, height, block_y):
        if _feedback_cancelled(feedback):
            raise CartomizeError("Analyse raster annulée par l’utilisateur.")
        rows = min(block_y, height - yoff)
        array = band.ReadAsArray(0, yoff, width, rows)
        if array is None:
            continue
        mask_band = band.GetMaskBand()
        mask = mask_band.ReadAsArray(0, yoff, width, rows) if mask_band else None
        valid_values, invalid_count = exact_valid_values(array, mask, nodata)
        valid_total += int(valid_values.size)
        nodata_total += invalid_count
        unique, value_counts = np.unique(valid_values, return_counts=True)
        for value, count in zip(unique.tolist(), value_counts.tolist()):
            value_f = float(value)
            counts[value_f] = counts.get(value_f, 0) + int(count)
        if len(counts) > max_unique:
            raise CartomizeError(
                f"Plus de {max_unique} valeurs distinctes : comptage exact interrompu pour protéger la mémoire."
            )
        _feedback_progress(feedback, 35 + (yoff + rows) / max(1, height) * 60)
    return counts, valid_total, nodata_total


def _merge_exact_counts(profiles: tuple[RasterValueProfile, ...], exact: dict[float, int], valid_total: int) -> tuple[RasterValueProfile, ...]:
    profile_map = {float(item.value): item for item in profiles}
    result = []
    for value, count in sorted(exact.items()):
        old = profile_map.get(value)
        result.append(
            RasterValueProfile(
                value,
                count,
                count / max(1, valid_total) * 100.0,
                old.border_percentage if old else 0.0,
                old.center_percentage if old else 0.0,
                False,
                old.corner_percentage if old else 0.0,
            )
        )
    return tuple(result)


def _read_rat_labels(rat) -> list[tuple[float, str]]:
    result: list[tuple[float, str]] = []
    try:
        from osgeo import gdal
        value_col = name_col = -1
        for col in range(rat.GetColumnCount()):
            usage = rat.GetUsageOfCol(col)
            if usage in {getattr(gdal, "GFU_Min", -2), getattr(gdal, "GFU_MinMax", -3)} and value_col < 0:
                value_col = col
            if usage == getattr(gdal, "GFU_Name", -4):
                name_col = col
        if value_col < 0:
            value_col = 0
        for row in range(min(rat.GetRowCount(), 4096)):
            try:
                value = float(rat.GetValueAsDouble(row, value_col))
                label = rat.GetValueAsString(row, name_col).strip() if name_col >= 0 else ""
                if label:
                    result.append((value, label))
            except Exception:
                logging.getLogger(__name__).debug("Non-fatal Cartomize item skipped", exc_info=True)
                continue
    except Exception:
        logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
    return result


def _renderer_labels(layer: QgsRasterLayer) -> tuple[dict[float, str], dict[float, str]]:
    labels: dict[float, str] = {}
    colors: dict[float, str] = {}
    renderer = layer.renderer()
    if renderer is None or not hasattr(renderer, "classes"):
        return labels, colors
    try:
        for item in renderer.classes():
            value = float(getattr(item, "value"))
            label = str(getattr(item, "label", "") or "").strip()
            color = getattr(item, "color", None)
            if label:
                labels[value] = label
            if color is not None and hasattr(color, "name"):
                colors[value] = color.name()
    except Exception:
        logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
    return labels, colors


def _known_class_label(layer: QgsRasterLayer, value: float) -> str:
    text = f"{layer.name()} {layer.source()}".casefold()
    ivalue = int(round(value)) if abs(value - round(value)) < 1e-9 else None
    if "worldcover" in text or "esa" in text:
        labels = {10:"Couvert arboré",20:"Arbustes",30:"Prairies",40:"Cultures",50:"Zones bâties",60:"Sol nu ou végétation clairsemée",70:"Neige et glace",80:"Eau permanente",90:"Zones humides herbacées",95:"Mangroves",100:"Mousses et lichens"}
        return labels.get(ivalue, "")
    if any(token in text for token in ("foret", "forêt", "forest")) and ivalue in {0, 1}:
        return {0: "Non-forêt", 1: "Forêt"}[ivalue]
    return ""


def _provider_has_color_table(provider) -> bool:
    try:
        return bool(provider.colorTable(1))
    except Exception:
        return False


def _provider_has_rat(provider) -> bool:
    try:
        return provider.attributeTable(1) is not None
    except Exception:
        return False


def _band_names(provider, count: int) -> list[str]:
    names = []
    for band in range(1, max(1, count) + 1):
        try:
            names.append(str(provider.generateBandName(band)))
        except Exception:
            names.append(f"Bande {band}")
    return names


def _safe_call(obj, name: str, default):
    try:
        return str(getattr(obj, name)())
    except Exception:
        return default


def _source_path(source: str) -> str:
    if not source:
        return ""
    candidate = source.split("|", 1)[0]
    if candidate.lower().startswith("file://"):
        candidate = candidate[7:]
    return candidate if Path(candidate).exists() else ""


def _stat_value(rows: tuple[dict[str, Any], ...], band: int, key: str) -> float | None:
    for row in rows:
        if int(row.get("band", 0)) == band:
            value = row.get(key)
            try:
                return float(value) if value is not None else None
            except Exception:
                return None
    return None


def _pretty_number(value: float) -> str:
    return str(int(round(value))) if abs(value - round(value)) < 1e-9 else f"{value:.6g}"


def _nodata_text(values: tuple[float | None, ...]) -> str:
    shown = [_pretty_number(value) for value in values if value is not None]
    return ", ".join(shown) if shown else "Non déclaré"


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except Exception:
        return False


def _feedback_cancelled(feedback) -> bool:
    if feedback is None:
        return False
    try:
        return bool(feedback.isCanceled())
    except Exception:
        return False


def _feedback_progress(feedback, value: float) -> None:
    if feedback is None:
        return
    try:
        feedback.setProgress(max(0.0, min(100.0, float(value))))
    except Exception:
        logging.getLogger(__name__).debug("Impossible de publier la progression raster", exc_info=True)
