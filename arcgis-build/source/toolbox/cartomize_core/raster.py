"""Raster Engine Cartomize 10.5.1 adapté à ArcPy sans modifier la source."""

from __future__ import annotations

import math
import os
from pathlib import Path
import re
import unicodedata
from typing import Any
from uuid import uuid4

from .band_semantics import infer_band_semantics, propose_spectral_indices
from .raster_intelligence_core import (
    RasterEvidence,
    RasterInference,
    RasterValueProfile,
    infer_raster,
)
from .raster_sampling import RasterSampleSummary, profile_array
from .raster_themes import THEME_PROFILES, detect_raster_theme


# Compatibilité interne : la table est désormais construite depuis la
# bibliothèque QGIS complète (16 profils), copiée sans modification.
THEMES = {
    profile.key: (
        profile.label, profile.mode, profile.keywords,
        profile.preferred_class_count, "",
    )
    for profile in THEME_PROFILES
}

QUALITATIVE_COLORS = (
    "#2E7D32", "#F9A825", "#1565C0", "#C62828", "#6A1B9A", "#00838F",
    "#8D6E63", "#7CB342", "#EF6C00", "#3949AB", "#00897B", "#5D4037",
    "#D81B60", "#546E7A", "#43A047", "#FDD835", "#1E88E5", "#E53935",
)

PIXEL_TYPES = {
    "U1": "UInt1", "U2": "UInt2", "U4": "UInt4", "U8": "UInt8",
    "S8": "Int8", "U16": "UInt16", "S16": "Int16",
    "U32": "UInt32", "S32": "Int32", "F32": "Float32", "F64": "Float64",
}


def resolve_raster_source(arcpy: Any, source: Any, source_text: str | None = None) -> str:
    """Retourne le nom ou chemin ArcPy attendu par ``arcpy.Raster``."""

    text = str(source_text or "").strip()
    if text:
        return text
    if isinstance(source, (str, os.PathLike)):
        text = str(source).strip()
        if text:
            return text
    try:
        supports = getattr(source, "supports", None)
        if callable(supports) and supports("DATASOURCE"):
            text = str(getattr(source, "dataSource", "") or "").strip()
            if text:
                return text
    except Exception:
        pass
    text = str(getattr(source, "dataSource", "") or "").strip()
    if text:
        return text
    try:
        desc = arcpy.Describe(source)
        for item in (desc, getattr(desc, "dataElement", None)):
            text = str(getattr(item, "catalogPath", "") or "").strip()
            if text:
                return text
    except Exception:
        pass
    raise ValueError("Sélectionnez une couche raster valide.")


def analyze_raster(
    arcpy: Any,
    source: Any,
    source_text: str | None = None,
) -> dict[str, Any]:
    """Analyse un raster avec le noyau déterministe de Cartomize QGIS 10.5.1."""

    raster_source = resolve_raster_source(arcpy, source, source_text)
    desc = arcpy.Describe(raster_source)
    data_desc = getattr(desc, "dataElement", None) or desc
    raster = arcpy.Raster(raster_source)
    band_count = max(1, int(getattr(raster, "bandCount", getattr(data_desc, "bandCount", 1)) or 1))
    width = max(0, int(getattr(raster, "width", getattr(data_desc, "width", 0)) or 0))
    height = max(0, int(getattr(raster, "height", getattr(data_desc, "height", 0)) or 0))
    total_pixels = width * height
    source_path = _catalog_path(raster, data_desc, raster_source)
    layer_name = str(
        getattr(source, "name", "")
        or getattr(desc, "nameString", "")
        or getattr(desc, "name", "")
        or Path(source_path).name
    )
    pixel_type_code = str(
        getattr(raster, "pixelType", getattr(data_desc, "pixelType", "Unknown"))
        or "Unknown"
    )
    pixel_type = PIXEL_TYPES.get(pixel_type_code.upper(), pixel_type_code)
    integer_type = _is_integer_type(pixel_type)
    nodata_values = _nodata_values(
        getattr(raster, "noDataValues", None)
        or getattr(raster, "noDataValue", None),
        band_count,
    )
    statistics = _band_statistics(arcpy, raster, raster_source, band_count)
    minimum = statistics[0]["minimum"] if statistics else None
    maximum = statistics[0]["maximum"] if statistics else None
    mean = statistics[0]["mean"] if statistics else None
    stddev = statistics[0]["stddev"] if statistics else None
    band_names = _band_names(raster, band_count)
    band_metadata = _band_metadata(raster, band_names)
    color_interpretations = _color_interpretations(band_names, band_metadata)
    band_metadata = tuple({
        **item,
        "description": item.get("description") or name,
        "color_interpretation": item.get("color_interpretation") or color,
    } for name, color, item in zip(band_names, color_interpretations, band_metadata))
    has_rat = bool(getattr(raster, "hasRAT", getattr(data_desc, "hasRAT", False)))
    rat_labels, rat_counts = _read_rat(arcpy, raster, raster_source, has_rat)
    color_table = _read_colormap(raster)
    has_color_table = bool(color_table)
    sample, warnings = _sample_raster(
        arcpy, raster_source, raster, width, height,
        nodata_values[0] if nodata_values else None,
        integer_type=integer_type,
    )
    profiles = _merge_rat_counts(sample.profiles, rat_counts)
    observed_unique_count = max(sample.observed_unique_count, len(rat_counts))
    valid_pixels = (
        sum(rat_counts.values())
        if rat_counts
        else int(round(sample.valid_pixels / max(1, sample.sampled_pixels) * total_pixels))
    )
    nodata_pixels = max(0, total_pixels - valid_pixels)
    spatial_reference = getattr(data_desc, "spatialReference", None)
    crs = str(
        getattr(spatial_reference, "factoryCode", "")
        or getattr(spatial_reference, "name", "")
        or "Unknown"
    )
    extent = getattr(raster, "extent", getattr(data_desc, "extent", None))
    extent_values = _extent_tuple(extent, width, height)
    resolution_x = _finite_or_none(getattr(raster, "meanCellWidth", None))
    resolution_y = _finite_or_none(getattr(raster, "meanCellHeight", None))
    storage_type = str(getattr(raster, "format", getattr(data_desc, "format", "")) or "")
    metadata = {
        "layer_name": layer_name,
        "source": source_path,
        "provider": "arcpy",
        "format": storage_type,
        "pixel_type": pixel_type,
    }
    evidence = RasterEvidence(
        band_count=band_count,
        data_type=pixel_type,
        total_pixels=total_pixels,
        valid_pixels=valid_pixels,
        unique_count=observed_unique_count,
        values=profiles,
        minimum=minimum,
        maximum=maximum,
        source_nodata=nodata_values[0] if nodata_values else None,
        has_mask=any(value is not None for value in nodata_values),
        has_alpha=any(value.casefold() == "alpha" for value in color_interpretations),
        has_color_table=has_color_table,
        has_rat=has_rat,
        rat_labels=tuple(sorted(rat_labels.items())),
        color_labels=(),
        band_color_interpretations=color_interpretations,
        metadata_text=" ".join(f"{key} {value}" for key, value in metadata.items()),
        sample_fraction=min(1.0, sample.sampled_pixels / max(1, total_pixels)),
    )
    inference = infer_raster(evidence)
    classes = _build_classes(
        profiles, inference, nodata_values, rat_labels,
        color_table,
    )
    semantics = infer_band_semantics(band_names, color_interpretations, band_metadata)
    spectral_indices = propose_spectral_indices(semantics)
    theme, theme_confidence, theme_reasons = detect_theme(
        f"{layer_name} {source_path}", inference.raster_type, minimum, maximum
    )
    inspection = {
        "layer_id": str(getattr(source, "URI", "") or ""),
        "layer_name": layer_name,
        "source": source_path,
        "provider": "arcpy",
        "storage_type": storage_type,
        "width": width,
        "height": height,
        "total_pixels": total_pixels,
        "crs": crs,
        "extent": list(extent_values),
        "resolution_x": resolution_x,
        "resolution_y": resolution_y,
        "band_count": band_count,
        "data_types": [pixel_type] * band_count,
        "band_names": list(band_names),
        "band_color_interpretations": list(color_interpretations),
        "statistics": list(statistics),
        "source_nodata": list(nodata_values),
        "has_mask": evidence.has_mask,
        "has_alpha": evidence.has_alpha,
        "has_color_table": has_color_table,
        "has_rat": has_rat,
        "metadata": metadata,
        "color_table_labels": [],
        "rat_labels": [[value, label] for value, label in sorted(rat_labels.items())],
        "value_profiles": [item.to_dict() for item in profiles],
        "exact_counts": bool(rat_counts),
        "sample_fraction": evidence.sample_fraction,
        "warnings": list(warnings),
        "valid_pixels": valid_pixels,
        "nodata_pixels": nodata_pixels,
        "observed_unique_count": observed_unique_count,
        "profile_limited": sample.profile_limited,
        "analyzed_band": 1,
        "band_metadata": list(band_metadata),
        "sample_quantiles": [list(item) for item in sample.quantiles],
    }
    recommended_colorizer = _recommended_colorizer(inference.raster_type)
    return {
        "inspection": inspection,
        "inference": inference.to_dict(),
        "classes": classes,
        "recommended_nodata": [item.to_dict() for item in inference.nodata_candidates],
        "anomalies": [item.to_dict() for item in inference.anomalous_values],
        "legend": [[item["label"], item["color"]] for item in classes if item["visible"] and item["show_in_legend"]],
        "band_semantics": [item.to_dict() for item in semantics],
        "spectral_indices": [item.to_dict() for item in spectral_indices],
        "name": layer_name,
        "source": source_path,
        "spatial_reference": crs,
        "width": width,
        "height": height,
        "band_count": band_count,
        "pixel_type": pixel_type,
        "minimum": minimum,
        "maximum": maximum,
        "mean": mean,
        "standard_deviation": stddev,
        "unique_count": observed_unique_count,
        "source_nodata": nodata_values[0] if nodata_values else None,
        "raster_type": inference.raster_type,
        "confidence": inference.confidence,
        "recommended_colorizer": recommended_colorizer,
        "theme": theme,
        "theme_confidence": theme_confidence,
        "rationale": list(inference.rationale) + theme_reasons,
        "non_destructive": True,
    }


def raster_type_label(code: str) -> str:
    return {
        "binary": "Raster binaire",
        "categorized": "Raster catégoriel / classifié",
        "continuous": "Raster continu",
        "rgb": "Image RGB",
        "multiband": "Raster multibande",
    }.get(code, code)


def detect_theme(
    text: str,
    raster_type: str,
    minimum: float | None,
    maximum: float | None,
) -> tuple[str, float, list[str]]:
    match = detect_raster_theme(
        text=text,
        raster_type=raster_type,
        minimum=minimum,
        maximum=maximum,
    )
    return match.key, match.confidence, list(match.reasons)


def _sample_raster(
    arcpy: Any,
    source: str,
    raster: Any,
    width: int,
    height: int,
    nodata: float | None,
    *,
    integer_type: bool,
) -> tuple[RasterSampleSummary, tuple[str, ...]]:
    warnings: list[str] = []
    temporary = ""
    sample_source = source
    try:
        if width > 512 or height > 512:
            temporary = _temporary_raster_path(arcpy)
            cell_width = abs(float(getattr(raster, "meanCellWidth", 1.0) or 1.0))
            cell_height = abs(float(getattr(raster, "meanCellHeight", 1.0) or 1.0))
            target_cell = max(
                cell_width * max(1.0, width / 512.0),
                cell_height * max(1.0, height / 512.0),
            )
            method = "NEAREST" if integer_type else "BILINEAR"
            arcpy.management.Resample(source, temporary, target_cell, method)
            sample_source = temporary
        array = arcpy.RasterToNumPyArray(sample_source)
        if int(getattr(array, "ndim", 0) or 0) >= 3:
            array = array[0]
        first = profile_array(array, nodata=nodata, max_profiles=4096)
        population = int(round(first.valid_pixels / max(1, first.sampled_pixels) * width * height))
        sampled = profile_array(
            array,
            nodata=nodata,
            total_pixels=population,
            max_profiles=4096,
        )
        return sampled, tuple(warnings)
    except Exception as exc:
        warnings.append(f"Échantillonnage ArcPy indisponible : {exc}")
        return RasterSampleSummary((), 0, 0, 0, 0, False), tuple(warnings)
    finally:
        if temporary:
            try:
                if arcpy.Exists(temporary):
                    arcpy.management.Delete(temporary)
            except Exception:
                pass


def _temporary_raster_path(arcpy: Any) -> str:
    name = f"cartomize_raster_sample_{uuid4().hex[:12]}"
    scratch_gdb = str(getattr(getattr(arcpy, "env", None), "scratchGDB", "") or "").strip()
    if scratch_gdb:
        return os.path.join(scratch_gdb, name)
    scratch_folder = str(getattr(getattr(arcpy, "env", None), "scratchFolder", "") or "").strip()
    if not scratch_folder:
        scratch_folder = os.getcwd()
    return os.path.join(scratch_folder, name + ".tif")


def _build_classes(
    profiles: tuple[RasterValueProfile, ...],
    inference: RasterInference,
    source_nodata: tuple[float | None, ...],
    labels: dict[float, str],
    colors: dict[float, str],
) -> list[dict[str, Any]]:
    profile_map = {float(item.value): item for item in profiles}
    explicit_nodata = {
        float(value) for value in source_nodata
        if value is not None and math.isfinite(float(value))
    }
    automatic_nodata = {float(value) for value in inference.automatic_nodata_values}
    anomaly_confidence = {
        float(item.value): item.confidence for item in inference.anomalous_values
    }
    values = sorted({
        *(float(value) for value in inference.class_values),
        *automatic_nodata,
    })
    result: list[dict[str, Any]] = []
    visible_index = 0
    for value in values:
        profile = profile_map.get(value, RasterValueProfile(value, 0, 0.0))
        automatic = value in automatic_nodata
        label = (
            f"Fond / NoData détecté ({_pretty_number(value)})"
            if automatic
            else labels.get(value) or f"Classe {_pretty_number(value)}"
        )
        hidden = automatic or value in explicit_nodata
        color = colors.get(value) or QUALITATIVE_COLORS[visible_index % len(QUALITATIVE_COLORS)]
        if not hidden:
            visible_index += 1
        result.append({
            "values": [value],
            "label": label,
            "color": color,
            "pixel_count": profile.pixel_count,
            "percentage": profile.percentage,
            "border_percentage": profile.border_percentage,
            "status": (
                "NoData visuel automatique"
                if automatic
                else "Valeur atypique" if value in anomaly_confidence else "Classe"
            ),
            "confidence": anomaly_confidence.get(value, inference.confidence),
            "visible": not hidden,
            "show_in_legend": not hidden,
            "source": (
                "source_nodata" if value in explicit_nodata
                else "automatic_nodata" if automatic
                else "metadata" if value in labels or value in colors
                else "detected"
            ),
            "opacity": 1.0,
        })
    return result


def _read_rat(
    arcpy: Any,
    raster: Any,
    source: str,
    has_rat: bool,
) -> tuple[dict[float, str], dict[float, int]]:
    if not has_rat:
        return {}, {}
    try:
        table = getattr(raster, "RAT", None)
        if isinstance(table, dict):
            by_name = {str(name).casefold(): values for name, values in table.items()}
            values = by_name.get("value") or ()
            counts = by_name.get("count") or ()
            labels = next((
                by_name[name]
                for name in (
                    "classname", "class_name", "class", "label", "name", "description"
                )
                if name in by_name
            ), ())
            label_result: dict[float, str] = {}
            count_result: dict[float, int] = {}
            for index, raw_value in enumerate(values):
                value = float(raw_value)
                if index < len(counts):
                    count_result[value] = max(0, int(counts[index] or 0))
                if index < len(labels):
                    label = str(labels[index] or "").strip()
                    if label:
                        label_result[value] = label
                if len(count_result) > 4096:
                    return label_result, {}
            if values:
                return label_result, count_result
    except Exception:
        pass
    try:
        fields = list(arcpy.ListFields(source))
        by_name = {str(field.name).casefold(): str(field.name) for field in fields}
        value_field = by_name.get("value")
        count_field = by_name.get("count")
        label_field = next(
            (
                by_name[name]
                for name in (
                    "classname", "class_name", "class", "label", "name", "description"
                )
                if name in by_name
            ),
            None,
        )
        if not value_field:
            return {}, {}
        cursor_fields = [value_field]
        if count_field:
            cursor_fields.append(count_field)
        if label_field:
            cursor_fields.append(label_field)
        labels: dict[float, str] = {}
        counts: dict[float, int] = {}
        with arcpy.da.SearchCursor(source, cursor_fields) as rows:
            for row in rows:
                value = float(row[0])
                index = 1
                if count_field:
                    counts[value] = max(0, int(row[index] or 0))
                    index += 1
                if label_field:
                    label = str(row[index] or "").strip()
                    if label:
                        labels[value] = label
                if len(counts) > 4096:
                    return labels, {}
        return labels, counts
    except Exception:
        return {}, {}


def _merge_rat_counts(
    profiles: tuple[RasterValueProfile, ...],
    counts: dict[float, int],
) -> tuple[RasterValueProfile, ...]:
    if not counts:
        return profiles
    total = sum(counts.values())
    profile_map = {float(item.value): item for item in profiles}
    result = []
    for value, count in sorted(counts.items()):
        old = profile_map.get(value)
        result.append(RasterValueProfile(
            value=value,
            pixel_count=count,
            percentage=count / max(1, total) * 100.0,
            border_percentage=old.border_percentage if old else 0.0,
            center_percentage=old.center_percentage if old else 0.0,
            estimated=False,
            corner_percentage=old.corner_percentage if old else 0.0,
        ))
    return tuple(result)


def _catalog_path(raster: Any, desc: Any, fallback: str) -> str:
    return str(
        getattr(raster, "catalogPath", "")
        or getattr(desc, "catalogPath", "")
        or fallback
    )


def _band_names(raster: Any, count: int) -> tuple[str, ...]:
    names = getattr(raster, "bandNames", None)
    if isinstance(names, (list, tuple)) and names:
        result = [str(item or f"Bande {index}") for index, item in enumerate(names, 1)]
    else:
        result = [f"Bande {index}" for index in range(1, count + 1)]
    while len(result) < count:
        result.append(f"Bande {len(result) + 1}")
    return tuple(result[:count])


def _color_interpretations(
    names: tuple[str, ...],
    metadata: tuple[dict[str, Any], ...],
) -> tuple[str, ...]:
    result = []
    for index, name in enumerate(names):
        details = metadata[index] if index < len(metadata) else {}
        text = _normalise(" ".join(
            [name, *(f"{key} {value}" for key, value in details.items())]
        ))
        if re.search(r"(?:^| )red(?: |$)|(?:^| )rouge(?: |$)", text):
            result.append("Red")
        elif re.search(r"(?:^| )green(?: |$)|(?:^| )vert(?: |$)", text):
            result.append("Green")
        elif re.search(r"(?:^| )blue(?: |$)|(?:^| )bleu(?: |$)", text):
            result.append("Blue")
        elif re.search(r"(?:^| )alpha(?: |$)", text):
            result.append("Alpha")
        else:
            result.append("")
    return tuple(result)


def _band_metadata(
    raster: Any,
    names: tuple[str, ...],
) -> tuple[dict[str, Any], ...]:
    result: list[dict[str, Any]] = []
    getter = getattr(raster, "getAllBandProperties", None)
    for index, name in enumerate(names, 1):
        item: dict[str, Any] = {"description": name}
        if callable(getter):
            try:
                properties = getter(index)
                if isinstance(properties, dict):
                    item.update({str(key): value for key, value in properties.items()})
            except Exception:
                pass
        result.append(item)
    return tuple(result)


def _band_statistics(
    arcpy: Any,
    raster: Any,
    source: str,
    count: int,
) -> tuple[dict[str, Any], ...]:
    bands: list[Any] = []
    getter = getattr(raster, "getRasterBands", None)
    if callable(getter):
        try:
            raw_bands = getter()
            bands = list(raw_bands) if isinstance(raw_bands, (list, tuple)) else [raw_bands]
        except Exception:
            bands = []
    result = []
    for index in range(count):
        band = bands[index] if index < len(bands) else None
        if band is not None:
            minimum = _finite_or_none(getattr(band, "minimum", None))
            maximum = _finite_or_none(getattr(band, "maximum", None))
            mean = _finite_or_none(getattr(band, "mean", None))
            stddev = _finite_or_none(getattr(band, "standardDeviation", None))
        elif index == 0:
            minimum = _finite_or_none(getattr(raster, "minimum", None))
            maximum = _finite_or_none(getattr(raster, "maximum", None))
            mean = _finite_or_none(getattr(raster, "mean", None))
            stddev = _finite_or_none(getattr(raster, "standardDeviation", None))
            minimum = minimum if minimum is not None else _property(arcpy, source, "MINIMUM")
            maximum = maximum if maximum is not None else _property(arcpy, source, "MAXIMUM")
            mean = mean if mean is not None else _property(arcpy, source, "MEAN")
            stddev = stddev if stddev is not None else _property(arcpy, source, "STD")
        else:
            minimum = maximum = mean = stddev = None
        result.append({
            "band": index + 1,
            "minimum": minimum,
            "maximum": maximum,
            "mean": mean,
            "stddev": stddev,
        })
    return tuple(result)


def _read_colormap(raster: Any) -> dict[float, str]:
    getter = getattr(raster, "getColormap", None)
    if not callable(getter):
        return {}
    try:
        payload = getter()
        if not isinstance(payload, dict):
            return {}
        values = payload.get("values") or ()
        colors = payload.get("colors") or ()
        return {
            float(value): str(colors[index])
            for index, value in enumerate(values)
            if index < len(colors) and str(colors[index]).strip()
        }
    except Exception:
        return {}


def _nodata_values(value: Any, count: int) -> tuple[float | None, ...]:
    if isinstance(value, (list, tuple)):
        raw_values = list(value)
    elif isinstance(value, str) and len(value.split()) > 1:
        raw_values = value.replace(",", " ").split()
    else:
        raw_values = [value]
    result = [_finite_or_none(item) for item in raw_values]
    if not result:
        result = [None]
    while len(result) < count:
        result.append(result[-1])
    return tuple(result[:count])


def _extent_tuple(extent: Any, width: int, height: int) -> tuple[float, float, float, float]:
    try:
        return (
            float(extent.XMin), float(extent.YMin),
            float(extent.XMax), float(extent.YMax),
        )
    except Exception:
        return (0.0, 0.0, float(width), float(height))


def _finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _is_integer_type(value: str) -> bool:
    text = str(value).casefold()
    return any(token in text for token in ("uint", "int", "byte")) and not any(
        token in text for token in ("float", "double")
    )


def _recommended_colorizer(raster_type: str) -> str:
    if raster_type in {"binary", "categorized"}:
        return "RasterUniqueValueColorizer"
    if raster_type in {"rgb", "multiband"}:
        return "RasterStretchColorizer"
    return "RasterClassifyColorizer"


def _property(arcpy: Any, source: Any, name: str) -> float | None:
    try:
        value = arcpy.management.GetRasterProperties(source, name).getOutput(0)
        number = float(value)
        return number if math.isfinite(number) else None
    except Exception:
        return None


def _pretty_number(value: float) -> str:
    number = float(value)
    return str(int(round(number))) if abs(number - round(number)) < 1e-9 else f"{number:.6g}"


def _normalise(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value))
    return " ".join(
        "".join(char for char in decomposed if not unicodedata.combining(char))
        .casefold()
        .replace("_", " ")
        .replace("-", " ")
        .split()
    )
