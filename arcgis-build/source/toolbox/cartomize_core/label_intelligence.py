"""Équivalent ArcPy du module d’étiquetage Cartomize QGIS 10.5.1."""

from __future__ import annotations

from typing import Any

from .models import Finding, Report


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
