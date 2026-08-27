"""Lecture non destructive du projet ArcGIS Pro courant."""


def project_summary(aprx) -> dict[str, object]:
    maps = list(aprx.listMaps())
    layers = [(map_item, layer) for map_item in maps for layer in map_item.listLayers()]
    return {
        "maps": len(maps),
        "layers": len(layers),
        "visible": sum(bool(getattr(layer, "visible", True)) for _, layer in layers),
        "broken": sum(bool(getattr(layer, "isBroken", False)) for _, layer in layers),
        "layouts": len(aprx.listLayouts()),
    }
