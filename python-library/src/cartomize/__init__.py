"""Cartomize: cartography, spatial analysis and automated map production."""
from geopandas import GeoDataFrame, GeoSeries, points_from_xy
from .mapping import Map, Layer
from .vector import read_file, from_xy, reproject, clip, overlay, sjoin, nearest, dissolve, buffer, area, length, validate, make_valid
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
from .assistant import assess_project
from .classification import SpectralModel,fit_classifier,load_classifier,classify_landcover,cluster_raster
from .session import save_session,load_session,save_map,load_map
from .relations import analyze_relations
from .automation import plan_cartography,run_plan,propose_layouts
from .mapops import snapshot_project,compare_snapshots,record_review,verify_review

__version__ = "0.8.1a1"


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
           "analyze_project", "prepare_project", "load_project", "PreparedProject", "assess_project", "nearest"]
__all__ += ['SpectralModel','fit_classifier','load_classifier','classify_landcover','cluster_raster',
            'save_session','load_session','save_map','load_map','analyze_relations','plan_cartography','run_plan',
            'propose_layouts','snapshot_project','compare_snapshots','record_review','verify_review']

from .recipes import save_recipe,load_recipe,instantiate_recipe,run_recipe,run_batch

from .native import native_project,inspect_qgis_project

from .terrain import terrain,convolve

__all__ += ["save_recipe","load_recipe","instantiate_recipe","run_recipe","run_batch",
            "native_project","inspect_qgis_project","terrain","convolve"]
raster.terrain=terrain
raster.convolve=convolve

from .processing import operation_catalog,execute_operation
from .automation import processing_plan,validate_plan
__all__ += ['operation_catalog','execute_operation','processing_plan','validate_plan']

from .native import import_native_project
__all__ += ['import_native_project']

from .hydrology import hydrology
from .routing import shortest_path
from .catalogs import search_stac,download_stac,scene_from_stac,load_scenes_manifest
__all__ += ['hydrology','shortest_path','search_stac','download_stac','scene_from_stac','load_scenes_manifest']

from .execution import execution_capabilities
from .native import validate_native_runtime
__all__ += ["execution_capabilities", "validate_native_runtime"]

from .imagery_pipeline import ImageryProducts, process_imagery, split_bands
__all__ += ["ImageryProducts", "process_imagery", "split_bands"]
