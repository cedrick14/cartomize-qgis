"""Cartographer's starting point: inspect data, explain and open next steps."""
import json
from pathlib import Path
from PySide6.QtCore import Signal,Qt
from PySide6.QtWidgets import (QWidget,QHBoxLayout,QComboBox,QListWidget,QPushButton,
    QFileDialog,QLineEdit,QLabel,QTableWidget,QTableWidgetItem,QHeaderView,QCheckBox,QPlainTextEdit,QTabWidget,QFormLayout)
from .desktop import Page,PathField,VECTOR_FILTER,spin
from .assistant import assess_project,GOALS


class AssistantPage(Page):
    engine=False
    openRequested=Signal(str,object)
    planRequested=Signal()
    executeRequested=Signal()
    def __init__(self,directory):
        super().__init__('Assistant cartographique','Définir la carte, examiner les données et suivre les étapes adaptées au projet.')
        self.directory=Path(directory);self.assessment=None
        outer_form=self.form;self.tabs=QTabWidget();outer_form.addRow(self.tabs)
        project_tab=QWidget();self.form=QFormLayout(project_tab);self.tabs.addTab(project_tab,'Données')
        processing_tab=QWidget();processing_form=QFormLayout(processing_tab);self.tabs.addTab(processing_tab,'Traitements complémentaires')
        plan_tab=QWidget();plan_form=QFormLayout(plan_tab);self.tabs.addTab(plan_tab,'Plan de traitement')
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
        self.form=plan_form
        self.findings=QLabel('L’examen ne modifie pas les données.');self.findings.setWordWrap(True);self.form.addRow(self.findings)
        self.steps=QTableWidget(0,2);self.steps.setHorizontalHeaderLabels(['Étape','Motif'])
        self.steps.setColumnWidth(0,230);self.steps.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        self.steps.setMinimumHeight(180);self.steps.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.form.addRow(self.steps)
        self.open_button=QPushButton('Ouvrir l’étape sélectionnée');self.open_button.setEnabled(False);self.open_button.clicked.connect(self.open_step)
        self.form.addRow(self.open_button)
        self.form=processing_form
        self.classification=QComboBox()
        for label,value in [('Sans classification',None),('Classification supervisée','supervised'),('Classification non supervisée','unsupervised')]:self.classification.addItem(label,value)
        self.training=PathField(filter=VECTOR_FILTER);self.class_column=QLineEdit('classe');self.indices=QLineEdit();self.credits=QLineEdit()
        self.extra_layers=QPlainTextEdit();self.extra_layers.setPlaceholderText('Un fichier par ligne : routes, limites, localités…');self.extra_layers.setMaximumHeight(70)
        self.atlas_zones=PathField(filter=VECTOR_FILTER);self.atlas_field=QLineEdit();self.dates=QCheckBox('Autoriser une mosaïque multitemporelle');self.clouds=QCheckBox('Appliquer les masques QA/SCL');self.clouds.setChecked(True)
        self.output=PathField('directory');self.name=QLineEdit('production');self.proposals=QComboBox();self.proposals.setMinimumWidth(360);self.execution_plan=None
        for label,widget in [('Couches complémentaires',self.extra_layers),('Classification',self.classification),('Échantillons',self.training),('Champ des classes',self.class_column),('Indices spectraux',self.indices),('Sources et crédits',self.credits),('Index de l’atlas',self.atlas_zones),('Nom des pages',self.atlas_field),('Dates',self.dates),('Qualité des scènes',self.clouds)]:self.form.addRow(label,widget)
        from .desktop_processing import ProcessingSteps
        self.processing_steps=ProcessingSteps();self.tabs.addTab(self.processing_steps,'Chaîne de traitements')
        self.form=outer_form
        self.processing_workers=spin(1,1,32);self.processing_block=spin(512,32,1024);self.processing_memory=spin(512,16,65536)
        for label,widget in [('Travailleurs de calcul',self.processing_workers),('Taille des blocs (pixels)',self.processing_block),('Budget des tableaux (Mo)',self.processing_memory)]:self.form.addRow(label,widget)
        from .desktop_execution import ExecutionSettings
        self.execution_settings=ExecutionSettings();self.form.addRow(self.execution_settings)
        for label,widget in [('Maquette proposée',self.proposals),('Répertoire parent',self.output),('Nom du résultat',self.name)]:self.form.addRow(label,widget)
        controls=QWidget();row=QHBoxLayout(controls)
        self.plan_button=QPushButton('Établir le plan de traitement');self.execute_button=QPushButton('Exécuter le plan');self.execute_button.setEnabled(False)
        row.addWidget(self.plan_button);row.addWidget(self.execute_button);self.form.addRow(controls)
        self.plan_button.clicked.connect(self.planRequested.emit);self.execute_button.clicked.connect(self.executeRequested.emit)
        self.layout.addStretch()
    def add_files(self):
        paths=QFileDialog.getOpenFileNames(self,'Données géographiques',filter='Données SIG (*.tif *.tiff *.jp2 *.vrt *.img *.gpkg *.shp *.geojson *.json)')[0]
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
        document=json.loads(Path(path).read_text(encoding='utf-8'))
        if document.get('schema')=='cartomize.automation.result.v1':
            self.findings.setText('Production achevée. Les couches et la mise en page sont disponibles dans les résultats.');return
        if document.get('schema')=='cartomize.automation.v1':
            self.execution_plan=document;self.proposals.clear()
            for item in document['proposals']:self.proposals.addItem(item['name']+' · '+str(item['score']),item['id'])
            self.execute_button.setEnabled(True)
            from copy import deepcopy
            document=deepcopy(document['assessment']);document['steps']=[]
            operations={'prepare':('prepare','Prétraitement multispectral','Calibrer, masquer, mosaïquer, assembler et extraire les bandes.'),'composite':('composite','Composition colorée','Créer le RVB depuis le multibande scientifique.'),'repair':('vector','Réparation géométrique','Corriger les géométries invalides dans une copie.'),'classify':('classification','Classification supervisée','Apprendre sur les références fournies et produire classes et probabilités.'),'cluster':('classification','Classification non supervisée','Former des groupes spectraux à interpréter.'),'indices':('indices','Indices spectraux','Calculer les indices sélectionnés sur les données scientifiques.'),'project':('project','Analyse du projet','Appliquer les masques et conserver les nomenclatures.'),'relations':('inspect','Relations spatiales','Mesurer intersections et distances entre les couches.'),'map':('mapping','Mise en page','Superposer les couches, renseigner les cadres et exporter.'),'atlas':('atlas','Atlas cartographique','Produire une carte par entité de l’index.')}
            for node in self.execution_plan['nodes']:
                tool,title,reason=operations.get(node['operation'],('assistant','Traitement enregistré','Exécuter les paramètres du plan.'))
                if node['operation']=='process':
                    from .processing import operation_spec
                    spec=operation_spec(node['parameters']['operator']);tool=spec['tool'];title=spec['label'];reason='Résultat : '+node['id']
                document['steps'].append(dict(tool=tool,title=title,reason=reason))
            document['issues']=[i for i in document['issues'] if i['severity']!='info']
            self.tabs.setCurrentIndex(2)
        self.assessment=document;report=self.assessment;self.tabs.setCurrentIndex(2)
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

    def plan_parameters(self):
        return dict(inputs=[self.inputs.item(i).text() for i in range(self.inputs.count())],goal=self.goal.currentData(),data_kind=self.kind.currentData(),aoi=self.aoi.text() or None,title=self.title.text(),credits=self.credits.text(),classification=self.classification.currentData(),training=self.training.text() or None,class_column=self.class_column.text(),indices=[x.strip().upper() for x in self.indices.text().split(',') if x.strip()],layers=[x.strip() for x in self.extra_layers.toPlainText().splitlines() if x.strip()],atlas_zones=self.atlas_zones.text() or None,atlas_field=self.atlas_field.text() or None,allow_mixed_dates=self.dates.isChecked(),processing_steps=self.processing_steps.records(),mask_clouds=self.clouds.isChecked())
    def plan_job(self):
        parameters=self.plan_parameters();destination=self.directory/'plan.json'
        def run(progress,cancel):
            from .automation import plan_cartography
            from .storage import save_json
            from .imagery import _check_cancel
            _check_cancel(cancel);plan=plan_cartography(**parameters);plan['ui_parameters']=parameters;_check_cancel(cancel)
            return save_json(plan,destination,overwrite=True)
        return run
    def execution_job(self,options):
        from copy import deepcopy
        from .automation import run_plan
        from .recipes import safe_name
        if not self.execution_plan:raise ValueError('Établir d’abord le plan de traitement.')
        if self.execution_plan.get('ui_parameters')!=self.plan_parameters():raise ValueError('Les paramètres ont changé : rétablir le plan avant son exécution.')
        plan=deepcopy(self.execution_plan)
        for node in plan['nodes']:
            if node['operation']=='map':node['parameters']['template']=self.proposals.currentData()
        destination=Path(self.destination())/safe_name(self.name.text());workers=self.processing_workers.value();block_size=self.processing_block.value();memory=self.processing_memory.value()
        engine=self.execution_settings.parameters()
        return lambda progress,cancel,stage:run_plan(plan,destination,workers=workers,block_size=block_size,memory_limit_mb=memory,progress=progress,cancel=cancel,stage=stage,**engine)
