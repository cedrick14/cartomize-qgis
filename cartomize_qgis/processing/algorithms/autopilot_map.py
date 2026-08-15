"""Algorithme Processing Cartomize Autopilot."""
from __future__ import annotations

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingOutputString,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterMapLayer,
    QgsProcessingParameterString,
)

from ...core.autopilot import CartomizeAutopilot, OBJECTIVES, STYLE_PROFILES


class AutopilotMapAlgorithm(QgsProcessingAlgorithm):
    OBJECTIVE = "OBJECTIVE"
    MAIN_LAYER = "MAIN_LAYER"
    STYLE = "STYLE"
    VARIANT = "VARIANT"
    APPLY_SYMBOLOGY = "APPLY_SYMBOLOGY"
    AUTO_CORRECT = "AUTO_CORRECT"
    VISIBLE_ONLY = "VISIBLE_ONLY"
    SOURCES = "SOURCES"
    LAYOUT_NAME = "LAYOUT_NAME"
    SCORE = "SCORE"

    def __init__(self, iface, catalog):
        super().__init__()
        self.iface = iface
        self.catalog = catalog

    def name(self):
        return "autopilot_map"

    def displayName(self):
        return "Créer automatiquement une carte"

    def group(self):
        return "Automatisation cartographique"

    def groupId(self):
        return "cartographic_automation"

    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.Flag.FlagNoThreading

    def shortHelpString(self):
        return (
            "Analyse le projet QGIS, choisit une maquette, applique une symbologie "
            "explicable, crée une mise en page native et calcule un score de qualité."
        )

    def createInstance(self):
        return AutopilotMapAlgorithm(self.iface, self.catalog)

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterEnum(
                self.OBJECTIVE,
                "Objectif cartographique",
                [label for _code, label in OBJECTIVES],
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterMapLayer(
                self.MAIN_LAYER,
                "Couche principale facultative",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.STYLE,
                "Orientation graphique",
                [label for _code, label in STYLE_PROFILES],
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.VARIANT,
                "Proposition à créer",
                ["Institutionnelle", "Analytique", "Minimaliste"],
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.APPLY_SYMBOLOGY,
                "Appliquer la symbologie recommandée",
                defaultValue=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.AUTO_CORRECT,
                "Corriger automatiquement la lisibilité",
                defaultValue=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.VISIBLE_ONLY,
                "Utiliser uniquement les couches visibles",
                defaultValue=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.SOURCES,
                "Sources et crédits",
                optional=True,
            )
        )
        self.addOutput(QgsProcessingOutputString(self.LAYOUT_NAME, "Mise en page créée"))
        self.addOutput(QgsProcessingOutputNumber(self.SCORE, "Score cartographique"))

    def processAlgorithm(self, parameters, context, feedback):
        objective_index = self.parameterAsEnum(parameters, self.OBJECTIVE, context)
        style_index = self.parameterAsEnum(parameters, self.STYLE, context)
        variant_index = self.parameterAsEnum(parameters, self.VARIANT, context)
        if not 0 <= objective_index < len(OBJECTIVES):
            raise QgsProcessingException("L’objectif cartographique est invalide.")
        if not 0 <= style_index < len(STYLE_PROFILES):
            raise QgsProcessingException("L’orientation graphique est invalide.")

        layer = self.parameterAsLayer(parameters, self.MAIN_LAYER, context)
        visible_only = self.parameterAsBool(parameters, self.VISIBLE_ONLY, context)
        autopilot = CartomizeAutopilot(self.iface, self.catalog)
        plan = autopilot.analyze(
            objective=OBJECTIVES[objective_index][0],
            main_layer_id=layer.id() if layer is not None else "",
            style_profile=STYLE_PROFILES[style_index][0],
            visible_only=visible_only,
        )
        result = autopilot.execute_variant(
            plan,
            variant_index,
            apply_symbology=self.parameterAsBool(parameters, self.APPLY_SYMBOLOGY, context),
            auto_correct=self.parameterAsBool(parameters, self.AUTO_CORRECT, context),
            visible_only=visible_only,
            sources=self.parameterAsString(parameters, self.SOURCES, context),
        )
        for warning in result.warnings:
            feedback.pushWarning(warning)
        feedback.pushInfo(
            f"Mise en page créée : {result.layout_name}. Score : {result.final_score}/100."
        )
        return {
            self.LAYOUT_NAME: result.layout_name,
            self.SCORE: result.final_score,
        }
