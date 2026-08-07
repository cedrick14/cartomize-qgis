"""Contrôle de qualité cartographique du projet QGIS courant."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from typing import Iterable

from qgis.core import (
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLayoutItemScaleBar,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)

from .constants import MAX_AUDIT_LAYERS


_SEVERITY_LABELS = {
    "critical": "Critique",
    "high": "Élevé",
    "medium": "Moyen",
    "low": "Faible",
    "info": "Information",
}


def severity_label(value: str) -> str:
    return _SEVERITY_LABELS.get(value, value.capitalize())


@dataclass(frozen=True)
class AuditFinding:
    severity: str
    code: str
    message: str
    layer_id: str = ""
    layer_name: str = ""
    remediation: str = ""


@dataclass
class AuditReport:
    generated_at: str
    score: int
    status: str
    findings: list[AuditFinding]
    statistics: dict

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "score": self.score,
            "status": self.status,
            "statistics": self.statistics,
            "findings": [asdict(item) for item in self.findings],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_text(self) -> str:
        lines = [
            "Audit Cartomize",
            f"Score : {self.score}/100",
            f"Statut : {self.status}",
            f"Date de génération : {self.generated_at}",
            "",
        ]
        if not self.findings:
            lines.append("Aucune anomalie détectée par les contrôles automatiques.")
            return "\n".join(lines)

        for finding in self.findings:
            lines.append(f"Niveau : {severity_label(finding.severity)}")
            lines.append(f"Code : {finding.code}")
            if finding.layer_name:
                lines.append(f"Couche : {finding.layer_name}")
            lines.append(f"Observation : {finding.message}")
            if finding.remediation:
                lines.append(f"Action recommandée : {finding.remediation}")
            lines.append("")
        return "\n".join(lines).rstrip()


class ProjectQualityAuditor:
    WEIGHTS = {
        "critical": 25,
        "high": 12,
        "medium": 6,
        "low": 2,
        "info": 0,
    }

    def __init__(self, project: QgsProject | None = None):
        self.project = project or QgsProject.instance()

    def run(self, layers: Iterable | None = None) -> AuditReport:
        layer_list = list(
            layers if layers is not None else self.project.mapLayers().values()
        )
        findings: list[AuditFinding] = []

        if len(layer_list) > MAX_AUDIT_LAYERS:
            findings.append(
                AuditFinding(
                    "medium",
                    "PROJECT_LAYER_LIMIT",
                    f"Le contrôle détaillé porte sur les {MAX_AUDIT_LAYERS} premières couches.",
                )
            )
            layer_list = layer_list[:MAX_AUDIT_LAYERS]

        if not layer_list:
            findings.append(
                AuditFinding(
                    "critical",
                    "PROJECT_NO_LAYER",
                    "Le projet ne contient aucune couche.",
                    remediation="Charger au moins une couche vectorielle ou raster valide.",
                )
            )

        if not self.project.crs().isValid():
            findings.append(
                AuditFinding(
                    "critical",
                    "PROJECT_CRS_MISSING",
                    "Le CRS du projet n'est pas défini.",
                    remediation="Définir un CRS adapté au territoire et à l'échelle de la carte.",
                )
            )

        if not self.project.fileName():
            findings.append(
                AuditFinding(
                    "medium",
                    "PROJECT_UNSAVED",
                    "Le projet QGIS n'est pas enregistré.",
                    remediation="Enregistrer le projet au format QGZ avant la production finale.",
                )
            )

        invalid_geometries = 0
        for layer in layer_list:
            name = layer.name()
            layer_id = layer.id()

            if not layer.isValid():
                findings.append(
                    AuditFinding(
                        "critical",
                        "LAYER_INVALID",
                        "La couche est invalide.",
                        layer_id,
                        name,
                        "Vérifier le chemin, le fournisseur et les droits de lecture.",
                    )
                )
                continue

            if not layer.crs().isValid():
                findings.append(
                    AuditFinding(
                        "high",
                        "LAYER_CRS_MISSING",
                        "La couche ne possède pas de CRS valide.",
                        layer_id,
                        name,
                        "Définir le CRS source réel.",
                    )
                )

            try:
                if layer.extent().isEmpty() or layer.extent().isNull():
                    findings.append(
                        AuditFinding(
                            "high",
                            "LAYER_EMPTY_EXTENT",
                            "L'emprise de la couche est vide.",
                            layer_id,
                            name,
                            "Vérifier les données et les filtres actifs.",
                        )
                    )
            except Exception:
                pass

            if isinstance(layer, QgsVectorLayer):
                invalid_geometries += self._audit_vector_layer(
                    layer,
                    layer_id,
                    name,
                    findings,
                )
            elif isinstance(layer, QgsRasterLayer) and layer.bandCount() < 1:
                findings.append(
                    AuditFinding(
                        "high",
                        "RASTER_NO_BAND",
                        "Le raster ne contient aucune bande lisible.",
                        layer_id,
                        name,
                        "Vérifier le fichier raster et le fournisseur GDAL.",
                    )
                )

            try:
                if not layer.metadata().abstract().strip():
                    findings.append(
                        AuditFinding(
                            "low",
                            "LAYER_METADATA_EMPTY",
                            "Le résumé des métadonnées est vide.",
                            layer_id,
                            name,
                            "Documenter la source, la date, la méthode et les limites.",
                        )
                    )
            except Exception:
                pass

        layouts = list(self.project.layoutManager().printLayouts())
        if not layouts:
            findings.append(
                AuditFinding(
                    "medium",
                    "LAYOUT_NONE",
                    "Le projet ne contient aucune mise en page.",
                    remediation="Créer une mise en page Cartomize.",
                )
            )
        for layout in layouts:
            self._audit_layout(layout, findings)

        score = max(
            0,
            min(
                100,
                100
                - sum(
                    self.WEIGHTS.get(item.severity, 0)
                    for item in findings
                ),
            ),
        )
        if score >= 85:
            status = "Conforme"
        elif score >= 65:
            status = "À améliorer"
        else:
            status = "Non conforme"

        return AuditReport(
            datetime.now(timezone.utc).isoformat(),
            score,
            status,
            findings,
            {
                "layers": len(layer_list),
                "vector_layers": sum(
                    isinstance(layer, QgsVectorLayer) for layer in layer_list
                ),
                "raster_layers": sum(
                    isinstance(layer, QgsRasterLayer) for layer in layer_list
                ),
                "layouts": len(layouts),
                "sampled_invalid_geometries": invalid_geometries,
                "findings": len(findings),
            },
        )

    def _audit_vector_layer(
        self,
        layer: QgsVectorLayer,
        layer_id: str,
        name: str,
        findings: list[AuditFinding],
    ) -> int:
        if layer.featureCount() == 0:
            findings.append(
                AuditFinding(
                    "medium",
                    "VECTOR_EMPTY",
                    "La couche vectorielle ne contient aucune entité.",
                    layer_id,
                    name,
                    "Retirer la couche ou corriger sa source.",
                )
            )

        invalid = self._sample_invalid_geometries(layer)
        if invalid:
            findings.append(
                AuditFinding(
                    "high",
                    "VECTOR_INVALID_GEOMETRY",
                    f"L'échantillon contient {invalid} géométries invalides.",
                    layer_id,
                    name,
                    "Exécuter l'outil Réparer les géométries.",
                )
            )

        if layer.renderer() is None:
            findings.append(
                AuditFinding(
                    "medium",
                    "VECTOR_NO_RENDERER",
                    "Aucune symbologie n'est configurée.",
                    layer_id,
                    name,
                    "Appliquer une symbologie QGIS.",
                )
            )

        if layer.isEditable():
            findings.append(
                AuditFinding(
                    "medium",
                    "VECTOR_EDITING",
                    "Une session d'édition est ouverte sur la couche.",
                    layer_id,
                    name,
                    "Enregistrer ou annuler les modifications avant l'export.",
                )
            )
        return invalid

    @staticmethod
    def _sample_invalid_geometries(layer: QgsVectorLayer) -> int:
        invalid = 0
        checked = 0
        for feature in layer.getFeatures():
            geometry = feature.geometry()
            if geometry and not geometry.isEmpty():
                checked += 1
                try:
                    invalid += 0 if geometry.isGeosValid() else 1
                except Exception:
                    pass
            if checked >= 200:
                break
        return invalid

    @staticmethod
    def _audit_layout(layout, findings: list[AuditFinding]) -> None:
        items = list(layout.items())
        maps = [item for item in items if isinstance(item, QgsLayoutItemMap)]
        legends = [item for item in items if isinstance(item, QgsLayoutItemLegend)]
        scales = [item for item in items if isinstance(item, QgsLayoutItemScaleBar)]
        labels = [item for item in items if isinstance(item, QgsLayoutItemLabel)]
        name = layout.name()

        if not maps:
            findings.append(
                AuditFinding(
                    "critical",
                    "LAYOUT_NO_MAP",
                    f"La mise en page « {name} » ne contient aucun cadre cartographique.",
                )
            )
        if maps and not legends:
            findings.append(
                AuditFinding(
                    "medium",
                    "LAYOUT_NO_LEGEND",
                    f"La mise en page « {name} » ne contient aucune légende.",
                )
            )
        if maps and not scales:
            findings.append(
                AuditFinding(
                    "medium",
                    "LAYOUT_NO_SCALE",
                    f"La mise en page « {name} » ne contient aucune barre d'échelle.",
                )
            )
        if not any(_label_text(label).strip() for label in labels):
            findings.append(
                AuditFinding(
                    "low",
                    "LAYOUT_NO_TITLE",
                    f"La mise en page « {name} » ne contient aucun texte significatif.",
                )
            )
        for legend in legends:
            if legend.linkedMap() is None:
                findings.append(
                    AuditFinding(
                        "high",
                        "LEGEND_UNLINKED",
                        f"Une légende de la mise en page « {name} » n'est liée à aucun cadre.",
                    )
                )
        for scale in scales:
            if scale.linkedMap() is None:
                findings.append(
                    AuditFinding(
                        "high",
                        "SCALE_UNLINKED",
                        f"Une barre d'échelle de la mise en page « {name} » n'est liée à aucun cadre.",
                    )
                )
        try:
            data_score = int(layout.customProperty("cartomize/data_quality_score", 100))
            cartographic_score = int(layout.customProperty("cartomize/cartographic_score", 100))
            automation_confidence = int(layout.customProperty("cartomize/automation_confidence", 100))
        except Exception:
            data_score = cartographic_score = automation_confidence = 100
        if data_score < 70:
            findings.append(
                AuditFinding(
                    "high",
                    "DATA_QUALITY_LOW",
                    f"La qualité des données associée à « {name} » est évaluée à {data_score}/100.",
                    remediation="Corriger les CRS, géométries, NoData ou anomalies avant publication.",
                )
            )
        if cartographic_score < 78:
            findings.append(
                AuditFinding(
                    "medium",
                    "CARTOGRAPHIC_SCORE_LOW",
                    f"La composition cartographique de « {name} » est évaluée à {cartographic_score}/100.",
                    remediation="Relancer l’optimisation de la mise en page et vérifier la légende, les textes et l’équilibre de page.",
                )
            )
        if automation_confidence < 60:
            findings.append(
                AuditFinding(
                    "medium",
                    "AUTOMATION_CONFIDENCE_LOW",
                    f"La confiance de l’automatisation pour « {name} » est de {automation_confidence}/100.",
                    remediation="Revoir manuellement l’objectif, la couche principale et les variables thématiques.",
                )
            )

        validation_status = str(layout.customProperty("cartomize/validation_status", "En attente"))
        if validation_status != "Approuvée":
            findings.append(
                AuditFinding(
                    "info",
                    "LAYOUT_HUMAN_VALIDATION_PENDING",
                    f"La mise en page « {name} » n'a pas encore été approuvée par un cartographe.",
                    remediation="Effectuer la validation humaine dans l'onglet Production de Cartomize.",
                )
            )


def _label_text(label) -> str:
    for attribute in ("currentText", "text"):
        method = getattr(label, attribute, None)
        if callable(method):
            try:
                return str(method())
            except Exception:
                pass
    return ""
