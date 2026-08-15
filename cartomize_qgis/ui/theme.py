"""Thème visuel professionnel du plugin Cartomize.

Palette alignée sur l'identité CARTOMIZE : blanc, bleu marine, bleu royal.
Aucune dépendance externe — uniquement des feuilles de style Qt (QSS).
"""
from __future__ import annotations

# Couleurs de marque
NAVY = "#132c56"
ROYAL = "#2456a6"
ROYAL_DARK = "#17388f"
ROYAL_LIGHT = "#5c8bd9"
BG = "#ffffff"
SURFACE = "#f5f7fb"
LINE = "#dde4ef"
TEXT = "#1f2937"
MUTED = "#64748b"
DANGER = "#b3453a"
SUCCESS = "#2c6e49"

DOCK_STYLESHEET = f"""
QDockWidget {{
    font-family: "Segoe UI", "Noto Sans", sans-serif;
}}
QWidget#cartomizeRoot {{
    background: {BG};
}}
QLabel {{
    color: {TEXT};
}}
QLabel#cartomizeBrandTitle {{
    color: {NAVY};
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 2px;
}}
QLabel#cartomizeBrandSubtitle {{
    color: {MUTED};
    font-size: 11px;
}}
QLabel#cartomizeScore {{
    color: {NAVY};
    font-size: 20px;
    font-weight: 700;
}}
QFrame#cartomizeHeader {{
    background: {BG};
    border-bottom: 2px solid {LINE};
}}
QTabWidget::pane {{
    border: 1px solid {LINE};
    border-radius: 6px;
    background: {BG};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {MUTED};
    padding: 7px 14px;
    margin-right: 2px;
    border: 1px solid transparent;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-weight: 600;
}}
QTabBar::tab:hover {{
    color: {ROYAL};
}}
QTabBar::tab:selected {{
    color: {ROYAL_DARK};
    background: {BG};
    border-color: {LINE};
    border-bottom-color: {BG};
}}
QGroupBox {{
    border: 1px solid {LINE};
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 6px;
    background: {BG};
    font-weight: 700;
    color: {NAVY};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    background: {BG};
}}
QLineEdit, QComboBox, QSpinBox {{
    border: 1px solid {LINE};
    border-radius: 4px;
    padding: 5px 8px;
    background: {BG};
    color: {TEXT};
    selection-background-color: {ROYAL};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border: 1px solid {ROYAL};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QPushButton {{
    background: {SURFACE};
    color: {NAVY};
    border: 1px solid {LINE};
    border-radius: 4px;
    padding: 6px 14px;
    font-weight: 600;
}}
QPushButton:hover {{
    border-color: {ROYAL};
    color: {ROYAL_DARK};
}}
QPushButton:pressed {{
    background: {LINE};
}}
QPushButton:disabled {{
    color: {MUTED};
    background: {SURFACE};
}}
QPushButton[cartomizeRole="primary"] {{
    background: {ROYAL};
    color: #ffffff;
    border: 1px solid {ROYAL_DARK};
}}
QPushButton[cartomizeRole="primary"]:hover {{
    background: {ROYAL_DARK};
    color: #ffffff;
}}
QListWidget, QTreeWidget, QTextBrowser {{
    border: 1px solid {LINE};
    border-radius: 6px;
    background: {BG};
    color: {TEXT};
    alternate-background-color: {SURFACE};
}}
QListWidget::item {{
    padding: 6px 8px;
    border-bottom: 1px solid {SURFACE};
}}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background: {ROYAL};
    color: #ffffff;
}}
QTreeWidget::item {{
    padding: 4px 6px;
}}
QHeaderView::section {{
    background: {SURFACE};
    color: {NAVY};
    border: none;
    border-bottom: 1px solid {LINE};
    padding: 6px 8px;
    font-weight: 700;
}}
QCheckBox {{
    color: {TEXT};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {LINE};
    border-radius: 3px;
    background: {BG};
}}
QCheckBox::indicator:checked {{
    background: {ROYAL};
    border-color: {ROYAL_DARK};
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {LINE};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {ROYAL_LIGHT};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""

DIALOG_STYLESHEET = DOCK_STYLESHEET

# Gabarit HTML commun pour les QTextBrowser (résumés, recommandations, détails)
HTML_STYLE = f"""
<style>
    body {{ color: {TEXT}; font-size: 13px; }}
    h2, h3, h4 {{ color: {NAVY}; margin: 0 0 6px 0; }}
    p {{ margin: 0 0 8px 0; }}
    ul {{ margin: 0 0 8px 18px; padding: 0; }}
    li {{ margin-bottom: 3px; }}
    b, strong {{ color: {NAVY}; }}
    .muted {{ color: {MUTED}; }}
    .tag {{ color: {ROYAL_DARK}; font-weight: 600; }}
    table {{ border-collapse: collapse; }}
    td {{ padding: 2px 10px 2px 0; }}
</style>
"""


def wrap_html(body: str) -> str:
    """Encapsule un fragment HTML avec la charte typographique Cartomize."""
    return HTML_STYLE + body


def mark_primary(button) -> None:
    """Marque un bouton comme action principale (bleu plein)."""
    button.setProperty("cartomizeRole", "primary")
    style = button.style()
    style.unpolish(button)
    style.polish(button)
