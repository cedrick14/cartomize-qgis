"""Interface du Raster Engine de Cartomize."""
from __future__ import annotations

from dataclasses import replace
import json
import math
from pathlib import Path

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QInputDialog,
    QPushButton,
    QSpinBox,
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
)
from ..core.raster_symbology import RasterSymbologyRecommendation, RasterSymbologyService


class RasterIntelligenceDialog(QDialog):
    def __init__(
        self,
        layer: QgsRasterLayer,
        engine: RasterIntelligenceEngine,
        parent=None,
        *,
        symbology_service: RasterSymbologyService | None = None,
    ):
        super().__init__(parent)
        self.layer = layer
        self.engine = engine
        self.symbology_service = symbology_service
        self.diagnosis: RasterDiagnosis | None = None
        self.rendering_recommendation: RasterSymbologyRecommendation | None = None
        self._automatic_classes: tuple[RasterClassDefinition, ...] = ()
        self._task = None
        self._preview_active = False
        self._loading_theme = False
        self.setWindowTitle(f"Analyse raster · {layer.name()}")
        self.resize(980, 720)
        self.setMinimumSize(760, 560)
        self._build_ui()
        self.refresh(False)

    def _build_ui(self):
        root = QVBoxLayout(self)
        title = QLabel("Raster Engine")
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
        self._build_rendering_tab()
        self._build_metadata_tab()

        footer = QHBoxLayout()
        self.status = QLabel("Prêt")
        self.status.setWordWrap(True)
        footer.addWidget(self.status, 1)
        close = QPushButton("Fermer")
        close.clicked.connect(self._close_dialog)
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
        self.class_table = QTableWidget(0, 10)
        self.class_table.setHorizontalHeaderLabels(
            ["Visible", "Valeur(s) source", "Nom", "Couleur", "Opacité %", "Pixels", "%", "Bordure", "Statut", "Légende"]
        )
        self.class_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.class_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.class_table.setAlternatingRowColors(True)
        self.class_table.itemDoubleClicked.connect(self._edit_color)
        layout.addWidget(self.class_table, 1)

        buttons = QGridLayout()
        apply_button = QPushButton("Appliquer la symbologie")
        apply_button.setStyleSheet("font-weight:700")
        add_button = QPushButton("Ajouter une classe visuelle")
        hide_button = QPushButton("Masquer la sélection")
        delete_button = QPushButton("Retirer du rendu")
        merge_button = QPushButton("Fusionner visuellement")
        up_button = QPushButton("Monter")
        down_button = QPushButton("Descendre")
        reset_button = QPushButton("Restaurer l’analyse automatique")
        apply_button.clicked.connect(self.apply_scheme)
        add_button.clicked.connect(self.add_visual_class)
        hide_button.clicked.connect(self.hide_selected_classes)
        delete_button.clicked.connect(self.delete_selected_classes)
        merge_button.clicked.connect(self.merge_selected_classes)
        up_button.clicked.connect(lambda: self.move_selected_class(-1))
        down_button.clicked.connect(lambda: self.move_selected_class(1))
        reset_button.clicked.connect(self.reset_classes)
        buttons.addWidget(apply_button, 0, 0, 1, 2)
        buttons.addWidget(add_button, 1, 0)
        buttons.addWidget(hide_button, 1, 1)
        buttons.addWidget(merge_button, 2, 0)
        buttons.addWidget(reset_button, 2, 1)
        buttons.addWidget(delete_button, 3, 0)
        buttons.addWidget(up_button, 3, 1)
        buttons.addWidget(down_button, 4, 1)
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

    def _build_rendering_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        info = QLabel(
            "La recommandation est un point de départ. Vérifiez et modifiez le mode, la bande, "
            "la palette, les bornes, le nombre de classes ou la composition RGB avant application."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        theme_form = QGridLayout()
        self.theme_mode = QComboBox()
        self.theme_mode.addItem("Détection automatique", "automatic")
        self.theme_mode.addItem("Choisir manuellement", "manual")
        self.theme_profile = QComboBox()
        profiles = (
            self.symbology_service.theme_profiles()
            if self.symbology_service is not None
            else RasterSymbologyService.theme_profiles()
        )
        for profile in profiles:
            self.theme_profile.addItem(profile.label, profile.key)
            index = self.theme_profile.count() - 1
            self.theme_profile.setItemData(index, profile.description, Qt.ItemDataRole.ToolTipRole)
        self.theme_profile.setEnabled(False)
        self.theme_evidence = QLabel("Analyse thématique en cours…")
        self.theme_evidence.setWordWrap(True)
        self.theme_evidence.setStyleSheet(
            "padding:8px;border:1px solid #cbd5e1;border-radius:4px;background:#f8fafc"
        )
        theme_form.addWidget(QLabel("Type de carte"), 0, 0)
        theme_form.addWidget(self.theme_mode, 0, 1, 1, 3)
        theme_form.addWidget(QLabel("Schéma thématique"), 1, 0)
        theme_form.addWidget(self.theme_profile, 1, 1, 1, 3)
        theme_form.addWidget(self.theme_evidence, 2, 0, 1, 4)
        layout.addLayout(theme_form)
        self.theme_mode.currentIndexChanged.connect(self._theme_mode_changed)
        self.theme_profile.currentIndexChanged.connect(self._theme_profile_changed)

        form = QGridLayout()
        self.render_mode = QComboBox()
        for label, code in (
            ("Catégoriel", "categorical"), ("Continu", "continuous"),
            ("Niveaux de gris", "gray"), ("Composition RGB", "rgb"),
        ):
            self.render_mode.addItem(label, code)
        self.render_band = QComboBox()
        self.render_palette = QComboBox()
        palettes = self.symbology_service.PALETTES if self.symbology_service else RasterSymbologyService.PALETTES
        for key in palettes:
            self.render_palette.addItem(key.replace("_", " ").title(), key)
        self.render_classes = QSpinBox()
        self.render_classes.setRange(2, 64)
        self.render_classification = QComboBox()
        self.render_classification.addItem("Quantiles de l’échantillon valide", "sample_quantiles")
        self.render_classification.addItem("Intervalles égaux", "equal_interval")
        self.render_minimum = QDoubleSpinBox()
        self.render_maximum = QDoubleSpinBox()
        for spin in (self.render_minimum, self.render_maximum):
            spin.setRange(-1.0e30, 1.0e30)
            spin.setDecimals(8)
        self.render_red = QComboBox()
        self.render_green = QComboBox()
        self.render_blue = QComboBox()
        self.render_confirmation = QCheckBox("Confirmer les paramètres avant application")
        form.addWidget(QLabel("Mode"), 0, 0)
        form.addWidget(self.render_mode, 0, 1)
        form.addWidget(QLabel("Bande analysée"), 1, 0)
        form.addWidget(self.render_band, 1, 1)
        form.addWidget(QLabel("Palette"), 2, 0)
        form.addWidget(self.render_palette, 2, 1)
        form.addWidget(QLabel("Nombre de classes"), 3, 0)
        form.addWidget(self.render_classes, 3, 1)
        form.addWidget(QLabel("Méthode de classification"), 4, 0)
        form.addWidget(self.render_classification, 4, 1)
        form.addWidget(QLabel("Minimum"), 5, 0)
        form.addWidget(self.render_minimum, 5, 1)
        form.addWidget(QLabel("Maximum"), 6, 0)
        form.addWidget(self.render_maximum, 6, 1)
        form.addWidget(QLabel("Bande rouge"), 0, 2)
        form.addWidget(self.render_red, 0, 3)
        form.addWidget(QLabel("Bande verte"), 1, 2)
        form.addWidget(self.render_green, 1, 3)
        form.addWidget(QLabel("Bande bleue"), 2, 2)
        form.addWidget(self.render_blue, 2, 3)
        form.addWidget(self.render_confirmation, 7, 0, 1, 4)
        layout.addLayout(form)
        rendering_actions = QGridLayout()
        preview_button = QPushButton("Prévisualiser")
        apply_button = QPushButton("Appliquer la symbologie")
        cancel_preview_button = QPushButton("Annuler l’aperçu")
        undo_button = QPushButton("Rétablir le rendu précédent")
        qml_button = QPushButton("Enregistrer le style QML…")
        apply_button.setStyleSheet("font-weight:700")
        preview_button.clicked.connect(self.preview_selected_theme)
        apply_button.clicked.connect(self.apply_rendering_plan)
        cancel_preview_button.clicked.connect(self.cancel_preview)
        undo_button.clicked.connect(self.undo_rendering)
        qml_button.clicked.connect(self.save_qml_style)
        for button in (preview_button, apply_button, cancel_preview_button, undo_button, qml_button):
            button.setEnabled(self.symbology_service is not None)
        rendering_actions.addWidget(preview_button, 0, 0)
        rendering_actions.addWidget(apply_button, 0, 1)
        rendering_actions.addWidget(cancel_preview_button, 1, 0)
        rendering_actions.addWidget(undo_button, 1, 1)
        rendering_actions.addWidget(qml_button, 2, 0, 1, 2)
        layout.addLayout(rendering_actions)
        note = QLabel(
            "Le rendu reste réversible et n’écrit jamais dans les pixels. Pour une transformation de données, "
            "utilisez explicitement les algorithmes de traitement QGIS."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        self.tabs.addTab(tab, "Symbologie")

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
            return RasterInspector().inspect_source(source_path, deep=True, feedback=task)

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
        semantics = "".join(
            f"<li>Bande {item.get('band')} : {_html(item.get('role', 'unknown'))} "
            f"({float(item.get('confidence', 0)):.0%})</li>"
            for item in diagnosis.band_semantics
        )
        indices = "".join(
            f"<li><b>{_html(item.get('name', ''))}</b> — {_html(item.get('formula', ''))} "
            f"({float(item.get('confidence', 0)):.0%})</li>"
            for item in diagnosis.spectral_indices
        ) or "<li>Aucun indice spectral proposé sans identification fiable des bandes requises.</li>"
        self.summary.setHtml(
            f"<table cellspacing='6'>{lines}</table>"
            f"<p><b>Codes potentiellement absents</b> : {_html(missing)}</p>"
            f"<p><b>Symbologie recommandée</b> : {_html(diagnosis.inference.recommended_renderer)}</p>"
            f"<ul>{rationale}</ul>"
            f"<p><b>Rôles de bandes détectés</b></p><ul>{semantics}</ul>"
            f"<p><b>Indices spectraux calculables</b></p><ul>{indices}</ul>"
        )
        self.nodata_tree.clear()
        for candidate in diagnosis.inference.nodata_candidates:
            item = QTreeWidgetItem([
                _number(candidate.value), f"{candidate.confidence:.0%}", candidate.reason,
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, float(candidate.value))
            self.nodata_tree.addTopLevelItem(item)
        self._populate_classes(diagnosis.classes)
        self._populate_metadata(diagnosis)
        if self.symbology_service is not None:
            try:
                self.rendering_recommendation = self.symbology_service.recommend_from_diagnosis(
                    self.layer, diagnosis
                )
                self._populate_theme_selector(self.rendering_recommendation)
                self._populate_rendering_editor(self.rendering_recommendation)
            except Exception as exc:
                self.status.setText(f"Diagnostic disponible, proposition de rendu incomplète : {exc}")

    def _populate_classes(self, classes):
        self.class_table.setRowCount(0)
        for definition in classes:
            row = self.class_table.rowCount()
            self.class_table.insertRow(row)
            visible = QTableWidgetItem()
            visible.setCheckState(
                Qt.CheckState.Checked if definition.visible else Qt.CheckState.Unchecked
            )
            visible.setData(Qt.ItemDataRole.UserRole, definition.to_dict())
            self.class_table.setItem(row, 0, visible)
            code = QTableWidgetItem(definition.code_label)
            code.setToolTip(
                "Correspondance vers les valeurs réelles du raster. Cette saisie ne modifie pas les pixels."
            )
            self.class_table.setItem(row, 1, code)
            self.class_table.setItem(row, 2, QTableWidgetItem(definition.label))
            color = QTableWidgetItem(definition.color.upper())
            color.setBackground(QColor(definition.color))
            self.class_table.setItem(row, 3, color)
            opacity = QTableWidgetItem(str(round(definition.opacity * 100)))
            opacity.setToolTip("Opacité du symbole entre 0 et 100 %.")
            self.class_table.setItem(row, 4, opacity)
            for col, text in ((5, f"{definition.pixel_count:,}"), (6, f"{definition.percentage:.2f}"), (7, f"{definition.border_percentage:.1%}"), (8, definition.status)):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.class_table.setItem(row, col, item)
            legend = QTableWidgetItem()
            legend.setCheckState(
                Qt.CheckState.Checked
                if definition.show_in_legend
                else Qt.CheckState.Unchecked
            )
            self.class_table.setItem(row, 9, legend)
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

    def _populate_rendering_editor(self, recommendation: RasterSymbologyRecommendation):
        names = self.diagnosis.inspection.band_names if self.diagnosis else ()
        for combo in (self.render_band, self.render_red, self.render_green, self.render_blue):
            combo.clear()
            for number in range(1, max(1, self.layer.bandCount()) + 1):
                name = names[number - 1] if number <= len(names) else f"Bande {number}"
                combo.addItem(f"{number} · {name}", number)
        for combo, value in (
            (self.render_mode, recommendation.mode),
            (self.render_palette, recommendation.theme),
            (self.render_band, recommendation.band),
            (self.render_red, recommendation.red_band),
            (self.render_green, recommendation.green_band),
            (self.render_blue, recommendation.blue_band),
        ):
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)
        self.render_classes.setValue(max(2, recommendation.class_count))
        method_index = self.render_classification.findData(recommendation.classification_method)
        self.render_classification.setCurrentIndex(max(0, method_index))
        self.render_minimum.setValue(float(recommendation.minimum if recommendation.minimum is not None else 0.0))
        self.render_maximum.setValue(float(recommendation.maximum if recommendation.maximum is not None else 1.0))
        verified = recommendation.confidence >= 0.65
        self.render_confirmation.setChecked(False)
        self.render_confirmation.setText(
            "J’ai vérifié ces paramètres (facultatif lorsque la confiance est suffisante)"
            if verified else "Confiance faible : je confirme explicitement ces paramètres"
        )

    def _populate_theme_selector(self, recommendation: RasterSymbologyRecommendation):
        self._loading_theme = True
        try:
            index = self.theme_profile.findData(recommendation.theme)
            if index < 0 and recommendation.mode == "rgb":
                index = self.theme_profile.findData("rgb")
            if index >= 0:
                self.theme_profile.setCurrentIndex(index)
            title = recommendation.theme_label or str(recommendation.theme).replace("_", " ").title()
            evidence = " ".join(recommendation.rationale[-3:])
            warning = (
                f"<br><b>Vérification requise :</b> {_html(recommendation.compatibility_warning)}"
                if recommendation.compatibility_warning else ""
            )
            self.theme_evidence.setTextFormat(Qt.TextFormat.RichText)
            self.theme_evidence.setText(
                f"<b>Type recommandé : {_html(title)}</b> &nbsp; "
                f"Confiance : {recommendation.confidence:.0%}<br>{_html(evidence)}{warning}"
            )
        finally:
            self._loading_theme = False

    def _theme_mode_changed(self):
        manual = self.theme_mode.currentData() == "manual"
        self.theme_profile.setEnabled(manual)
        if self._loading_theme or self.diagnosis is None or self.symbology_service is None:
            return
        try:
            if manual:
                self._load_manual_theme()
            else:
                recommendation = self.symbology_service.recommend_from_diagnosis(
                    self.layer, self.diagnosis
                )
                self.rendering_recommendation = recommendation
                self._populate_theme_selector(recommendation)
                self._populate_rendering_editor(recommendation)
                self.preview_selected_theme()
        except Exception as exc:
            self.status.setText(str(exc))

    def _theme_profile_changed(self):
        if (
            self._loading_theme
            or self.theme_mode.currentData() != "manual"
            or self.diagnosis is None
            or self.symbology_service is None
        ):
            return
        self._load_manual_theme()

    def _load_manual_theme(self):
        key = str(self.theme_profile.currentData() or "continuous")
        recommendation = self.symbology_service.manual_recommendation_from_diagnosis(
            self.layer, self.diagnosis, key
        )
        self.rendering_recommendation = recommendation
        if recommendation.mode == "categorical":
            definitions, _warning = self.symbology_service.class_definitions_for_theme(
                self.diagnosis, key
            )
            self._populate_classes(definitions)
        self._populate_theme_selector(recommendation)
        self._populate_rendering_editor(recommendation)
        self.preview_selected_theme()

    def _recommendation_from_editor(self) -> RasterSymbologyRecommendation:
        if self.rendering_recommendation is None:
            raise CartomizeError("Aucune proposition de rendu n'est disponible.")
        minimum = float(self.render_minimum.value())
        maximum = float(self.render_maximum.value())
        mode = str(self.render_mode.currentData())
        if minimum >= maximum and mode in {"continuous", "gray"}:
            raise CartomizeError("Le minimum doit être strictement inférieur au maximum.")
        theme = str(self.render_palette.currentData() or "continuous")
        palette = self.symbology_service.PALETTES.get(
            theme,
            self.rendering_recommendation.palette
            or self.symbology_service.PALETTES["continuous"],
        )
        values = self.rendering_recommendation.class_values
        value_groups = self.rendering_recommendation.class_value_groups
        opacities = self.rendering_recommendation.class_opacities
        labels = self.rendering_recommendation.labels
        if mode == "categorical":
            definitions = tuple(
                item for item in self._definitions_from_table() if item.visible and item.values
            )
            values = tuple(item.values[0] for item in definitions)
            value_groups = tuple(item.values for item in definitions)
            opacities = tuple(item.opacity for item in definitions)
            labels = tuple(item.label for item in definitions)
            palette = tuple(item.color for item in definitions)
        selected_theme = (
            str(self.theme_profile.currentData())
            if self.theme_mode.currentData() == "manual" else theme
        )
        return replace(
            self.rendering_recommendation,
            mode=mode,
            theme="gray" if mode == "gray" else selected_theme,
            band=int(self.render_band.currentData() or 1),
            minimum=minimum,
            maximum=maximum,
            class_count=len(values) if mode == "categorical" else int(self.render_classes.value()),
            classification_method=str(self.render_classification.currentData() or "equal_interval"),
            palette=palette,
            labels=labels,
            class_values=values,
            class_value_groups=value_groups,
            class_opacities=opacities,
            red_band=int(self.render_red.currentData() or 1),
            green_band=int(self.render_green.currentData() or 1),
            blue_band=int(self.render_blue.currentData() or 1),
            expert_confirmed=self.render_confirmation.isChecked(),
        )

    def preview_selected_theme(self):
        if self.symbology_service is None:
            return
        try:
            recommendation = self._recommendation_from_editor()
            self.symbology_service.preview(self.layer, recommendation)
            self._preview_active = True
            self.status.setText(
                f"Aperçu actif · {recommendation.summary()} · pixels et NoData source inchangés."
            )
        except Exception as exc:
            self.status.setText(str(exc))

    def cancel_preview(self):
        if self.symbology_service is not None and self.symbology_service.cancel_preview(self.layer):
            self._preview_active = False
            self.status.setText("Aperçu annulé; le rendu antérieur est restauré.")

    def undo_rendering(self):
        self.cancel_preview()
        restored = False
        if self.symbology_service is not None:
            restored = self.symbology_service.undo_last(self.layer)
        if not restored:
            restored = self.engine.undo_last(self.layer)
        self.status.setText(
            "Rendu précédent restauré." if restored else "Aucun rendu antérieur à restaurer."
        )

    def save_qml_style(self):
        default = Path.home() / f"Cartomize-{self.layer.name()}.qml"
        path, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer le style raster QGIS", str(default), "Style QGIS (*.qml)"
        )
        if not path:
            return
        if not path.casefold().endswith(".qml"):
            path += ".qml"
        try:
            result = self.layer.saveNamedStyle(path)
            ok = True
            message = ""
            if isinstance(result, tuple):
                message = str(result[0] or "")
                booleans = [value for value in result if isinstance(value, bool)]
                ok = all(booleans) if booleans else True
            if not ok:
                raise CartomizeError(message or "QGIS n'a pas pu enregistrer le style QML.")
            self.status.setText(f"Style QML enregistré : {path}")
        except Exception as exc:
            self.status.setText(f"Enregistrement QML impossible : {exc}")

    def apply_rendering_plan(self):
        if self.symbology_service is None or self.rendering_recommendation is None:
            self.status.setText("Service de rendu raster indisponible.")
            return
        try:
            recommendation = self._recommendation_from_editor()
            mode = recommendation.mode
            if mode == "categorical":
                if self.rendering_recommendation.confidence < 0.65 and not self.render_confirmation.isChecked():
                    raise CartomizeError("Confirmez les paramètres catégoriels à faible confiance.")
                self.cancel_preview()
                self.engine.apply_classes(
                    self.layer, self._definitions_from_table(),
                    band=int(self.render_band.currentData() or 1),
                )
                self._preview_active = False
                self.status.setText("Rendu catégoriel expert appliqué. Les pixels sont inchangés.")
                return
            result = self.symbology_service.apply(self.layer, recommendation)
            self.rendering_recommendation = result
            self._preview_active = False
            self.status.setText(f"{result.summary()} appliqué. Les pixels du raster sont inchangés.")
        except Exception as exc:
            self.status.setText(str(exc))

    def _definitions_from_table(self) -> tuple[RasterClassDefinition, ...]:
        definitions = []
        assigned_values: dict[float, int] = {}
        for row in range(self.class_table.rowCount()):
            base = self.class_table.item(row, 0).data(Qt.ItemDataRole.UserRole) or {}
            original = RasterClassDefinition.from_dict(base)
            values = _parse_codes(self.class_table.item(row, 1).text())
            if not values:
                raise CartomizeError(f"Ligne {row + 1} : indiquez au moins une valeur source numérique.")
            label = self.class_table.item(row, 2).text().strip() or original.label
            color = self.class_table.item(row, 3).text().strip()
            if not QColor(color).isValid():
                color = original.color
            try:
                opacity = float(self.class_table.item(row, 4).text().replace(",", ".")) / 100.0
            except (TypeError, ValueError):
                raise CartomizeError(f"Ligne {row + 1} : l'opacité doit être comprise entre 0 et 100 %.")
            if not 0.0 <= opacity <= 1.0:
                raise CartomizeError(f"Ligne {row + 1} : l'opacité doit être comprise entre 0 et 100 %.")
            for value in values:
                previous = assigned_values.get(value)
                if previous is not None:
                    raise CartomizeError(
                        f"Le code source {_number(value)} est affecté aux lignes "
                        f"{previous} et {row + 1}. Chaque code ne peut appartenir "
                        "qu'à une seule classe visuelle."
                    )
                assigned_values[value] = row + 1
            definitions.append(replace(
                original,
                values=values,
                label=label,
                color=QColor(color).name(),
                opacity=opacity,
                visible=(
                    self.class_table.item(row, 0).checkState()
                    == Qt.CheckState.Checked
                ),
                show_in_legend=(
                    self.class_table.item(row, 9).checkState()
                    == Qt.CheckState.Checked
                ),
                source="manual",
            ))
        return tuple(definitions)

    def apply_scheme(self):
        try:
            classes = self._definitions_from_table()
            self.cancel_preview()
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
            self.class_table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
            self.class_table.item(row, 9).setCheckState(Qt.CheckState.Unchecked)
        self.status.setText(f"{len(rows)} classe(s) masquée(s) dans la représentation")

    def delete_selected_classes(self):
        rows = sorted(
            {index.row() for index in self.class_table.selectionModel().selectedRows()},
            reverse=True,
        )
        if not rows:
            self.status.setText("Sélectionnez au moins une correspondance à retirer du rendu.")
            return
        definitions = list(self._definitions_from_table())
        for row in rows:
            del definitions[row]
        self._populate_classes(definitions)
        self.status.setText(
            f"{len(rows)} correspondance(s) retirée(s) du rendu; les pixels source sont inchangés."
        )

    def move_selected_class(self, offset: int):
        rows = sorted({index.row() for index in self.class_table.selectionModel().selectedRows()})
        if len(rows) != 1:
            self.status.setText("Sélectionnez une seule classe à déplacer.")
            return
        source = rows[0]
        target = source + int(offset)
        definitions = list(self._definitions_from_table())
        if target < 0 or target >= len(definitions):
            return
        definitions[source], definitions[target] = definitions[target], definitions[source]
        self._populate_classes(definitions)
        self.class_table.selectRow(target)
        self.status.setText("Ordre de légende modifié dans l'aperçu.")

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
            opacity=selected[0].opacity,
        )
        remaining = [item for index, item in enumerate(definitions) if index not in rows]
        remaining.insert(rows[0], merged)
        self._populate_classes(remaining)

    def mark_selected_nodata(self):
        item = self.nodata_tree.currentItem()
        if item is None:
            self.status.setText("Sélectionnez une valeur NoData potentielle.")
            return
        value = float(item.data(0, Qt.ItemDataRole.UserRole))
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
        value = float(item.data(0, Qt.ItemDataRole.UserRole))
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

    def _close_dialog(self):
        self.cancel_preview()
        self.accept()

    def reject(self):
        self.cancel_preview()
        super().reject()

    def closeEvent(self, event):
        self.cancel_preview()
        super().closeEvent(event)


def _html(value) -> str:
    import html
    return html.escape(str(value))


def _number(value: float) -> str:
    return str(int(round(value))) if abs(value - round(value)) < 1e-9 else f"{value:.6g}"


def _parse_codes(text: str) -> tuple[float, ...]:
    values = []
    for token in str(text).replace(";", ",").split(","):
        token = token.strip()
        if not token:
            continue
        try:
            value = float(token)
        except ValueError as exc:
            raise CartomizeError(f"Code source non numérique : {token}") from exc
        if not math.isfinite(value):
            raise CartomizeError(
                f"Code source non fini interdit : {token}. Utilisez une valeur raster réelle."
            )
        if value not in values:
            values.append(value)
    return tuple(values)
