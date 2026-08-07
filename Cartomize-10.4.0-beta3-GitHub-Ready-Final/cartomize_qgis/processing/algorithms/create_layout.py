"""Algorithme Processing de création d'une mise en page Cartomize."""
from __future__ import annotations

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputString,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
)

from ...core.exporter import NativeLayoutExporter
from ...core.layout_builder import LayoutBuildOptions, LayoutBuilder


class CreateLayoutAlgorithm(QgsProcessingAlgorithm):
    TEMPLATE = "TEMPLATE"
    TITLE = "TITLE"
    SUBTITLE = "SUBTITLE"
    SOURCES = "SOURCES"
    VISIBLE_ONLY = "VISIBLE_ONLY"
    MARGIN = "MARGIN"
    GRID = "GRID"
    OUTPUT_QPT = "OUTPUT_QPT"
    LAYOUT_NAME = "LAYOUT_NAME"

    def __init__(self, iface, catalog):
        super().__init__()
        self.iface = iface
        self.catalog = catalog
        self._templates = []

    def name(self):
        return "create_cartomize_layout"

    def displayName(self):
        return "Créer une mise en page Cartomize"

    def group(self):
        return "Mise en page et publication"

    def groupId(self):
        return "layout_publication"

    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading

    def shortHelpString(self):
        return (
            "Crée une mise en page QGIS à partir des couches du projet et "
            "d'une maquette Cartomize."
        )

    def createInstance(self):
        return CreateLayoutAlgorithm(self.iface, self.catalog)

    def initAlgorithm(self, config=None):
        self._templates = self.catalog.all()
        self.addParameter(
            QgsProcessingParameterEnum(
                self.TEMPLATE,
                "Maquette",
                [item.name for item in self._templates],
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.TITLE,
                "Titre",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.SUBTITLE,
                "Sous-titre",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.SOURCES,
                "Sources et crédits",
                optional=True,
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
            QgsProcessingParameterNumber(
                self.MARGIN,
                "Marge autour de l'emprise en pourcentage",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=3.0,
                minValue=0.0,
                maxValue=50.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.GRID,
                "Ajouter une grille",
                defaultValue=False,
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_QPT,
                "Modèle QPT facultatif",
                "Modèle QGIS (*.qpt)",
                optional=True,
            )
        )
        self.addOutput(
            QgsProcessingOutputString(
                self.LAYOUT_NAME,
                "Mise en page créée",
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        index = self.parameterAsEnum(parameters, self.TEMPLATE, context)
        if index < 0 or index >= len(self._templates):
            raise QgsProcessingException("La maquette Cartomize est invalide.")

        options = LayoutBuildOptions(
            title=self.parameterAsString(parameters, self.TITLE, context),
            subtitle=self.parameterAsString(parameters, self.SUBTITLE, context),
            sources=self.parameterAsString(parameters, self.SOURCES, context),
            visible_layers_only=self.parameterAsBool(
                parameters,
                self.VISIBLE_ONLY,
                context,
            ),
            extent_margin_percent=self.parameterAsDouble(
                parameters,
                self.MARGIN,
                context,
            ),
            add_grid=self.parameterAsBool(parameters, self.GRID, context),
            open_designer=False,
        )
        result = LayoutBuilder(self.iface).build(
            self._templates[index],
            options,
        )

        output_qpt = self.parameterAsFileOutput(
            parameters,
            self.OUTPUT_QPT,
            context,
        )
        if output_qpt:
            NativeLayoutExporter().save_as_qpt(result.layout, output_qpt)

        for warning in result.warnings:
            feedback.pushWarning(warning)
        feedback.pushInfo(f"Mise en page créée : {result.layout_name}")
        return {self.LAYOUT_NAME: result.layout_name}
