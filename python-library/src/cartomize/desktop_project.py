"""Project analysis and reversible cartographic preparation in the Qt window."""
from pathlib import Path
import json
import os
import tempfile
import numpy as np
from matplotlib.colors import is_color_like
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget,QHBoxLayout,QLabel,QLineEdit,QPushButton,
    QFileDialog,QTableWidget,QTableWidgetItem,QHeaderView,QCheckBox,QTabWidget)
from .desktop import Page,PathField
from . import prepare_project,load_project


def values(text):
    result=[float(v.strip()) for v in text.split(',') if v.strip()]
    if not all(np.isfinite(result)):raise ValueError('Saisir des valeurs finies séparées par des virgules.')
    return result


def fixed(text):
    item=QTableWidgetItem(str(text));item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable);return item


class ProjectPage(Page):
    engine=False
    staged=True
    applyRequested=Signal(object)
    def __init__(self):
        super().__init__('Analyse du projet','Diagnostic des couches, masquage du NoData, nomenclature et préparation de la symbologie.')
        self.project=None
        self.layers=QTableWidget(0,3)
        self.layers.setHorizontalHeaderLabels(['Couche','NoData supplémentaires','Valeurs à conserver'])
        self.layers.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        self.layers.setMinimumHeight(145);self.layers.setColumnWidth(1,165);self.layers.setColumnWidth(2,150)
        self.form.addRow(self.layers)
        buttons=QWidget();row=QHBoxLayout(buttons);row.setContentsMargins(0,0,0,0)
        add=QPushButton('Importer des couches');remove=QPushButton('Retirer');open_project=QPushButton('Ouvrir une analyse')
        row.addWidget(add);row.addWidget(remove);row.addWidget(open_project);row.addStretch()
        add.clicked.connect(self.browse);remove.clicked.connect(lambda:self.layers.removeRow(self.layers.currentRow()))
        open_project.clicked.connect(self.open_project);self.form.addRow(buttons)
        self.auto=QCheckBox('Détecter les valeurs de fond en périphérie');self.auto.setChecked(True);self.form.addRow(self.auto)
        note=QLabel('Les masques NoData déclarés sont conservés. Les fonds détectés sont masqués dans des copies. '
                    'Les rasters binaires 0/1 restent inchangés. Les valeurs supplémentaires s’appliquent à toute l’image ; séparer les codes par des virgules.')
        note.setWordWrap(True);self.form.addRow(note)
        self.footprint=PathField(filter='Emprise valide (*.gpkg *.geojson *.shp)');self.form.addRow('Emprise valide (facultatif)',self.footprint)
        self.directory=PathField('directory');self.name=QLineEdit('analyse_projet')
        self.form.addRow('Répertoire de sortie',self.directory);self.form.addRow('Nouveau répertoire de préparation',self.name)
        self.tabs=QTabWidget();self.report=QTableWidget(0,4)
        self.report.setHorizontalHeaderLabels(['Couche','Diagnostic','NoData ajoutés','Pixels masqués en plus'])
        self.report.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.classes=QTableWidget(0,4);self.classes.setHorizontalHeaderLabels(['Couche','Code','Libellé','Couleur'])
        self.classes.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.report,'Résultats');self.tabs.addTab(self.classes,'Nomenclature');self.form.addRow(self.tabs)
        self.summary=QLabel('Importer les couches, puis lancer l’analyse du projet.');self.summary.setWordWrap(True);self.form.addRow(self.summary)
        actions=QWidget();row=QHBoxLayout(actions);row.setContentsMargins(0,0,0,0)
        self.apply_button=QPushButton('Appliquer à la mise en page');self.restore_button=QPushButton('Rétablir les sources')
        row.addWidget(self.apply_button);row.addWidget(self.restore_button);row.addStretch()
        self.apply_button.setEnabled(False);self.restore_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply);self.restore_button.clicked.connect(self.restore)
        self.form.addRow(actions);self.layout.addStretch()
    def add_layer(self,path):
        row=self.layers.rowCount();self.layers.insertRow(row);self.layers.setItem(row,0,QTableWidgetItem(str(path)))
        self.layers.setItem(row,1,QTableWidgetItem(''));self.layers.setItem(row,2,QTableWidgetItem(''))
    def browse(self):
        for path in QFileDialog.getOpenFileNames(self,'Couches géographiques',filter='Données SIG (*.tif *.tiff *.jp2 *.vrt *.img *.gpkg *.shp *.geojson)')[0]:self.add_layer(path)
    def open_project(self):
        path=QFileDialog.getOpenFileName(self,'Analyse Cartomize',filter='Plan Cartomize (*.json)')[0]
        if path:
            try:self.show_result(path)
            except Exception as exc:self.summary.setText(str(exc))
    def job(self,options):
        layers=[dict(data=self.layers.item(row,0).text(),nodata_values=values(self.layers.item(row,1).text()),
                     keep_values=values(self.layers.item(row,2).text()),valid_footprint=self.footprint.text() or None) for row in range(self.layers.rowCount())]
        if not layers:raise ValueError('Importer au moins une couche géographique.')
        name=self.name.text().strip()
        if not self.directory.text():raise ValueError('Choisir un répertoire de sortie.')
        if not name or name in {'.','..'} or '/' in name or '\\' in name:raise ValueError('Saisir un nom de répertoire simple.')
        destination=Path(self.directory.text())/name;automatic=self.auto.isChecked()
        return lambda progress,cancel,stage:prepare_project(layers,destination,auto_background=automatic,
                                                           progress=progress,cancel=cancel,stage=stage).manifest
    def show_result(self,path):
        project=load_project(path);self.project=project;self.report.setRowCount(0);self.classes.setRowCount(0)
        generic=False;masked=0
        for number,record in enumerate(project.report['layers']):
            row=self.report.rowCount();self.report.insertRow(row)
            count=sum(record.get('mask_result',{}).get(k,0) for k in ('additional_border_masked','additional_value_masked','outside_footprint_masked'));masked+=count
            diagnosis='Raster binaire : 0 conservé' if record['diagnostic'].get('binary_zero_preserved') else 'Classes discrètes' if record.get('classes') else 'Raster multibande' if record['kind']=='raster' and record['diagnostic']['bands']>1 else 'Raster' if record['kind']=='raster' else 'Géométries et attributs'
            rules=[]
            for key,label in [('border_values','Bord'),('nodata_values','Global')]:
                if record.get(key):rules.append(label+' : '+', '.join(f'{v:g}' for v in record[key]))
            for col,text in enumerate([record['name'],diagnosis,' ; '.join(rules) or 'Aucun ajout',str(count)]):self.report.setItem(row,col,fixed(text))
            self.report.item(row,1).setToolTip('NoData déclarés : '+str(record['diagnostic'].get('declared_nodata','Sans objet')))
            for item in record.get('classes') or []:
                row=self.classes.rowCount();self.classes.insertRow(row)
                cell=fixed(record['name']);cell.setData(Qt.ItemDataRole.UserRole,number);self.classes.setItem(row,0,cell)
                code=fixed(f"{item['value']:g}");code.setData(Qt.ItemDataRole.UserRole,item['value']);self.classes.setItem(row,1,code)
                self.classes.setItem(row,2,QTableWidgetItem(item['label']));self.classes.setItem(row,3,QTableWidgetItem(item['color']))
                generic|=item['label_source']=='code'
        ambiguous=sum(bool(r['diagnostic'].get('decision_required')) and not r.get('valid_footprint') for r in project.report['layers'])
        self.summary.setText((f'{ambiguous} couche(s) : vérifier les valeurs de fond ou fournir une emprise valide. ' if ambiguous else '')+f'{len(project.layers)} couches analysées. {masked:,} pixels de fond supplémentaires masqués. Sources conservées.'+
                             (' Compléter les libellés des classes dans Nomenclature.' if generic else ''))
        self.apply_button.setEnabled(True);self.restore_button.setEnabled(True)
    def apply(self):
        if self.project is None:return
        try:
            # Validate all edits before changing the saved plan.
            report=json.loads(json.dumps(self.project.report));edits=[]
            for row in range(self.classes.rowCount()):
                index=self.classes.item(row,0).data(Qt.ItemDataRole.UserRole);value=self.classes.item(row,1).data(Qt.ItemDataRole.UserRole)
                label=self.classes.item(row,2).text().strip();color=self.classes.item(row,3).text().strip()
                if not label or not is_color_like(color):raise ValueError('Chaque classe nécessite un libellé et une couleur valide, par exemple #2e7d32.')
                edits.append((index,value,label,color))
            for index,value,label,color in edits:
                record=report['layers'][index];record['options']['classes'][str(float(value))]=[label,color]
                for item in record['classes']:
                    if item['value']==value:
                        if item['label']!=label:item['label_source']='user'
                        item.update(label=label,color=color)
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=self.project.directory,suffix='.json',delete=False) as handle:
                temporary=Path(handle.name);json.dump(report,handle,ensure_ascii=False,indent=2,allow_nan=False)
            try:os.replace(temporary,self.project.manifest)
            finally:temporary.unlink(missing_ok=True)
            self.project=load_project(self.project.manifest);self.applyRequested.emit(self.project.layers)
        except Exception as exc:self.summary.setText(str(exc))
    def restore(self):
        if self.project:self.applyRequested.emit(load_project(self.project.manifest,original_sources=True).layers)
