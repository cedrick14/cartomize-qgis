"""Fournisseur Cartomize pour la boîte à outils Traitements.

Les algorithmes sont importés à la demande. Une erreur localisée dans un
algorithme ne doit jamais empêcher le reste du plugin Cartomize de démarrer.
"""
from __future__ import annotations

from importlib import import_module

from qgis.core import QgsMessageLog, QgsProcessingProvider

from ..core.compat import warning_level


class CartomizeProcessingProvider(QgsProcessingProvider):
    """Fournisseur Processing résilient pour QGIS 3.40 et versions ultérieures."""

    ALGORITHMS = (
        (".algorithms.autopilot_map", "AutopilotMapAlgorithm", True),
        (".algorithms.replay_recipe", "ReplayRecipeAlgorithm", True),
        (".algorithms.batch_maps", "BatchMapsAlgorithm", True),
        (".algorithms.create_layout", "CreateLayoutAlgorithm", True),
        (".algorithms.audit_project", "AuditProjectAlgorithm", False),
        (".algorithms.mapops_check", "MapOpsCheckAlgorithm", False),
        (".algorithms.raster_intelligence", "RasterIntelligenceAlgorithm", False),
        (".algorithms.geo_intelligence", "GeoIntelligenceAlgorithm", False),
        (".algorithms.vector_intelligence", "VectorIntelligenceAlgorithm", False),
    )

    def __init__(self, iface, catalog):
        super().__init__()
        self.iface = iface
        self.catalog = catalog
        self.load_errors: list[str] = []
        self.loaded_algorithm_names: list[str] = []

    def id(self):
        return "cartomize"

    def name(self):
        return "Cartomize"

    def longName(self):
        return "Cartomize. Conception cartographique et contrôle de la qualité"

    def loadAlgorithms(self):
        self.load_errors.clear()
        self.loaded_algorithm_names.clear()
        for module_name, class_name, needs_context in self.ALGORITHMS:
            try:
                module = import_module(module_name, package=__package__)
                algorithm_class = getattr(module, class_name)
                if needs_context:
                    algorithm = algorithm_class(self.iface, self.catalog)
                else:
                    algorithm = algorithm_class()
                self.addAlgorithm(algorithm)
                self.loaded_algorithm_names.append(class_name)
            except Exception as exc:
                message = f"{class_name} indisponible : {exc}"
                self.load_errors.append(message)
                QgsMessageLog.logMessage(message, "Cartomize", warning_level())

    def compatibility_summary(self) -> dict[str, object]:
        return {
            "loaded": tuple(self.loaded_algorithm_names),
            "errors": tuple(self.load_errors),
            "expected": len(self.ALGORITHMS),
        }
