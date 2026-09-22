"""Standalone cartographic pages rendered with Matplotlib, without a GIS GUI."""
from dataclasses import dataclass, field
from pathlib import Path
import math
import warnings

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.vrt import WarpedVRT
from pyproj import CRS, Transformer
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import ListedColormap, BoundaryNorm, Normalize
from matplotlib.patches import Patch, Rectangle
from matplotlib.lines import Line2D
from matplotlib.ticker import ScalarFormatter
from matplotlib import colormaps
import matplotlib.patheffects as path_effects

from ._validation import frame, output_path
from .templates import layout_plan


@dataclass
class Layer:
    """Layer settings independent of ArcGIS Pro and QGIS."""
    data: object
    name: str
    kind: str
    column: str | None = None
    labels: str | None = None
    color: str = "#56866c"
    cmap: str = "viridis"
    categorical: bool = False
    classes: dict = field(default_factory=dict)
    band: int = 1
    alpha: float = 1.0
    legend: bool = True
    style: dict = field(default_factory=dict)


def _extent(bounds):
    bounds = tuple(map(float, bounds))
    if len(bounds) != 4 or not np.isfinite(bounds).all() or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
        raise ValueError("extent must be finite (xmin, ymin, xmax, ymax) with positive width and height.")
    return bounds


class Map:
    """Compose maps and export PDF/PNG/SVG pages.

    Template coordinates are preserved from Cartomize ArcGIS Pro. Every frame
    may use its own extent, CRS and layers via set_frame(). Input data is copied.
    """

    def __init__(self, *, title="", subtitle="", credits="", crs=None,
                 format="A4", orientation="landscape", template=None):
        if format not in {"A4", "A3"} or orientation not in {"landscape", "portrait"}:
            raise ValueError("Use A4/A3 and landscape/portrait.")
        self.title, self.subtitle, self.credits = title, subtitle, credits
        self.crs = CRS.from_user_input(crs) if crs is not None else None
        self.layers: list[Layer] = []
        self.plan = layout_plan(template) if template else None
        width, height = (210, 297) if format == "A4" else (297, 420)
        if orientation == "landscape":
            width, height = height, width
        self.width, self.height = (self.plan.page_width_mm, self.plan.page_height_mm) if self.plan else (width, height)
        self.extent = None
        self.frames = {}
        self.tables, self.charts, self.texts = {}, {}, {}
        self.legend_enabled = self.scale_enabled = self.north_enabled = True

    @property
    def frame_ids(self):
        return [i.item_id for i in self.plan.map_items] if self.plan else ["main"]

    def add_layer(self, data, *, name=None, kind=None, column=None, labels=None,
                  color="#56866c", cmap="viridis", categorical=False, classes=None,
                  band=1, alpha=1.0, legend=True, **style):
        """Add vector data or a raster path; classes={code: (label, color)}.

        Use kind='raster' for raster formats without a .tif/.tiff/.vrt suffix.
        For vector layers, categorical defaults to true for nonnumeric fields.
        """
        if not 0 <= alpha <= 1:
            raise ValueError("alpha must be between zero and one.")
        if kind is None:
            kind = "raster" if isinstance(data, (str, Path)) and Path(data).suffix.lower() in {".tif", ".tiff", ".vrt", ".img"} else "vector"
        if kind not in {"raster", "vector"}:
            raise ValueError("kind must be raster or vector.")
        layer_name = name or (Path(data).stem if isinstance(data, (str, Path)) else f"Layer {len(self.layers)+1}")
        if layer_name in {l.name for l in self.layers}:
            raise ValueError("Each layer needs a unique name.")
        if kind == "vector":
            data = frame(data)
            for field_name in (column, labels):
                if field_name and field_name not in data.columns:
                    raise KeyError(field_name)
            if column and not pd.api.types.is_numeric_dtype(data[column]):
                categorical = True
            layer_crs = data.crs
        else:
            with rasterio.open(data) as src:
                if src.crs is None:
                    raise ValueError("Raster has no CRS.")
                if not isinstance(band, int) or not 1 <= band <= src.count:
                    raise ValueError("Invalid raster band.")
                layer_crs = src.crs
        if self.crs is None:
            self.crs = CRS.from_user_input(layer_crs)
        self.layers.append(Layer(data, layer_name, kind, column, labels, color, cmap,
                                 categorical, dict(classes or {}), band, alpha, legend, style))
        return self

    def set_extent(self, bounds):
        """Set the default bounds in the map CRS."""
        self.extent = _extent(bounds)
        return self

    def set_frame(self, frame_id, *, extent=None, layers=None, crs=None):
        if frame_id not in self.frame_ids:
            raise KeyError(f"Unknown frame {frame_id}; choose from {self.frame_ids}.")
        if layers is not None and set(layers) - {l.name for l in self.layers}:
            raise ValueError("A frame references unknown layer names.")
        self.frames[frame_id] = {"extent": _extent(extent) if extent is not None else None,
                                 "layers": list(layers) if layers is not None else None,
                                 "crs": CRS.from_user_input(crs) if crs is not None else None}
        return self

    def set_text(self, item_id, text):
        self.texts[item_id] = str(text)
        return self

    def set_table(self, item_id, data):
        self.tables[item_id] = pd.DataFrame(data)
        return self

    def set_chart(self, item_id, labels, values, *, color="#56866c"):
        values = list(values)
        labels = list(labels)
        if len(labels) != len(values) or not np.isfinite(values).all():
            raise ValueError("Chart labels and finite values must have equal lengths.")
        self.charts[item_id] = (labels, values, color)
        return self

    def add_legend(self, enabled=True):
        self.legend_enabled = enabled
        return self

    def add_scale_bar(self, enabled=True):
        self.scale_enabled = enabled
        return self

    def add_north_arrow(self, enabled=True):
        self.north_enabled = enabled
        return self

    def _axes(self, fig, box, **kwargs):
        x, y, w, h = box
        return fig.add_axes([x/self.width, 1-(y+h)/self.height, w/self.width, h/self.height], **kwargs)

    def render(self, *, dpi=150, max_raster_size=2048):
        """Return a Matplotlib Figure. Raster previews are bounded in memory.

        max_raster_size limits each raster display dimension, not processing.
        Increase it explicitly for large print exports if memory permits.
        """
        if not self.layers:
            raise ValueError("Add at least one layer before rendering.")
        if dpi <= 0 or max_raster_size < 1:
            raise ValueError("dpi and max_raster_size must be positive.")
        fig = Figure(figsize=(self.width/25.4, self.height/25.4), dpi=dpi, facecolor="white")
        FigureCanvasAgg(fig)
        frame_axes, frame_legends, frame_crs = {}, {}, {}
        if self.plan:
            map_items = [(i.item_id, (i.x_mm, i.y_mm, i.width_mm, i.height_mm)) for i in self.plan.map_items]
            fig.set_facecolor(self.plan.background_color)
        else:
            landscape = self.width > self.height
            map_items = [("main", (12, 38, self.width-82 if landscape else self.width-24,
                                    self.height-55 if landscape else self.height-99))]
        for ident, box in map_items:
            ax = self._axes(fig, box)
            config = self.frames.get(ident, {})
            crs = config.get("crs") or self.crs
            layers = [l for l in self.layers if config.get("layers") is None or l.name in config["layers"]]
            bounds = config.get("extent")
            if bounds is None and self.extent is not None:
                if crs == self.crs:
                    bounds = self.extent
                else:
                    bounds = Transformer.from_crs(self.crs, crs, always_xy=True).transform_bounds(*self.extent)
            handles = self._draw_layers(ax, layers, crs, bounds, max_raster_size)
            ax.tick_params(labelsize=6, colors="#54616a")
            ax.grid(alpha=.12, linewidth=.4)
            for spine in ax.spines.values():
                spine.set_color("#52636a"); spine.set_linewidth(.7)
            frame_axes[ident], frame_legends[ident], frame_crs[ident] = ax, handles, crs
        if self.plan:
            self._draw_template(fig, frame_axes, frame_legends, frame_crs)
        else:
            fig.text(12/self.width, 1-15/self.height, self.title, fontsize=17, weight="bold", color="#183f3e", va="top")
            fig.text(12/self.width, 1-27/self.height, self.subtitle, fontsize=9, color="#52636a", va="top")
            landscape = self.width > self.height
            legend_box = (self.width-61, 42, 51, self.height-70) if landscape else (12, self.height-52, self.width-24, 31)
            if self.legend_enabled:
                self._legend(fig, legend_box, frame_legends["main"])
            if self.scale_enabled:
                self._scale(frame_axes["main"], frame_crs["main"])
            if self.north_enabled:
                self._north(frame_axes["main"], frame_crs["main"])
            fig.text(12/self.width, 8/self.height, self.credits or str(self.crs), fontsize=7, color="#52636a", va="bottom")
        return fig

    def _draw_layers(self, ax, layers, crs, bounds, max_size):
        legends, annotations = [], []
        automatic_extent = bounds is None
        initial_position = ax.get_position(original=True)
        frame_ratio = (initial_position.width*ax.figure.bbox.width /
                       (initial_position.height*ax.figure.bbox.height))
        if bounds is None:
            all_bounds = []
            for layer in layers:
                if layer.kind == "vector":
                    candidate = layer.data.to_crs(crs).total_bounds
                else:
                    with rasterio.open(layer.data) as src:
                        candidate = Transformer.from_crs(src.crs, crs, always_xy=True).transform_bounds(*src.bounds)
                if np.isfinite(candidate).all():
                    all_bounds.append(candidate)
            if all_bounds:
                all_bounds = np.array(all_bounds)
                x0, y0 = all_bounds[:, :2].min(axis=0)
                x1, y1 = all_bounds[:, 2:].max(axis=0)
                # Avoid a zero-size map for one point or a straight line.
                minimum = .01 if crs.is_geographic else 100
                dx, dy = max(x1-x0, minimum)*.04, max(y1-y0, minimum)*.04
                bounds = (x0-dx, y0-dy, x1+dx, y1+dy)
        for layer in layers:
            if layer.kind == "vector":
                data = layer.data.to_crs(crs)
                present = data.geometry.notna() & ~data.geometry.is_empty
                data = data.loc[present]
                if data.empty:
                    continue
                style = dict(alpha=layer.alpha, aspect=None)
                kinds = set(data.geom_type)
                point = all("Point" in kind for kind in kinds)
                line = all("Line" in kind for kind in kinds)
                style.update({"markersize": 22} if point else {"linewidth": 1.1} if line else {"edgecolor": "#ffffff", "linewidth": .5})
                style.update(layer.style)
                entries = []
                if layer.column and layer.categorical:
                    categories = sorted(data[layer.column].dropna().unique(), key=str)
                    palette = colormaps[layer.cmap].resampled(max(1, len(categories)))
                    color_map = {c: layer.classes.get(c, (str(c), palette(i)))[1] for i, c in enumerate(categories)}
                    colors = [color_map.get(value, "#d9dfe1") for value in data[layer.column]]
                    data.plot(ax=ax, color=colors, **style)
                    entries = [(layer.classes.get(c, (str(c), None))[0], color_map[c]) for c in categories]
                elif layer.column:
                    values = pd.to_numeric(data[layer.column], errors="coerce")
                    valid = values[np.isfinite(values)]
                    if valid.empty:
                        raise ValueError(f"No finite values for {layer.column}.")
                    norm = Normalize(float(valid.min()), float(valid.max()))
                    data.plot(ax=ax, column=layer.column, cmap=layer.cmap, norm=norm, **style)
                    if layer.legend:
                        legends.append(("continuous", layer.name, colormaps[layer.cmap], norm))
                else:
                    data.plot(ax=ax, color=layer.color, **style)
                    entries = [(layer.name, layer.color)]
                if layer.legend:
                    for label, color in entries:
                        handle = Line2D([], [], marker="o", linestyle="none", color=color, markersize=5, label=str(label)) if point else Line2D([], [], color=color, label=str(label)) if line else Patch(facecolor=color, edgecolor="#64706b", linewidth=.3, label=str(label))
                        legends.append(("discrete", handle))
                if layer.labels:
                    for geometry, text in zip(data.geometry, data[layer.labels]):
                        if pd.isna(text):
                            continue
                        p = geometry.representative_point()
                        annotations.append((p.x, p.y, str(text)))
            else:
                with rasterio.open(layer.data) as src:
                    with WarpedVRT(src, crs=crs, dtype="float64", nodata=np.nan) as vrt:
                        ratio = min(1, max_size/max(vrt.width, vrt.height))
                        data = np.ma.masked_invalid(vrt.read(layer.band, masked=True,
                                     out_shape=(max(1, int(vrt.height*ratio)), max(1, int(vrt.width*ratio)))))
                        extent = (vrt.bounds.left, vrt.bounds.right, vrt.bounds.bottom, vrt.bounds.top)
                if layer.classes:
                    keys = sorted(layer.classes)
                    display = np.ma.masked_all(data.shape, dtype=float)
                    for i, key in enumerate(keys):
                        display[(data.data == key) & ~np.ma.getmaskarray(data)] = i
                    valid_unmapped = ~np.ma.getmaskarray(data) & ~np.isin(data.data, keys)
                    if valid_unmapped.any():
                        raise ValueError(f"Layer {layer.name}: class labels/colors are missing for observed values.")
                    cmap = ListedColormap([layer.classes[k][1] for k in keys])
                    norm = BoundaryNorm(np.arange(len(keys)+1)-.5, len(keys))
                    ax.imshow(display, extent=extent, origin="upper", cmap=cmap, norm=norm, alpha=layer.alpha, interpolation="nearest")
                    if layer.legend:
                        legends.extend(("discrete", Patch(facecolor=layer.classes[k][1], label=str(layer.classes[k][0]))) for k in keys)
                else:
                    cmap = colormaps[layer.cmap]
                    artist = ax.imshow(data, extent=extent, origin="upper", cmap=cmap, alpha=layer.alpha, interpolation="nearest")
                    if layer.legend:
                        legends.append(("continuous", layer.name, cmap, artist.norm))
        if bounds and automatic_extent:
            x0, y0, x1, y1 = bounds
            cx, cy = (x0+x1)/2, (y0+y1)/2
            aspect = 1/max(.01, math.cos(math.radians(cy))) if crs.is_geographic else 1
            # Expand the automatically selected extent to fill the template
            # frame at the correct aspect, without stretching geography.
            target_ratio = frame_ratio*aspect
            width, height = x1-x0, y1-y0
            if width/height < target_ratio:
                width = height*target_ratio
            else:
                height = width/target_ratio
            bounds = (cx-width/2, cy-height/2, cx+width/2, cy+height/2)
        if bounds:
            ax.set_xlim(bounds[0], bounds[2]); ax.set_ylim(bounds[1], bounds[3])
        else:
            ax.margins(.04)
        if crs.is_geographic:
            lat = np.mean(ax.get_ylim())
            ax.set_aspect(1/max(.01, math.cos(math.radians(lat))))
        else:
            ax.set_aspect("equal", adjustable="box")
        ax.set_xlim(ax.get_xlim()); ax.set_ylim(ax.get_ylim())
        ax.xaxis.set_major_formatter(ScalarFormatter(useOffset=False))
        ax.yaxis.set_major_formatter(ScalarFormatter(useOffset=False))
        ax.ticklabel_format(style="plain", axis="both")
        # Suppress label overlaps at the current figure resolution.
        ax.figure.canvas.draw()
        occupied = []
        xlim, ylim = ax.get_xlim(), ax.get_ylim()
        for x, y, label in annotations:
            if not (xlim[0] <= x <= xlim[1] and ylim[0] <= y <= ylim[1]):
                continue
            text = ax.annotate(label, (x, y), xytext=(4, 4), textcoords="offset points",
                               fontsize=7, color="#182d35", clip_on=True,
                               path_effects=[path_effects.withStroke(linewidth=2, foreground="white")])
            box = text.get_window_extent(ax.figure.canvas.get_renderer()).expanded(1.08, 1.12)
            if any(box.overlaps(previous) for previous in occupied):
                text.remove()
            else:
                occupied.append(box)
        return legends

    def _legend(self, fig, box, entries):
        ax = self._axes(fig, box)
        ax.axis("off")
        handles, seen, continuous = [], set(), []
        for entry in entries:
            if entry[0] == "discrete":
                handle = entry[1]
                key = (handle.get_label(), str(handle.get_facecolor() if isinstance(handle, Patch) else handle.get_color()))
                if key not in seen:
                    handles.append(handle); seen.add(key)
            else:
                continuous.append(entry)
        discrete_height = min(.70 if continuous else .95, .09*len(handles)+.1)
        if handles:
            fontsize = max(5, min(8, box[3]*2.8346*discrete_height/(len(handles)*1.7)))
            ax.legend(handles=handles, loc="upper left", frameon=False, fontsize=fontsize,
                      borderaxespad=0, title="Légende", title_fontsize=9)
        start = discrete_height if handles else .06
        for index, (_, name, cmap, norm) in enumerate(continuous):
            step = (1-start)/max(1, len(continuous))
            bar = ax.inset_axes([.02, 1-start-(index+1)*step+.05, .90, min(.08, step*.25)])
            fig.colorbar(__import__("matplotlib").cm.ScalarMappable(norm=norm, cmap=cmap), cax=bar, orientation="horizontal")
            bar.tick_params(labelsize=6)
            bar.set_title(name, fontsize=7, loc="left", pad=4)

    def _north(self, ax, crs, position=(.91, .85)):
        # Project a geodesic toward true north at the frame centre.
        x, y = np.mean(ax.get_xlim()), np.mean(ax.get_ylim())
        to_geo = Transformer.from_crs(crs, 4326, always_xy=True)
        from_geo = Transformer.from_crs(4326, crs, always_xy=True)
        lon, lat = to_geo.transform(x, y)
        north_lon, north_lat, _ = CRS.from_epsg(4326).get_geod().fwd(lon, lat, 0, 1000)
        nx, ny = from_geo.transform(north_lon, north_lat)
        delta = ax.transData.transform((nx, ny))-ax.transData.transform((x, y))
        if not np.isfinite(delta).all() or np.linalg.norm(delta) == 0:
            warnings.warn("Cannot determine true north for this frame.", stacklevel=2)
            return
        delta = delta/np.linalg.norm(delta)
        # Convert a fixed display-length arrow to axes units.
        pixels = 22*ax.figure.dpi/72
        dx, dy = delta[0]*pixels/ax.bbox.width, delta[1]*pixels/ax.bbox.height
        tip = (position[0]+dx, position[1]+dy)
        arrow = ax.annotate("", xy=tip, xytext=position, annotation_clip=False,
                    xycoords="axes fraction", textcoords="axes fraction",
                    arrowprops={"arrowstyle": "-|>", "color": "#182d35", "lw": 1.4})
        arrow.arrow_patch.set_path_effects([path_effects.withStroke(linewidth=3, foreground="white")])
        ax.annotate("N", tip, xycoords="axes fraction", xytext=(0, 3), textcoords="offset points",
                    ha="center", va="bottom", fontsize=9, weight="bold", annotation_clip=False,
                    bbox={"facecolor": "white", "alpha": .8, "edgecolor": "none", "pad": 1})

    def _scale(self, ax, crs, position=(.06, .06), length_fraction=.22):
        xmin, xmax = ax.get_xlim(); ymin, ymax = ax.get_ylim()
        x, y = xmin+position[0]*(xmax-xmin), ymin+position[1]*(ymax-ymin)
        target = length_fraction*(xmax-xmin)
        transform = Transformer.from_crs(crs, 4326, always_xy=True)
        lon1, lat1 = transform.transform(x, y)
        lon2, lat2 = transform.transform(x+target, y)
        geod = CRS.from_epsg(4326).get_geod()
        distance = geod.inv(lon1, lat1, lon2, lat2)[2]
        if not np.isfinite(distance) or distance <= 0:
            return
        magnitude = 10**math.floor(math.log10(distance))
        nice = max(v*magnitude for v in (1, 2, 5, 10) if v*magnitude <= distance)
        # Solve the horizontal end position for the actual geodesic distance.
        low, high = 0., target
        for _ in range(35):
            mid = (low+high)/2
            lon, lat = transform.transform(x+mid, y)
            if geod.inv(lon1, lat1, lon, lat)[2] < nice:
                low = mid
            else:
                high = mid
        end = x+(low+high)/2
        line, = ax.plot([x, end], [y, y], color="#182d35", linewidth=2, marker="|", markersize=7, clip_on=False)
        line.set_path_effects([path_effects.withStroke(linewidth=4, foreground="white")])
        label = f"{nice/1000:g} km" if nice >= 1000 else f"{nice:g} m"
        ax.annotate(label, ((x+end)/2, y), xytext=(0, 5), textcoords="offset points", ha="center", fontsize=7,
                    bbox={"facecolor": "white", "alpha": .85, "edgecolor": "none", "pad": 1}, annotation_clip=False)

    def _draw_template(self, fig, axes, legends, crss):
        primary = next((i.item_id for i in self.plan.map_items if i.content.get("role") == "main"), self.plan.primary_map_id)
        for item in sorted(self.plan.items, key=lambda i: i.z_index):
            box = (item.x_mm, item.y_mm, item.width_mm, item.height_mm)
            linked = item.linked_map_id or primary
            if item.kind in {"title", "subtitle", "text"}:
                text = self.texts.get(item.item_id)
                if text is None:
                    text = self.title if item.kind == "title" else self.subtitle if item.kind == "subtitle" else self.credits if item.item_id in {"credits", "sources"} else item.content.get("text", "")
                ax = self._axes(fig, box); ax.axis("off")
                ax.text(0, 1, text, fontsize=max(6, float(item.style.get("fontSize", 9))),
                        va="top", color=item.style.get("fill", "#182d35"),
                        weight=item.style.get("fontWeight", "normal"), wrap=True, clip_on=True)
            elif item.kind == "shape":
                rectangle = Rectangle((item.x_mm/self.width, 1-(item.y_mm+item.height_mm)/self.height),
                                      item.width_mm/self.width, item.height_mm/self.height,
                                      transform=fig.transFigure, facecolor=item.style.get("fill", "none"),
                                      edgecolor=item.style.get("stroke", "none"), linewidth=float(item.style.get("strokeWidth", .5)),
                                      zorder=-1)
                fig.add_artist(rectangle)
            elif item.kind == "legend" and self.legend_enabled:
                self._legend(fig, box, legends[linked])
            elif item.kind in {"scale_bar", "north_arrow"}:
                # Keep the linked map's display/data transform so the printed
                # scale has the same physical scale as that map frame.
                original = axes[linked]
                rect = original.get_position()
                page_x = (item.x_mm+item.width_mm*.1)/self.width
                page_y = 1-(item.y_mm+item.height_mm*.75)/self.height
                position = ((page_x-rect.x0)/rect.width, (page_y-rect.y0)/rect.height)
                if item.kind == "scale_bar" and self.scale_enabled:
                    self._scale(original, crss[linked], position=position,
                                length_fraction=item.width_mm*.8/self.width/rect.width)
                elif item.kind == "north_arrow" and self.north_enabled:
                    self._north(original, crss[linked], position=position)
            elif item.kind == "table" and item.item_id in self.tables:
                ax = self._axes(fig, box); ax.axis("off")
                table = self.tables[item.item_id]
                artist = ax.table(cellText=table.astype(str).values, colLabels=list(table.columns), loc="center", bbox=[0, 0, 1, 1])
                artist.auto_set_font_size(False); artist.set_fontsize(7)
            elif item.kind == "chart" and item.item_id in self.charts:
                ax = self._axes(fig, box)
                labels, values, color = self.charts[item.item_id]
                ax.bar(labels, values, color=color); ax.tick_params(labelsize=6)
                ax.set_title(item.content.get("title", ""), fontsize=8)

    def export(self, path, *, dpi=300, overwrite=False, max_raster_size=2048):
        """Save an exact-size page. Existing files require overwrite=True."""
        path = output_path(path, overwrite)
        if path.suffix.lower() not in {".pdf", ".png", ".svg"}:
            raise ValueError("Supported exports: .pdf, .png, .svg.")
        fig = self.render(dpi=dpi, max_raster_size=max_raster_size)
        try:
            fig.savefig(path, dpi=dpi, facecolor=fig.get_facecolor())
        finally:
            fig.clear()
        return path
