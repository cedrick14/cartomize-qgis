"""Optional Qt desktop application for Cartomize processing tools."""
from pathlib import Path
import os
import sys
import threading
import tempfile
from .desktop_connections import ProjectConnections
from .desktop_session import SessionControls

try:
    from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot, QUrl
    from PySide6.QtGui import QDesktopServices, QIcon, QPixmap, QColor, QPalette
    from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QHBoxLayout,QVBoxLayout,
        QFormLayout,QLabel,QLineEdit,QPushButton,QFileDialog,QListWidget,QListWidgetItem,
        QStackedWidget,QComboBox,QSpinBox,QDoubleSpinBox,QCheckBox,QPlainTextEdit,
        QTableWidget,QTableWidgetItem,QHeaderView,QProgressBar,QMessageBox,QGroupBox,QScrollArea,QTabWidget,QDialog)
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
        if self.mode=="directory":path=QFileDialog.getExistingDirectory(self,"Sélectionner un répertoire",self.edit.text())
        elif self.mode=="save":path=QFileDialog.getSaveFileName(self,"Fichier de sortie",self.edit.text(),self.filter)[0]
        else:path=QFileDialog.getOpenFileName(self,"Données d’entrée",self.edit.text(),self.filter)[0]
        if path:self.edit.setText(path)
    def text(self):return self.edit.text().strip()


def spin(value=1,minimum=1,maximum=999):
    widget=QSpinBox();widget.setRange(minimum,maximum);widget.setValue(value);return widget


def real(value=1.):
    widget=QDoubleSpinBox();widget.setDecimals(8);widget.setRange(-1e9,1e9);widget.setValue(value);return widget


class Page(QWidget):
    staged=False
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
        self.stat.currentIndexChanged.connect(self.stat_changed)
    def stat_changed(self):
        count=self.stat.currentData()=='count';self.minimum.setEnabled(not count)
        if count:self.minimum.setValue(1)
    def job(self,options):
        sources=[self.sources.item(i).text() for i in range(self.sources.count())]
        kwargs=dict(statistic=self.stat.currentData(),band=self.band.value(),min_valid=self.minimum.value())
        destination=self.destination()
        return lambda progress,cancel:cm.reduce_rasters(sources,destination,progress=progress,cancel=cancel,**kwargs,**options)


class MappingPage(Page):
    engine=False
    cancellable=False
    previewRequested=Signal()
    reviewRequested=Signal()
    atlasRequested=Signal(object)
    def __init__(self):
        super().__init__("Mise en page cartographique","Maquettes, cadres multiples, légende, échelle, orientation et exports PDF, PNG ou SVG.")
        self._analysis_overrides={}
        from .desktop_layout import LayoutSettings
        self.tabs=QTabWidget();self.form.addRow(self.tabs)
        self.layer_tab=QWidget();layer_form=QFormLayout(self.layer_tab);self.tabs.addTab(self.layer_tab,"Couches et symbologie")
        self.layers=QTableWidget(0,7);self.layers.setHorizontalHeaderLabels(["Couche","Rôle","Étiquettes","Champ thématique","Bande","Opacité","Palette"])
        self.layers.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        for col,width in [(1,135),(2,100),(3,125),(4,60),(5,70),(6,100)]:self.layers.setColumnWidth(col,width)
        self.layers.setMinimumHeight(190);layer_form.addRow(self.layers)
        buttons=QWidget();row=QHBoxLayout(buttons);row.setContentsMargins(0,0,0,0)
        button=QPushButton("Importer des couches…");remove=QPushButton("Supprimer la sélection")
        row.addWidget(button);row.addWidget(remove);row.addStretch();layer_form.addRow(buttons)
        button.clicked.connect(self.browse);remove.clicked.connect(lambda:[self.layers.removeRow(i) for i in sorted({x.row() for x in self.layers.selectedIndexes()},reverse=True)])
        self.crs=QLineEdit();self.crs.setPlaceholderText("Exemple : EPSG:32733")
        self.aoi=PathField(filter=VECTOR_FILTER);self.rgb=QComboBox();self.rgb.addItem("Bande unique (raster scientifique)",None)
        for label,value in [("Couleurs naturelles","natural"),("Végétation","vegetation"),("Infrarouge à ondes courtes","swir"),("Agriculture","agriculture")]:self.rgb.addItem(label,value)
        for label,widget in [("Système de coordonnées",self.crs),("Zone d’étude",self.aoi),("Composition colorée",self.rgb)]:layer_form.addRow(label,widget)
        self.title=QLineEdit();self.subtitle=QLineEdit();self.credits=QLineEdit();self.dpi=spin(300,72,1200)
        page=QWidget();form=QFormLayout(page);self.tabs.addTab(page,"Maquette et habillage")
        self.layout_settings=LayoutSettings()
        for label,widget in [("Titre",self.title),("Sous-titre",self.subtitle),("Sources et auteur",self.credits)]:form.addRow(label,widget)
        form.addRow(self.layout_settings)
        frames_tab=QWidget();form=QFormLayout(frames_tab);self.tabs.addTab(frames_tab,"Cadres et contenus")
        detail=QLabel("Les emprises utilisent le système de coordonnées de chaque cadre. Sans réglage, l’emprise et les couches de la carte sont utilisées.")
        detail.setWordWrap(True);form.addRow(detail);form.addRow(self.layout_settings.frames)
        form.addRow(QLabel("Contenus facultatifs des emplacements de la maquette : textes, tableaux CSV et graphiques."))
        form.addRow(self.layout_settings.elements)
        geometry_tab=QWidget();geometry_form=QVBoxLayout(geometry_tab);geometry_form.addWidget(self.layout_settings.items);self.tabs.addTab(geometry_tab,"Géométrie des éléments")
        self.output.filter="Document PDF (*.pdf);;Image PNG (*.png);;Image SVG (*.svg)"
        self.form.addRow("Résolution d’export (ppp)",self.dpi)
        self.preview_button=QPushButton("Aperçu cartographique");self.preview_button.clicked.connect(self.previewRequested.emit);self.form.addRow(self.preview_button)
        self.review_button=QPushButton('Contrôler la carte');self.review_button.clicked.connect(self.reviewRequested.emit);self.form.addRow(self.review_button)
        self.atlas_button=QPushButton('Préparer l’atlas');self.atlas_button.clicked.connect(self.request_atlas);self.form.addRow(self.atlas_button)
        self.finish();self.tabs.setCurrentIndex(1)
    def browse(self):
        for path in QFileDialog.getOpenFileNames(self,"Couches géographiques",filter="Données SIG (*.tif *.tiff *.jp2 *.vrt *.gpkg *.shp *.geojson)")[0]:self.add_layer(path)
    def add_layer(self,path):
        row=self.layers.rowCount();self.layers.insertRow(row);self.layers.setItem(row,0,QTableWidgetItem(str(path)))
        roles=QComboBox();roles.addItem("Automatique",None)
        for label,value in ROLE_LABELS.items():roles.addItem(label,value)
        self.layers.setCellWidget(row,1,roles);self.layers.setItem(row,2,QTableWidgetItem(""))
        if self.layers.columnCount()>3:
            self.layers.setItem(row,3,QTableWidgetItem(""));self.layers.setCellWidget(row,4,spin())
            opacity=spin(100,0,100);opacity.setSuffix(" %");self.layers.setCellWidget(row,5,opacity)
            palette=QComboBox();palette.addItems(["Greys","viridis","Greens","Blues","terrain","Set2","tab20"]);self.layers.setCellWidget(row,6,palette)
    def capture_map(self):
        layers=[]
        for row in range(self.layers.rowCount()):
            path=self.layers.item(row,0).text()
            layers.append(dict(self._analysis_overrides.get(path,{}),data=path,role=self.layers.cellWidget(row,1).currentData(),
                labels=self.layers.item(row,2).text().strip() or None,column=self.layers.item(row,3).text().strip() or None,
                band=self.layers.cellWidget(row,4).value(),alpha=self.layers.cellWidget(row,5).value()/100,cmap=self.layers.cellWidget(row,6).currentText()))
        if not layers:raise ValueError("Importer au moins une couche géographique dans Couches et symbologie.")
        return dict(layers=layers,rgb=self.rgb.currentData(),aoi=self.aoi.text() or None,
            options=dict(title=self.title.text(),subtitle=self.subtitle.text(),credits=self.credits.text(),crs=self.crs.text().strip() or None),
            layout=self.layout_settings.capture())
    def load_layers(self,layers):
        self.layers.setRowCount(0);self._analysis_overrides={}
        for layer in layers:self.append_layer(layer)
        self.tabs.setCurrentIndex(0)
    def append_layer(self,layer):
        layer=dict(layer)
        if layer.get('classes') and (layer.get('kind')=='raster' or Path(str(layer['data'])).suffix.lower() in {'.tif','.tiff','.jp2','.vrt','.img'}):layer['classes']={float(k):v for k,v in layer['classes'].items()}
        path=str(layer['data']);self.add_layer(path);row=self.layers.rowCount()-1
        self._analysis_overrides[path]={key:layer[key] for key in ('name','kind','classes','rgb','color','categorical','legend','zorder') if key in layer}
        role=self.layers.cellWidget(row,1);role.setCurrentIndex(max(0,role.findData(layer.get('role'))))
        self.layers.item(row,2).setText(layer.get('labels') or '');self.layers.item(row,3).setText(layer.get('column') or '')
        self.layers.cellWidget(row,4).setValue(layer.get('band',1));self.layers.cellWidget(row,5).setValue(round(100*layer.get('alpha',1)))
        palette=self.layers.cellWidget(row,6);cmap=layer.get('cmap','Greys')
        if palette.findText(cmap)<0:palette.addItem(cmap)
        palette.setCurrentText(cmap)
    def load_config(self,config):
        self.load_layers(config['layers']);self.rgb.setCurrentIndex(max(0,self.rgb.findData(config['rgb'])))
        self.aoi.edit.setText(config['aoi'] or '')
        for key in ('title','subtitle','credits','crs'):getattr(self,key).setText(config['options'].get(key) or '')
        self.layout_settings.restore(config['layout'])
    def request_atlas(self):
        try:self.atlasRequested.emit(self.capture_map())
        except ValueError as exc:QMessageBox.warning(self,'Atlas cartographique',str(exc))
    def review_job(self,path):
        from .desktop_tools import write_result
        config=self.capture_map()
        return lambda progress,cancel:write_result(self.build_map(config).audit(visual=True),path,overwrite=True)
    @staticmethod
    def build_map(config):
        from .desktop_layout import apply_layout
        layers=[dict(layer) for layer in config["layers"]]
        for layer in layers:
            if Path(layer["data"]).suffix.lower() in {".tif",".tiff",".jp2",".vrt",".img"}:
                with rasterio.open(layer["data"]) as src:
                    if src.count>=3 and config["rgb"] is not None:layer["rgb"]="native" if src.dtypes[:3]==("uint8",)*3 and tuple(c.name for c in src.colorinterp[:3])==("red","green","blue") else config["rgb"]
        settings=config["layout"];options={**config["options"],**{k:settings[k] for k in ("template","format","orientation")}}
        return apply_layout(cm.compose_map(layers,aoi=config["aoi"],**options),settings)
    def job(self,options):
        config=self.capture_map();destination=self.destination();dpi=self.dpi.value()
        return lambda progress,cancel:self.build_map(config).export(destination,dpi=dpi,overwrite=options["overwrite"])
    def preview_job(self,path):
        config=self.capture_map()
        return lambda progress,cancel:self.build_map(config).export(path,dpi=100,overwrite=True)


class AtlasPage(MappingPage):
    cancellable=True
    def __init__(self):
        super().__init__();self.findChild(QLabel,"pageTitle").setText("Atlas cartographique")
        self.atlas_button.hide()
        self.findChild(QLabel,"description").setText("Production d’une carte par entité de la couche d’index, avec maquette et habillage communs.")
        tab=QWidget();form=QFormLayout(tab);self.tabs.insertTab(0,tab,"Index de l’atlas")
        self.zones=PathField(filter=VECTOR_FILTER);self.name_column=QLineEdit();self.name_column.setPlaceholderText("Exemple : nom")
        self.atlas_format=QComboBox();self.atlas_format.addItems(["pdf","png","svg"])
        self.padding=spin(8,0,100);self.padding.setSuffix(" %")
        for label,widget in [("Couche d’index",self.zones),("Champ du nom des pages",self.name_column),("Format d’export",self.atlas_format),("Marge autour des entités",self.padding)]:form.addRow(label,widget)
        detail=QLabel("Chaque entité définit l’emprise principale d’une page. Les cadres ayant une emprise explicite conservent leur cadrage.")
        detail.setWordWrap(True);form.addRow(detail)
        self.output.mode="directory";self.form.labelForField(self.output).setText("Répertoire de sortie")
        self.tabs.setCurrentIndex(0)
    def job(self,options):
        config=self.capture_map();directory=Path(self.destination());zones=self.zones.text();field=self.name_column.text().strip()
        if not zones or not field:raise ValueError("Renseigner la couche d’index et le champ du nom des pages.")
        kwargs=dict(name_column=field,format=self.atlas_format.currentText(),dpi=self.dpi.value(),padding=self.padding.value()/100,overwrite=options["overwrite"])
        def run(progress,cancel):
            paths=cm.atlas(self.build_map(config),zones,directory,progress=progress,cancel=cancel,**kwargs)
            if not paths:raise ValueError("La couche d’index ne contient aucune entité.")
            return paths[0]
        return run


class WorkflowPage(Page):
    engine=False
    staged=True
    def __init__(self):
        super().__init__("Production cartographique automatisée",
            "Des scènes satellites à la carte : traitement multispectral, superposition des couches et mise en page.")
        sequence=QLabel("01  Scènes satellites     →     02  Mosaïque     →     03  Composite multibande\n"
                        "04  Extraction par masque     →     05  Composition colorée     →     06  Mise en page")
        sequence.setObjectName("sequence");sequence.setWordWrap(True);self.form.addRow(sequence)
        tabs=QTabWidget();self.tabs=tabs;self.form.addRow(tabs)
        self.data_tab=QWidget();data=QFormLayout(self.data_tab);tabs.addTab(self.data_tab,"Données")
        self.source=PathField("directory");data.addRow("Répertoire des scènes",self.source)
        self.files=[];selection=QWidget();buttons=QHBoxLayout(selection);buttons.setContentsMargins(0,0,0,0)
        select=QPushButton("Sélectionner les bandes…");clear=QPushButton("Utiliser le répertoire")
        buttons.addWidget(select);buttons.addWidget(clear);buttons.addStretch();data.addRow(selection)
        self.inventory=QLabel("Landsat Collection 2 L2 · Sentinel-2 L2A");self.inventory.setObjectName("muted")
        self.inventory.setWordWrap(True);data.addRow(self.inventory)
        select.clicked.connect(self.select_files);clear.clicked.connect(self.clear_files)
        self.aoi=PathField(filter=VECTOR_FILTER);data.addRow("Zone d’étude",self.aoi)
        self.layers=QTableWidget(0,3);self.layers.setHorizontalHeaderLabels(["Couche vectorielle","Rôle cartographique","Champ d’étiquette"])
        self.layers.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        self.layers.setColumnWidth(1,180);self.layers.setColumnWidth(2,165);self.layers.setMaximumHeight(130);self.layers.setMinimumHeight(110)
        self.layers.setToolTip("Rôle automatique selon le nom et la géométrie. Vérifier les rôles avant la production.")
        data.addRow("Couches à superposer",self.layers)
        controls=QWidget();row=QHBoxLayout(controls);row.setContentsMargins(0,0,0,0)
        add=QPushButton("Importer des couches…");remove=QPushButton("Supprimer la sélection")
        row.addWidget(add);row.addWidget(remove);row.addStretch();data.addRow(controls)
        add.clicked.connect(self.browse_layers)
        remove.clicked.connect(lambda:[self.layers.removeRow(i) for i in sorted({x.row() for x in self.layers.selectedIndexes()},reverse=True)])
        prep=QWidget();form=QFormLayout(prep);tabs.addTab(prep,"Prétraitement")
        self.crs=QLineEdit();self.crs.setPlaceholderText("Automatique selon les scènes · exemple : EPSG:32733")
        self.bands=QLineEdit("blue, green, red, nir")
        self.resolution=spin(0,0,100000);self.resolution.setSpecialValueText("Résolution native la plus grossière")
        self.clouds=QCheckBox("Appliquer les masques QA/SCL");self.clouds.setChecked(True)
        self.dates=QCheckBox("Autoriser une mosaïque multitemporelle")
        for label,widget in [("Système de coordonnées cible",self.crs),("Bandes spectrales",self.bands),
            ("Résolution (m)",self.resolution),("Masque de qualité",self.clouds),("Dates d’acquisition",self.dates)]:form.addRow(label,widget)
        note=QLabel("Calibration radiométrique et masque de qualité avant rééchantillonnage. Les scènes sont alignées sur une grille commune. Les bandes nécessaires à la composition colorée sont ajoutées à la sélection.")
        note.setWordWrap(True);note.setObjectName("muted");form.addRow(note)
        output=QWidget();form=QFormLayout(output);tabs.addTab(output,"Restitution cartographique")
        self.title=QLineEdit();self.subtitle=QLineEdit();self.credits=QLineEdit();self.rgb=QComboBox()
        for label,value in [("Couleurs naturelles","natural"),("Infrarouge proche — végétation","vegetation"),
            ("Infrarouge à ondes courtes","swir"),("Agriculture","agriculture")]:self.rgb.addItem(label,value)
        self.format=QComboBox()
        for label,value in [("PDF et PNG",("pdf","png")),("PDF",("pdf",)),("PNG",("png",)),("SVG",("svg",))]:self.format.addItem(label,value)
        self.dpi=spin(300,72,1200)
        for label,widget in [("Composition colorée",self.rgb),("Titre de la carte",self.title),
            ("Sous-titre",self.subtitle),("Sources et auteur",self.credits),("Format d’export",self.format),("Résolution d’export (ppp)",self.dpi)]:form.addRow(label,widget)
        from .desktop_layout import LayoutSettings
        self.layout_settings=LayoutSettings(compact=True);form.addRow(self.layout_settings)
        note=QLabel("Ordre des couches selon leur rôle cartographique ; reprojection, découpage vectoriel, légende, échelle et orientation intégrés à la mise en page.")
        note.setWordWrap(True);note.setObjectName("muted");form.addRow(note)
        self.directory=PathField("directory");self.project=QLineEdit("production_cartographique")
        self.form.addRow("Répertoire de sortie",self.directory);self.form.addRow("Nom de la production",self.project)
        products=QLabel("Produits : GeoTIFF multibande · composition colorée · carte PDF/PNG · rapport de traitement")
        products.setWordWrap(True);products.setObjectName("muted");self.form.addRow(products)
        self.layout.addStretch()
    def select_files(self):
        paths=QFileDialog.getOpenFileNames(self,"Bandes spectrales et masques de qualité",filter=RASTER_FILTER)[0]
        if paths:
            self.files=paths;self.source.setEnabled(False)
            self.inventory.setText(f"{len(paths)} fichiers sélectionnés — inclure les bandes et les masques QA/SCL.")
    def clear_files(self):
        self.files=[];self.source.setEnabled(True);self.inventory.setText("Landsat Collection 2 L2 · Sentinel-2 L2A")
    def browse_layers(self):
        for path in QFileDialog.getOpenFileNames(self,"Couches vectorielles",filter=VECTOR_FILTER)[0]:self.add_layer(path)
    def add_layer(self,path):
        MappingPage.add_layer(self,path)
    def job(self,options):
        source=list(self.files) if self.files else self.source.text()
        if not source:raise ValueError("Sélectionner un répertoire de scènes ou des bandes spectrales.")
        name=self.project.text().strip()
        if not name or name in {".",".."} or any(c in name for c in '/\\:*?"<>|'):
            raise ValueError("Renseigner un nom de production sans séparateur de chemin.")
        if not self.directory.text():raise ValueError("Sélectionner le répertoire de sortie.")
        destination=Path(self.directory.text())/name
        if destination.exists():raise ValueError("Ce nom de production existe déjà. Choisir un nouveau nom.")
        layers=[dict(data=self.layers.item(i,0).text(),role=self.layers.cellWidget(i,1).currentData(),
                     labels=self.layers.item(i,2).text().strip() or None) for i in range(self.layers.rowCount())]
        layout=self.layout_settings.capture()
        kwargs=dict(layers=layers,aoi=self.aoi.text() or None,band_order=[b.strip() for b in self.bands.text().split(",") if b.strip()],
            target_crs=self.crs.text().strip() or None,resolution=self.resolution.value() or None,
            mask_clouds=self.clouds.isChecked(),allow_mixed_dates=self.dates.isChecked(),composition=self.rgb.currentData(),
            title=self.title.text(),credits=self.credits.text(),formats=self.format.currentData(),dpi=self.dpi.value(),
            template=layout["template"],page_format=layout["format"],orientation=layout["orientation"],subtitle=self.subtitle.text(),
            legend=layout["legend"],scale_bar=layout["scale"],north_arrow=layout["north"])
        self.result_map_config=dict(layers=layers,rgb=None,aoi=kwargs['aoi'],layout=layout,
            options=dict(title=kwargs['title'],subtitle=kwargs['subtitle'],credits=kwargs['credits'],crs=kwargs['target_crs']))
        return lambda progress,cancel,stage:cm.cartographic_workflow(source,destination,progress=progress,cancel=cancel,stage=stage,**kwargs).manifest


class CompositePage(Page):
    engine=False
    def __init__(self):
        super().__init__("Composition colorée","Affectation des bandes aux canaux rouge, vert et bleu et étirement radiométrique pour la visualisation.")
        self.source=PathField();self.rgb=QComboBox()
        for label,value in [("Couleurs naturelles","natural"),("Végétation","vegetation"),("Infrarouge à ondes courtes","swir"),("Agriculture","agriculture")]:self.rgb.addItem(label,value)
        self.form.addRow("Composite multibande",self.source);self.form.addRow("Composition colorée",self.rgb)
        note=QLabel("Le GeoTIFF de visualisation est enregistré séparément. Le composite multibande conserve ses valeurs de réflectance.")
        note.setWordWrap(True);self.form.addRow(note);self.finish()
    def job(self,options):
        source=self.source.text();destination=self.destination();bands=self.rgb.currentData()
        return lambda progress,cancel:cm.color_composite(source,destination,bands=bands,progress=progress,cancel=cancel,overwrite=options["overwrite"])


class Worker(QThread):
    progress=Signal(int,int);succeeded=Signal(str);failed=Signal(str);cancelled=Signal();stage=Signal(str)
    def __init__(self,job,event,parent=None,staged=False):super().__init__(parent);self.job=job;self.cancel_event=event;self.staged=staged
    @Slot()
    def run(self):
        try:
            args=(self.progress.emit,self.cancel_event,self.stage.emit) if self.staged else (self.progress.emit,self.cancel_event)
            self.succeeded.emit(str(self.job(*args)))
        except cm.ProcessingCancelled:self.cancelled.emit()
        except Exception as exc:self.failed.emit(str(exc))


class CartomizeWindow(SessionControls,ProjectConnections,QMainWindow):
    def __init__(self):
        super().__init__();self.setWindowTitle("Cartomize");self.resize(1220,940);self.setMinimumSize(980,700)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.thread=None;self.worker=None;self.cancel_event=None;self.output_path=None
        self._preview_target=None;self._preview_directory=tempfile.TemporaryDirectory(prefix="cartomize-preview-")
        palette=self.palette()
        for role,color in [(QPalette.ColorRole.Window,"#f7f7f7"),(QPalette.ColorRole.WindowText,"#111111"),
            (QPalette.ColorRole.Base,"#ffffff"),(QPalette.ColorRole.Text,"#111111"),(QPalette.ColorRole.ButtonText,"#111111"),
            (QPalette.ColorRole.Highlight,"#333333"),(QPalette.ColorRole.HighlightedText,"#ffffff"),
            (QPalette.ColorRole.Link,"#111111"),(QPalette.ColorRole.LinkVisited,"#444444"),(QPalette.ColorRole.Accent,"#333333")]:palette.setColor(role,QColor(color))
        self.setPalette(palette)
        root=QWidget();self.setCentralWidget(root);outer=QVBoxLayout(root)
        outer.setContentsMargins(20,14,20,14);outer.setSpacing(12)
        header=QHBoxLayout();icon_path=Path(__file__).parent/"assets"/"cartomize.png"
        icon=QPixmap(str(icon_path));self.setWindowIcon(QIcon(icon));self.brand_icon=QLabel()
        ratio=self.devicePixelRatioF();pixmap=icon.scaled(round(52*ratio),round(52*ratio),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
        pixmap.setDevicePixelRatio(ratio);self.brand_icon.setPixmap(pixmap);self.brand_icon.setFixedSize(58,58)
        header.addWidget(self.brand_icon);identity=QVBoxLayout();identity.setSpacing(1)
        brand=QLabel("Cartomize");brand.setObjectName("brand");identity.addWidget(brand)
        subtitle=QLabel("Assistant cartographique intelligent");subtitle.setObjectName("muted");identity.addWidget(subtitle)
        header.addLayout(identity);header.addStretch();version=QLabel(cm.__version__);version.setObjectName("muted");header.addWidget(version);outer.addLayout(header)
        session_bar=QHBoxLayout();self.init_session(session_bar);session_bar.addStretch();outer.addLayout(session_bar)
        body=QHBoxLayout();outer.addLayout(body,1)
        self.navigation=QListWidget();self.navigation.setFixedWidth(245);self.navigation.setObjectName("navigation");body.addWidget(self.navigation)
        self.stack=QStackedWidget();body.addWidget(self.stack,1)
        from .desktop_tools import InspectionPage,VectorPage,RasterToolsPage
        from .desktop_project import ProjectPage
        from .desktop_assistant import AssistantPage
        from .desktop_classification import ClassificationPage
        from .desktop_recipes import RecipesPage
        from .desktop_native import NativePage
        from .desktop_mapops import MapOpsPage
        from .desktop_terrain import TerrainPage
        from .assistant import TOOL_LABELS
        from .desktop_processing import ProcessingPage
        from .desktop_imagery import PreparationPage
        self.tool_pages=dict(assistant=AssistantPage(self._preview_directory.name),project=ProjectPage(),inspect=InspectionPage(),
            prepare=PreparationPage(),composite=CompositePage(),classification=ClassificationPage(),vector=VectorPage(),raster=RasterToolsPage(),terrain=TerrainPage(),indices=IndicesPage(),
            calculator=CalculatorPage(),focal=FocalPage(),temporal=TemporalPage(),mapping=MappingPage(),atlas=AtlasPage(),workflow=WorkflowPage(),processing=ProcessingPage(),recipes=RecipesPage(self),native=NativePage(self._preview_directory.name),mapops=MapOpsPage(self))
        self.pages=list(self.tool_pages.values());titles=['Assistant cartographique' if key=='assistant' else TOOL_LABELS[key] for key in self.tool_pages]
        for title,page in zip(titles,self.pages):
            self.navigation.addItem(title);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page);self.stack.addWidget(scroll)
            if isinstance(page,MappingPage):
                page.previewRequested.connect(lambda:self.start(preview=True));page.reviewRequested.connect(lambda:self.start(review=True))
                page.atlasRequested.connect(self.prepare_atlas)
            if isinstance(page,ProjectPage):page.applyRequested.connect(self.apply_project)
        self.tool('native').layersRequested.connect(self.apply_project)
        self.tool('assistant').openRequested.connect(self.open_assistant_step)
        self.tool('assistant').planRequested.connect(lambda:self.start(proposal=True))
        self.tool('assistant').executeRequested.connect(lambda:self.start(execute_plan=True))
        self.navigation.currentRowChanged.connect(self.stack.setCurrentIndex);self.navigation.currentRowChanged.connect(self.page_changed)
        settings=QGroupBox("Paramètres de traitement");self.settings=settings;row=QHBoxLayout(settings)
        self.workers=spin(min(4,os.cpu_count() or 1),1,32);self.block_size=QComboBox();self.block_size.addItems(["256","512","1024","2048"]);self.block_size.setCurrentText("512")
        self.memory=spin(512,16,32768);self.memory.setSuffix(" Mio")
        self.overwrite=QCheckBox("Remplacer les fichiers existants")
        self.engine_labels=[]
        for label,widget in [("Threads de calcul",self.workers),("Bloc (pixels)",self.block_size),("Budget des tableaux",self.memory)]:
            caption=QLabel(label);self.engine_labels.append(caption);row.addWidget(caption);row.addWidget(widget)
        row.addWidget(self.overwrite);outer.addWidget(settings)
        from .desktop_execution import ExecutionSettings
        self.execution_settings=ExecutionSettings();outer.addWidget(self.execution_settings)
        self.init_results(outer)
        bottom=QHBoxLayout();self.run_button=QPushButton("Exécuter");self.run_button.setObjectName("primary")
        self.cancel_button=QPushButton("Annuler");self.cancel_button.setEnabled(False)
        self.folder_button=QPushButton("Ouvrir le répertoire de sortie");self.folder_button.setEnabled(False)
        bottom.addWidget(self.run_button);bottom.addWidget(self.cancel_button);bottom.addStretch();bottom.addWidget(self.folder_button);outer.addLayout(bottom)
        self.progress=QProgressBar();self.progress.setValue(0);outer.addWidget(self.progress)
        self.status=QLabel("Prêt.");self.status.setWordWrap(True);outer.addWidget(self.status)
        self.run_button.clicked.connect(self.start);self.cancel_button.clicked.connect(self.cancel)
        self.folder_button.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.output_path).resolve().parent))))
        self.navigation.setCurrentRow(0)
        self.checkpoint()
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #f7f7f7; color: #111111; font-size: 12px; }
            QLabel#brand { color: #000000; font-size: 26px; font-weight: 700; }
            QLabel#pageTitle { color: #000000; font-size: 21px; font-weight: 600; padding-bottom: 4px; }
            QLabel#description { color: #555555; padding-bottom: 8px; }
            QLabel#muted { color: #555555; }
            QLabel#sequence { background: #eeeeee; color: #000000; border: 1px solid #dddddd; border-radius: 4px; padding: 12px; margin-bottom: 8px; line-height: 1.6; }
            QLineEdit,QPlainTextEdit,QTableWidget,QListWidget,QComboBox,QSpinBox,QDoubleSpinBox { background: white; border: 1px solid #cccccc; border-radius: 3px; padding: 5px; selection-background-color: #222222; }
            QLineEdit:focus,QPlainTextEdit:focus { border-color: #222222; }
            QListWidget#navigation { border: 0; background: #eeeeee; padding: 8px; }
            QListWidget::item { padding: 10px 6px; }
            QListWidget::item:selected { background: #dddddd; color: #000000; border-radius: 3px; }
            QPushButton { background: white; border: 1px solid #cccccc; border-radius: 4px; padding: 8px 12px; }
            QPushButton:hover { border-color: #222222; }
            QPushButton#primary { background: #222222; color: white; border: none; min-width: 150px; font-weight: 600; }
            QPushButton:disabled { color: #999999; background: #eeeeee; }
            QGroupBox { border: 1px solid #cccccc; border-radius: 4px; margin-top: 15px; padding-top: 12px; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
            QProgressBar { border: 1px solid #cccccc; background: white; text-align: center; min-height: 16px; }
            QProgressBar::chunk { background: #bbbbbb; }
            QScrollArea { border: none; }
            QTabWidget::pane { border: 1px solid #dddddd; padding: 10px; }
            QTabBar::tab { background: #eeeeee; padding: 10px 14px; border-bottom: 2px solid transparent; }
            QTabBar::tab:selected { color: #000000; background: #f7f7f7; border-bottom: 2px solid #222222; }
            QHeaderView::section { background: #eeeeee; border: none; border-bottom: 1px solid #cccccc; padding: 6px; }
        """)
    def page_changed(self,index):
        if index<0:return
        page=self.pages[index]
        key=next(k for k,v in self.tool_pages.items() if v is page)
        self.execution_settings.setVisible(key in {'calculator','indices','temporal','focal','terrain','processing'})
        self.execution_settings.device.setEnabled(key in {'calculator','indices','temporal','processing'})
        for widget in (*self.engine_labels,self.workers,self.block_size,self.memory):widget.setVisible(page.engine)
        from .desktop_project import ProjectPage
        from .desktop_assistant import AssistantPage
        self.settings.setVisible(key not in {'workflow','project','assistant','prepare'})
        self.settings.setTitle("Paramètres de traitement" if page.engine else "")
        self.settings.setStyleSheet("" if page.engine else "QGroupBox { border: none; margin-top: 0px; padding-top: 0px; }")
        self.run_button.setText("Exécuter la chaîne" if isinstance(page,WorkflowPage) else "Analyser le projet" if isinstance(page,ProjectPage) else "Produire l’atlas" if isinstance(page,AtlasPage) else "Exporter la carte" if isinstance(page,MappingPage) else "Exécuter")
        if isinstance(page,AssistantPage):self.run_button.setText('Examiner les données')
    def apply_project(self,layers):
        self.checkpoint()
        for layer in layers:self.register_result(layer)
        page=next(page for page in self.pages if type(page) is MappingPage)
        page.load_layers(layers);self.navigation.setCurrentRow(self.pages.index(page))
        assessment=self.tool('assistant').assessment
        if assessment and not page.title.text():self.open_assistant_step('mapping',assessment)
        self.status.setText('Couches et symbologie appliquées à la mise en page.')
    def start(self,checked=False,*,preview=False,review=False,proposal=False,execute_plan=False):
        if self.thread is not None:return
        self.checkpoint()
        options=dict(workers=self.workers.value(),block_size=int(self.block_size.currentText()),
                     memory_limit_mb=self.memory.value(),overwrite=self.overwrite.isChecked())
        page=self.pages[self.stack.currentIndex()]
        key=next(k for k,v in self.tool_pages.items() if v is page)
        if key in {'calculator','indices','temporal','focal','terrain','processing'}:
            options.update(self.execution_settings.parameters(gpu=key in {'calculator','indices','temporal','processing'}))
        self._preview_target=None;self._reviewing=review
        try:
            if proposal:job=page.plan_job()
            elif execute_plan:job=page.execution_job(options)
            elif preview:
                self._preview_target=Path(self._preview_directory.name)/"apercu.png"
                job=page.preview_job(self._preview_target)
            elif review:job=page.review_job(Path(self._preview_directory.name)/'controle.json')
            else:job=page.job(options)
        except Exception as exc:self.status.setText(str(exc));return
        self.cancel_event=threading.Event();self.worker=Worker(job,self.cancel_event,self,staged=execute_plan or self.pages[self.stack.currentIndex()].staged);self.thread=self.worker
        self.worker.progress.connect(self.show_progress);self.worker.stage.connect(self.status.setText);self.worker.succeeded.connect(self.completed)
        self.worker.failed.connect(self.failed);self.worker.cancelled.connect(self.cancelled)
        self.thread.finished.connect(self.cleaned);self.thread.finished.connect(self.thread.deleteLater)
        self.run_button.setEnabled(False);self.navigation.setEnabled(False);self.stack.setEnabled(False);self.settings.setEnabled(False)
        self.results_box.setEnabled(False)
        self.cancel_button.setEnabled(page.cancellable and not preview and not review)
        self.folder_button.setEnabled(False);self.progress.setRange(0,0);self.status.setText("Traitement en cours.")
        self.thread.start()
    @Slot(int,int)
    def show_progress(self,done,total):self.progress.setRange(0,max(1,total));self.progress.setValue(done)
    @Slot(str)
    def completed(self,path):
        self.output_path=path;self.progress.setRange(0,100);self.progress.setValue(100)
        if self._preview_target is not None:
            dialog=QDialog(self);dialog.setWindowTitle("Aperçu cartographique");layout=QVBoxLayout(dialog);label=QLabel()
            pixmap=QPixmap(path);label.setPixmap(pixmap.scaled(1050,760,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
            layout.addWidget(label);dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose);dialog.show();self.preview_dialog=dialog
            self.status.setText("Aperçu cartographique actualisé.")
        elif self._reviewing:self.show_review(path)
        else:
            self.status.setText("Traitement terminé : "+path);self.folder_button.setEnabled(True)
            page=self.pages[self.stack.currentIndex()]
            if hasattr(page,"show_result"):page.show_result(path)
            self.collect_result(path)
    @Slot(str)
    def failed(self,error):self.progress.setRange(0,100);self.progress.setValue(0);self.status.setText("Échec du traitement : "+error)
    @Slot()
    def cancelled(self):self.progress.setRange(0,100);self.progress.setValue(0);self.status.setText("Traitement interrompu.")
    @Slot()
    def cleaned(self):
        self.thread=None;self.worker=None;self.run_button.setEnabled(True);self.navigation.setEnabled(True)
        self.results_box.setEnabled(True)
        self.stack.setEnabled(True);self.settings.setEnabled(True);self.page_changed(self.stack.currentIndex());self.cancel_button.setEnabled(False)
    def cancel(self):
        if self.cancel_event:self.cancel_event.set();self.cancel_button.setEnabled(False);self.status.setText("Interruption à la fin du bloc ou de l’export en cours.")
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
