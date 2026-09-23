"""Persist every tool's editable state, tables, choices and result references."""
from copy import deepcopy
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QLineEdit,QPlainTextEdit,QCheckBox,QComboBox,QSpinBox,QDoubleSpinBox,
    QListWidget,QListWidgetItem,QTableWidget,QTableWidgetItem,QTabWidget,QPushButton,QFileDialog,QMessageBox)
from .session import save_session,load_session
from .storage import json_value


def widget_state(widget):
    if type(widget).__name__=='ExecutionSettings':return dict(type='execution',widgets=capture_widgets(widget))
    if type(widget).__name__=='ProcessingSteps':return dict(type='processing_steps',records=widget.records())
    if hasattr(widget,'edit') and hasattr(widget,'mode'):
        text=widget.edit.text()
        if text and Path(text).exists():text=str(Path(text).resolve())
        return dict(type='path',text=text,mode=widget.mode,filter=widget.filter)
    if isinstance(widget,QLineEdit):return dict(type='line',text=widget.text())
    if isinstance(widget,QPlainTextEdit):return dict(type='plain',text=widget.toPlainText())
    if isinstance(widget,QCheckBox):return dict(type='check',checked=widget.isChecked())
    if isinstance(widget,QComboBox):return dict(type='combo',index=widget.currentIndex(),items=[[widget.itemText(i),widget.itemData(i)] for i in range(widget.count())])
    if isinstance(widget,(QSpinBox,QDoubleSpinBox)):
        return dict(type='real' if isinstance(widget,QDoubleSpinBox) else 'spin',value=widget.value(),minimum=widget.minimum(),maximum=widget.maximum(),suffix=widget.suffix(),special=widget.specialValueText())
    if isinstance(widget,QTableWidget):
        rows=[]
        for r in range(widget.rowCount()):
            cells=[]
            for c in range(widget.columnCount()):
                cell=widget.cellWidget(r,c);item=widget.item(r,c)
                cells.append({'widget':widget_state(cell)} if cell else {'text':item.text(),'data':item.data(Qt.ItemDataRole.UserRole),'flags':item.flags().value} if item else None)
            rows.append(cells)
        return dict(type='table',columns=widget.columnCount(),rows=rows)
    if isinstance(widget,QListWidget):
        return dict(type='list',items=[dict(text=widget.item(i).text(),data=widget.item(i).data(Qt.ItemDataRole.UserRole),
            check=widget.item(i).checkState().value,flags=widget.item(i).flags().value) for i in range(widget.count())])
    if isinstance(widget,QTabWidget):return dict(type='tabs',index=widget.currentIndex())
    if type(widget).__name__=='LayoutSettings':return dict(type='layout',widgets=capture_widgets(widget))
    return None


def capture_widgets(page):
    result={}
    for name,value in vars(page).items():
        if name.startswith('_'):continue
        state=widget_state(value)
        if state is not None:result[name]=state
    return result


def restore_widget(widget,state):
    kind=state['type']
    if kind=='execution':restore_widgets(widget,state['widgets'])
    elif kind=='processing_steps':widget.set_records(state['records'])
    elif kind=='path':widget.edit.setText(state['text']);widget.mode=state['mode'];widget.filter=state['filter']
    elif kind=='line':widget.setText(state['text'])
    elif kind=='plain':widget.setPlainText(state['text'])
    elif kind=='check':widget.setChecked(state['checked'])
    elif kind=='combo':
        widget.blockSignals(True);widget.clear()
        for label,data in state['items']:widget.addItem(label,data)
        widget.blockSignals(False);widget.setCurrentIndex(state['index'])
    elif kind in {'spin','real'}:
        widget.setRange(state['minimum'],state['maximum']);widget.setValue(state['value']);widget.setSuffix(state['suffix']);widget.setSpecialValueText(state['special'])
    elif kind=='table':
        widget.setRowCount(0);widget.setColumnCount(state['columns']);widget.setRowCount(len(state['rows']))
        types={'combo':QComboBox,'spin':QSpinBox,'real':QDoubleSpinBox,'line':QLineEdit,'check':QCheckBox}
        for r,row in enumerate(state['rows']):
            for c,cell in enumerate(row):
                if cell is None:continue
                if 'widget' in cell:
                    setting=cell['widget'];control=types[setting['type']]()
                    if isinstance(control,QDoubleSpinBox):control.setDecimals(8)
                    restore_widget(control,setting);widget.setCellWidget(r,c,control)
                else:
                    item=QTableWidgetItem(cell['text']);item.setData(Qt.ItemDataRole.UserRole,cell['data']);item.setFlags(Qt.ItemFlag(cell['flags']));widget.setItem(r,c,item)
    elif kind=='list':
        widget.blockSignals(True);widget.clear()
        for record in state['items']:
            item=QListWidgetItem(record['text']);item.setFlags(Qt.ItemFlag(record['flags']));item.setData(Qt.ItemDataRole.UserRole,record['data']);item.setCheckState(Qt.CheckState(record['check']));widget.addItem(item)
        widget.blockSignals(False)
    elif kind=='tabs':widget.setCurrentIndex(state['index'])
    elif kind=='layout':restore_widgets(widget,state['widgets'])


def restore_widgets(page,states):
    for name,state in states.items():
        if hasattr(page,name):restore_widget(getattr(page,name),state)


class SessionControls:
    def init_session(self,header):
        self.session_path=None;self.history=[];self.history_index=-1;self._restoring=False
        for text,callback in [('Ouvrir',self.open_session_dialog),('Enregistrer',self.save_session_dialog),('Projet portable',self.pack_session_dialog),('Annuler une action',self.undo_session),('Rétablir',self.redo_session)]:
            button=QPushButton(text);button.clicked.connect(callback);header.addWidget(button)
    def capture_session(self):
        pages={}
        for key,page in self.tool_pages.items():
            extras={}
            for name in ('files','_analysis_overrides','_band_source','assessment','execution_plan','result_map_config','inventory'):
                if hasattr(page,name) and isinstance(getattr(page,name),(dict,list,str,type(None))):extras[name]=getattr(page,name)
            if getattr(page,'project',None) is not None and hasattr(page.project,'manifest'):extras['project_manifest']=str(page.project.manifest)
            pages[key]=dict(widgets=capture_widgets(page),extras=extras)
        return json_value(dict(schema='cartomize.desktop.v1',pages=pages,selected=next(k for k,v in self.tool_pages.items() if v is self.pages[self.stack.currentIndex()]),
            results=self.results,production_config=self.production_config,processing={k:widget_state(getattr(self,k)) for k in ('workers','block_size','memory','overwrite','execution_settings')},
            input_directories=[str(Path(page.source.text()).resolve()) for page in self.pages if hasattr(page,'source') and getattr(page.source,'mode',None)=='directory' and page.source.text() and Path(page.source.text()).is_dir()]))
    def restore_session(self,state):
        if state.get('schema')!='cartomize.desktop.v1':raise ValueError('Le document ne contient pas une session de la fenêtre.')
        self._restoring=True
        try:
            for key,record in state['pages'].items():
                if key not in self.tool_pages:continue
                page=self.tool(key);restore_widgets(page,record['widgets'])
                for name,value in record['extras'].items():
                    if name=='project_manifest':
                        if Path(value).is_file():
                            from .project import load_project
                            page.project=load_project(value);page.apply_button.setEnabled(True);page.restore_button.setEnabled(True)
                    elif name=='_analysis_overrides':
                        for layer in value.values():
                            if layer.get('classes') and layer.get('kind')=='raster':layer['classes']={float(k):v for k,v in layer['classes'].items()}
                        setattr(page,name,value)
                    else:setattr(page,name,value)
                if key=='native':page.import_button.setEnabled(bool(page.inventory))
                if key=='assistant':page.open_button.setEnabled(bool(page.assessment));page.execute_button.setEnabled(bool(page.execution_plan))
                if hasattr(page,'files'):
                    page.source.setEnabled(not page.files);page.inventory.setText(f'{len(page.files)} fichiers sélectionnés' if page.files else 'Répertoire des scènes')
                if hasattr(page,'restore_controls'):page.restore_controls()
            self.results=[];self.result_choice.clear()
            for layer in state.get('results',[]):
                if layer.get('classes') and layer.get('kind')=='raster':layer['classes']={float(k):v for k,v in layer['classes'].items()}
                if Path(layer['data']).is_file():self.register_result(layer)
            self.results_box.setVisible(bool(self.results));self.production_config=state.get('production_config');self.resume_button.setVisible(bool(self.production_config))
            for key,value in state.get('processing',{}).items():restore_widget(getattr(self,key),value)
            self.select_tool(state.get('selected','assistant'))
        finally:self._restoring=False
    def checkpoint(self):
        if self._restoring:return
        state=self.capture_session()
        if self.history_index>=0 and self.history[self.history_index]==state:return
        self.history=self.history[:self.history_index+1]+[deepcopy(state)];self.history=self.history[-20:];self.history_index=len(self.history)-1
    def undo_session(self):
        if self.thread is not None:return
        self.checkpoint()
        if self.history_index>0:self.history_index-=1;self.restore_session(deepcopy(self.history[self.history_index]));self.status.setText('État précédent rétabli ; fichiers produits conservés.')
    def redo_session(self):
        if self.thread is not None:return
        if self.history_index<len(self.history)-1:self.history_index+=1;self.restore_session(deepcopy(self.history[self.history_index]));self.status.setText('État suivant rétabli.')
    def save_session_file(self,path,*,portable=False):
        if self.thread is not None:raise ValueError('Attendre la fin du traitement avant d’enregistrer le projet.')
        self.checkpoint();result=save_session(self.capture_session(),path,portable=portable,overwrite=True)
        if not portable:self.session_path=str(result)
        self.status.setText('Projet enregistré : '+str(result));return result
    def open_session_file(self,path,*,relocate=None):
        if self.thread is not None:raise ValueError('Attendre la fin du traitement avant d’ouvrir un projet.')
        loaded=load_session(path,relocate=relocate)
        if loaded.missing:raise FileNotFoundError('Sources à relocaliser : '+', '.join(loaded.missing))
        self.checkpoint();self.restore_session(loaded.state);self.checkpoint();self.session_path=str(path)
        self.status.setText('Projet ouvert : '+str(path));return loaded
    def save_session_dialog(self):
        path=self.session_path or QFileDialog.getSaveFileName(self,'Enregistrer le projet',filter='Projet Cartomize (*.cartomize.json)')[0]
        if path:
            try:self.save_session_file(path)
            except Exception as exc:QMessageBox.warning(self,'Enregistrement du projet',str(exc))
    def pack_session_dialog(self):
        path=QFileDialog.getSaveFileName(self,'Projet portable avec données',filter='Archive Cartomize (*.cmz)')[0]
        if path:
            try:self.save_session_file(path,portable=True)
            except Exception as exc:QMessageBox.warning(self,'Projet portable',str(exc))
    def open_session_dialog(self):
        path=QFileDialog.getOpenFileName(self,'Ouvrir le projet',filter='Projet Cartomize (*.cartomize.json *.cmz)')[0]
        if path:
            try:self.open_session_file(path)
            except Exception as exc:QMessageBox.warning(self,'Ouverture du projet',str(exc))
