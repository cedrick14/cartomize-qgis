"""Explicit, metadata-preserving transfers between desktop tools."""
import json
from pathlib import Path
import rasterio
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGroupBox,QHBoxLayout,QComboBox,QPushButton,QDialog,QVBoxLayout,QPlainTextEdit

RASTERS={'.tif','.tiff','.jp2','.vrt','.img'}
VECTORS={'.gpkg','.shp','.geojson'}


class ProjectConnections:
    def tool(self,key):return self.tool_pages[key]
    def select_tool(self,key):self.navigation.setCurrentRow(self.pages.index(self.tool(key)))
    def init_results(self,outer):
        self.results=[];self.results_box=QGroupBox('Résultats du projet');row=QHBoxLayout(self.results_box)
        self.result_choice=QComboBox();self.result_choice.setMinimumContentsLength(25)
        self.result_target=QComboBox();self.transfer_button=QPushButton('Transmettre au traitement')
        row.addWidget(self.result_choice,1);row.addWidget(self.result_target);row.addWidget(self.transfer_button)
        self.production_config=None;self.resume_button=QPushButton('Reprendre la mise en page');self.resume_button.hide()
        self.resume_button.clicked.connect(self.resume_production);row.addWidget(self.resume_button)
        self.result_choice.currentIndexChanged.connect(self.result_targets)
        self.transfer_button.clicked.connect(self.transfer_selected);outer.addWidget(self.results_box);self.results_box.hide()
    def register_result(self,layer):
        layer=dict(layer);path=str(Path(layer['data']).resolve());layer['data']=path
        suffix=Path(path).suffix.lower()
        if suffix not in RASTERS|VECTORS:return
        layer.setdefault('kind','raster' if suffix in RASTERS else 'vector')
        # Refresh existing results, including edited class labels.
        for index,old in enumerate(self.results):
            if old['data']==path:self.results[index]={**old,**layer};self.result_choice.setCurrentIndex(index);self.result_targets();return
        self.results.append(layer);self.result_choice.addItem(Path(path).name)
        self.result_choice.setItemData(len(self.results)-1,path,Qt.ItemDataRole.ToolTipRole)
        self.result_choice.setCurrentIndex(len(self.results)-1);self.results_box.show()
    def result_targets(self):
        self.result_target.clear();index=self.result_choice.currentIndex()
        if not 0<=index<len(self.results):return
        layer=self.results[index];targets=['project','mapping','atlas','inspect']
        if layer['kind']=='vector':targets+=['vector']
        else:
            targets+=['raster','calculator','focal','temporal','terrain']
            with rasterio.open(layer['data']) as src:
                if src.tags().get('CARTOMIZE_PRODUCT')!='display_rgba':
                    targets+=['indices','classification']
                    if src.count>=3:targets+=['composite']
        from .assistant import TOOL_LABELS
        for key in targets:self.result_target.addItem(TOOL_LABELS[key],key)
    def transfer_selected(self):
        index=self.result_choice.currentIndex();target=self.result_target.currentData()
        if not 0<=index<len(self.results) or target is None:return
        try:self.transfer_result(self.results[index],target)
        except (ValueError,OSError,rasterio.errors.RasterioError) as exc:self.status.setText(str(exc))
    def transfer_result(self,layer,target):
        page=self.tool(target);path=str(layer['data'])
        if target in {'mapping','atlas'}:page.append_layer(layer)
        elif target=='project':page.add_layer(path)
        elif target=='calculator':page.add_raster(path)
        elif target=='temporal':page.sources.addItem(path)
        else:
            if target=='indices':
                with rasterio.open(path) as src:
                    if src.tags().get('CARTOMIZE_PRODUCT')=='display_rgba':raise ValueError('Utiliser le multibande scientifique pour les indices.')
            page.source.edit.setText(path)
            if target=='inspect':page.kind.setCurrentIndex(page.kind.findData(layer['kind']))
        self.select_tool(target);self.status.setText('Résultat transmis : '+Path(path).name)
    def collect_result(self,path):
        path=Path(path)
        if path.suffix.lower() in RASTERS|VECTORS:
            layer=dict(data=path)
            if path.suffix.lower() in RASTERS:
                with rasterio.open(path) as src:
                    if src.tags().get('CARTOMIZE_CLASSES'):
                        layer.update(kind='raster',role='landcover',classes={float(k):v for k,v in json.loads(src.tags()['CARTOMIZE_CLASSES']).items()})
            if path.name=='classification.tif':
                for key,file in [('report',path.parent/'classification.json'),('model',path.parent/'model/model.json')]:
                    if file.is_file():layer[key]=str(file)
            elif path.name=='clusters.tif' and (path.parent/'clustering.json').is_file():layer['report']=str(path.parent/'clustering.json')
            self.register_result(layer)
            confidence=path.parent/'confidence.tif'
            if path.name=='classification.tif' and confidence.is_file():self.register_result(dict(data=confidence))
        elif path.name=='imagery.json':
            record=json.loads(path.read_text(encoding='utf-8'))
            for product in record['products']:
                if product['multiband']:
                    self.register_result(dict(data=product['multiband'],name='Multibande · '+', '.join(product['scenes'])))
                    self.tool('composite').source.edit.setText(product['multiband'])
                    self.tool('indices').source.edit.setText(product['multiband'])
                if product['composition']:
                    self.register_result(dict(data=product['composition'],rgb='native',role='background',name='Composition colorée · '+', '.join(product['scenes'])))
                for band in product['bands'].values():
                    self.register_result(dict(data=band['path'],name=band['name']))
        elif path.name=='project.json':
            import cartomize as cm
            for layer in cm.load_project(path).layers:self.register_result(layer)
        elif path.name=='automation.json':
            record=json.loads(path.read_text(encoding='utf-8'))
            for layer in record['layers']:self.register_result(layer)
            self.production_config=record.get('map_config');self.resume_button.setVisible(bool(self.production_config))
        elif path.name=='production.json':
            record=json.loads(path.read_text(encoding='utf-8'))
            scientific=path.parent/record['multiband'];display=path.parent/record['composite']
            self.register_result(dict(data=scientific));self.register_result(dict(data=display,rgb='native',role='background',name='Image satellite'))
            self.tool('composite').source.edit.setText(str(scientific));self.tool('indices').source.edit.setText(str(scientific))
            from copy import deepcopy
            config=deepcopy(getattr(self.tool('workflow'),'result_map_config',None))
            if config:
                config['layers'].insert(0,dict(data=str(display),rgb='native',role='background',name='Image satellite'))
                self.production_config=config;self.resume_button.show()
        if path.suffix.lower() in RASTERS and self.pages[self.stack.currentIndex()] is self.tool('prepare'):
            self.tool('composite').source.edit.setText(str(path));self.tool('indices').source.edit.setText(str(path))
    def resume_production(self):
        if self.production_config:
            self.tool('mapping').load_config(self.production_config);self.select_tool('mapping')
            self.status.setText('Production reprise avec les couches, la zone d’étude et l’habillage.')
    def open_assistant_step(self,target,report):
        page=self.tool(target);assistant=self.tool('assistant');paths=report['inputs']
        layers=[dict(r.get('options',{}),data=r['source']) for r in report['layers']]
        if report['data_kind']=='scenes':layers=list(self.results)
        if target=='prepare':
            page.invalidate_inputs()
            if len(paths)==1 and Path(paths[0]).is_dir():
                page.files=[];page.source.setEnabled(True);page.source.edit.setText(paths[0]);page.inventory.setText('Répertoire sélectionné')
            else:
                page.files=list(paths);page.source.setEnabled(False);page.inventory.setText(f'{len(paths)} fichiers sélectionnés')
        elif target=='project':
            existing={page.layers.item(i,0).text() for i in range(page.layers.rowCount())}
            for layer in layers:
                if str(layer['data']) not in existing:page.add_layer(layer['data']);existing.add(str(layer['data']))
        elif target in {'mapping','atlas'}:
            # Explicit result transfers take precedence over original sources.
            if page.layers.rowCount()==0:page.load_layers(layers)
            page.title.setText(assistant.title.text())
            recommendation=report.get('recommended_template')
            if recommendation:page.layout_settings.template.setCurrentIndex(page.layout_settings.template.findData(recommendation['id']))
        elif target in {'vector','raster','composite','inspect','classification'} and not page.source.text():
            wanted='vector' if target=='vector' else 'raster'
            for layer in layers:
                suffix=Path(layer['data']).suffix.lower()
                if (suffix in RASTERS)==(wanted=='raster'):
                    if target in {'composite','classification'}:
                        with rasterio.open(layer['data']) as src:
                            if src.count<3:continue
                    page.source.edit.setText(str(layer['data']));break
            if target=='vector' and any(i['code']=='invalid_geometry' for i in report['issues']):
                page.operation.setCurrentIndex(page.operation.findData('make_valid'))
        if target=='classification':page.training.edit.setText(assistant.training.text());page.column.setText(assistant.class_column.text())
        if hasattr(page,'aoi'):page.aoi.edit.setText(report.get('aoi') or '')
        self.select_tool(target)
    def prepare_atlas(self,config):
        self.tool('atlas').load_config(config);self.tool('atlas').dpi.setValue(self.tool('mapping').dpi.value())
        self.select_tool('atlas');self.status.setText('Couches et habillage transmis. Renseigner la couche d’index et le nom des pages.')
    def show_review(self,path):
        report=json.loads(Path(path).read_text(encoding='utf-8'))
        dialog=QDialog(self);dialog.setWindowTitle('Contrôle cartographique');dialog.resize(780,460)
        from PySide6.QtCore import Qt
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose);layout=QVBoxLayout(dialog);view=QPlainTextEdit();view.setReadOnly(True)
        labels={'error':'À corriger','warning':'À vérifier','info':'Information'}
        lines=['Contrôles techniques : '+('aucune erreur bloquante.' if report['valid'] else 'corrections nécessaires.')]
        lines += [labels[i['severity']]+' — '+((i.get('layer') or '')+' : ' if i.get('layer') else '')+i['message'] for i in report['issues']]
        lines += ['','Le contrôle des rasters repose sur un échantillon. Vérifier aussi l’exactitude thématique, les étiquettes et la lisibilité de l’export.']
        view.setPlainText('\n'.join(lines));layout.addWidget(view);dialog.show();self.review_dialog=dialog
        self.status.setText('Contrôle cartographique terminé.');self.folder_button.setEnabled(True)
