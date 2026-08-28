"""Lecture non destructive du projet ArcGIS Pro courant."""

from dataclasses import dataclass
from typing import Iterable

from .extent_policy import extent_factor_for_role, is_remote_basemap
from .layer_stack import LayerDescriptor, plan_layer_stacks


def project_summary(aprx) -> dict[str, object]:
    maps = list(aprx.listMaps())
    layers = [(map_item, layer) for map_item in maps for layer in map_item.listLayers()]
    return {
        "maps": len(maps),
        "layers": len(layers),
        "visible": sum(bool(getattr(layer, "visible", True)) for _, layer in layers),
        "broken": sum(bool(getattr(layer, "isBroken", False)) for _, layer in layers),
        "layouts": len(aprx.listLayouts()),
    }


@dataclass(frozen=True)
class ProjectSummary:
    layer_count: int; visible_count: int; vector_count: int; raster_count: int
    invalid_count: int; project_crs: str; extent_text: str


@dataclass(frozen=True)
class ContextBasemap:
    key: str; label: str; url: str; max_zoom: int; attribution: str


class ProjectService:
    MANAGED_PREFIX = "Cartomize — Contexte — "

    def __init__(self, iface=None, project=None, *, arcpy_module=None):
        self.arcpy = arcpy_module or _import_arcpy(); self.project = project or self.arcpy.mp.ArcGISProject("CURRENT"); self.iface = iface

    def _map(self):
        return self.project.activeMap or (self.project.listMaps()[0] if self.project.listMaps() else None)

    def ordered_layers(self, visible_only: bool = False):
        map_item = self._map(); layers = list(map_item.listLayers()) if map_item else []
        return [layer for layer in layers if not visible_only or bool(getattr(layer, "visible", True))]
    def visible_layers(self): return self.ordered_layers(True)
    def layout_ordered_layers(self): return self.ordered_layers(False)

    def layout_layer_plan(self, *, selected_ids: Iterable[str] = (), focus_id: str = "", include_visible_context: bool = True, background_mode: str = "automatic", background_layer_id: str = "", locator_mode: str = "automatic"):
        layers = self.ordered_layers(); visible = [_id(layer) for layer in layers if bool(getattr(layer, "visible", True))]
        descriptors = [LayerDescriptor(_id(layer), "vector" if getattr(layer, "isFeatureLayer", False) else "raster" if getattr(layer, "isRasterLayer", False) else "other", self.is_basemap_layer(layer)) for layer in layers]
        return plan_layer_stacks(descriptors, selected_ids=selected_ids, visible_ids=visible, focus_id=focus_id, include_visible_context=include_visible_context, background_mode=background_mode, background_layer_id=background_layer_id, locator_mode=locator_mode)

    def layers_from_ids(self, layer_ids: Iterable[str]):
        by_id = {_id(layer): layer for layer in self.ordered_layers()}; return [by_id[value] for value in layer_ids if value in by_id]
    def background_candidates(self):
        layers = self.layout_ordered_layers()
        remote = [layer for layer in layers if self.is_basemap_layer(layer)]
        local_rasters = [
            layer for layer in layers
            if bool(getattr(layer, "isRasterLayer", False)) and not self.is_basemap_layer(layer)
        ]
        return remote + local_rasters

    @staticmethod
    def context_basemap_definitions():
        return (
            ContextBasemap("osm", "OpenStreetMap", "https://basemaps.arcgis.com/arcgis/rest/services/OpenStreetMap_v2/VectorTileServer", 19, "© OpenStreetMap contributors"),
            ContextBasemap("terrain", "Terrain (OpenTopoMap)", "https://services.arcgisonline.com/ArcGIS/rest/services/World_Terrain_Base/MapServer", 17, "© OpenStreetMap contributors, SRTM | OpenTopoMap"),
            ContextBasemap("satellite", "Imagerie satellitaire", "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer", 19, "Sources: Esri, Maxar, Earthstar Geographics and contributors"),
        )

    def active_context_basemap_key(self):
        for layer in self.background_candidates():
            name = str(getattr(layer, "name", "")).casefold()
            for item in self.context_basemap_definitions():
                if item.key in name or item.label.casefold() in name: return item.key
        return ""
    def active_context_opacity_percent(self):
        layers = self.background_candidates(); return max(0, min(100, 100 - int(getattr(layers[0], "transparency", 0) or 0))) if layers else 100

    def activate_context_basemap(self, key: str):
        definition = next((item for item in self.context_basemap_definitions() if item.key == key), None)
        if definition is None: raise ValueError(f"Fond cartographique inconnu : {key}")
        self.clear_managed_context_basemap(); map_item = self._map()
        if map_item is None: raise RuntimeError("Aucune carte ArcGIS Pro active.")
        layer = map_item.addDataFromPath(definition.url)
        try: layer.name = f"{self.MANAGED_PREFIX}{definition.key}"
        except Exception: pass
        return layer

    def clear_managed_context_basemap(self):
        map_item = self._map(); removed = 0
        if map_item:
            for layer in list(map_item.listLayers()):
                if str(getattr(layer, "name", "")).startswith(self.MANAGED_PREFIX): map_item.removeLayer(layer); removed += 1
        return removed
    def set_context_layer_opacity(self, layer_id: str, percent: int | float):
        layer = self.layer_by_id(layer_id); percent = max(0, min(100, float(percent)))
        if layer is None: return False
        layer.transparency = 100 - round(percent); return True
    def canvas_style_overrides(self, layers): return {_id(layer): "" for layer in layers}
    def active_layer(self):
        view = getattr(self.project, "activeView", None)
        selected = list(getattr(view, "getSelection", lambda: [])() or []) if view else []
        return selected[0] if selected else (self.ordered_layers()[0] if self.ordered_layers() else None)
    @staticmethod
    def is_basemap_layer(layer):
        if layer is None: return False
        name = str(getattr(layer, "name", "")); source = str(getattr(layer, "dataSource", ""));
        return is_remote_basemap("arcgismapserver" if "MapServer" in source else "", source, name) or any(token in name.casefold() for token in ("basemap", "fond de carte", "world topo", "world imagery", "hillshade", "openstreetmap"))
    def focus_layer(self, layers, main_layer_id: str = ""):
        layers = list(layers); return next((layer for layer in layers if _id(layer) == main_layer_id), layers[0] if layers else None)
    def active_vector_layer(self):
        layer = self.active_layer(); return layer if layer is not None and getattr(layer, "isFeatureLayer", False) else None
    def layer_by_id(self, layer_id: str): return next((layer for layer in self.ordered_layers() if _id(layer) == layer_id), None)
    def display_crs(self, layers=None):
        map_item = self._map(); return getattr(map_item, "spatialReference", None)

    def combined_extent(self, layers, *, target_crs=None, margin_ratio: float = 0.0):
        extents = [self.arcpy.Describe(layer).extent for layer in layers if layer is not None and not self.is_basemap_layer(layer)]
        if not extents: return None
        xmin, ymin = min(e.XMin for e in extents), min(e.YMin for e in extents); xmax, ymax = max(e.XMax for e in extents), max(e.YMax for e in extents)
        dx, dy = (xmax-xmin)*max(0, margin_ratio), (ymax-ymin)*max(0, margin_ratio)
        return self.arcpy.Extent(xmin-dx, ymin-dy, xmax+dx, ymax+dy)
    def layer_extent(self, layer, *, target_crs=None, margin_ratio: float = 0.0): return self.combined_extent([layer] if layer else [], target_crs=target_crs, margin_ratio=margin_ratio)
    def map_extent(self, layers, *, main_layer_id: str = "", target_crs=None, margin_ratio: float = 0.03):
        focus = self.focus_layer(layers, main_layer_id); return self.combined_extent(layers, target_crs=target_crs, margin_ratio=margin_ratio), focus
    def extent_for_role(self, main_extent, role: str, *, target_crs=None):
        if main_extent is None: return None
        factor = extent_factor_for_role(role); cx, cy = (main_extent.XMin+main_extent.XMax)/2, (main_extent.YMin+main_extent.YMax)/2
        width, height = main_extent.width*factor, main_extent.height*factor
        return self.arcpy.Extent(cx-width/2, cy-height/2, cx+width/2, cy+height/2)
    def preferred_extent(self, layers, margin_ratio: float = .03, *, target_crs=None): return self.combined_extent(layers, target_crs=target_crs, margin_ratio=margin_ratio)
    def project_extent(self, margin_ratio: float = .08, *, target_crs=None): return self.combined_extent(self.visible_layers(), target_crs=target_crs, margin_ratio=margin_ratio)
    def zoom_to_layer(self, layer):
        extent = self.layer_extent(layer)
        map_item = self._map()
        if map_item is not None and extent is not None: map_item.defaultCamera.setExtent(extent); return True
        return False
    def summary(self):
        layers = self.ordered_layers(); extent = self.project_extent(0)
        crs = self.display_crs(); crs_name = str(getattr(crs, "name", "") or "")
        extent_text = "" if extent is None else f"{extent.XMin:.3f}, {extent.YMin:.3f} — {extent.XMax:.3f}, {extent.YMax:.3f}"
        return ProjectSummary(len(layers), sum(bool(getattr(layer, "visible", True)) for layer in layers), sum(bool(getattr(layer, "isFeatureLayer", False)) for layer in layers), sum(bool(getattr(layer, "isRasterLayer", False)) for layer in layers), sum(bool(getattr(layer, "isBroken", False)) for layer in layers), crs_name, extent_text)


def _id(layer): return str(getattr(layer, "URI", "") or getattr(layer, "longName", "") or getattr(layer, "name", "") or layer)
def _import_arcpy():
    try:
        import arcpy; return arcpy
    except ImportError as exc: raise RuntimeError("ArcPy est requis pour lire le projet.") from exc
