"""Intégration de Cartomize dans QGIS."""
from __future__ import annotations
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import platform
import sys
import traceback
from typing import TYPE_CHECKING

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QApplication
from qgis.core import Qgis, QgsMessageLog

from .core.constants import PLUGIN_MENU, PLUGIN_NAME, PLUGIN_VERSION

if TYPE_CHECKING:
    from .core.template_catalog import TemplateCatalog
    from .processing.provider import CartomizeProcessingProvider
    from .ui.dock import CartomizeDock
    from .ui.safe_launcher import CartomizeSafeLauncher


def _message_level(name: str, fallback: int):
    direct = getattr(Qgis, name, None)
    if direct is not None:
        return direct
    enum = getattr(Qgis, "MessageLevel", None)
    return getattr(enum, name, fallback) if enum is not None else fallback


class CartomizePlugin:
    LOG_TAG = "Cartomize"

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = Path(__file__).resolve().parent
        # L'icône standard est volontairement utilisée au démarrage. Charger
        # l'image HD n'apporte rien dans une barre d'outils et consomme beaucoup
        # plus de mémoire sur les écrans Windows à forte densité.
        self.icon = QIcon(str(self.plugin_dir / "icon.png"))
        self.actions: list[QAction] = []
        self.toolbar = None
        self.launcher: CartomizeSafeLauncher | None = None
        self.dock: CartomizeDock | None = None
        self.provider: CartomizeProcessingProvider | None = None
        self.catalog: TemplateCatalog | None = None
        self._unloading = False
        self._full_ui_loading = False
        self._health_timer_token = 0
        self._health_checks_remaining = 0
        self._provider_timer_token = 0
        self._provider_attempts = 0

    def initGui(self):  # noqa: N802
        """Installe uniquement les contrôles légers requis par QGIS.

        Les modules de mise en page, d'intelligence et de traitement sont
        importés après le retour à la boucle d'événements. QGIS reste ainsi
        utilisable pendant le chargement d'un projet volumineux ou distant.
        """
        self.toolbar = self.iface.addToolBar("Cartomize")
        self.toolbar.setObjectName("CartomizeToolbar")

        # Comme dans Cartomize 10.4, l'utilisateur ne voit qu'une seule action.
        # Le fournisseur Traitements est enregistré automatiquement après le
        # démarrage, lorsque la boucle d'événements QGIS est disponible.
        self._add_action("Ouvrir Cartomize", self.show_dock, toolbar=True)
        self._schedule_processing_registration()

        QgsMessageLog.logMessage(
            f"{PLUGIN_NAME} est chargé automatiquement et progressivement.",
            self.LOG_TAG,
            _message_level("Info", 0),
        )

    def _ensure_catalog(self):
        if self.catalog is None:
            from .core.template_catalog import TemplateCatalog

            self.catalog = TemplateCatalog(self.plugin_dir / "templates_library")
            self.catalog.reload()
        return self.catalog

    def _schedule_processing_registration(self, delay_ms: int = 1500, *, token=None):
        """Planifie l'enregistrement automatique sans bloquer ``initGui``."""
        if self._unloading or self.provider is not None:
            return
        if token is None:
            self._provider_timer_token += 1
            token = self._provider_timer_token
            self._provider_attempts = 0
        QTimer.singleShot(
            max(0, int(delay_ms)),
            lambda: self._attempt_processing_registration(token),
        )

    def _attempt_processing_registration(self, token: int):
        """Enregistre Traitements dès que QGIS et le panneau sont stables."""
        if (
            token != self._provider_timer_token
            or self._unloading
            or self.provider is not None
        ):
            return
        # Ne cumulons jamais le chargement des algorithmes avec la construction
        # du dock. Les deux opérations utilisent des objets QGIS/Qt du thread
        # principal et doivent rester séquentielles.
        if self._full_ui_loading or (self.dock is not None and not self.dock.is_ready()):
            self._schedule_processing_registration(500, token=token)
            return

        self._provider_attempts += 1
        final_attempt = self._provider_attempts >= 3
        if self._register_processing_provider(log_failure=final_attempt):
            return
        if not final_attempt:
            self._schedule_processing_registration(
                750 * self._provider_attempts,
                token=token,
            )

    def _register_processing_provider(self, *, log_failure: bool = True) -> bool:
        if self._unloading or self.provider is not None:
            return self.provider is not None
        try:
            from .processing.provider import CartomizeProcessingProvider

            catalog = self._ensure_catalog()
            from qgis.core import QgsApplication

            registry = QgsApplication.processingRegistry()
            if registry is None:
                raise RuntimeError("Le registre Traitements de QGIS n’est pas disponible.")
            provider = CartomizeProcessingProvider(self.iface, catalog)
            if not registry.addProvider(provider):
                raise RuntimeError("QGIS a refusé l’enregistrement du fournisseur Cartomize.")
            self.provider = provider
            return True
        except Exception as exc:
            if log_failure:
                QgsMessageLog.logMessage(
                    "Les outils Traitements Cartomize n’ont pas pu être "
                    f"enregistrés automatiquement : {exc}",
                    self.LOG_TAG,
                    _message_level("Warning", 1),
                )
            self.provider = None
            return False

    def enable_processing_tools(self):
        """Enregistre explicitement le fournisseur sans ralentir QGIS au démarrage."""
        if self.provider is not None:
            self.iface.messageBar().pushMessage(
                self.LOG_TAG,
                "Les outils Cartomize sont déjà disponibles dans Traitements.",
                level=_message_level("Info", 0),
                duration=5,
            )
            return
        self._register_processing_provider()
        if self.provider is not None:
            self.iface.messageBar().pushMessage(
                self.LOG_TAG,
                "Les outils Cartomize sont maintenant disponibles dans Traitements.",
                level=_message_level("Info", 0),
                duration=6,
            )
        elif self.launcher is not None:
            self.launcher.set_error(
                "Les outils Traitements n'ont pas pu être chargés. "
                "Copiez le diagnostic et consultez le journal QGIS."
            )

    def unload(self):
        self._unloading = True
        self._provider_timer_token += 1
        self._health_timer_token += 1
        if self.provider is not None:
            try:
                from qgis.core import QgsApplication

                QgsApplication.processingRegistry().removeProvider(self.provider)
            except Exception:
                logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
            self.provider = None

        if self.dock is not None:
            self.dock.dispose()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None

        if self.launcher is not None:
            self.iface.removeDockWidget(self.launcher)
            self.launcher.deleteLater()
            self.launcher = None

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
        """Ouvre Cartomize en un clic, ou le mode récupération après un échec."""
        if self.dock is not None:
            self.dock.show()
            self.dock.raise_()
            if self.launcher is not None:
                self.launcher.hide()
            return self.dock
        last_launch_failed = self._crash_marker_path().is_file()
        if self.launcher is None:
            from .ui.safe_launcher import CartomizeSafeLauncher

            self.launcher = CartomizeSafeLauncher(
                self.iface,
                qgis_version=str(getattr(Qgis, "QGIS_VERSION", "3.x")),
                last_launch_failed=last_launch_failed,
                open_full_interface=self.open_full_interface,
                enable_processing_tools=self.enable_processing_tools,
                copy_diagnostic=self.copy_compatibility_diagnostic,
            )
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.launcher)
        self.launcher.show()
        self.launcher.raise_()
        if (
            not last_launch_failed
            and self.dock is None
            and not self._full_ui_loading
        ):
            self.launcher.set_busy("Initialisation automatique de Cartomize…")
            QTimer.singleShot(0, self.open_full_interface)
        return self.launcher

    def open_full_interface(self):
        """Charge l'interface avancée après retour à la boucle Qt."""
        if self._unloading or self._full_ui_loading:
            return
        if self.dock is not None:
            self.dock.show()
            self.dock.raise_()
            if self.launcher is not None:
                self.launcher.hide()
            return
        self._full_ui_loading = True
        self._write_crash_marker("import_pending")
        if self.launcher is not None:
            self.launcher.set_busy("Étape 1/3 : préparation des modules Cartomize…")
        QTimer.singleShot(0, self._load_full_interface)

    def _load_full_interface(self):
        try:
            self._write_crash_marker("importing_advanced_ui")
            from .ui.dock import CartomizeDock

            self._full_dock_class = CartomizeDock
            if self.launcher is not None:
                self.launcher.set_busy("Étape 2/3 : construction du panneau avancé…")
            self._write_crash_marker("constructing_advanced_ui")
            # Retour explicite à la boucle Qt entre l'import et la construction.
            # Cela évite processEvents(), qui peut provoquer une réentrance native.
            QTimer.singleShot(0, self._construct_full_interface)
        except Exception as exc:
            self._handle_full_ui_failure(exc)

    def _construct_full_interface(self):
        try:
            dock_class = self._full_dock_class
            dock = dock_class(self.iface, self.plugin_dir)
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
            self.dock = dock
            dock.show()
            dock.raise_()
            if self.launcher is not None:
                self.launcher.hide()
            self._write_crash_marker("initializing_runtime")
            QTimer.singleShot(0, dock.initialize_runtime)
            # La visite guidée reste disponible depuis Paramètres, mais elle ne
            # doit jamais ouvrir automatiquement un overlay Qt pendant le
            # premier affichage du dock. Sur QGIS 3.40/Qt 5, cette superposition
            # pouvait entrer en concurrence avec la construction du panneau et
            # provoquer un gel ou une fermeture native sans traceback Python.
            self._health_timer_token += 1
            token = self._health_timer_token
            self._health_checks_remaining = 40
            QTimer.singleShot(250, lambda: self._mark_full_ui_healthy(token))
        except Exception as exc:
            self._handle_full_ui_failure(exc)
        finally:
            self._full_ui_loading = False
            if hasattr(self, "_full_dock_class"):
                del self._full_dock_class

    def _handle_full_ui_failure(self, exc: Exception):
        self._record_python_failure(exc)
        self.dock = None
        self._full_ui_loading = False
        if self.launcher is not None:
            self.launcher.show()
            self.launcher.set_error(
                "L'interface avancée a été arrêtée sans fermer QGIS. "
                "Cliquez sur « Copier le diagnostic » avant de réessayer."
            )
        QgsMessageLog.logMessage(
            f"Interface avancée indisponible : {exc}",
            self.LOG_TAG,
            _message_level("Critical", 2),
        )

    def _mark_full_ui_healthy(self, token: int):
        if token != self._health_timer_token or self._unloading or self.dock is None:
            return
        if not self.dock.is_ready():
            self._health_checks_remaining -= 1
            if self._health_checks_remaining > 0:
                QTimer.singleShot(250, lambda: self._mark_full_ui_healthy(token))
            # Après dix secondes sans état prêt, le marqueur est conservé : le
            # prochain démarrage proposera alors le mode récupération.
            return
        try:
            self._crash_marker_path().unlink(missing_ok=True)
        except OSError:
            logging.getLogger(__name__).debug("Impossible d'effacer le marqueur Cartomize.", exc_info=True)

    def _state_dir(self) -> Path:
        from qgis.core import QgsApplication

        path = Path(QgsApplication.qgisSettingsDirPath()) / "cartomize"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _crash_marker_path(self) -> Path:
        return self._state_dir() / "advanced-ui-startup.json"

    def _diagnostic_path(self) -> Path:
        return self._state_dir() / "compatibility-diagnostic.txt"

    def _write_crash_marker(self, stage: str):
        payload = {
            "stage": stage,
            "time_utc": datetime.now(timezone.utc).isoformat(),
            "plugin": PLUGIN_VERSION,
            "qgis": str(getattr(Qgis, "QGIS_VERSION", "unknown")),
            "python": sys.version,
            "platform": platform.platform(),
        }
        self._crash_marker_path().write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _record_python_failure(self, exc: Exception):
        report = self._compatibility_report()
        report += "\n\nEXCEPTION PYTHON\n" + "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
        try:
            self._diagnostic_path().write_text(report, encoding="utf-8")
        except OSError:
            logging.getLogger(__name__).debug("Impossible d'écrire le diagnostic Cartomize.", exc_info=True)

    def _compatibility_report(self) -> str:
        marker = "aucun"
        path = self._crash_marker_path()
        try:
            if path.is_file():
                marker = path.read_text(encoding="utf-8")
        except OSError as exc:
            marker = f"illisible: {exc}"
        return "\n".join(
            (
                f"Cartomize {PLUGIN_VERSION} — diagnostic de compatibilité",
                f"QGIS: {getattr(Qgis, 'QGIS_VERSION', 'unknown')}",
                f"Python: {sys.version}",
                f"Plateforme: {platform.platform()}",
                f"Marqueur de démarrage avancé: {marker}",
            )
        )

    def copy_compatibility_diagnostic(self):
        report = self._compatibility_report()
        QApplication.clipboard().setText(report)
        try:
            self._diagnostic_path().write_text(report, encoding="utf-8")
        except OSError:
            pass
        if self.launcher is not None:
            self.launcher.set_ready(
                f"Diagnostic copié et enregistré dans : {self._diagnostic_path()}"
            )

    def restart_guided_tour(self):
        dock = self._require_full_dock()
        if dock is None:
            return
        QTimer.singleShot(0, dock.start_guided_tour)

    def _require_full_dock(self):
        if self.dock is None:
            self.show_dock()
            self.open_full_interface()
            return None
        return self.dock

    def run_autopilot(self):
        dock = self._require_full_dock()
        if dock is None:
            return
        dock.tabs.setCurrentIndex(0)
        dock.analyze_automation()

    def run_raster_intelligence(self):
        dock = self._require_full_dock()
        if dock is None:
            return
        dock.tabs.setCurrentIndex(1)
        dock._open_raster_intelligence()

    def create_layout(self):
        dock = self._require_full_dock()
        if dock is None:
            return None
        dock.tabs.setCurrentIndex(2)
        return dock.create_layout()

    def open_hd_preview(self):
        dock = self._require_full_dock()
        if dock is None:
            return
        dock.tabs.setCurrentIndex(2)
        dock.open_selected_layout()

    def run_audit(self):
        dock = self._require_full_dock()
        if dock is None:
            return
        dock.tabs.setCurrentIndex(3)
        dock.run_audit()

    def run_batch(self):
        dock = self._require_full_dock()
        if dock is None:
            return
        dock.tabs.setCurrentIndex(4)

    def run_mapops(self):
        dock = self._require_full_dock()
        if dock is None:
            return
        dock.tabs.setCurrentIndex(4)
        dock.check_mapops_changes()

    def run_diagnostics(self):
        dock = self._require_full_dock()
        if dock is None:
            return
        dock.tabs.setCurrentIndex(6)
        dock.run_diagnostics()
