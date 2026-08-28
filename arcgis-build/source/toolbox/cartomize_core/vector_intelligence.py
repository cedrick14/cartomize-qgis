"""Façade ArcGIS du moteur vectoriel 10.5.1."""

from dataclasses import asdict, dataclass
from typing import Any

from .vector import analyze_vector


@dataclass(frozen=True)
class FieldProfile:
    name: str; type_name: str; count: int; null_count: int; null_percent: float
    unique_count: int; unique_ratio: float; minimum: float | None; maximum: float | None
    median: float | None; mean: float | None; skewness: float | None
    semantic_role: str; recommended_use: str; confidence: float
    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True)
class VectorLayerProfile:
    layer_id: str; name: str; source: str; geometry_type: str; crs: str
    feature_count: int; sampled_features: int; invalid_geometry_count: int
    empty_geometry_count: int; multipart_count: int; duplicate_geometry_count: int
    role: str; role_confidence: float; label_field: str; thematic_field: str
    fields: tuple[FieldProfile, ...]; warnings: tuple[str, ...]
    def to_dict(self) -> dict[str, Any]:
        result = asdict(self); result["fields"] = [item.to_dict() for item in self.fields]; return result


class VectorIntelligenceEngine:
    def __init__(self, arcpy_module=None, sample_limit: int = 1000):
        self.arcpy = arcpy_module or _import_arcpy(); self.sample_limit = sample_limit

    def analyze(self, layer) -> VectorLayerProfile:
        payload = analyze_vector(self.arcpy, layer, self.sample_limit)
        fields = tuple(FieldProfile(**{key: item.get(key) for key in FieldProfile.__dataclass_fields__}) for item in payload.get("fields", ()))
        return VectorLayerProfile(
            layer_id=str(payload.get("layer_id", "")), name=str(payload.get("name", "")), source=str(payload.get("source", "")),
            geometry_type=str(payload.get("geometry_type", "")), crs=str(payload.get("crs", "")), feature_count=int(payload.get("feature_count", 0)),
            sampled_features=int(payload.get("sampled_features", 0)), invalid_geometry_count=int(payload.get("invalid_geometry_count", 0)),
            empty_geometry_count=int(payload.get("empty_geometry_count", 0)), multipart_count=int(payload.get("multipart_count", 0)),
            duplicate_geometry_count=int(payload.get("duplicate_geometry_count", 0)), role=str(payload.get("role", "")),
            role_confidence=float(payload.get("role_confidence", 0)), label_field=str(payload.get("label_field", "")),
            thematic_field=str(payload.get("thematic_field", "")), fields=fields, warnings=tuple(payload.get("warnings", ())),
        )


def _import_arcpy():
    try:
        import arcpy; return arcpy
    except ImportError as exc:
        raise RuntimeError("ArcPy est requis pour analyser la couche vectorielle.") from exc


__all__ = ["FieldProfile", "VectorLayerProfile", "VectorIntelligenceEngine", "analyze_vector"]
