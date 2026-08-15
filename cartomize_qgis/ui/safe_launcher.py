"""Lanceur minimal de Cartomize, sans import des moteurs cartographiques."""
from __future__ import annotations

from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QFrame,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class CartomizeSafeLauncher(QDockWidget):
    """Point d'entrée toujours utilisable, même si l'interface avancée échoue."""

    def __init__(
        self,
        iface,
        *,
        qgis_version: str,
        last_launch_failed: bool,
        open_full_interface,
        enable_processing_tools,
        copy_diagnostic,
        parent=None,
    ):
        super().__init__("Cartomize", parent or iface.mainWindow())
        self.setObjectName("CartomizeSafeLauncher")
        self.setMinimumWidth(390)
        self._open_full_interface = open_full_interface
        self._enable_processing_tools = enable_processing_tools
        self._copy_diagnostic = copy_diagnostic
        self._recovery_mode = bool(last_launch_failed)

        content = QWidget(self)
        content.setObjectName("CartomizeSafeContent")
        content.setStyleSheet(
            """
            QWidget#CartomizeSafeContent { background: palette(window); }
            QFrame[role="card"] {
                background: palette(base);
                border: 1px solid rgba(100, 116, 139, 75);
                border-radius: 8px;
            }
            QLabel[role="title"] { font-size: 20px; font-weight: 700; }
            QLabel[role="subtitle"] { color: palette(mid); }
            QLabel[role="warning"] {
                color: #8a4b08;
                background: #fff4df;
                border: 1px solid #e5b96f;
                border-radius: 6px;
                padding: 8px;
            }
            QPushButton {
                min-height: 32px;
                padding: 6px 10px;
                border-radius: 5px;
            }
            QPushButton[primary="true"] {
                color: white;
                background: #0f5cab;
                border: 1px solid #0f5cab;
                font-weight: 600;
            }
            """
        )
        self.setWidget(content)

        root = QVBoxLayout(content)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        title = QLabel("Cartomize")
        title.setProperty("role", "title")
        root.addWidget(title)

        subtitle = QLabel(f"Initialisation progressive · QGIS {qgis_version}")
        subtitle.setProperty("role", "subtitle")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        if last_launch_failed:
            warning = QLabel(
                "La dernière ouverture de l'interface avancée ne s'est pas terminée "
                "normalement. Cartomize a donc redémarré en mode sûr. Vous pouvez "
                "copier le diagnostic avant de réessayer."
            )
            warning.setProperty("role", "warning")
            warning.setWordWrap(True)
            root.addWidget(warning)

        card = QFrame()
        card.setProperty("role", "card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(9)

        explanation = QLabel(
            "Cartomize prépare automatiquement la symbologie, l'analyse, les "
            "maquettes et les outils Traitements."
        )
        explanation.setWordWrap(True)
        card_layout.addWidget(explanation)

        self.open_button = QPushButton("Réessayer l'ouverture de Cartomize")
        self.open_button.setProperty("primary", True)
        self.open_button.clicked.connect(self._request_full_interface)
        card_layout.addWidget(self.open_button)

        self.processing_button = QPushButton("Réparer les outils Traitements")
        self.processing_button.clicked.connect(self._enable_processing_tools)
        card_layout.addWidget(self.processing_button)

        self.diagnostic_button = QPushButton("Copier le diagnostic de compatibilité")
        self.diagnostic_button.clicked.connect(self._copy_diagnostic)
        card_layout.addWidget(self.diagnostic_button)

        self.open_button.setVisible(self._recovery_mode)
        self.processing_button.setVisible(self._recovery_mode)
        self.diagnostic_button.setVisible(self._recovery_mode)

        root.addWidget(card)

        self.status = QTextEdit()
        self.status.setReadOnly(True)
        self.status.setMaximumHeight(110)
        self.status.setPlainText("Initialisation automatique en attente…")
        root.addWidget(self.status)
        root.addStretch(1)

    def _request_full_interface(self):
        self.set_busy("Chargement progressif de l'interface avancée…")
        self._open_full_interface()

    def set_busy(self, message: str):
        self.open_button.setEnabled(False)
        self.status.setPlainText(message)

    def set_ready(self, message: str):
        self.open_button.setEnabled(True)
        self.status.setPlainText(message)

    def set_error(self, message: str):
        self._recovery_mode = True
        self.open_button.setVisible(True)
        self.processing_button.setVisible(True)
        self.diagnostic_button.setVisible(True)
        self.open_button.setEnabled(True)
        self.status.setPlainText(message)
