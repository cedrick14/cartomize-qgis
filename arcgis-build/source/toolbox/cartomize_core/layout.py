"""Conversion des maquettes Cartomize en mises en page arcpy.mp natives."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from .constants import BASEMAP_HINTS, DEFAULT_DPI, TEMPLATE_SCALE_PX_PER_MM
from .models import LayoutResult, TemplateSpec


def build_layout(
    arcpy: Any,
    aprx: Any,
    map_item: Any,
    spec: TemplateSpec,
    *,
    layout_name: str,
    title: str,
    subtitle: str = "",
    credits: str = "",
    remove_basemap_from_legend: bool = True,
    visible_only: bool = True,
    margin_percent: float = 3.0,
    add_grid: bool = False,
    open_view: bool = True,
    export_path: str = "",
    pagx_path: str = "",
    dpi: int = DEFAULT_DPI,
) -> LayoutResult:
    page_width, page_height = spec.page_size_mm
    final_name = _unique_layout_name(aprx, layout_name or f"Cartomize — {spec.name}")
    layout = aprx.createLayout(page_width, page_height, "MILLIMETER", final_name)
    maps: dict[str, Any] = {}
    created: list[Any] = []

    ordered = sorted(spec.elements, key=lambda item: (item["z_index"], item["id"]))
    for item in ordered:
        kind = item["type"]
        if kind in {"legend", "scale_bar", "north_arrow"}:
            continue
        box = _page_box(item, page_width, page_height)
        geometry = _polygon(arcpy, *box)
        element = None
        if kind == "map_frame":
            element = layout.createMapFrame(geometry, map_item, item["id"])
            maps[item["id"]] = element
        elif kind in {"title", "subtitle", "text"}:
            content = item.get("content", {})
            raw_text = str(content.get("text") or "")
            text = _resolve_text(kind, raw_text, title, subtitle, credits)
            style = item.get("style", {})
            size = max(7.0, float(style.get("fontSize", 10)))
            family = str(style.get("fontFamily") or "Arial")
            font_style = "Bold" if str(style.get("fontWeight", "")).casefold() == "bold" else "Regular"
            element = aprx.createTextElement(
                # ArcGIS Pro 3.7 attend le type lié à la géométrie :
                # POLYGON pour un bloc de texte rectangulaire.
                layout, geometry, "POLYGON", text, size, family, font_style,
                None, item["id"], False,
            )
        elif kind in {"shape", "chart", "table"}:
            element = aprx.createGraphicElement(layout, geometry, None, item["id"], False)
            _style_graphic(element, item.get("style", {}))
            if kind in {"chart", "table"}:
                placeholder = "ZONE DE GRAPHIQUE" if kind == "chart" else "ZONE DE TABLEAU"
                label = aprx.createTextElement(
                    layout, _point(arcpy, box[0] + 3, box[1] + 3), "POINT",
                    placeholder, 7, "Arial", "Regular", None, f"{item['id']}-label", True,
                )
                created.append(label)
        if element is not None:
            _apply_common(element, item)
            created.append(element)

    primary = _primary_map(spec, maps)
    if primary is None:
        raise RuntimeError("La maquette ne contient aucun cadre cartographique exploitable.")
    _configure_map_extents(
        map_item, spec, maps,
        visible_only=visible_only,
        margin_percent=margin_percent,
    )

    removed = 0
    for item in ordered:
        kind = item["type"]
        if kind not in {"legend", "scale_bar", "north_arrow"}:
            continue
        linked_id = str(item.get("content", {}).get("map_id") or "")
        linked = maps.get(linked_id) or primary
        geometry = _polygon(arcpy, *_page_box(item, page_width, page_height))
        surround_type = {
            "legend": "LEGEND",
            "scale_bar": "SCALE_BAR",
            "north_arrow": "NORTH_ARROW",
        }[kind]
        element = layout.createMapSurroundElement(geometry, surround_type, linked, None, item["id"])
        _apply_common(element, item)
        created.append(element)
        if kind == "legend" and remove_basemap_from_legend:
            removed += _remove_basemap_items(element)

    warnings: list[str] = []
    grid_added = False
    if add_grid:
        grid_added = _add_native_grid(aprx, primary)
        if not grid_added:
            warnings.append(
                "Aucun style de grille ArcGIS Pro n'a été trouvé dans les styles du projet."
            )

    exported = ""
    if export_path:
        exported = export_layout(arcpy, layout, export_path, dpi=dpi)
    saved_pagx = ""
    if pagx_path:
        target = Path(pagx_path).expanduser().resolve()
        if target.suffix.casefold() != ".pagx":
            target = target.with_suffix(".pagx")
        target.parent.mkdir(parents=True, exist_ok=True)
        layout.exportToPAGX(str(target))
        saved_pagx = str(target)
    if open_view:
        try:
            layout.openView()
        except Exception:
            pass
    return LayoutResult(
        layout_name=final_name,
        template_id=spec.template_id,
        map_name=str(getattr(map_item, "name", "Map")),
        element_count=len(created),
        map_frame_count=len(maps),
        basemap_legend_items_removed=removed,
        export_path=exported,
        pagx_path=saved_pagx,
        grid_added=grid_added,
        warnings=tuple(warnings),
    )


def result_dict(result: LayoutResult) -> dict[str, Any]:
    return asdict(result)


def export_layout(arcpy: Any, layout: Any, output_path: str, *, dpi: int = DEFAULT_DPI) -> str:
    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    suffix = target.suffix.casefold().lstrip(".")
    supported = {"pdf": "PDF", "png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "tif": "TIFF", "tiff": "TIFF", "svg": "SVG"}
    if suffix not in supported:
        raise ValueError("Formats pris en charge : PDF, PNG, JPEG, TIFF et SVG.")
    export_format = arcpy.mp.CreateExportFormat(supported[suffix], str(target))
    if hasattr(export_format, "resolution"):
        export_format.resolution = max(96, min(1200, int(dpi)))
    if hasattr(export_format, "embedFonts"):
        export_format.embedFonts = True
    if hasattr(export_format, "imageQuality"):
        try:
            export_format.setImageQuality("BEST")
        except Exception:
            pass
    layout.export(export_format)
    return str(target)


def synchronize_layout(
    arcpy: Any,
    layout: Any,
    map_item: Any,
    *,
    title: str = "",
    subtitle: str = "",
    credits: str = "",
    visible_only: bool = True,
    margin_percent: float = 3.0,
) -> dict[str, int]:
    """Actualise une mise en page existante sans recréer ses éléments."""

    updated_texts = 0
    map_frames = list(layout.listElements("MAPFRAME_ELEMENT"))
    for element in layout.listElements("TEXT_ELEMENT"):
        name = str(getattr(element, "name", "") or "").casefold()
        current = str(getattr(element, "text", "") or "")
        replacement = ""
        if "title" in name or "titre" in name:
            replacement = subtitle if "sub" in name or "sous" in name else title
        elif any(token in name for token in ("source", "credit", "crédit")):
            replacement = credits
        elif current.casefold().startswith("sources"):
            replacement = credits
        if replacement and replacement != current:
            element.text = replacement
            updated_texts += 1
    reference = next((layer for layer in map_item.listLayers() if not getattr(layer, "isBroken", False) and not is_basemap_layer(layer) and (not visible_only or bool(getattr(layer, "visible", True)))), None)
    updated_frames = 0
    if reference is not None:
        for frame in map_frames:
            try:
                frame.map = map_item
            except Exception:
                pass
            try:
                extent = frame.getLayerExtent(reference, False, True)
                frame.camera.setExtent(extent)
                frame.camera.scale *= 1.0 + max(0.0, min(50.0, float(margin_percent))) / 100.0
                updated_frames += 1
            except Exception:
                pass
    return {"texts": updated_texts, "map_frames": updated_frames}


def optimize_layout(layout: Any) -> dict[str, int]:
    """Applique les garde-fous de lisibilité Cartomize à une mise en page existante."""

    page_width = float(getattr(layout, "pageWidth", 0.0) or 0.0)
    page_height = float(getattr(layout, "pageHeight", 0.0) or 0.0)
    moved = resized = 0
    for element in layout.listElements():
        try:
            x = float(getattr(element, "elementPositionX", 0.0) or 0.0)
            y = float(getattr(element, "elementPositionY", 0.0) or 0.0)
            width = float(getattr(element, "elementWidth", 0.0) or 0.0)
            height = float(getattr(element, "elementHeight", 0.0) or 0.0)
            if page_width and width > page_width:
                element.elementWidth = page_width
                width = page_width
                resized += 1
            if page_height and height > page_height:
                element.elementHeight = page_height
                height = page_height
                resized += 1
            safe_x = min(max(0.0, x), max(0.0, page_width - width)) if page_width else x
            safe_y = min(max(0.0, y), max(0.0, page_height - height)) if page_height else y
            if safe_x != x or safe_y != y:
                element.elementPositionX = safe_x
                element.elementPositionY = safe_y
                moved += 1
        except Exception:
            continue
    return {"moved": moved, "resized": resized}


def is_basemap_layer(layer_or_name: Any) -> bool:
    name = str(getattr(layer_or_name, "name", layer_or_name) or "").casefold()
    long_name = str(getattr(layer_or_name, "longName", "") or "").casefold()
    text = f"{name} {long_name}"
    if any(hint in text for hint in BASEMAP_HINTS):
        return True
    try:
        uri = str(getattr(layer_or_name, "URI", "") or "").casefold()
        return "basemap" in uri
    except Exception:
        return False


def _remove_basemap_items(legend: Any) -> int:
    removed = 0
    for item in list(getattr(legend, "items", []) or []):
        if is_basemap_layer(item):
            try:
                legend.removeItem(item)
                removed += 1
            except Exception:
                pass
    return removed


def _configure_map_extents(
    map_item: Any,
    spec: TemplateSpec,
    maps: dict[str, Any],
    *,
    visible_only: bool,
    margin_percent: float,
) -> None:
    layers = [
        layer for layer in map_item.listLayers()
        if not getattr(layer, "isBroken", False)
        and not is_basemap_layer(layer)
        and (not visible_only or bool(getattr(layer, "visible", True)))
    ]
    reference = next((layer for layer in layers if getattr(layer, "isFeatureLayer", False) or getattr(layer, "isRasterLayer", False)), None)
    if reference is None:
        return
    specs = {item["id"]: item for item in spec.elements if item["type"] == "map_frame"}
    for item_id, frame in maps.items():
        try:
            extent = frame.getLayerExtent(reference, False, True)
            frame.camera.setExtent(extent)
            role = str(specs[item_id].get("content", {}).get("role") or "main").casefold()
            margin_factor = 1.0 + max(0.0, min(50.0, float(margin_percent))) / 100.0
            factor = margin_factor if role == "main" else (3.0 if role == "locator" else max(1.35, margin_factor))
            frame.camera.scale *= factor
        except Exception:
            try:
                frame.camera = map_item.defaultCamera
            except Exception:
                pass


def _add_native_grid(aprx: Any, map_frame: Any) -> bool:
    """Ajoute une grille ArcGIS native via un élément de style du projet."""
    candidates: list[Any] = []
    for style_name in ("ArcGIS 2D", "Favorites"):
        for wildcard in ("*Measured Grid*", "*Grid*", "*Graticule*"):
            try:
                candidates.extend(aprx.listStyleItems(style_name, "GRID", wildcard))
            except Exception:
                continue
            if candidates:
                break
        if candidates:
            break
    if not candidates:
        return False
    try:
        map_frame.addGrid(candidates[0])
        return True
    except Exception:
        return False


def _primary_map(spec: TemplateSpec, maps: dict[str, Any]) -> Any | None:
    for item in spec.elements:
        if item["type"] == "map_frame" and str(item.get("content", {}).get("role", "")).casefold() == "main":
            return maps.get(item["id"])
    return next(iter(maps.values()), None)


def _resolve_text(kind: Any, raw: Any, title: Any, subtitle: Any, credits: Any) -> str:
    """Résout les textes, y compris les paramètres ArcPy facultatifs valant None."""
    kind_text = str(kind or "").casefold()
    raw_text = str(raw or "")
    title_text = str(title or "").strip()
    subtitle_text = str(subtitle or "").strip()
    credits_text = str(credits or "").strip()
    if kind_text == "title":
        return title_text or raw_text or "TITRE DE LA CARTE"
    if kind_text == "subtitle":
        return subtitle_text or raw_text
    if raw_text.casefold().startswith("sources") and credits_text:
        return credits_text
    return raw_text


def _apply_common(element: Any, item: dict[str, Any]) -> None:
    for attribute, value in (("locked", item.get("locked", False)), ("elementRotation", item.get("angle", 0))):
        if hasattr(element, attribute):
            try:
                setattr(element, attribute, value)
            except Exception:
                pass


def _style_graphic(element: Any, style: dict[str, Any]) -> None:
    """Applique les couleurs par CIM si la structure native les expose."""
    try:
        definition = element.getDefinition("V3")
        symbol = definition.graphic.symbol.symbol
        layers = list(symbol.symbolLayers or [])
        fill = _rgba(style.get("fill", "#FFFFFF"), style.get("opacity", 1))
        stroke = _rgba(style.get("stroke", "#000000"), 1)
        for layer in layers:
            if hasattr(layer, "color"):
                layer.color.values = fill
            if hasattr(layer, "width"):
                layer.width = float(style.get("strokeWidth", 0.5))
            if hasattr(layer, "color") and "Stroke" in type(layer).__name__:
                layer.color.values = stroke
        element.setDefinition(definition)
    except Exception:
        pass


def _rgba(value: Any, opacity: Any) -> list[float]:
    text = str(value or "#000000").lstrip("#")[:6]
    try:
        red, green, blue = int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    except Exception:
        red = green = blue = 0
    alpha = max(0.0, min(100.0, float(opacity) * 100.0))
    return [red, green, blue, alpha]


def _page_box(item: dict[str, Any], page_width: float, page_height: float) -> tuple[float, float, float, float]:
    x = max(0.0, float(item["x"]) / TEMPLATE_SCALE_PX_PER_MM)
    top = max(0.0, float(item["y"]) / TEMPLATE_SCALE_PX_PER_MM)
    width = max(0.1, float(item["width"]) / TEMPLATE_SCALE_PX_PER_MM)
    height = max(0.1, float(item["height"]) / TEMPLATE_SCALE_PX_PER_MM)
    x = min(x, page_width - 0.1)
    width = min(width, page_width - x)
    top = min(top, page_height - 0.1)
    height = min(height, page_height - top)
    bottom = page_height - top - height
    return round(x, 4), round(bottom, 4), round(width, 4), round(height, 4)


def _polygon(arcpy: Any, x: float, y: float, width: float, height: float) -> Any:
    points = arcpy.Array([
        arcpy.Point(x, y), arcpy.Point(x + width, y), arcpy.Point(x + width, y + height),
        arcpy.Point(x, y + height), arcpy.Point(x, y),
    ])
    return arcpy.Polygon(points)


def _point(arcpy: Any, x: float, y: float) -> Any:
    return arcpy.PointGeometry(arcpy.Point(x, y))


def _unique_layout_name(aprx: Any, requested: str) -> str:
    existing = {str(item.name).casefold() for item in aprx.listLayouts()}
    if requested.casefold() not in existing:
        return requested
    index = 2
    while f"{requested} ({index})".casefold() in existing:
        index += 1
    return f"{requested} ({index})"
