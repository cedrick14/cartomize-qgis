"""Cartographer's starting point: inspect data, explain and open next steps."""
import json
from pathlib import Path
from PySide6.QtCore import Signal,Qt
from PySide6.QtWidgets import (QWidget,QHBoxLayout,QComboBox,QListWidget,QPushButton,
    QFileDialog,QLineEdit,QLabel,QTableWidget,QTableWidgetItem,QHeaderView)
from .desktop import Page,PathField,VECTOR_FILTER
from .assistant import assess_project,GOALS


class AssistantPage(Page):
    engine=False
    openRequested=Signal(str,object)
    def __init__(self,directory):
        super().__init__('Assistant cartographique','Définir la carte, examiner les données et suivre les étapes adaptées au projet.')
        self.directory=Path(directory);self.assessment=None
        self.goal=QComboBox()
        for value,label in GOALS.items():self.goal.addItem(label,value)
        self.kind=QComboBox();self.kind.addItem('Couches raster et vectorielles','layers');self.kind.addItem('Scènes satellites et bandes','scenes')
        self.title=QLineEdit();self.aoi=PathField(filter=VECTOR_FILTER)
        self.inputs=QListWidget();self.inputs.setMinimumHeight(100);self.inputs.setMaximumHeight(160)
        self.form.addRow('Objectif',self.goal);self.form.addRow('Données disponibles',self.kind);self.form.addRow('Titre de la carte',self.title)
        self.form.addRow('Zone d’étude',self.aoi);self.form.addRow(self.inputs)
        controls=QWidget();row=QHBoxLayout(controls);row.setContentsMargins(0,0,0,0)
        files=QPushButton('Importer des fichiers');folder=QPushButton('Répertoire de scènes');remove=QPushButton('Retirer')
        row.addWidget(files);row.addWidget(folder);row.addWidget(remove);row.addStretch();self.form.addRow(controls)
        files.clicked.connect(self.add_files);folder.clicked.connect(self.add_folder);remove.clicked.connect(lambda:self.inputs.takeItem(self.inputs.currentRow()))
        self.findings=QLabel('L’examen ne modifie pas les données.');self.findings.setWordWrap(True);self.form.addRow(self.findings)
        self.steps=QTableWidget(0,2);self.steps.setHorizontalHeaderLabels(['Étape','Motif'])
        self.steps.setColumnWidth(0,230);self.steps.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        self.steps.setMinimumHeight(180);self.steps.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.form.addRow(self.steps)
        self.open_button=QPushButton('Ouvrir l’étape sélectionnée');self.open_button.setEnabled(False);self.open_button.clicked.connect(self.open_step)
        self.form.addRow(self.open_button);self.layout.addStretch()
    def add_files(self):
        paths=QFileDialog.getOpenFileNames(self,'Données géographiques',filter='Données SIG (*.tif *.tiff *.jp2 *.vrt *.img *.gpkg *.shp *.geojson)')[0]
        self.inputs.addItems(paths)
    def add_folder(self):
        path=QFileDialog.getExistingDirectory(self,'Scènes satellites')
        if path:self.inputs.addItem(path);self.kind.setCurrentIndex(1)
    def job(self,options):
        inputs=[self.inputs.item(i).text() for i in range(self.inputs.count())]
        goal=self.goal.currentData();kind=self.kind.currentData();aoi=self.aoi.text() or None
        destination=self.directory/'assessment.json'
        def run(progress,cancel):
            from .desktop_tools import write_result
            report=assess_project(inputs,goal=goal,data_kind=kind,aoi=aoi,progress=progress,cancel=cancel)
            return write_result(report,destination,overwrite=True,sources=inputs)
        return run
    def show_result(self,path):
        self.assessment=json.loads(Path(path).read_text(encoding='utf-8'));report=self.assessment
        prefixes={'error':'À corriger','warning':'À vérifier','info':'Information'}
        messages=[prefixes[i['severity']]+' : '+i['message'] for i in report['issues']]
        self.findings.setText('\n'.join(messages) if messages else 'Les contrôles effectués ne signalent pas d’anomalie. Vérifier les propositions ci-dessous.')
        self.steps.setRowCount(len(report['steps']))
        for row,step in enumerate(report['steps']):
            for col,text in enumerate([step['title'],step['reason']]):
                item=QTableWidgetItem(text);item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable)
                self.steps.setItem(row,col,item)
        self.steps.resizeRowsToContents();self.steps.selectRow(0);self.open_button.setEnabled(bool(report['steps']))
    def open_step(self):
        row=self.steps.currentRow()
        if self.assessment and 0<=row<len(self.assessment['steps']):self.openRequested.emit(self.assessment['steps'][row]['tool'],self.assessment)
