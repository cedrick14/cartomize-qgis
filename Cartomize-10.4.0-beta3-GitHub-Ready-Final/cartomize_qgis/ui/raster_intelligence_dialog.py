"""Interface du Raster Intelligence Engine de Cartomize."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QInputDialog,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsApplication, QgsRasterLayer, QgsTask

from ..core.errors import CartomizeError
from ..core.raster_intelligence import (
    RasterClassDefinition,
    RasterDiagnosis,
    RasterInspector,
    RasterIntelligenceEngine,
    raster_type_label,
)


class RasterIntelligenceDialog(QDialog):
    def __init__(self, layer: QgsRasterLayer, engine: RasterIntelligenceEngine, parent=None):
        super().__init__(parent)
        self.layer = layer
        self.engine = engine
        self.diagnosis: RasterDiagnosis | None = None
        self._automatic_classes: tuple[RasterClassDefinition, ...] = ()
        self._task = None
        self.setWindowTitle(f"Analyse raster · {layer.name()}")
        self.resize(980, 720)
        self.setMinimumSize(760, 560)
        self._build_ui()
        self.refresh(False)

    def _build_ui(self):
        root = QVBoxLayout(self)
        title = QLabel("Raster Intelligence Engine")
        title.setStyleSheet("font-size:18px;font-weight:700")
        root.addWidget(title)
        subtitle = QLabel(
            "Analyse les métadonnées, le NoData, les classes et les anomalies avant toute symbologie. "
            "Les réglages visuels ne modifient jamais les pixels du raster source."
        )
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self._build_diagnostic_tab()
        self._build_classes_tab()
        self._build_metadata_tab()

        footer = QHBoxLayout()
        self.status = QLabel("Prêt")
        self.status.setWordWrap(True)
        footer.addWidget(self.status, 1)
        close = QPushButton("Fermer")
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        root.addLayout(footer)

    def _build_diagnostic_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        actions = QHBoxLayout()
        self.quick_button = QPushButton("Analyser")
        self.deep_button = QPushButton("Analyse approfondie")
        self.export_button = QPushButton("Exporter le diagnostic")
        self.quick_button.clicked.connect(lambda: self.refresh(False))
        self.deep_button.clicked.connect(self.start_deep_analysis)
        self.export_button.clicked.connect(self.export_diagnostic)
        actions.addWidget(self.quick_button)
        actions.addWidget(self.deep_button)
        actions.addWidget(self.export_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.summary = QTextBrowser()
        self.summary.setMinimumHeight(180)
        layout.addWidget(self.summary)

        self.nodata_tree = QTreeWidget()
        self.nodata_tree.setHeaderLabels(["Valeur", "Confiance", "Diagnostic"])
        self.nodata_tree.setRootIsDecorated(False)
        layout.addWidget(QLabel("Valeurs NoData potentielles"))
        layout.addWidget(self.nodata_tree, 1)

        nodata_actions = QHBoxLayout()
        mark = QPushButton("Considérer comme NoData visuel")
        keep = QPushButton("Conserver comme classe")
        mark.clicked.connect(self.mark_selected_nodata)
        keep.clicked.connect(self.keep_selected_class)
        nodata_actions.addWidget(mark)
        nodata_actions.addWidget(keep)
        nodata_actions.addStretch(1)
        layout.addLayout(nodata_actions)
        self.tabs.addTab(tab, "Diagnostic")

    def _build_classes_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        info = QLabel(
            "Modifiez les noms, couleurs, visibilité et regroupements de légende. "
            "Ajouter, masquer ou fusionner ici agit uniquement sur la représentation."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        self.class_table = QTableWidget(0, 9)
        self.class_table.setHorizontalHeaderLabels(
            ["Visible", "Code", "Nom", "Couleur", "Pixels", "%", "Bordure", "Statut", "Légende"]
        )
        self.class_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.class_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.class_table.setAlternatingRowColors(True)
        self.class_table.itemDoubleClicked.connect(self._edit_color)
        layout.addWidget(self.class_table, 1)

        buttons = QGridLayout()
        apply_button = QPushButton("Appliquer la symbologie")
        apply_button.setStyleSheet("font-weight:700")
        add_button = QPushButton("Ajouter une classe visuelle")
        hide_button = QPushButton("Masquer la sélection")
        merge_button = QPushButton("Fusionner visuellement")
        reset_button = QPushButton("Restaurer l’analyse automatique")
        apply_button.clicked.connect(self.apply_scheme)
        add_button.clicked.connect(self.add_visual_class)
        hide_button.clicked.connect(self.hide_selected_classes)
        merge_button.clicked.connect(self.merge_selected_classes)
        reset_button.clicked.connect(self.reset_classes)
        buttons.addWidget(apply_button, 0, 0, 1, 2)
        buttons.addWidget(add_button, 1, 0)
        buttons.addWidget(hide_button, 1, 1)
        buttons.addWidget(merge_button, 2, 0)
        buttons.addWidget(reset_button, 2, 1)
        layout.addLayout(buttons)
        warning = QLabel(
            "La reclassification réelle des pixels est volontairement séparée de cet éditeur et doit être lancée explicitement dans les outils de traitement QGIS."
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)
        self.tabs.addTab(tab, "Classes")

    def _build_metadata_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.metadata = QTextBrowser()
        layout.addWidget(self.metadata)
        self.tabs.addTab(tab, "Métadonnées")

    def refresh(self, deep: bool):
        try:
            self.status.setText("Analyse du raster…")
            diagnosis = self.engine.analyze(self.layer, deep=deep)
            self._set_diagnosis(diagnosis)
            self.status.setText("Analyse terminée")
        except Exception as exc:
            self.status.setText(str(exc))

    def start_deep_analysis(self):
        if self._task is not None:
            return
        source = self.layer.source()
        self.deep_button.setEnabled(False)
        self.status.setText("Analyse approfondie en arrière-plan…")

        def worker(task, source_path):
            if task.isCanceled():
                return None
            return RasterInspector().inspect_source(source_path, deep=True)

        def finished(exception, result):
            self._task = None
            self.deep_button.setEnabled(True)
            if exception is not None:
                self.status.setText(f"Analyse approfondie indisponible : {exception}")
                return
            if result is None:
                self.status.setText("Analyse approfondie annulée")
                return
            try:
                inspection = replace(
                    result,
                    layer_id=self.layer.id(),
                    layer_name=self.layer.name(),
                    provider=self.layer.providerType(),
                )
                diagnosis = self.engine.diagnose_inspection(self.layer, inspection)
                self._set_diagnosis(diagnosis)
                self.status.setText("Analyse approfondie terminée")
            except Exception as exc:
                self.status.setText(str(exc))

        self._task = QgsTask.fromFunction(
            f"Cartomize · Analyse raster · {self.layer.name()}", worker,
            on_finished=finished, source_path=source,
        )
        QgsApplication.taskManager().addTask(self._task)

    def _set_diagnosis(self, diagnosis: RasterDiagnosis):
        self.diagnosis = diagnosis
        self._automatic_classes = diagnosis.classes
        lines = "".join(f"<tr><td>{_html(line.split(':',1)[0])}</td><td>{_html(line.split(':',1)[1].strip() if ':' in line else '')}</td></tr>" for line in diagnosis.summary_lines())
        rationale = "".join(f"<li>{_html(text)}</li>" for text in diagnosis.inference.rationale)
        missing = ", ".join(str(value) for value in diagnosis.inference.possible_missing_codes) or "Aucun code intermédiaire manquant détecté"
        self.summary.setHtml(
            f"<table cellspacing='6'>{lines}</table>"
            f"<p><b>Codes potentiellement absents</b> : {_html(missing)}</p>"
            f"<p><b>Symbologie recommandée</b> : {_html(diagnosis.inference.recommended_renderer)}</p>"
            f"<ul>{rationale}</ul>"
        )
        self.nodata_tree.clear()
        for candidate in diagnosis.inference.nodata_candidates:
            item = QTreeWidgetItem([
                _number(candidate.value), f"{candidate.confidence:.0%}", candidate.reason,
            ])
            item.setData(0, Qt.UserRole, float(candidate.value))
            self.nodata_tree.addTopLevelItem(item)
        self._populate_classes(diagnosis.classes)
        self._populate_metadata(diagnosis)

    def _populate_classes(self, classes):
        self.class_table.setRowCount(0)
        for definition in classes:
            row = self.class_table.rowCount()
            self.class_table.insertRow(row)
            visible = QTableWidgetItem()
            visible.setCheckState(Qt.Checked if definition.visible else Qt.Unchecked)
            visible.setData(Qt.UserRole, definition.to_dict())
            self.class_table.setItem(row, 0, visible)
            code = QTableWidgetItem(definition.code_label)
            code.setFlags(code.flags() & ~Qt.ItemIsEditable)
            self.class_table.setItem(row, 1, code)
            self.class_table.setItem(row, 2, QTableWidgetItem(definition.label))
            color = QTableWidgetItem(definition.color.upper())
            color.setBackground(QColor(definition.color))
            self.class_table.setItem(row, 3, color)
            for col, text in ((4, f"{definition.pixel_count:,}"), (5, f"{definition.percentage:.2f}"), (6, f"{definition.border_percentage:.1%}"), (7, definition.status)):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.class_table.setItem(row, col, item)
            legend = QTableWidgetItem()
            legend.setCheckState(Qt.Checked if definition.show_in_legend else Qt.Unchecked)
            self.class_table.setItem(row, 8, legend)
        self.class_table.resizeColumnsToContents()
        self.class_table.horizontalHeader().setStretchLastSection(True)

    def _populate_metadata(self, diagnosis):
        inspection = diagnosis.inspection
        rows = [
            ("Source", inspection.source), ("Format", inspection.storage_type),
            ("Dimensions", f"{inspection.width} × {inspection.height}"),
            ("Pixels", f"{inspection.total_pixels:,}"), ("CRS", inspection.crs),
            ("Bandes", str(inspection.band_count)),
            ("Types", ", ".join(inspection.data_types)),
            ("Résolution", f"{inspection.resolution_x or 'n/a'} × {inspection.resolution_y or 'n/a'}"),
            ("Masque", "Oui" if inspection.has_mask else "Non"),
            ("Alpha", "Oui" if inspection.has_alpha else "Non"),
            ("Table de couleurs", "Oui" if inspection.has_color_table else "Non"),
            ("Raster Attribute Table", "Oui" if inspection.has_rat else "Non"),
        ]
        html = "".join(f"<tr><td><b>{_html(key)}</b></td><td>{_html(value)}</td></tr>" for key, value in rows)
        extra = "".join(f"<tr><td>{_html(key)}</td><td>{_html(value)}</td></tr>" for key, value in sorted(inspection.metadata.items())[:100])
        self.metadata.setHtml(f"<table cellspacing='6'>{html}</table><h4>Métadonnées source</h4><table cellspacing='5'>{extra}</table>")

    def _definitions_from_table(self) -> tuple[RasterClassDefinition, ...]:
        definitions = []
        for row in range(self.class_table.rowCount()):
            base = self.class_table.item(row, 0).data(Qt.UserRole) or {}
            original = RasterClassDefinition.from_dict(base)
            label = self.class_table.item(row, 2).text().strip() or original.label
            color = self.class_table.item(row, 3).text().strip()
            if not QColor(color).isValid():
                color = original.color
            definitions.append(replace(
                original,
                label=label,
                color=QColor(color).name(),
                visible=self.class_table.item(row, 0).checkState() == Qt.Checked,
                show_in_legend=self.class_table.item(row, 8).checkState() == Qt.Checked,
                source="manual",
            ))
        return tuple(definitions)

    def apply_scheme(self):
        try:
            classes = self._definitions_from_table()
            self.engine.apply_classes(self.layer, classes)
            self.status.setText("Symbologie appliquée. Les pixels du raster n’ont pas été modifiés.")
        except Exception as exc:
            self.status.setText(str(exc))

    def reset_classes(self):
        self._populate_classes(self._automatic_classes)
        self.status.setText("Paramètres automatiques restaurés dans l’éditeur")

    def _edit_color(self, item):
        if item.column() != 3:
            return
        color = QColorDialog.getColor(QColor(item.text()), self, "Choisir la couleur de la classe")
        if color.isValid():
            item.setText(color.name().upper())
            item.setBackground(color)

    def add_visual_class(self):
        value, ok = QInputDialog.getDouble(self, "Ajouter une classe", "Code de la classe", decimals=6)
        if not ok:
            return
        label, ok = QInputDialog.getText(self, "Ajouter une classe", "Nom de la classe")
        if not ok:
            return
        current = list(self._definitions_from_table())
        current.append(RasterClassDefinition((float(value),), label.strip() or f"Classe {_number(value)}", "#607D8B", 0, 0.0, 0.0, "Classe visuelle", 0.5, True, True, "manual"))
        self._populate_classes(current)

    def hide_selected_classes(self):
        rows = sorted({index.row() for index in self.class_table.selectionModel().selectedRows()})
        for row in rows:
            self.class_table.item(row, 0).setCheckState(Qt.Unchecked)
            self.class_table.item(row, 8).setCheckState(Qt.Unchecked)
        self.status.setText(f"{len(rows)} classe(s) masquée(s) dans la représentation")

    def merge_selected_classes(self):
        rows = sorted({index.row() for index in self.class_table.selectionModel().selectedRows()})
        if len(rows) < 2:
            self.status.setText("Sélectionnez au moins deux classes à fusionner visuellement.")
            return
        definitions = list(self._definitions_from_table())
        selected = [definitions[row] for row in rows]
        label, ok = QInputDialog.getText(self, "Fusion visuelle", "Nom du groupe", text="Classes regroupées")
        if not ok:
            return
        merged = RasterClassDefinition(
            values=tuple(value for item in selected for value in item.values),
            label=label.strip() or "Classes regroupées",
            color=selected[0].color,
            pixel_count=sum(item.pixel_count for item in selected),
            percentage=sum(item.percentage for item in selected),
            border_percentage=max(item.border_percentage for item in selected),
            status="Fusion visuelle",
            confidence=min(item.confidence for item in selected),
            visible=True,
            show_in_legend=True,
            source="manual",
        )
        remaining = [item for index, item in enumerate(definitions) if index not in rows]
        remaining.insert(rows[0], merged)
        self._populate_classes(remaining)

    def mark_selected_nodata(self):
        item = self.nodata_tree.currentItem()
        if item is None:
            self.status.setText("Sélectionnez une valeur NoData potentielle.")
            return
        value = float(item.data(0, Qt.UserRole))
        definitions = []
        for definition in self._definitions_from_table():
            if value in definition.values:
                definitions.append(replace(definition, visible=False, show_in_legend=False, status="NoData visuel", source="manual"))
            else:
                definitions.append(definition)
        self._populate_classes(definitions)
        self.status.setText(f"Valeur {_number(value)} marquée comme NoData visuel. La donnée source reste intacte.")

    def keep_selected_class(self):
        item = self.nodata_tree.currentItem()
        if item is None:
            return
        value = float(item.data(0, Qt.UserRole))
        definitions = []
        for definition in self._definitions_from_table():
            if value in definition.values:
                definitions.append(replace(definition, visible=True, show_in_legend=True, status="Classe conservée", source="manual"))
            else:
                definitions.append(definition)
        self._populate_classes(definitions)
        self.status.setText(f"Valeur {_number(value)} conservée comme classe.")

    def export_diagnostic(self):
        if self.diagnosis is None:
            return
        default = Path.home() / f"Cartomize-Raster-{self.layer.name()}.json"
        path, _ = QFileDialog.getSaveFileName(self, "Exporter le diagnostic raster", str(default), "JSON (*.json)")
        if not path:
            return
        Path(path).write_text(json.dumps(self.diagnosis.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        self.status.setText(f"Diagnostic exporté : {path}")


def _html(value) -> str:
    import html
    return html.escape(str(value))


def _number(value: float) -> str:
    return str(int(round(value))) if abs(value - round(value)) < 1e-9 else f"{value:.6g}"
