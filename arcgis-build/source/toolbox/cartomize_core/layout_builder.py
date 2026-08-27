"""Construction des mises en page depuis les mêmes maquettes Cartomize."""

from dataclasses import dataclass

from .constants import APP_VERSION
from .errors import LayoutBuildError
from .layout import build_layout, optimize_layout, result_dict, synchronize_layout


@dataclass(frozen=True)
class LayoutBuildOptions:
    title: str = ""
    subtitle: str = ""
    author: str = ""
    organization: str = ""
    sources: str = ""
    visible_layers_only: bool = True
    extent_margin_percent: float = 3.0
    add_grid: bool = False
    requested_name: str = ""
    open_designer: bool | None = None
    layer_ids: tuple[str, ...] = ()
    main_layer_id: str = ""
    include_visible_context: bool = True
    background_mode: str = "automatic"
    background_layer_id: str = ""
    locator_mode: str = "automatic"


@dataclass(frozen=True)
class LayoutBuildResult:
    layout: object
    layout_name: str
    item_count: int
    map_count: int
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class LayoutSyncResult:
    map_count: int
    main_layer_count: int
    locator_layer_count: int
    warnings: tuple[str, ...]


class LayoutBuilder:
    """Adaptation arcpy.mp du contrat public LayoutBuilder 10.5.1."""

    def __init__(self, iface=None, project=None, resources_dir=None, *, arcpy_module=None, map_item=None):
        self.arcpy = arcpy_module or _import_arcpy()
        self.project = project or self.arcpy.mp.ArcGISProject("CURRENT")
        self.map_item = map_item

    def build(self, spec, options: LayoutBuildOptions | None = None) -> LayoutBuildResult:
        options = options or LayoutBuildOptions()
        map_item = self.map_item or _active_map(self.project)
        if map_item is None:
            raise LayoutBuildError("Aucune carte ArcGIS Pro n'est disponible.")
        try:
            result = build_layout(
                self.arcpy, self.project, map_item, spec,
                layout_name=options.requested_name or options.title or spec.name,
                title=options.title or spec.name, subtitle=options.subtitle,
                credits=options.sources, visible_only=options.visible_layers_only,
                margin_percent=options.extent_margin_percent, add_grid=options.add_grid,
                open_view=True if options.open_designer is None else options.open_designer,
            )
            layout = self.project.listLayouts(result.layout_name)[0]
            return LayoutBuildResult(layout, result.layout_name, result.element_count, result.map_frame_count, result.warnings)
        except Exception as exc:
            raise LayoutBuildError(str(exc)) from exc

    def synchronize_with_project(self, layout, options: LayoutBuildOptions | None = None) -> LayoutSyncResult:
        options = options or LayoutBuildOptions()
        map_item = self.map_item or _active_map(self.project)
        if layout is None or map_item is None:
            raise LayoutBuildError("Aucune mise en page ou carte ArcGIS Pro n'est disponible.")
        counts = synchronize_layout(self.arcpy, layout, map_item, title=options.title, subtitle=options.subtitle, credits=options.sources, visible_only=options.visible_layers_only, margin_percent=options.extent_margin_percent)
        map_count = int(counts.get("map_frames", 0))
        return LayoutSyncResult(map_count, map_count, max(0, map_count - 1), ())

    def optimize_existing_layout(self, layout) -> tuple[str, ...]:
        counts = optimize_layout(layout)
        changes = []
        if counts.get("moved"):
            changes.append(f"{counts['moved']} déplacement(s)")
        if counts.get("resized"):
            changes.append(f"{counts['resized']} redimensionnement(s)")
        return tuple(changes)


def _import_arcpy():
    try:
        import arcpy
        return arcpy
    except ImportError as exc:
        raise LayoutBuildError("ArcPy est requis pour construire une mise en page.") from exc


def _active_map(project):
    active = getattr(project, "activeMap", None)
    if active is not None:
        return active
    maps = list(project.listMaps())
    return maps[0] if maps else None

__all__ = ["LayoutBuildOptions", "LayoutBuildResult", "LayoutSyncResult", "LayoutBuilder", "build_layout", "result_dict"]
