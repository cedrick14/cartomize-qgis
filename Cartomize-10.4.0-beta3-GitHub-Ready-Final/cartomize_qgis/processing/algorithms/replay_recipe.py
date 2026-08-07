"""Algorithme Processing pour rejouer une recette Cartomize."""
from __future__ import annotations

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingOutputNumber,
    QgsProcessingOutputString,
    QgsProcessingParameterFile,
)

from ...core.autopilot import CartomizeAutopilot


class ReplayRecipeAlgorithm(QgsProcessingAlgorithm):
    RECIPE = "RECIPE"
    LAYOUT_NAME = "LAYOUT_NAME"
    SCORE = "SCORE"

    def __init__(self, iface, catalog):
        super().__init__()
        self.iface = iface
        self.catalog = catalog

    def name(self):
        return "replay_cartomize_recipe"

    def displayName(self):
        return "Rejouer une recette Cartomize"

    def group(self):
        return "Automatisation cartographique"

    def groupId(self):
        return "cartographic_automation"

    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading

    def shortHelpString(self):
        return (
            "Recrée une mise en page à partir d’une recette Cartomize. Les couches "
            "sont retrouvées par identifiant puis par nom lorsque le projet a été mis à jour."
        )

    def createInstance(self):
        return ReplayRecipeAlgorithm(self.iface, self.catalog)

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFile(
                self.RECIPE,
                "Recette Cartomize",
                behavior=QgsProcessingParameterFile.File,
                fileFilter="Recette Cartomize (*.cartomize.json *.json)",
            )
        )
        self.addOutput(QgsProcessingOutputString(self.LAYOUT_NAME, "Mise en page créée"))
        self.addOutput(QgsProcessingOutputNumber(self.SCORE, "Score cartographique"))

    def processAlgorithm(self, parameters, context, feedback):
        path = self.parameterAsFile(parameters, self.RECIPE, context)
        autopilot = CartomizeAutopilot(self.iface, self.catalog)
        recipe = autopilot.load_recipe(path)
        result = autopilot.replay_recipe(recipe)
        for warning in result.warnings:
            feedback.pushWarning(warning)
        feedback.pushInfo(
            f"Recette rejouée : {result.layout_name}. Score : {result.final_score}/100."
        )
        return {
            self.LAYOUT_NAME: result.layout_name,
            self.SCORE: result.final_score,
        }
