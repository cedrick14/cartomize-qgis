"""Algorithme Processing de contrôle MapOps."""
from __future__ import annotations

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingOutputNumber,
    QgsProcessingOutputString,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
)

from ...core.mapops import MapOpsService


class MapOpsCheckAlgorithm(QgsProcessingAlgorithm):
    BASELINE = "BASELINE"
    REPORT = "REPORT"
    CHANGES = "CHANGES"
    STATUS = "STATUS"

    def name(self):
        return "check_cartomize_mapops"

    def displayName(self):
        return "Vérifier les changements MapOps"

    def group(self):
        return "Contrôle qualité"

    def groupId(self):
        return "quality_control"

    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading

    def shortHelpString(self):
        return "Compare le projet courant à un instantané MapOps et signale les cartes à régénérer."

    def createInstance(self):
        return MapOpsCheckAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFile(
                self.BASELINE,
                "État de référence MapOps",
                behavior=QgsProcessingParameterFile.File,
                fileFilter="Instantané JSON (*.json)",
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.REPORT,
                "Rapport MapOps",
                "Rapport JSON (*.json)",
            )
        )
        self.addOutput(QgsProcessingOutputNumber(self.CHANGES, "Changements détectés"))
        self.addOutput(QgsProcessingOutputString(self.STATUS, "Statut"))

    def processAlgorithm(self, parameters, context, feedback):
        service = MapOpsService()
        baseline = service.load_snapshot(self.parameterAsFile(parameters, self.BASELINE, context))
        report = service.compare(baseline)
        output = service.save_report(report, self.parameterAsFileOutput(parameters, self.REPORT, context))
        for change in report.changes:
            feedback.pushInfo(f"{change.severity} : {change.message}")
        return {self.CHANGES: len(report.changes), self.STATUS: report.status, self.REPORT: str(output)}
