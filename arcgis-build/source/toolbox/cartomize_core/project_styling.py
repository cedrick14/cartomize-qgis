"""Application des styles recommandés au projet."""

from .symbology import apply_raster_symbology, apply_vector_symbology


def apply_recommendation(aprx, layer, analysis):
    if getattr(layer, "isRasterLayer", False):
        return apply_raster_symbology(aprx, layer, analysis)
    return apply_vector_symbology(aprx, layer, analysis)
