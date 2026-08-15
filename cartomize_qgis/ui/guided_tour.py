"""Coach marks natifs Qt pour la découverte progressive de Cartomize."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from qgis.PyQt.QtCore import QEvent, QObject, QPoint, QRect, QRectF, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QPainter, QPainterPath, QPen
from qgis.PyQt.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qgis.PyQt.QtCore import QSettings

from ..core.constants import SETTINGS_PREFIX
from ..core.onboarding_state import (
    ONBOARDING_VERSION,
    normalise_completion_status,
    should_offer_tour,
)


@dataclass(frozen=True)
class GuidedTourStep:
    title: str
    description: str
    target: Callable[[], QWidget | None]
    tab_index: int | None = None


class GuidedTourOverlay(QWidget):
    """Voile non modal avec découpe, repère et panneau de navigation."""

    previousRequested = pyqtSignal()
    nextRequested = pyqtSignal()
    skipRequested = pyqtSignal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._target: QWidget | None = None
        self._target_rect = QRect()
        self.setObjectName("CartomizeGuidedTourOverlay")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.card = QFrame(self)
        self.card.setObjectName("CartomizeGuidedTourCard")
        self.card.setAccessibleName("Visite guidée Cartomize")
        self.card.setStyleSheet(
            """
            QFrame#CartomizeGuidedTourCard {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 12px;
            }
            QLabel#CartomizeTourKicker {
                color: #0f6cbd;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 1px;
            }
            QLabel#CartomizeTourTitle {
                color: #0f172a;
                font-size: 17px;
                font-weight: 700;
            }
            QLabel#CartomizeTourBody {
                color: #334155;
                font-size: 12px;
            }
            QLabel#CartomizeTourProgress {
                color: #64748b;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton {
                min-height: 30px;
                padding: 4px 11px;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                background: #ffffff;
                color: #0f172a;
            }
            QPushButton:hover { background: #f8fafc; }
            QPushButton#CartomizeTourNext {
                border-color: #0f6cbd;
                background: #0f6cbd;
                color: #ffffff;
                font-weight: 700;
            }
            QPushButton#CartomizeTourSkip { border: 0; color: #475569; }
            """
        )

        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(18, 16, 18, 15)
        layout.setSpacing(8)

        header = QHBoxLayout()
        self.kicker = QLabel("PRISE EN MAIN")
        self.kicker.setObjectName("CartomizeTourKicker")
        self.progress = QLabel()
        self.progress.setObjectName("CartomizeTourProgress")
        self.progress.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.kicker)
        header.addStretch(1)
        header.addWidget(self.progress)
        layout.addLayout(header)

        self.title = QLabel()
        self.title.setObjectName("CartomizeTourTitle")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)

        self.description = QLabel()
        self.description.setObjectName("CartomizeTourBody")
        self.description.setWordWrap(True)
        layout.addWidget(self.description)

        actions = QHBoxLayout()
        self.skip_button = QPushButton("Passer")
        self.skip_button.setObjectName("CartomizeTourSkip")
        self.previous_button = QPushButton("Précédent")
        self.next_button = QPushButton("Suivant")
        self.next_button.setObjectName("CartomizeTourNext")
        actions.addWidget(self.skip_button)
        actions.addStretch(1)
        actions.addWidget(self.previous_button)
        actions.addWidget(self.next_button)
        layout.addLayout(actions)

        self.skip_button.clicked.connect(self.skipRequested)
        self.previous_button.clicked.connect(self.previousRequested)
        self.next_button.clicked.connect(self.nextRequested)
        parent.installEventFilter(self)

    def dispose(self) -> None:
        try:
            self.parentWidget().removeEventFilter(self)
        except (AttributeError, RuntimeError):
            pass

    def set_step(
        self,
        step: GuidedTourStep,
        index: int,
        total: int,
        target: QWidget,
    ) -> None:
        self._target = target
        self.title.setText(step.title)
        self.description.setText(step.description)
        self.progress.setText(f"{index + 1}/{total}")
        self.previous_button.setVisible(index > 0)
        self.next_button.setText("Terminer" if index + 1 == total else "Suivant")
        self._sync_geometry()
        self.show()
        self.raise_()
        self.next_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def eventFilter(self, watched, event):  # noqa: N802
        if watched is self.parentWidget() and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.Move,
            QEvent.Type.Show,
            QEvent.Type.LayoutRequest,
        }:
            self._sync_geometry()
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.skipRequested.emit()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Left:
            self.previousRequested.emit()
            event.accept()
            return
        if event.key() in {Qt.Key.Key_Right, Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            self.nextRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        shade = QPainterPath()
        shade.addRect(QRectF(self.rect()))
        if not self._target_rect.isEmpty():
            shade.addRoundedRect(QRectF(self._target_rect), 8.0, 8.0)
            shade.setFillRule(Qt.FillRule.OddEvenFill)
        painter.fillPath(shade, QColor(15, 23, 42, 168))

        if not self._target_rect.isEmpty():
            painter.setPen(QPen(QColor("#38bdf8"), 3.0))
            painter.drawRoundedRect(self._target_rect, 8, 8)
            target_center = self._target_rect.center()
            card_rect = self.card.geometry()
            anchor = QPoint(
                min(max(target_center.x(), card_rect.left()), card_rect.right()),
                min(max(target_center.y(), card_rect.top()), card_rect.bottom()),
            )
            painter.setPen(QPen(QColor("#38bdf8"), 2.0))
            painter.drawLine(anchor, target_center)
            painter.setBrush(QColor("#38bdf8"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(target_center, 4, 4)

    def _sync_geometry(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.setGeometry(parent.rect())
        self._target_rect = self._mapped_target_rect()
        self._place_card()
        self.update()

    def _mapped_target_rect(self) -> QRect:
        target = self._target
        if target is None or not target.isVisible():
            return QRect()
        top_left = target.mapTo(self, QPoint(0, 0))
        rect = QRect(top_left, target.size()).adjusted(-7, -7, 7, 7)
        return rect.intersected(self.rect().adjusted(6, 6, -6, -6))

    def _place_card(self) -> None:
        available = self.rect().adjusted(16, 16, -16, -16)
        width = max(280, min(370, available.width()))
        self.card.setFixedWidth(width)
        self.card.adjustSize()
        card_size = self.card.sizeHint()
        height = min(card_size.height(), max(210, available.height()))
        gap = 18
        target = self._target_rect

        candidates = (
            QPoint(target.left(), target.bottom() + gap),
            QPoint(target.left(), target.top() - height - gap),
            QPoint(target.right() + gap, target.center().y() - height // 2),
            QPoint(target.left() - width - gap, target.center().y() - height // 2),
        )
        chosen = None
        for point in candidates:
            candidate = QRect(point, card_size)
            if available.contains(candidate):
                chosen = point
                break
        if chosen is None:
            chosen = QPoint(
                max(available.left(), min(target.left(), available.right() - width)),
                max(available.top(), min(target.bottom() + gap, available.bottom() - height)),
            )
        self.card.setGeometry(chosen.x(), chosen.y(), width, height)


class GuidedTourController(QObject):
    """Orchestre les étapes et persiste la décision de l'utilisateur."""

    finished = pyqtSignal(str)

    def __init__(self, dock, host: QWidget, steps: list[GuidedTourStep]):
        super().__init__(dock)
        self.dock = dock
        self.host = host
        self.steps = list(steps)
        self.index = -1
        self.overlay: GuidedTourOverlay | None = None

    @property
    def running(self) -> bool:
        return self.overlay is not None and self.overlay.isVisible()

    def should_start_automatically(self) -> bool:
        settings = QSettings()
        return should_offer_tour(
            settings.value(f"{SETTINGS_PREFIX}/onboarding/version", ""),
            settings.value(f"{SETTINGS_PREFIX}/onboarding/status", ""),
        )

    def start(self, *, force: bool = False) -> bool:
        if not self.steps or (not force and not self.should_start_automatically()):
            return False
        if self.overlay is None:
            self.overlay = GuidedTourOverlay(self.host)
            self.overlay.previousRequested.connect(self.previous)
            self.overlay.nextRequested.connect(self.next)
            self.overlay.skipRequested.connect(self.skip)
        self.index = 0
        self._show_current()
        return True

    def previous(self) -> None:
        if self.index > 0:
            self.index -= 1
            self._show_current()

    def next(self) -> None:
        if self.index + 1 >= len(self.steps):
            self._finish("completed")
            return
        self.index += 1
        self._show_current()

    def skip(self) -> None:
        self._finish("skipped")

    def dispose(self) -> None:
        if self.overlay is not None:
            self.overlay.dispose()
            self.overlay.hide()
            self.overlay.deleteLater()
            self.overlay = None

    def _show_current(self) -> None:
        step = self.steps[self.index]
        if step.tab_index is not None:
            self.dock.tabs.setCurrentIndex(step.tab_index)
        target = step.target()
        if target is None:
            target = self.host
        self._ensure_visible(target)
        self.overlay.set_step(step, self.index, len(self.steps), target)

    @staticmethod
    def _ensure_visible(target: QWidget) -> None:
        parent = target.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                parent.ensureWidgetVisible(target, 18, 18)
                break
            parent = parent.parentWidget()

    def _finish(self, status: str) -> None:
        value = normalise_completion_status(status)
        settings = QSettings()
        settings.setValue(f"{SETTINGS_PREFIX}/onboarding/version", ONBOARDING_VERSION)
        settings.setValue(f"{SETTINGS_PREFIX}/onboarding/status", value)
        if self.overlay is not None:
            self.overlay.hide()
        self.index = -1
        self.finished.emit(value)
