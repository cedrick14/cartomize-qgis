"""Façade ArcGIS du Raster Engine 10.5.1."""

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .raster import analyze_raster, raster_type_label as _raster_type_label, resolve_raster_source
from .raster_intelligence_core import RasterEvidence, RasterInference, RasterValueProfile, infer_raster


@dataclass(frozen=True)
class RasterClassDefinition:
    values: tuple[float, ...]; label: str; color: str; pixel_count: int; percentage: float; border_percentage: float
    status: str = "Classe"; confidence: float = 1.0; visible: bool = True; show_in_legend: bool = True; source: str = "detected"; opacity: float = 1.0
    @property
    def code_label(self) -> str: return ", ".join(f"{value:g}" for value in self.values)
    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self); payload["values"] = list(self.values); return payload
    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RasterClassDefinition":
        return cls(tuple(float(v) for v in payload.get("values", ())), str(payload.get("label") or "Classe"), str(payload.get("color") or "#808080"), max(0, int(payload.get("pixel_count", 0))), float(payload.get("percentage", 0)), float(payload.get("border_percentage", 0)), str(payload.get("status") or "Classe"), float(payload.get("confidence", 1)), bool(payload.get("visible", True)), bool(payload.get("show_in_legend", True)), str(payload.get("source") or "manual"), max(0, min(1, float(payload.get("opacity", 1)))))


@dataclass(frozen=True)
class RasterInspection:
    layer_id: str; layer_name: str; source: str; provider: str; storage_type: str; width: int; height: int; total_pixels: int; crs: str
    extent: tuple[float, float, float, float]; resolution_x: float | None; resolution_y: float | None; band_count: int
    data_types: tuple[str, ...]; band_names: tuple[str, ...]; band_color_interpretations: tuple[str, ...]; statistics: tuple[dict[str, Any], ...]
    source_nodata: tuple[float | None, ...]; has_mask: bool; has_alpha: bool; has_color_table: bool; has_rat: bool; metadata: dict[str, str]
    color_table_labels: tuple[tuple[float, str], ...]; rat_labels: tuple[tuple[float, str], ...]; value_profiles: tuple[RasterValueProfile, ...]
    exact_counts: bool; sample_fraction: float; warnings: tuple[str, ...] = (); valid_pixels: int = 0; nodata_pixels: int = 0
    observed_unique_count: int = 0; profile_limited: bool = False; analyzed_band: int = 1; band_metadata: tuple[dict[str, Any], ...] = (); sample_quantiles: tuple[tuple[float, float], ...] = ()
    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self); payload["value_profiles"] = [item.to_dict() for item in self.value_profiles]; return payload


@dataclass(frozen=True)
class RasterDiagnosis:
    inspection: RasterInspection; inference: RasterInference; classes: tuple[RasterClassDefinition, ...]
    recommended_nodata: tuple[dict[str, Any], ...]; anomalies: tuple[dict[str, Any], ...]; legend: tuple[tuple[str, str], ...]
    band_semantics: tuple[dict[str, Any], ...] = (); spectral_indices: tuple[dict[str, Any], ...] = ()
    def to_dict(self) -> dict[str, Any]:
        return {"inspection": self.inspection.to_dict(), "inference": self.inference.to_dict(), "classes": [item.to_dict() for item in self.classes], "recommended_nodata": list(self.recommended_nodata), "anomalies": list(self.anomalies), "legend": [list(item) for item in self.legend], "band_semantics": list(self.band_semantics), "spectral_indices": list(self.spectral_indices)}
    def summary_lines(self) -> tuple[str, ...]:
        return (f"Type détecté : {raster_type_label(self.inference.raster_type)}", f"Confiance : {self.inference.confidence:.0%}", f"Bandes : {self.inspection.band_count}", f"Classes détectées : {len(self.classes)}", f"Valeurs atypiques : {len(self.anomalies)}")


class RasterInspector:
    def __init__(self, arcpy_module=None): self.arcpy = arcpy_module or _import_arcpy()
    def inspect(self, layer, *, deep: bool = False, feedback=None) -> RasterInspection: return _diagnosis_from_payload(analyze_raster(self.arcpy, layer)).inspection
    def inspect_source(self, source: str, *, deep: bool = True, feedback=None) -> RasterInspection: return _diagnosis_from_payload(analyze_raster(self.arcpy, source, source)).inspection


class RasterIntelligenceEngine:
    def __init__(self, project=None, *, arcpy_module=None):
        self.arcpy = arcpy_module or _import_arcpy(); self.project = project; self._saved: dict[str, tuple[RasterClassDefinition, ...]] = {}
    def analyze(self, layer, *, deep: bool = False, feedback=None) -> RasterDiagnosis:
        diagnosis = _diagnosis_from_payload(analyze_raster(self.arcpy, layer)); self._saved[_layer_key(layer)] = diagnosis.classes; return diagnosis
    def diagnose_inspection(self, layer, inspection: RasterInspection) -> RasterDiagnosis: return self.analyze(layer)
    def apply_classes(self, layer, classes: Iterable[RasterClassDefinition], *, band: int = 1):
        values = tuple(classes); self._saved[_layer_key(layer)] = values
        try:
            from .symbology import apply_raster_symbology
            aprx = self.project or self.arcpy.mp.ArcGISProject("CURRENT")
            return apply_raster_symbology(aprx, layer, {"raster_type": "categorized", "theme": "land_cover", "classes": [item.to_dict() for item in values]}, class_count=len(values))
        except Exception as exc:
            return {"applied": False, "reason": str(exc)}
    def saved_classes(self, layer) -> tuple[RasterClassDefinition, ...]: return self._saved.get(_layer_key(layer), ())
    def undo_last(self, layer) -> bool: return self._saved.pop(_layer_key(layer), None) is not None


def apply_visual_nodata_transparency(renderer, values: Iterable[float]):
    values = tuple(float(value) for value in values)
    setter = getattr(renderer, "setNoDataValue", None)
    if callable(setter):
        for value in values: setter(value)
    return values


def raster_type_label(code: str) -> str:
    return _raster_type_label(code)


def _diagnosis_from_payload(payload: dict[str, Any]) -> RasterDiagnosis:
    raw = payload.get("inspection", {})
    profiles = tuple(RasterValueProfile(**item) for item in raw.get("value_profiles", ()))
    inspection = RasterInspection(
        layer_id=str(raw.get("layer_id", "")), layer_name=str(raw.get("layer_name", payload.get("name", ""))), source=str(raw.get("source", payload.get("source", ""))),
        provider=str(raw.get("provider", "ArcPy")), storage_type=str(raw.get("storage_type", payload.get("pixel_type", ""))), width=int(raw.get("width", payload.get("width", 0))),
        height=int(raw.get("height", payload.get("height", 0))), total_pixels=int(raw.get("total_pixels", 0)), crs=str(raw.get("crs", payload.get("spatial_reference", ""))),
        extent=tuple(raw.get("extent", (0, 0, 0, 0))), resolution_x=raw.get("resolution_x"), resolution_y=raw.get("resolution_y"), band_count=int(raw.get("band_count", payload.get("band_count", 1))),
        data_types=tuple(raw.get("data_types", (payload.get("pixel_type", ""),))), band_names=tuple(raw.get("band_names", ())), band_color_interpretations=tuple(raw.get("band_color_interpretations", ())),
        statistics=tuple(raw.get("statistics", ())), source_nodata=tuple(raw.get("source_nodata", (payload.get("source_nodata"),))), has_mask=bool(raw.get("has_mask", False)),
        has_alpha=bool(raw.get("has_alpha", False)), has_color_table=bool(raw.get("has_color_table", False)), has_rat=bool(raw.get("has_rat", False)), metadata=dict(raw.get("metadata", {})),
        color_table_labels=tuple(tuple(item) for item in raw.get("color_table_labels", ())), rat_labels=tuple(tuple(item) for item in raw.get("rat_labels", ())), value_profiles=profiles,
        exact_counts=bool(raw.get("exact_counts", False)), sample_fraction=float(raw.get("sample_fraction", 0)), warnings=tuple(raw.get("warnings", ())), valid_pixels=int(raw.get("valid_pixels", 0)),
        nodata_pixels=int(raw.get("nodata_pixels", 0)), observed_unique_count=int(raw.get("observed_unique_count", payload.get("unique_count", 0))), profile_limited=bool(raw.get("profile_limited", False)),
        analyzed_band=int(raw.get("analyzed_band", 1)), band_metadata=tuple(raw.get("band_metadata", ())), sample_quantiles=tuple(tuple(item) for item in raw.get("sample_quantiles", ())),
    )
    inference = RasterInference(**payload.get("inference", {})) if isinstance(payload.get("inference"), RasterInference) else _inference_from_dict(payload.get("inference", {}))
    classes = tuple(RasterClassDefinition.from_dict(item) for item in payload.get("classes", ()))
    return RasterDiagnosis(inspection, inference, classes, tuple(payload.get("recommended_nodata", ())), tuple(payload.get("anomalies", ())), tuple(tuple(item) for item in payload.get("legend", ())), tuple(payload.get("band_semantics", ())), tuple(payload.get("spectral_indices", ())))


def _inference_from_dict(value: dict[str, Any]) -> RasterInference:
    from .raster_intelligence_core import RasterCandidate
    return RasterInference(str(value.get("raster_type", "continuous")), float(value.get("confidence", 0)), tuple(value.get("rationale", ())), tuple(RasterCandidate(**item) for item in value.get("nodata_candidates", ())), tuple(float(v) for v in value.get("automatic_nodata_values", ())), tuple(RasterCandidate(**item) for item in value.get("anomalous_values", ())), tuple(float(v) for v in value.get("class_values", ())), tuple(int(v) for v in value.get("possible_missing_codes", ())), str(value.get("recommended_renderer", "singleband_pseudocolor")), str(value.get("recommended_palette", "sequential")))


def _layer_key(layer) -> str: return str(getattr(layer, "URI", "") or getattr(layer, "name", "") or layer)
def _import_arcpy():
    try:
        import arcpy; return arcpy
    except ImportError as exc: raise RuntimeError("ArcPy est requis pour analyser le raster.") from exc

__all__ = ["RasterClassDefinition", "RasterInspection", "RasterDiagnosis", "RasterIntelligenceEngine", "RasterInspector", "raster_type_label", "apply_visual_nodata_transparency", "analyze_raster", "resolve_raster_source", "RasterEvidence", "RasterInference", "infer_raster"]
