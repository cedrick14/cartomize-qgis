"""Conversion pure des anciens JSON en plan de mise en page en millimètres."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .constants import TEMPLATE_SCALE_PX_PER_MM
from .template_catalog import TemplateSpec


@dataclass(frozen=True)
class PlannedItem:
    item_id: str
    kind: str
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    rotation: float
    z_index: int
    locked: bool
    style: dict[str, Any]
    content: dict[str, Any]
    linked_map_id: str | None = None


@dataclass(frozen=True)
class LayoutPlan:
    template_id: str
    name: str
    category: str
    page_width_mm: float
    page_height_mm: float
    background_color: str
    accent_color: str
    items: tuple[PlannedItem, ...]
    primary_map_id: str

    @property
    def map_items(self) -> tuple[PlannedItem, ...]:
        return tuple(item for item in self.items if item.kind == "map_frame")


def build_layout_plan(spec: TemplateSpec) -> LayoutPlan:
    page_width, page_height = spec.page_size_mm
    raw_maps = [element for element in spec.elements if element["type"] == "map_frame"]
    if not raw_maps:
        raise ValueError(f"La maquette {spec.template_id} ne contient aucun cadre cartographique.")

    map_ids = [element["id"] for element in raw_maps]
    primary_map_id = map_ids[0]
    planned: list[PlannedItem] = []
    map_index = 0

    for element in sorted(spec.elements, key=lambda item: (item["z_index"], item["id"])):
        x = element["x"] / TEMPLATE_SCALE_PX_PER_MM
        y = element["y"] / TEMPLATE_SCALE_PX_PER_MM
        width = element["width"] / TEMPLATE_SCALE_PX_PER_MM
        height = element["height"] / TEMPLATE_SCALE_PX_PER_MM
        x, y, width, height = _fit_to_page(x, y, width, height, page_width, page_height)

        content = dict(element["content"])
        linked_map_id: str | None = None
        if element["type"] == "map_frame":
            role = (content.get("role") or "").strip().lower()
            if not role:
                role = "main" if map_index == 0 else ("locator" if map_index == 1 else "comparison")
            content["role"] = role
            map_index += 1
        elif element["type"] in {"legend", "scale_bar", "north_arrow"}:
            requested = content.get("map_id")
            linked_map_id = requested if requested in map_ids else primary_map_id
            content["map_id"] = linked_map_id

        planned.append(
            PlannedItem(
                item_id=element["id"],
                kind=element["type"],
                x_mm=x,
                y_mm=y,
                width_mm=width,
                height_mm=height,
                rotation=element["angle"],
                z_index=element["z_index"],
                locked=element["locked"],
                style=dict(element["style"]),
                content=content,
                linked_map_id=linked_map_id,
            )
        )

    return LayoutPlan(
        template_id=spec.template_id,
        name=spec.name,
        category=spec.category,
        page_width_mm=page_width,
        page_height_mm=page_height,
        background_color=spec.background_color,
        accent_color=spec.accent_color,
        items=tuple(planned),
        primary_map_id=primary_map_id,
    )


def _fit_to_page(
    x: float,
    y: float,
    width: float,
    height: float,
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float]:
    x = max(0.0, min(page_width - 0.1, x))
    y = max(0.0, min(page_height - 0.1, y))
    width = max(0.1, min(width, page_width - x))
    height = max(0.1, min(height, page_height - y))
    return (round(x, 4), round(y, 4), round(width, 4), round(height, 4))
