"""Recettes reproductibles de production cartographique."""

from __future__ import annotations

from .constants import APP_VERSION
from .io_utils import read_json, write_json
from .models import utc_now


def make_recipe(**values):
    allowed = {
        "map_name", "template_id", "layout_name", "title", "subtitle", "credits",
        "remove_basemap_from_legend", "open_view", "export_path", "dpi",
        "visible_only", "margin_percent", "add_grid", "pagx_path",
        "context_opacity_percent", "locator_map_name", "proposal_validated",
    }
    layout = {key: values[key] for key in allowed if key in values}
    template_id = str(values.get("template_id") or "")
    title = str(values.get("title") or "")
    subtitle = str(values.get("subtitle") or "")
    return {
        "schema": "cartomize.arcgispro.recipe/v1",
        "schema_version": 1,
        "app_version": APP_VERSION,
        "cartomize_version": APP_VERSION,
        "created_at": utc_now(),
        "objective": str(values.get("objective") or "auto"),
        "main_layer_id": str(values.get("main_layer_id") or ""),
        "main_layer_name": str(values.get("main_layer_name") or ""),
        "layer_ids": list(values.get("layer_ids") or []),
        "layer_names": list(values.get("layer_names") or []),
        "variant": {
            "variant_id": str(values.get("variant_id") or "institutional"),
            "name": str(values.get("variant_name") or "Institutionnelle"),
            "template_id": template_id,
            "template_name": str(values.get("template_name") or template_id),
            "style_profile": str(values.get("style_profile") or "balanced"),
            "title": title,
            "subtitle": subtitle,
            "margin_percent": float(values.get("margin_percent") or 3.0),
            "add_grid": bool(values.get("add_grid", False)),
        },
        "apply_symbology": bool(values.get("apply_symbology", True)),
        "auto_correct": bool(values.get("auto_correct", True)),
        "visible_only": bool(values.get("visible_only", True)),
        "sources": str(values.get("sources") or values.get("credits") or "")[:2000],
        "background_mode": str(values.get("background_mode") or "automatic"),
        "background_layer_id": str(values.get("background_layer_id") or ""),
        "locator_mode": str(values.get("locator_mode") or "automatic"),
        "layout": layout,
    }


def save_recipe(path, recipe):
    return write_json(path, recipe)


def load_recipe(path):
    recipe = read_json(path)
    if not isinstance(recipe, dict):
        raise ValueError("Le fichier n'est pas une recette Cartomize v1.")
    if recipe.get("schema") != "cartomize.arcgispro.recipe/v1" and int(recipe.get("schema_version", 0)) != 1:
        raise ValueError("Le fichier n'est pas une recette Cartomize v1.")
    layout = recipe.get("layout")
    if not isinstance(layout, dict):
        variant = recipe.get("variant")
        if not isinstance(variant, dict) or not variant.get("template_id"):
            raise ValueError("La recette ne contient aucune maquette valide.")
        layout = {
            "map_name": str(recipe.get("map_name") or ""),
            "template_id": str(variant.get("template_id") or ""),
            "layout_name": str(variant.get("layout_name") or f"Cartomize — {variant.get('name', 'Mise en page')}"),
            "title": str(variant.get("title") or "TITRE DE LA CARTE"),
            "subtitle": str(variant.get("subtitle") or ""),
            "credits": str(recipe.get("sources") or ""),
            "remove_basemap_from_legend": True,
            "visible_only": bool(recipe.get("visible_only", True)),
            "margin_percent": float(variant.get("margin_percent") or 3.0),
            "add_grid": bool(variant.get("add_grid", False)),
            "open_view": True,
            "dpi": 600,
        }
        recipe["layout"] = layout
    if not isinstance(layout, dict):
        raise ValueError("La section layout de la recette est absente.")
    return recipe
