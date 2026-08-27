"""Équivalent ArcPy du module d’étiquetage Cartomize QGIS 10.5.1."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .models import Finding, Report


@dataclass(frozen=True)
class LabelRecommendation:
    layer_id: str; field_name: str; role: str; enabled: bool; priority: int
    font_size_pt: float; placement: str; density: float; estimated_candidates: int
    confidence: float; reason: str
    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True)
class LabelPlacementAudit:
    total_positions: int; placed: int; unplaced: int; per_layer: dict[str, dict[str, int]]; status: str
    def to_dict(self) -> dict[str, Any]: return asdict(self)


class LabelIntelligenceEngine:
    def recommend(self, layer, *, role: str, label_field: str, scale: float, density: float = 1.0) -> LabelRecommendation:
        scale = max(1, float(scale or 1)); density = max(0, min(1, float(density)))
        geometry = _geometry_name(layer)
        placement = "Autour du point" if geometry == "point" else "Le long de la ligne" if geometry == "line" else "Horizontal"
        estimated = 0
        try:
            import arcpy
            estimated = int(arcpy.management.GetCount(layer)[0])
        except Exception:
            pass
        enabled = bool(label_field) and density > 0
        font = 11.0 if scale < 30_000 else 9.5 if scale < 800_000 else 8.0
        priority = 100 if role == "principal" else 70 if role in {"localités", "transport"} else 50
        return LabelRecommendation(_layer_key(layer), str(label_field or ""), str(role or "contexte"), enabled, priority, font, placement, density, estimated, .9 if label_field else .3, "Réglage adapté au rôle, à la géométrie et à l'échelle.")

    def apply(self, layer, recommendation: LabelRecommendation):
        if not recommendation.enabled:
            layer.showLabels = False; return False
        classes = list(layer.listLabelClasses())
        if not classes: return False
        classes[0].expression = f"$feature.{recommendation.field_name}"
        if hasattr(classes[0], "visible"): classes[0].visible = True
        layer.showLabels = True
        try:
            cim = layer.getDefinition("V3")
            for label_class in cim.labelClasses:
                label_class.textSymbol.symbol.height = recommendation.font_size_pt
            layer.setDefinition(cim)
        except Exception:
            pass
        return True

    @staticmethod
    def audit_canvas(iface) -> LabelPlacementAudit:
        project = getattr(iface, "project", None)
        try:
            report = audit_labels(project or iface)
            total = int(report.statistics.get("label_classes", 0))
            unplaced = sum(1 for item in report.findings if item.code in {"LABEL_NO_ACTIVE_CLASS", "LABEL_EXPRESSION_EMPTY"})
            return LabelPlacementAudit(total, max(0, total - unplaced), unplaced, {}, report.status)
        except Exception:
            return LabelPlacementAudit(0, 0, 0, {}, "Indisponible")


def _layer_key(layer): return str(getattr(layer, "URI", "") or getattr(layer, "name", "") or layer)
def _geometry_name(layer):
    try:
        import arcpy
        value = str(getattr(arcpy.Describe(layer), "shapeType", "")).casefold()
        return "point" if "point" in value else "line" if "line" in value or "polyline" in value else "polygon"
    except Exception:
        return "polygon"


def audit_labels(aprx: Any) -> Report:
    """Contrôle la configuration native des étiquettes des couches ArcGIS Pro."""

    findings: list[Finding] = []
    vector_count = enabled_count = class_count = 0
    for map_item in aprx.listMaps():
        for layer in map_item.listLayers():
            if not getattr(layer, "isFeatureLayer", False) or getattr(layer, "isBroken", False):
                continue
            vector_count += 1
            layer_id = str(getattr(layer, "URI", "") or getattr(layer, "longName", layer.name))
            name = str(layer.name)
            try:
                enabled = bool(getattr(layer, "showLabels", False))
                classes = list(layer.listLabelClasses()) if hasattr(layer, "listLabelClasses") else []
            except Exception as exc:
                findings.append(Finding("medium", "LABEL_CONFIG_UNREADABLE", f"La configuration d’étiquetage est illisible : {exc}", layer_id, name, "Vérifier les propriétés d’étiquetage de la couche."))
                continue
            if not enabled:
                continue
            enabled_count += 1
            active = [item for item in classes if bool(getattr(item, "visible", True))]
            class_count += len(active)
            if not active:
                findings.append(Finding("medium", "LABEL_NO_ACTIVE_CLASS", "L’étiquetage est activé sans classe visible.", layer_id, name, "Activer une classe d’étiquettes ou désactiver l’étiquetage."))
                continue
            for label_class in active:
                expression = str(getattr(label_class, "expression", "") or "").strip()
                if not expression:
                    findings.append(Finding("high", "LABEL_EXPRESSION_EMPTY", "Une classe d’étiquettes ne possède aucune expression.", layer_id, name, "Choisir un champ ou définir une expression Arcade valide."))
                try:
                    cim = label_class.getDefinition("V3")
                    symbol = getattr(getattr(cim, "textSymbol", None), "symbol", None)
                    height = float(getattr(symbol, "height", 0.0) or 0.0)
                    if 0 < height < 7:
                        findings.append(Finding("medium", "LABEL_TEXT_SMALL", f"La taille d’étiquette ({height:g} pt) est faible.", layer_id, name, "Utiliser au moins 7 pt pour la carte finale."))
                except Exception:
                    pass
    penalty = sum({"critical": 25, "high": 12, "medium": 6, "low": 2}.get(item.severity, 0) for item in findings)
    score = max(0, min(100, 100 - penalty))
    status = "Bon" if score >= 85 else ("À optimiser" if score >= 65 else "Surchargé")
    return Report(
        kind="label_audit",
        score=score,
        status=status,
        findings=findings,
        statistics={"vector_layers": vector_count, "labeled_layers": enabled_count, "label_classes": class_count, "findings": len(findings)},
        evidence={"host": "ArcGIS Pro", "method": "native_label_class_configuration"},
    )
