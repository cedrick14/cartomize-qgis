"""Inspection, diagnostic et schéma de classes pour les rasters Cartomize."""
from __future__ import annotations

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
)

from .errors import CartomizeError
from .raster_intelligence_core import (
    RasterEvidence,
    RasterInference,
    RasterValueProfile,
    infer_raster,
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "inspection": self.inspection.to_dict(),
            "inference": self.inference.to_dict(),
            "classes": [item.to_dict() for item in self.classes],
            "recommended_nodata": list(self.recommended_nodata),
            "anomalies": list(self.anomalies),
            "legend": [list(item) for item in self.legend],
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

    def analyze(self, layer: QgsRasterLayer, *, deep: bool = False) -> RasterDiagnosis:
        inspection = RasterInspector().inspect(layer, deep=deep)
        return self.diagnose_inspection(layer, inspection)

    def diagnose_inspection(self, layer: QgsRasterLayer, inspection: RasterInspection) -> RasterDiagnosis:
        band = 1
        evidence = RasterEvidence(
            band_count=inspection.band_count,
            data_type=inspection.data_types[0] if inspection.data_types else "",
            total_pixels=inspection.total_pixels,
            valid_pixels=max(0, sum(item.pixel_count for item in inspection.value_profiles)),
            unique_count=len(inspection.value_profiles),
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
        diagnosis = RasterDiagnosis(inspection, inference, classes, nodata, anomalies, legend)
        layer.setCustomProperty(DIAGNOSIS_PROPERTY, json.dumps(diagnosis.to_dict(), ensure_ascii=False))
        return diagnosis

    def apply_classes(self, layer: QgsRasterLayer, classes: Iterable[RasterClassDefinition], *, band: int = 1) -> None:
        if not isinstance(layer, QgsRasterLayer) or not layer.isValid():
            raise CartomizeError("La couche raster est invalide.")
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
        for index, value in enumerate(inference.class_values):
            profile = profiles.get(float(value), RasterValueProfile(float(value), 0, 0.0))
            label = (
                rat_labels.get(float(value))
                or color_labels.get(float(value))
                or existing_labels.get(float(value))
                or _known_class_label(layer, value)
                or f"Classe {_pretty_number(value)}"
            )
            color = existing_colors.get(float(value)) or palette[index % len(palette)]
            status = "Valeur atypique" if float(value) in anomaly_values else "Classe"
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
                    visible=float(value) not in explicit_nodata,
                    show_in_legend=float(value) not in explicit_nodata,
                    source="metadata" if float(value) in rat_labels or float(value) in color_labels else "detected",
                )
            )
        return tuple(result)


class RasterInspector:
    """Collecte les métadonnées et un profil statistique sans écrire dans la source."""

    SAMPLE_SIDE = 512
    MAX_EXACT_PIXELS = 25_000_000

    def inspect(self, layer: QgsRasterLayer, *, deep: bool = False) -> RasterInspection:
        if not isinstance(layer, QgsRasterLayer) or not layer.isValid():
            raise CartomizeError("Sélectionnez une couche raster valide.")
        source = _source_path(layer.source())
        gdal_result = self._inspect_gdal(source, deep=deep) if source else None
        if gdal_result:
            return replace(gdal_result, layer_id=layer.id(), layer_name=layer.name(), provider=layer.providerType())
        return self._inspect_provider(layer)

    def inspect_source(self, source: str, *, deep: bool = True) -> RasterInspection:
        result = self._inspect_gdal(_source_path(source) or source, deep=deep)
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
                stats = provider.bandStatistics(band, QgsRasterBandStats.All, layer.extent(), 250_000)
                minimum, maximum = float(stats.minimumValue), float(stats.maximumValue)
            except Exception:
                pass
            statistics.append({"band": band, "minimum": minimum, "maximum": maximum})
            try:
                nodata.append(float(provider.sourceNoDataValue(band)) if provider.sourceHasNoDataValue(band) else None)
            except Exception:
                nodata.append(None)
            try:
                data_types.append(str(provider.sourceDataType(band)))
            except Exception:
                data_types.append("")
        profiles = self._sample_provider(layer, 1)
        metadata = {"layer_name": layer.name(), "source": layer.source(), "provider": layer.providerType()}
        extent = layer.extent()
        return RasterInspection(
            layer.id(), layer.name(), layer.source(), layer.providerType(), _safe_call(provider, "storageType", ""),
            width, height, total, layer.crs().authid() or layer.crs().description(),
            (extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum()),
            abs(extent.width() / width) if width else None, abs(extent.height() / height) if height else None,
            max(1, layer.bandCount()), tuple(data_types), tuple(_band_names(provider, layer.bandCount())), (),
            tuple(statistics), tuple(nodata), False, False, _provider_has_color_table(provider), _provider_has_rat(provider),
            metadata, (), (), profiles, False, min(1.0, len(profiles) / max(1, total)), tuple(warnings),
        )

    def _sample_provider(self, layer: QgsRasterLayer, band: int) -> tuple[RasterValueProfile, ...]:
        provider = layer.dataProvider()
        side_x = min(self.SAMPLE_SIDE, max(1, layer.width()))
        side_y = min(self.SAMPLE_SIDE, max(1, layer.height()))
        try:
            block = provider.block(band, layer.extent(), side_x, side_y)
        except Exception:
            return ()
        counts: dict[float, int] = {}
        border: dict[float, int] = {}
        center: dict[float, int] = {}
        border_total = center_total = 0
        edge = max(1, min(side_x, side_y) // 20)
        for row in range(side_y):
            for col in range(side_x):
                try:
                    if hasattr(block, "isNoData") and block.isNoData(row, col):
                        continue
                    value = float(block.value(row, col))
                except Exception:
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
        sample_total = sum(counts.values())
        total_pixels = max(1, layer.width() * layer.height())
        return tuple(
            RasterValueProfile(
                value,
                int(round(count / max(1, sample_total) * total_pixels)),
                count / max(1, sample_total) * 100.0,
                border.get(value, 0) / max(1, border_total),
                center.get(value, 0) / max(1, center_total),
                True,
            )
            for value, count in sorted(counts.items(), key=lambda item: item[0])[:4096]
        )

    def _inspect_gdal(self, source: str, *, deep: bool) -> RasterInspection | None:
        try:
            from osgeo import gdal
            import numpy as np
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
        stats_rows: list[dict[str, Any]] = []
        nodata: list[float | None] = []
        data_types: list[str] = []
        names: list[str] = []
        color_interpretations: list[str] = []
        has_mask = has_alpha = has_color_table = has_rat = False
        color_labels: list[tuple[float, str]] = []
        rat_labels: list[tuple[float, str]] = []
        first_band_array = None
        first_band_mask = None
        exact_counts = False
        warnings: list[str] = []

        for number in range(1, bands + 1):
            band = ds.GetRasterBand(number)
            nodata_value = band.GetNoDataValue()
            nodata.append(float(nodata_value) if nodata_value is not None else None)
            data_types.append(gdal.GetDataTypeName(band.DataType) or "")
            names.append(band.GetDescription() or f"Bande {number}")
            interpretation = gdal.GetColorInterpretationName(band.GetColorInterpretation()) or ""
            color_interpretations.append(interpretation)
            has_alpha = has_alpha or interpretation.casefold() == "alpha"
            try:
                mask_flags = int(band.GetMaskFlags())
                has_mask = has_mask or mask_flags != int(getattr(gdal, "GMF_ALL_VALID", 1))
            except Exception:
                pass
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
                statistics = band.GetStatistics(False, True)
                if statistics:
                    minimum, maximum, mean, stddev = [float(value) for value in statistics]
            except Exception:
                pass
            stats_rows.append({"band": number, "minimum": minimum, "maximum": maximum, "mean": mean, "stddev": stddev})
            if number == 1:
                sx, sy = min(self.SAMPLE_SIDE, width), min(self.SAMPLE_SIDE, height)
                try:
                    first_band_array = band.ReadAsArray(0, 0, width, height, sx, sy)
                    mask_band = band.GetMaskBand()
                    first_band_mask = mask_band.ReadAsArray(0, 0, width, height, sx, sy) if mask_band else None
                except Exception as exc:
                    warnings.append(f"Échantillonnage GDAL incomplet : {exc}")

        profiles = _profiles_from_array(first_band_array, first_band_mask, nodata[0] if nodata else None, total)
        if deep and total <= self.MAX_EXACT_PIXELS and bands:
            try:
                exact = _exact_counts_gdal(ds.GetRasterBand(1), width, height, nodata[0] if nodata else None)
                profiles = _merge_exact_counts(profiles, exact, total)
                exact_counts = True
            except Exception as exc:
                warnings.append(f"Comptage exact indisponible : {exc}")
        elif deep and total > self.MAX_EXACT_PIXELS:
            warnings.append("Le raster est volumineux. Les fréquences restent échantillonnées pour préserver la réactivité.")

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
        sampled = max(1, sum(1 for _ in _flatten_valid(first_band_array))) if first_band_array is not None else 0
        sample_fraction = min(1.0, sampled / max(1, total))
        return RasterInspection(
            "", "", source, "gdal", metadata.get("driver", ""), width, height, total,
            projection, extent, resolution_x, resolution_y, bands, tuple(data_types), tuple(names), tuple(color_interpretations),
            tuple(stats_rows), tuple(nodata), has_mask, has_alpha, has_color_table, has_rat, metadata,
            tuple(color_labels), tuple(rat_labels), profiles, exact_counts, sample_fraction, tuple(warnings),
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
    multi_type = getattr(QgsPalettedRasterRenderer, "MultiValueClass", None)
    if multi_type is not None and hasattr(QgsPalettedRasterRenderer, "setMultiValueClasses"):
        try:
            flattened = []
            for item in visible:
                for value in item.values:
                    flattened.append(QgsPalettedRasterRenderer.Class(float(value), QColor(item.color), item.label if item.show_in_legend else ""))
            renderer = QgsPalettedRasterRenderer(provider, band, flattened)
            multi = [multi_type(list(item.values), QColor(item.color), item.label if item.show_in_legend else "") for item in visible]
            renderer.setMultiValueClasses(multi)
            return renderer
        except Exception:
            pass
    flat = []
    for item in visible:
        for value in item.values:
            flat.append(QgsPalettedRasterRenderer.Class(float(value), QColor(item.color), item.label if item.show_in_legend else ""))
    return QgsPalettedRasterRenderer(provider, band, flat)


def _profiles_from_array(array, mask, nodata, total_pixels: int) -> tuple[RasterValueProfile, ...]:
    if array is None:
        return ()
    try:
        import numpy as np
        values = np.asarray(array)
        valid = np.isfinite(values)
        if mask is not None:
            mask_valid = np.asarray(mask) != 0
            if nodata is not None and math.isfinite(float(nodata)):
                nodata_pixels = np.isclose(values.astype(float), float(nodata), rtol=0.0, atol=0.0)
                valid &= (mask_valid | nodata_pixels)
            else:
                valid &= mask_valid
        valid_values = values[valid]
        if valid_values.size == 0:
            return ()
        unique, counts = np.unique(valid_values, return_counts=True)
        if unique.size > 4096:
            unique = unique[:4096]
            counts = counts[:4096]
        border_mask = np.zeros(values.shape, dtype=bool)
        edge = max(1, min(values.shape[-2:]) // 20)
        border_mask[:edge, :] = True
        border_mask[-edge:, :] = True
        border_mask[:, :edge] = True
        border_mask[:, -edge:] = True
        border_valid = valid & border_mask
        center_valid = valid & ~border_mask
        border_total = int(border_valid.sum())
        center_total = int(center_valid.sum())
        sample_total = int(valid.sum())
        result = []
        for value, count in zip(unique.tolist(), counts.tolist()):
            value_f = float(value)
            border_count = int(((values == value) & border_valid).sum())
            center_count = int(((values == value) & center_valid).sum())
            result.append(
                RasterValueProfile(
                    value_f,
                    int(round(count / max(1, sample_total) * max(1, total_pixels))),
                    count / max(1, sample_total) * 100.0,
                    border_count / max(1, border_total),
                    center_count / max(1, center_total),
                    True,
                )
            )
        return tuple(result)
    except Exception:
        return ()


def _exact_counts_gdal(band, width: int, height: int, nodata: float | None) -> dict[float, int]:
    import numpy as np
    counts: dict[float, int] = {}
    block_y = max(256, min(2048, int(8_000_000 / max(1, width))))
    for yoff in range(0, height, block_y):
        rows = min(block_y, height - yoff)
        array = band.ReadAsArray(0, yoff, width, rows)
        if array is None:
            continue
        valid = np.isfinite(array)
        unique, value_counts = np.unique(array[valid], return_counts=True)
        for value, count in zip(unique.tolist(), value_counts.tolist()):
            value_f = float(value)
            counts[value_f] = counts.get(value_f, 0) + int(count)
    return counts


def _merge_exact_counts(profiles: tuple[RasterValueProfile, ...], exact: dict[float, int], total: int) -> tuple[RasterValueProfile, ...]:
    profile_map = {float(item.value): item for item in profiles}
    result = []
    for value, count in sorted(exact.items()):
        old = profile_map.get(value)
        result.append(
            RasterValueProfile(
                value,
                count,
                count / max(1, total) * 100.0,
                old.border_percentage if old else 0.0,
                old.center_percentage if old else 0.0,
                False,
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
                continue
    except Exception:
        pass
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
        pass
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


def _flatten_valid(array):
    if array is None:
        return ()
    try:
        return array.ravel()
    except Exception:
        return ()
