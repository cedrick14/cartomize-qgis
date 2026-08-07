"""Algorithme Processing de contrôle de la qualité du projet."""
from __future__ import annotations

from pathlib import Path

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingOutputNumber,
    QgsProcessingOutputString,
    QgsProcessingParameterFileDestination,
)

from ...core.quality import ProjectQualityAuditor


class AuditProjectAlgorithm(QgsProcessingAlgorithm):
    OUTPUT_JSON = "OUTPUT_JSON"
    SCORE = "SCORE"
    STATUS = "STATUS"

    def name(self):
        return "audit_cartographic_project"

    def displayName(self):
        return "Contrôler la qualité cartographique du projet"

    def group(self):
        return "Contrôle de la qualité"

    def groupId(self):
        return "quality_control"

    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading

    def shortHelpString(self):
        return (
            "Vérifie les systèmes de coordonnées, les couches, un échantillon "
            "de géométries et les principaux objets des mises en page."
        )

    def createInstance(self):
        return AuditProjectAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_JSON,
                "Rapport JSON",
                "JSON (*.json)",
            )
        )
        self.addOutput(QgsProcessingOutputNumber(self.SCORE, "Score sur 100"))
        self.addOutput(QgsProcessingOutputString(self.STATUS, "Statut"))

    def processAlgorithm(self, parameters, context, feedback):
        report = ProjectQualityAuditor().run()
        output = Path(
            self.parameterAsFileOutput(
                parameters,
                self.OUTPUT_JSON,
                context,
            )
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report.to_json(), encoding="utf-8")
        feedback.pushInfo(report.to_text())
        return {
            self.OUTPUT_JSON: str(output),
            self.SCORE: report.score,
            self.STATUS: report.status,
        }
