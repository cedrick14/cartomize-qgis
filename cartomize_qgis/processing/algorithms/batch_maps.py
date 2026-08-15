"""Algorithme Processing de production cartographique en série."""
from __future__ import annotations

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingOutputNumber,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
)

from ...core.autopilot import CartomizeAutopilot
from ...core.batch import CartomizeBatchRunner, load_manifest, save_report
from ...core.constants import PLUGIN_VERSION


class BatchMapsAlgorithm(QgsProcessingAlgorithm):
    MANIFEST = "MANIFEST"
    REPORT = "REPORT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"

    def __init__(self, iface, catalog):
        super().__init__()
        self.iface = iface
        self.catalog = catalog

    def name(self):
        return "batch_cartomize_maps"

    def displayName(self):
        return "Produire une série de cartes Cartomize"

    def group(self):
        return "Automatisation cartographique"

    def groupId(self):
        return "cartographic_automation"

    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.Flag.FlagNoThreading

    def shortHelpString(self):
        return (
            "Exécute un manifeste JSON pouvant contenir jusqu’à 5 000 cartes. "
            "Chaque carte est reconstruite avec QGIS, exportée et inscrite dans un rapport."
        )

    def createInstance(self):
        return BatchMapsAlgorithm(self.iface, self.catalog)

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFile(
                self.MANIFEST,
                "Manifeste de production Cartomize",
                behavior=QgsProcessingParameterFile.Behavior.File,
                fileFilter="Manifeste JSON (*.json)",
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.REPORT,
                "Rapport JSON",
                "Rapport JSON (*.json)",
            )
        )
        self.addOutput(QgsProcessingOutputNumber(self.SUCCEEDED, "Cartes produites"))
        self.addOutput(QgsProcessingOutputNumber(self.FAILED, "Cartes en échec"))

    def processAlgorithm(self, parameters, context, feedback):
        manifest_path = self.parameterAsFile(parameters, self.MANIFEST, context)
        report_path = self.parameterAsFileOutput(parameters, self.REPORT, context)
        manifest = load_manifest(manifest_path)
        autopilot = CartomizeAutopilot(self.iface, self.catalog)
        report = CartomizeBatchRunner(autopilot, version=PLUGIN_VERSION).run(manifest, feedback)
        output = save_report(report, report_path)
        feedback.pushInfo(
            f"Production terminée : {report.succeeded} réussite(s), {report.failed} échec(s)."
        )
        return {
            self.SUCCEEDED: report.succeeded,
            self.FAILED: report.failed,
            self.REPORT: str(output),
        }
