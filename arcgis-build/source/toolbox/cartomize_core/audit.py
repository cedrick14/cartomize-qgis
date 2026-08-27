"""Port ArcPy du contrôle qualité Cartomize QGIS 10.5.1."""

from __future__ import annotations

from typing import Any

from .constants import MAX_AUDIT_LAYERS
from .models import Finding, Report

_WEIGHTS = {"critical": 25, "high": 12, "medium": 6, "low": 2, "info": 0}


def audit_project(arcpy: Any, aprx: Any) -> Report:
    findings: list[Finding] = []
    maps = list(aprx.listMaps())
    layouts = list(aprx.listLayouts())
    broken = list(aprx.listBrokenDataSources())
    layers: list[tuple[Any, Any]] = []
    for map_item in maps:
        layers.extend((map_item, layer) for layer in map_item.listLayers())

    if not maps:
        findings.append(Finding(
            "critical", "PROJECT_NO_MAP", "Le projet ne contient aucune carte.",
            remediation="Créer ou importer une carte ArcGIS Pro.",
        ))
    if not layers:
        findings.append(Finding(
            "critical", "PROJECT_NO_LAYER", "Le projet ne contient aucune couche.",
            remediation="Ajouter au moins une couche vectorielle ou raster valide.",
        ))
    if not str(getattr(aprx, "filePath", "") or "").strip():
        findings.append(Finding(
            "medium", "PROJECT_UNSAVED", "Le projet ArcGIS Pro n'est pas enregistré.",
            remediation="Enregistrer le projet APRX avant la production finale.",
        ))
    if getattr(aprx, "isReadOnly", False):
        findings.append(Finding(
            "medium", "PROJECT_READ_ONLY", "Le projet courant est ouvert en lecture seule.",
            remediation="Enregistrer une copie modifiable avant d'appliquer des changements.",
        ))

    for source in broken:
        findings.append(Finding(
            "critical", "BROKEN_DATA_SOURCE", "La connexion à la source de données est rompue.",
            layer_name=str(getattr(source, "name", "Source inconnue")),
            remediation="Réparer la source dans les propriétés de la couche.",
        ))

    sampled_invalid_geometries = 0
    for map_item, layer in layers[:MAX_AUDIT_LAYERS]:
        name = str(getattr(layer, "name", "Couche sans nom"))
        layer_id = str(getattr(layer, "URI", "") or getattr(layer, "longName", name))
        if getattr(layer, "isBroken", False):
            continue
        try:
            description = arcpy.Describe(layer)
        except Exception as exc:
            findings.append(Finding(
                "high", "LAYER_UNREADABLE", f"La couche n'a pas pu être décrite : {exc}",
                layer_id=layer_id, layer_name=name,
                remediation="Vérifier la connexion et les droits de lecture.",
            ))
            continue

        spatial_reference = getattr(description, "spatialReference", None)
        sr_name = str(getattr(spatial_reference, "name", "") or "")
        if not sr_name or sr_name.casefold() in {"unknown", "inconnu"}:
            findings.append(Finding(
                "high", "LAYER_CRS_MISSING", "Le système de coordonnées est inconnu.",
                layer_id=layer_id, layer_name=name,
                remediation="Définir le système de coordonnées source réel.",
            ))

        extent = getattr(description, "extent", None)
        if extent is not None:
            width = float(getattr(extent, "width", 0) or 0)
            height = float(getattr(extent, "height", 0) or 0)
            if width <= 0 or height <= 0:
                findings.append(Finding(
                    "high", "LAYER_EMPTY_EXTENT", "L'emprise de la couche est vide.",
                    layer_id=layer_id, layer_name=name,
                    remediation="Vérifier les données et les filtres actifs.",
                ))

        if getattr(layer, "isFeatureLayer", False):
            try:
                count = int(arcpy.management.GetCount(layer)[0])
                if count == 0:
                    findings.append(Finding(
                        "medium", "VECTOR_EMPTY", "La couche ne contient aucune entité.",
                        layer_id=layer_id, layer_name=name,
                        remediation="Retirer la couche ou corriger sa source.",
                    ))
                invalid = _sample_invalid_geometries(arcpy, layer)
                sampled_invalid_geometries += invalid
                if invalid:
                    findings.append(Finding(
                        "high", "VECTOR_INVALID_GEOMETRY",
                        f"L'échantillon contient {invalid} géométrie(s) non simple(s).",
                        layer_id=layer_id, layer_name=name,
                        remediation="Exécuter l'outil Réparer les géométries.",
                    ))
            except Exception:
                findings.append(Finding(
                    "low", "VECTOR_COUNT_UNAVAILABLE", "Le nombre d'entités n'a pas pu être lu.",
                    layer_id=layer_id, layer_name=name,
                ))
        elif getattr(layer, "isRasterLayer", False):
            band_count = int(getattr(description, "bandCount", 0) or 0)
            if band_count < 1:
                findings.append(Finding(
                    "high", "RASTER_NO_BAND", "Le raster ne contient aucune bande lisible.",
                    layer_id=layer_id, layer_name=name,
                    remediation="Vérifier le fichier raster et son format.",
                ))

        try:
            metadata = getattr(layer, "metadata", None)
            summary = str(getattr(metadata, "summary", "") or "")
            description_text = str(getattr(metadata, "description", "") or "")
            if not summary.strip() and not description_text.strip():
                findings.append(Finding(
                    "low", "LAYER_METADATA_EMPTY", "Le résumé des métadonnées est vide.",
                    layer_id=layer_id, layer_name=name,
                    remediation="Documenter la source, la date, la méthode et les limites.",
                ))
        except Exception:
            pass

    if len(layers) > MAX_AUDIT_LAYERS:
        findings.append(Finding(
            "medium", "PROJECT_LAYER_LIMIT",
            f"Le contrôle détaillé porte sur les {MAX_AUDIT_LAYERS} premières couches.",
        ))

    if not layouts:
        findings.append(Finding(
            "medium", "LAYOUT_NONE", "Le projet ne contient aucune mise en page.",
            remediation="Créer une mise en page Cartomize.",
        ))
    for layout in layouts:
        _audit_layout(layout, findings)

    score = max(0, min(100, 100 - sum(_WEIGHTS.get(item.severity, 0) for item in findings)))
    status = "Conforme" if score >= 85 else ("À améliorer" if score >= 65 else "Non conforme")
    return Report(
        kind="project_audit",
        score=score,
        status=status,
        findings=findings,
        statistics={
            "maps": len(maps),
            "layers": len(layers),
            "vector_layers": sum(bool(getattr(layer, "isFeatureLayer", False)) for _, layer in layers),
            "raster_layers": sum(bool(getattr(layer, "isRasterLayer", False)) for _, layer in layers),
            "layouts": len(layouts),
            "broken_sources": len(broken),
            "sampled_invalid_geometries": sampled_invalid_geometries,
            "findings": len(findings),
        },
    )


def _audit_layout(layout: Any, findings: list[Finding]) -> None:
    name = str(getattr(layout, "name", "Mise en page"))
    elements = list(layout.listElements())
    maps = [item for item in elements if getattr(item, "type", "") == "MAPFRAME_ELEMENT"]
    legends = [item for item in elements if getattr(item, "type", "") == "LEGEND_ELEMENT"]
    scales = [item for item in elements if getattr(item, "type", "") == "MAPSURROUND_ELEMENT" and "scale" in str(getattr(item, "name", "")).casefold()]
    texts = [item for item in elements if getattr(item, "type", "") == "TEXT_ELEMENT"]
    if not maps:
        findings.append(Finding("critical", "LAYOUT_NO_MAP", f"« {name} » ne contient aucun cadre cartographique."))
    if maps and not legends:
        findings.append(Finding("medium", "LAYOUT_NO_LEGEND", f"« {name} » ne contient aucune légende."))
    if maps and not scales:
        findings.append(Finding("medium", "LAYOUT_NO_SCALE", f"« {name} » ne contient aucune barre d'échelle."))
    if not any(str(getattr(item, "text", "") or "").strip() for item in texts):
        findings.append(Finding("low", "LAYOUT_NO_TITLE", f"« {name} » ne contient aucun texte significatif."))
    for legend in legends:
        if getattr(legend, "mapFrame", None) is None:
            findings.append(Finding(
                "high", "LEGEND_UNLINKED",
                f"Une légende de « {name} » n'est liée à aucun cadre.",
            ))
    for scale in scales:
        if getattr(scale, "mapFrame", None) is None:
            findings.append(Finding(
                "high", "SCALE_UNLINKED",
                f"Une barre d'échelle de « {name} » n'est liée à aucun cadre.",
            ))


def _sample_invalid_geometries(arcpy: Any, layer: Any, limit: int = 200) -> int:
    invalid = 0
    checked = 0
    with arcpy.da.SearchCursor(layer, ["SHAPE@"]) as cursor:
        for (geometry,) in cursor:
            if geometry is None or bool(getattr(geometry, "isEmpty", False)):
                continue
            checked += 1
            try:
                invalid += int(not bool(getattr(geometry, "isSimple", True)))
            except Exception:
                pass
            if checked >= limit:
                break
    return invalid
