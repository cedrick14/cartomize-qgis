"""Règles de sécurité des légendes Cartomize."""

from .layout import is_basemap_layer


def legend_layer_names(map_item, *, visible_only: bool = True) -> list[str]:
    return [str(layer.name) for layer in map_item.listLayers() if not is_basemap_layer(layer) and not getattr(layer, "isBroken", False) and (not visible_only or bool(getattr(layer, "visible", True)))]


def isolate_legend_model(legend) -> bool:
    """Désactive la synchronisation lorsque l'API ArcGIS l'expose.

    Les éléments d'une légende ArcGIS Pro sont indépendants du panneau
    Contenu : les retirer ne supprime jamais les couches de la carte.
    """
    changed = False
    for name in ("syncLayerVisibility", "syncNewLayer", "syncReferenceScale"):
        if hasattr(legend, name):
            try: setattr(legend, name, False); changed = True
            except Exception: pass
    return True if legend is not None else changed
