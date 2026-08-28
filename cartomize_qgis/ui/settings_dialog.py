"""Préférences de Cartomize."""
from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.constants import DEFAULT_COMMUNITY_URL
from ..core.settings import CartomizeSettings


_SETTINGS_QSS = r"""
QDialog {
    background: palette(window);
}
QLabel[role="dialogTitle"] {
    font-size: 18px;
    font-weight: 700;
}
QLabel[role="muted"] {
    color: #64748b;
}
QFrame[role="card"] {
    background: palette(base);
    border: 1px solid rgba(100, 116, 139, 65);
    border-radius: 8px;
}
QLineEdit, QSpinBox, QDoubleSpinBox {
    min-height: 28px;
    padding: 4px 7px;
    border: 1px solid rgba(100, 116, 139, 80);
    border-radius: 5px;
    background: palette(base);
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #0f6cbd;
}
QTabWidget::pane {
    border: 0;
}
QTabBar::tab {
    min-width: 100px;
    min-height: 28px;
    padding: 5px 12px;
}
QTabBar::tab:selected {
    font-weight: 700;
}
"""


class SettingsDialog(QDialog):
    def __init__(self, settings: CartomizeSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Préférences Cartomize")
        self.setMinimumWidth(540)
        self.resize(580, 500)
        self.setStyleSheet(_SETTINGS_QSS)
        self._restart_guided_tour = False

        title = QLabel("Préférences Cartomize")
        title.setProperty("role", "dialogTitle")
        description = QLabel(
            "Configurez votre identité, la qualité du rendu et le comportement des mises en page."
        )
        description.setProperty("role", "muted")
        description.setWordWrap(True)

        self.author = QLineEdit(settings.author)
        self.organization = QLineEdit(settings.organization)
        self.dpi = QSpinBox()
        self.dpi.setRange(150, 1200)
        self.dpi.setSuffix(" DPI")
        self.dpi.setValue(settings.default_dpi)

        self.preview_width = QSpinBox()
        self.preview_width.setRange(1920, 7680)
        self.preview_width.setSingleStep(320)
        self.preview_width.setSuffix(" px")
        self.preview_width.setValue(settings.preview_width_px)
        self.preview_width.setToolTip(
            "Largeur interne utilisée pour l’aperçu dans le concepteur QGIS."
        )

        self.text_scale = QSpinBox()
        self.text_scale.setRange(100, 180)
        self.text_scale.setSuffix(" %")
        self.text_scale.setValue(settings.text_scale_percent)

        self.minimum_font_size = QDoubleSpinBox()
        self.minimum_font_size.setRange(8.0, 14.0)
        self.minimum_font_size.setDecimals(1)
        self.minimum_font_size.setSingleStep(0.5)
        self.minimum_font_size.setSuffix(" pt")
        self.minimum_font_size.setValue(settings.minimum_font_size_pt)

        self.open_designer = QCheckBox(
            "Ouvrir la mise en page dans QGIS après sa création"
        )
        self.open_designer.setChecked(settings.open_designer_after_creation)

        self.preserve_layers = QCheckBox(
            "Conserver la liste des couches dans chaque cadre"
        )
        self.preserve_layers.setChecked(settings.preserve_map_layer_set)

        self.filter_legend = QCheckBox("Adapter la légende au contenu du cadre")
        self.filter_legend.setChecked(settings.filter_legend_by_map)

        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.addTab(self._general_tab(), "Général")
        tabs.addTab(self._render_tab(), "Rendu")
        tabs.addTab(self._behavior_tab(), "Comportement")
        tabs.addTab(self._help_tab(), "Aide")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_validated)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(tabs, 1)
        layout.addWidget(buttons)

    def _card(self, title: str, description: str = ""):
        card = QFrame()
        card.setProperty("role", "card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 11, 12, 12)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setStyleSheet("font-weight: 700;")
        layout.addWidget(heading)
        if description:
            details = QLabel(description)
            details.setProperty("role", "muted")
            details.setWordWrap(True)
            layout.addWidget(details)
        return card, layout

    def _general_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(10)

        identity, identity_layout = self._card(
            "Identité cartographique",
            "Ces informations peuvent être reprises dans les cartouches et certificats de validation.",
        )
        form = QFormLayout()
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        form.addRow("Auteur", self.author)
        form.addRow("Organisation", self.organization)
        identity_layout.addLayout(form)
        layout.addWidget(identity)

        community, community_layout = self._card(
            "Portail Cartomize",
            "Le portail officiel est configuré automatiquement. Aucune donnée du projet n’est transmise.",
        )
        portal = QLabel(DEFAULT_COMMUNITY_URL)
        portal.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        community_layout.addWidget(portal)
        layout.addWidget(community)
        layout.addStretch(1)
        return tab

    def _render_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(10)

        quality, quality_layout = self._card(
            "Qualité du rendu",
            "Le profil 4K améliore l’aperçu dans QGIS. Les sorties PDF et SVG restent vectorielles.",
        )
        form = QFormLayout()
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        form.addRow("Résolution raster", self.dpi)
        form.addRow("Largeur de l’aperçu", self.preview_width)
        form.addRow("Échelle typographique", self.text_scale)
        form.addRow("Taille minimale", self.minimum_font_size)
        quality_layout.addLayout(form)
        layout.addWidget(quality)

        note = QLabel(
            "Une valeur d’aperçu très élevée peut ralentir les projets contenant de grands rasters ou de nombreuses couches."
        )
        note.setProperty("role", "muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return tab

    def _behavior_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(10)

        behavior, behavior_layout = self._card(
            "Comportement des mises en page",
            "Ces options s’appliquent aux nouvelles compositions créées par Cartomize.",
        )
        behavior_layout.addWidget(self.open_designer)
        behavior_layout.addWidget(self.preserve_layers)
        behavior_layout.addWidget(self.filter_legend)
        layout.addWidget(behavior)
        layout.addStretch(1)
        return tab

    def _help_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(10)

        onboarding, onboarding_layout = self._card(
            "Découvrir Cartomize",
            "La visite présente les principales étapes du flux de travail directement dans l’interface.",
        )
        self.restart_tour_button = QPushButton("Relancer la visite guidée")
        self.restart_tour_button.setMinimumHeight(32)
        self.restart_tour_button.clicked.connect(self._request_guided_tour)
        onboarding_layout.addWidget(self.restart_tour_button)
        layout.addWidget(onboarding)
        layout.addStretch(1)
        return tab

    def _request_guided_tour(self):
        self._restart_guided_tour = True
        self.accept()

    def wants_guided_tour(self) -> bool:
        return self._restart_guided_tour

    def _accept_validated(self):
        self.accept()

    def result_settings(self) -> CartomizeSettings:
        return CartomizeSettings(
            author=self.author.text().strip(),
            organization=self.organization.text().strip(),
            community_url=DEFAULT_COMMUNITY_URL,
            default_dpi=self.dpi.value(),
            preview_width_px=self.preview_width.value(),
            text_scale_percent=self.text_scale.value(),
            minimum_font_size_pt=self.minimum_font_size.value(),
            open_designer_after_creation=self.open_designer.isChecked(),
            preserve_map_layer_set=self.preserve_layers.isChecked(),
            filter_legend_by_map=self.filter_legend.isChecked(),
        )
