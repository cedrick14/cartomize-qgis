"""Optional Qt desktop application for Cartomize processing tools."""
from pathlib import Path
import os
import sys
import threading

try:
    from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot, QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QHBoxLayout,QVBoxLayout,
        QFormLayout,QLabel,QLineEdit,QPushButton,QFileDialog,QListWidget,QListWidgetItem,
        QStackedWidget,QComboBox,QSpinBox,QDoubleSpinBox,QCheckBox,QPlainTextEdit,
        QTableWidget,QTableWidgetItem,QHeaderView,QProgressBar,QMessageBox,QGroupBox,QScrollArea)
except ImportError as exc:
    raise ImportError('Interface graphique indisponible. Installer : python -m pip install "PySide6-Essentials>=6.7,<7"') from exc

import rasterio
import cartomize as cm
from .composition import ORDER

RASTER_FILTER="Données raster (*.tif *.tiff *.vrt *.img *.jp2);;Tous les fichiers (*)"
VECTOR_FILTER="Données vectorielles (*.gpkg *.shp *.geojson *.json);;Tous les fichiers (*)"
STATISTICS={"Moyenne":"mean","Somme":"sum","Minimum":"min","Maximum":"max","Écart-type":"std","Nombre de valeurs valides":"count"}
ROLE_LABELS={"Fond raster":"background","Occupation du sol":"landcover","Données thématiques":"thematic",
             "Polygones":"polygon","Hydrographie":"water","Lignes":"line","Routes":"roads",
             "Voies ferrées":"railways","Limites administratives":"boundaries","Localités":"localities","Points":"points"}


class PathField(QWidget):
    def __init__(self,mode="open",filter=RASTER_FILTER):
        super().__init__();self.mode=mode;self.filter=filter
        layout=QHBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.edit=QLineEdit();button=QPushButton("Parcourir…")
        layout.addWidget(self.edit,1);layout.addWidget(button);button.clicked.connect(self.browse)
    def browse(self):
        if self.mode=="directory":path=QFileDialog.getExistingDirectory(self,"Répertoire des scènes",self.edit.text())
        elif self.mode=="save":path=QFileDialog.getSaveFileName(self,"Fichier de sortie",self.edit.text(),self.filter)[0]
        else:path=QFileDialog.getOpenFileName(self,"Données d’entrée",self.edit.text(),self.filter)[0]
        if path:self.edit.setText(path)
    def text(self):return self.edit.text().strip()


def spin(value=1,minimum=1,maximum=999):
    widget=QSpinBox();widget.setRange(minimum,maximum);widget.setValue(value);return widget


def real(value=1.):
    widget=QDoubleSpinBox();widget.setDecimals(8);widget.setRange(-1e9,1e9);widget.setValue(value);return widget


class Page(QWidget):
    cancellable=True
    engine=True
    def __init__(self,title,description):
        super().__init__();self.layout=QVBoxLayout(self)
        heading=QLabel(title);heading.setObjectName("pageTitle")
        detail=QLabel(description);detail.setWordWrap(True);detail.setObjectName("description")
        self.layout.addWidget(heading);self.layout.addWidget(detail)
        self.form=QFormLayout();self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.layout.addLayout(self.form)
        self.output=PathField("save","GeoTIFF (*.tif)")
    def finish(self):
        self.form.addRow("Fichier de sortie",self.output);self.layout.addStretch()
    def destination(self):
        if not self.output.text():raise ValueError("Sélectionner un fichier de sortie.")
        return self.output.text()


class IndicesPage(Page):
    def __init__(self):
        super().__init__("Indices spectraux","Calcul multibande des indices de végétation, d’humidité, d’eau, de sol et du bâti.")
        self.source=PathField();self.form.addRow("Raster multispectral",self.source)
        self.selection=QListWidget();self.selection.setMaximumHeight(165)
        for definition in cm.list_indices():
            item=QListWidgetItem(f"{definition['name']}  ·  {definition['title']}",self.selection)
            item.setData(Qt.ItemDataRole.UserRole,definition["name"])
            item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if definition["name"]=="NDVI" else Qt.CheckState.Unchecked)
            item.setToolTip(definition["formula"]+"\n"+definition["reference"])
        self.form.addRow("Indices",self.selection)
        self.bands=QTableWidget(0,2);self.bands.setHorizontalHeaderLabels(["Bande spectrale","Numéro de bande"])
        self.bands.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);self.bands.setMaximumHeight(155)
        self.form.addRow("Correspondance spectrale",self.bands)
        self.parameters=QTableWidget(0,3);self.parameters.setHorizontalHeaderLabels(["Indice","Paramètre","Valeur"])
        self.parameters.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);self.parameters.setMaximumHeight(110)
        self.form.addRow("Paramètres des indices",self.parameters)
        self.metadata=QCheckBox("Utiliser la calibration enregistrée dans le raster");self.metadata.setChecked(True)
        self.metadata.setToolTip("EVI, SAVI et MSAVI nécessitent des valeurs de réflectance calibrées. Le prétraitement multispectral prépare les produits Landsat et Sentinel pris en charge.")
        self.form.addRow("Calibration",self.metadata)
        self.scale=real(1);self.offset=real(0)
        self.form.addRow("Facteur multiplicatif",self.scale);self.form.addRow("Terme additif",self.offset)
        self.scale.setEnabled(False);self.offset.setEnabled(False)
        self.metadata.toggled.connect(lambda checked:(self.scale.setEnabled(not checked),self.offset.setEnabled(not checked)))
        self.selection.itemChanged.connect(self.refresh);self.source.edit.textChanged.connect(self.refresh)
        self.refresh();self.finish()
    def selected(self):
        return [self.selection.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.selection.count())
                if self.selection.item(i).checkState()==Qt.CheckState.Checked]
    def refresh(self):
        old={self.bands.item(i,0).text():self.bands.cellWidget(i,1).value() for i in range(self.bands.rowCount())}
        if getattr(self,"_band_source",None)!=self.source.text():old={}
        self._band_source=self.source.text()
        definitions=[cm.get_index(name) for name in self.selected()];required=sorted(set().union(*(d.bands for d in definitions)))
        labels=[];count=999
        try:
            with rasterio.open(self.source.text()) as src:
                labels=[(d or src.tags(i).get("semantic_name","")).casefold() for i,d in enumerate(src.descriptions,1)];count=src.count
        except (OSError,rasterio.errors.RasterioError):pass
        self.bands.setRowCount(len(required))
        for row,name in enumerate(required):
            item=QTableWidgetItem(name);item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable);self.bands.setItem(row,0,item)
            matches=[i+1 for i,label in enumerate(labels) if label==name]
            field=spin(matches[0] if len(matches)==1 else old.get(name,0),0,count);field.setSpecialValueText("Non affectée")
            self.bands.setCellWidget(row,1,field)
        params=[(d.name,k,v) for d in definitions for k,v in d.parameters.items()]
        self.parameters.setRowCount(len(params));self.parameters.setVisible(bool(params))
        self.form.labelForField(self.parameters).setVisible(bool(params))
        for row,(name,param,value) in enumerate(params):
            for col,text in enumerate([name,param]):
                item=QTableWidgetItem(text);item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable);self.parameters.setItem(row,col,item)
            self.parameters.setCellWidget(row,2,real(value))
    def job(self,options):
        names=self.selected()
        if not names:raise ValueError("Sélectionner au moins un indice spectral.")
        mapping={self.bands.item(i,0).text():self.bands.cellWidget(i,1).value() for i in range(self.bands.rowCount())}
        if 0 in mapping.values():raise ValueError("Affecter un numéro à chaque bande spectrale requise.")
        params={}
        for i in range(self.parameters.rowCount()):params.setdefault(self.parameters.item(i,0).text(),{})[self.parameters.item(i,1).text()]=self.parameters.cellWidget(i,2).value()
        source=self.source.text();destination=self.destination()
        calibration={} if self.metadata.isChecked() else {"scale":self.scale.value(),"offset":self.offset.value()}
        return lambda progress,cancel:cm.spectral_indices(source,destination,names,band_map=mapping,parameters=params,
               progress=progress,cancel=cancel,**calibration,**options)


class CalculatorPage(Page):
    def __init__(self):
        super().__init__("Calculatrice raster","Algèbre locale, expressions conditionnelles, fonctions mathématiques et reclassification.")
        self.inputs=QTableWidget(0,5);self.inputs.setHorizontalHeaderLabels(["Variable","Fichier raster","Bande","Facteur","Décalage"])
        self.inputs.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        for col in [0,2,3,4]:self.inputs.setColumnWidth(col,90)
        self.inputs.setMinimumHeight(200);self.form.addRow(self.inputs)
        buttons=QWidget();row=QHBoxLayout(buttons);row.setContentsMargins(0,0,0,0)
        add=QPushButton("Importer des rasters");remove=QPushButton("Supprimer la sélection")
        row.addWidget(add);row.addWidget(remove);row.addStretch();self.form.addRow(buttons)
        add.clicked.connect(self.browse);remove.clicked.connect(self.remove)
        self.expression=QPlainTextEdit();self.expression.setPlaceholderText("(nir - red) / (nir + red)")
        self.expression.setMaximumHeight(115);self.form.addRow("Expression",self.expression)
        self.form.addRow(QLabel("Fonctions : where, coalesce, sqrt, log, exp, minimum, maximum, mean, median, std, bitand."))
        self.align=QCheckBox("Aligner les entrées sur la grille du premier raster");self.form.addRow("Grille",self.align)
        self.finish()
    def browse(self):
        paths=QFileDialog.getOpenFileNames(self,"Données raster",filter=RASTER_FILTER)[0]
        try:
            for path in paths:self.add_raster(path)
        except Exception as exc:QMessageBox.warning(self,"Importation raster",str(exc))
    def add_raster(self,path):
        with rasterio.open(path) as src:
            for index in range(1,src.count+1):
                row=self.inputs.rowCount();self.inputs.insertRow(row)
                alias=src.descriptions[index-1] or f"b{row+1}"
                existing={self.inputs.item(i,0).text() for i in range(row)}
                if not alias.isidentifier() or alias in existing:alias=f"b{row+1}"
                while alias in existing:alias+="_"
                self.inputs.setItem(row,0,QTableWidgetItem(alias));self.inputs.setItem(row,1,QTableWidgetItem(str(path)))
                self.inputs.setCellWidget(row,2,spin(index,1,src.count))
                self.inputs.setCellWidget(row,3,real(src.scales[index-1]));self.inputs.setCellWidget(row,4,real(src.offsets[index-1]))
    def remove(self):
        for row in sorted({i.row() for i in self.inputs.selectedIndexes()},reverse=True):self.inputs.removeRow(row)
    def job(self,options):
        inputs={}
        for i in range(self.inputs.rowCount()):
            name=self.inputs.item(i,0).text().strip()
            if name in inputs:raise ValueError("Les noms des variables doivent être uniques.")
            inputs[name]=cm.Band(self.inputs.item(i,1).text(),index=self.inputs.cellWidget(i,2).value(),
                                scale=self.inputs.cellWidget(i,3).value(),offset=self.inputs.cellWidget(i,4).value())
        expression=self.expression.toPlainText();destination=self.destination();align=self.align.isChecked()
        from .algebra import Expression
        Expression(expression)
        return lambda progress,cancel:cm.calculate(expression,inputs,destination,align=align,progress=progress,cancel=cancel,**options)


class FocalPage(Page):
    def __init__(self):
        super().__init__("Statistiques focales","Analyse du voisinage spatial par fenêtre mobile carrée.")
        self.source=PathField();self.band=spin();self.stat=QComboBox()
        for label,value in {**STATISTICS,"Étendue":"range"}.items():self.stat.addItem(label,value)
        self.size=spin(3,1,255);self.size.setSingleStep(2);self.minimum=spin(1,1,65025)
        self.preserve=QCheckBox("Conserver les pixels NoData au centre du voisinage");self.preserve.setChecked(True)
        for label,widget in [("Raster",self.source),("Bande",self.band),("Statistique",self.stat),
             ("Dimension de la fenêtre (pixels)",self.size),("Nombre minimal de voisins valides",self.minimum),("Masque",self.preserve)]:self.form.addRow(label,widget)
        self.finish()
    def job(self,options):
        kwargs=dict(source=self.source.text(),destination=self.destination(),band=self.band.value(),statistic=self.stat.currentData(),
                    size=self.size.value(),min_valid=self.minimum.value(),preserve_nodata=self.preserve.isChecked())
        return lambda progress,cancel:cm.focal(**kwargs,progress=progress,cancel=cancel,**options)


class TemporalPage(Page):
    def __init__(self):
        super().__init__("Statistiques multirasters","Synthèse pixel par pixel de rasters superposés ou d’une série temporelle.")
        self.sources=QListWidget();self.sources.setMinimumHeight(180);self.form.addRow("Rasters",self.sources)
        buttons=QWidget();row=QHBoxLayout(buttons);row.setContentsMargins(0,0,0,0)
        add=QPushButton("Importer des rasters");remove=QPushButton("Supprimer la sélection")
        row.addWidget(add);row.addWidget(remove);row.addStretch();self.form.addRow(buttons)
        self.sources.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        add.clicked.connect(lambda:self.sources.addItems(QFileDialog.getOpenFileNames(self,"Rasters",filter=RASTER_FILTER)[0]))
        remove.clicked.connect(lambda:[self.sources.takeItem(self.sources.row(i)) for i in self.sources.selectedItems()])
        self.band=spin();self.stat=QComboBox()
        for label,value in {**STATISTICS,"Médiane":"median"}.items():self.stat.addItem(label,value)
        self.minimum=spin();self.form.addRow("Bande",self.band);self.form.addRow("Statistique",self.stat)
        self.form.addRow("Nombre minimal d’observations",self.minimum);self.finish()
    def job(self,options):
        sources=[self.sources.item(i).text() for i in range(self.sources.count())]
        kwargs=dict(statistic=self.stat.currentData(),band=self.band.value(),min_valid=self.minimum.value())
        destination=self.destination()
        return lambda progress,cancel:cm.reduce_rasters(sources,destination,progress=progress,cancel=cancel,**kwargs,**options)


class PreparationPage(Page):
    engine=False
    def __init__(self):
        super().__init__("Prétraitement multispectral","Calibration radiométrique, masque de qualité, mosaïque, assemblage des bandes et extraction par masque.")
        self.source=PathField("directory");self.aoi=PathField(filter=VECTOR_FILTER);self.crs=QLineEdit()
        self.crs.setPlaceholderText("Exemple : EPSG:32733")
        self.bands=QLineEdit("blue,green,red,nir");self.resolution=spin(0,0,100000)
        self.resolution.setSpecialValueText("Résolution native la plus grossière")
        self.clouds=QCheckBox("Appliquer les masques QA/SCL disponibles");self.clouds.setChecked(True)
        self.dates=QCheckBox("Autoriser une mosaïque multitemporelle")
        for label,widget in [("Répertoire des scènes",self.source),("Zone d’étude",self.aoi),("Système de coordonnées cible",self.crs),
            ("Bandes spectrales",self.bands),("Résolution (m)",self.resolution),("Masque de qualité",self.clouds),("Dates d’acquisition",self.dates)]:self.form.addRow(label,widget)
        self.finish()
    def job(self,options):
        kwargs=dict(scenes=self.source.text(),destination=self.destination(),aoi=self.aoi.text() or None,
            target_crs=self.crs.text().strip() or None,band_order=[b.strip() for b in self.bands.text().split(",")],
            resolution=self.resolution.value() or None,mask_clouds=self.clouds.isChecked(),allow_mixed_dates=self.dates.isChecked(),overwrite=options["overwrite"])
        return lambda progress,cancel:cm.prepare_imagery(**kwargs,progress=progress,cancel=cancel).path


class MappingPage(Page):
    engine=False
    cancellable=False
    def __init__(self):
        super().__init__("Composition cartographique","Superposition des couches, symbologie, étiquetage et export de la mise en page.")
        self.layers=QTableWidget(0,3);self.layers.setHorizontalHeaderLabels(["Couche","Rôle cartographique","Champ d’étiquette"])
        self.layers.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        self.layers.setColumnWidth(1,180);self.layers.setMinimumHeight(190);self.form.addRow(self.layers)
        button=QPushButton("Importer des couches");self.form.addRow(button);button.clicked.connect(self.browse)
        remove=QPushButton("Supprimer la sélection");self.form.addRow(remove)
        remove.clicked.connect(lambda:[self.layers.removeRow(i) for i in sorted({x.row() for x in self.layers.selectedIndexes()},reverse=True)])
        self.title=QLineEdit();self.credits=QLineEdit();self.crs=QLineEdit();self.crs.setPlaceholderText("Exemple : EPSG:32733")
        self.aoi=PathField(filter=VECTOR_FILTER);self.rgb=QComboBox()
        for label,value in [("Couleurs naturelles","natural"),("Végétation","vegetation"),("Infrarouge à ondes courtes","swir"),("Agriculture","agriculture")]:self.rgb.addItem(label,value)
        self.dpi=spin(300,72,1200)
        for label,widget in [("Titre",self.title),("Sources et auteur",self.credits),("Système de coordonnées",self.crs),
             ("Zone d’étude",self.aoi),("Composition colorée",self.rgb),("Résolution d’export (ppp)",self.dpi)]:self.form.addRow(label,widget)
        self.output.filter="Document PDF (*.pdf);;Image PNG (*.png);;Image SVG (*.svg)";self.finish()
    def browse(self):
        paths=QFileDialog.getOpenFileNames(self,"Couches géographiques",filter="Données SIG (*.tif *.tiff *.jp2 *.vrt *.gpkg *.shp *.geojson)")[0]
        for path in paths:self.add_layer(path)
    def add_layer(self,path):
        row=self.layers.rowCount();self.layers.insertRow(row);self.layers.setItem(row,0,QTableWidgetItem(str(path)))
        roles=QComboBox();roles.addItem("Automatique",None)
        for label,value in ROLE_LABELS.items():roles.addItem(label,value)
        self.layers.setCellWidget(row,1,roles);self.layers.setItem(row,2,QTableWidgetItem(""))
    def job(self,options):
        layers=[];rgb=self.rgb.currentData()
        for row in range(self.layers.rowCount()):
            layers.append(dict(data=self.layers.item(row,0).text(),role=self.layers.cellWidget(row,1).currentData(),
                               labels=self.layers.item(row,2).text().strip() or None))
        if not layers:raise ValueError("Importer au moins une couche géographique.")
        destination=self.destination();aoi=self.aoi.text() or None
        kwargs=dict(title=self.title.text(),credits=self.credits.text(),crs=self.crs.text().strip() or None)
        dpi=self.dpi.value()
        def run(progress,cancel):
            for layer in layers:
                if Path(layer["data"]).suffix.lower() in {".tif",".tiff",".jp2",".vrt"}:
                    with rasterio.open(layer["data"]) as src:
                        if src.count>=3:layer["rgb"]="native" if src.dtypes[:3]==("uint8",)*3 and tuple(c.name for c in src.colorinterp[:3])==("red","green","blue") else rgb
            return cm.compose_map(layers,aoi=aoi,**kwargs).export(destination,dpi=dpi,overwrite=options["overwrite"])
        return run


class Worker(QThread):
    progress=Signal(int,int);succeeded=Signal(str);failed=Signal(str);cancelled=Signal()
    def __init__(self,job,event,parent=None):super().__init__(parent);self.job=job;self.cancel_event=event
    @Slot()
    def run(self):
        try:self.succeeded.emit(str(self.job(self.progress.emit,self.cancel_event)))
        except cm.ProcessingCancelled:self.cancelled.emit()
        except Exception as exc:self.failed.emit(str(exc))


class CartomizeWindow(QMainWindow):
    def __init__(self):
        super().__init__();self.setWindowTitle("Cartomize");self.resize(1160,900);self.setMinimumSize(880,650)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.thread=None;self.worker=None;self.cancel_event=None;self.output_path=None
        root=QWidget();self.setCentralWidget(root);outer=QVBoxLayout(root)
        header=QLabel("Cartomize");header.setObjectName("brand");outer.addWidget(header)
        body=QHBoxLayout();outer.addLayout(body,1)
        self.navigation=QListWidget();self.navigation.setFixedWidth(225);body.addWidget(self.navigation)
        self.stack=QStackedWidget();body.addWidget(self.stack,1)
        self.pages=[IndicesPage(),CalculatorPage(),FocalPage(),TemporalPage(),PreparationPage(),MappingPage()]
        for title,page in zip(["Indices spectraux","Calculatrice raster","Statistiques focales","Statistiques multirasters","Prétraitement multispectral","Composition cartographique"],self.pages):
            self.navigation.addItem(title);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page);self.stack.addWidget(scroll)
        self.navigation.currentRowChanged.connect(self.stack.setCurrentIndex);self.navigation.currentRowChanged.connect(self.page_changed)
        settings=QGroupBox("Paramètres de traitement");self.settings=settings;row=QHBoxLayout(settings)
        self.workers=spin(min(4,os.cpu_count() or 1),1,32);self.block_size=QComboBox();self.block_size.addItems(["256","512","1024","2048"]);self.block_size.setCurrentText("512")
        self.memory=spin(512,16,32768);self.memory.setSuffix(" Mio")
        self.overwrite=QCheckBox("Remplacer les fichiers existants")
        for label,widget in [("Threads de calcul",self.workers),("Bloc (pixels)",self.block_size),("Budget des tableaux",self.memory)]:row.addWidget(QLabel(label));row.addWidget(widget)
        row.addWidget(self.overwrite);outer.addWidget(settings)
        bottom=QHBoxLayout();self.run_button=QPushButton("Exécuter");self.run_button.setObjectName("primary")
        self.cancel_button=QPushButton("Annuler");self.cancel_button.setEnabled(False)
        self.folder_button=QPushButton("Ouvrir le répertoire de sortie");self.folder_button.setEnabled(False)
        bottom.addWidget(self.run_button);bottom.addWidget(self.cancel_button);bottom.addStretch();bottom.addWidget(self.folder_button);outer.addLayout(bottom)
        self.progress=QProgressBar();self.progress.setValue(0);outer.addWidget(self.progress)
        self.status=QLabel("Prêt.");self.status.setWordWrap(True);outer.addWidget(self.status)
        self.run_button.clicked.connect(self.start);self.cancel_button.clicked.connect(self.cancel)
        self.folder_button.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.output_path).resolve().parent))))
        self.navigation.setCurrentRow(0)
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #f5f7f7; color: #223b3d; font-size: 12px; }
            QLabel#brand { font-size: 25px; font-weight: 700; padding: 6px 4px 12px; }
            QLabel#pageTitle { font-size: 21px; font-weight: 600; padding-bottom: 5px; }
            QLabel#description { color: #536669; padding-bottom: 14px; }
            QLineEdit,QPlainTextEdit,QTableWidget,QListWidget,QComboBox,QSpinBox,QDoubleSpinBox { background: white; border: 1px solid #c4d0d0; border-radius: 3px; padding: 5px; }
            QListWidget::item { padding: 9px 4px; }
            QListWidget::item:selected { background: #d5e8e4; color: #163f39; }
            QPushButton { background: #e5edeb; border: 1px solid #b6c9c4; border-radius: 4px; padding: 8px 12px; }
            QPushButton#primary { background: #246858; color: white; border: none; min-width: 110px; }
            QPushButton:disabled { color: #8b9997; background: #edf0ef; }
            QGroupBox { border: 1px solid #c4d0d0; border-radius: 4px; margin-top: 15px; padding-top: 12px; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
            QProgressBar { border: 1px solid #c4d0d0; background: white; text-align: center; min-height: 16px; }
            QProgressBar::chunk { background: #70a797; }
        """)
    def page_changed(self,index):
        if index<0:return
        for widget in (self.workers,self.block_size,self.memory):widget.setEnabled(self.pages[index].engine)
    def start(self):
        if self.thread is not None:return
        options=dict(workers=self.workers.value(),block_size=int(self.block_size.currentText()),
                     memory_limit_mb=self.memory.value(),overwrite=self.overwrite.isChecked())
        try:job=self.pages[self.stack.currentIndex()].job(options)
        except Exception as exc:self.status.setText(str(exc));return
        self.cancel_event=threading.Event();self.worker=Worker(job,self.cancel_event,self);self.thread=self.worker
        self.worker.progress.connect(self.show_progress);self.worker.succeeded.connect(self.completed)
        self.worker.failed.connect(self.failed);self.worker.cancelled.connect(self.cancelled)
        self.thread.finished.connect(self.cleaned);self.thread.finished.connect(self.thread.deleteLater)
        self.run_button.setEnabled(False);self.navigation.setEnabled(False);self.stack.setEnabled(False);self.settings.setEnabled(False)
        self.cancel_button.setEnabled(self.pages[self.stack.currentIndex()].cancellable)
        self.folder_button.setEnabled(False);self.progress.setRange(0,0);self.status.setText("Traitement en cours.")
        self.thread.start()
    @Slot(int,int)
    def show_progress(self,done,total):self.progress.setRange(0,max(1,total));self.progress.setValue(done)
    @Slot(str)
    def completed(self,path):
        self.output_path=path;self.progress.setRange(0,100);self.progress.setValue(100)
        self.status.setText("Traitement terminé : "+path);self.folder_button.setEnabled(True)
    @Slot(str)
    def failed(self,error):self.progress.setRange(0,100);self.progress.setValue(0);self.status.setText("Échec du traitement : "+error)
    @Slot()
    def cancelled(self):self.progress.setRange(0,100);self.progress.setValue(0);self.status.setText("Traitement interrompu.")
    @Slot()
    def cleaned(self):
        self.thread=None;self.worker=None;self.run_button.setEnabled(True);self.navigation.setEnabled(True)
        self.stack.setEnabled(True);self.settings.setEnabled(True);self.page_changed(self.stack.currentIndex());self.cancel_button.setEnabled(False)
    def cancel(self):
        if self.cancel_event:self.cancel_event.set();self.cancel_button.setEnabled(False);self.status.setText("Interruption à la fin du bloc en cours.")
    def closeEvent(self,event):
        if self.thread is not None:
            self.cancel();self.status.setText("Attendre la fin du traitement avant de fermer la fenêtre.");event.ignore()
        else:event.accept()


_windows=[]


def launch(*,block=None):
    """Open a native window; reuse an existing QApplication when available."""
    application=QApplication.instance();owns_loop=application is None
    if application is None:application=QApplication(["Cartomize"])
    window=CartomizeWindow();_windows.append(window)
    window.destroyed.connect(lambda:_windows.remove(window) if window in _windows else None)
    window.show()
    # Keep the application alive when embedded without a running Qt event loop.
    window._application=application
    if block is True or (block is None and owns_loop):application.exec()
    return window


def main():
    launch();return 0


if __name__=="__main__":raise SystemExit(main())
