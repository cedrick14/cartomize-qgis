"""Automatisation explicable de la production cartographique dans QGIS."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable

from qgis.core import (
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLayoutItemScaleBar,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)

from .constants import PLUGIN_VERSION
from .errors import CartomizeError
from .layout_builder import LayoutBuildOptions, LayoutBuilder
from .project_service import ProjectService
from .quality import ProjectQualityAuditor
from .symbology import SmartSymbologyService
from .project_styling import ProjectStylingOrchestrator, StylingDecision
from .human_validation import HumanValidationService
from .geo_intelligence import GeoIntelligenceEngine
from .layout_intelligence import AdaptiveLayoutOptimizer
from .template_catalog import TemplateCatalog, TemplateSpec


OBJECTIVES: tuple[tuple[str, str], ...] = (
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

STYLE_PROFILES: tuple[tuple[str, str], ...] = (
    ("balanced", "Équilibré"),
    ("institutional", "Institutionnel"),
    ("analytical", "Analytique"),
    ("minimal", "Minimaliste"),
)

_OBJECTIVE_LABELS = dict(OBJECTIVES)
_STYLE_LABELS = dict(STYLE_PROFILES)

_INTENT_RULES: dict[str, tuple[str, ...]] = {
    "administrative": ("administr", "province", "departement", "district", "commune", "limite", "boundary"),
    "amenagement": ("amenagement", "planification", "schema", "zonage", "territoire", "planning"),
    "occupation_sol": ("occupation", "land cover", "landcover", "lulc", "couverture", "classe", "classification"),
    "risques": ("risque", "hazard", "alea", "inond", "flood", "incend", "vulnerab", "susceptibil"),
    "hydrologique": ("hydro", "riv", "fleuve", "bassin", "watershed", "drainage", "eau", "lake"),
    "environnement": ("foret", "forest", "climat", "environment", "fragment", "carbone", "ndvi", "ecosystem"),
    "agriculture": ("agric", "culture", "crop", "sol", "aptitude", "rendement", "pasture"),
    "transport": ("route", "road", "rail", "transport", "access", "reseau", "network"),
    "urbanisme": ("urbain", "urban", "bati", "building", "parcelle", "cadastre", "ville", "city"),
    "demographie": ("population", "densite", "density", "menage", "census", "demograph"),
    "biodiversite": ("biodivers", "habitat", "espece", "species", "connectiv", "corridor"),
    "energie": ("energie", "electric", "power", "reseau elect", "solaire", "hydroelec"),
    "sante": ("sante", "health", "hopital", "centre de sante", "maladie", "disease"),
    "humanitaire": ("humanitaire", "urgence", "refug", "deplace", "crise", "emergency"),
    "scientifique": ("scientifique", "article", "research", "etude", "study", "analyse", "resultat"),
    "topographique": ("topograph", "mnt", "dem", "elevation", "altitude", "courbe", "contour", "relief"),
    "atlas": ("atlas", "serie", "territorial", "couverture nationale", "multi page"),
}

_CATEGORY_FALLBACKS: dict[str, tuple[str, ...]] = {
    "administrative": ("administrative", "atlas"),
    "amenagement": ("amenagement", "administrative"),
    "occupation_sol": ("occupation_sol", "environnement"),
    "risques": ("risques", "humanitaire"),
    "hydrologique": ("hydrologique", "environnement"),
    "environnement": ("environnement", "occupation_sol"),
    "agriculture": ("agriculture", "occupation_sol"),
    "transport": ("transport", "urbanisme"),
    "urbanisme": ("urbanisme", "administrative"),
    "demographie": ("demographie", "administrative"),
    "biodiversite": ("biodiversite", "environnement"),
    "energie": ("energie", "amenagement"),
    "sante": ("sante", "demographie"),
    "humanitaire": ("humanitaire", "risques"),
    "scientifique": ("scientifique", "environnement"),
    "topographique": ("topographique", "administrative"),
    "atlas": ("atlas", "administrative"),
}


@dataclass(frozen=True)
class LayerProfile:
    layer_id: str
    name: str
    layer_type: str
    crs: str
    visible: bool
    feature_count: int | None = None
    band_count: int | None = None
    categorical_fields: tuple[str, ...] = ()
    numeric_fields: tuple[str, ...] = ()
    label_field: str = ""


@dataclass(frozen=True)
class AutomationVariant:
    variant_id: str
    name: str
    template_id: str
    template_name: str
    page_format: str
    style_profile: str
    score: int
    title: str
    subtitle: str
    margin_percent: float
    add_grid: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AutomationPlan:
    generated_at: str
    objective: str
    objective_label: str
    confidence: float
    main_layer_id: str
    main_layer_name: str
    layer_ids: tuple[str, ...]
    project_crs: str
    map_type_reason: str
    warnings: tuple[str, ...]
    layers: tuple[LayerProfile, ...]
    variants: tuple[AutomationVariant, ...]
    intelligence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "objective": self.objective,
            "objective_label": self.objective_label,
            "confidence": self.confidence,
            "main_layer_id": self.main_layer_id,
            "main_layer_name": self.main_layer_name,
            "layer_ids": list(self.layer_ids),
            "project_crs": self.project_crs,
            "map_type_reason": self.map_type_reason,
            "warnings": list(self.warnings),
            "layers": [asdict(item) for item in self.layers],
            "variants": [item.to_dict() for item in self.variants],
            "intelligence": dict(self.intelligence),
        }


@dataclass(frozen=True)
class AutomationRecipe:
    schema_version: int
    cartomize_version: str
    created_at: str
    objective: str
    main_layer_id: str
    main_layer_name: str
    layer_ids: tuple[str, ...]
    layer_names: tuple[str, ...]
    variant: dict[str, Any]
    apply_symbology: bool
    auto_correct: bool
    visible_only: bool
    sources: str

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["layer_ids"] = list(self.layer_ids)
        result["layer_names"] = list(self.layer_names)
        return result

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AutomationRecipe":
        if not isinstance(payload, dict) or int(payload.get("schema_version", 0)) != 1:
            raise CartomizeError("Le fichier de recette Cartomize est invalide ou incompatible.")
        variant = payload.get("variant")
        if not isinstance(variant, dict) or not variant.get("template_id"):
            raise CartomizeError("La recette ne contient aucune maquette valide.")
        return cls(
            schema_version=1,
            cartomize_version=str(payload.get("cartomize_version") or ""),
            created_at=str(payload.get("created_at") or ""),
            objective=str(payload.get("objective") or "auto"),
            main_layer_id=str(payload.get("main_layer_id") or ""),
            main_layer_name=str(payload.get("main_layer_name") or ""),
            layer_ids=tuple(str(item) for item in payload.get("layer_ids", [])[:2000]),
            layer_names=tuple(str(item) for item in payload.get("layer_names", [])[:2000]),
            variant=dict(variant),
            apply_symbology=bool(payload.get("apply_symbology", True)),
            auto_correct=bool(payload.get("auto_correct", True)),
            visible_only=bool(payload.get("visible_only", True)),
            sources=str(payload.get("sources") or "")[:2000],
        )


@dataclass(frozen=True)
class AutomationExecutionResult:
    layout: Any
    layout_name: str
    variant_name: str
    layout_score: int
    project_score: int
    final_score: int
    corrections: tuple[str, ...]
    warnings: tuple[str, ...]
    recipe: AutomationRecipe
    styling: tuple[StylingDecision, ...] = ()
    validation_status: str = "En attente"
    data_quality_score: int = 0
    cartographic_score: int = 0
    automation_confidence: int = 0


class CartomizeAutopilot:
    """Analyse le projet, planifie une carte et orchestre les moteurs QGIS natifs."""

    def __init__(
        self,
        iface,
        catalog: TemplateCatalog,
        project: QgsProject | None = None,
        builder: LayoutBuilder | None = None,
        symbology: SmartSymbologyService | None = None,
        auditor: ProjectQualityAuditor | None = None,
    ):
        self.iface = iface
        self.project = project or QgsProject.instance()
        self.catalog = catalog
        self.project_service = ProjectService(iface, self.project)
        self.builder = builder or LayoutBuilder(iface, self.project)
        self.symbology = symbology or SmartSymbologyService(self.project)
        self.auditor = auditor or ProjectQualityAuditor(self.project)
        self.styling = ProjectStylingOrchestrator(self.project, self.symbology)
        self.validator = HumanValidationService(self.project, PLUGIN_VERSION)
        self.geo = GeoIntelligenceEngine(iface, self.project)
        self.layout_optimizer = AdaptiveLayoutOptimizer(self.builder)

    def analyze(
        self,
        objective: str = "auto",
        main_layer_id: str = "",
        style_profile: str = "balanced",
        visible_only: bool = True,
    ) -> AutomationPlan:
        layers = (
            self.project_service.visible_layers()
            if visible_only
            else self.project_service.ordered_layers()
        )
        layers = [layer for layer in layers if layer and layer.isValid()]
        if not layers:
            raise CartomizeError("Chargez au moins une couche valide avant de lancer l’automatisation.")

        visible_ids = {layer.id() for layer in self.project_service.visible_layers()}
        profiles = tuple(self._profile_layer(layer, layer.id() in visible_ids) for layer in layers)
        main = self._select_main_layer(layers, main_layer_id)
        detected, confidence, reason = self._detect_objective(objective, profiles, main)
        geo_report = self.geo.analyze(layers, main_layer_id=main.id(), objective=detected)
        warnings = tuple(dict.fromkeys((*self._project_warnings(layers), *geo_report.warnings)))
        variants = self._build_variants(detected, style_profile, main, profiles, geo_report)
        variants = self._apply_memory_preferences(variants, detected, geo_report.memory_suggestions)
        crs = self.project_service.display_crs(layers)
        return AutomationPlan(
            generated_at=_utc_now(),
            objective=detected,
            objective_label=_OBJECTIVE_LABELS.get(detected, detected.replace("_", " ").title()),
            confidence=confidence,
            main_layer_id=main.id(),
            main_layer_name=main.name(),
            layer_ids=tuple(layer.id() for layer in layers),
            project_crs=crs.authid() or crs.description() or "Non défini",
            map_type_reason=reason,
            warnings=warnings,
            layers=profiles,
            variants=variants,
            intelligence=geo_report.to_dict(),
        )

    def execute_variant(
        self,
        plan: AutomationPlan,
        variant_index: int,
        *,
        apply_symbology: bool = True,
        auto_correct: bool = True,
        visible_only: bool = True,
        sources: str = "",
    ) -> AutomationExecutionResult:
        if not plan.variants:
            raise CartomizeError("Le plan ne contient aucune proposition cartographique.")
        index = max(0, min(len(plan.variants) - 1, int(variant_index)))
        variant = plan.variants[index]
        spec = self.catalog.get(variant.template_id)
        main = self.project.mapLayer(plan.main_layer_id)
        warnings: list[str] = []
        styling_decisions: tuple[StylingDecision, ...] = ()
        project_layers = [self.project.mapLayer(layer_id) for layer_id in plan.layer_ids]
        project_layers = [layer for layer in project_layers if layer is not None and layer.isValid()]
        geo_report = self.geo.analyze(project_layers, main_layer_id=plan.main_layer_id, objective=plan.objective)

        if apply_symbology:
            try:
                styling_decisions = self.styling.apply_project(
                    project_layers,
                    main_layer_id=plan.main_layer_id,
                    objective=plan.objective,
                    force=True,
                    roles=geo_report.roles,
                    vector_profiles={item.layer_id: item for item in geo_report.vector_profiles},
                )
                label_changes = self.geo.apply_labeling(geo_report)
                if label_changes:
                    warnings.append("Étiquetage intelligent : " + ", ".join(label_changes[:8]))
                for decision in styling_decisions:
                    if decision.warning:
                        warnings.append(f"{decision.layer_name} : {decision.warning}")
            except Exception as exc:
                warnings.append(f"Symbologie automatique partielle : {exc}")

        options = LayoutBuildOptions(
            title=variant.title,
            subtitle=variant.subtitle,
            sources=sources,
            visible_layers_only=visible_only,
            extent_margin_percent=variant.margin_percent,
            add_grid=variant.add_grid,
            requested_name=f"Cartomize Autopilot. {variant.name}. {variant.title}",
            open_designer=False,
            layer_ids=plan.layer_ids,
            main_layer_id=plan.main_layer_id,
        )
        result = self.builder.build(spec, options)
        warnings.extend(result.warnings)
        layout = result.layout
        layout.setCustomProperty("cartomize/autopilot", True)
        layout.setCustomProperty("cartomize/autopilot_objective", plan.objective)
        layout.setCustomProperty("cartomize/autopilot_variant", variant.variant_id)
        layout.setCustomProperty("cartomize/autopilot_confidence", plan.confidence)
        try:
            scale_label_changes = self.geo.apply_layout_scale(layout, geo_report)
            if scale_label_changes:
                warnings.append("Échelle réelle du cadre : " + ", ".join(scale_label_changes[:8]))
        except Exception as exc:
            warnings.append(f"Intelligence d’échelle partielle : {exc}")
        layout.setCustomProperty(
            "cartomize/geo_intelligence",
            json.dumps(
                {
                    "data_quality_score": geo_report.data_quality_score,
                    "automation_confidence": geo_report.automation_confidence,
                    "roles": geo_report.roles,
                    "relationship_count": len(geo_report.graph.relations),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )

        corrections: tuple[str, ...] = ()
        base_layout_score = self._score_layout(layout)
        layout_intel_score, _layout_findings = self.layout_optimizer.analyze(layout)
        if auto_correct:
            try:
                optimization = self.layout_optimizer.optimize(layout, max_passes=3, target_score=94)
                corrections = optimization.corrections
                layout_intel_score = optimization.after_score
            except Exception as exc:
                warnings.append(f"Autocorrection partielle : {exc}")
        structural_score = self._score_layout(layout)
        layout_score = max(0, min(100, round(structural_score * 0.55 + layout_intel_score * 0.45)))
        project_report = self.auditor.run(self.project_service.ordered_layers())
        project_score = int(project_report.score)
        data_quality_score = max(0, min(100, round(project_score * 0.55 + geo_report.data_quality_score * 0.45)))
        automation_confidence = max(0, min(100, round((plan.confidence * 100) * 0.55 + geo_report.automation_confidence * 0.45)))
        for finding in project_report.findings:
            if finding.severity not in {"critical", "high"}:
                continue
            message = finding.message
            if finding.layer_name:
                message = f"{finding.layer_name} : {message}"
            warnings.append(message)
            if len(warnings) >= 8:
                break
        final_score = max(0, min(100, round(layout_score * 0.50 + data_quality_score * 0.30 + automation_confidence * 0.20)))
        blockers = []
        for finding in project_report.findings:
            if finding.severity == "critical":
                blockers.append(finding.message if not finding.layer_name else f"{finding.layer_name} : {finding.message}")
        validation = self.validator.draft(layout, final_score, blockers)
        layout.setCustomProperty("cartomize/automatic_score", final_score)
        layout.setCustomProperty("cartomize/data_quality_score", data_quality_score)
        layout.setCustomProperty("cartomize/cartographic_score", layout_score)
        layout.setCustomProperty("cartomize/automation_confidence", automation_confidence)
        layout.setCustomProperty("cartomize/automatic_score_notice", "Scores automatiques distincts. Validation cartographe requise.")

        recipe = self._recipe_from_execution(
            plan,
            variant,
            apply_symbology,
            auto_correct,
            visible_only,
            sources,
        )
        _write_project_entry(
            self.project,
            "autopilot_last_recipe",
            json.dumps(recipe.to_dict(), ensure_ascii=False),
        )
        _write_project_entry(self.project, "autopilot_last_score", final_score)
        self.project.setDirty(True)
        return AutomationExecutionResult(
            layout=layout,
            layout_name=result.layout_name,
            variant_name=variant.name,
            layout_score=layout_score,
            project_score=project_score,
            final_score=final_score,
            corrections=corrections,
            warnings=tuple(warnings),
            recipe=recipe,
            styling=styling_decisions,
            validation_status=validation.human_status,
            data_quality_score=data_quality_score,
            cartographic_score=layout_score,
            automation_confidence=automation_confidence,
        )

    def replay_recipe(self, recipe: AutomationRecipe) -> AutomationExecutionResult:
        layer_ids = self._resolve_recipe_layers(recipe)
        main_layer_id = recipe.main_layer_id
        if self.project.mapLayer(main_layer_id) is None:
            main_layer_id = self._layer_id_by_name(recipe.main_layer_name) or (layer_ids[0] if layer_ids else "")
        objective = recipe.objective if recipe.objective in _OBJECTIVE_LABELS else "auto"
        plan = self.analyze(
            objective=objective,
            main_layer_id=main_layer_id,
            style_profile=str(recipe.variant.get("style_profile") or "balanced"),
            visible_only=recipe.visible_only,
        )
        if layer_ids:
            plan = AutomationPlan(
                generated_at=plan.generated_at,
                objective=plan.objective,
                objective_label=plan.objective_label,
                confidence=plan.confidence,
                main_layer_id=main_layer_id or plan.main_layer_id,
                main_layer_name=recipe.main_layer_name or plan.main_layer_name,
                layer_ids=tuple(layer_ids),
                project_crs=plan.project_crs,
                map_type_reason="Recette Cartomize rejouée avec les couches disponibles.",
                warnings=plan.warnings,
                layers=tuple(item for item in plan.layers if item.layer_id in set(layer_ids)),
                variants=plan.variants,
                intelligence=plan.intelligence,
            )
        requested_template = str(recipe.variant.get("template_id") or "")
        matching = next((i for i, item in enumerate(plan.variants) if item.template_id == requested_template), 0)
        if requested_template and all(item.template_id != requested_template for item in plan.variants):
            spec = self.catalog.get(requested_template)
            restored = AutomationVariant(
                variant_id="recipe",
                name=str(recipe.variant.get("name") or "Recette"),
                template_id=spec.template_id,
                template_name=spec.name,
                page_format=spec.page_format,
                style_profile=str(recipe.variant.get("style_profile") or "balanced"),
                score=int(recipe.variant.get("score") or 85),
                title=str(recipe.variant.get("title") or _suggest_title(objective, recipe.main_layer_name)),
                subtitle=str(recipe.variant.get("subtitle") or "Carte générée à partir d’une recette Cartomize"),
                margin_percent=float(recipe.variant.get("margin_percent") or 3.0),
                add_grid=bool(recipe.variant.get("add_grid", False)),
                reasons=("Maquette restaurée depuis la recette.",),
            )
            plan = AutomationPlan(
                generated_at=plan.generated_at,
                objective=plan.objective,
                objective_label=plan.objective_label,
                confidence=plan.confidence,
                main_layer_id=main_layer_id,
                main_layer_name=recipe.main_layer_name or plan.main_layer_name,
                layer_ids=tuple(layer_ids or plan.layer_ids),
                project_crs=plan.project_crs,
                map_type_reason="Recette Cartomize rejouée.",
                warnings=plan.warnings,
                layers=plan.layers,
                variants=(restored,),
                intelligence=plan.intelligence,
            )
            matching = 0
        return self.execute_variant(
            plan,
            matching,
            apply_symbology=recipe.apply_symbology,
            auto_correct=recipe.auto_correct,
            visible_only=recipe.visible_only,
            sources=recipe.sources,
        )

    def save_recipe(self, recipe: AutomationRecipe, path: str | Path) -> Path:
        destination = Path(path).expanduser().resolve()
        if destination.suffix.lower() != ".json":
            destination = destination.with_suffix(".cartomize.json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(recipe.to_dict(), ensure_ascii=False, indent=2)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(payload)
            handle.flush()
            temporary = Path(handle.name)
        temporary.replace(destination)
        return destination

    def load_recipe(self, path: str | Path) -> AutomationRecipe:
        source = Path(path).expanduser().resolve()
        if not source.is_file() or source.stat().st_size > 1_000_000:
            raise CartomizeError("Le fichier de recette est introuvable ou trop volumineux.")
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CartomizeError("Le fichier de recette n’est pas un JSON Cartomize valide.") from exc
        return AutomationRecipe.from_dict(payload)

    def _profile_layer(self, layer, visible: bool) -> LayerProfile:
        if isinstance(layer, QgsVectorLayer):
            categorical: list[str] = []
            numeric: list[str] = []
            for field in list(layer.fields())[:250]:
                if field.isNumeric():
                    numeric.append(field.name())
                elif not field.isDateOrTime():
                    categorical.append(field.name())
            try:
                recommendation = self.symbology.recommend(layer)
                label_field = recommendation.label_field
            except Exception:
                label_field = categorical[0] if categorical else ""
            try:
                count = int(layer.featureCount())
            except Exception:
                count = None
            return LayerProfile(
                layer_id=layer.id(),
                name=layer.name(),
                layer_type="vector",
                crs=layer.crs().authid() or layer.crs().description() or "Non défini",
                visible=visible,
                feature_count=count,
                categorical_fields=tuple(categorical[:20]),
                numeric_fields=tuple(numeric[:20]),
                label_field=label_field,
            )
        if isinstance(layer, QgsRasterLayer):
            try:
                bands = int(layer.bandCount())
            except Exception:
                bands = None
            return LayerProfile(
                layer_id=layer.id(),
                name=layer.name(),
                layer_type="raster",
                crs=layer.crs().authid() or layer.crs().description() or "Non défini",
                visible=visible,
                band_count=bands,
            )
        return LayerProfile(
            layer_id=layer.id(),
            name=layer.name(),
            layer_type="other",
            crs=layer.crs().authid() or layer.crs().description() or "Non défini",
            visible=visible,
        )

    def _select_main_layer(self, layers: list, requested_id: str):
        if requested_id:
            requested = next((layer for layer in layers if layer.id() == requested_id), None)
            if requested is not None:
                return requested
        active = self.iface.activeLayer()
        if active is not None and active in layers:
            return active
        scored = sorted(layers, key=self._main_layer_score, reverse=True)
        return scored[0]

    @staticmethod
    def _main_layer_score(layer) -> float:
        score = 0.0
        if isinstance(layer, QgsRasterLayer):
            score += 8.0
        if isinstance(layer, QgsVectorLayer):
            score += 10.0
            try:
                score += min(5.0, max(0.0, float(layer.featureCount())) / 20_000.0)
            except Exception:
                pass
        name = layer.name().casefold()
        if any(token in name for token in ("limite", "boundary", "fond", "basemap", "grille")):
            score -= 4.0
        return score

    def _detect_objective(
        self,
        requested: str,
        profiles: tuple[LayerProfile, ...],
        main,
    ) -> tuple[str, float, str]:
        if requested and requested != "auto" and requested in _OBJECTIVE_LABELS:
            return requested, 0.99, "Objectif choisi explicitement par l’utilisateur."
        main_corpus = main.name().casefold()
        project_corpus = " ".join(
            [profile.name for profile in profiles]
            + [field for profile in profiles for field in (*profile.categorical_fields, *profile.numeric_fields)]
        ).casefold()
        scores: dict[str, int] = {key: 0 for key in _INTENT_RULES}
        matched: dict[str, list[str]] = {key: [] for key in _INTENT_RULES}
        for objective, tokens in _INTENT_RULES.items():
            for token in tokens:
                if token in main_corpus:
                    scores[objective] += 3
                    matched[objective].append(token)
                elif token in project_corpus:
                    scores[objective] += 1
                    matched[objective].append(token)
        if isinstance(main, QgsRasterLayer):
            scores["occupation_sol"] += 2
            scores["topographique"] += 1
        if len(profiles) >= 8:
            scores["atlas"] += 1
        best = max(scores, key=scores.get)
        best_score = scores[best]
        if best_score == 0:
            best = "scientifique" if len(profiles) > 3 else "administrative"
            return best, 0.56, "Aucun mot-clé dominant. Le choix repose sur la structure du projet."
        second = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0
        confidence = min(0.96, 0.62 + best_score * 0.06 + max(0, best_score - second) * 0.03)
        tokens = ", ".join(list(dict.fromkeys(matched[best]))[:5])
        return best, confidence, f"Indices détectés dans les couches et les champs : {tokens}."

    def _build_variants(
        self,
        objective: str,
        style_profile: str,
        main,
        profiles: tuple[LayerProfile, ...],
        geo_report=None,
    ) -> tuple[AutomationVariant, ...]:
        templates = self.catalog.all()
        requested_style = style_profile if style_profile in _STYLE_LABELS else "balanced"
        variant_defs = [
            ("institutional", "Institutionnelle", True, 4.0),
            ("analytical", "Analytique", True, 3.0),
            ("minimal", "Minimaliste", False, 2.0),
        ]
        if requested_style != "balanced":
            variant_defs.sort(key=lambda item: item[0] != requested_style)
        used: set[str] = set()
        output: list[AutomationVariant] = []
        main_aspect = self._layer_aspect_ratio(main)
        layer_count = len(profiles)
        legend_complexity = self._legend_complexity(geo_report)
        for variant_style, name, grid, margin in variant_defs:
            effective_style = variant_style
            ranked = sorted(
                (self._score_template(spec, objective, effective_style, main_aspect, layer_count, legend_complexity) for spec in templates),
                key=lambda item: (item[1], item[0].name.casefold()),
                reverse=True,
            )
            chosen = next((item for item in ranked if item[0].template_id not in used), ranked[0])
            spec, score, reasons = chosen
            if requested_style != "balanced" and variant_style == requested_style:
                score = min(100, score + 4)
                reasons = tuple(reasons) + ("Cette proposition correspond à l’orientation graphique choisie.",)
            used.add(spec.template_id)
            title = _suggest_title(objective, main.name())
            subtitle = self._suggest_subtitle(objective, effective_style, profiles)
            output.append(
                AutomationVariant(
                    variant_id=variant_style,
                    name=name,
                    template_id=spec.template_id,
                    template_name=spec.name,
                    page_format=spec.page_format,
                    style_profile=effective_style,
                    score=score,
                    title=title,
                    subtitle=subtitle,
                    margin_percent=margin,
                    add_grid=grid and objective != "scientifique",
                    reasons=reasons,
                )
            )
        return tuple(output)

    def _score_template(
        self,
        spec: TemplateSpec,
        objective: str,
        style_profile: str,
        main_aspect: float = 1.0,
        layer_count: int = 1,
        legend_complexity: int = 0,
    ) -> tuple[TemplateSpec, int, tuple[str, ...]]:
        score = 35
        reasons: list[str] = []
        accepted_categories = _CATEGORY_FALLBACKS.get(objective, (objective,))
        if spec.category == accepted_categories[0]:
            score += 42
            reasons.append("Catégorie directement adaptée à l’objectif.")
        elif spec.category in accepted_categories[1:]:
            score += 22
            reasons.append("Catégorie complémentaire adaptée au projet.")
        searchable = " ".join((spec.name, spec.variant, spec.description, *spec.tags)).casefold()
        style_tokens = {
            "institutional": ("institution", "officiel", "atlas"),
            "analytical": ("scient", "analyse", "article", "a3"),
            "minimal": ("minimal", "epure", "portrait", "a4"),
            "balanced": ("standard", "institution", "a4"),
        }.get(style_profile, ())
        if any(token in searchable for token in style_tokens):
            score += 12
            reasons.append(f"Présentation {_STYLE_LABELS.get(style_profile, style_profile).lower()} cohérente.")
        if spec.map_count > 1 and objective in {"atlas", "administrative", "risques"}:
            score += 7
            reasons.append("La carte de localisation renforce la lecture territoriale.")
        if spec.page_format.startswith("A3") and style_profile == "analytical":
            score += 5
            reasons.append("Le format A3 réserve davantage de place aux analyses.")
        if spec.page_format.startswith("A4") and style_profile == "minimal":
            score += 5
            reasons.append("Le format A4 convient à une diffusion concise.")
        page_text = spec.page_format.casefold()
        if main_aspect >= 1.35 and "paysage" in page_text:
            score += 7
            reasons.append("L’orientation paysage correspond à l’emprise principale, plus large que haute.")
        elif main_aspect <= 0.74 and "portrait" in page_text:
            score += 7
            reasons.append("L’orientation portrait correspond à l’emprise principale, plus haute que large.")
        elif 0.85 <= main_aspect <= 1.18:
            score += 2
        if layer_count >= 10 and spec.page_format.startswith("A3"):
            score += 5
            reasons.append("Le projet comporte de nombreuses couches et bénéficie d’un format plus spacieux.")
        elif layer_count <= 4 and spec.page_format.startswith("A4"):
            score += 3
        if legend_complexity >= 14 and spec.page_format.startswith("A3"):
            score += 7
            reasons.append("La légende comporte de nombreuses classes et nécessite davantage d’espace.")
        elif legend_complexity >= 9 and spec.page_format.startswith("A4"):
            score -= 3
        score = max(45, min(99, score))
        if not reasons:
            reasons.append("Maquette compatible avec la structure actuelle du projet.")
        return spec, score, tuple(reasons)

    @staticmethod
    def _legend_complexity(geo_report) -> int:
        if geo_report is None:
            return 0
        complexity = 0
        try:
            complexity = max([item.class_count for item in geo_report.raster_summaries] or [0])
        except Exception:
            pass
        try:
            for profile in geo_report.vector_profiles:
                field = next((item for item in profile.fields if item.name == profile.thematic_field), None)
                if field is not None and field.semantic_role in {"category", "coded_category", "ordinal"}:
                    complexity = max(complexity, min(40, int(field.unique_count)))
        except Exception:
            pass
        return complexity

    @staticmethod
    def _layer_aspect_ratio(layer) -> float:
        try:
            extent = layer.extent()
            width = float(extent.width())
            height = float(extent.height())
            if width > 0 and height > 0:
                return width / height
        except Exception:
            pass
        return 1.0

    def _apply_memory_preferences(
        self,
        variants: tuple[AutomationVariant, ...],
        objective: str,
        suggestions: tuple[str, ...],
    ) -> tuple[AutomationVariant, ...]:
        template_pref = self.geo.memory.suggest(objective, "template_id")
        style_pref = self.geo.memory.suggest(objective, "style_profile")
        page_pref = self.geo.memory.suggest(objective, "page_format")
        adjusted: list[AutomationVariant] = []
        for variant in variants:
            bonus = 0
            reasons = list(variant.reasons)
            if template_pref and template_pref.confidence >= 0.6 and variant.template_id == template_pref.value:
                bonus += 4
                reasons.append("Cette maquette correspond à vos choix locaux précédemment validés.")
            if style_pref and style_pref.confidence >= 0.6 and variant.style_profile == style_pref.value:
                bonus += 2
            if page_pref and page_pref.confidence >= 0.65 and variant.page_format == page_pref.value:
                bonus += 2
                reasons.append("Le format correspond à vos validations locales précédentes.")
            adjusted.append(
                AutomationVariant(
                    variant.variant_id, variant.name, variant.template_id, variant.template_name,
                    variant.page_format, variant.style_profile, min(100, variant.score + bonus),
                    variant.title, variant.subtitle, variant.margin_percent, variant.add_grid, tuple(reasons),
                )
            )
        return tuple(sorted(adjusted, key=lambda item: item.score, reverse=True))

    def _project_warnings(self, layers: list) -> tuple[str, ...]:
        warnings: list[str] = []
        if not self.project.crs().isValid():
            warnings.append("Le CRS du projet doit être confirmé avant publication.")
        missing = [layer.name() for layer in layers if not layer.crs().isValid()]
        if missing:
            warnings.append(f"CRS absent pour {len(missing)} couche(s).")
        if not self.project.fileName():
            warnings.append("Le projet QGIS n’est pas encore enregistré.")
        return tuple(warnings)

    @staticmethod
    def _suggest_subtitle(
        objective: str,
        style_profile: str,
        profiles: tuple[LayerProfile, ...],
    ) -> str:
        layer_types = {profile.layer_type for profile in profiles}
        data_phrase = "données vectorielles et raster" if {"vector", "raster"} <= layer_types else "données du projet QGIS"
        style = _STYLE_LABELS.get(style_profile, style_profile)
        return f"{_OBJECTIVE_LABELS.get(objective, 'Analyse cartographique')}. Composition {style.lower()} fondée sur les {data_phrase}."

    @staticmethod
    def _score_layout(layout) -> int:
        score = 20
        items = list(layout.items())
        maps = [item for item in items if isinstance(item, QgsLayoutItemMap)]
        legends = [item for item in items if isinstance(item, QgsLayoutItemLegend)]
        scales = [item for item in items if isinstance(item, QgsLayoutItemScaleBar)]
        labels = [item for item in items if isinstance(item, QgsLayoutItemLabel)]
        score += min(28, len(maps) * 18)
        if legends:
            score += 14
            if any(getattr(item, "linkedMap", lambda: None)() is not None for item in legends):
                score += 5
        if scales:
            score += 12
            if any(getattr(item, "linkedMap", lambda: None)() is not None for item in scales):
                score += 4
        if labels:
            score += 9
        if maps and any(_map_item_has_layers(item) for item in maps):
            score += 8
        return max(0, min(100, score))

    def _recipe_from_execution(
        self,
        plan: AutomationPlan,
        variant: AutomationVariant,
        apply_symbology: bool,
        auto_correct: bool,
        visible_only: bool,
        sources: str,
    ) -> AutomationRecipe:
        names = []
        for layer_id in plan.layer_ids:
            layer = self.project.mapLayer(layer_id)
            names.append(layer.name() if layer is not None else "")
        return AutomationRecipe(
            schema_version=1,
            cartomize_version=PLUGIN_VERSION,
            created_at=_utc_now(),
            objective=plan.objective,
            main_layer_id=plan.main_layer_id,
            main_layer_name=plan.main_layer_name,
            layer_ids=plan.layer_ids,
            layer_names=tuple(names),
            variant=variant.to_dict(),
            apply_symbology=apply_symbology,
            auto_correct=auto_correct,
            visible_only=visible_only,
            sources=sources,
        )

    def _resolve_recipe_layers(self, recipe: AutomationRecipe) -> list[str]:
        resolved = [layer_id for layer_id in recipe.layer_ids if self.project.mapLayer(layer_id) is not None]
        for name in recipe.layer_names:
            layer_id = self._layer_id_by_name(name)
            if layer_id and layer_id not in resolved:
                resolved.append(layer_id)
        if not resolved:
            resolved = [layer.id() for layer in self.project_service.visible_layers()]
        return resolved

    def _layer_id_by_name(self, name: str) -> str:
        if not name:
            return ""
        for layer in self.project.mapLayersByName(name):
            if layer and layer.isValid():
                return layer.id()
        return ""


def _suggest_title(objective: str, layer_name: str) -> str:
    clean = re.sub(r"[_-]+", " ", str(layer_name or "")).strip()
    clean = " ".join(clean.split()) or "Territoire étudié"
    labels = {
        "administrative": "Organisation administrative",
        "amenagement": "Aménagement du territoire",
        "occupation_sol": "Occupation du sol",
        "risques": "Analyse des risques",
        "hydrologique": "Réseau hydrographique",
        "environnement": "Analyse environnementale",
        "agriculture": "Aptitude et activités agricoles",
        "transport": "Accessibilité et réseaux de transport",
        "urbanisme": "Structure et développement urbains",
        "demographie": "Répartition de la population",
        "biodiversite": "Biodiversité et connectivité écologique",
        "energie": "Infrastructure et accès à l’énergie",
        "sante": "Accessibilité aux services de santé",
        "humanitaire": "Situation humanitaire",
        "scientifique": "Résultats cartographiques",
        "topographique": "Relief et topographie",
        "atlas": "Atlas territorial",
    }
    prefix = labels.get(objective, "Carte thématique")
    return f"{prefix}. {clean}"[:180]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _map_item_has_layers(item) -> bool:
    method = getattr(item, "layers", None)
    if not callable(method):
        return False
    try:
        return bool(method())
    except Exception:
        return False


def _write_project_entry(project, key: str, value: Any) -> None:
    writer = getattr(project, "writeEntry", None)
    if callable(writer):
        try:
            writer("Cartomize", key, value)
            return
        except Exception:
            pass
    setter = getattr(project, "setCustomProperty", None)
    if callable(setter):
        setter(f"cartomize/{key}", value)
