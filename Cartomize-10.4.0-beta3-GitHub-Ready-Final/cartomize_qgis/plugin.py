"""Intégration de Cartomize dans QGIS."""
from __future__ import annotations

from pathlib import Path

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsApplication, QgsMessageLog

from .core.compat import info_level, right_dock_area, warning_level
from .core.constants import PLUGIN_MENU, PLUGIN_NAME, PLUGIN_VERSION
from .core.template_catalog import TemplateCatalog
from .processing.provider import CartomizeProcessingProvider
from .ui.dock import CartomizeDock


class CartomizePlugin:
    LOG_TAG = "Cartomize"

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = Path(__file__).resolve().parent
        self.icon = QIcon(str(self.plugin_dir / "icon-hd.png"))
        self.actions: list[QAction] = []
        self.toolbar = None
        self.dock: CartomizeDock | None = None
        self.provider = None
        self.catalog = TemplateCatalog(self.plugin_dir / "templates_library")

    def initGui(self):  # noqa: N802
        self.catalog.reload()
        self.toolbar = self.iface.addToolBar("Cartomize")
        self.toolbar.setObjectName("CartomizeToolbar")

        self._add_action("Ouvrir Cartomize", self.show_dock, toolbar=True)
        self._add_action("Créer automatiquement une carte", self.run_autopilot, toolbar=True)
        self._add_action("Créer une mise en page", self.create_layout)
        self._add_action("Analyser le raster actif", self.run_raster_intelligence)
        self._add_action("Ouvrir l’aperçu HD", self.open_hd_preview, toolbar=True)
        self._add_action("Contrôler la qualité du projet", self.run_audit)
        self._add_action("Produire une série de cartes", self.run_batch)
        self._add_action("Vérifier les changements MapOps", self.run_mapops)
        self._add_action("Vérifier l'environnement", self.run_diagnostics)

        self.provider = CartomizeProcessingProvider(self.iface, self.catalog)
        try:
            registry = QgsApplication.processingRegistry()
            if registry is None:
                raise RuntimeError("Le registre Traitements de QGIS n’est pas disponible.")
            registry.addProvider(self.provider)
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"Les outils Traitements Cartomize n’ont pas pu être enregistrés : {exc}",
                self.LOG_TAG,
                warning_level(),
            )
            self.provider = None
        QgsMessageLog.logMessage(
            f"{PLUGIN_NAME} est chargé.",
            self.LOG_TAG,
            info_level(),
        )

    def unload(self):
        if self.provider is not None:
            try:
                QgsApplication.processingRegistry().removeProvider(self.provider)
            except Exception:
                pass
            self.provider = None

        if self.dock is not None:
            self.dock.dispose()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None

        for action in self.actions:
            self.iface.removePluginMenu(PLUGIN_MENU, action)
            action.deleteLater()
        self.actions.clear()

        if self.toolbar is not None:
            self.toolbar.clear()
            self.toolbar.deleteLater()
            self.toolbar = None

    def _add_action(self, text: str, callback, toolbar: bool = False) -> QAction:
        action = QAction(self.icon, text, self.iface.mainWindow())
        action.triggered.connect(callback)
        self.iface.addPluginToMenu(PLUGIN_MENU, action)
        if toolbar and self.toolbar is not None:
            self.toolbar.addAction(action)
        self.actions.append(action)
        return action

    def show_dock(self):
        if self.dock is None:
            self.dock = CartomizeDock(self.iface, self.plugin_dir)
            self.iface.addDockWidget(right_dock_area(), self.dock)
        self.dock.show()
        self.dock.raise_()
        self.dock.refresh_all()
        return self.dock

    def run_autopilot(self):
        dock = self.show_dock()
        dock.tabs.setCurrentIndex(0)
        dock.analyze_automation()

    def run_raster_intelligence(self):
        dock = self.show_dock()
        dock.tabs.setCurrentIndex(1)
        dock._open_raster_intelligence()

    def create_layout(self):
        dock = self.show_dock()
        dock.tabs.setCurrentIndex(2)
        return dock.create_layout()

    def open_hd_preview(self):
        dock = self.show_dock()
        dock.tabs.setCurrentIndex(2)
        dock.open_selected_layout()

    def run_audit(self):
        dock = self.show_dock()
        dock.tabs.setCurrentIndex(3)
        dock.run_audit()

    def run_batch(self):
        dock = self.show_dock()
        dock.tabs.setCurrentIndex(4)

    def run_mapops(self):
        dock = self.show_dock()
        dock.tabs.setCurrentIndex(4)
        dock.check_mapops_changes()

    def run_diagnostics(self):
        dock = self.show_dock()
        dock.tabs.setCurrentIndex(6)
        dock.run_diagnostics()
