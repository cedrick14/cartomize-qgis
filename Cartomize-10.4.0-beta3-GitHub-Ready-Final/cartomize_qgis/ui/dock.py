"""Panneau principal de Cartomize."""
from __future__ import annotations

from html import escape
from pathlib import Path
import json
import re

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QPixmap
from qgis.PyQt.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsFeedback, QgsProject, QgsRasterLayer, QgsVectorLayer

from ..core.autopilot import AutomationRecipe, CartomizeAutopilot, OBJECTIVES, STYLE_PROFILES
from ..core.batch import (
    BatchJob,
    BatchManifest,
    CartomizeBatchRunner,
    load_manifest,
    save_manifest,
    save_report as save_batch_report,
)
from ..core.community import CommunityClient
from ..core.compat import dialog_exec, user_role, project_read_entry, project_write_entry
from ..core.constants import PLUGIN_VERSION
from ..core.diagnostics import DiagnosticEngine
from ..core.errors import CartomizeError
from ..core.exporter import NativeLayoutExporter
from ..core.layout_builder import LayoutBuildOptions, LayoutBuilder
from ..core.project_service import ProjectService
from ..core.preview import HighDefinitionPreviewController
from ..core.quality import ProjectQualityAuditor, severity_label
from ..core.human_validation import HumanValidationService, MANDATORY_CHECKS
from ..core.mapops import MapOpsMonitor, MapOpsService, MapOpsSnapshot
from ..core.settings import CartomizeSettings
from ..core.symbology import SmartSymbologyService
from ..core.template_catalog import TemplateCatalog
from .settings_dialog import SettingsDialog
from .raster_intelligence_dialog import RasterIntelligenceDialog




_CARTOMIZE_QSS = r"""
QWidget#CartomizeContent {
    background: palette(window);
}
QFrame[role="brandHeader"] {
    background: palette(base);
    border-bottom: 1px solid rgba(100, 116, 139, 70);
}
QLabel[role="brandTitle"] {
    font-size: 18px;
    font-weight: 700;
}
QLabel[role="brandSubtitle"],
QLabel[role="pageDescription"],
QLabel[role="sectionDescription"],
QLabel[role="muted"] {
    color: palette(mid);
}
QLabel[role="pageTitle"] {
    font-size: 17px;
    font-weight: 700;
}
QLabel[role="sectionTitle"] {
    font-size: 13px;
    font-weight: 700;
}
QFrame[role="card"] {
    background: palette(base);
    border: 1px solid rgba(100, 116, 139, 65);
    border-radius: 8px;
}
QLineEdit, QComboBox, QSpinBox, QTextEdit, QTextBrowser,
QListWidget, QTreeWidget {
    border: 1px solid rgba(100, 116, 139, 80);
    border-radius: 5px;
    padding: 4px;
    background: palette(base);
    selection-background-color: #0f6cbd;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QTextEdit:focus, QListWidget:focus, QTreeWidget:focus {
    border: 1px solid #0f6cbd;
}
QPushButton {
    min-height: 30px;
    padding: 5px 10px;
    border-radius: 5px;
    border: 1px solid rgba(100, 116, 139, 90);
    background: palette(button);
}
QPushButton:hover {
    border-color: #0f6cbd;
}
QPushButton[variant="primary"] {
    background: #0f6cbd;
    color: white;
    border: 1px solid #0f6cbd;
    font-weight: 600;
}
QPushButton[variant="primary"]:hover {
    background: #0b5ca8;
}
QPushButton[variant="quiet"] {
    background: transparent;
}
QProgressBar {
    min-height: 18px;
    border: 1px solid rgba(100, 116, 139, 80);
    border-radius: 5px;
    text-align: center;
}
QProgressBar::chunk {
    background: #0f6cbd;
    border-radius: 4px;
}
QTabWidget::pane {
    border: 0;
}
QTabBar::tab {
    min-width: 84px;
    min-height: 28px;
    padding: 5px 10px;
}
QTabBar::tab:selected {
    font-weight: 700;
}
QScrollArea {
    border: 0;
    background: transparent;
}
QHeaderView::section {
    padding: 6px;
    font-weight: 600;
    border: 0;
    border-bottom: 1px solid rgba(100, 116, 139, 75);
}
QFrame[role="footer"] {
    border-top: 1px solid rgba(100, 116, 139, 65);
}
"""

_CATEGORY_LABELS = {
    "administrative": "Administration",
    "agriculture": "Agriculture",
    "amenagement": "Aménagement du territoire",
    "atlas": "Atlas",
    "biodiversite": "Biodiversité",
    "demographie": "Démographie",
    "energie": "Énergie",
    "environnement": "Environnement",
    "humanitaire": "Humanitaire",
    "hydrologique": "Hydrologie",
    "occupation_sol": "Occupation du sol",
    "risques": "Risques",
    "sante": "Santé",
    "scientifique": "Publication scientifique",
    "topographique": "Topographie",
    "transport": "Transport",
    "urbanisme": "Urbanisme",
}


class CartomizeDock(QDockWidget):
    def __init__(self, iface, plugin_root: Path, parent=None):
        super().__init__("Cartomize", parent or iface.mainWindow())
        self.setObjectName("CartomizeDock")
        self.iface = iface
        self.plugin_root = plugin_root.resolve()
        self.project = QgsProject.instance()
        self.project_service = ProjectService(iface, self.project)
        self.preview = HighDefinitionPreviewController(iface)
        self.catalog = TemplateCatalog(self.plugin_root / "templates_library")
        self.builder = LayoutBuilder(
            iface,
            self.project,
            self.plugin_root / "resources",
        )
        self.exporter = NativeLayoutExporter()
        self.symbology = SmartSymbologyService(self.project)
        self.auditor = ProjectQualityAuditor(self.project)
        self.autopilot = CartomizeAutopilot(
            iface,
            self.catalog,
            self.project,
            self.builder,
            self.symbology,
            self.auditor,
        )
        self.raster_symbology = self.autopilot.styling.raster
        self.batch_runner = CartomizeBatchRunner(
            self.autopilot, self.exporter, self.project, PLUGIN_VERSION
        )
        self.mapops_service = MapOpsService(self.project)
        self.mapops_monitor = MapOpsMonitor(self.mapops_service, self)
        try:
            stored_mapops = project_read_entry(self.project, "mapops_baseline", "")
            if stored_mapops:
                self.mapops_monitor.baseline = MapOpsSnapshot.from_dict(json.loads(str(stored_mapops)))
        except Exception:
            pass
        self.validator = HumanValidationService(self.project, PLUGIN_VERSION)
        self.current_automatic_score = 0
        self.community = CommunityClient()
        self.diagnostics = DiagnosticEngine(self.plugin_root)
        self.settings = CartomizeSettings.load()
        self.current_report = None
        self.current_vector_profile = None
        self.current_automation_plan = None
        self.last_automation_recipe = None
        try:
            stored_recipe = project_read_entry(self.project, "autopilot_last_recipe", "")
            if stored_recipe:
                self.last_automation_recipe = AutomationRecipe.from_dict(json.loads(str(stored_recipe)))
        except Exception:
            pass
        self.mapops_monitor.changesDetected.connect(self._on_mapops_changes)

        self.setMinimumWidth(420)
        content = QWidget()
        content.setObjectName("CartomizeContent")
        content.setStyleSheet(_CARTOMIZE_QSS)
        self.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setProperty("role", "brandHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 10, 12, 10)
        header_layout.setSpacing(10)

        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignCenter)
        icon_path = self.plugin_root / "icon-hd.png"
        if not icon_path.is_file():
            icon_path = self.plugin_root / "icon.png"
        if icon_path.is_file():
            source = QPixmap(str(icon_path))
            # Render at the physical pixel density of the current display.
            # This avoids the blurred 38 px bitmap that Windows would upscale
            # on 125 %, 150 % or 200 % display scaling.
            try:
                screen = QApplication.primaryScreen()
                dpr = float(screen.devicePixelRatio()) if screen is not None else 1.0
            except Exception:
                dpr = 1.0
            dpr = max(1.0, min(dpr, 4.0))
            logical_size = 56
            physical_size = max(logical_size, int(round(logical_size * dpr)))
            pixmap = source.scaled(
                physical_size,
                physical_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            try:
                pixmap.setDevicePixelRatio(dpr)
            except Exception:
                pass
            icon_label.setPixmap(pixmap)
        icon_label.setFixedSize(60, 60)
        header_layout.addWidget(icon_label)

        brand_text = QVBoxLayout()
        brand_text.setSpacing(1)
        brand_title = QLabel("Cartomize")
        brand_title.setProperty("role", "brandTitle")
        brand_subtitle = QLabel("Automatisation et mise en page pour QGIS")
        brand_subtitle.setProperty("role", "brandSubtitle")
        brand_subtitle.setWordWrap(True)
        brand_text.addWidget(brand_title)
        brand_text.addWidget(brand_subtitle)
        header_layout.addLayout(brand_text, 1)

        root.addWidget(header)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(False)
        self.tabs.setUsesScrollButtons(True)
        root.addWidget(self.tabs, 1)

        self._build_automation_tab()
        self._build_project_tab()
        self._build_layout_tab()
        self._build_quality_tab()
        self._build_production_tab()
        self._build_community_tab()
        self._build_diagnostics_tab()

        footer = QFrame()
        footer.setProperty("role", "footer")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(10, 5, 10, 5)
        self.footer_status = QLabel("Prêt")
        self.footer_status.setProperty("role", "muted")
        self.footer_status.setWordWrap(True)
        footer_layout.addWidget(self.footer_status, 1)
        root.addWidget(footer)

        self._connect_signals()
        self.refresh_all()
        self.run_diagnostics()

    def _create_page(self, title: str, description: str):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(12, 12, 12, 14)
        page_layout.setSpacing(12)

        page_title = QLabel(title)
        page_title.setProperty("role", "pageTitle")
        page_layout.addWidget(page_title)

        if description:
            page_description = QLabel(description)
            page_description.setProperty("role", "pageDescription")
            page_description.setWordWrap(True)
            page_layout.addWidget(page_description)

        scroll.setWidget(page)
        return scroll, page, page_layout

    def _create_card(self, title: str, description: str = ""):
        card = QFrame()
        card.setProperty("role", "card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 11, 12, 12)
        card_layout.setSpacing(9)

        heading = QLabel(title)
        heading.setProperty("role", "sectionTitle")
        card_layout.addWidget(heading)

        if description:
            details = QLabel(description)
            details.setProperty("role", "sectionDescription")
            details.setWordWrap(True)
            card_layout.addWidget(details)

        return card, card_layout

    @staticmethod
    def _style_button(button: QPushButton, variant: str = "secondary"):
        button.setProperty("variant", variant)
        button.setMinimumHeight(32)
        return button

    @staticmethod
    def _configure_tree(tree: QTreeWidget):
        tree.setAlternatingRowColors(True)
        tree.setRootIsDecorated(False)
        tree.setUniformRowHeights(True)
        tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        tree.setSelectionMode(QAbstractItemView.SingleSelection)
        tree.header().setStretchLastSection(True)

    def dispose(self):
        self.mapops_monitor.dispose()
        connections = (
            (self.project.layersAdded, self._project_changed),
            (self.project.layersRemoved, self._project_changed),
            (self.iface.currentLayerChanged, self._active_layer_changed),
        )
        for signal, slot in connections:
            try:
                signal.disconnect(slot)
            except Exception:
                pass
        try:
            self.project.readProject.disconnect(self._project_changed)
        except Exception:
            pass

    def _build_automation_tab(self):
        scroll, _tab, layout = self._create_page(
            "Automatisation",
            "Analysez le projet, comparez plusieurs propositions et créez une carte QGIS native en suivant un plan explicable.",
        )

        settings_card, settings_layout = self._create_card(
            "Préparer l’analyse",
            "Définissez l’objectif et les données à prendre en compte. Les valeurs automatiques conviennent à la plupart des projets.",
        )
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.automation_objective = QComboBox()
        for code, label in OBJECTIVES:
            self.automation_objective.addItem(label, code)
        self.automation_main_layer = QComboBox()
        self.automation_style = QComboBox()
        for code, label in STYLE_PROFILES:
            self.automation_style.addItem(label, code)
        self.automation_sources = QLineEdit()
        self.automation_sources.setPlaceholderText("Sources, année et crédits cartographiques")
        form.addRow("Objectif", self.automation_objective)
        form.addRow("Couche principale", self.automation_main_layer)
        form.addRow("Style de composition", self.automation_style)
        form.addRow("Sources", self.automation_sources)
        settings_layout.addLayout(form)

        options_grid = QGridLayout()
        options_grid.setHorizontalSpacing(12)
        options_grid.setVerticalSpacing(8)
        self.automation_visible_only = QCheckBox("Limiter l’analyse aux couches visibles")
        self.automation_visible_only.setChecked(True)
        self.automation_apply_symbology = QCheckBox("Harmoniser la symbologie du projet")
        self.automation_apply_symbology.setChecked(True)
        self.automation_auto_correct = QCheckBox("Corriger automatiquement la lisibilité")
        self.automation_auto_correct.setChecked(True)
        options_grid.addWidget(self.automation_visible_only, 0, 0, 1, 2)
        options_grid.addWidget(self.automation_apply_symbology, 1, 0, 1, 2)
        options_grid.addWidget(self.automation_auto_correct, 2, 0, 1, 2)
        settings_layout.addLayout(options_grid)

        self.automation_analyze_button = self._style_button(
            QPushButton("Analyser le projet"), "primary"
        )
        self.automation_analyze_button.setToolTip(
            "Détecter le type de carte, la couche principale et les maquettes les plus adaptées."
        )
        settings_layout.addWidget(self.automation_analyze_button)
        layout.addWidget(settings_card)

        plan_card, plan_layout = self._create_card(
            "Plan cartographique recommandé",
            "Le rapport présente les décisions proposées avant toute modification du projet.",
        )
        self.automation_plan_text = QTextBrowser()
        self.automation_plan_text.setMinimumHeight(170)
        self.automation_plan_text.setHtml(
            "<p>Lancez l’analyse pour obtenir une recommandation structurée.</p>"
        )
        plan_layout.addWidget(self.automation_plan_text)
        self.automation_progress = QProgressBar()
        self.automation_progress.setRange(0, 100)
        self.automation_progress.setValue(0)
        self.automation_progress.setTextVisible(True)
        plan_layout.addWidget(self.automation_progress)
        layout.addWidget(plan_card)

        variants_card, variants_layout = self._create_card(
            "Propositions",
            "Comparez les variantes selon leur score, leur maquette et les principales décisions de composition.",
        )
        self.automation_variants = QTreeWidget()
        self.automation_variants.setHeaderLabels(
            ["Score", "Proposition", "Maquette", "Format", "Décisions"]
        )
        self.automation_variants.setMinimumHeight(220)
        self._configure_tree(self.automation_variants)
        header = self.automation_variants.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        variants_layout.addWidget(self.automation_variants)

        self.automation_generate_button = self._style_button(
            QPushButton("Créer la proposition sélectionnée"), "primary"
        )
        self.automation_generate_all_button = self._style_button(
            QPushButton("Créer les trois propositions")
        )
        variants_layout.addWidget(self.automation_generate_button)
        variants_layout.addWidget(self.automation_generate_all_button)
        layout.addWidget(variants_card)

        recipe_card, recipe_layout = self._create_card(
            "Recettes réutilisables",
            "Enregistrez les décisions cartographiques pour reproduire la même carte avec de nouvelles données.",
        )
        recipe_actions = QGridLayout()
        self.automation_save_recipe_button = self._style_button(
            QPushButton("Enregistrer la recette")
        )
        self.automation_replay_recipe_button = self._style_button(
            QPushButton("Rejouer une recette")
        )
        recipe_actions.addWidget(self.automation_save_recipe_button, 0, 0)
        recipe_actions.addWidget(self.automation_replay_recipe_button, 0, 1)
        recipe_layout.addLayout(recipe_actions)
        layout.addWidget(recipe_card)
        layout.addStretch(1)

        self.tabs.addTab(scroll, "Automatisation")
        self.automation_analyze_button.clicked.connect(self.analyze_automation)
        self.automation_generate_button.clicked.connect(self.generate_selected_variant)
        self.automation_generate_all_button.clicked.connect(self.generate_all_variants)
        self.automation_save_recipe_button.clicked.connect(self.save_automation_recipe)
        self.automation_replay_recipe_button.clicked.connect(self.replay_automation_recipe)

    def _build_project_tab(self):
        scroll, _tab, layout = self._create_page(
            "Projet",
            "Consultez l’état du projet, sélectionnez une couche et appliquez une recommandation de symbologie réversible.",
        )

        summary_card, summary_layout = self._create_card("Vue d’ensemble du projet")
        self.project_summary = QTextBrowser()
        self.project_summary.setMinimumHeight(150)
        summary_layout.addWidget(self.project_summary)
        layout.addWidget(summary_card)

        layer_card, layer_layout = self._create_card(
            "Couche active",
            "Les actions utilisent la couche choisie ici, sans modifier les autres couches du projet.",
        )
        layer_form = QFormLayout()
        layer_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.layer_combo = QComboBox()
        layer_form.addRow("Couche", self.layer_combo)
        layer_layout.addLayout(layer_form)
        layer_actions = QGridLayout()
        self.zoom_button = self._style_button(QPushButton("Afficher l’emprise"))
        self.zoom_button.setToolTip("Centrer le canevas QGIS sur la couche sélectionnée.")
        self.properties_button = self._style_button(QPushButton("Ouvrir les propriétés"))
        self.properties_button.setToolTip("Ouvrir les propriétés QGIS de la couche sélectionnée.")
        layer_actions.addWidget(self.zoom_button, 0, 0)
        layer_actions.addWidget(self.properties_button, 0, 1)
        layer_layout.addLayout(layer_actions)
        layout.addWidget(layer_card)

        recommendation_card, recommendation_layout = self._create_card(
            "Recommandation de symbologie",
            "La proposition tient compte du type de géométrie, des champs et du rôle probable de la couche.",
        )
        self.recommendation = QTextBrowser()
        self.recommendation.setMinimumHeight(190)
        recommendation_layout.addWidget(self.recommendation)
        self.apply_style_button = self._style_button(
            QPushButton("Appliquer la recommandation"), "primary"
        )
        self.undo_style_button = self._style_button(
            QPushButton("Restaurer le style précédent")
        )
        recommendation_layout.addWidget(self.apply_style_button)
        recommendation_layout.addWidget(self.undo_style_button)
        self.raster_intelligence_button = self._style_button(
            QPushButton("Ouvrir Raster Intelligence")
        )
        self.raster_intelligence_button.setToolTip(
            "Analyser le NoData, les classes, les fréquences, les anomalies et la symbologie d’un raster."
        )
        self.raster_intelligence_button.setEnabled(False)
        recommendation_layout.addWidget(self.raster_intelligence_button)
        layout.addWidget(recommendation_card)
        layout.addStretch(1)

        self.tabs.addTab(scroll, "Projet")
        self.layer_combo.currentIndexChanged.connect(self._update_recommendation)
        self.zoom_button.clicked.connect(self._zoom_selected_layer)
        self.properties_button.clicked.connect(self._open_layer_properties)
        self.apply_style_button.clicked.connect(self._apply_recommendation)
        self.undo_style_button.clicked.connect(self._undo_recommendation)
        self.raster_intelligence_button.clicked.connect(self._open_raster_intelligence)

    def _build_layout_tab(self):
        scroll, _tab, layout = self._create_page(
            "Mise en page",
            "Choisissez une maquette, renseignez les informations essentielles et produisez une mise en page QGIS native entièrement modifiable.",
        )

        template_card, template_layout = self._create_card(
            "Catalogue de maquettes",
            "Utilisez la recherche et les catégories pour réduire rapidement la liste des 24 maquettes disponibles.",
        )
        filters = QGridLayout()
        filters.setColumnStretch(0, 2)
        filters.setColumnStretch(1, 1)
        self.template_search = QLineEdit()
        self.template_search.setPlaceholderText("Rechercher par titre, thème ou usage")
        self.category_combo = QComboBox()
        filters.addWidget(QLabel("Recherche"), 0, 0)
        filters.addWidget(QLabel("Catégorie"), 0, 1)
        filters.addWidget(self.template_search, 1, 0)
        filters.addWidget(self.category_combo, 1, 1)
        template_layout.addLayout(filters)

        self.template_list = QListWidget()
        self.template_list.setMinimumHeight(190)
        self.template_list.setAlternatingRowColors(True)
        self.template_list.setSelectionMode(QAbstractItemView.SingleSelection)
        template_layout.addWidget(self.template_list)

        details_label = QLabel("Détails de la maquette")
        details_label.setProperty("role", "muted")
        template_layout.addWidget(details_label)
        self.template_details = QTextBrowser()
        self.template_details.setMinimumHeight(145)
        template_layout.addWidget(self.template_details)
        layout.addWidget(template_card)

        settings_card, settings_layout = self._create_card(
            "Contenu de la carte",
            "Ces informations sont ajoutées à la composition et restent modifiables dans le concepteur QGIS.",
        )
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.layout_title = QLineEdit()
        self.layout_title.setPlaceholderText("Titre principal de la carte")
        self.layout_subtitle = QLineEdit()
        self.layout_subtitle.setPlaceholderText("Sous-titre ou période d’analyse")
        self.layout_sources = QLineEdit()
        self.layout_sources.setPlaceholderText("Sources, auteur et date")
        self.margin = QSpinBox()
        self.margin.setRange(0, 50)
        self.margin.setValue(3)
        self.margin.setSuffix(" %")
        form.addRow("Titre", self.layout_title)
        form.addRow("Sous-titre", self.layout_subtitle)
        form.addRow("Sources", self.layout_sources)
        form.addRow("Marge cartographique", self.margin)
        settings_layout.addLayout(form)
        self.visible_only = QCheckBox("Utiliser uniquement les couches visibles")
        self.visible_only.setChecked(True)
        self.add_grid = QCheckBox("Ajouter une grille au cadre principal")
        settings_layout.addWidget(self.visible_only)
        settings_layout.addWidget(self.add_grid)

        self.create_layout_button = self._style_button(
            QPushButton("Créer la mise en page"), "primary"
        )
        self.open_designer_button = self._style_button(
            QPushButton("Ouvrir l’aperçu HD dans QGIS")
        )
        self.open_designer_button.setToolTip(
            "Ouvrir la mise en page avec le profil haute définition et un zoom ajusté à la page."
        )
        settings_layout.addWidget(self.create_layout_button)
        settings_layout.addWidget(self.open_designer_button)
        layout.addWidget(settings_card)

        output_card, output_layout = self._create_card(
            "Aperçu et export",
            "Sélectionnez une mise en page existante, améliorez son rendu puis choisissez un format de sortie.",
        )
        output_form = QFormLayout()
        output_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.layout_combo = QComboBox()
        output_form.addRow("Mise en page", self.layout_combo)
        output_layout.addLayout(output_form)

        preview_actions = QGridLayout()
        self.preview_hd_button = self._style_button(QPushButton("Actualiser l’aperçu HD"))
        self.preview_hd_button.setToolTip(
            "Recalculer les cadres, légendes, images et barres d’échelle avec le profil haute définition."
        )
        self.optimize_layout_button = self._style_button(QPushButton("Améliorer la lisibilité"))
        self.optimize_layout_button.setToolTip(
            "Agrandir les textes, clarifier la légende et corriger les chevauchements."
        )
        preview_actions.addWidget(self.preview_hd_button, 0, 0)
        preview_actions.addWidget(self.optimize_layout_button, 0, 1)
        output_layout.addLayout(preview_actions)

        export_label = QLabel("Formats de sortie")
        export_label.setProperty("role", "muted")
        output_layout.addWidget(export_label)
        export_grid = QGridLayout()
        self.export_pdf_button = self._style_button(QPushButton("Exporter en PDF"), "primary")
        self.export_svg_button = self._style_button(QPushButton("Exporter en SVG"))
        self.export_png_button = self._style_button(QPushButton("Exporter en PNG"))
        self.save_qpt_button = self._style_button(QPushButton("Enregistrer en QPT"))
        export_grid.addWidget(self.export_pdf_button, 0, 0)
        export_grid.addWidget(self.export_svg_button, 0, 1)
        export_grid.addWidget(self.export_png_button, 1, 0)
        export_grid.addWidget(self.save_qpt_button, 1, 1)
        output_layout.addLayout(export_grid)
        layout.addWidget(output_card)
        layout.addStretch(1)

        self.tabs.addTab(scroll, "Mise en page")
        self.template_search.textChanged.connect(self.refresh_templates)
        self.category_combo.currentIndexChanged.connect(self.refresh_templates)
        self.template_list.currentItemChanged.connect(self._show_template_details)
        self.create_layout_button.clicked.connect(self.create_layout)
        self.open_designer_button.clicked.connect(self.open_selected_layout)
        self.preview_hd_button.clicked.connect(self.refresh_hd_preview)
        self.optimize_layout_button.clicked.connect(self.optimize_selected_layout)
        self.export_pdf_button.clicked.connect(lambda: self._export("pdf"))
        self.export_svg_button.clicked.connect(lambda: self._export("svg"))
        self.export_png_button.clicked.connect(lambda: self._export("png"))
        self.save_qpt_button.clicked.connect(lambda: self._export("qpt"))

    def _build_quality_tab(self):
        scroll, _tab, layout = self._create_page(
            "Qualité",
            "Contrôlez la cohérence du projet et des mises en page avant publication. Chaque anomalie est accompagnée d’une action recommandée.",
        )

        score_card, score_layout = self._create_card("Résultat du contrôle")
        self.audit_score = QLabel("Score non évalué")
        self.audit_score.setStyleSheet("font-size: 22px; font-weight: 700;")
        score_layout.addWidget(self.audit_score)
        self.run_audit_button = self._style_button(
            QPushButton("Lancer le contrôle de la qualité"), "primary"
        )
        self.label_audit_button = self._style_button(QPushButton("Vérifier le placement des étiquettes"))
        self.label_audit_status = QLabel("Étiquettes non évaluées")
        self.label_audit_status.setWordWrap(True)
        self.label_audit_status.setProperty("role", "muted")
        score_layout.addWidget(self.run_audit_button)
        score_layout.addWidget(self.label_audit_button)
        score_layout.addWidget(self.label_audit_status)
        layout.addWidget(score_card)

        issues_card, issues_layout = self._create_card(
            "Observations",
            "Sélectionnez une ligne pour examiner le niveau, la couche concernée et la correction proposée.",
        )
        self.audit_tree = QTreeWidget()
        self.audit_tree.setHeaderLabels(
            ["Niveau", "Code", "Couche", "Observation et action recommandée"]
        )
        self.audit_tree.setMinimumHeight(330)
        self._configure_tree(self.audit_tree)
        audit_header = self.audit_tree.header()
        audit_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        audit_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        audit_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        audit_header.setSectionResizeMode(3, QHeaderView.Stretch)
        issues_layout.addWidget(self.audit_tree)
        self.copy_audit_button = self._style_button(QPushButton("Copier le rapport"))
        issues_layout.addWidget(self.copy_audit_button)
        layout.addWidget(issues_card)
        layout.addStretch(1)

        self.tabs.addTab(scroll, "Qualité")
        self.run_audit_button.clicked.connect(self.run_audit)
        self.label_audit_button.clicked.connect(self.run_label_audit)
        self.copy_audit_button.clicked.connect(self.copy_audit)

    def _build_production_tab(self):
        scroll, _tab, layout = self._create_page(
            "Production",
            "Produisez des séries de cartes, surveillez les changements du projet et formalisez la validation du cartographe.",
        )

        batch_card, batch_layout = self._create_card(
            "Production en série",
            "Un manifeste JSON décrit les cartes à produire, les variables et les formats de sortie.",
        )
        manifest_grid = QGridLayout()
        manifest_grid.setColumnStretch(0, 1)
        self.batch_manifest_path = QLineEdit()
        self.batch_manifest_path.setPlaceholderText("Chemin du manifeste de production")
        self.batch_select_button = self._style_button(QPushButton("Parcourir"))
        manifest_grid.addWidget(self.batch_manifest_path, 0, 0)
        manifest_grid.addWidget(self.batch_select_button, 0, 1)
        batch_layout.addLayout(manifest_grid)
        self.batch_create_button = self._style_button(QPushButton("Créer un manifeste"))
        self.batch_run_button = self._style_button(QPushButton("Exécuter la série"), "primary")
        batch_layout.addWidget(self.batch_create_button)
        batch_layout.addWidget(self.batch_run_button)
        self.batch_status = QTextBrowser()
        self.batch_status.setMinimumHeight(135)
        self.batch_status.setPlainText(
            "Sélectionnez ou créez un manifeste. Cartomize peut produire jusqu’à 5 000 cartes par série."
        )
        batch_layout.addWidget(self.batch_status)
        layout.addWidget(batch_card)

        mapops_card, mapops_layout = self._create_card(
            "Suivi MapOps",
            "Comparez l’état actuel du projet à une référence et identifiez les cartes à régénérer.",
        )
        mapops_actions = QGridLayout()
        self.mapops_baseline_button = self._style_button(QPushButton("Créer l’état de référence"))
        self.mapops_check_button = self._style_button(QPushButton("Vérifier les changements"), "primary")
        self.mapops_accept_button = self._style_button(QPushButton("Accepter l’état actuel"))
        self.mapops_regenerate_button = self._style_button(QPushButton("Régénérer la dernière recette"))
        mapops_actions.addWidget(self.mapops_baseline_button, 0, 0)
        mapops_actions.addWidget(self.mapops_check_button, 0, 1)
        mapops_actions.addWidget(self.mapops_accept_button, 1, 0)
        mapops_actions.addWidget(self.mapops_regenerate_button, 1, 1)
        mapops_layout.addLayout(mapops_actions)
        self.mapops_auto_regenerate = QCheckBox("Régénérer automatiquement la dernière recette lorsque des données utilisées changent")
        self.mapops_auto_regenerate.setChecked(False)
        self.mapops_auto_regenerate.setToolTip(
            "Cartomize attend la fin des changements, rejoue la dernière recette et conserve la validation humaine à refaire."
        )
        mapops_layout.addWidget(self.mapops_auto_regenerate)
        self.mapops_report = QTextBrowser()
        self.mapops_report.setMinimumHeight(160)
        self.mapops_report.setPlainText("Aucun changement vérifié.")
        mapops_layout.addWidget(self.mapops_report)
        layout.addWidget(mapops_card)

        validation_card, validation_layout = self._create_card(
            "Validation cartographique",
            "L’approbation humaine reste distincte du score automatique et produit un certificat traçable.",
        )
        validation_form = QFormLayout()
        validation_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.validation_reviewer = QLineEdit()
        self.validation_reviewer.setPlaceholderText("Nom du cartographe responsable")
        self.validation_organization = QLineEdit()
        self.validation_organization.setPlaceholderText("Organisation")
        validation_form.addRow("Réviseur", self.validation_reviewer)
        validation_form.addRow("Organisation", self.validation_organization)
        validation_layout.addLayout(validation_form)

        checklist_label = QLabel("Liste de contrôle obligatoire")
        checklist_label.setProperty("role", "muted")
        validation_layout.addWidget(checklist_label)
        self.validation_checks = {}
        for key, label in MANDATORY_CHECKS:
            checkbox = QCheckBox(label)
            self.validation_checks[key] = checkbox
            validation_layout.addWidget(checkbox)

        notes_label = QLabel("Notes et réserves")
        notes_label.setProperty("role", "muted")
        validation_layout.addWidget(notes_label)
        self.validation_notes = QTextEdit()
        self.validation_notes.setPlaceholderText(
            "Précisez les limites des données, les réserves ou les corrections demandées."
        )
        self.validation_notes.setMinimumHeight(110)
        validation_layout.addWidget(self.validation_notes)

        self.validation_approve_button = self._style_button(
            QPushButton("Approuver la mise en page"), "primary"
        )
        self.validation_export_button = self._style_button(
            QPushButton("Exporter le certificat")
        )
        validation_layout.addWidget(self.validation_approve_button)
        validation_layout.addWidget(self.validation_export_button)
        self.validation_status = QLabel("Statut : en attente de validation humaine")
        self.validation_status.setWordWrap(True)
        self.validation_status.setProperty("role", "muted")
        validation_layout.addWidget(self.validation_status)
        layout.addWidget(validation_card)
        layout.addStretch(1)

        self.tabs.addTab(scroll, "Production")
        self.batch_select_button.clicked.connect(self.choose_batch_manifest)
        self.batch_create_button.clicked.connect(self.create_batch_manifest)
        self.batch_run_button.clicked.connect(self.run_batch_manifest)
        self.mapops_baseline_button.clicked.connect(self.create_mapops_baseline)
        self.mapops_check_button.clicked.connect(self.check_mapops_changes)
        self.mapops_accept_button.clicked.connect(self.accept_mapops_state)
        self.mapops_regenerate_button.clicked.connect(self.regenerate_after_mapops)
        self.validation_approve_button.clicked.connect(self.approve_selected_layout)
        self.validation_export_button.clicked.connect(self.export_validation_certificate)

    def _build_community_tab(self):
        scroll, _tab, layout = self._create_page(
            "Communauté",
            "Consultez les maquettes et ressources partagées sans transmettre automatiquement les données de votre projet QGIS.",
        )

        info_card, info_layout = self._create_card(
            "Cartomize Community",
            "Téléchargez des maquettes, découvrez les créations de la communauté et publiez volontairement vos propres ressources.",
        )
        community_text = QLabel(
            "L’ouverture de Community se fait dans votre navigateur. Les couches, attributs et emprises restent locaux tant qu’aucun partage n’est lancé explicitement."
        )
        community_text.setWordWrap(True)
        info_layout.addWidget(community_text)
        layout.addWidget(info_card)

        service_card, service_layout = self._create_card("Service configuré")
        self.community_label = QLabel()
        self.community_label.setWordWrap(True)
        service_layout.addWidget(self.community_label)
        self.open_community_button = self._style_button(
            QPushButton("Ouvrir la communauté"), "primary"
        )
        self.settings_button = self._style_button(QPushButton("Configurer le service"))
        service_layout.addWidget(self.open_community_button)
        service_layout.addWidget(self.settings_button)
        layout.addWidget(service_card)
        layout.addStretch(1)

        self.tabs.addTab(scroll, "Communauté")
        self.open_community_button.clicked.connect(self.open_community)
        self.settings_button.clicked.connect(self.open_settings)

    def _build_diagnostics_tab(self):
        scroll, _tab, layout = self._create_page(
            "Système",
            "Vérifiez la disponibilité des composants QGIS requis et consultez l’état technique du plugin.",
        )
        diagnostic_card, diagnostic_layout = self._create_card("Diagnostic")
        self.diagnostic_text = QTextBrowser()
        self.diagnostic_text.setMinimumHeight(360)
        diagnostic_layout.addWidget(self.diagnostic_text)
        self.diagnostic_button = self._style_button(
            QPushButton("Actualiser l’état du système"), "primary"
        )
        diagnostic_layout.addWidget(self.diagnostic_button)
        layout.addWidget(diagnostic_card)
        layout.addStretch(1)

        self.tabs.addTab(scroll, "Système")
        self.diagnostic_button.clicked.connect(self.run_diagnostics)

    def _connect_signals(self):
        self.project.layersAdded.connect(self._project_changed)
        self.project.layersRemoved.connect(self._project_changed)
        try:
            self.project.readProject.connect(self._project_changed)
        except Exception:
            pass
        self.iface.currentLayerChanged.connect(self._active_layer_changed)

    def _project_changed(self, *_):
        self.current_automation_plan = None
        self.refresh_all()

    def _active_layer_changed(self, *_):
        self.refresh_layers()
        self.refresh_automation_layers()

    def refresh_all(self):
        self.settings = CartomizeSettings.load()
        configured = self.settings.community_url or "Non configuré"
        self.community_label.setText(f"Adresse du service : {configured}")
        self.refresh_project_summary()
        self.refresh_layers()
        self.refresh_automation_layers()
        self.refresh_categories()
        self.refresh_templates()
        self.refresh_layouts()

    def refresh_automation_layers(self):
        if not hasattr(self, "automation_main_layer"):
            return
        previous = self.automation_main_layer.currentData()
        active = self.iface.activeLayer()
        self.automation_main_layer.blockSignals(True)
        self.automation_main_layer.clear()
        self.automation_main_layer.addItem("Détection automatique", "")
        for layer in self.project_service.ordered_layers():
            if not layer or not layer.isValid():
                continue
            crs = layer.crs().authid() or "CRS non défini"
            self.automation_main_layer.addItem(f"{layer.name()} ({crs})", layer.id())
        wanted = active.id() if active and active.isValid() else previous
        index = self.automation_main_layer.findData(wanted)
        self.automation_main_layer.setCurrentIndex(index if index >= 0 else 0)
        self.automation_main_layer.blockSignals(False)

    def analyze_automation(self):
        try:
            self.automation_progress.setValue(10)
            plan = self.autopilot.analyze(
                objective=self.automation_objective.currentData() or "auto",
                main_layer_id=self.automation_main_layer.currentData() or "",
                style_profile=self.automation_style.currentData() or "balanced",
                visible_only=self.automation_visible_only.isChecked(),
            )
            self.current_automation_plan = plan
            self.automation_variants.clear()
            for index, variant in enumerate(plan.variants):
                item = QTreeWidgetItem(
                    self.automation_variants,
                    [
                        f"{variant.score}/100",
                        variant.name,
                        variant.template_name,
                        variant.page_format,
                        " ".join(variant.reasons),
                    ],
                )
                item.setData(0, user_role(), index)
            if self.automation_variants.topLevelItemCount():
                self.automation_variants.setCurrentItem(self.automation_variants.topLevelItem(0))
            self.automation_variants.resizeColumnToContents(0)
            self.automation_variants.resizeColumnToContents(1)
            warnings = "".join(f"<li>{escape(text)}</li>" for text in plan.warnings)
            warning_block = f"<h4>Points à vérifier</h4><ul>{warnings}</ul>" if warnings else ""
            intel = plan.intelligence or {}
            graph = intel.get("graph") or {}
            vectors = intel.get("vector_profiles") or []
            rasters = intel.get("raster_summaries") or []
            memory = intel.get("memory_suggestions") or []
            memory_block = ""
            if memory:
                memory_block = "<h4>Préférences locales apprises</h4><ul>" + "".join(
                    f"<li>{escape(str(item))}</li>" for item in memory
                ) + "</ul>"
            self.automation_plan_text.setHtml(
                f"<h3>{escape(plan.objective_label)}</h3>"
                "<table cellspacing='4'>"
                f"<tr><td><b>Couche principale</b></td><td>{escape(plan.main_layer_name)}</td></tr>"
                f"<tr><td><b>CRS de travail</b></td><td>{escape(plan.project_crs)}</td></tr>"
                f"<tr><td><b>Confiance de l’objectif</b></td><td>{plan.confidence:.0%}</td></tr>"
                f"<tr><td><b>Qualité des données</b></td><td>{int(intel.get('data_quality_score', 0))}/100</td></tr>"
                f"<tr><td><b>Confiance Geo Intelligence</b></td><td>{int(intel.get('automation_confidence', 0))}/100</td></tr>"
                f"<tr><td><b>Vecteurs analysés</b></td><td>{len(vectors)}</td></tr>"
                f"<tr><td><b>Rasters analysés</b></td><td>{len(rasters)}</td></tr>"
                f"<tr><td><b>Relations entre couches</b></td><td>{len(graph.get('relations') or [])}</td></tr>"
                "</table>"
                f"<p>{escape(plan.map_type_reason)}</p>{memory_block}{warning_block}"
            )
            self.automation_progress.setValue(100)
            self._message(
                "Automatisation",
                "Le projet a été analysé et trois propositions sont disponibles.",
                True,
            )
        except Exception as exc:
            self.automation_progress.setValue(0)
            self._error("Automatisation", exc)

    def generate_selected_variant(self):
        if self.current_automation_plan is None:
            self.analyze_automation()
        if self.current_automation_plan is None:
            return
        current = self.automation_variants.currentItem()
        index = current.data(0, user_role()) if current else 0
        self._execute_automation_variant(int(index or 0), open_preview=True)

    def generate_all_variants(self):
        if self.current_automation_plan is None:
            self.analyze_automation()
        plan = self.current_automation_plan
        if plan is None:
            return
        created = []
        total = max(1, len(plan.variants))
        for index, _variant in enumerate(plan.variants):
            self.automation_progress.setValue(round(index * 100 / total))
            QApplication.processEvents()
            result = self._execute_automation_variant(index, open_preview=False)
            if result is not None:
                created.append(result)
        self.automation_progress.setValue(100)
        if created:
            best = max(created, key=lambda result: result.final_score)
            self.preview.open(best.layout, self.settings.preview_width_px, zoom_mode="width")
            self._message(
                "Automatisation",
                f"{len(created)} propositions créées. Meilleur score automatique : {best.final_score}/100. Validation cartographe requise.",
                True,
            )

    def _execute_automation_variant(self, index: int, *, open_preview: bool):
        plan = self.current_automation_plan
        if plan is None:
            return None
        try:
            self.automation_progress.setValue(35)
            QApplication.processEvents()
            result = self.autopilot.execute_variant(
                plan,
                index,
                apply_symbology=self.automation_apply_symbology.isChecked(),
                auto_correct=self.automation_auto_correct.isChecked(),
                visible_only=self.automation_visible_only.isChecked(),
                sources=self.automation_sources.text().strip(),
            )
            self.last_automation_recipe = result.recipe
            self.current_automatic_score = result.final_score
            self.validation_status.setText(
                f"Statut : {result.validation_status}. Données : {result.data_quality_score}/100. "
                f"Cartographie : {result.cartographic_score}/100. "
                f"Confiance : {result.automation_confidence}/100. Synthèse : {result.final_score}/100."
            )
            self.refresh_layouts()
            layout_index = self.layout_combo.findData(result.layout_name)
            if layout_index >= 0:
                self.layout_combo.setCurrentIndex(layout_index)
            self.automation_progress.setValue(85)
            if open_preview:
                self.preview.open(result.layout, self.settings.preview_width_px, zoom_mode="width")
            detail = (
                f"{result.variant_name} créée. Qualité des données : {result.data_quality_score}/100. "
                f"Qualité cartographique : {result.cartographic_score}/100. "
                f"Confiance de l’automatisation : {result.automation_confidence}/100. "
                f"Synthèse : {result.final_score}/100. Validation cartographe requise. "
                f"Mise en page : {result.layout_name}."
            )
            if result.corrections:
                detail += " Corrections : " + ", ".join(result.corrections) + "."
            if result.warnings:
                detail += " Points à vérifier : " + " ".join(result.warnings)
            self._message("Cartomize Autopilot", detail, result.final_score >= 75)
            self.automation_progress.setValue(100)
            return result
        except Exception as exc:
            self.automation_progress.setValue(0)
            self._error("Cartomize Autopilot", exc)
            return None

    def save_automation_recipe(self):
        if self.last_automation_recipe is None:
            self._message(
                "Recette Cartomize",
                "Créez d’abord une proposition afin d’enregistrer sa recette.",
            )
            return
        default = Path.home() / "recette-cartomize.cartomize.json"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Enregistrer la recette Cartomize",
            str(default),
            "Recette Cartomize (*.cartomize.json);;JSON (*.json)",
        )
        if not path:
            return
        try:
            output = self.autopilot.save_recipe(self.last_automation_recipe, path)
            self._message("Recette Cartomize", f"Recette enregistrée : {output}", True)
        except Exception as exc:
            self._error("Recette Cartomize", exc)

    def replay_automation_recipe(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Rejouer une recette Cartomize",
            str(Path.home()),
            "Recette Cartomize (*.cartomize.json *.json)",
        )
        if not path:
            return
        try:
            recipe = self.autopilot.load_recipe(path)
            result = self.autopilot.replay_recipe(recipe)
            self.last_automation_recipe = result.recipe
            self.current_automatic_score = result.final_score
            self.validation_status.setText(
                f"Statut : {result.validation_status}. Données : {result.data_quality_score}/100. "
                f"Cartographie : {result.cartographic_score}/100. "
                f"Confiance : {result.automation_confidence}/100. Synthèse : {result.final_score}/100."
            )
            self.refresh_layouts()
            index = self.layout_combo.findData(result.layout_name)
            if index >= 0:
                self.layout_combo.setCurrentIndex(index)
            self.preview.open(result.layout, self.settings.preview_width_px, zoom_mode="width")
            self._message(
                "Recette Cartomize",
                f"Recette rejouée. Score automatique : {result.final_score}/100. Validation cartographe requise.",
                True,
            )
        except Exception as exc:
            self._error("Recette Cartomize", exc)

    def choose_batch_manifest(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choisir un manifeste de production",
            str(Path.home()),
            "Manifeste Cartomize (*.json)",
        )
        if path:
            self.batch_manifest_path.setText(path)

    def create_batch_manifest(self):
        if self.last_automation_recipe is None:
            self._message(
                "Production en série",
                "Créez d’abord une carte avec Autopilot afin de disposer d’une recette.",
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Créer un manifeste de production",
            str(Path.home() / "production-cartomize.json"),
            "Manifeste JSON (*.json)",
        )
        if not path:
            return
        try:
            destination = Path(path).expanduser().resolve(strict=False)
            recipe_path = destination.with_name("recette-production.cartomize.json")
            self.autopilot.save_recipe(self.last_automation_recipe, recipe_path)
            manifest = BatchManifest(
                1,
                str(recipe_path),
                str(destination.parent / "exports-cartomize"),
                (
                    BatchJob(
                        "carte-1",
                        "carte-1",
                        title=str(self.last_automation_recipe.variant.get("title") or "Carte 1"),
                        sources=self.last_automation_recipe.sources,
                        output_formats=("pdf", "png"),
                    ),
                ),
                dpi=self.settings.default_dpi,
                keep_layouts=False,
                require_human_validation=True,
            )
            output = save_manifest(manifest, destination)
            self.batch_manifest_path.setText(str(output))
            self.batch_status.setPlainText(
                "Manifeste créé. Dupliquez les objets de la liste jobs pour produire plusieurs territoires, années ou scénarios."
            )
            self._message("Production en série", f"Manifeste créé : {output}", True)
        except Exception as exc:
            self._error("Production en série", exc)

    def run_batch_manifest(self):
        path = self.batch_manifest_path.text().strip()
        if not path:
            self._message("Production en série", "Choisissez un manifeste JSON.")
            return
        progress = None
        try:
            manifest = load_manifest(path)
            feedback = QgsFeedback()
            progress = QProgressDialog(
                "Production cartographique en cours",
                "Annuler",
                0,
                100,
                self,
            )
            progress.setWindowTitle("Cartomize")
            progress.setAutoClose(False)
            progress.setMinimumDuration(0)
            feedback.progressChanged.connect(lambda value: progress.setValue(int(value)))
            progress.canceled.connect(feedback.cancel)
            progress.show()
            report = self.batch_runner.run(manifest, feedback)
            report_path = Path(manifest.output_directory) / "cartomize-batch-report.json"
            save_batch_report(report, report_path)
            self.batch_status.setHtml(
                "<h4>Production terminée</h4>"
                f"<p>Cartes demandées : {report.total}<br>"
                f"Réussies : {report.succeeded}<br>"
                f"Échecs : {report.failed}<br>"
                f"Annulée : {'oui' if report.canceled else 'non'}<br>"
                f"Rapport : {escape(str(report_path))}</p>"
            )
            self.refresh_layouts()
            self._message(
                "Production en série",
                f"{report.succeeded} cartes produites sur {report.total}.",
                report.failed == 0 and not report.canceled,
            )
        except Exception as exc:
            self._error("Production en série", exc)
        finally:
            if progress is not None:
                progress.setValue(100)
                progress.close()
                progress.deleteLater()

    def create_mapops_baseline(self):
        try:
            self.mapops_monitor.accept_current()
            snapshot = self.mapops_monitor.baseline
            project_write_entry(
                self.project,
                "mapops_baseline",
                json.dumps(snapshot.to_dict(), ensure_ascii=False, separators=(",", ":")),
            )
            self.project.setDirty(True)
            self.mapops_report.setPlainText(
                f"État de référence créé. Empreinte : {snapshot.fingerprint[:16]}…"
            )
            self._message("MapOps", "L’état de référence du projet a été enregistré.", True)
        except Exception as exc:
            self._error("MapOps", exc)

    def check_mapops_changes(self):
        try:
            report = self.mapops_monitor.check_now()
            self.mapops_report.setPlainText(report.to_text())
            self._message(
                "MapOps",
                f"{len(report.changes)} changement(s) détecté(s). Statut : {report.status}.",
                not report.changes,
            )
        except Exception as exc:
            self._error("MapOps", exc)

    def accept_mapops_state(self):
        self.mapops_monitor.accept_current()
        self.mapops_report.setPlainText("L’état actuel est devenu la nouvelle référence MapOps.")
        self._message("MapOps", "Nouvel état de référence accepté.", True)

    def regenerate_after_mapops(self):
        if self.last_automation_recipe is None:
            self._message(
                "MapOps",
                "Aucune recette récente n’est disponible. Créez une carte avec Autopilot ou chargez une recette.",
            )
            return
        try:
            result = self.autopilot.replay_recipe(self.last_automation_recipe)
            self.last_automation_recipe = result.recipe
            self.current_automatic_score = result.final_score
            self.refresh_layouts()
            index = self.layout_combo.findData(result.layout_name)
            if index >= 0:
                self.layout_combo.setCurrentIndex(index)
            self.preview.open(result.layout, self.settings.preview_width_px, zoom_mode="width")
            self.mapops_monitor.accept_current()
            self.mapops_report.setPlainText(
                f"Carte régénérée. Score automatique : {result.final_score}/100. Validation cartographe requise."
            )
            self._message("MapOps", "La dernière recette a été régénérée avec les données actuelles.", True)
        except Exception as exc:
            self._error("MapOps", exc)

    def _on_mapops_changes(self, report):
        self.mapops_report.setPlainText(report.to_text())
        if report.changes:
            impacted = len(report.impacted_layouts)
            suffix = f" {impacted} mise(s) en page directement concernée(s)." if impacted else ""
            self.iface.messageBar().pushWarning(
                "Cartomize MapOps",
                f"{len(report.changes)} changement(s) peuvent affecter les cartes existantes.{suffix}",
            )
            if (
                hasattr(self, "mapops_auto_regenerate")
                and self.mapops_auto_regenerate.isChecked()
                and self.last_automation_recipe is not None
            ):
                QTimer.singleShot(1800, self._auto_regenerate_after_mapops)

    def _auto_regenerate_after_mapops(self):
        if self.last_automation_recipe is None:
            return
        try:
            report = self.mapops_monitor.check_now()
            if not report.changes:
                return
            result = self.autopilot.replay_recipe(self.last_automation_recipe)
            self.last_automation_recipe = result.recipe
            self.current_automatic_score = result.final_score
            self.refresh_layouts()
            self.mapops_monitor.accept_current()
            self.mapops_report.setPlainText(
                report.to_text()
                + "\n\nRégénération automatique terminée. La validation cartographique humaine doit être renouvelée."
            )
            self.iface.messageBar().pushSuccess(
                "Cartomize MapOps",
                f"Carte régénérée automatiquement. Score de synthèse : {result.final_score}/100.",
            )
        except Exception as exc:
            self.iface.messageBar().pushWarning(
                "Cartomize MapOps",
                f"La régénération automatique n’a pas abouti : {exc}",
            )

    def approve_selected_layout(self):
        layout = self.selected_layout()
        if layout is None:
            self._message("Validation cartographique", "Sélectionnez une mise en page.")
            return
        try:
            score = int(layout.customProperty("cartomize/automatic_score", self.current_automatic_score or 0))
        except Exception:
            score = self.current_automatic_score or 0
        report = self.auditor.run(self.project_service.ordered_layers())
        self.current_report = report
        blockers = [
            finding.message if not finding.layer_name else f"{finding.layer_name} : {finding.message}"
            for finding in report.findings
            if finding.severity == "critical"
        ]
        try:
            certificate = self.validator.approve(
                layout,
                automatic_score=score,
                reviewer=self.validation_reviewer.text(),
                organization=self.validation_organization.text(),
                checks={key: checkbox.isChecked() for key, checkbox in self.validation_checks.items()},
                notes=self.validation_notes.toPlainText(),
                blockers=blockers,
            )
            self.validation_status.setText(
                f"Statut : {certificate.human_status}. Réviseur : {certificate.reviewer}. "
                f"Empreinte : {certificate.fingerprint[:16]}…"
            )
            objective = str(layout.customProperty("cartomize/autopilot_objective", "auto") or "auto")
            template_id = str(layout.customProperty("cartomize/template_id", "") or "")
            style_profile = "balanced"
            page_format = ""
            if self.last_automation_recipe is not None:
                style_profile = str(self.last_automation_recipe.variant.get("style_profile") or "balanced")
                page_format = str(self.last_automation_recipe.variant.get("page_format") or "")
            if template_id:
                self.autopilot.geo.remember_accepted_layout(
                    objective=objective,
                    template_id=template_id,
                    style_profile=style_profile,
                    page_format=page_format,
                )
            self._message("Validation cartographique", "La mise en page a été approuvée et tracée.", True)
        except Exception as exc:
            self._error("Validation cartographique", exc)

    def export_validation_certificate(self):
        layout = self.selected_layout()
        if layout is None:
            self._message("Validation cartographique", "Sélectionnez une mise en page.")
            return
        certificate = self.validator.load(layout)
        if certificate is None:
            self._message("Validation cartographique", "Aucun certificat n’est associé à cette mise en page.")
            return
        default = Path.home() / f"validation-{re.sub(r'[^A-Za-z0-9_-]+', '-', layout.name())}.json"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exporter le certificat de validation",
            str(default),
            "Certificat JSON (*.json)",
        )
        if not path:
            return
        try:
            output = self.validator.save(certificate, path)
            self._message("Validation cartographique", f"Certificat enregistré : {output}", True)
        except Exception as exc:
            self._error("Validation cartographique", exc)

    def refresh_project_summary(self):
        summary = self.project_service.summary()
        self.project_summary.setHtml(
            "<table cellspacing='4' cellpadding='2'>"
            f"<tr><td><b>Couches</b></td><td>{summary.layer_count}</td></tr>"
            f"<tr><td><b>Couches visibles</b></td><td>{summary.visible_count}</td></tr>"
            f"<tr><td><b>Vecteurs</b></td><td>{summary.vector_count}</td></tr>"
            f"<tr><td><b>Rasters</b></td><td>{summary.raster_count}</td></tr>"
            f"<tr><td><b>CRS</b></td><td>{escape(summary.project_crs)}</td></tr>"
            f"<tr><td><b>Emprise</b></td><td>{escape(summary.extent_text)}</td></tr>"
            f"<tr><td><b>Couches invalides</b></td><td>{summary.invalid_count}</td></tr>"
            "</table>"
        )
        if hasattr(self, "footer_status"):
            self.footer_status.setText(
                f"{summary.layer_count} couche(s), {summary.visible_count} visible(s), "
                f"{summary.invalid_count} invalide(s)"
            )

    def refresh_layers(self):
        previous = self.layer_combo.currentData()
        active = self.iface.activeLayer()
        self.layer_combo.blockSignals(True)
        self.layer_combo.clear()

        for layer in self.project_service.ordered_layers():
            crs = layer.crs().authid() or "CRS non défini"
            self.layer_combo.addItem(f"{layer.name()} ({crs})", layer.id())

        wanted = active.id() if active else previous
        index = self.layer_combo.findData(wanted)
        fallback = 0 if self.layer_combo.count() else -1
        self.layer_combo.setCurrentIndex(index if index >= 0 else fallback)
        self.layer_combo.blockSignals(False)
        self._update_recommendation()
        self.refresh_project_summary()

    def refresh_categories(self):
        current = self.category_combo.currentData()
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItem("Toutes les catégories", "")

        for category in self.catalog.categories():
            label = _CATEGORY_LABELS.get(category, category.replace("_", " ").capitalize())
            self.category_combo.addItem(label, category)

        index = self.category_combo.findData(current)
        self.category_combo.setCurrentIndex(index if index >= 0 else 0)
        self.category_combo.blockSignals(False)

    def refresh_templates(self):
        current_item = self.template_list.currentItem()
        selected = current_item.data(user_role()) if current_item else ""
        self.template_list.clear()
        category = self.category_combo.currentData() or ""

        for spec in self.catalog.search(self.template_search.text(), category):
            item = QListWidgetItem(f"{spec.name} ({spec.page_format})")
            item.setData(user_role(), spec.template_id)
            self.template_list.addItem(item)
            if spec.template_id == selected:
                self.template_list.setCurrentItem(item)

        if self.template_list.currentRow() < 0 and self.template_list.count():
            self.template_list.setCurrentRow(0)

    def refresh_layouts(self):
        selected = self.layout_combo.currentData()
        self.layout_combo.blockSignals(True)
        self.layout_combo.clear()
        for layout in self.project.layoutManager().printLayouts():
            self.layout_combo.addItem(layout.name(), layout.name())
        index = self.layout_combo.findData(selected)
        fallback = self.layout_combo.count() - 1
        self.layout_combo.setCurrentIndex(index if index >= 0 else fallback)
        self.layout_combo.blockSignals(False)

    def selected_layer(self):
        layer_id = self.layer_combo.currentData()
        return self.project.mapLayer(layer_id) if layer_id else None

    def selected_template(self):
        item = self.template_list.currentItem()
        return self.catalog.get(item.data(user_role())) if item else None

    def selected_layout(self):
        name = self.layout_combo.currentData()
        return self.project.layoutManager().layoutByName(name) if name else None

    def _update_recommendation(self):
        layer = self.selected_layer()
        if not isinstance(layer, (QgsVectorLayer, QgsRasterLayer)):
            self.recommendation.setPlainText("Sélectionnez une couche vectorielle ou raster valide.")
            self.apply_style_button.setEnabled(False)
            self.undo_style_button.setEnabled(False)
            self.raster_intelligence_button.setEnabled(False)
            return
        self.raster_intelligence_button.setEnabled(isinstance(layer, QgsRasterLayer))
        try:
            if isinstance(layer, QgsRasterLayer):
                self.current_vector_profile = None
                objective = self.automation_objective.currentData() or "auto"
                recommendation = self.raster_symbology.recommend(layer, objective)
                rationale = "".join(
                    f"<p style='margin:4px 0'>{escape(line)}</p>"
                    for line in recommendation.rationale
                )
                self.recommendation.setHtml(
                    f"<h4>{escape(recommendation.summary())}</h4>"
                    f"{rationale}"
                    f"<p><b>Indice de confiance</b> : {recommendation.confidence:.0%}</p>"
                )
            else:
                profile = self.autopilot.geo.vector.analyze(layer)
                self.current_vector_profile = profile
                recommendation = self.symbology.recommend_from_profile(layer, profile)
                rationale = "".join(
                    f"<p style='margin:4px 0'>{escape(line)}</p>"
                    for line in recommendation.rationale
                )
                warnings = "".join(f"<li>{escape(item)}</li>" for item in profile.warnings)
                warning_block = f"<ul>{warnings}</ul>" if warnings else ""
                self.recommendation.setHtml(
                    f"<h4>{escape(recommendation.summary())}</h4>"
                    "<table cellspacing='4'>"
                    f"<tr><td><b>Rôle probable</b></td><td>{escape(profile.role)}</td></tr>"
                    f"<tr><td><b>Confiance du rôle</b></td><td>{profile.role_confidence:.0%}</td></tr>"
                    f"<tr><td><b>Champ thématique</b></td><td>{escape(profile.thematic_field or 'Aucun')}</td></tr>"
                    f"<tr><td><b>Champ d’étiquette</b></td><td>{escape(profile.label_field or 'Aucun')}</td></tr>"
                    f"<tr><td><b>Entités</b></td><td>{profile.feature_count:,}</td></tr>"
                    "</table>"
                    f"{rationale}"
                    f"<p><b>Indice de confiance</b> : {recommendation.confidence:.0%}</p>"
                    f"{warning_block}"
                )
            self.apply_style_button.setEnabled(True)
            self.undo_style_button.setEnabled(True)
        except Exception as exc:
            self.recommendation.setPlainText(str(exc))
            self.apply_style_button.setEnabled(False)
            self.undo_style_button.setEnabled(False)

    def _zoom_selected_layer(self):
        layer = self.selected_layer()
        if layer:
            self.iface.setActiveLayer(layer)
            self.project_service.zoom_to_layer(layer)

    def _open_layer_properties(self):
        layer = self.selected_layer()
        if layer:
            self.iface.showLayerProperties(layer)

    def _apply_recommendation(self):
        layer = self.selected_layer()
        try:
            if isinstance(layer, QgsRasterLayer):
                result = self.raster_symbology.apply(
                    layer, objective=self.automation_objective.currentData() or "auto"
                )
            else:
                profile = self.current_vector_profile
                if profile is None and isinstance(layer, QgsVectorLayer):
                    profile = self.autopilot.geo.vector.analyze(layer)
                recommendation = self.symbology.recommend_from_profile(layer, profile)
                result = self.symbology.apply(layer, recommendation)
            self._message("Symbologie", result.summary(), True)
            self._update_recommendation()
        except Exception as exc:
            self._error("Symbologie", exc)

    def _undo_recommendation(self):
        layer = self.selected_layer()
        restored = self.autopilot.styling.undo_layer(layer) if layer is not None else False
        if restored:
            self._message("Symbologie", "Le style précédent a été restauré.", True)
            self._update_recommendation()
        else:
            self._message("Symbologie", "Aucun style précédent n'est disponible.")

    def _open_raster_intelligence(self):
        layer = self.selected_layer()
        if not isinstance(layer, QgsRasterLayer) or not layer.isValid():
            self._message("Raster Intelligence", "Sélectionnez une couche raster valide.")
            return
        dialog = RasterIntelligenceDialog(
            layer, self.raster_symbology.intelligence, self
        )
        dialog_exec(dialog)
        self._update_recommendation()
        self.refresh_layouts()

    def _show_template_details(self, current, _previous=None):
        if not current:
            self.template_details.clear()
            return

        spec = self.catalog.get(current.data(user_role()))
        notes = "".join(f"<li>{escape(note)}</li>" for note in spec.notes)
        self.template_details.setHtml(
            f"<h4>{escape(spec.name)}</h4>"
            f"<p>{escape(spec.description)}</p>"
            "<table cellspacing='3'>"
            f"<tr><td><b>Format</b></td><td>{escape(spec.page_format)}</td></tr>"
            f"<tr><td><b>Cadres cartographiques</b></td><td>{spec.map_count}</td></tr>"
            "</table>"
            f"<ul>{notes}</ul>"
        )
        if not self.layout_title.text().strip():
            self.layout_title.setText(spec.name)

    def create_layout(self):
        spec = self.selected_template()
        if spec is None:
            self._message("Maquette", "Sélectionnez une maquette Cartomize.")
            return None

        try:
            options = LayoutBuildOptions(
                title=self.layout_title.text().strip(),
                subtitle=self.layout_subtitle.text().strip(),
                author=self.settings.author,
                organization=self.settings.organization,
                sources=self.layout_sources.text().strip(),
                visible_layers_only=self.visible_only.isChecked(),
                extent_margin_percent=self.margin.value(),
                add_grid=self.add_grid.isChecked(),
                open_designer=False,
            )
            result = self.builder.build(spec, options)
            self.refresh_layouts()
            index = self.layout_combo.findData(result.layout_name)
            self.layout_combo.setCurrentIndex(index)

            detail = (
                f"La mise en page « {result.layout_name} » contient "
                f"{result.item_count} objets QGIS."
            )
            if result.warnings:
                detail += " Avertissements : " + ". ".join(result.warnings)
            self._message("Mise en page créée", detail, True)

            if self.settings.open_designer_after_creation:
                self.preview.open(
                    result.layout,
                    self.settings.preview_width_px,
                    zoom_mode="width",
                )
            return result.layout
        except Exception as exc:
            self._error("Mise en page", exc)
            return None

    def open_selected_layout(self):
        layout = self.selected_layout() or self.create_layout()
        if layout is None:
            return
        try:
            result = self.preview.open(
                layout,
                self.settings.preview_width_px,
                zoom_mode="width",
            )
            self._message(
                "Aperçu haute définition",
                f"Aperçu 4K préparé à {result.target_width_px} px de largeur ({result.dpi} DPI calculés), avec {result.map_items} cadre(s) cartographique(s).",
                True,
            )
        except Exception as exc:
            self._error("Aperçu haute définition", exc)

    def refresh_hd_preview(self):
        layout = self.selected_layout()
        if layout is None:
            self._message("Aperçu haute définition", "Sélectionnez d’abord une mise en page Cartomize.")
            return
        try:
            result = self.preview.open(
                layout,
                self.settings.preview_width_px,
                zoom_mode="width",
            )
            self._message(
                "Aperçu haute définition",
                f"{result.refreshed_items} élément(s) actualisé(s) en aperçu 4K à {result.target_width_px} px.",
                True,
            )
        except Exception as exc:
            self._error("Aperçu haute définition", exc)

    def optimize_selected_layout(self):
        layout = self.selected_layout()
        if layout is None:
            self._message("Mise en page", "Sélectionnez d'abord une mise en page Cartomize.")
            return
        try:
            changes = self.builder.optimize_existing_layout(layout)
            detail = "Lisibilité améliorée."
            if changes:
                detail += " Éléments ajustés : " + ", ".join(changes) + "."
            self._message("Mise en page", detail, True)
            self.preview.open(layout, self.settings.preview_width_px, zoom_mode="width")
        except Exception as exc:
            self._error("Lisibilité de la mise en page", exc)

    def _export(self, kind: str):
        layout = self.selected_layout() or self.create_layout()
        if layout is None:
            return

        filters = {
            "pdf": ("PDF (*.pdf)", ".pdf"),
            "svg": ("SVG (*.svg)", ".svg"),
            "png": ("PNG (*.png)", ".png"),
            "qpt": ("Modèle QGIS (*.qpt)", ".qpt"),
        }
        file_filter, suffix = filters[kind]
        default = Path.home() / (_safe_filename(layout.name()) + suffix)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exporter la mise en page",
            str(default),
            file_filter,
        )
        if not path:
            return

        try:
            if kind == "qpt":
                result = self.exporter.save_as_qpt(layout, path)
            else:
                result = self.exporter.export(
                    layout,
                    path,
                    kind,
                    dpi=self.settings.default_dpi,
                    force_vector=True,
                    geo_pdf=(kind == "pdf"),
                )
            self._message("Export", f"Fichier créé : {result.path}", True)
        except Exception as exc:
            self._error("Export", exc)

    def run_audit(self):
        try:
            report = self.auditor.run(self.project_service.ordered_layers())
            self.current_report = report
            self.audit_score.setText(
                f"Score : {report.score}/100. Statut : {report.status}."
            )
            self.audit_tree.clear()

            for finding in report.findings:
                detail = f"Observation : {finding.message}"
                if finding.remediation:
                    detail += f" Action recommandée : {finding.remediation}"
                QTreeWidgetItem(
                    self.audit_tree,
                    [
                        severity_label(finding.severity),
                        finding.code,
                        finding.layer_name,
                        detail,
                    ],
                )

            self.audit_tree.resizeColumnToContents(0)
            self.audit_tree.resizeColumnToContents(1)
        except Exception as exc:
            self._error("Contrôle de la qualité", exc)

    def run_label_audit(self):
        try:
            audit = self.autopilot.geo.label_audit()
            if audit.total_positions <= 0:
                self.label_audit_status.setText(audit.status)
                self._message("Étiquetage", audit.status)
                return
            ratio = audit.unplaced / max(1, audit.total_positions)
            self.label_audit_status.setText(
                f"{audit.placed} étiquette(s) placée(s), {audit.unplaced} non placée(s), "
                f"soit {ratio:.0%} non placées. Statut : {audit.status}."
            )
            self._message(
                "Étiquetage",
                f"Analyse terminée : {audit.total_positions} positions, {audit.unplaced} non placées.",
                audit.status == "Bon",
            )
        except Exception as exc:
            self._error("Étiquetage", exc)

    def copy_audit(self):
        if self.current_report is None:
            self.run_audit()
        if self.current_report is not None:
            QApplication.clipboard().setText(self.current_report.to_text())
            self._message("Contrôle de la qualité", "Le rapport a été copié.", True)

    def open_community(self):
        try:
            self.community.open_in_browser(self.settings.community_url)
        except Exception as exc:
            self._error("Communauté", exc)

    def open_settings(self):
        dialog = SettingsDialog(self.settings, self)
        if dialog_exec(dialog):
            settings = dialog.result_settings()
            settings.save()
            self.settings = CartomizeSettings.load()
            configured = self.settings.community_url or "Non configuré"
            self.community_label.setText(f"Adresse du service : {configured}")

    def run_diagnostics(self):
        try:
            report = self.diagnostics.run()
            self.diagnostic_text.setPlainText(report.as_text())
            if hasattr(self, "footer_status"):
                self.footer_status.setText("Système vérifié")
        except Exception as exc:
            message = f"Le diagnostic est indisponible. {str(exc).strip()}"
            self.diagnostic_text.setPlainText(message)
            self._error("État du système", exc)

    def _message(self, title: str, text: str, success: bool = False):
        from ..core.compat import info_level, success_level

        level = success_level() if success else info_level()
        self.iface.messageBar().pushMessage(
            title,
            text,
            level=level,
            duration=8,
        )
        if hasattr(self, "footer_status"):
            self.footer_status.setText(text)

    def _error(self, title: str, exc: Exception):
        from ..core.compat import critical_level

        if isinstance(exc, CartomizeError):
            message = str(exc)
        else:
            message = str(exc).strip() or "Une erreur inattendue est survenue."
        self.iface.messageBar().pushMessage(
            title,
            message,
            level=critical_level(),
            duration=12,
        )
        if hasattr(self, "footer_status"):
            self.footer_status.setText(f"Erreur : {message}")


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-.")
    return cleaned[:100] or "cartomize-layout"
