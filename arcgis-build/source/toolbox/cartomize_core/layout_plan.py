"""Plan déterministe d’une maquette Cartomize."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LayoutPlan:
    template_id: str
    ordered_element_ids: tuple[str, ...]
    map_frame_ids: tuple[str, ...]


def build_plan(spec) -> LayoutPlan:
    items = sorted(spec.elements, key=lambda item: (item["z_index"], item["id"]))
    return LayoutPlan(spec.template_id, tuple(item["id"] for item in items), tuple(item["id"] for item in items if item["type"] == "map_frame"))
