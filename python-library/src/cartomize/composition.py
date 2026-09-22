"""Cartographic role inference, layer order and an automatic map composer."""
import unicodedata
from pathlib import Path

from ._validation import frame

ORDER={"background":0,"landcover":10,"thematic":15,"polygon":20,"water":30,
       "line":40,"roads":45,"railways":46,"boundaries":50,"localities":60,"points":65}
COLORS={"background":"#dddddd","landcover":"#769c76","thematic":"#56866c","polygon":"#c1cebd",
        "water":"#4a93bb","roads":"#cf985a","railways":"#41474b","boundaries":"#253b43",
        "localities":"#182d35","line":"#65777d","points":"#344e63"}


def infer_role(name,kind,geometry_types=(),*,column=None,classes=None,rgb=None):
    text="".join(c for c in unicodedata.normalize("NFKD",name.casefold()) if not unicodedata.combining(c))
    if kind=="raster":
        return "background" if rgb is not None else "landcover" if classes else "thematic"
    types=set(geometry_types)
    polygon=bool(types) and all("Polygon" in k for k in types)
    point=bool(types) and all("Point" in k for k in types)
    line=bool(types) and all("Line" in k for k in types)
    if polygon and column:return "thematic"
    if any(t in text for t in ("rivi","river","fleuve","hydro","water","lac","lake")):
        return "water"
    if line and any(t in text for t in ("rail","chemin de fer")):return "railways"
    if line and any(t in text for t in ("route","road","street","piste","voie")):return "roads"
    if any(t in text for t in ("limite","boundary","boundaries","district","province","departement","commune","aoi","emprise")) and (line or polygon):
        return "boundaries"
    if point and any(t in text for t in ("village","localit","city","cities","ville","town")):return "localities"
    return "polygon" if polygon else "points" if point else "line" if line else "thematic"


def default_label(data):
    candidates={str(c).casefold():c for c in data.columns if c!=data.geometry.name}
    for key in ("nom","name","nom_village","village","label","libelle","localite"):
        if key in candidates:return candidates[key]
    return None


def compose_map(layers,*,aoi=None,clip_vectors=True,**options):
    """Build an ordered Map from paths or add_layer keyword dictionaries.

    Semantic inference can always be overridden with role, zorder and style.
    AOI is polygonal and controls the common extent; vector clipping is optional.
    Raster clipping/masking belongs to prepare_imagery, not visual layer ordering.
    """
    from .mapping import Map
    result=Map(auto_order=True,**options)
    zones=frame(aoi) if aoi is not None else None
    if zones is not None and (zones.empty or not zones.geom_type.isin(["Polygon","MultiPolygon"]).all()
                              or zones.geometry.isna().any() or not zones.geometry.is_valid.all()):
        raise ValueError("AOI must contain valid polygons.")
    for item in layers:
        kwargs=dict(item) if isinstance(item,dict) else {"data":item}
        data=kwargs.pop("data")
        kind=kwargs.get("kind")
        raster=kind=="raster" or (kind is None and isinstance(data,(str,Path)) and Path(data).suffix.lower() in {".tif",".tiff",".vrt",".img",".jp2"})
        if zones is not None and clip_vectors and not raster:
            import geopandas as gpd
            if isinstance(data,(str,Path)):
                kwargs.setdefault("name",Path(data).stem)
                result._sources.append(Path(data).expanduser().resolve())
            data=frame(data)
            data=gpd.clip(data,zones.to_crs(data.crs),keep_geom_type=True)
        result.add_layer(data,**kwargs)
    if zones is not None:
        if result.crs is None:raise ValueError("Add at least one layer.")
        result.set_extent(zones.to_crs(result.crs).total_bounds)
    return result
