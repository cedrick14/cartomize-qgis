"""Algorithme Processing pour le diagnostic d'un raster."""
from __future__ import annotations

import json
from pathlib import Path

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingOutputNumber,
    QgsProcessingOutputString,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterRasterLayer,
)

from ...core.raster_intelligence import RasterIntelligenceEngine, raster_type_label


class RasterIntelligenceAlgorithm(QgsProcessingAlgorithm):
    INPUT = "INPUT"
    REPORT = "REPORT"
    TYPE = "TYPE"
    CONFIDENCE = "CONFIDENCE"
    CLASSES = "CLASSES"

    def name(self):
        return "analyze_cartomize_raster"

    def displayName(self):
        return "Analyser un raster avec Raster Engine"

    def group(self):
        return "Automatisation cartographique"

    def groupId(self):
        return "automation"

    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.Flag.FlagNoThreading

    def shortHelpString(self):
        return (
            "Analyse les métadonnées, le NoData, les classes, les fréquences et les valeurs atypiques "
            "sans modifier le raster source."
        )

    def createInstance(self):
        return RasterIntelligenceAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(self.INPUT, "Raster"))
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.REPORT, "Rapport Raster Engine", "Rapport JSON (*.json)"
            )
        )
        self.addOutput(QgsProcessingOutputString(self.TYPE, "Type détecté"))
        self.addOutput(QgsProcessingOutputNumber(self.CONFIDENCE, "Confiance"))
        self.addOutput(QgsProcessingOutputNumber(self.CLASSES, "Classes détectées"))

    def processAlgorithm(self, parameters, context, feedback):
        layer = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        diagnosis = RasterIntelligenceEngine().analyze(layer, deep=False, feedback=feedback)
        output = Path(self.parameterAsFileOutput(parameters, self.REPORT, context))
        output.parent.mkdir(parents=True, exist_ok=True)
        temp = output.with_suffix(output.suffix + ".tmp")
        temp.write_text(json.dumps(diagnosis.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(output)
        for line in diagnosis.summary_lines():
            feedback.pushInfo(line)
        return {
            self.REPORT: str(output),
            self.TYPE: raster_type_label(diagnosis.inference.raster_type),
            self.CONFIDENCE: diagnosis.inference.confidence,
            self.CLASSES: len(diagnosis.classes),
        }
