"""Supervised classification and spectral clustering controls."""
from pathlib import Path
import json
from PySide6.QtWidgets import QComboBox,QLineEdit,QPlainTextEdit
from .desktop import Page,PathField,spin,VECTOR_FILTER
import cartomize as cm


class ClassificationPage(Page):
    engine=False
    def __init__(self):
        super().__init__('Classification de l’occupation du sol','Apprentissage sur échantillons, prédiction par blocs et validation indépendante. Les groupes spectraux non supervisés doivent être interprétés.')
        self.source=PathField();self.method=QComboBox()
        for label,key in [('Forêt aléatoire','random_forest'),('Arbres extrêmement aléatoires','extra_trees'),('K-moyennes par mini-lots','kmeans'),('Modèle enregistré','model')]:self.method.addItem(label,key)
        self.training=PathField(filter=VECTOR_FILTER);self.validation=PathField(filter=VECTOR_FILTER)
        self.model=PathField(filter='Modèle Cartomize (model.json)');self.column=QLineEdit('classe');self.labels=QLineEdit();self.groups=QLineEdit()
        self.bands=QLineEdit();self.bands.setPlaceholderText('Toutes les bandes, ou numéros séparés par des virgules')
        self.trees=spin(100,10,1000);self.clusters=spin(6,2,64);self.samples=spin(50000,20,2000000);self.depth=spin(24,1,64)
        self.output=PathField('directory');self.name=QLineEdit('classification')
        for label,widget in [('Raster scientifique',self.source),('Méthode',self.method),('Échantillons d’apprentissage',self.training),('Champ des classes',self.column),('Champ des libellés',self.labels),('Groupes de validation',self.groups),('Échantillons de validation',self.validation),('Modèle',self.model),('Bandes',self.bands),('Arbres',self.trees),('Profondeur maximale',self.depth),('Groupes spectraux',self.clusters),('Pixels échantillonnés',self.samples),('Répertoire parent',self.output),('Nom du résultat',self.name)]:self.form.addRow(label,widget)
        self.report=QPlainTextEdit();self.report.setReadOnly(True);self.report.setMaximumHeight(170);self.form.addRow('Validation',self.report)
        self.method.currentIndexChanged.connect(self.changed);self.changed();self.layout.addStretch()
    def changed(self):
        method=self.method.currentData();supervised=method in {'random_forest','extra_trees'}
        for widget in (self.training,self.validation,self.column,self.labels,self.groups,self.trees,self.depth):widget.setEnabled(supervised)
        self.model.setEnabled(method=='model');self.clusters.setEnabled(method=='kmeans');self.samples.setEnabled(method!='model')
    def job(self,options):
        from .recipes import safe_name
        source=self.source.text();destination=Path(self.destination())/safe_name(self.name.text());method=self.method.currentData()
        bands=[int(b.strip()) for b in self.bands.text().split(',')] if self.bands.text().strip() else None
        common=dict(bands=bands,block_size=min(1024,int(options.get('block_size',256))))
        if method=='kmeans':
            common.update(clusters=self.clusters.value(),sample_limit=self.samples.value())
            return lambda progress,cancel:cm.cluster_raster(source,destination,progress=progress,cancel=cancel,**common)
        training=self.training.text() or None
        if method=='model':common['model']=self.model.text()
        else:common.update(algorithm=method,class_column=self.column.text(),label_column=self.labels.text() or None,group_column=self.groups.text() or None,validation=self.validation.text() or None,n_estimators=self.trees.value(),max_depth=self.depth.value(),sample_limit=self.samples.value(),workers=options.get('workers',1))
        return lambda progress,cancel:cm.classify_landcover(source,training,destination,progress=progress,cancel=cancel,**common)
    def show_result(self,path):
        directory=Path(path).parent;report=directory/('clustering.json' if Path(path).name=='clusters.tif' else 'classification.json')
        self.report.setPlainText(json.dumps(json.loads(report.read_text(encoding='utf-8')),ensure_ascii=False,indent=2))
