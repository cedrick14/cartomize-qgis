# -*- coding: utf-8 -*-
"""Boîte à outils native Cartomize pour ArcGIS Pro 3.7 et arcpy.mp."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import json
import os
import traceback

import arcpy

from cartomize_core.audit import audit_project
from cartomize_core.batch import load_manifest, safe_output_name
from cartomize_core.constants import APP_NAME, APP_VERSION, DEFAULT_DPI
from cartomize_core.io_utils import safe_name, write_json
from cartomize_core.layout import build_layout, export_layout, is_basemap_layer, result_dict
from cartomize_core.layout import optimize_layout, synchronize_layout
from cartomize_core.label_intelligence import audit_labels
from cartomize_core.layer_stack import LayerDescriptor, plan_layer_stacks
from cartomize_core.mapops import compare as compare_snapshot
from cartomize_core.mapops import save as save_snapshot
from cartomize_core.mapops import snapshot
from cartomize_core.raster import analyze_raster, raster_type_label
from cartomize_core.project_graph import ProjectRelationshipEngine
from cartomize_core.project_service import ProjectService
from cartomize_core.recipes import load_recipe, make_recipe, save_recipe
from cartomize_core.symbology import apply_raster_symbology, apply_vector_symbology
from cartomize_core.templates import TemplateCatalog, discover_template_root
from cartomize_core.vector import analyze_vector


OBJECTIVES = (
    ("auto", "Détection automatique"),
    ("administrative", "Carte administrative"),
    ("amenagement", "Aménagement du territoire"),
    ("occupation_sol", "Occupation du sol"),
    ("risques", "Carte de risques"),
    ("hydrologique", "Hydrologie"),
    ("environnement", "Environnement"),
    ("agriculture", "Agriculture"),
    ("transport", "Transport et accessibilité"),
    ("urbanisme", "Urbanisme"),
    ("demographie", "Démographie"),
    ("biodiversite", "Biodiversité"),
    ("energie", "Énergie"),
    ("sante", "Santé"),
    ("humanitaire", "Humanitaire"),
    ("scientifique", "Publication scientifique"),
    ("topographique", "Topographie"),
    ("atlas", "Atlas territorial"),
)
STYLE_PROFILES = (
    ("balanced", "Équilibré"),
    ("institutional", "Institutionnel"),
    ("analytical", "Analytique"),
    ("minimal", "Minimaliste"),
)
VARIANTS = (
    ("institutional", "Institutionnelle"),
    ("analytical", "Analytique"),
    ("minimal", "Minimaliste"),
)


def _catalog():
    return TemplateCatalog(discover_template_root(__file__))


def _project():
    return arcpy.mp.ArcGISProject("CURRENT")


def _project_folder(aprx=None):
    aprx = aprx or _project()
    folder = str(getattr(aprx, "homeFolder", "") or "").strip()
    return Path(folder if folder else os.environ.get("USERPROFILE", os.getcwd())).resolve()


def _map_by_name(aprx, name):
    if name:
        matches = aprx.listMaps(str(name))
        if matches:
            return matches[0]
    active = getattr(aprx, "activeMap", None)
    if active is not None:
        return active
    maps = aprx.listMaps()
    if not maps:
        raise RuntimeError("Le projet courant ne contient aucune carte.")
    return maps[0]


def _layer_by_name(map_item, name, predicate=None):
    for layer in map_item.listLayers():
        if name and str(layer.name).casefold() != str(name).casefold():
            continue
        if predicate is None or predicate(layer):
            return layer
    raise RuntimeError(f"La couche « {name} » est introuvable dans la carte « {map_item.name} ».")


def _layer_identity_values(value):
    """Return every stable ArcGIS identity exposed by a layer or GP layer value."""
    values = set()
    if value is None:
        return values
    for candidate in (value, getattr(value, "value", None)):
        if candidate is None:
            continue
        for attribute in ("URI", "longName", "name", "dataSource"):
            try:
                text = str(getattr(candidate, attribute, "") or "").strip()
            except Exception:
                text = ""
            if text:
                values.add(text.casefold())
                values.add(os.path.normcase(os.path.normpath(text)).casefold())
        try:
            text = str(candidate or "").strip()
        except Exception:
            text = ""
        if text:
            values.add(text.casefold())
            values.add(os.path.normcase(os.path.normpath(text)).casefold())
    return values


def _same_layer_input(layer, source, source_text=""):
    requested = _layer_identity_values(source) | _layer_identity_values(source_text)
    return bool(requested and requested.intersection(_layer_identity_values(layer)))


def _raster_layer_from_input(map_item, source, source_text, diagnosis):
    if getattr(source, "isRasterLayer", False) and hasattr(source, "symbology"):
        return source
    names = {
        str(value).casefold()
        for value in (
            source_text,
            Path(str(source_text or "")).name,
            Path(str(source_text or "")).stem,
            diagnosis.get("name"),
            Path(str(diagnosis.get("source") or "")).name,
            Path(str(diagnosis.get("source") or "")).stem,
        )
        if str(value or "").strip()
    }
    expected_path = os.path.normcase(os.path.normpath(str(diagnosis.get("source") or "")))
    for layer in map_item.listLayers():
        if not getattr(layer, "isRasterLayer", False):
            continue
        if str(getattr(layer, "name", "")).casefold() in names:
            return layer
        try:
            layer_path = os.path.normcase(os.path.normpath(str(layer.dataSource)))
            if expected_path and layer_path == expected_path:
                return layer
        except Exception:
            pass
    return None


def _template_id(value):
    text = str(value or "")
    labels = _catalog().labels()
    return labels.get(text, text)


def _template_label(template_id):
    for label, item_id in _catalog().labels().items():
        if item_id == template_id:
            return label
    return template_id


def _map_parameter(display="Carte", name="map_name", multi=False):
    parameter = arcpy.Parameter(displayName=display, name=name, datatype="GPString", parameterType="Required", direction="Input", multiValue=multi)
    try:
        aprx = _project()
        choices = [item.name for item in aprx.listMaps()]
        parameter.filter.type = "ValueList"
        parameter.filter.list = choices
        if choices:
            active = getattr(aprx, "activeMap", None)
            parameter.value = active.name if active is not None else choices[0]
    except Exception:
        pass
    return parameter


def _template_parameter(required=True):
    parameter = arcpy.Parameter(
        displayName="Maquette Cartomize",
        name="template",
        datatype="GPString",
        parameterType="Required" if required else "Optional",
        direction="Input",
    )
    try:
        labels = list(_catalog().labels())
        parameter.filter.type = "ValueList"
        parameter.filter.list = labels
        if labels:
            parameter.value = labels[0]
    except Exception:
        pass
    return parameter


def _file_parameter(display, name, direction="Output", required=False, extension="json"):
    parameter = arcpy.Parameter(
        displayName=display,
        name=name,
        datatype="DEFile",
        parameterType="Required" if required else "Optional",
        direction=direction,
    )
    parameter.filter.list = [item for item in str(extension).split(";") if item]
    return parameter


def _status_parameter():
    return arcpy.Parameter(displayName="Statut", name="status", datatype="GPString", parameterType="Derived", direction="Output")


def _bool_parameter(display, name, value=False):
    parameter = arcpy.Parameter(displayName=display, name=name, datatype="GPBoolean", parameterType="Optional", direction="Input")
    parameter.value = bool(value)
    return parameter


def _integer_parameter(display, name, value, low=1, high=10000):
    parameter = arcpy.Parameter(displayName=display, name=name, datatype="GPLong", parameterType="Optional", direction="Input")
    parameter.value = int(value)
    parameter.filter.type = "Range"
    parameter.filter.list = [low, high]
    return parameter


def _double_parameter(display, name, value, low=0.0, high=100.0):
    parameter = arcpy.Parameter(displayName=display, name=name, datatype="GPDouble", parameterType="Optional", direction="Input")
    parameter.value = float(value)
    parameter.filter.type = "Range"
    parameter.filter.list = [float(low), float(high)]
    return parameter


def _choice_parameter(display, name, choices, default_key):
    labels = {label: key for key, label in choices}
    parameter = arcpy.Parameter(displayName=display, name=name, datatype="GPString", parameterType="Required", direction="Input")
    parameter.filter.type = "ValueList"
    parameter.filter.list = list(labels)
    parameter.value = next(label for key, label in choices if key == default_key)
    return parameter


def _choice_key(value, choices, fallback):
    text = str(value or "")
    for key, label in choices:
        if text == label or text == key:
            return key
    return fallback


def _context_choices(map_item):
    choices = [
        ("automatic", "Selon l’affichage ArcGIS Pro"),
        ("none", "Couches thématiques uniquement"),
    ]
    choices.extend(
        (f"catalog:{item.key}", item.label)
        for item in ProjectService.context_basemap_definitions()
    )
    if map_item is not None:
        for layer in map_item.listLayers():
            if getattr(layer, "isBroken", False):
                continue
            if not (is_basemap_layer(layer) or getattr(layer, "isRasterLayer", False)):
                continue
            layer_id = str(getattr(layer, "URI", "") or getattr(layer, "longName", "") or layer.name)
            choices.append((f"layer:{layer_id}", str(layer.name)))
    return choices


def _context_parameter():
    parameter = arcpy.Parameter(
        displayName="Contexte cartographique",
        name="background_choice",
        datatype="GPString",
        parameterType="Optional",
        direction="Input",
    )
    try:
        choices = _context_choices(_map_by_name(_project(), None))
        parameter.filter.type = "ValueList"
        parameter.filter.list = [label for _key, label in choices]
        parameter.value = choices[0][1]
    except Exception:
        parameter.value = "Selon l’affichage ArcGIS Pro"
    return parameter


def _context_key(value, map_item):
    text = str(value or "automatic")
    for key, label in _context_choices(map_item):
        if text == key or text == label:
            return key
    return "automatic"


def _apply_context_choice(map_item, value, opacity_percent=100):
    choice = _context_key(value, map_item)
    percent = max(0, min(100, int(opacity_percent or 100)))
    managed_prefix = ProjectService.MANAGED_PREFIX
    managed = [
        layer for layer in map_item.listLayers()
        if str(getattr(layer, "name", "")).startswith(managed_prefix)
    ]

    if choice == "none":
        for layer in managed:
            map_item.removeLayer(layer)
        return "none", ""

    if choice.startswith("catalog:"):
        key = choice.split(":", 1)[1]
        definition = next(
            (item for item in ProjectService.context_basemap_definitions() if item.key == key),
            None,
        )
        if definition is None:
            raise RuntimeError(f"Fond cartographique inconnu : {key}")
        expected_name = f"{managed_prefix}{key}"
        layer = next((item for item in managed if str(item.name) == expected_name), None)
        for item in managed:
            if item is not layer:
                map_item.removeLayer(item)
        if layer is None:
            layer = map_item.addDataFromPath(definition.url)
            try:
                layer.name = expected_name
            except Exception:
                pass
        try:
            layer.transparency = 100 - percent
        except Exception:
            pass
        return "layer", str(getattr(layer, "URI", "") or getattr(layer, "longName", "") or layer.name)

    if choice.startswith("layer:"):
        layer_id = choice.split(":", 1)[1]
        layer = next(
            (
                item for item in map_item.listLayers()
                if layer_id in {
                    str(getattr(item, "URI", "")),
                    str(getattr(item, "longName", "")),
                    str(getattr(item, "name", "")),
                }
            ),
            None,
        )
        if layer is None:
            raise RuntimeError("La couche de contexte sélectionnée n’est plus disponible.")
        try:
            layer.transparency = 100 - percent
        except Exception:
            pass
        return "layer", layer_id

    for layer in map_item.listLayers():
        if is_basemap_layer(layer):
            try:
                layer.transparency = 100 - percent
            except Exception:
                pass
    return "automatic", ""


def _text(parameter):
    if parameter is None:
        return ""
    return str(getattr(parameter, "valueAsText", None) or "")


def _message(messages, value):
    messages.addMessage(str(value))


def _fail(messages, exc):
    messages.addErrorMessage(str(exc))
    messages.addErrorMessage(traceback.format_exc())
    raise arcpy.ExecuteError


class Toolbox:
    def __init__(self):
        self.label = f"Cartomize {APP_VERSION}"
        self.alias = "cartomize"
        self.tools = [
            AuditProject, AutopilotMap, CreateLayout, VectorIntelligence,
            RasterIntelligence, GeoIntelligence, BatchMaps, ReplayRecipe, MapOpsCheck,
        ]


class AuditProject:
    def __init__(self):
        self.label = "Contrôler la qualité cartographique du projet"
        self.description = "Contrôle les sources, CRS, couches, métadonnées et mises en page sans modifier le projet."
        self.category = "Contrôle de la qualité"
        self.canRunInBackground = False

    def getParameterInfo(self):
        output = _file_parameter("Rapport JSON", "output_report")
        try:
            output.value = str(_project_folder() / "cartomize-audit.json")
        except Exception:
            pass
        mode = arcpy.Parameter(displayName="Contrôle", name="audit_mode", datatype="GPString", parameterType="Optional", direction="Input")
        mode.filter.type = "ValueList"
        mode.filter.list = ["Projet", "Étiquettes"]
        mode.value = "Projet"
        return [output, mode, _status_parameter()]

    def isLicensed(self):
        return True

    def execute(self, parameters, messages):
        try:
            report = audit_labels(_project()) if _text(parameters[1]).casefold().startswith("étiq") else audit_project(arcpy, _project())
            if _text(parameters[0]):
                write_json(_text(parameters[0]), report.to_dict())
            status = f"{report.status} — {report.score}/100 — {len(report.findings)} observation(s)"
            parameters[2].value = status
            _message(messages, status)
        except Exception as exc:
            _fail(messages, exc)


class VectorIntelligence:
    def __init__(self):
        self.label = "Analyser une couche vectorielle"
        self.description = "Profile les attributs et géométries, recommande champs, étiquettes et rendu."
        self.category = "Automatisation cartographique"
        self.canRunInBackground = False

    def getParameterInfo(self):
        source = arcpy.Parameter(displayName="Couche vectorielle", name="input_features", datatype="GPFeatureLayer", parameterType="Required", direction="Input")
        sample = _integer_parameter("Taille maximale de l'échantillon", "sample_limit", 1000, 100, 5000)
        apply_style = _bool_parameter("Appliquer la symbologie recommandée", "apply_style", False)
        output = _file_parameter("Rapport JSON", "output_report")
        render_mode = _choice_parameter("Mode de rendu", "render_mode", [("single", "Symbole unique"), ("categorized", "Catégorisé"), ("graduated", "Gradué — quantiles")], "single")
        thematic = arcpy.Parameter(displayName="Champ thématique", name="thematic_field", datatype="Field", parameterType="Optional", direction="Input"); thematic.parameterDependencies = [source.name]
        max_classes = _integer_parameter("Nombre maximal de classes", "max_classes", 5, 2, 12)
        palette = _choice_parameter("Palette", "palette", [("qualitative", "Qualitative"), ("sequential", "Séquentielle"), ("diverging", "Divergente")], "qualitative")
        label_field = arcpy.Parameter(displayName="Champ d'étiquette", name="label_field", datatype="Field", parameterType="Optional", direction="Input"); label_field.parameterDependencies = [source.name]
        labels = _bool_parameter("Activer les étiquettes", "labels_enabled", False)
        label_size = _double_parameter("Taille des étiquettes (pt)", "label_size", 9.5, 5.0, 48.0)
        placement = _choice_parameter("Placement", "label_placement", [("auto", "Automatique selon la géométrie"), ("around", "Autour du point"), ("on", "Sur le point"), ("line", "Le long de la ligne"), ("curved", "Courbe"), ("horizontal", "Horizontal"), ("free", "Libre")], "auto")
        opacity = _integer_parameter("Opacité de la couche (%)", "opacity_percent", 100, 0, 100)
        confirmed = _bool_parameter("Confirmer les paramètres avant application", "expert_confirmed", False)
        return [source, sample, apply_style, output, render_mode, thematic, max_classes, palette, label_field, labels, label_size, placement, opacity, confirmed, _status_parameter()]

    def execute(self, parameters, messages):
        try:
            source = parameters[0].value
            profile = analyze_vector(arcpy, source, int(parameters[1].value or 1000))
            profile = dict(profile)
            if _text(parameters[5]):
                profile["thematic_field"] = _text(parameters[5])
            if _text(parameters[8]):
                profile["label_field"] = _text(parameters[8])
            style_result = {"applied": False}
            if bool(parameters[2].value):
                if float(profile.get("role_confidence", 0.0) or 0.0) < 0.70 and not bool(parameters[13].value):
                    raise RuntimeError("La confiance est limitée. Vérifiez les paramètres puis confirmez leur application.")
                aprx = _project()
                active_map = _map_by_name(aprx, None)
                layer = source if hasattr(source, "symbology") else _layer_by_name(active_map, profile["layer_name"], lambda item: getattr(item, "isFeatureLayer", False))
                if is_basemap_layer(layer):
                    raise RuntimeError("Le rendu du fond cartographique est protégé. Sélectionnez une couche thématique pour la symbologie.")
                style_result = apply_vector_symbology(aprx, layer, profile, int(parameters[6].value or 5), mode=_text(parameters[4]), field_name=_text(parameters[5]), palette=_text(parameters[7]), label_field=_text(parameters[8]), labels_enabled=bool(parameters[9].value), label_size=float(parameters[10].value or 9.5), label_placement=_text(parameters[11]), opacity_percent=int(parameters[12].value or 100), expert_confirmed=bool(parameters[13].value))
            expert = {"render_mode": _text(parameters[4]), "thematic_field": profile.get("thematic_field", ""), "max_classes": int(parameters[6].value or 5), "palette": _text(parameters[7]), "label_field": profile.get("label_field", ""), "labels_enabled": bool(parameters[9].value), "label_size": float(parameters[10].value or 9.5), "label_placement": _text(parameters[11]), "opacity_percent": int(parameters[12].value or 100), "expert_confirmed": bool(parameters[13].value)}
            payload = {"kind": "vector_intelligence", "profile": profile, "expert_parameters": expert, "styling": style_result}
            if _text(parameters[3]):
                write_json(_text(parameters[3]), payload)
            status = f"Champ d’étiquette : {profile['label_field'] or 'à confirmer'} · champ thématique : {profile['thematic_field'] or 'à confirmer'}"
            parameters[14].value = status
            _message(messages, status)
        except Exception as exc:
            _fail(messages, exc)


class RasterIntelligence:
    def __init__(self):
        self.label = "Analyser un raster avec Raster Engine"
        self.description = "Analyse les métadonnées, le NoData, les classes, les fréquences et les valeurs atypiques sans modifier le raster source."
        self.category = "Automatisation cartographique"
        self.canRunInBackground = False

    def getParameterInfo(self):
        source = arcpy.Parameter(displayName="Couche raster", name="input_raster", datatype="GPRasterLayer", parameterType="Required", direction="Input")
        apply_style = _bool_parameter("Appliquer le coloriseur recommandé", "apply_style", False)
        output = _file_parameter("Rapport JSON", "output_report")
        render_choices = (("categorical", "Catégoriel"), ("continuous", "Continu"), ("gray", "Niveaux de gris"), ("rgb", "Composition RGB"))
        render_mode = _choice_parameter("Mode", "render_mode", render_choices, "continuous")
        thematic = arcpy.Parameter(displayName="Champ thématique", name="thematic_field", datatype="GPString", parameterType="Optional", direction="Input")
        max_classes = _integer_parameter("Nombre maximal de classes", "max_classes", 5, 2, 12)
        palette_choices = tuple(
            (key, key.replace("_", " ").title())
            for key in (
                "land_cover", "ndvi", "elevation", "temperature", "precipitation",
                "risk", "probability", "slope", "forest_dynamics", "deforestation",
                "forest_degradation", "land_cover_change", "categorical", "population",
                "water", "continuous", "diverging", "gray",
            )
        )
        palette = _choice_parameter("Palette", "palette", palette_choices, "continuous")
        label_field = arcpy.Parameter(displayName="Champ d'étiquette", name="label_field", datatype="GPString", parameterType="Optional", direction="Input")
        labels = _bool_parameter("Activer les étiquettes", "labels_enabled", False)
        label_size = _double_parameter("Taille des étiquettes (pt)", "label_size", 9.5, 5.0, 48.0)
        placement = _choice_parameter("Placement", "label_placement", [("auto", "Automatique selon la géométrie"), ("around", "Autour du point"), ("on", "Sur le point"), ("line", "Le long de la ligne"), ("curved", "Courbe"), ("horizontal", "Horizontal"), ("free", "Libre")], "auto")
        opacity = _integer_parameter("Opacité de la couche (%)", "opacity_percent", 100, 0, 100)
        confirmed = _bool_parameter("Confirmer les paramètres avant application", "expert_confirmed", False)
        deep = _bool_parameter("Analyse approfondie", "deep_analysis", False)
        class_plan = _file_parameter("Plan de classes visuelles JSON", "class_plan", direction="Input")
        theme_mode_choices = (("automatic", "Détection automatique"), ("manual", "Choisir manuellement"))
        theme_choices = (
            ("land_cover", "Occupation du sol"), ("forest_dynamics", "Dynamique forestière"),
            ("deforestation", "Déforestation"), ("forest_degradation", "Dégradation forestière"),
            ("land_cover_change", "Changement d'occupation du sol"), ("ndvi", "NDVI / végétation"),
            ("elevation", "Altitude / MNT"), ("slope", "Pente"), ("temperature", "Température"),
            ("precipitation", "Précipitations"), ("risk", "Risque"), ("probability", "Probabilité"),
            ("categorical", "Classification raster"), ("rgb", "Image satellite RGB"),
            ("false_color", "Image satellite fausses couleurs"),
            ("continuous", "Autre carte thématique continue"),
        )
        theme_mode = _choice_parameter("Type de carte", "theme_mode", theme_mode_choices, "automatic")
        theme_profile = _choice_parameter("Schéma thématique", "theme_profile", theme_choices, "continuous")
        render_band = _integer_parameter("Bande analysée", "render_band", 1, 1, 999)
        classification_choices = (("sample_quantiles", "Quantiles de l’échantillon valide"), ("equal_interval", "Intervalles égaux"))
        classification = _choice_parameter("Méthode de classification", "classification_method", classification_choices, "sample_quantiles")
        minimum = _double_parameter("Minimum", "render_minimum", 0.0, -1.0e30, 1.0e30)
        maximum = _double_parameter("Maximum", "render_maximum", 1.0, -1.0e30, 1.0e30)
        red_band = _integer_parameter("Bande rouge", "red_band", 1, 1, 999)
        green_band = _integer_parameter("Bande verte", "green_band", 2, 1, 999)
        blue_band = _integer_parameter("Bande bleue", "blue_band", 3, 1, 999)
        return [
            source, apply_style, output, render_mode, thematic, max_classes, palette,
            label_field, labels, label_size, placement, opacity, confirmed, deep,
            class_plan, theme_mode, theme_profile, render_band, classification,
            minimum, maximum, red_band, green_band, blue_band, _status_parameter(),
        ]

    def execute(self, parameters, messages):
        try:
            source = parameters[0].value
            source_text = _text(parameters[0])
            diagnosis = analyze_raster(
                arcpy, source, source_text,
                deep=bool(parameters[13].value),
            )
            render_choices = (("categorical", "Catégoriel"), ("continuous", "Continu"), ("gray", "Niveaux de gris"), ("rgb", "Composition RGB"))
            render_mode = _choice_key(parameters[3].value, render_choices, "continuous")
            palette_choices = tuple(
                (key, key.replace("_", " ").title())
                for key in (
                    "land_cover", "ndvi", "elevation", "temperature", "precipitation",
                    "risk", "probability", "slope", "forest_dynamics", "deforestation",
                    "forest_degradation", "land_cover_change", "categorical", "population",
                    "water", "continuous", "diverging", "gray",
                )
            )
            palette_key = _choice_key(parameters[6].value, palette_choices, "continuous")
            theme_mode = _choice_key(parameters[15].value, (("automatic", "Détection automatique"), ("manual", "Choisir manuellement")), "automatic")
            theme_choices = (
                ("land_cover", "Occupation du sol"), ("forest_dynamics", "Dynamique forestière"),
                ("deforestation", "Déforestation"), ("forest_degradation", "Dégradation forestière"),
                ("land_cover_change", "Changement d'occupation du sol"), ("ndvi", "NDVI / végétation"),
                ("elevation", "Altitude / MNT"), ("slope", "Pente"), ("temperature", "Température"),
                ("precipitation", "Précipitations"), ("risk", "Risque"), ("probability", "Probabilité"),
                ("categorical", "Classification raster"), ("rgb", "Image satellite RGB"),
                ("false_color", "Image satellite fausses couleurs"),
                ("continuous", "Autre carte thématique continue"),
            )
            if theme_mode == "manual":
                diagnosis["theme"] = _choice_key(parameters[16].value, theme_choices, "continuous")
            diagnosis["raster_type"] = {
                "categorical": "categorized", "continuous": "continuous",
                "gray": "continuous", "rgb": "rgb",
            }[render_mode]
            class_plan_path = _text(parameters[14])
            if class_plan_path:
                payload = json.loads(Path(class_plan_path).expanduser().resolve().read_text(encoding="utf-8-sig"))
                classes = payload.get("classes") if isinstance(payload, dict) else None
                if not isinstance(classes, list):
                    raise RuntimeError("Le plan de classes visuelles est invalide.")
                normalized = []
                for index, item in enumerate(classes, 1):
                    if not isinstance(item, dict):
                        raise RuntimeError(f"Classe visuelle {index} invalide.")
                    values = [float(value) for value in item.get("values", ())]
                    if not values:
                        raise RuntimeError(f"Classe visuelle {index} : indiquez au moins une valeur source.")
                    normalized.append({
                        **item,
                        "values": values,
                        "label": str(item.get("label") or f"Classe {index}"),
                        "color": str(item.get("color") or "#808080"),
                        "opacity": max(0.0, min(1.0, float(item.get("opacity", 1.0)))),
                        "visible": bool(item.get("visible", True)),
                        "show_in_legend": bool(item.get("show_in_legend", True)),
                    })
                diagnosis["classes"] = normalized
                diagnosis["legend"] = [
                    [item["label"], item["color"]]
                    for item in normalized
                    if item["visible"] and item["show_in_legend"]
                ]
            style_result = {"applied": False}
            if bool(parameters[1].value):
                if float(diagnosis.get("confidence", 0.0) or 0.0) < 0.70 and not bool(parameters[12].value):
                    raise RuntimeError("La confiance est limitée. Vérifiez les paramètres puis confirmez leur application.")
                aprx = _project()
                active_map = _map_by_name(aprx, None)
                layer = _raster_layer_from_input(active_map, source, source_text, diagnosis)
                if layer is None:
                    style_result = {
                        "applied": False,
                        "reason": "Le diagnostic est terminé, mais la source n’est pas une couche de la carte active.",
                    }
                else:
                    if is_basemap_layer(layer):
                        raise RuntimeError("Le rendu du fond cartographique est protégé. Sélectionnez une couche thématique pour la symbologie.")
                    style_result = apply_raster_symbology(
                        aprx, layer, diagnosis, int(parameters[5].value or 5),
                        palette=palette_key,
                        opacity_percent=int(parameters[11].value or 100),
                        expert_confirmed=bool(parameters[12].value),
                        mode=render_mode,
                        band=int(parameters[17].value or 1),
                        classification_method=_choice_key(
                            parameters[18].value,
                            (("sample_quantiles", "Quantiles de l’échantillon valide"), ("equal_interval", "Intervalles égaux")),
                            "sample_quantiles",
                        ),
                        minimum=float(parameters[19].value),
                        maximum=float(parameters[20].value),
                        red_band=int(parameters[21].value or 1),
                        green_band=int(parameters[22].value or 2),
                        blue_band=int(parameters[23].value or 3),
                    )
            expert = {
                "render_mode": render_mode, "theme_mode": theme_mode,
                "theme_profile": diagnosis.get("theme"),
                "render_band": int(parameters[17].value or 1),
                "classification_method": _choice_key(parameters[18].value, (("sample_quantiles", "Quantiles de l’échantillon valide"), ("equal_interval", "Intervalles égaux")), "sample_quantiles"),
                "minimum": float(parameters[19].value), "maximum": float(parameters[20].value),
                "red_band": int(parameters[21].value or 1), "green_band": int(parameters[22].value or 2), "blue_band": int(parameters[23].value or 3),
                "max_classes": int(parameters[5].value or 5), "palette": palette_key,
                "opacity_percent": int(parameters[11].value or 100),
                "expert_confirmed": bool(parameters[12].value),
            }
            payload = {"kind": "raster_intelligence", "diagnosis": diagnosis, "expert_parameters": expert, "styling": style_result}
            if _text(parameters[2]):
                write_json(_text(parameters[2]), payload)
            status = (
                f"{raster_type_label(diagnosis['raster_type'])} · "
                f"confiance {round(100 * diagnosis['confidence'])}% · "
                f"{len(diagnosis['classes'])} classe(s)"
            )
            parameters[24].value = status
            _message(messages, status)
        except Exception as exc:
            _fail(messages, exc)


class CreateLayout:
    def __init__(self):
        self.label = "Créer une mise en page Cartomize"
        self.description = "Convertit une maquette Cartomize en mise en page ArcGIS Pro entièrement éditable."
        self.category = "Mise en page et publication"
        self.canRunInBackground = False

    def getParameterInfo(self):
        map_parameter = _map_parameter()
        template = _template_parameter()
        title = arcpy.Parameter(displayName="Titre", name="title", datatype="GPString", parameterType="Required", direction="Input")
        title.value = "TITRE DE LA CARTE"
        subtitle = arcpy.Parameter(displayName="Sous-titre", name="subtitle", datatype="GPString", parameterType="Optional", direction="Input")
        layout_name = arcpy.Parameter(displayName="Nom de la mise en page", name="layout_name", datatype="GPString", parameterType="Optional", direction="Input")
        layout_name.value = "Cartomize — Mise en page"
        credits = arcpy.Parameter(displayName="Sources et crédits", name="credits", datatype="GPString", parameterType="Optional", direction="Input")
        visible_only = _bool_parameter("Utiliser uniquement les couches visibles", "visible_only", True)
        margin = _double_parameter("Marge autour des données (%)", "margin_percent", 3.0, 0.0, 50.0)
        add_grid = _bool_parameter("Ajouter une grille", "add_grid", False)
        hide_basemap = _bool_parameter("Exclure le fond de carte de la légende", "hide_basemap_legend", True)
        open_view = _bool_parameter("Ouvrir la mise en page", "open_view", True)
        export = _file_parameter("Export immédiat (facultatif)", "export_path", extension="pdf;png;jpg;tif;svg")
        dpi = _integer_parameter("Résolution d'export (DPI)", "dpi", DEFAULT_DPI, 96, 1200)
        pagx = _file_parameter("Enregistrer la maquette ArcGIS Pro (PAGX)", "pagx_path", extension="pagx")
        recipe = _file_parameter("Enregistrer la recette JSON", "recipe_path")
        operation = arcpy.Parameter(displayName="Opération", name="operation", datatype="GPString", parameterType="Optional", direction="Input")
        operation.filter.type = "ValueList"
        operation.filter.list = ["Créer", "Synchroniser", "Optimiser", "Exporter"]
        operation.value = "Créer"
        existing_layout = arcpy.Parameter(displayName="Mise en page existante", name="existing_layout", datatype="GPString", parameterType="Optional", direction="Input")
        try:
            names = [item.name for item in _project().listLayouts()]
            existing_layout.filter.type = "ValueList"
            existing_layout.filter.list = names
        except Exception:
            pass
        background_choice = _context_parameter()
        context_opacity = _integer_parameter("Opacité du contexte (%)", "context_opacity", 100, 0, 100)
        locator_map = arcpy.Parameter(displayName="Carte de situation", name="locator_map", datatype="GPString", parameterType="Optional", direction="Input")
        try:
            locator_map.filter.type = "ValueList"
            locator_map.filter.list = [item.name for item in _project().listMaps()]
        except Exception:
            pass
        return [
            map_parameter, template, title, subtitle, layout_name, credits,
            visible_only, margin, add_grid, hide_basemap, open_view,
            export, dpi, pagx, recipe, operation, existing_layout, background_choice,
            context_opacity, locator_map, _status_parameter(),
        ]

    def execute(self, parameters, messages):
        try:
            aprx = _project()
            map_item = _map_by_name(aprx, _text(parameters[0]))
            template_id = _template_id(_text(parameters[1]))
            spec = _catalog().get(template_id)
            operation = _text(parameters[15]) or "Créer"
            existing_name = _text(parameters[16]) or _text(parameters[4])
            background_mode, background_layer_id = _apply_context_choice(
                map_item, _text(parameters[17]), int(parameters[18].value or 100)
            )
            locator_map = _map_by_name(aprx, _text(parameters[19])) if _text(parameters[19]) else None
            result = None
            status = ""
            if operation == "Créer":
                result = build_layout(
                    arcpy, aprx, map_item, spec,
                    layout_name=_text(parameters[4]) or f"Cartomize — {spec.name}",
                    title=_text(parameters[2]), subtitle=_text(parameters[3]), credits=_text(parameters[5]),
                    visible_only=bool(parameters[6].value),
                    margin_percent=float(parameters[7].value or 0.0),
                    add_grid=bool(parameters[8].value),
                    remove_basemap_from_legend=bool(parameters[9].value),
                    open_view=bool(parameters[10].value),
                    export_path=_text(parameters[11]),
                    dpi=int(parameters[12].value or DEFAULT_DPI),
                    pagx_path=_text(parameters[13]),
                    locator_map=locator_map,
                    context_opacity_percent=int(parameters[18].value or 100),
                )
                status = f"{result.layout_name} créée — {result.element_count} éléments — {result.map_frame_count} cadre(s)"
            else:
                matches = aprx.listLayouts(existing_name) if existing_name else aprx.listLayouts()
                if not matches:
                    raise RuntimeError("Sélectionnez une mise en page ArcGIS Pro existante.")
                layout = matches[0]
                if operation == "Synchroniser":
                    counts = synchronize_layout(arcpy, layout, map_item, title=_text(parameters[2]), subtitle=_text(parameters[3]), credits=_text(parameters[5]), visible_only=bool(parameters[6].value), margin_percent=float(parameters[7].value or 0.0))
                    status = f"{layout.name} actualisée — {counts['texts']} texte(s) · {counts['map_frames']} cadre(s)"
                elif operation == "Optimiser":
                    counts = optimize_layout(layout)
                    status = f"{layout.name} améliorée — {counts['moved']} déplacement(s) · {counts['resized']} redimensionnement(s)"
                elif operation == "Exporter":
                    target = _text(parameters[13]) or _text(parameters[11])
                    if not target:
                        raise RuntimeError("Indiquez un fichier d’export.")
                    if str(target).casefold().endswith(".pagx"):
                        Path(target).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
                        layout.exportToPAGX(str(Path(target).expanduser().resolve()))
                    else:
                        export_layout(arcpy, layout, target, dpi=int(parameters[12].value or DEFAULT_DPI))
                    status = f"{layout.name} exportée — {target}"
                else:
                    raise RuntimeError(f"Opération inconnue : {operation}")
                if bool(parameters[10].value):
                    try:
                        layout.openView()
                    except Exception:
                        pass
            if _text(parameters[14]):
                recipe = make_recipe(
                    map_name=map_item.name, template_id=template_id, layout_name=result.layout_name if result is not None else existing_name,
                    title=_text(parameters[2]), subtitle=_text(parameters[3]), credits=_text(parameters[5]),
                    visible_only=bool(parameters[6].value), margin_percent=float(parameters[7].value or 0.0),
                    add_grid=bool(parameters[8].value),
                    remove_basemap_from_legend=bool(parameters[9].value), open_view=bool(parameters[10].value),
                    export_path=_text(parameters[11]), dpi=int(parameters[12].value or DEFAULT_DPI),
                    pagx_path=_text(parameters[13]), sources=_text(parameters[5]),
                    background_mode=background_mode,
                    background_layer_id=background_layer_id,
                    background_choice=_context_key(_text(parameters[17]), map_item),
                    locator_mode="automatic",
                )
                save_recipe(_text(parameters[14]), recipe)
            parameters[20].value = status
            _message(messages, status)
        except Exception as exc:
            _fail(messages, exc)


class GeoIntelligence:
    def __init__(self):
        self.label = "Analyser le projet"
        self.description = "Produit une lecture combinée du projet, des relations cartographiques et des couches."
        self.category = "Automatisation cartographique"
        self.canRunInBackground = False

    def getParameterInfo(self):
        map_parameter = _map_parameter()
        objective = _choice_parameter("Objectif cartographique", "objective", OBJECTIVES, "auto")
        main_layer = arcpy.Parameter(displayName="Couche principale", name="main_layer", datatype="GPLayer", parameterType="Optional", direction="Input")
        try:
            active_map = _map_by_name(_project(), None)
            main_layer.value = next(
                (layer for layer in active_map.listLayers()
                if not getattr(layer, "isBroken", False)
                and not is_basemap_layer(layer)
                and (getattr(layer, "isFeatureLayer", False) or getattr(layer, "isRasterLayer", False))),
                None,
            )
        except Exception:
            pass
        style_profile = _choice_parameter("Profil cartographique", "style_profile", STYLE_PROFILES, "balanced")
        visible_only = _bool_parameter("Utiliser uniquement les couches visibles", "visible_only", True)
        output = _file_parameter("Rapport JSON", "output_report")
        return [map_parameter, objective, main_layer, style_profile, visible_only, output, _status_parameter()]

    def execute(self, parameters, messages):
        try:
            aprx = _project()
            map_item = _map_by_name(aprx, _text(parameters[0]))
            objective = _choice_key(_text(parameters[1]), OBJECTIVES, "auto")
            objective_label = dict(OBJECTIVES).get(objective, "Détection automatique")
            requested_main = parameters[2].value
            requested_main_text = _text(parameters[2])
            style_profile = _choice_key(_text(parameters[3]), STYLE_PROFILES, "balanced")
            visible_only = bool(parameters[4].value)
            audit = audit_project(arcpy, aprx)
            layers = []
            layer_objects = [
                layer for layer in map_item.listLayers()
                if not getattr(layer, "isBroken", False)
                and (not visible_only or bool(getattr(layer, "visible", True)))
            ]
            roles = {}
            main_layer_id = ""
            main_analysis = {}
            for layer in layer_objects:
                layer_id = str(getattr(layer, "URI", "") or getattr(layer, "longName", layer.name))
                record = {
                    "layer_id": layer_id,
                    "name": layer.name,
                    "visible": bool(getattr(layer, "visible", True)),
                    "basemap": is_basemap_layer(layer),
                }
                if getattr(layer, "isFeatureLayer", False) and not getattr(layer, "isBroken", False):
                    try:
                        profile = analyze_vector(arcpy, layer, 500)
                        record.update({
                            "kind": "vector", "label_field": profile["label_field"],
                            "thematic_field": profile["thematic_field"], "role": profile["role"],
                            "role_confidence": profile["role_confidence"],
                        })
                        roles[layer_id] = profile["role"]
                    except Exception as exc:
                        record.update({"kind": "vector", "error": str(exc)})
                elif getattr(layer, "isRasterLayer", False) and not getattr(layer, "isBroken", False):
                    try:
                        diagnosis = analyze_raster(arcpy, layer)
                        record.update({
                            "kind": "raster", "theme": diagnosis["theme"],
                            "raster_type": diagnosis["raster_type"],
                            "theme_confidence": diagnosis["theme_confidence"],
                        })
                        roles[layer_id] = diagnosis["theme"]
                    except Exception as exc:
                        record.update({"kind": "raster", "error": str(exc)})
                else:
                    record["kind"] = "other"
                if (
                    _same_layer_input(layer, requested_main, requested_main_text)
                    and not record["basemap"]
                    and record.get("kind") in {"vector", "raster"}
                ):
                    main_layer_id = layer_id
                    main_analysis = dict(record)
                elif not main_layer_id and not record["basemap"] and record.get("kind") in {"vector", "raster"}:
                    main_layer_id = layer_id
                    main_analysis = dict(record)
                layers.append(record)

            graph = ProjectRelationshipEngine(arcpy).analyze(
                layer_objects, roles=roles, main_layer_id=main_layer_id,
            )
            descriptors = [
                LayerDescriptor(
                    layer_id=item["layer_id"], kind=item.get("kind", "other"),
                    basemap=bool(item.get("basemap")),
                )
                for item in layers
            ]
            stack = plan_layer_stacks(
                descriptors,
                visible_ids=[item["layer_id"] for item in layers if item["visible"]],
                focus_id=main_layer_id,
            )
            payload = {
                "kind": "geo_intelligence", "map": map_item.name, "audit": audit.to_dict(),
                "layers": layers,
                "relationship_graph": graph.to_dict(),
                "layer_stack": asdict(stack),
                "recommendations": _geo_recommendations(audit, layers),
                "objective": objective,
                "objective_label": objective_label,
                "style_profile": style_profile,
                "main_layer_id": main_layer_id,
                "proposals": _automation_proposals(objective, objective_label.upper(), main_analysis),
            }
            if _text(parameters[5]):
                write_json(_text(parameters[5]), payload)
            status = f"{len(layers)} couche(s) analysée(s) · score projet {audit.score}/100"
            parameters[6].value = status
            _message(messages, status)
        except Exception as exc:
            _fail(messages, exc)


class AutopilotMap:
    def __init__(self):
        self.label = "Créer automatiquement une carte"
        self.description = "Audit, profilage, symbologie native et mise en page explicable dans un flux unique."
        self.category = "Automatisation cartographique"
        self.canRunInBackground = False

    def getParameterInfo(self):
        map_parameter = _map_parameter()
        objective = _choice_parameter("Objectif cartographique", "objective", OBJECTIVES, "auto")
        main_layer = arcpy.Parameter(displayName="Couche principale", name="main_layer", datatype="GPLayer", parameterType="Optional", direction="Input")
        try:
            active_map = _map_by_name(_project(), None)
            main_layer.value = next(
                (layer for layer in active_map.listLayers()
                if not getattr(layer, "isBroken", False)
                and not is_basemap_layer(layer)
                and (getattr(layer, "isFeatureLayer", False) or getattr(layer, "isRasterLayer", False))),
                None,
            )
        except Exception:
            pass
        style_profile = _choice_parameter("Profil cartographique", "style_profile", STYLE_PROFILES, "balanced")
        variant = _choice_parameter("Proposition", "variant", VARIANTS, "institutional")
        apply_style = _bool_parameter("Appliquer la symbologie", "apply_style", True)
        auto_correct = _bool_parameter("Corriger automatiquement la lisibilité", "auto_correct", True)
        visible_only = _bool_parameter("Utiliser uniquement les couches visibles", "visible_only", True)
        sources = arcpy.Parameter(displayName="Sources et crédits", name="sources", datatype="GPString", parameterType="Optional", direction="Input")
        title = arcpy.Parameter(displayName="Titre", name="title", datatype="GPString", parameterType="Optional", direction="Input")
        template = _template_parameter(required=False)
        report = _file_parameter("Rapport et recette JSON", "output_report")
        background_choice = _context_parameter()
        context_opacity = _integer_parameter("Opacité du contexte (%)", "context_opacity", 100, 0, 100)
        locator_map = arcpy.Parameter(displayName="Carte de situation", name="locator_map", datatype="GPString", parameterType="Optional", direction="Input")
        try:
            locator_map.filter.type = "ValueList"
            locator_map.filter.list = [item.name for item in _project().listMaps()]
        except Exception:
            pass
        validated = _bool_parameter("Décisions vérifiées par le cartographe", "proposal_validated", False)
        return [
            map_parameter, objective, main_layer, style_profile, variant,
            apply_style, auto_correct, visible_only, sources, title,
            template, report, background_choice, context_opacity, locator_map,
            validated, _status_parameter(),
        ]

    def execute(self, parameters, messages):
        try:
            aprx = _project()
            map_item = _map_by_name(aprx, _text(parameters[0]))
            objective = _choice_key(_text(parameters[1]), OBJECTIVES, "auto")
            objective_label = dict(OBJECTIVES).get(objective, "Détection automatique")
            style_profile = _choice_key(_text(parameters[3]), STYLE_PROFILES, "balanced")
            variant_id = _choice_key(_text(parameters[4]), VARIANTS, "institutional")
            audit = audit_project(arcpy, aprx)
            candidates = [
                layer for layer in map_item.listLayers()
                if not getattr(layer, "isBroken", False)
                and not is_basemap_layer(layer)
                and (not bool(parameters[7].value) or bool(getattr(layer, "visible", True)))
                and (getattr(layer, "isFeatureLayer", False) or getattr(layer, "isRasterLayer", False))
            ]
            requested_main = parameters[2].value
            requested_main_text = _text(parameters[2])
            primary = next(
                (layer for layer in candidates if _same_layer_input(layer, requested_main, requested_main_text)),
                candidates[0] if candidates else None,
            )
            if primary is None:
                raise RuntimeError("Aucune couche thématique valide n'a été trouvée.")
            context_opacity = int(parameters[13].value or 100)
            background_mode, background_layer_id = _apply_context_choice(
                map_item, _text(parameters[12]), context_opacity
            )
            analysis = {}
            styling = {"applied": False}
            if getattr(primary, "isFeatureLayer", False):
                analysis = analyze_vector(arcpy, primary, 1000)
                if bool(parameters[5].value):
                    styling = apply_vector_symbology(aprx, primary, analysis)
            else:
                analysis = analyze_raster(arcpy, primary)
                if bool(parameters[5].value):
                    styling = apply_raster_symbology(aprx, primary, analysis)
            confidence = float(analysis.get("role_confidence", analysis.get("confidence", 0.6)) or 0.6)
            if confidence < 0.70 and not bool(parameters[15].value):
                raise RuntimeError("La confiance de la composition est limitée. Vérifiez les paramètres puis confirmez la décision du cartographe.")
            requested = _template_id(_text(parameters[10])) if _text(parameters[10]) else ""
            spec = _catalog().get(requested or _choose_template(objective_label, analysis))
            title = _text(parameters[9]) or objective_label.upper()
            margin = 3.0 if bool(parameters[6].value) else 0.0
            result = build_layout(
                arcpy, aprx, map_item, spec,
                layout_name=f"Cartomize — {safe_name(title, 'Carte').replace('_', ' ')}",
                title=title, subtitle=objective_label, credits=_text(parameters[8]),
                visible_only=bool(parameters[7].value), margin_percent=margin,
                add_grid=objective in {"topographique", "atlas"},
                remove_basemap_from_legend=True, open_view=True,
                locator_map=_map_by_name(aprx, _text(parameters[14])) if _text(parameters[14]) else None,
                context_opacity_percent=context_opacity,
            )
            layer_ids = [str(getattr(layer, "URI", "") or layer.name) for layer in candidates]
            layer_names = [str(layer.name) for layer in candidates]
            recipe = make_recipe(
                map_name=map_item.name, template_id=spec.template_id,
                template_name=spec.name, layout_name=result.layout_name,
                title=title, subtitle=objective_label, credits=_text(parameters[8]),
                objective=objective,
                main_layer_id=str(getattr(primary, "URI", "") or primary.name),
                main_layer_name=str(primary.name), layer_ids=layer_ids, layer_names=layer_names,
                variant_id=variant_id, variant_name=dict(VARIANTS).get(variant_id, "Institutionnelle"),
                style_profile=style_profile, apply_symbology=bool(parameters[5].value),
                auto_correct=bool(parameters[6].value), visible_only=bool(parameters[7].value),
                sources=_text(parameters[8]), margin_percent=margin,
                add_grid=objective in {"topographique", "atlas"},
                remove_basemap_from_legend=True, open_view=True, dpi=DEFAULT_DPI,
                context_opacity_percent=context_opacity,
                background_mode=background_mode,
                background_layer_id=background_layer_id,
                background_choice=_context_key(_text(parameters[12]), map_item),
                locator_mode="automatic",
                locator_map_name=_text(parameters[14]), proposal_validated=bool(parameters[15].value),
            )
            final_score = max(0, min(100, round((audit.score + 100 * confidence) / 2)))
            payload = {
                "kind": "autopilot", "objective": objective,
                "objective_label": objective_label, "style_profile": style_profile,
                "variant": variant_id, "audit": audit.to_dict(),
                "primary_layer": primary.name, "analysis": analysis, "styling": styling,
                "layout": result_dict(result), "final_score": final_score,
                "proposals": _automation_proposals(objective, title, analysis),
                "background_mode": background_mode,
                "background_layer_id": background_layer_id,
                "context_opacity_percent": context_opacity,
                "locator_map_name": _text(parameters[14]),
                "proposal_validated": bool(parameters[15].value),
                "recipe": recipe,
            }
            if _text(parameters[11]):
                write_json(_text(parameters[11]), payload)
            status = f"{result.layout_name} — score {final_score}/100"
            parameters[16].value = status
            _message(messages, status)
        except Exception as exc:
            _fail(messages, exc)


class BatchMaps:
    def __init__(self):
        self.label = "Produire une série de cartes Cartomize"
        self.description = "Exécute un manifeste Cartomize QGIS ou ArcGIS Pro jusqu’à 5 000 cartes."
        self.category = "Automatisation cartographique"
        self.canRunInBackground = False

    def getParameterInfo(self):
        manifest = _file_parameter("Manifeste de production JSON", "manifest_path", direction="Input", required=True)
        report = _file_parameter("Rapport JSON", "output_report")
        return [manifest, report, _status_parameter()]

    def execute(self, parameters, messages):
        try:
            aprx = _project()
            manifest = load_manifest(_text(parameters[0]))
            recipe = load_recipe(manifest.recipe_path)
            settings = recipe["layout"]
            spec = _catalog().get(settings["template_id"])
            folder = Path(manifest.output_directory).expanduser().resolve()
            folder.mkdir(parents=True, exist_ok=True)
            results = []
            errors = []
            for index, job in enumerate(manifest.jobs, 1):
                layout = None
                try:
                    map_item = _map_by_name(aprx, settings.get("map_name"))
                    background_choice = recipe.get("background_choice")
                    if not background_choice:
                        background_choice = (
                            f"layer:{recipe.get('background_layer_id')}"
                            if recipe.get("background_mode") == "layer" and recipe.get("background_layer_id")
                            else recipe.get("background_mode", "automatic")
                        )
                    _apply_context_choice(
                        map_item,
                        background_choice,
                        int(settings.get("context_opacity_percent", 100)),
                    )
                    title = job.title or settings.get("title") or "TITRE DE LA CARTE"
                    subtitle = job.subtitle or settings.get("subtitle") or ""
                    credits = job.sources or settings.get("credits") or recipe.get("sources") or ""
                    result = build_layout(
                        arcpy, aprx, map_item, spec,
                        layout_name=f"Cartomize — {job.output_name}", title=title,
                        subtitle=subtitle, credits=credits,
                        visible_only=bool(settings.get("visible_only", True)),
                        margin_percent=float(settings.get("margin_percent", 3.0)),
                        add_grid=bool(settings.get("add_grid", False)),
                        remove_basemap_from_legend=bool(settings.get("remove_basemap_from_legend", True)),
                        open_view=False,
                        locator_map=_map_by_name(aprx, settings.get("locator_map_name")) if settings.get("locator_map_name") else None,
                        context_opacity_percent=int(settings.get("context_opacity_percent", 100)),
                    )
                    layout = aprx.listLayouts(result.layout_name)[0]
                    outputs = []
                    stem = safe_output_name(job.output_name or job.job_id)
                    for output_format in job.output_formats:
                        suffix = "pagx" if output_format == "qpt" else output_format
                        target = folder / f"{stem}.{suffix}"
                        if suffix == "pagx":
                            layout.exportToPAGX(str(target))
                            outputs.append(str(target))
                        else:
                            outputs.append(export_layout(arcpy, layout, str(target), dpi=manifest.dpi))
                    results.append({
                        "job_id": job.job_id,
                        "status": "Réussie",
                        "layout_name": result.layout_name,
                        "outputs": outputs,
                        "validation_status": "En attente" if manifest.require_human_validation else "Non requise",
                    })
                    _message(messages, f"[{index}/{len(manifest.jobs)}] {job.output_name} exportée.")
                except Exception as exc:
                    errors.append({"job_id": job.job_id, "output_name": job.output_name, "error": str(exc)})
                    messages.addWarningMessage(f"{job.output_name} : {exc}")
                finally:
                    if layout is not None and not manifest.keep_layouts:
                        try:
                            aprx.deleteItem(layout)
                        except Exception:
                            pass
            payload = {
                "kind": "batch_maps", "template": spec.template_id,
                "total": len(manifest.jobs), "succeeded": len(results),
                "failed": len(errors), "results": results, "errors": errors,
            }
            if _text(parameters[1]):
                write_json(_text(parameters[1]), payload)
            status = f"{len(results)} export(s) réussi(s) · {len(errors)} échec(s)"
            parameters[2].value = status
            _message(messages, status)
        except Exception as exc:
            _fail(messages, exc)


class ReplayRecipe:
    def __init__(self):
        self.label = "Rejouer une recette Cartomize"
        self.description = "Recrée une mise en page Cartomize à partir d'une recette JSON v1."
        self.category = "Automatisation cartographique"
        self.canRunInBackground = False

    def getParameterInfo(self):
        recipe = _file_parameter("Recette Cartomize JSON", "recipe_path", direction="Input", required=True)
        return [recipe, _status_parameter()]

    def execute(self, parameters, messages):
        try:
            recipe = load_recipe(_text(parameters[0]))
            settings = recipe["layout"]
            aprx = _project()
            map_item = _map_by_name(aprx, settings.get("map_name"))
            background_choice = recipe.get("background_choice")
            if not background_choice:
                background_choice = (
                    f"layer:{recipe.get('background_layer_id')}"
                    if recipe.get("background_mode") == "layer" and recipe.get("background_layer_id")
                    else recipe.get("background_mode", "automatic")
                )
            _apply_context_choice(
                map_item,
                background_choice,
                int(settings.get("context_opacity_percent", 100)),
            )
            spec = _catalog().get(settings["template_id"])
            result = build_layout(
                arcpy, aprx, map_item, spec,
                layout_name=settings.get("layout_name") or f"Cartomize — {spec.name}",
                title=settings.get("title") or "TITRE DE LA CARTE",
                subtitle=settings.get("subtitle") or "",
                credits=settings.get("credits") or recipe.get("sources") or "",
                visible_only=bool(settings.get("visible_only", recipe.get("visible_only", True))),
                margin_percent=float(settings.get("margin_percent", 3.0)),
                add_grid=bool(settings.get("add_grid", False)),
                remove_basemap_from_legend=bool(settings.get("remove_basemap_from_legend", True)),
                open_view=bool(settings.get("open_view", True)), export_path=settings.get("export_path") or "",
                pagx_path=settings.get("pagx_path") or "",
                dpi=int(settings.get("dpi") or DEFAULT_DPI),
                locator_map=_map_by_name(aprx, settings.get("locator_map_name")) if settings.get("locator_map_name") else None,
                context_opacity_percent=int(settings.get("context_opacity_percent", 100)),
            )
            status = f"Recette rejouée — {result.layout_name}"
            parameters[1].value = status
            _message(messages, status)
        except Exception as exc:
            _fail(messages, exc)


class MapOpsCheck:
    def __init__(self):
        self.label = "Vérifier les changements MapOps"
        self.description = "Crée ou compare une empreinte légère des cartes, couches et mises en page."
        self.category = "Contrôle qualité"
        self.canRunInBackground = False

    def getParameterInfo(self):
        previous = _file_parameter("Empreinte précédente (facultatif)", "previous_snapshot", direction="Input")
        output = _file_parameter("Nouvelle empreinte", "output_snapshot", required=True)
        try:
            output.value = str(_project_folder() / "cartomize-mapops.json")
        except Exception:
            pass
        report = _file_parameter("Rapport de comparaison", "comparison_report")
        action = arcpy.Parameter(displayName="Action", name="action", datatype="GPString", parameterType="Optional", direction="Input")
        action.filter.type = "ValueList"
        action.filter.list = ["Créer référence", "Vérifier", "Accepter"]
        action.value = "Vérifier"
        return [previous, output, report, action, _status_parameter()]

    def execute(self, parameters, messages):
        try:
            current = snapshot(_project(), arcpy)
            action = _text(parameters[3]) or "Vérifier"
            comparison = {"changed": False, "baseline_created": action == "Créer référence", "accepted": action == "Accepter", "status": action}
            if action == "Vérifier" and _text(parameters[0]):
                comparison = compare_snapshot(_text(parameters[0]), current)
                comparison["baseline_created"] = False
            elif action == "Vérifier" and not _text(parameters[0]):
                raise RuntimeError("Créez d’abord un état de référence MapOps.")
            save_snapshot(_text(parameters[1]), current)
            if _text(parameters[2]):
                write_json(_text(parameters[2]), comparison)
            if action == "Créer référence":
                status = "État de référence créé"
            elif action == "Accepter":
                status = "État actuel accepté comme référence"
            else:
                status = "Modifications détectées" if comparison.get("changed") else "Aucune modification détectée"
            parameters[4].value = status
            _message(messages, status)
        except Exception as exc:
            _fail(messages, exc)


def _choose_template(objective, analysis):
    text = str(objective).casefold()
    candidates = {
        "localisation": "professionnelles/25-localisation-territoriale-trois-niveaux",
        "occupation": "occupation_sol/institutionnel",
        "environnement": "environnement/fragmentation-forestiere-a3",
        "transport": "transport/accessibilite-reseau-a4",
        "santé": "sante/couverture-services-a4",
        "agriculture": "agriculture/aptitude-agricole-a3",
        "humanitaire": "humanitaire/situation-urgence-a3",
    }
    for token, template_id in candidates.items():
        if token in text:
            return template_id
    theme = str(analysis.get("theme") or "")
    if theme in {"land_cover", "forest_dynamics"}:
        return "occupation_sol/institutionnel" if theme == "land_cover" else "environnement/fragmentation-forestiere-a3"
    return "administrative/institutionnel"


def _automation_proposals(objective, title, analysis):
    """Trois propositions comme dans l’onglet Automatisation de QGIS."""
    base = _choose_template(dict(OBJECTIVES).get(objective, objective), analysis)
    options = (
        ("institutional", "Institutionnelle", base, 3.0, objective in {"topographique", "atlas"}),
        ("analytical", "Analytique", "professionnelles/13-planche-analyse-multi-blocs", 4.0, False),
        ("minimal", "Minimaliste", "professionnelles/03-localisation-hierarchique", 5.0, False),
    )
    proposals = []
    for index, (variant_id, name, template_id, margin, add_grid) in enumerate(options):
        try:
            spec = _catalog().get(template_id)
        except Exception:
            spec = _catalog().get(base)
        proposals.append({
            "variant_id": variant_id,
            "name": name,
            "template_id": spec.template_id,
            "template_name": spec.name,
            "page_format": spec.page_format,
            "title": title,
            "subtitle": dict(OBJECTIVES).get(objective, objective),
            "margin_percent": margin,
            "add_grid": add_grid,
            "score": 92 - index * 4,
            "decisions": f"Marge {margin:g}% · grille {'oui' if add_grid else 'non'}",
        })
    return proposals


def _geo_recommendations(audit, layers):
    recommendations = []
    if audit.score < 85:
        recommendations.append("Corriger d'abord les observations critiques et élevées de l'audit.")
    if not any(item.get("basemap") for item in layers):
        recommendations.append("Un fond de carte Esri peut améliorer le contexte; il restera exclu de la légende Cartomize.")
    if sum(item.get("kind") == "raster" for item in layers) > 1:
        recommendations.append("Vérifier l'ordre, la transparence et les fonctions de rendu des rasters superposés.")
    if not recommendations:
        recommendations.append("Le projet est prêt pour une mise en page Cartomize et une validation humaine.")
    return recommendations
