"""Standalone cartographic pages rendered with Matplotlib, without a GIS GUI."""
from dataclasses import dataclass, field
from pathlib import Path
import math
import warnings
import os
import tempfile

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.vrt import WarpedVRT
from pyproj import CRS, Transformer
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import ListedColormap, BoundaryNorm, Normalize, LinearSegmentedColormap, is_color_like
from matplotlib.patches import Patch, Rectangle
from matplotlib.lines import Line2D
from matplotlib.ticker import ScalarFormatter
from matplotlib import colormaps
import matplotlib.patheffects as path_effects

from ._validation import frame, output_path
from .templates import layout_plan
from .composition import ORDER, COLORS, infer_role, default_label
from .color import read_rgb, resolve_rgb


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
    role: str = "thematic"
    zorder: float | None = None
    rgb: str | tuple | None = None
    percentiles: tuple = (2,98)
    gamma: float = 1.0
    ranges: list = field(default_factory=list)
    category_styles: dict = field(default_factory=dict)
    symbol_layers: list = field(default_factory=list)
    hidden_categories: list = field(default_factory=list)
    raster_ramp: dict = field(default_factory=dict)
    raster_range: tuple | None = None


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
                 format="A4", orientation="landscape", template=None, auto_order=True):
        if format not in {"A4", "A3"} or orientation not in {"landscape", "portrait"}:
            raise ValueError("Use A4/A3 and landscape/portrait.")
        self.title, self.subtitle, self.credits = title, subtitle, credits
        self.crs = CRS.from_user_input(crs) if crs is not None else None
        self.layers: list[Layer] = []
        self._sources=[]
        self.auto_order = bool(auto_order)
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
                  color=None, cmap="viridis", categorical=False, classes=None,
                  band=1, alpha=1.0, legend=None, role=None, zorder=None,
                  rgb=None, percentiles=(2,98), gamma=1.0, ranges=(),category_styles=None,
                  symbol_layers=(),hidden_categories=(),raster_ramp=None,raster_range=None,**style):
        """Add vector data or a raster path; classes={code: (label, color)}.

        Use kind='raster' for raster formats without a .tif/.tiff/.vrt suffix.
        For vector layers, categorical defaults to true for nonnumeric fields.
        """
        if not 0 <= alpha <= 1:
            raise ValueError("alpha must be between zero and one.")
        ranges=[dict(r) for r in ranges]
        for i,r in enumerate(ranges):
            if not np.isfinite([r['lower'],r['upper']]).all() or r['lower']>r['upper'] or not is_color_like(r['color']):raise ValueError('Classe graduée invalide.')
            if i and r['lower']<ranges[i-1]['upper']:raise ValueError('Les classes graduées se chevauchent ou ne sont pas ordonnées.')
        if ranges and (not column or classes):raise ValueError('Les classes graduées nécessitent un champ numérique et excluent les catégories.')
        if raster_range is not None and (len(raster_range)!=2 or not np.isfinite(raster_range).all() or raster_range[0]>=raster_range[1]):raise ValueError('Bornes du rendu raster invalides.')
        if kind is None:
            kind = "raster" if isinstance(data, (str, Path)) and Path(data).suffix.lower() in {".tif", ".tiff", ".vrt", ".img", ".jp2"} else "vector"
        if kind not in {"raster", "vector"}:
            raise ValueError("kind must be raster or vector.")
        source=Path(data).expanduser().resolve() if isinstance(data,(str,Path)) else None
        layer_name = name or (Path(data).stem if isinstance(data, (str, Path)) else f"Layer {len(self.layers)+1}")
        if layer_name in {l.name for l in self.layers}:
            raise ValueError("Each layer needs a unique name.")
        if kind == "vector":
            if rgb is not None:
                raise ValueError("RGB compositions require a raster layer.")
            data = frame(data)
            if labels == "auto":
                labels = default_label(data)
            for field_name in (column, labels):
                if field_name and field_name not in data.columns:
                    raise KeyError(field_name)
            if column and not pd.api.types.is_numeric_dtype(data[column]):
                categorical = True
            if classes and column:categorical=True
            if ranges and not pd.api.types.is_numeric_dtype(data[column]):raise ValueError('Champ numérique requis pour les classes graduées.')
            layer_crs = data.crs
        else:
            with rasterio.open(data) as src:
                if src.crs is None:
                    raise ValueError("Raster has no CRS.")
                if not isinstance(band, int) or not 1 <= band <= src.count:
                    raise ValueError("Invalid raster band.")
                if rgb is None and src.count >= 3 and src.dtypes[:3] == ("uint8",)*3 and tuple(c.name for c in src.colorinterp[:3]) == ("red","green","blue"):
                    rgb = "native"
                if rgb is not None:
                    resolve_rgb(src,rgb)
                    if classes or column:
                        raise ValueError("RGB display cannot also use categorical or single-band styling.")
                layer_crs = src.crs
        if classes and (kind=='raster' or column and pd.api.types.is_numeric_dtype(data[column])):
            converted={float(k):v for k,v in classes.items()}
            if len(converted)!=len(classes) or not np.isfinite(list(converted)).all():raise ValueError('Codes numériques de nomenclature invalides ou dupliqués.')
            classes=converted
            if category_styles:category_styles={float(k):v for k,v in category_styles.items()}
            hidden_categories=[float(k) for k in hidden_categories]
        if raster_ramp:
            items=raster_ramp.get('items',[])
            if raster_ramp.get('type') not in {'linear','discrete','exact'} or not items or any(not np.isfinite(i['value']) or not is_color_like(i['color']) for i in items):raise ValueError('Rampe raster invalide.')
            if any(a['value']>=b['value'] for a,b in zip(items,items[1:])):raise ValueError('Les valeurs de rampe doivent être strictement croissantes.')
            if raster_ramp['type']=='linear' and len(items)<2:raise ValueError('Deux couleurs au moins pour une interpolation.')
        role = role or infer_role(layer_name,kind,data.geom_type.dropna() if kind=="vector" else (),column=column,classes=classes,rgb=rgb)
        if role not in ORDER:
            raise ValueError(f"Unknown cartographic role. Choose from {list(ORDER)}.")
        if zorder is not None and not np.isfinite(zorder):
            raise ValueError("zorder must be finite.")
        color = color if color is not None else COLORS[role]
        if kind=="vector" and role=="localities" and labels is None:
            labels=default_label(data)
        if kind=="vector" and role=="boundaries" and not column:
            style.setdefault("edgecolor",color)
            style.setdefault("linewidth",1.1)
            if data.geom_type.dropna().str.contains("Polygon").all():
                color="none"
        if kind=="vector" and role=="roads":
            style.setdefault("linewidth",1.1)
            style.setdefault("path_effects",[path_effects.withStroke(linewidth=2.2,foreground="#ffffff")])
        if self.crs is None:
            self.crs = CRS.from_user_input(layer_crs)
        self.layers.append(Layer(data=data,name=layer_name,kind=kind,column=column,labels=labels,color=color,cmap=cmap,
                                 categorical=categorical,classes=dict(classes or {}),band=band,alpha=alpha,
                                 legend=(rgb is None) if legend is None else legend,style=style,role=role,zorder=zorder,
                                 rgb=rgb,percentiles=tuple(percentiles),gamma=gamma,ranges=ranges,
                                 category_styles=dict(category_styles or {}),symbol_layers=list(symbol_layers),hidden_categories=list(hidden_categories),
                                 raster_ramp=dict(raster_ramp or {}),raster_range=tuple(raster_range) if raster_range else None))
        if source is not None:self._sources.append(source)
        return self

    def layer_plan(self):
        """Explain the effective layer order from bottom to top."""
        result=[{"name":l.name,"kind":l.kind,"role":l.role,"labels":l.labels,
                 "zorder":l.zorder if l.zorder is not None else ORDER[l.role] if self.auto_order else i,
                 "insertion_index":i} for i,l in enumerate(self.layers)]
        return sorted(result,key=lambda r:(r["zorder"],r["insertion_index"]))

    def add_layers(self,layers):
        for item in layers:
            self.add_layer(**item) if isinstance(item,dict) else self.add_layer(item)
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
        self._check_item(item_id,{'title','subtitle','text'})
        self.texts[item_id] = str(text)
        return self

    def set_table(self, item_id, data):
        self._check_item(item_id,{'table'})
        self.tables[item_id] = pd.DataFrame(data)
        return self

    def set_chart(self, item_id, labels, values, *, color="#56866c"):
        self._check_item(item_id,{'chart'})
        values = list(values)
        labels = list(labels)
        if len(labels) != len(values) or not np.isfinite(values).all():
            raise ValueError("Chart labels and finite values must have equal lengths.")
        self.charts[item_id] = (labels, values, color)
        return self

    def _check_item(self,item_id,kinds):
        if self.plan is None or not any(i.item_id==item_id and i.kind in kinds for i in self.plan.items):
            raise KeyError(f'No matching layout element: {item_id}')

    def audit(self,*,visual=False):
        """Technical checks before export; not a certification of map accuracy."""
        from .quality import audit_map
        report=audit_map(self)
        if visual and report['valid']:
            fig=self.render(dpi=100)
            try:
                for item in self.render_diagnostics.get('text',[]):
                    if not item['fitted']:report['issues'].append(dict(severity='error',code='text_overflow',message='Texte trop long : '+item.get('id',''),layer=None))
                for item in self.render_diagnostics.get('labels',[]):
                    if item['omitted']:report['issues'].append(dict(severity='warning',code='labels_omitted',message=f"{len(item['omitted'])} étiquettes sans emplacement libre.",layer=None))
                report['render']=self.render_diagnostics;report['valid']=not any(i['severity']=='error' for i in report['issues'])
            finally:fig.clear()
        return report

    def save(self,path,*,portable=False,overwrite=False):
        from .session import save_map
        return save_map(self,path,portable=portable,overwrite=overwrite)

    @classmethod
    def load(cls,path,**options):
        from .session import load_map
        return load_map(path,**options)

    def set_item(self,item_id,**changes):
        """Edit an existing template item without changing the bundled template."""
        from dataclasses import replace
        if self.plan is None:raise ValueError('Choisir une maquette pour modifier ses éléments.')
        allowed={'x_mm','y_mm','width_mm','height_mm','rotation','z_index','style','content','linked_map_id'}
        if set(changes)-allowed:raise ValueError('Propriété de mise en page inconnue.')
        original=next((i for i in self.plan.items if i.item_id==item_id),None)
        if original is None:raise KeyError(item_id)
        if 'rotation' in changes and changes['rotation']!=original.rotation and original.kind not in {'title','subtitle','text'}:raise ValueError('La rotation éditable concerne les éléments textuels.')
        if 'z_index' in changes and changes['z_index']!=original.z_index and original.kind in {'scale_bar','north_arrow'}:raise ValueError('L’échelle et le nord restent associés à leur cadre cartographique.')
        updated=replace(original,**changes)
        if not np.isfinite([updated.x_mm,updated.y_mm,updated.width_mm,updated.height_mm,updated.rotation,updated.z_index]).all():raise ValueError('Les dimensions doivent être finies.')
        if min(updated.x_mm,updated.y_mm)<0 or min(updated.width_mm,updated.height_mm)<=0 or updated.x_mm+updated.width_mm>self.width+.001 or updated.y_mm+updated.height_mm>self.height+.001:
            raise ValueError('L’élément doit tenir dans la page avec des dimensions positives.')
        if updated.linked_map_id and updated.linked_map_id not in self.frame_ids:raise ValueError('Cadre associé inconnu.')
        self.plan=replace(self.plan,items=tuple(updated if i.item_id==item_id else i for i in self.plan.items));return self

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
        self.render_diagnostics={"text":[],"labels":[]}
        frame_axes, frame_legends, frame_crs = {}, {}, {}
        if self.plan:
            map_items = [(i.item_id, (i.x_mm, i.y_mm, i.width_mm, i.height_mm)) for i in self.plan.map_items]
            fig.set_facecolor(self.plan.background_color)
        else:
            landscape = self.width > self.height
            map_items = [("main", (16, 38, self.width-86 if landscape else self.width-28,
                                    self.height-55 if landscape else self.height-99))]
        for ident, box in map_items:
            ax = self._axes(fig, box)
            if self.plan:ax.set_zorder(next(i.z_index for i in self.plan.map_items if i.item_id==ident))
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
            if self.plan and ident!=self.plan.primary_map_id and (box[2]<90 or box[3]<55):
                ax.tick_params(labelbottom=False,labelleft=False)
            ax.grid(alpha=.12, linewidth=.4)
            for spine in ax.spines.values():
                spine.set_color("#52636a"); spine.set_linewidth(.7)
            frame_axes[ident], frame_legends[ident], frame_crs[ident] = ax, handles, crs
        if self.plan:
            self._draw_template(fig, frame_axes, frame_legends, frame_crs)
        else:
            from .typography import fit_text
            for ident,text,box,size,weight in [("title",self.title,(12,9,self.width-24,16),17,"bold"),("subtitle",self.subtitle,(12,26,self.width-24,10),9,"normal")]:
                text_ax=self._axes(fig,box);text_ax.axis("off");_,record=fit_text(text_ax,text,fontsize=size,weight=weight)
                self.render_diagnostics["text"].append(dict(record,id=ident))
            landscape = self.width > self.height
            legend_box = (self.width-61, 42, 51, self.height-70) if landscape else (12, self.height-52, self.width-24, 31)
            if self.legend_enabled:
                self._legend(fig, legend_box, frame_legends["main"])
            if self.scale_enabled:
                self._scale(frame_axes["main"], frame_crs["main"])
            if self.north_enabled:
                self._north(frame_axes["main"], frame_crs["main"])
            text_ax=self._axes(fig,(12,self.height-11,self.width-24,9));text_ax.axis("off")
            _,record=fit_text(text_ax,self.credits or (':'.join(self.crs.to_authority()) if self.crs.to_authority() else self.crs.name),fontsize=7)
            self.render_diagnostics["text"].append(dict(record,id="credits"))
        return fig

    def _draw_layers(self, ax, layers, crs, bounds, max_size):
        legends, annotations, label_obstacles = [], [], []
        priorities={r["name"]:r["zorder"] for r in self.layer_plan()}
        layers=sorted(layers,key=lambda l:priorities[l.name])
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
                if layer.column and layer.hidden_categories:data=data.loc[~data[layer.column].isin(layer.hidden_categories)]
                if data.empty:
                    continue
                style = dict(alpha=layer.alpha, aspect=None,zorder=priorities[layer.name])
                kinds = set(data.geom_type)
                point = all("Point" in kind for kind in kinds)
                line = all("Line" in kind for kind in kinds)
                style.update({"markersize": 22} if point else {"linewidth": 1.1} if line else {"edgecolor": "#ffffff", "linewidth": .5})
                style.update(layer.style)
                def draw_features(features,color,symbol=None):
                    if features.empty:return
                    symbol=dict(symbol or {});components=symbol.pop('symbol_layers',None) or layer.symbol_layers or [{}]
                    for component in components:
                        settings={**style,**symbol,**component};ink=settings.pop('color',color)
                        settings['alpha']=layer.alpha*float(symbol.get('alpha',1))*float(component.get('alpha',1))
                        features.plot(ax=ax,color=ink,**settings)
                if point:
                    radius=max(2,math.sqrt(float(style.get('markersize',22)))/2+1)
                    for geometry in data.geometry:
                        for pt in geometry.geoms if geometry.geom_type=='MultiPoint' else [geometry]:label_obstacles.append((pt.x,pt.y,radius))
                entries = []
                if layer.ranges:
                    values=pd.to_numeric(data[layer.column],errors='coerce');assigned=np.zeros(len(data),dtype=bool)
                    visible=np.zeros(len(data),dtype=bool)
                    for i,r in enumerate(layer.ranges):
                        selected=np.asarray(values.between(r['lower'],r['upper']))&~assigned;assigned|=selected
                        if not r.get('visible',True):continue
                        visible|=selected;symbol=r.get('style',{});draw_features(data.loc[selected],r['color'],symbol)
                        entries.append((r.get('label',str(r['upper'])),r['color'],symbol))
                    data=data.loc[visible]
                elif layer.column and layer.categorical:
                    categories = sorted(data[layer.column].dropna().unique(), key=str)
                    palette = colormaps[layer.cmap].resampled(max(1, len(categories)))
                    color_map = {c: layer.classes.get(c, (str(c), palette(i)))[1] for i, c in enumerate(categories)}
                    colors = [color_map.get(value, "#d9dfe1") for value in data[layer.column]]
                    if layer.category_styles:
                        for c in categories:draw_features(data.loc[data[layer.column]==c],color_map[c],layer.category_styles.get(c,{}))
                    else:draw_features(data,colors)
                    entries = [(layer.classes.get(c, (str(c), None))[0], color_map[c],layer.category_styles.get(c,{})) for c in categories]
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
                    draw_features(data,layer.color)
                    entries = [(layer.name, layer.color,{})]
                if layer.legend:
                    for label, color, symbol in entries:
                        legend_style={**style,**symbol};legend_style.update((symbol.get('symbol_layers') or layer.symbol_layers or [{}])[-1])
                        ink=legend_style.get('color',color)
                        handle = Line2D([], [], marker=legend_style.get('marker','o'), linestyle="none", color=ink, markersize=math.sqrt(legend_style.get('markersize',25)), label=str(label)) if point else Line2D([], [], color=ink,linewidth=legend_style.get('linewidth',1.1),linestyle=legend_style.get('linestyle','-'),label=str(label)) if line else Patch(facecolor=ink, edgecolor=legend_style.get("edgecolor","#64706b"), linewidth=max(.3,legend_style.get("linewidth",.3)), label=str(label))
                        legends.append(("discrete", handle))
                if layer.labels:
                    for geometry, text in zip(data.geometry, data[layer.labels]):
                        if pd.isna(text):
                            continue
                        p = geometry.representative_point()
                        annotations.append((p.x, p.y, str(text)))
            else:
                if layer.rgb is not None:
                    rgba,extent,_=read_rgb(layer.data,bands=layer.rgb,crs=crs,max_size=max_size,
                                          percentiles=layer.percentiles,gamma=layer.gamma)
                    ax.imshow(rgba,extent=extent,origin="upper",alpha=layer.alpha,interpolation="nearest",zorder=priorities[layer.name])
                    if layer.legend:
                        legends.append(("discrete",Patch(facecolor="#c6d2ca",label=layer.name)))
                    continue
                with rasterio.open(layer.data) as src:
                    with WarpedVRT(src, crs=crs, dtype="float64", nodata=np.nan, UNIFIED_SRC_NODATA="NO") as vrt:
                        ratio = min(1, max_size/max(vrt.width, vrt.height))
                        data = np.ma.masked_invalid(vrt.read(layer.band, masked=True,
                                     out_shape=(max(1, int(vrt.height*ratio)), max(1, int(vrt.width*ratio)))))
                        extent = (vrt.bounds.left, vrt.bounds.right, vrt.bounds.bottom, vrt.bounds.top)
                if layer.raster_ramp:
                    ramp=layer.raster_ramp;items=ramp['items'];stops=np.array([i['value'] for i in items]);colors=[i['color'] for i in items]
                    if ramp['type']=='linear':
                        norm=Normalize(stops[0],stops[-1]);cmap=LinearSegmentedColormap.from_list('cartomize',list(zip((stops-stops[0])/(stops[-1]-stops[0]),colors)))
                        display=np.ma.masked_where((data<stops[0])|(data>stops[-1]),data) if ramp.get('clip') else data
                        if layer.legend:legends.append(('continuous',layer.name,cmap,norm))
                    else:
                        indices=np.searchsorted(stops,data.data,side='left');mask=np.ma.getmaskarray(data)|(indices>=len(stops))
                        if ramp['type']=='exact':mask|=stops[np.minimum(indices,len(stops)-1)]!=data.data
                        if ramp.get('clip'):mask|=data.data<stops[0]
                        display=np.ma.array(indices,mask=mask);cmap=ListedColormap(colors);norm=BoundaryNorm(np.arange(len(items)+1)-.5,len(items))
                        if layer.legend:legends.extend(('discrete',Patch(facecolor=i['color'],label=i.get('label',str(i['value'])))) for i in items)
                    ax.imshow(display,extent=extent,origin='upper',cmap=cmap,norm=norm,alpha=layer.alpha,interpolation='nearest',zorder=priorities[layer.name])
                elif layer.classes:
                    keys = sorted(layer.classes)
                    display = np.ma.masked_all(data.shape, dtype=float)
                    for i, key in enumerate(keys):
                        display[(data.data == key) & ~np.ma.getmaskarray(data)] = i
                    valid_unmapped = ~np.ma.getmaskarray(data) & ~np.isin(data.data, keys)
                    if valid_unmapped.any():
                        raise ValueError(f"Layer {layer.name}: class labels/colors are missing for observed values.")
                    cmap = ListedColormap([layer.classes[k][1] for k in keys])
                    norm = BoundaryNorm(np.arange(len(keys)+1)-.5, len(keys))
                    ax.imshow(display, extent=extent, origin="upper", cmap=cmap, norm=norm, alpha=layer.alpha, interpolation="nearest",zorder=priorities[layer.name])
                    if layer.legend:
                        legends.extend(("discrete", Patch(facecolor=layer.classes[k][1], label=str(layer.classes[k][0]))) for k in keys)
                else:
                    cmap = colormaps[layer.cmap]
                    artist = ax.imshow(data, extent=extent, origin="upper", cmap=cmap, norm=Normalize(*layer.raster_range) if layer.raster_range else None,alpha=layer.alpha, interpolation="nearest",zorder=priorities[layer.name])
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
        ax.figure.canvas.draw()
        from .typography import place_labels
        label_report=place_labels(ax,annotations,zorder=max(priorities.values(),default=0)+100,obstacles=label_obstacles)
        self.render_diagnostics['labels'].append(label_report)
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
            from .typography import wrap_measured
            from matplotlib.font_manager import FontProperties
            renderer=fig.canvas.get_renderer();labels=[h.get_label() for h in handles];fitted=False
            max_columns=min(4,len(handles),max(1,int(ax.bbox.width/(55*fig.dpi/72))))
            for fontsize in np.arange(8,4,-.5):
                for columns in range(1,max_columns+1):
                    width=max(10,ax.bbox.width/columns-30*fig.dpi/72)
                    wrapped=[wrap_measured(label,width,renderer,FontProperties(size=fontsize)) for label in labels]
                    legend=ax.legend(handles=handles,labels=wrapped,loc='upper left',frameon=False,fontsize=fontsize,borderaxespad=0,title='Légende',title_fontsize=min(9,fontsize+1),ncol=columns,columnspacing=1)
                    extent=legend.get_window_extent(renderer)
                    if extent.width<=ax.bbox.width+1 and extent.height<=ax.bbox.height*discrete_height+1:fitted=True;break
                    legend.remove()
                if fitted:break
            if not fitted:ax.legend(handles=handles,labels=wrapped,loc='upper left',frameon=False,fontsize=4.5,borderaxespad=0,title='Légende',title_fontsize=5.5,ncol=columns)
            self.render_diagnostics['text'].append(dict(id='legend',text='; '.join(labels),fitted=fitted,fontsize=float(fontsize),lines=len(handles),columns=columns))
        start = discrete_height if handles else .06
        for index, (_, name, cmap, norm) in enumerate(continuous):
            step = (1-start)/max(1, len(continuous))
            bar = ax.inset_axes([.02, 1-start-(index+1)*step+.05, .90, min(.08, step*.25)])
            fig.colorbar(__import__("matplotlib").cm.ScalarMappable(norm=norm, cmap=cmap), cax=bar, orientation="horizontal")
            bar.tick_params(labelsize=6)
            bar.set_title(name, fontsize=7, loc="left", pad=4)
        return ax

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
        arrow = ax.annotate("", xy=tip, xytext=position, annotation_clip=False,zorder=1_000_000,
                    xycoords="axes fraction", textcoords="axes fraction",
                    arrowprops={"arrowstyle": "-|>", "color": "#182d35", "lw": 1.4})
        arrow.arrow_patch.set_path_effects([path_effects.withStroke(linewidth=3, foreground="white")])
        ax.annotate("N", tip, xycoords="axes fraction", xytext=(0, 3), textcoords="offset points",
                    ha="center", va="bottom", fontsize=9, weight="bold", annotation_clip=False,zorder=1_000_000,
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
        line, = ax.plot([x, end], [y, y], color="#182d35", linewidth=2, marker="|", markersize=7, clip_on=False,zorder=1_000_000)
        line.set_path_effects([path_effects.withStroke(linewidth=4, foreground="white")])
        label = f"{nice/1000:g} km" if nice >= 1000 else f"{nice:g} m"
        ax.annotate(label, ((x+end)/2, y), xytext=(0, 5), textcoords="offset points", ha="center", fontsize=7,zorder=1_000_000,
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
                ax = self._axes(fig, box,zorder=item.z_index); ax.axis("off")
                from .typography import fit_text
                _,record=fit_text(ax,text,fontsize=max(6,float(item.style.get('fontSize',9))),
                    color=item.style.get('fill','#182d35'),weight=item.style.get('fontWeight','normal'),rotation=item.rotation)
                self.render_diagnostics['text'].append(dict(record,id=item.item_id))
            elif item.kind == "shape":
                rectangle = Rectangle((item.x_mm/self.width, 1-(item.y_mm+item.height_mm)/self.height),
                                      item.width_mm/self.width, item.height_mm/self.height,
                                      transform=fig.transFigure, facecolor=item.style.get("fill", "none"),
                                      edgecolor=item.style.get("stroke", "none"), linewidth=float(item.style.get("strokeWidth", .5)),
                                      zorder=item.z_index)
                fig.add_artist(rectangle)
            elif item.kind == "legend" and self.legend_enabled:
                legend_ax=self._legend(fig, box, legends[linked]);legend_ax.set_zorder(item.z_index)
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
                ax = self._axes(fig, box,zorder=item.z_index); ax.axis("off")
                table = self.tables[item.item_id]
                artist = ax.table(cellText=table.astype(str).values, colLabels=list(table.columns), loc="center", bbox=[0, 0, 1, 1])
                artist.auto_set_font_size(False); artist.set_fontsize(7)
            elif item.kind == "chart" and item.item_id in self.charts:
                ax = self._axes(fig, box,zorder=item.z_index)
                labels, values, color = self.charts[item.item_id]
                ax.bar(labels, values, color=color); ax.tick_params(labelsize=6)
                ax.set_title(item.content.get("title", ""), fontsize=8)

    def export(self, path, *, dpi=300, overwrite=False, max_raster_size=2048):
        """Save an exact-size page. Existing files require overwrite=True."""
        path = output_path(path, overwrite,self._sources)
        if path.suffix.lower() not in {".pdf", ".png", ".svg"}:
            raise ValueError("Supported exports: .pdf, .png, .svg.")
        errors=[i['message'] for i in self.audit()['issues'] if i['severity']=='error']
        if errors:raise ValueError('; '.join(errors))
        fig = self.render(dpi=dpi, max_raster_size=max_raster_size)
        overflow=[i['id'] for i in self.render_diagnostics.get('text',[]) if not i['fitted']]
        if overflow:
            fig.clear();raise ValueError('Contenu trop grand pour son emplacement : '+', '.join(overflow)+'. Agrandir l’élément ou choisir une autre maquette.')
        fd,temporary=tempfile.mkstemp(prefix='.cartomize-map-',suffix=path.suffix,dir=path.parent);os.close(fd)
        try:
            fig.savefig(temporary, dpi=dpi, facecolor=fig.get_facecolor())
            os.replace(temporary,path)
        finally:
            fig.clear();Path(temporary).unlink(missing_ok=True)
        return path
