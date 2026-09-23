"""Scene/band selection and optional multispectral production in Qt."""
from dataclasses import asdict
from pathlib import Path

import rasterio
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHeaderView,
    QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QFileDialog)

import cartomize as cm
from .desktop import Page, PathField, RASTER_FILTER, VECTOR_FILTER, spin


class PreparationPage(Page):
    engine = False
    staged = True

    def __init__(self):
        super().__init__("Prétraitement multispectral",
            "Sélection des scènes et des bandes, mosaïque, assemblage multibande, extraction par masque et composition colorée.")
        self.files = []
        self.source = PathField("directory")
        self.mode = QComboBox()
        self.mode.addItem("Landsat, Sentinel-2 ou manifeste de scènes", "auto")
        self.mode.addItem("Bandes personnalisées : correspondance manuelle", "manual")
        self.form.addRow("Identification des bandes", self.mode)
        self.form.addRow("Répertoire des scènes", self.source)
        select = QPushButton("Sélectionner les bandes…")
        clear = QPushButton("Utiliser le répertoire")
        select.clicked.connect(self.select_files)
        clear.clicked.connect(self.clear_files)
        self.form.addRow(select, clear)
        inspect = QPushButton("Analyser les bandes")
        inspect.clicked.connect(self.inspect_inputs)
        self.inventory = QLabel("Sélectionner les bandes ou analyser un répertoire.")
        self.inventory.setWordWrap(True)
        self.form.addRow(inspect, self.inventory)
        self.assets = QTableWidget(0, 8)
        self.assets.setHorizontalHeaderLabels(["Inclure", "Scène", "Bande spectrale", "Fichier", "Numéro", "Échelle", "Décalage", "Date"])
        self.assets.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.assets.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.assets.setMinimumHeight(170)
        self.assets.setMaximumHeight(250)
        self.form.addRow(self.assets)
        note = QLabel("Cocher les bandes à traiter. En mode personnalisé, renseigner le même identifiant de scène pour les bandes d’une acquisition et le même nom spectral entre scènes (red, green, blue, nir…). Vérifier les facteurs de calibration.")
        note.setWordWrap(True)
        self.form.addRow(note)
        self.aoi = PathField(filter=VECTOR_FILTER)
        self.form.addRow("Couche de délimitation", self.aoi)
        self.mosaic = QCheckBox("Mosaïque des scènes")
        self.mosaic.setChecked(True)
        self.multiband = QCheckBox("Assemblage multibande — conserver le GeoTIFF scientifique")
        self.multiband.setChecked(True)
        self.clip = QCheckBox("Extraction par masque — couche de délimitation")
        self.colour = QCheckBox("Composition colorée — GeoTIFF de visualisation séparé")
        self.separate = QCheckBox("Extraction des bandes — un GeoTIFF par bande")
        for control in (self.mosaic, self.multiband, self.clip, self.colour, self.separate):
            self.form.addRow(control)
        self.rgb_red = QComboBox()
        self.rgb_green = QComboBox()
        self.rgb_blue = QComboBox()
        for label, control in [("Canal rouge", self.rgb_red), ("Canal vert", self.rgb_green), ("Canal bleu", self.rgb_blue)]:
            self.form.addRow(label, control)
        self.crs = QLineEdit()
        self.crs.setPlaceholderText("Automatique · exemple : EPSG:32733")
        self.resolution = spin(0, 0, 100000)
        self.resolution.setSpecialValueText("Résolution native la plus grossière")
        self.clouds = QCheckBox("Appliquer les masques QA/SCL")
        self.clouds.setChecked(True)
        self.dates = QCheckBox("Autoriser une mosaïque multitemporelle ou de dates inconnues")
        for label, control in [("Système de coordonnées cible", self.crs), ("Résolution (m)", self.resolution),
                               ("Masque de qualité", self.clouds), ("Dates d’acquisition", self.dates)]:
            self.form.addRow(label, control)
        self.output = PathField("directory")
        self.name = QLineEdit("pretraitement")
        self.form.addRow("Répertoire de sortie", self.output)
        self.form.addRow("Nouveau dossier de résultats", self.name)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.form.addRow(self.summary)
        self.layout.addStretch()
        self.assets.itemChanged.connect(self.refresh_bands)
        self.source.edit.textChanged.connect(self.invalidate_inputs)
        self.mode.currentIndexChanged.connect(self.invalidate_inputs)
        self.aoi.edit.textChanged.connect(lambda text: self.clip.setChecked(bool(text.strip())))
        for control in (self.mosaic, self.multiband, self.clip, self.colour, self.separate):
            control.toggled.connect(self.refresh_options)
        self.refresh_options()

    def invalidate_inputs(self, *_):
        self.assets.setRowCount(0)
        self.inventory.setText("Analyser les bandes pour actualiser la sélection.")
        self.refresh_bands()

    def select_files(self):
        paths = QFileDialog.getOpenFileNames(self, "Bandes spectrales et masques de qualité",
            filter=RASTER_FILTER + ";;Manifestes de scènes (*.json)")[0]
        if paths:
            self.files = paths
            self.source.setEnabled(False)
            self.inspect_inputs()

    def clear_files(self):
        self.files = []
        self.source.setEnabled(True)
        self.invalidate_inputs()

    def inspect_inputs(self):
        try:
            self.load_inputs()
        except (ValueError, OSError, rasterio.errors.RasterioError) as exc:
            self.inventory.setText(str(exc))

    def load_inputs(self):
        self.assets.setRowCount(0)
        sources = list(self.files) if self.files else self.source.text()
        if not sources:
            raise ValueError("Sélectionner les bandes ou le répertoire des scènes.")
        if self.mode.currentData() == "auto":
            scenes = cm.discover_scenes(sources)
        else:
            paths = [Path(p) for p in sources] if isinstance(sources, list) else sorted(
                p for p in Path(sources).rglob("*") if p.suffix.lower() in {".tif", ".tiff", ".jp2", ".img", ".vrt"})
            bands = {}
            for path in paths:
                with rasterio.open(path) as src:
                    for index in src.indexes:
                        name = src.descriptions[index - 1] or (path.stem if src.count == 1 else f"band_{index}")
                        # Temporary unique keys; duplicates remain visible for manual correction.
                        bands[f"asset_{len(bands)}"] = (name, cm.Band(str(path.resolve()), index=index,
                            scale=src.scales[index - 1], offset=src.offsets[index - 1], unit=src.units[index - 1] or "source units"))
            if not bands:
                raise ValueError("Aucune bande raster trouvée.")
            scenes = [cm.Scene("scene_1", {key: band for key, (_, band) in bands.items()}, sensor="custom")]
            self.clouds.setChecked(False)
        self.assets.blockSignals(True)
        for scene in scenes:
            metadata = asdict(scene)
            metadata.pop("bands")
            for name, band in scene.bands.items():
                if self.mode.currentData() == "manual":
                    name = bands[name][0]
                row = self.assets.rowCount()
                self.assets.insertRow(row)
                checked = QCheckBox()
                checked.setChecked(True)
                checked.toggled.connect(self.refresh_bands)
                self.assets.setCellWidget(row, 0, checked)
                values = [scene.scene_id, name, str(Path(band.path).resolve()), str(band.index), str(band.scale), str(band.offset), scene.acquired or ""]
                for col, value in enumerate(values, 1):
                    item = QTableWidgetItem(value)
                    if col == 3:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        item.setData(Qt.ItemDataRole.UserRole, dict(scene=metadata, nodata=band.nodata, unit=band.unit))
                    self.assets.setItem(row, col, item)
        self.assets.blockSignals(False)
        self.inventory.setText(f"{len(scenes)} scène(s) · {self.assets.rowCount()} bande(s). Vérifier la sélection.")
        self.refresh_bands()

    def refresh_bands(self, *_):
        names = list(dict.fromkeys(self.assets.item(row, 2).text().strip() for row in range(self.assets.rowCount())
            if self.assets.item(row, 2) and self.assets.cellWidget(row, 0) and self.assets.cellWidget(row, 0).isChecked()))
        for control, default in [(self.rgb_red, "red"), (self.rgb_green, "green"), (self.rgb_blue, "blue")]:
            previous = control.currentData() or default
            control.clear()
            control.addItem("Sélectionner une bande", None)
            for name in names:
                control.addItem(name, name)
            index = control.findData(previous)
            control.setCurrentIndex(max(0, index))

    def refresh_options(self, *_):
        for control in (self.rgb_red, self.rgb_green, self.rgb_blue):
            control.setEnabled(self.colour.isChecked())
        self.summary.setText("Sortie : " + ("scènes assemblées" if self.mosaic.isChecked() else "un dossier par scène") +
            ". Les bandes scientifiques et la composition colorée sont enregistrées dans des fichiers distincts. Le dossier de résultats doit être nouveau.")

    def restore_controls(self):
        for row in range(self.assets.rowCount()):
            self.assets.cellWidget(row, 0).toggled.connect(self.refresh_bands)
        self.refresh_options()

    def selected_scenes(self):
        groups = {}
        for row in range(self.assets.rowCount()):
            if not self.assets.cellWidget(row, 0).isChecked():
                continue
            scene, name, path, index, scale, offset, date = [self.assets.item(row, col).text().strip() for col in range(1, 8)]
            raw = self.assets.item(row, 3).data(Qt.ItemDataRole.UserRole)
            metadata = {**raw["scene"], "scene_id": scene, "acquired": date or None}
            group = groups.setdefault(scene, dict(metadata=metadata, bands={}))
            if group["metadata"] != metadata:
                raise ValueError("Métadonnées différentes pour une même scène : " + scene)
            if name in group["bands"]:
                raise ValueError(f"Bande dupliquée : {scene} / {name}. Corriger la scène ou le nom spectral.")
            group["bands"][name] = cm.Band(path, index=int(index), scale=float(scale), offset=float(offset),
                nodata=raw["nodata"], unit=raw["unit"])
        if not groups:
            raise ValueError("Cocher au moins une bande.")
        return [cm.Scene(bands=value["bands"], **value["metadata"]) for value in groups.values()]

    def job(self, options):
        if not self.assets.rowCount():
            self.load_inputs()
        scenes = self.selected_scenes()
        if self.clip.isChecked() and not self.aoi.text():
            raise ValueError("Charger la couche de délimitation pour l’extraction par masque.")
        rgb = tuple(control.currentData() for control in (self.rgb_red, self.rgb_green, self.rgb_blue)) if self.colour.isChecked() else None
        if rgb and None in rgb:
            raise ValueError("Affecter une bande à chacun des trois canaux rouge, vert et bleu.")
        name = self.name.text().strip()
        if not name or name in {".", ".."} or any(c in name for c in '/\\:*?"<>|'):
            raise ValueError("Renseigner un nom de dossier de résultats sans séparateur de chemin.")
        if not self.output.text():
            raise ValueError("Sélectionner le répertoire de sortie.")
        destination = Path(self.output.text()) / name
        kwargs = dict(aoi=self.aoi.text() if self.clip.isChecked() else None, mosaic=self.mosaic.isChecked(),
            multiband=self.multiband.isChecked(), separate_bands=self.separate.isChecked(), composition=rgb,
            target_crs=self.crs.text().strip() or None, resolution=self.resolution.value() or None,
            mask_clouds=self.clouds.isChecked(), allow_mixed_dates=self.dates.isChecked())
        return lambda progress, cancel, stage: cm.process_imagery(scenes, destination,
            progress=progress, cancel=cancel, stage=stage, **kwargs).manifest
