"""Conversion des maquettes Cartomize en véritables QgsPrintLayout."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import math
from typing import Any

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont
from qgis.core import (
    QgsFillSymbol,
    QgsLayoutFrame,
    QgsLayoutItemAttributeTable,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLayoutItemMapGrid,
    QgsLayoutItemMapOverview,
    QgsLayoutItemPicture,
    QgsLayoutItemScaleBar,
    QgsLayoutItemShape,
    QgsLegendStyle,
    Qgis,
    QgsLayoutMeasurement,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsMapLayer,
    QgsMapLayerLegendUtils,
    QgsPrintLayout,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsTextFormat,
    QgsVectorLayer,
)

from .compat import (
    configure_layout_rendering,
    preview_dpi_for_width,
    distance_meters,
    horizontal_alignment,
    layout_mm_unit,
    render_points_unit,
    vertical_alignment,
)
from .constants import PLUGIN_VERSION
from .errors import LayoutBuildError
from .layout_plan import PlannedItem, build_layout_plan
from .project_service import ProjectService
from .settings import CartomizeSettings
from .template_catalog import TemplateSpec


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


@dataclass(frozen=True)
class LayoutBuildResult:
    layout: QgsPrintLayout
    layout_name: str
    item_count: int
    map_count: int
    warnings: tuple[str, ...]


class LayoutBuilder:
    """Construit des objets QGIS natifs, persistés dans le projet QGZ."""

    def __init__(self, iface, project: QgsProject | None = None, resources_dir: Path | None = None):
        self.iface = iface
        self.project = project or QgsProject.instance()
        self.project_service = ProjectService(iface, self.project)
        self.resources_dir = (resources_dir or Path(__file__).resolve().parents[1] / "resources").resolve()

    def build(self, spec: TemplateSpec, options: LayoutBuildOptions | None = None) -> LayoutBuildResult:
        options = options or LayoutBuildOptions()
        settings = CartomizeSettings.load()
        plan = build_layout_plan(spec)
        manager = self.project.layoutManager()
        layout_name = self._unique_layout_name(options.requested_name or options.title or spec.name)
        layout = QgsPrintLayout(self.project)
        layout.initializeDefaults()
        configure_layout_rendering(layout, preview_dpi_for_width(layout, settings.preview_width_px))
        layout.setName(layout_name)
        layout.setUnits(layout_mm_unit())
        layout.setCustomProperty("cartomize/template_id", plan.template_id)
        layout.setCustomProperty("cartomize/version", PLUGIN_VERSION)
        layout.setCustomProperty("cartomize/native_qgis", True)
        layout.setCustomProperty("cartomize/readability_profile", 5)
        if options.main_layer_id:
            layout.setCustomProperty("cartomize/main_layer_id", options.main_layer_id)
        if options.layer_ids:
            layout.setCustomProperty("cartomize/layer_ids", list(options.layer_ids))

        page = layout.pageCollection().page(0)
        page.setPageSize(QgsLayoutSize(plan.page_width_mm, plan.page_height_mm, layout_mm_unit()))
        page.setPageStyleSymbol(QgsFillSymbol.createSimple({"color": plan.background_color, "outline_style": "no"}))

        if options.layer_ids:
            requested = set(options.layer_ids)
            layers = [
                layer
                for layer in self.project_service.ordered_layers()
                if layer.id() in requested
            ]
        elif options.visible_layers_only:
            layers = self.project_service.visible_layers()
        else:
            layers = self.project_service.ordered_layers()
        layers = [layer for layer in layers if layer and layer.isValid()]
        warnings: list[str] = []
        if not layers:
            warnings.append("Aucune couche valide n'était chargée lors de la création de la mise en page.")

        map_crs = self.project_service.display_crs(layers)
        if not map_crs.isValid():
            raise LayoutBuildError("Aucun CRS valide n'est disponible pour construire les cadres cartographiques.")
        if not self.project.crs().isValid():
            warnings.append(
                "Le CRS du projet n'est pas défini. Les cadres utilisent "
                f"temporairement {map_crs.authid() or map_crs.description()}."
            )

        margin_ratio = max(0.0, min(0.5, float(options.extent_margin_percent) / 100.0))
        main_extent = self.project_service.combined_extent(layers, target_crs=map_crs, margin_ratio=margin_ratio)
        if main_extent is None or main_extent.isEmpty():
            main_extent = self.project_service.preferred_extent(layers, margin_ratio, target_crs=map_crs)
        project_extent = self.project_service.project_extent(max(0.08, margin_ratio), target_crs=map_crs)

        map_items: dict[str, QgsLayoutItemMap] = {}
        map_roles: dict[str, str] = {}
        for planned in plan.map_items:
            role = str(planned.content.get("role") or "main").lower()
            map_item = self._create_map_item(
                layout,
                planned,
                layers,
                main_extent if role not in {"locator", "overview", "inset"} else project_extent,
                settings.preserve_map_layer_set,
                map_crs,
            )
            map_items[planned.item_id] = map_item
            map_roles[planned.item_id] = role

        if not map_items:
            raise LayoutBuildError("La maquette ne contient aucun cadre cartographique.")
        primary_map = map_items.get(plan.primary_map_id) or next(iter(map_items.values()))
        layout.setReferenceMap(primary_map)

        for item_id, map_item in map_items.items():
            if map_roles.get(item_id) not in {"locator", "overview", "inset"}:
                continue
            try:
                overview = QgsLayoutItemMapOverview(f"Cartomize {item_id}", map_item)
                overview.setLinkedMap(primary_map)
                map_item.overviews().addOverview(overview)
            except Exception as exc:
                warnings.append(f"Indicateur d'emprise non ajouté à {item_id} : {exc}")

        if options.add_grid:
            try:
                self._add_grid(primary_map)
            except Exception as exc:
                warnings.append(f"Grille non ajoutée : {exc}")

        created = len(map_items)
        for planned in plan.items:
            if planned.kind == "map_frame":
                continue
            linked = map_items.get(planned.linked_map_id or "", primary_map)
            try:
                created += self._create_item(layout, planned, linked, options, settings)
            except Exception as exc:
                warnings.append(f"Élément {planned.item_id} ({planned.kind}) non créé : {exc}")

        for map_item in map_items.values():
            try:
                map_item.invalidateCache()
            except Exception:
                pass
            map_item.refresh()
        try:
            invalidate = getattr(layout, "invalidateCachedRenders", None)
            if callable(invalidate):
                invalidate()
        except Exception:
            pass
        try:
            layout.refresh()
        except Exception:
            pass

        if not manager.addLayout(layout):
            raise LayoutBuildError(f"QGIS a refusé d'ajouter la mise en page « {layout_name} » au projet.")
        self.project.setDirty(True)
        should_open = settings.open_designer_after_creation if options.open_designer is None else options.open_designer
        if should_open:
            self.iface.openLayoutDesigner(layout)
        return LayoutBuildResult(layout, layout_name, created, len(map_items), tuple(warnings))

    def _create_map_item(
        self,
        layout: QgsPrintLayout,
        planned: PlannedItem,
        layers: list[QgsMapLayer],
        extent: QgsRectangle,
        preserve_layer_set: bool,
        map_crs,
    ) -> QgsLayoutItemMap:
        item = QgsLayoutItemMap(layout)
        layout.addLayoutItem(item)
        self._apply_geometry(item, planned)
        item.setCustomProperty("cartomize/role", planned.content.get("role", "main"))
        item.setCustomProperty("cartomize/template_item_id", planned.item_id)
        item.setCrs(map_crs)
        item.setLayers(layers)
        item.setKeepLayerSet(bool(preserve_layer_set))
        try:
            item.setKeepLayerStyles(False)
        except AttributeError:
            pass
        item.setDrawAnnotations(True)
        try:
            item.setBackgroundEnabled(True)
            item.setBackgroundColor(QColor("#ffffff"))
        except AttributeError:
            pass
        item.setFrameEnabled(True)
        item.setFrameStrokeColor(QColor(planned.style.get("stroke", "#334155")))
        stroke_width = max(
            0.1,
            float(planned.style.get("strokeWidth", 0.8)),
        ) / 3.0
        item.setFrameStrokeWidth(
            QgsLayoutMeasurement(stroke_width, layout_mm_unit())
        )
        item.zoomToExtent(extent)
        if planned.rotation:
            item.setMapRotation(planned.rotation)
        return item

    def _create_item(
        self,
        layout: QgsPrintLayout,
        planned: PlannedItem,
        linked_map: QgsLayoutItemMap,
        options: LayoutBuildOptions,
        settings: CartomizeSettings,
    ) -> int:
        if planned.kind in {"title", "subtitle", "text"}:
            self._create_label(layout, planned, options, settings)
            return 1
        if planned.kind == "shape":
            self._create_shape(layout, planned)
            return 1
        if planned.kind == "legend":
            self._create_legend(layout, planned, linked_map, settings)
            return 1
        if planned.kind == "scale_bar":
            self._create_scale_bar(layout, planned, linked_map, settings)
            return 1
        if planned.kind == "north_arrow":
            self._create_north_arrow(layout, planned, linked_map)
            return 1
        if planned.kind == "table":
            return self._create_attribute_table(layout, planned, linked_map, settings)
        if planned.kind == "chart":
            return self._create_summary_chart(layout, planned, settings)
        return 0

    def _create_label(self, layout, planned, options, settings):
        label = QgsLayoutItemLabel(layout)
        layout.addLayoutItem(label)
        label.setText(self._resolved_text(planned, options, settings))
        fmt = QgsTextFormat()
        font = QFont(_font_family(planned.style.get("fontFamily", "Noto Sans")))
        font.setBold(str(planned.style.get("fontWeight", "")).lower() in {"bold", "600", "700", "800", "900"})
        font.setItalic(str(planned.style.get("fontStyle", "")).lower() == "italic")
        fmt.setFont(font)
        fmt.setSize(_readable_font_size(planned, settings))
        fmt.setSizeUnit(render_points_unit())
        fmt.setColor(QColor(planned.style.get("fill", "#111827")))
        label.setTextFormat(fmt)
        label.setHAlign(horizontal_alignment(str(planned.style.get("textAlign", "left"))))
        label.setVAlign(vertical_alignment(str(planned.style.get("verticalAlign", "top"))))
        label.setMargin(0.6 if planned.kind == "text" else 0.3)
        self._apply_geometry(label, planned)
        return label

    def _create_shape(self, layout, planned):
        shape = QgsLayoutItemShape(layout)
        layout.addLayoutItem(shape)
        shape.setSymbol(QgsFillSymbol.createSimple({
            "color": planned.style.get("fill", "#ffffff"),
            "outline_color": planned.style.get("stroke", planned.style.get("fill", "#ffffff")),
            "outline_width": str(max(0.0, float(planned.style.get("strokeWidth", 0.0))) / 3.0),
            "outline_style": "solid" if planned.style.get("stroke") else "no",
        }))
        self._apply_geometry(shape, planned)
        return shape

    def _create_legend(self, layout, planned, linked_map, settings):
        legend = QgsLayoutItemLegend(layout)
        layout.addLayoutItem(legend)
        legend.setLinkedMap(linked_map)
        legend.setTitle("Légende")
        legend.setResizeToContents(False)
        try:
            legend.setColumnCount(1)
            legend.setSplitLayer(False)
        except AttributeError:
            pass
        if settings.filter_legend_by_map:
            legend.setLegendFilterByMapEnabled(True)
        self._apply_legend_readability(legend, settings)
        try:
            legend.setAutoWrapLinesAfter(max(28.0, planned.width_mm - 7.0))
        except AttributeError:
            pass
        self._apply_geometry(legend, planned)
        legend.updateLegend()
        self._clean_legend_model(legend, linked_map.layers())
        legend.refresh()
        return legend

    def _apply_legend_readability(self, legend, settings) -> None:
        components = getattr(Qgis, "LegendComponent", None)
        if components is None:
            return
        sizes = {
            "Title": max(14.0, settings.minimum_font_size_pt + 4.0),
            "Group": max(11.5, settings.minimum_font_size_pt + 2.0),
            "Subgroup": max(11.0, settings.minimum_font_size_pt + 1.5),
            "SymbolLabel": max(10.5, settings.minimum_font_size_pt + 0.75),
        }
        for component_name, size in sizes.items():
            component = getattr(components, component_name, None)
            if component is None:
                continue
            style = legend.style(component)
            text_format = style.textFormat()
            font = QFont("Arial")
            font.setBold(component_name in {"Title", "Group"})
            text_format.setFont(font)
            text_format.setSize(size)
            text_format.setSizeUnit(render_points_unit())
            text_format.setColor(QColor("#111827"))
            style.setTextFormat(text_format)
            legend.setStyle(component, style)
        legend.setBoxSpace(2.5)
        legend.setSymbolWidth(7.0)
        legend.setSymbolHeight(5.0)
        try:
            legend.setMaximumSymbolSize(9.0)
        except AttributeError:
            pass
        try:
            legend.setBackgroundEnabled(True)
            legend.setBackgroundColor(QColor("#ffffff"))
        except AttributeError:
            pass

    def _clean_legend_model(self, legend, layers) -> None:
        """Supprime les en-têtes raster redondants et rend les noms de couches lisibles."""
        try:
            model = legend.model()
            root = model.rootGroup()
        except Exception:
            return
        display_role = getattr(getattr(Qt, "ItemDataRole", Qt), "DisplayRole", 0)
        for layer in layers or []:
            try:
                node = root.findLayer(layer.id())
            except Exception:
                node = None
            if node is None:
                continue
            try:
                node.setCustomProperty("legend/title-label", _readable_layer_name(layer.name()))
            except Exception:
                pass
            if not isinstance(layer, QgsRasterLayer):
                continue
            try:
                nodes = list(model.layerLegendNodes(node, True))
            except TypeError:
                try:
                    nodes = list(model.layerLegendNodes(node))
                except Exception:
                    continue
            except Exception:
                continue
            if len(nodes) < 3:
                continue
            keep: list[int] = []
            for index, legend_node in enumerate(nodes):
                try:
                    label = str(legend_node.data(display_role) or "").strip()
                except Exception:
                    label = ""
                if index == 0 and _redundant_raster_heading(label):
                    continue
                keep.append(index)
            if keep and len(keep) < len(nodes):
                try:
                    QgsMapLayerLegendUtils.setLegendNodeOrder(node, keep)
                except Exception:
                    pass
        try:
            legend.updateLegend()
        except Exception:
            pass

    def _create_scale_bar(self, layout, planned, linked_map, settings):
        scale = QgsLayoutItemScaleBar(layout)
        layout.addLayoutItem(scale)
        scale.setLinkedMap(linked_map)
        scale.applyDefaultSettings()
        try:
            scale.setStyle("Single Box")
        except Exception:
            pass
        try:
            scale.setUnits(distance_meters())
        except Exception:
            pass
        self._configure_scale_bar(scale, linked_map, settings, planned.width_mm)
        self._apply_geometry(scale, planned)
        try:
            scale.refresh()
        except Exception:
            pass
        return scale

    def _configure_scale_bar(self, scale, linked_map, settings, width_mm: float) -> None:
        try:
            scale.setNumberOfSegments(4)
            scale.setNumberOfSegmentsLeft(0)
        except Exception:
            pass
        modes = getattr(Qgis, "ScaleBarSegmentSizeMode", None)
        fit_width = getattr(modes, "FitWidth", None) if modes is not None else None
        if fit_width is not None:
            try:
                scale.setSegmentSizeMode(fit_width)
            except Exception:
                pass
        usable_width = max(24.0, float(width_mm) - 4.0)
        try:
            scale.setMinimumBarWidth(max(20.0, usable_width * 0.82))
            scale.setMaximumBarWidth(usable_width)
        except Exception:
            pass
        try:
            scale.setHeight(4.0)
            scale.setBoxContentSpace(1.5)
        except Exception:
            pass
        try:
            map_scale = float(linked_map.scale())
        except Exception:
            map_scale = 100000.0
        try:
            if map_scale >= 75000:
                scale.setMapUnitsPerScaleBarUnit(1000.0)
                scale.setUnitLabel("km")
            else:
                scale.setMapUnitsPerScaleBarUnit(1.0)
                scale.setUnitLabel("m")
        except Exception:
            pass
        text_format = scale.textFormat()
        font = QFont("Arial")
        font.setBold(True)
        text_format.setFont(font)
        text_format.setSize(max(10.0, settings.minimum_font_size_pt + 0.5))
        text_format.setSizeUnit(render_points_unit())
        text_format.setColor(QColor("#111827"))
        scale.setTextFormat(text_format)
        scale.setLabelBarSpace(2.0)

    def _create_north_arrow(self, layout, planned, linked_map):
        path = self.resources_dir / "north_arrow.svg"
        if not path.is_file() or path.is_symlink():
            raise LayoutBuildError("La ressource de flèche nord est introuvable.")
        north = QgsLayoutItemPicture(layout)
        layout.addLayoutItem(north)
        north.setPicturePath(str(path))
        north.setLinkedMap(linked_map)
        size = max(18.0, planned.width_mm, planned.height_mm)
        x = max(0.0, planned.x_mm + (planned.width_mm - size) / 2.0)
        y = max(0.0, planned.y_mm + (planned.height_mm - size) / 2.0)
        north.setId(planned.item_id)
        north.attemptMove(QgsLayoutPoint(x, y, layout_mm_unit()))
        north.attemptResize(QgsLayoutSize(size, size, layout_mm_unit()))
        north.setLocked(planned.locked)
        north.setZValue(planned.z_index)
        return north

    def _create_attribute_table(self, layout, planned, linked_map, settings) -> int:
        layer = self.project_service.active_vector_layer()
        if layer is None:
            self._create_placeholder(
                layout,
                planned,
                "Table attributaire. Sélectionnez une couche vectorielle dans QGIS.",
                settings,
            )
            return 1
        try:
            table = QgsLayoutItemAttributeTable(layout)
            layout.addMultiFrame(table)
            table.setVectorLayer(layer)
            table.setMap(linked_map)
            table.setDisplayOnlyVisibleFeatures(True)
            table.setMaximumNumberOfFeatures(10)
            table.setUseConditionalStyling(True)
            header_format = QgsTextFormat()
            header_font = QFont("Arial")
            header_font.setBold(True)
            header_format.setFont(header_font)
            header_format.setSize(max(8.5, settings.minimum_font_size_pt))
            header_format.setSizeUnit(render_points_unit())
            content_format = QgsTextFormat()
            content_format.setFont(QFont("Arial"))
            content_format.setSize(max(8.0, settings.minimum_font_size_pt))
            content_format.setSizeUnit(render_points_unit())
            table.setHeaderTextFormat(header_format)
            table.setContentTextFormat(content_format)
            fields = [field.name() for field in list(layer.fields())[:8]]
            if hasattr(table, "setDisplayedFields"):
                table.setDisplayedFields(fields)
            frame = QgsLayoutFrame(layout, table)
            frame.setId(planned.item_id)
            frame.attemptMove(QgsLayoutPoint(planned.x_mm, planned.y_mm, layout_mm_unit()))
            frame.attemptResize(QgsLayoutSize(planned.width_mm, planned.height_mm, layout_mm_unit()))
            table.addFrame(frame)
            frame.setLocked(planned.locked)
            frame.setZValue(planned.z_index)
            return 1
        except Exception:
            self._create_placeholder(
                layout,
                planned,
                f"Table : {layer.name()}. Configurez les colonnes dans la mise en page QGIS.",
                settings,
            )
            return 1

    def _create_summary_chart(self, layout, planned, settings) -> int:
        """Graphique natif minimal composé de QgsLayoutItemShape et QgsLayoutItemLabel."""
        values: list[tuple[str, int]] = []
        for layer in self.project_service.visible_layers()[:5]:
            if isinstance(layer, QgsVectorLayer):
                value = max(0, int(layer.featureCount()))
            elif isinstance(layer, QgsRasterLayer):
                value = max(1, int(layer.bandCount()))
            else:
                value = 1
            values.append((layer.name()[:28], value))
        if not values:
            values = [("Aucune couche visible", 0)]
        max_value = max(1, max(value for _, value in values))
        created = 0
        background = QgsLayoutItemShape(layout)
        layout.addLayoutItem(background)
        background.setSymbol(
            QgsFillSymbol.createSimple(
                {
                    "color": "#f8fafc",
                    "outline_color": "#cbd5e1",
                    "outline_width": "0.25",
                }
            )
        )
        self._apply_geometry(background, planned)
        created += 1
        title = QgsLayoutItemLabel(layout)
        layout.addLayoutItem(title)
        title.setText(str(planned.content.get("title") or "Indicateurs"))
        fmt = QgsTextFormat()
        font = QFont("Noto Sans")
        font.setBold(True)
        fmt.setFont(font)
        fmt.setSize(max(9.0, settings.minimum_font_size_pt))
        fmt.setSizeUnit(render_points_unit())
        fmt.setColor(QColor("#0f172a"))
        title.setTextFormat(fmt)
        title.attemptMove(QgsLayoutPoint(planned.x_mm + 2, planned.y_mm + 1.5, layout_mm_unit()))
        title.attemptResize(QgsLayoutSize(planned.width_mm - 4, 6, layout_mm_unit()))
        title.setId(f"{planned.item_id}-title")
        title.setZValue(planned.z_index + 1)
        created += 1
        top = planned.y_mm + 9.0
        row_height = max(5.0, (planned.height_mm - 11.0) / max(1, len(values)))
        label_width = min(planned.width_mm * 0.42, 38.0)
        bar_space = max(5.0, planned.width_mm - label_width - 8.0)
        colors = ("#0f766e", "#2563eb", "#7c3aed", "#ea580c", "#be123c")
        for index, (name, value) in enumerate(values):
            y = top + index * row_height
            label = QgsLayoutItemLabel(layout)
            layout.addLayoutItem(label)
            label.setText(name)
            label_fmt = QgsTextFormat()
            label_fmt.setSize(max(8.0, settings.minimum_font_size_pt))
            label_fmt.setSizeUnit(render_points_unit())
            label_fmt.setColor(QColor("#334155"))
            label.setTextFormat(label_fmt)
            label.attemptMove(QgsLayoutPoint(planned.x_mm + 2, y, layout_mm_unit()))
            label.attemptResize(QgsLayoutSize(label_width, row_height - 0.5, layout_mm_unit()))
            label.setId(f"{planned.item_id}-label-{index}")
            label.setZValue(planned.z_index + 1)
            created += 1
            bar = QgsLayoutItemShape(layout)
            layout.addLayoutItem(bar)
            bar.setSymbol(QgsFillSymbol.createSimple({"color": colors[index % len(colors)], "outline_style": "no"}))
            bar.attemptMove(QgsLayoutPoint(planned.x_mm + label_width + 3, y + 0.7, layout_mm_unit()))
            bar.attemptResize(
                QgsLayoutSize(
                    max(0.8, bar_space * value / max_value),
                    max(1.8, row_height - 2.0),
                    layout_mm_unit(),
                )
            )
            bar.setId(f"{planned.item_id}-bar-{index}")
            bar.setZValue(planned.z_index + 1)
            created += 1
        return created

    def _create_placeholder(self, layout, planned, text, settings):
        label = QgsLayoutItemLabel(layout)
        layout.addLayoutItem(label)
        label.setText(text)
        fmt = QgsTextFormat()
        fmt.setSize(max(8.0, settings.minimum_font_size_pt))
        fmt.setSizeUnit(render_points_unit())
        fmt.setColor(QColor("#475569"))
        label.setTextFormat(fmt)
        label.setFrameEnabled(True)
        self._apply_geometry(label, planned)

    def _add_grid(self, map_item):
        grid = QgsLayoutItemMapGrid("Grille Cartomize", map_item)
        extent = map_item.extent()
        interval = _nice_interval(max(abs(extent.width()), abs(extent.height())) / 5.0)
        grid.setIntervalX(interval)
        grid.setIntervalY(interval)
        grid.setGridLineColor(QColor("#64748b"))
        grid.setGridLineWidth(0.15)
        grid.setAnnotationEnabled(True)
        try:
            grid.setAnnotationPrecision(2 if map_item.crs().isGeographic() else 0)
        except Exception:
            pass
        grid.setEnabled(True)
        map_item.grids().addGrid(grid)
        map_item.updateBoundingRect()
        map_item.update()

    def _apply_geometry(self, item, planned: PlannedItem) -> None:
        item.setId(planned.item_id)
        item.attemptMove(QgsLayoutPoint(planned.x_mm, planned.y_mm, layout_mm_unit()))
        item.attemptResize(QgsLayoutSize(planned.width_mm, planned.height_mm, layout_mm_unit()))
        if planned.rotation and not isinstance(item, QgsLayoutItemMap):
            item.setItemRotation(planned.rotation)
        item.setLocked(planned.locked)
        item.setZValue(planned.z_index)
        if "opacity" in planned.style:
            item.setItemOpacity(max(0.0, min(1.0, float(planned.style["opacity"]))))

    def _resolved_text(self, planned: PlannedItem, options: LayoutBuildOptions, settings: CartomizeSettings) -> str:
        text = str(planned.content.get("text") or "")[:4000]
        if planned.kind == "title" and options.title:
            text = options.title
        elif planned.kind == "subtitle" and options.subtitle:
            text = options.subtitle
        elif (
            planned.kind == "text"
            and options.sources
            and any(
                token in text.casefold()
                for token in ("source", "donnée", "crédit")
            )
        ):
            text = options.sources
        author = options.author or settings.author
        organization = options.organization or settings.organization
        crs = self.project.crs().authid() or self.project.crs().description() or "non défini"
        project_name = self.project.title() or self.project.baseName() or "Projet QGIS"
        replacements: dict[str, str] = {
            "{{project}}": project_name,
            "{{crs}}": crs,
            "{{author}}": author or "…",
            "{{organization}}": organization or "…",
            "{{date}}": date.today().isoformat(),
            "Projection/CRS : …": f"Projection/CRS : {crs}",
            "Réalisation : …": f"Réalisation : {author or '…'}",
            "Date : …": f"Date : {date.today().isoformat()}",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
        return text

    def optimize_existing_layout(self, layout: QgsPrintLayout) -> tuple[str, ...]:
        """Améliore une mise en page Cartomize déjà créée sans modifier les couches du projet."""
        settings = CartomizeSettings.load()
        configure_layout_rendering(layout, preview_dpi_for_width(layout, settings.preview_width_px))
        changes: list[str] = []
        for item in list(layout.items()):
            if isinstance(item, QgsLayoutItemLegend):
                self._apply_legend_readability(item, settings)
                linked = item.linkedMap()
                self._clean_legend_model(item, linked.layers() if linked else [])
                item.refresh()
                changes.append("légende")
            elif isinstance(item, QgsLayoutItemScaleBar):
                linked = item.linkedMap()
                try:
                    width = item.sizeWithUnits().width()
                except Exception:
                    width = 55.0
                self._configure_scale_bar(item, linked, settings, width)
                item.refresh()
                changes.append("barre d'échelle")
            elif isinstance(item, QgsLayoutItemLabel):
                identifier = (item.id() or "").casefold()
                target = settings.minimum_font_size_pt
                if "title" in identifier:
                    target = max(20.0, settings.minimum_font_size_pt * 2.0)
                elif "subtitle" in identifier:
                    target = max(11.5, settings.minimum_font_size_pt + 2.0)
                elif "source" in identifier or "footer" in identifier:
                    target = max(9.5, settings.minimum_font_size_pt)
                fmt = item.textFormat()
                if fmt.size() < target:
                    fmt.setSize(target)
                    fmt.setSizeUnit(render_points_unit())
                    item.setTextFormat(fmt)
                    item.refresh()
                    changes.append(f"texte {item.id() or 'sans identifiant'}")
        brand = layout.itemById("text_20_608")
        credits = layout.itemById("source-credits")
        if brand is not None and credits is not None:
            brand.setVisible(False)
            credits.attemptMove(QgsLayoutPoint(6.7, 202.0, layout_mm_unit()))
            credits.attemptResize(QgsLayoutSize(283.0, 6.0, layout_mm_unit()))
            fmt = credits.textFormat()
            fmt.setColor(QColor("#ffffff"))
            fmt.setSize(max(9.5, settings.minimum_font_size_pt))
            fmt.setSizeUnit(render_points_unit())
            credits.setTextFormat(fmt)
            credits.refresh()
            changes.append("pied de page")
        footer = layout.itemById("footer-text")
        if footer is not None and credits is not None:
            footer.attemptMove(QgsLayoutPoint(8.0, 191.5, layout_mm_unit()))
            footer.attemptResize(QgsLayoutSize(280.0, 8.0, layout_mm_unit()))
            credits.attemptMove(QgsLayoutPoint(8.0, 201.0, layout_mm_unit()))
            credits.attemptResize(QgsLayoutSize(280.0, 6.0, layout_mm_unit()))
            fmt = credits.textFormat()
            fmt.setColor(QColor("#ffffff"))
            fmt.setSize(max(9.0, settings.minimum_font_size_pt))
            fmt.setSizeUnit(render_points_unit())
            credits.setTextFormat(fmt)
            changes.append("crédits")
        for item in list(layout.items()):
            try:
                invalidate = getattr(item, "invalidateCache", None)
                if callable(invalidate):
                    invalidate()
            except Exception:
                pass
        try:
            invalidate = getattr(layout, "invalidateCachedRenders", None)
            if callable(invalidate):
                invalidate()
        except Exception:
            pass
        try:
            layout.refresh()
        except AttributeError:
            pass
        self.project.setDirty(True)
        return tuple(dict.fromkeys(changes))

    def _unique_layout_name(self, base: str) -> str:
        clean = " ".join(str(base).replace("\x00", "").split())[:120] or "Mise en page Cartomize"
        manager = self.project.layoutManager()
        if manager.layoutByName(clean) is None:
            return clean
        index = 2
        while manager.layoutByName(f"{clean} ({index})") is not None:
            index += 1
        return f"{clean} ({index})"


def _readable_font_size(planned: PlannedItem, settings: CartomizeSettings) -> float:
    raw_size = max(1.0, float(planned.style.get("fontSize", 12.0)))
    scaled = raw_size * 0.75 * (settings.text_scale_percent / 100.0)
    minimums = {
        "title": max(20.0, settings.minimum_font_size_pt * 2.0),
        "subtitle": max(11.5, settings.minimum_font_size_pt + 2.0),
        "text": settings.minimum_font_size_pt,
    }
    minimum = minimums.get(planned.kind, settings.minimum_font_size_pt)
    available_points = max(8.0, planned.height_mm * 72.0 / 25.4 * 0.84)
    return round(min(max(scaled, minimum), available_points), 2)

def _readable_layer_name(value: Any) -> str:
    text = str(value or "Couche").replace("_", " ").replace("-", " ")
    text = " ".join(text.split())
    return text[:120] or "Couche"


def _redundant_raster_heading(label: str) -> bool:
    normalized = " ".join(str(label or "").casefold().split())
    return normalized.startswith(("band ", "bande ")) and ":" in normalized


def _font_family(css_family: Any) -> str:
    first = str(css_family or "Noto Sans").split(",", 1)[0].strip().strip("'\"")
    return first[:100] or "Noto Sans"


def _nice_interval(value: float) -> float:
    """Arrondit un intervalle de grille selon la série cartographique 1/2/5."""
    if not math.isfinite(value) or value <= 0:
        return 1.0
    exponent = math.floor(math.log10(value))
    fraction = value / (10 ** exponent)
    if fraction <= 1:
        nice = 1
    elif fraction <= 2:
        nice = 2
    elif fraction <= 5:
        nice = 5
    else:
        nice = 10
    return float(nice * (10 ** exponent))
