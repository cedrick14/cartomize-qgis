"""Form-based construction of named processing dependencies."""
import json
from copy import deepcopy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QDialog,QDialogButtonBox,
    QComboBox,QLineEdit,QCheckBox,QPushButton,QLabel,QTableWidget,QTableWidgetItem,QFileDialog,
    QMessageBox,QScrollArea)
from .processing import operation_catalog,operation_spec,validate_parameters


LABELS={'data':'Couche source','source':'Raster ou couche source','left':'Couche principale','right':'Couche secondaire',
        'mask':'Masque de découpage','sources':'Rasters sources (liste JSON)','inputs':'Variables et rasters (objet JSON)',
        'expression':'Expression raster','crs':'Système de coordonnées cible','metric_crs':'Système de coordonnées projeté',
        'distance':'Distance (m)','band':'Bande','by':'Champ de regroupement','column':'Champ',
        'products':'Dérivées du terrain (liste JSON)','kernel':'Matrice de convolution (JSON)',
        'mapping':'Correspondance des classes (objet JSON)','zones':'Couche des zones','before':'Raster initial',
        'after':'Raster final','training':'Échantillons de référence','class_column':'Champ des classes','indices':'Indices (liste JSON)',
        'border_values':'Valeurs périphériques à masquer (liste JSON)','keep_values':'Valeurs à conserver (liste JSON)'}
PATHS={'data','source','left','right','mask','zones','before','after','training','validation','model','valid_footprint','outlets'}
COMPLEX={'inputs','sources','kernel','mapping','products','indices','border_values','nodata_values','keep_values','classes','band_map','bands','predictors','rgb','start','end','bbox','collections','assets','band_order'}


class OperationDialog(QDialog):
    def __init__(self,steps,record=None,parent=None,*,allow_map=True):
        super().__init__(parent);self.setWindowTitle('Étape de traitement');self.resize(620,620)
        self.previous=steps;self.record=record;self.allow_map=allow_map;layout=QVBoxLayout(self);form=QFormLayout()
        self.ident=QLineEdit(record['id'] if record else f'process_{len(steps)+1:02d}')
        self.operation=QComboBox()
        for spec in operation_catalog():self.operation.addItem(spec['label'],spec['id'])
        form.addRow('Identifiant du résultat',self.ident);form.addRow('Opération',self.operation);layout.addLayout(form)
        scroll=QScrollArea();scroll.setWidgetResizable(True);self.fields=QWidget();self.form=QFormLayout(self.fields);scroll.setWidget(self.fields);layout.addWidget(scroll)
        self.product=QComboBox();product_label=QLabel('Produit cartographique');layout.addWidget(product_label);layout.addWidget(self.product)
        self.add_map=QCheckBox('Ajouter le résultat à la carte');self.add_map.setChecked(record is not None and record.get('map_layer') is not None);layout.addWidget(self.add_map)
        for widget in (product_label,self.product,self.add_map):widget.setVisible(allow_map)
        note=QLabel('Choisir un fichier ou le résultat d’une étape précédente. Les identifiants précédés de @ désignent des résultats intermédiaires.');note.setWordWrap(True);layout.addWidget(note)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self.operation.currentIndexChanged.connect(self.changed)
        if record:self.operation.setCurrentIndex(self.operation.findData(record['operation']))
        self.changed()
        if record:
            self.product.setCurrentIndex(max(0,self.product.findText((record.get('map_layer') or {}).get('product','primary'))))
            for name,value in record['parameters'].items():
                if name in self.controls:
                    widget=self.controls[name]
                    if isinstance(widget,QCheckBox):widget.setChecked(bool(value))
                    else:widget.setCurrentText(json.dumps(value,ensure_ascii=False) if isinstance(value,(dict,list,tuple)) else str(value))
    def changed(self):
        while self.form.rowCount():self.form.removeRow(0)
        self.controls={};spec=operation_spec(self.operation.currentData())
        self.add_map.setEnabled(self.allow_map and spec['output'] in {'raster','vector'});self.product.clear();self.product.addItems(spec['products'])
        for field in spec['parameters']:
            name=field['name'];default=field['default'];label=LABELS.get(name,name.replace('_',' '))+(' *' if field['required'] else '')
            if isinstance(default,bool):widget=QCheckBox();widget.setChecked(default);row=widget
            else:
                widget=QComboBox();widget.setEditable(True);widget.setMinimumWidth(270)
                if name in PATHS:
                    widget.addItem('');widget.addItem('@scientific')
                    for step in self.previous:
                        widget.addItem('@'+step['id'])
                        for product in operation_spec(step['operation'])['products'][1:]:widget.addItem('@'+step['id']+':'+product)
                text=json.dumps(default,ensure_ascii=False) if isinstance(default,(list,tuple,dict)) else str(default) if default is not None else ''
                widget.setCurrentText(text);row=widget
                if name in PATHS:
                    row=QWidget();line=QHBoxLayout(row);line.setContentsMargins(0,0,0,0);line.addWidget(widget)
                    button=QPushButton('Parcourir');line.addWidget(button)
                    button.clicked.connect(lambda checked=False,w=widget:self.browse(w))
            self.controls[name]=widget;self.form.addRow(label,row)
    def browse(self,widget):
        path=QFileDialog.getOpenFileName(self,'Donnée source')[0]
        if path:widget.setCurrentText(path)
    def value(self):
        parameters={};spec=operation_spec(self.operation.currentData())
        for field in spec['parameters']:
            name=field['name'];widget=self.controls[name]
            if isinstance(widget,QCheckBox):value=widget.isChecked()
            else:
                text=widget.currentText().strip()
                if not text:
                    if field['required']:raise ValueError('Renseigner '+LABELS.get(name,name))
                    continue
                default=field['default']
                if name in PATHS:value=text
                elif name in COMPLEX or isinstance(default,(list,tuple,dict)):value=json.loads(text)
                elif isinstance(default,int):value=int(text)
                elif isinstance(default,float):value=float(text)
                else:
                    try:value=json.loads(text)
                    except json.JSONDecodeError:value=text
            parameters[name]=value
        validate_parameters(spec['id'],parameters)
        record=dict(id=self.ident.text().strip(),operation=spec['id'],parameters=parameters)
        if self.add_map.isEnabled() and self.add_map.isChecked():record['map_layer']=deepcopy(self.record.get('map_layer',{})) if self.record else {}
        if record.get('map_layer') is not None:
            record['map_layer'].pop('product',None)
            if self.product.currentText()!='primary':record['map_layer']['product']=self.product.currentText()
        return record
    def accept(self):
        try:
            record=self.value()
            import re
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',record['id']):raise ValueError('Identifiant : lettres, chiffres et soulignement, commençant par une lettre.')
            if record['id'] in {s['id'] for s in self.previous}:raise ValueError('Cet identifiant existe déjà.')
            self.result_record=record
        except (ValueError,TypeError) as exc:QMessageBox.warning(self,'Paramètres',str(exc));return
        super().accept()


class ProcessingSteps(QWidget):
    def __init__(self,parent=None,*,allow_map=True):
        super().__init__(parent);self.allow_map=allow_map;layout=QVBoxLayout(self)
        self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['Résultat','Opération','Ajouter à la carte']);self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);self.table.setMinimumHeight(170);layout.addWidget(self.table)
        self.table.setColumnHidden(2,not allow_map)
        row=QHBoxLayout();layout.addLayout(row)
        for text,fn in [('Ajouter',self.add),('Modifier',self.edit),('Monter',lambda:self.move(-1)),('Descendre',lambda:self.move(1)),('Retirer',self.remove)]:
            button=QPushButton(text);button.clicked.connect(fn);row.addWidget(button)
    def records(self):return [deepcopy(self.table.item(r,0).data(Qt.ItemDataRole.UserRole)) for r in range(self.table.rowCount())]
    def set_records(self,records):
        self.table.setRowCount(0)
        for record in records:
            row=self.table.rowCount();self.table.insertRow(row)
            for col,text in enumerate([record['id'],operation_spec(record['operation'])['label'],'Oui' if record.get('map_layer') is not None else 'Non']):
                item=QTableWidgetItem(text);item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable)
                if col==0:item.setData(Qt.ItemDataRole.UserRole,deepcopy(record))
                self.table.setItem(row,col,item)
        self.table.resizeColumnsToContents()
    def add(self):
        records=self.records();dialog=OperationDialog(records,parent=self,allow_map=self.allow_map)
        if dialog.exec():self.set_records(records+[dialog.result_record])
    def edit(self):
        row=self.table.currentRow();records=self.records()
        if row<0:return
        dialog=OperationDialog(records[:row],records[row],self,allow_map=self.allow_map)
        if dialog.exec():records[row]=dialog.result_record;self.set_records(records)
    def move(self,offset):
        row=self.table.currentRow();records=self.records();other=row+offset
        if row>=0 and 0<=other<len(records):records[row],records[other]=records[other],records[row];self.set_records(records);self.table.selectRow(other)
    def remove(self):
        row=self.table.currentRow()
        if row>=0:self.table.removeRow(row)



from .desktop import Page,PathField
class ProcessingPage(Page):
    engine=True
    staged=True
    def __init__(self):
        super().__init__('Chaîne de traitements','Définir les opérations et leurs dépendances, puis exécuter l’ensemble dans un nouveau dossier.')
        self.processing_steps=ProcessingSteps(allow_map=False);self.form.addRow(self.processing_steps)
        self.output.mode='directory';self.name=QLineEdit('traitements');self.form.addRow('Répertoire parent',self.output);self.form.addRow('Nouveau dossier',self.name);self.layout.addStretch()
    def job(self,options):
        from .automation import processing_plan,run_plan
        from pathlib import Path
        from .recipes import safe_name
        plan=processing_plan(self.processing_steps.records());destination=Path(self.destination())/safe_name(self.name.text())
        engine={k:options[k] for k in ('execution','device','scheduler_address') if k in options}
        return lambda progress,cancel,stage:run_plan(plan,destination,workers=options.get('workers',1),block_size=options.get('block_size',512),memory_limit_mb=options.get('memory_limit_mb',512),progress=progress,cancel=cancel,stage=stage,**engine)
