"""Algorithme Processing pour l'analyse globale d'un projet Cartomize."""
from __future__ import annotations

import json
from pathlib import Path

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingOutputNumber,
    QgsProcessingOutputString,
    QgsProcessingParameterFileDestination,
    QgsProject,
)

from ...core.geo_intelligence import GeoIntelligenceEngine


class GeoIntelligenceAlgorithm(QgsProcessingAlgorithm):
    REPORT = "REPORT"
    DATA_QUALITY = "DATA_QUALITY"
    CONFIDENCE = "CONFIDENCE"
    RELATIONS = "RELATIONS"

    def name(self):
        return "analyze_cartomize_project_intelligence"

    def displayName(self):
        return "Analyser l’intelligence cartographique du projet"

    def group(self):
        return "Automatisation cartographique"

    def groupId(self):
        return "automation"

    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.Flag.FlagNoThreading

    def shortHelpString(self):
        return (
            "Analyse les couches vectorielles et raster, leurs rôles, leurs relations spatiales, "
            "l’échelle et les champs d’étiquetage sans modifier les données sources."
        )

    def createInstance(self):
        return GeoIntelligenceAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.REPORT,
                "Rapport Geo Intelligence",
                "Rapport JSON (*.json)",
            )
        )
        self.addOutput(QgsProcessingOutputNumber(self.DATA_QUALITY, "Qualité des données"))
        self.addOutput(QgsProcessingOutputNumber(self.CONFIDENCE, "Confiance de l’automatisation"))
        self.addOutput(QgsProcessingOutputString(self.RELATIONS, "Relations détectées"))

    def processAlgorithm(self, parameters, context, feedback):
        project = QgsProject.instance()
        layers = [layer for layer in project.mapLayers().values() if layer and layer.isValid()]
        main_id = layers[0].id() if layers else ""
        report = GeoIntelligenceEngine(None, project).analyze(
            layers,
            main_layer_id=main_id,
            objective="auto",
        )
        output = Path(self.parameterAsFileOutput(parameters, self.REPORT, context))
        output.parent.mkdir(parents=True, exist_ok=True)
        temp = output.with_suffix(output.suffix + ".tmp")
        temp.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(output)
        feedback.pushInfo(f"Qualité des données : {report.data_quality_score}/100")
        feedback.pushInfo(f"Confiance : {report.automation_confidence}/100")
        feedback.pushInfo(f"Relations détectées : {len(report.graph.relations)}")
        return {
            self.REPORT: str(output),
            self.DATA_QUALITY: report.data_quality_score,
            self.CONFIDENCE: report.automation_confidence,
            self.RELATIONS: str(len(report.graph.relations)),
        }
