"""Graphe des relations spatiales, fidèle au moteur QGIS 10.5.1.

Les règles, priorités et libellés sont conservés. ArcPy remplace uniquement
les appels QgsCoordinateTransform et les accesseurs de couches QGIS.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class LayerNode:
    layer_id: str
    name: str
    layer_type: str
    role: str
    crs: str
    extent: tuple[float, float, float, float]
    priority: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LayerRelation:
    source_id: str
    target_id: str
    relation: str
    overlap_ratio: float
    confidence: float
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProjectRelationshipGraph:
    nodes: tuple[LayerNode, ...]
    relations: tuple[LayerRelation, ...]
    recommended_order: tuple[str, ...]
    context_layer_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "relations": [relation.to_dict() for relation in self.relations],
            "recommended_order": list(self.recommended_order),
            "context_layer_ids": list(self.context_layer_ids),
        }


_ROLE_PRIORITY = {
    "principal": 100,
    "risques": 96,
    "occupation_sol": 94,
    "zones_thématiques": 90,
    "points_thématiques": 88,
    "localités": 78,
    "transport": 68,
    "réseau": 65,
    "hydrographie": 62,
    "limites": 55,
    "bâtiments": 52,
    "parcelles": 50,
    "contexte": 25,
}


class ProjectRelationshipEngine:
    """Construit le même graphe léger que Cartomize QGIS."""

    def __init__(self, arcpy: Any):
        self.arcpy = arcpy

    def analyze(
        self,
        layers: Iterable[Any],
        *,
        roles: dict[str, str] | None = None,
        main_layer_id: str = "",
    ) -> ProjectRelationshipGraph:
        roles = roles or {}
        nodes: list[LayerNode] = []
        for layer in layers:
            if layer is None or bool(getattr(layer, "isBroken", False)):
                continue
            layer_id = _layer_id(layer)
            role = "principal" if layer_id == main_layer_id else roles.get(layer_id, "contexte")
            description = self.arcpy.Describe(layer)
            nodes.append(LayerNode(
                layer_id=layer_id,
                name=str(getattr(layer, "name", getattr(description, "name", "Couche"))),
                layer_type=(
                    "vector" if bool(getattr(layer, "isFeatureLayer", False))
                    else "raster" if bool(getattr(layer, "isRasterLayer", False))
                    else "other"
                ),
                role=role,
                crs=str(getattr(getattr(description, "spatialReference", None), "name", "") or ""),
                extent=_extent_tuple(getattr(description, "extent", None)),
                priority=_ROLE_PRIORITY.get(role, 40),
            ))

        relations: list[LayerRelation] = []
        for index, source in enumerate(nodes):
            for target in nodes[index + 1:]:
                relation = _classify_extent_relation(source, target)
                if relation is not None:
                    relations.append(relation)

        ordered = tuple(
            node.layer_id for node in sorted(
                nodes,
                key=lambda node: (node.priority, 1 if node.layer_id == main_layer_id else 0),
                reverse=True,
            )
        )
        context = tuple(
            node.layer_id for node in nodes
            if node.layer_id != main_layer_id
            and node.role in {"limites", "transport", "hydrographie", "localités", "contexte"}
        )
        return ProjectRelationshipGraph(tuple(nodes), tuple(relations), ordered, context)


def _layer_id(layer: Any) -> str:
    return str(
        getattr(layer, "URI", "")
        or getattr(layer, "longName", "")
        or getattr(layer, "name", "")
    )


def _extent_tuple(extent: Any) -> tuple[float, float, float, float]:
    if extent is None:
        return (0.0, 0.0, 0.0, 0.0)
    try:
        return (
            float(extent.XMin), float(extent.YMin),
            float(extent.XMax), float(extent.YMax),
        )
    except Exception:
        return (0.0, 0.0, 0.0, 0.0)


def _classify_extent_relation(source: LayerNode, target: LayerNode) -> LayerRelation | None:
    a = source.extent
    b = target.extent
    if _invalid_extent(a) or _invalid_extent(b):
        return None
    intersection = _intersection_area(a, b)
    if intersection <= 0:
        return None
    area_a = _area(a)
    area_b = _area(b)
    ratio_a = intersection / max(area_a, 1e-12)
    ratio_b = intersection / max(area_b, 1e-12)
    smaller_covered = max(ratio_a, ratio_b)
    if ratio_b >= 0.96 and area_a >= area_b:
        relation = "contains"
        explanation = f"L’emprise de {source.name} contient presque entièrement {target.name}."
    elif ratio_a >= 0.96 and area_b >= area_a:
        relation = "within"
        explanation = f"L’emprise de {source.name} est presque entièrement incluse dans {target.name}."
    else:
        relation = "overlaps"
        explanation = f"Les emprises de {source.name} et {target.name} se recouvrent."
    confidence = min(0.98, 0.55 + 0.43 * smaller_covered)
    if source.layer_type != target.layer_type:
        confidence = min(0.99, confidence + 0.03)
    return LayerRelation(
        source.layer_id, target.layer_id, relation,
        round(min(ratio_a, ratio_b), 4), round(confidence, 3), explanation,
    )


def _invalid_extent(extent: tuple[float, float, float, float]) -> bool:
    return extent[2] <= extent[0] or extent[3] <= extent[1]


def _area(extent: tuple[float, float, float, float]) -> float:
    return max(0.0, extent[2] - extent[0]) * max(0.0, extent[3] - extent[1])


def _intersection_area(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, width) * max(0.0, height)
