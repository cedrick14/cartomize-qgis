"""Contrôles de compatibilité de l’hôte ArcGIS Pro."""

from typing import Any


def host_capabilities(arcpy: Any) -> dict[str, object]:
    info = arcpy.GetInstallInfo() if hasattr(arcpy, "GetInstallInfo") else {}
    return {
        "host": info.get("ProductName", "ArcGIS Pro"),
        "version": info.get("Version", ""),
        "arcpy_mp": hasattr(arcpy, "mp"),
        "raster": hasattr(arcpy, "Raster"),
    }
