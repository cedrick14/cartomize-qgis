"""Automatisation Cartomize 10.5.1 adaptée à arcpy.mp."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .constants import APP_VERSION
from .errors import CartomizeError
from .human_validation import HumanValidationService
from .layout_builder import LayoutBuildOptions, LayoutBuilder
from .layout_intelligence import AdaptiveLayoutOptimizer
from .project_styling import ProjectStylingOrchestrator, StylingDecision
from .quality import ProjectQualityAuditor
from .raster_intelligence import RasterIntelligenceEngine
from .symbology import SmartSymbologyService
from .vector_intelligence import VectorIntelligenceEngine


@dataclass(frozen=True)
class LayerProfile:
    layer_id: str; name: str; layer_type: str; crs: str; visible: bool
    feature_count: int | None = None; band_count: int | None = None
    categorical_fields: tuple[str, ...] = (); numeric_fields: tuple[str, ...] = (); label_field: str = ""


@dataclass(frozen=True)
class AutomationVariant:
    variant_id: str; name: str; template_id: str; template_name: str; page_format: str; style_profile: str
    score: int; title: str; subtitle: str; margin_percent: float; add_grid: bool; reasons: tuple[str, ...]
    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True)
class AutomationPlan:
    generated_at: str; objective: str; objective_label: str; confidence: float; main_layer_id: str; main_layer_name: str
    layer_ids: tuple[str, ...]; project_crs: str; map_type_reason: str; warnings: tuple[str, ...]
    layers: tuple[LayerProfile, ...]; variants: tuple[AutomationVariant, ...]; intelligence: dict[str, Any] = field(default_factory=dict)
    def to_dict(self) -> dict[str, Any]:
        return {"generated_at": self.generated_at, "objective": self.objective, "objective_label": self.objective_label, "confidence": self.confidence, "main_layer_id": self.main_layer_id, "main_layer_name": self.main_layer_name, "layer_ids": list(self.layer_ids), "project_crs": self.project_crs, "map_type_reason": self.map_type_reason, "warnings": list(self.warnings), "layers": [asdict(item) for item in self.layers], "variants": [item.to_dict() for item in self.variants], "intelligence": dict(self.intelligence)}


@dataclass(frozen=True)
class AutomationRecipe:
    schema_version: int; cartomize_version: str; created_at: str; objective: str; main_layer_id: str; main_layer_name: str
    layer_ids: tuple[str, ...]; layer_names: tuple[str, ...]; variant: dict[str, Any]; apply_symbology: bool; auto_correct: bool
    visible_only: bool; sources: str; background_mode: str = "automatic"; background_layer_id: str = ""; locator_mode: str = "automatic"
    def to_dict(self) -> dict[str, Any]:
        result = asdict(self); result["layer_ids"] = list(self.layer_ids); result["layer_names"] = list(self.layer_names); return result
    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AutomationRecipe":
        if not isinstance(payload, dict) or int(payload.get("schema_version", 0)) != 1: raise CartomizeError("Le fichier de recette Cartomize est invalide ou incompatible.")
        variant = payload.get("variant")
        if not isinstance(variant, dict) or not variant.get("template_id"): raise CartomizeError("La recette ne contient aucune maquette valide.")
        return cls(1, str(payload.get("cartomize_version") or ""), str(payload.get("created_at") or ""), str(payload.get("objective") or "auto"), str(payload.get("main_layer_id") or ""), str(payload.get("main_layer_name") or ""), tuple(str(item) for item in payload.get("layer_ids", [])[:2000]), tuple(str(item) for item in payload.get("layer_names", [])[:2000]), dict(variant), bool(payload.get("apply_symbology", True)), bool(payload.get("auto_correct", True)), bool(payload.get("visible_only", True)), str(payload.get("sources") or "")[:2000], str(payload.get("background_mode") or "automatic"), str(payload.get("background_layer_id") or ""), str(payload.get("locator_mode") or "automatic"))


@dataclass(frozen=True)
class AutomationExecutionResult:
    layout: Any; layout_name: str; variant_name: str; layout_score: int; project_score: int; final_score: int
    corrections: tuple[str, ...]; warnings: tuple[str, ...]; recipe: AutomationRecipe; styling: tuple[StylingDecision, ...] = ()
    validation_status: str = "En attente"; data_quality_score: int = 0; cartographic_score: int = 0; automation_confidence: int = 0


_OBJECTIVES = {
    "auto": "Détection automatique", "administrative": "Carte administrative", "occupation_sol": "Occupation du sol",
    "risques": "Carte de risques", "hydrologique": "Hydrologie", "environnement": "Environnement", "agriculture": "Agriculture",
    "transport": "Transport et accessibilité", "demographie": "Démographie", "biodiversite": "Biodiversité", "energie": "Énergie",
    "sante": "Santé", "humanitaire": "Humanitaire", "topographique": "Topographie", "atlas": "Atlas territorial",
}


class CartomizeAutopilot:
    def __init__(self, iface, catalog, project=None, builder=None, symbology=None, auditor=None, *, arcpy_module=None):
        self.arcpy = arcpy_module or _import_arcpy(); self.project = project or self.arcpy.mp.ArcGISProject("CURRENT"); self.catalog = catalog
        self.builder = builder or LayoutBuilder(project=self.project, arcpy_module=self.arcpy)
        self.symbology = symbology or SmartSymbologyService(self.project, arcpy_module=self.arcpy)
        self.auditor = auditor or ProjectQualityAuditor(self.project, arcpy_module=self.arcpy)
        self.styling = ProjectStylingOrchestrator(self.project, self.symbology)

    def analyze(self, objective: str = "auto", main_layer_id: str = "", style_profile: str = "balanced", visible_only: bool = True) -> AutomationPlan:
        map_item = self.project.activeMap or (self.project.listMaps()[0] if self.project.listMaps() else None)
        if map_item is None: raise CartomizeError("Le projet ne contient aucune carte ArcGIS Pro.")
        layers = [layer for layer in map_item.listLayers() if not getattr(layer, "isBroken", False) and (not visible_only or bool(getattr(layer, "visible", True))) and (getattr(layer, "isFeatureLayer", False) or getattr(layer, "isRasterLayer", False))]
        if not layers: raise CartomizeError("Aucune couche vectorielle ou raster valide n'est disponible.")
        primary = next((layer for layer in layers if _key(layer) == main_layer_id), layers[0]); main_layer_id = _key(primary)
        profiles, warnings, confidence_values = [], [], []
        for layer in layers:
            if getattr(layer, "isFeatureLayer", False):
                profile = VectorIntelligenceEngine(self.arcpy).analyze(layer); warnings.extend(profile.warnings); confidence_values.append(profile.role_confidence)
                categorical = tuple(item.name for item in profile.fields if item.semantic_role in {"category", "coded_category", "ordinal"})
                numeric = tuple(item.name for item in profile.fields if item.semantic_role in {"quantitative", "diverging_quantitative", "measure"})
                profiles.append(LayerProfile(_key(layer), str(layer.name), "vector", profile.crs, bool(getattr(layer, "visible", True)), profile.feature_count, None, categorical, numeric, profile.label_field))
            else:
                diagnosis = RasterIntelligenceEngine(self.project, arcpy_module=self.arcpy).analyze(layer); confidence_values.append(diagnosis.inference.confidence)
                profiles.append(LayerProfile(_key(layer), str(layer.name), "raster", diagnosis.inspection.crs, bool(getattr(layer, "visible", True)), None, diagnosis.inspection.band_count))
        objective = objective if objective in _OBJECTIVES else "auto"; label = _OBJECTIVES[objective]
        templates = self.catalog.all(); variants = _variants(templates, objective, label, style_profile)
        confidence = sum(confidence_values) / max(1, len(confidence_values))
        crs = str(getattr(getattr(map_item, "spatialReference", None), "name", "") or "")
        return AutomationPlan(datetime.now(timezone.utc).isoformat(), objective, label, confidence, main_layer_id, str(primary.name), tuple(_key(layer) for layer in layers), crs, f"Objectif retenu : {label}.", tuple(warnings), tuple(profiles), variants, {"host": "ArcGIS Pro", "layers": len(layers), "style_profile": style_profile})

    def execute_variant(self, plan: AutomationPlan, variant_index: int, *, apply_symbology: bool = True, auto_correct: bool = True, visible_only: bool = True, sources: str = "", background_mode: str = "automatic", background_layer_id: str = "", locator_mode: str = "automatic") -> AutomationExecutionResult:
        if variant_index < 0 or variant_index >= len(plan.variants): raise CartomizeError("Proposition Cartomize inexistante.")
        variant = plan.variants[variant_index]; layers = [layer for map_item in self.project.listMaps() for layer in map_item.listLayers() if _key(layer) in plan.layer_ids]
        styling = self.styling.apply_project(layers, main_layer_id=plan.main_layer_id, objective=plan.objective) if apply_symbology else ()
        spec = self.catalog.get(variant.template_id)
        options = LayoutBuildOptions(variant.title, variant.subtitle, sources=sources, visible_layers_only=visible_only, extent_margin_percent=variant.margin_percent, add_grid=variant.add_grid, requested_name=f"Cartomize — {variant.name}", layer_ids=plan.layer_ids, main_layer_id=plan.main_layer_id, background_mode=background_mode, background_layer_id=background_layer_id, locator_mode=locator_mode)
        built = self.builder.build(spec, options); optimizer = AdaptiveLayoutOptimizer(self.builder)
        if auto_correct: layout_report = optimizer.optimize(built.layout)
        else:
            score, findings = optimizer.analyze(built.layout); from .layout_intelligence import LayoutOptimizationReport; layout_report = LayoutOptimizationReport(score, score, 0, (), findings)
        project_report = self.auditor.run(layers); final = round((layout_report.after_score + project_report.score + 100 * plan.confidence) / 3)
        recipe = AutomationRecipe(1, APP_VERSION, datetime.now(timezone.utc).isoformat(), plan.objective, plan.main_layer_id, plan.main_layer_name, plan.layer_ids, tuple(item.name for item in plan.layers), variant.to_dict(), apply_symbology, auto_correct, visible_only, sources, background_mode, background_layer_id, locator_mode)
        HumanValidationService(self.project, APP_VERSION).draft(built.layout, final, [item.message for item in layout_report.findings if item.severity == "critical"])
        return AutomationExecutionResult(built.layout, built.layout_name, variant.name, layout_report.after_score, project_report.score, final, layout_report.corrections, tuple((*plan.warnings, *built.warnings)), recipe, tuple(styling), "En attente", project_report.score, layout_report.after_score, round(100 * plan.confidence))

    def replay_recipe(self, recipe: AutomationRecipe):
        variant = dict(recipe.variant); spec = self.catalog.get(str(variant.get("template_id")))
        options = LayoutBuildOptions(str(variant.get("title") or variant.get("name") or spec.name), str(variant.get("subtitle") or ""), sources=recipe.sources, visible_layers_only=recipe.visible_only, extent_margin_percent=float(variant.get("margin_percent", 3)), add_grid=bool(variant.get("add_grid", False)), requested_name=f"Cartomize — {variant.get('name') or spec.name}", layer_ids=recipe.layer_ids, main_layer_id=recipe.main_layer_id, background_mode=recipe.background_mode, background_layer_id=recipe.background_layer_id, locator_mode=recipe.locator_mode)
        return self.builder.build(spec, options)

    @staticmethod
    def save_recipe(recipe: AutomationRecipe, path: str | Path):
        target = Path(path).expanduser().resolve(); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(json.dumps(recipe.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"); return target
    @staticmethod
    def load_recipe(path: str | Path): return AutomationRecipe.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _variants(templates, objective: str, label: str, style_profile: str):
    preferred = [item for item in templates if objective != "auto" and objective in item.template_id]
    fallback = templates or preferred
    choices = []
    seen = set()
    for item in (*preferred, *fallback):
        if item.template_id in seen:
            continue
        seen.add(item.template_id)
        choices.append(item)
        if len(choices) == 3:
            break
    names = ("Institutionnelle", "Analytique", "Minimaliste")
    return tuple(AutomationVariant(("institutional", "analytical", "minimal")[i], names[i], item.template_id, item.name, item.page_format, style_profile, 92 - i*4, label.upper(), label, 3.0 + i, objective in {"topographique", "atlas"}, ("Maquette Cartomize compatible avec l'objectif.",)) for i, item in enumerate(choices))
def _key(layer): return str(getattr(layer, "URI", "") or getattr(layer, "name", "") or layer)
def _import_arcpy():
    try:
        import arcpy; return arcpy
    except ImportError as exc: raise CartomizeError("ArcPy est requis pour l'automatisation.") from exc
