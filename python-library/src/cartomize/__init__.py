"""Cartomize: cartography, spatial analysis and automated map production."""
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
from .algebra import calculate, reduce_rasters, ProcessingCancelled
from .indices import spectral_indices, list_indices, get_index, register_index
from .focal import focal
from .workflow import CartographicProduct, cartographic_workflow
from .nodata import detect_background, mask_background
from .project import analyze_project, prepare_project, load_project, PreparedProject

__version__ = "0.4.0a1"


def launch(*,block=None):
    """Open the optional desktop interface; scripts remain usable without Qt."""
    from .desktop import launch as open_desktop
    return open_desktop(block=block)


# Retain convenient access through the raster module without import cycles.
raster.calculate=calculate
raster.reduce=reduce_rasters
raster.focal=focal
raster.indices=spectral_indices
__all__ = ["Map", "Layer", "GeoDataFrame", "GeoSeries", "points_from_xy", "read_file",
           "from_xy", "reproject", "clip", "overlay", "sjoin", "dissolve", "buffer",
           "area", "length", "validate", "make_valid", "list_templates", "get_template",
           "layout_plan", "atlas", "raster", "vector", "Scene", "Band", "discover_scenes",
           "PreparedImage", "prepare_imagery", "color_composite", "read_rgb", "compose_map",
           "calculate", "reduce_rasters", "ProcessingCancelled", "spectral_indices", "list_indices",
           "get_index", "register_index", "focal", "launch", "CartographicProduct", "cartographic_workflow", "detect_background", "mask_background",
           "analyze_project", "prepare_project", "load_project", "PreparedProject"]
