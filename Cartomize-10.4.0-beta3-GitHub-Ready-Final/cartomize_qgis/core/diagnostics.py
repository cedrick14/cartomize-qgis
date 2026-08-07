"""Contrôle de compatibilité de Cartomize avec l'environnement QGIS."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import qgis.core as qgis_core
from qgis.core import Qgis, QgsApplication, QgsProject, QgsProviderRegistry

from .constants import PLUGIN_VERSION
from .template_catalog import TemplateCatalog


@dataclass(frozen=True)
class DiagnosticReport:
    ok: bool
    lines: tuple[str, ...]

    def as_text(self) -> str:
        return "\n".join(self.lines)


class DiagnosticEngine:
    REQUIRED_PROVIDERS = ("ogr", "gdal")

    def __init__(self, plugin_root: Path):
        self.plugin_root = plugin_root.resolve()

    @staticmethod
    def _provider_keys() -> tuple[str, ...]:
        registry = QgsProviderRegistry.instance()
        if registry is None:
            raise RuntimeError("Le registre des fournisseurs QGIS n'est pas initialisé.")
        provider_list = getattr(registry, "providerList", None)
        if not callable(provider_list):
            raise RuntimeError("La liste des fournisseurs QGIS n'est pas disponible.")
        return tuple(str(provider) for provider in provider_list())

    def run(self) -> DiagnosticReport:
        qgis_version = getattr(Qgis, "QGIS_VERSION", "Inconnue")
        lines = [
            f"Cartomize {PLUGIN_VERSION}",
            f"Version de QGIS : {qgis_version}",
            "",
            "Composants requis",
        ]
        ok = True

        version_int = int(getattr(Qgis, "QGIS_VERSION_INT", 0) or 0)
        if version_int and version_int < 34000:
            ok = False
            lines.append("Compatibilité QGIS : non conforme. QGIS 3.40 ou une version ultérieure est requis.")
        else:
            lines.append("Compatibilité QGIS : conforme")

        try:
            providers = set(self._provider_keys())
        except Exception as exc:
            providers = set()
            ok = False
            lines.append(f"Registre des fournisseurs : indisponible. {str(exc).strip()}")

        for provider in self.REQUIRED_PROVIDERS:
            present = provider in providers
            ok = ok and present
            status = "disponible" if present else "indisponible"
            lines.append(f"Fournisseur {provider.upper()} : {status}")

        required_processing_symbols = (
            "QgsProcessingAlgorithm",
            "QgsProcessingOutputNumber",
            "QgsProcessingOutputString",
            "QgsProcessingParameterFile",
            "QgsProcessingParameterFileDestination",
            "QgsProcessingParameterVectorLayer",
            "QgsProcessingParameterRasterLayer",
        )
        missing_processing = [
            name for name in required_processing_symbols if getattr(qgis_core, name, None) is None
        ]
        if missing_processing:
            ok = False
            lines.append(
                "API Traitements : incomplète. Éléments manquants : "
                + ", ".join(missing_processing)
            )
        else:
            lines.append("API Traitements QGIS : conforme")

        try:
            registry = QgsApplication.processingRegistry()
            provider = registry.providerById("cartomize") if registry is not None else None
            if provider is None:
                lines.append("Fournisseur Traitements Cartomize : non encore enregistré")
            else:
                algorithms = tuple(provider.algorithms()) if hasattr(provider, "algorithms") else ()
                lines.append(f"Algorithmes Traitements Cartomize : {len(algorithms)} chargés")
                provider_errors = tuple(getattr(provider, "load_errors", ()) or ())
                if provider_errors:
                    ok = False
                    lines.append("Erreurs de chargement Traitements : " + " | ".join(provider_errors))
        except Exception as exc:
            ok = False
            lines.append(f"Fournisseur Traitements Cartomize : contrôle impossible. {str(exc).strip()}")

        try:
            catalog = TemplateCatalog(self.plugin_root / "templates_library")
            count = len(catalog.all())
            valid_templates = count == 24
            ok = ok and valid_templates
            status = "conforme" if valid_templates else "incomplet"
            lines.append(f"Catalogue de maquettes : {count} maquettes, statut {status}")
        except Exception as exc:
            ok = False
            lines.append(f"Catalogue de maquettes : indisponible. {str(exc).strip()}")

        resource = self.plugin_root / "resources" / "north_arrow.svg"
        resource_ok = resource.is_file() and not resource.is_symlink()
        ok = ok and resource_ok
        resource_status = "disponible" if resource_ok else "indisponible"
        lines.append(f"Ressource de flèche nord : {resource_status}")

        capabilities = {
            "Cartomize Autopilot": ("core/autopilot.py", "processing/algorithms/autopilot_map.py"),
            "Raster Intelligence": ("core/raster_intelligence.py", "core/raster_intelligence_core.py", "processing/algorithms/raster_intelligence.py"),
            "Vector Intelligence": ("core/vector_intelligence.py", "processing/algorithms/vector_intelligence.py"),
            "Geo Intelligence": ("core/geo_intelligence.py", "core/project_graph.py", "processing/algorithms/geo_intelligence.py"),
            "Intelligence d’échelle": ("core/scale_intelligence.py",),
            "Intelligence d’étiquetage": ("core/label_intelligence.py",),
            "Optimisation adaptative des mises en page": ("core/layout_intelligence.py",),
            "Mémoire locale des préférences": ("core/local_memory.py",),
            "Symbologie raster": ("core/raster_symbology.py",),
            "Hiérarchie multi-couches": ("core/project_styling.py",),
            "Production en série": ("core/batch.py", "processing/algorithms/batch_maps.py"),
            "Suivi MapOps": ("core/mapops.py", "processing/algorithms/mapops_check.py"),
            "Validation cartographique": ("core/human_validation.py",),
        }
        for label, relative_paths in capabilities.items():
            available = all(
                (self.plugin_root / relative).is_file()
                and not (self.plugin_root / relative).is_symlink()
                for relative in relative_paths
            )
            ok = ok and available
            lines.append(f"{label} : {'disponible' if available else 'indisponible'}")

        lines.extend(("", "Projet courant"))
        try:
            project = QgsProject.instance()
            if project is None:
                raise RuntimeError("Le projet QGIS courant n'est pas disponible.")
            lines.append(f"Couches : {len(project.mapLayers())}")
            lines.append(f"Mises en page : {len(project.layoutManager().printLayouts())}")
        except Exception as exc:
            ok = False
            lines.append(f"Projet QGIS : indisponible. {str(exc).strip()}")

        lines.extend(("", f"Statut général : {'Conforme' if ok else 'Non conforme'}"))
        return DiagnosticReport(ok, tuple(lines))
