"""Règles pures de cadrage cartographique, indépendantes de PyQGIS.

Les fonds web doivent participer au rendu d'une carte, mais jamais décider de
son emprise. Un fond XYZ/WMTS est généralement mondial : l'inclure dans une
union d'emprises transforme une carte locale en planisphère.
"""
from __future__ import annotations


_BASEMAP_NAME_TOKENS = (
    "basemap",
    "base map",
    "fond de carte",
    "fond cartographique",
    "openstreetmap",
    "open street map",
    "osm",
    "google satellite",
    "google maps",
    "esri world",
    "cartodb",
    "mapbox",
    "bing maps",
)

_REMOTE_TILE_PROVIDERS = {
    "arcgismapserver",
    "vectortile",
}


def is_remote_basemap(provider_type: str, source: str, name: str = "") -> bool:
    """Retourne ``True`` pour les fonds web dont l'emprise ne doit pas cadrer la carte."""

    provider = str(provider_type or "").strip().casefold()
    uri = str(source or "").strip().casefold()
    label = str(name or "").strip().casefold()
    if provider in _REMOTE_TILE_PROVIDERS:
        return True
    if provider == "wms" and any(
        token in uri
        for token in (
            "type=xyz",
            "type%3dxyz",
            "tilematrixset=",
            "service=wmts",
            "{x}",
            "{y}",
            "{z}",
        )
    ):
        return True
    return any(token in label for token in _BASEMAP_NAME_TOKENS)


def extent_factor_for_role(role: str) -> float:
    """Facteur de contexte d'un cadre par rapport à l'emprise thématique."""

    normalized = str(role or "main").strip().casefold()
    if normalized == "overview":
        return 10.0
    if normalized == "locator":
        return 4.0
    if normalized == "inset":
        return 1.75
    return 1.0
