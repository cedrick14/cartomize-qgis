"""Algorithme Processing pour l'analyse sémantique d'une couche vectorielle."""
from __future__ import annotations

import json
from pathlib import Path

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingOutputNumber,
    QgsProcessingOutputString,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterVectorLayer,
)

from ...core.vector_intelligence import VectorIntelligenceEngine


class VectorIntelligenceAlgorithm(QgsProcessingAlgorithm):
    INPUT = "INPUT"
    REPORT = "REPORT"
    ROLE = "ROLE"
    CONFIDENCE = "CONFIDENCE"
    THEMATIC_FIELD = "THEMATIC_FIELD"
    LABEL_FIELD = "LABEL_FIELD"

    def name(self):
        return "analyze_cartomize_vector"

    def displayName(self):
        return "Analyser une couche avec Vector Intelligence"

    def group(self):
        return "Automatisation cartographique"

    def groupId(self):
        return "automation"

    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.Flag.FlagNoThreading

    def shortHelpString(self):
        return (
            "Profile la géométrie, les attributs et les rôles sémantiques d'une couche vectorielle "
            "sans modifier la donnée source."
        )

    def createInstance(self):
        return VectorIntelligenceAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer(self.INPUT, "Couche vectorielle"))
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.REPORT, "Rapport Vector Intelligence", "Rapport JSON (*.json)"
            )
        )
        self.addOutput(QgsProcessingOutputString(self.ROLE, "Rôle cartographique probable"))
        self.addOutput(QgsProcessingOutputNumber(self.CONFIDENCE, "Confiance"))
        self.addOutput(QgsProcessingOutputString(self.THEMATIC_FIELD, "Champ thématique recommandé"))
        self.addOutput(QgsProcessingOutputString(self.LABEL_FIELD, "Champ d'étiquette recommandé"))

    def processAlgorithm(self, parameters, context, feedback):
        layer = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        profile = VectorIntelligenceEngine().analyze(layer)
        output = Path(self.parameterAsFileOutput(parameters, self.REPORT, context))
        output.parent.mkdir(parents=True, exist_ok=True)
        temp = output.with_suffix(output.suffix + ".tmp")
        temp.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(output)
        feedback.pushInfo(f"Rôle probable : {profile.role} ({profile.role_confidence:.0%})")
        feedback.pushInfo(f"Champ thématique : {profile.thematic_field or 'aucun'}")
        feedback.pushInfo(f"Champ d'étiquette : {profile.label_field or 'aucun'}")
        return {
            self.REPORT: str(output),
            self.ROLE: profile.role,
            self.CONFIDENCE: profile.role_confidence,
            self.THEMATIC_FIELD: profile.thematic_field,
            self.LABEL_FIELD: profile.label_field,
        }
