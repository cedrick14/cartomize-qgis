"""Cartomize: Python cartography and spatial analysis from ArcGIS Pro roots."""
from geopandas import GeoDataFrame, GeoSeries, points_from_xy
from .mapping import Map, Layer
from .vector import read_file, from_xy, reproject, clip, overlay, sjoin, dissolve, buffer, area, length, validate, make_valid
from .templates import list_templates, get_template, layout_plan
from .batch import atlas
from . import raster, vector
from .scenes import Scene, Band, discover_scenes
from .imagery import PreparedImage, prepare_imagery
from .color import color_composite, read_rgb
from .composition import compose_map

__version__ = "0.2.0a1"
__all__ = ["Map", "Layer", "GeoDataFrame", "GeoSeries", "points_from_xy", "read_file",
           "from_xy", "reproject", "clip", "overlay", "sjoin", "dissolve", "buffer",
           "area", "length", "validate", "make_valid", "list_templates", "get_template",
           "layout_plan", "atlas", "raster", "vector", "Scene", "Band", "discover_scenes",
           "PreparedImage", "prepare_imagery", "color_composite", "read_rgb", "compose_map"]
