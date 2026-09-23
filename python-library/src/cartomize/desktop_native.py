"""Inventory and native exports of existing GIS projects."""
from pathlib import Path
import json
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox,QLineEdit,QPlainTextEdit,QPushButton
from .desktop import Page,PathField,spin


class NativePage(Page):
    engine=False
    layersRequested=Signal(object)
    def __init__(self,directory):
        super().__init__('Projets SIG','Inventorier les couches, ouvrir leurs sources et conserver le rendu natif avec le Python du moteur SIG installé.')
        self.directory=Path(directory);self.source=PathField(filter='Projets SIG (*.qgs *.qgz *.aprx)');self.python=PathField(filter='Python SIG (*)')
        self.action=QComboBox()
        for label,value in [('Inventaire du projet','inspect'),('Exporter une mise en page','export'),('Enregistrer une copie du projet','copy'),('Importer les couches et les styles','import')]:self.action.addItem(label,value)
        self.action.addItem('Valider le moteur natif','validate')
        self.import_name=QLineEdit('projet_importe');self.form.addRow('Dossier du projet importé',self.import_name)
        self.layout_name=QLineEdit();self.template=PathField(filter='Maquette native (*.qpt *.pagx)');self.texts=QPlainTextEdit('{}');self.extents=QPlainTextEdit('{}')
        self.texts.setMaximumHeight(65);self.extents.setMaximumHeight(65);self.dpi=spin(150,72,1200);self.output.filter='Fichiers SIG (*.pdf *.png *.svg *.qpt *.pagx *.qgs *.qgz *.aprx)'
        for label,widget in [('Projet',self.source),('Interpréteur Python SIG',self.python),('Opération',self.action),('Nom de la mise en page',self.layout_name),('Maquette à importer',self.template),('Textes par identifiant (JSON)',self.texts),('Emprises par cadre (JSON)',self.extents),('Résolution (ppp)',self.dpi)]:self.form.addRow(label,widget)
        self.report=QPlainTextEdit();self.report.setReadOnly(True);self.form.addRow(self.report)
        self.import_button=QPushButton('Transmettre les sources locales à la mise en page');self.import_button.setEnabled(False);self.import_button.clicked.connect(self.import_layers);self.form.addRow(self.import_button)
        self.inventory=None;self.finish()
        self.action.currentIndexChanged.connect(lambda:self.configure_destination())
    def configure_destination(self):
        self.output.mode='directory' if self.action.currentData() in {'import','validate'} else 'save'
    def job(self,options):
        from .native import native_project
        from .storage import save_json
        action=self.action.currentData();kwargs=dict(project=self.source.text(),python=self.python.text() or None,action=action,destination=self.destination() if action!='inspect' else None,layout=self.layout_name.text() or None,template=self.template.text() or None,texts=json.loads(self.texts.toPlainText()),extents=json.loads(self.extents.toPlainText()),dpi=self.dpi.value())
        if action in {'import','validate'}:
            from .recipes import safe_name
            kwargs['destination']=Path(kwargs['destination'])/safe_name(self.import_name.text())
        if action=='validate':
            from .native import validate_native_runtime
            if not kwargs['python']:raise ValueError('Sélectionner le Python du moteur SIG installé.')
            return lambda progress,cancel:validate_native_runtime(kwargs['project'],kwargs['destination'],python=kwargs['python'],layout=kwargs['layout'],cancel=cancel)
        path=self.directory/'native-inventory.json'
        def run(progress,cancel):return save_json(native_project(**kwargs,cancel=cancel),path,overwrite=True)
        return run
    def show_result(self,path):
        self.inventory=json.loads(Path(path).read_text(encoding='utf-8'));self.report.setPlainText(json.dumps(self.inventory,ensure_ascii=False,indent=2));self.import_button.setEnabled(bool(self.inventory.get('layers')))
    def import_layers(self):
        layers=[];unavailable=[]
        for item in (self.inventory or {}).get('layers',[]):
            source=item.get('source');provider_options=item.get('provider_options')
            if source and not provider_options and Path(source).is_file() and item.get('visible',True) and Path(source).suffix.lower() in {'.tif','.tiff','.jp2','.vrt','.img','.gpkg','.shp','.geojson'}:layers.append(dict(data=source,name=item['name'],**item.get('options',{})))
            elif item.get('visible',True):unavailable.append(item['name'])
        if layers:self.layersRequested.emit(layers)
        if unavailable:self.report.appendPlainText('Sources à ouvrir dans le moteur natif (service, sous-couche ou format non pris en charge) : '+', '.join(unavailable))
