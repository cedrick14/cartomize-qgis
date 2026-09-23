"""Exercise editable treatment chains and their real Qt worker execution."""
import json
import time
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
import pytest
import rasterio
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication,QComboBox
from PySide6.QtCore import QTimer,QEventLoop


@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])


def wait(window):
    loop=QEventLoop();timer=QTimer();deadline=time.monotonic()+40
    timer.timeout.connect(lambda:loop.quit() if window.thread is None or time.monotonic()>deadline else None)
    timer.start(10);loop.exec();timer.stop()
    assert window.thread is None
    assert window.status.text().startswith('Traitement terminé'),window.status.text()


def test_chain_page_worker_and_session(app,write_raster,tmp_path):
    from cartomize.desktop import CartomizeWindow
    source=write_raster('source.tif',np.full((40,40),2,dtype='float32'))
    window=CartomizeWindow();window.select_tool('processing');page=window.tool('processing')
    assert page.processing_steps.table.isColumnHidden(2)
    records=[dict(id='algebra',operation='calculate',parameters={'inputs':{'a':[str(source),1]},'expression':'a * 3'}),
             dict(id='smooth',operation='focal',parameters={'source':'@algebra','statistic':'mean','size':3})]
    page.processing_steps.set_records(records);page.output.edit.setText(str(tmp_path));page.name.setText('chain')
    snapshot=window.capture_session();page.processing_steps.set_records([]);window.restore_session(snapshot)
    assert page.processing_steps.records()==records
    window.start();wait(window)
    report=json.loads((tmp_path/'chain/automation.json').read_text())
    with rasterio.open(report['results']['smooth']) as src:np.testing.assert_allclose(src.read(1,masked=True).compressed(),6)
    window.close()


def test_assistant_custom_steps_survive_plan_and_worker(app,write_raster,tmp_path):
    from cartomize.desktop import CartomizeWindow
    source=write_raster('dem.tif',np.tile(np.arange(40,dtype='float32'),(40,1))*10)
    window=CartomizeWindow();page=window.tool('assistant');page.inputs.addItem(str(source));page.title.setText('Relief');page.credits.setText('Test')
    page.processing_steps.set_records([dict(id='terrain',operation='terrain',parameters={'source':str(source),'products':['slope']},map_layer={'name':'Pente','legend':False})])
    page.output.edit.setText(str(tmp_path));page.name.setText('assistant')
    window.start(proposal=True);wait(window)
    assert any(n['operation']=='process' for n in page.execution_plan['nodes'])
    window.start(execute_plan=True);wait(window)
    assert (tmp_path/'assistant/carte.pdf').is_file()
    window.close()


def test_operation_editor_typed_fields_and_native_directory(app,write_raster,tmp_path):
    from cartomize.desktop_processing import OperationDialog
    from cartomize.desktop_native import NativePage
    source=write_raster('dem.tif',np.ones((10,10),dtype='float32'))
    record=dict(id='hillshade',operation='terrain',parameters={'source':str(source),'products':['hillshade'],'azimuth':135.},map_layer={})
    editor=OperationDialog([],record)
    assert editor.value()['parameters']['products']==['hillshade'] and editor.value()['parameters']['azimuth']==135.
    assert editor.value()['map_layer']=={}
    editor.close()
    editor=OperationDialog([],dict(id='drainage',operation='hydrology',parameters={'source':str(source)},map_layer={'product':'watersheds'}))
    assert editor.value()['map_layer']['product']=='watersheds'
    editor.product.setCurrentText('primary');assert 'product' not in editor.value()['map_layer']
    editor.close()
    editor=OperationDialog([],record,allow_map=False)
    assert not editor.add_map.isEnabled() and 'map_layer' not in editor.value()
    editor.close()
    native=NativePage(tmp_path);native.action.setCurrentIndex(native.action.findData('import'));assert native.output.mode=='directory'
    native.action.setCurrentIndex(native.action.findData('export'));assert native.output.mode=='save'
    native.close()
