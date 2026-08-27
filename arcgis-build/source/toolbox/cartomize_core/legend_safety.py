"""Règles de sécurité des légendes Cartomize."""

from .layout import is_basemap_layer


def legend_layer_names(map_item, *, visible_only: bool = True) -> list[str]:
    return [str(layer.name) for layer in map_item.listLayers() if not is_basemap_layer(layer) and not getattr(layer, "isBroken", False) and (not visible_only or bool(getattr(layer, "visible", True)))]
